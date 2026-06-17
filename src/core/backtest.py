"""
백테스트 모듈
- [전략1] 현물-선물 펀딩피 아비트라지
- [전략2] 거래소 간 현물 아비트라지 (Binance vs Bybit 가격 차이)
"""
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from src.core.config import Config
from src.core.logger import setup_logger

logger = setup_logger()

# ──────────────────────────────────────────────
# 공통 결과 구조체
# ──────────────────────────────────────────────
@dataclass
class BacktestResult:
    strategy: str              # "funding" | "arbitrage"
    symbol: str
    exchange: str
    start_date: str
    end_date: str
    total_days: int
    total_gross: float         # 총 수익 (수수료 전)
    total_fee: float
    net_return: float          # 순수익률 (%)
    annual_return: float       # 연환산 (%)
    max_drawdown: float
    sharpe_ratio: float
    opportunity_count: int     # 기회 발생 횟수
    win_rate: float            # 양수 기회 비율 (%)


# ──────────────────────────────────────────────
# 백테스터
# ──────────────────────────────────────────────
class Backtester:
    def __init__(self, config: Config):
        self.config = config

    # ── 공통: ccxt exchange 객체 생성 ──
    def _make_ccxt(self, exchange_name: str, market_type: str):
        import ccxt.async_support as ccxt
        from src.exchanges.base import make_exchange_config

        if exchange_name == "binance":
            key, secret = self.config.BINANCE_API_KEY, self.config.BINANCE_API_SECRET
            ex = ccxt.binance(make_exchange_config(key, secret, {"defaultType": market_type}))
        else:
            key, secret = self.config.BYBIT_API_KEY, self.config.BYBIT_API_SECRET
            ex = ccxt.bybit(make_exchange_config(key, secret, {"defaultType": market_type}))
        return ex

    # ══════════════════════════════════════════
    # 전략 1: 펀딩피 아비트라지 백테스트
    # ══════════════════════════════════════════
    async def fetch_funding_history(self, exchange_name: str, symbol: str, days: int) -> pd.DataFrame:
        market_type = "future" if exchange_name == "binance" else "linear"
        ex = self._make_ccxt(exchange_name, market_type)
        since = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        query_symbol = symbol
        if exchange_name == "bybit" and ":" not in symbol:
            base = symbol.split("/")[1]
            query_symbol = f"{symbol}:{base}"

        records = []
        try:
            await ex.load_markets()
            current = since
            while True:
                batch = await ex.fetch_funding_rate_history(query_symbol, since=current, limit=1000)
                if not batch:
                    break
                records.extend(batch)
                if len(batch) < 1000:
                    break
                current = batch[-1]["timestamp"] + 1
                await asyncio.sleep(0.2)
        except Exception as e:
            logger.error(f"[{exchange_name}] {symbol} 펀딩피 히스토리 오류: {e}")
        finally:
            await ex.close()

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame([{
            "timestamp": r["timestamp"],
            "datetime": r["datetime"],
            "funding_rate": float(r["fundingRate"]) * 100,
        } for r in records])
        return df.sort_values("timestamp").reset_index(drop=True)

    def simulate_funding(self, df: pd.DataFrame, symbol: str, exchange_name: str,
                         fee_pct: float = 0.15, min_rate: float = 0.005) -> BacktestResult | None:
        if df.empty:
            return None

        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        in_position = False
        opp_count = 0
        win_count = 0
        total_fee = fee_pct * 2   # 진입+청산

        for _, row in df.iterrows():
            rate = row["funding_rate"]
            if rate >= min_rate:
                if not in_position:
                    in_position = True
                opp_count += 1
                if rate > 0:
                    win_count += 1
                cumulative += rate
            else:
                in_position = False

            net_now = cumulative - total_fee
            peak = max(peak, net_now)
            max_dd = max(max_dd, peak - net_now)

        net = cumulative - total_fee
        total_days = max((df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]) / (1000 * 86400), 1)
        annual = net / total_days * 365
        rates = df["funding_rate"].values
        sharpe = (np.mean(rates) / np.std(rates) * np.sqrt(3 * 365)) if np.std(rates) > 0 else 0

        return BacktestResult(
            strategy="funding",
            symbol=symbol,
            exchange=exchange_name,
            start_date=df["datetime"].iloc[0][:10],
            end_date=df["datetime"].iloc[-1][:10],
            total_days=int(total_days),
            total_gross=round(cumulative, 4),
            total_fee=round(total_fee, 4),
            net_return=round(net, 4),
            annual_return=round(annual, 2),
            max_drawdown=round(max_dd, 4),
            sharpe_ratio=round(sharpe, 2),
            opportunity_count=opp_count,
            win_rate=round(win_count / opp_count * 100, 1) if opp_count else 0,
        )

    # ══════════════════════════════════════════
    # 전략 2: 거래소 간 아비트라지 백테스트
    # ══════════════════════════════════════════
    async def fetch_ohlcv(self, exchange_name: str, symbol: str, days: int,
                          timeframe: str = "1m") -> pd.DataFrame:
        """1분봉 OHLCV 수집 (close 가격으로 스프레드 계산)"""
        ex = self._make_ccxt(exchange_name, "spot")
        since = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
        records = []
        try:
            await ex.load_markets()
            current = since
            while True:
                batch = await ex.fetch_ohlcv(symbol, timeframe=timeframe, since=current, limit=1000)
                if not batch:
                    break
                records.extend(batch)
                if len(batch) < 1000:
                    break
                current = batch[-1][0] + 60000   # 1분 = 60000ms
                await asyncio.sleep(0.2)
                # 최대 7일치 (데이터 과부하 방지)
                if len(records) >= 7 * 24 * 60:
                    break
        except Exception as e:
            logger.error(f"[{exchange_name}] {symbol} OHLCV 오류: {e}")
        finally:
            await ex.close()

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df.sort_values("timestamp").reset_index(drop=True)

    def simulate_arbitrage(self, df_a: pd.DataFrame, df_b: pd.DataFrame,
                           symbol: str, buy_ex: str, sell_ex: str,
                           fee_pct: float = 0.2,
                           min_spread: float = 0.3) -> BacktestResult | None:
        """
        두 거래소 close 가격 비교 → 스프레드 계산
        buy_ex에서 사서 sell_ex에서 파는 방향
        """
        if df_a.empty or df_b.empty:
            return None

        # timestamp 기준 inner join
        df_a = df_a[["timestamp", "close"]].rename(columns={"close": "price_a"})
        df_b = df_b[["timestamp", "close"]].rename(columns={"close": "price_b"})
        merged = pd.merge(df_a, df_b, on="timestamp", how="inner")
        if merged.empty:
            return None

        # 스프레드: (sell_ex 가격 - buy_ex 가격) / buy_ex 가격 * 100
        merged["spread"] = (merged["price_b"] - merged["price_a"]) / merged["price_a"] * 100
        merged["net"] = merged["spread"] - fee_pct - self.config.ARBITRAGE_FEE_BUFFER

        profitable = merged[merged["net"] > min_spread]
        opp_count = len(profitable)
        win_count = len(profitable[profitable["net"] > 0])

        if opp_count == 0:
            cumulative = 0.0
        else:
            # 각 기회마다 동일 금액 투입 가정, 수익 합산
            cumulative = profitable["net"].sum()

        total_days = max((merged["timestamp"].iloc[-1] - merged["timestamp"].iloc[0]) / (1000 * 86400), 1)
        annual = cumulative / total_days * 365

        spreads = merged["spread"].values
        sharpe = (np.mean(spreads) / np.std(spreads) * np.sqrt(365 * 24 * 60)) if np.std(spreads) > 0 else 0

        # MDD (누적 수익 곡선 기준)
        equity = profitable["net"].cumsum().values
        peak = np.maximum.accumulate(equity) if len(equity) > 0 else np.array([0])
        dd = peak - equity
        max_dd = float(dd.max()) if len(dd) > 0 else 0

        start_dt = merged["timestamp"].iloc[0]
        end_dt = merged["timestamp"].iloc[-1]
        start_str = datetime.fromtimestamp(start_dt / 1000).strftime("%Y-%m-%d")
        end_str = datetime.fromtimestamp(end_dt / 1000).strftime("%Y-%m-%d")

        return BacktestResult(
            strategy="arbitrage",
            symbol=symbol,
            exchange=f"{buy_ex}→{sell_ex}",
            start_date=start_str,
            end_date=end_str,
            total_days=int(total_days),
            total_gross=round(cumulative + fee_pct * opp_count, 4),
            total_fee=round(fee_pct * opp_count, 4),
            net_return=round(cumulative, 4),
            annual_return=round(annual, 2),
            max_drawdown=round(max_dd, 4),
            sharpe_ratio=round(sharpe, 2),
            opportunity_count=opp_count,
            win_rate=round(win_count / opp_count * 100, 1) if opp_count else 0,
        )

    # ══════════════════════════════════════════
    # 통합 실행
    # ══════════════════════════════════════════
    async def run_funding(self, days: int = 90) -> list[BacktestResult]:
        results = []
        logger.info(f"[펀딩피 백테스트] 최근 {days}일 시작...")
        for ex in ["binance", "bybit"]:
            fee = (self.config.BINANCE_SPOT_FEE + self.config.BINANCE_FUTURES_FEE
                   if ex == "binance"
                   else self.config.BYBIT_SPOT_FEE + self.config.BYBIT_FUTURES_FEE)
            for symbol in self.config.TARGET_SYMBOLS:
                logger.info(f"  [{ex}] {symbol} 수집 중...")
                df = await self.fetch_funding_history(ex, symbol, days)
                r = self.simulate_funding(df, symbol, ex, fee_pct=fee)
                if r:
                    results.append(r)
                await asyncio.sleep(0.3)
        return results

    async def run_arbitrage(self, days: int = 7) -> list[BacktestResult]:
        """거래소 간 아비트라지 백테스트 (기본 7일, 1분봉)"""
        results = []
        logger.info(f"[차익거래 백테스트] 최근 {days}일 시작 (1분봉 데이터)...")
        fee = self.config.BINANCE_SPOT_FEE + self.config.BYBIT_SPOT_FEE

        for symbol in self.config.TARGET_SYMBOLS:
            logger.info(f"  {symbol} Binance + Bybit 데이터 수집 중...")
            df_binance, df_bybit = await asyncio.gather(
                self.fetch_ohlcv("binance", symbol, days),
                self.fetch_ohlcv("bybit", symbol, days),
            )
            # 양방향 시뮬레이션
            r1 = self.simulate_arbitrage(df_binance, df_bybit, symbol, "binance", "bybit", fee)
            r2 = self.simulate_arbitrage(df_bybit, df_binance, symbol, "bybit", "binance", fee)
            if r1:
                results.append(r1)
            if r2:
                results.append(r2)
            await asyncio.sleep(0.5)

        return results

    async def run_all(self, funding_days: int = 90, arb_days: int = 7) -> dict:
        funding_results = await self.run_funding(funding_days)
        arb_results = await self.run_arbitrage(arb_days)
        return {"funding": funding_results, "arbitrage": arb_results}

    # ══════════════════════════════════════════
    # 출력 / 리포트
    # ══════════════════════════════════════════
    def print_report(self, results: list[BacktestResult], title: str = "백테스트 결과"):
        if not results:
            logger.info("결과 없음")
            return
        results = sorted(results, key=lambda x: x.annual_return, reverse=True)
        print("\n" + "=" * 82)
        print(f"  {title}")
        print("=" * 82)
        print(f"{'거래소/방향':<16} {'코인':<12} {'기간':>5} {'총수익':>8} {'수수료':>7} {'순수익':>7} {'연환산':>8} {'MDD':>6} {'샤프':>6} {'기회수':>6}")
        print("-" * 82)
        for r in results:
            print(
                f"{r.exchange:<16} {r.symbol:<12} {r.total_days:>4}일"
                f" {r.total_gross:>7.3f}% {r.total_fee:>6.3f}% {r.net_return:>6.3f}%"
                f" {r.annual_return:>7.1f}% {r.max_drawdown:>5.3f}% {r.sharpe_ratio:>5.2f}"
                f" {r.opportunity_count:>6}회"
            )
        print("=" * 82)
        best = results[0]
        print(f"\n최고: {best.exchange} {best.symbol} | 연환산 {best.annual_return:.1f}% | 기회 {best.opportunity_count}회 | 샤프 {best.sharpe_ratio:.2f}")
        print(f"기간: {best.start_date} ~ {best.end_date} ({best.total_days}일)\n")

    def format_telegram(self, funding: list, arbitrage: list, days_f: int, days_a: int) -> str:
        lines = []

        # 펀딩피 TOP3
        lines.append(f"📊 <b>펀딩피 백테스트 (최근 {days_f}일)</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━")
        for i, r in enumerate(sorted(funding, key=lambda x: x.annual_return, reverse=True)[:3], 1):
            e = "🥇🥈🥉"[i-1]
            lines.append(
                f"{e} {r.exchange.upper()} {r.symbol}\n"
                f"   연환산 <b>{r.annual_return:+.1f}%</b> | MDD {r.max_drawdown:.3f}% | 샤프 {r.sharpe_ratio:.2f}"
            )

        lines.append("")
        # 차익거래 TOP3
        lines.append(f"⚡ <b>거래소간 차익거래 백테스트 (최근 {days_a}일)</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━")
        arb_sorted = sorted(arbitrage, key=lambda x: x.annual_return, reverse=True)
        if arb_sorted:
            for i, r in enumerate(arb_sorted[:3], 1):
                e = "🥇🥈🥉"[i-1]
                lines.append(
                    f"{e} {r.exchange} {r.symbol}\n"
                    f"   기회: <b>{r.opportunity_count}회</b> | 순수익 {r.net_return:+.3f}% | 연환산 {r.annual_return:+.1f}%\n"
                    f"   MDD {r.max_drawdown:.3f}% | 샤프 {r.sharpe_ratio:.2f}"
                )
        else:
            lines.append("기간 내 수익성 있는 차익거래 기회 없음")

        lines.append("━━━━━━━━━━━━━━━━━━━")
        lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return "\n".join(lines)
