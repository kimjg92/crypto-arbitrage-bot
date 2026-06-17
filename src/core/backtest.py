"""
백테스트 모듈
- 과거 펀딩피 데이터 수집 (Binance/Bybit)
- 현물-선물 Cash & Carry 전략 시뮬레이션
- 수익률, MDD, 샤프 비율 계산
"""
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from src.exchanges.binance_exchange import BinanceExchange
from src.exchanges.bybit_exchange import BybitExchange
from src.core.config import Config
from src.core.logger import setup_logger

logger = setup_logger()

@dataclass
class BacktestResult:
    symbol: str
    exchange: str
    start_date: str
    end_date: str
    total_days: int
    total_funding_income: float   # 펀딩피 수입 (%)
    total_fee: float              # 총 수수료 (%)
    net_return: float             # 순수익률 (%)
    annual_return: float          # 연환산 수익률 (%)
    max_drawdown: float           # 최대 낙폭 (%)
    sharpe_ratio: float
    positive_rate: float          # 양수 펀딩피 비율 (%)
    funding_records: list = field(default_factory=list)


class Backtester:
    def __init__(self, config: Config):
        self.config = config

    async def fetch_funding_history(
        self,
        exchange_name: str,
        symbol: str,
        days: int = 90,
    ) -> pd.DataFrame:
        """과거 펀딩피 데이터 수집"""
        since = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        if exchange_name == "binance":
            ex = BinanceExchange(self.config.BINANCE_API_KEY, self.config.BINANCE_API_SECRET)
            futures_type = "future"
        else:
            ex = BybitExchange(self.config.BYBIT_API_KEY, self.config.BYBIT_API_SECRET)
            futures_type = "linear"

        import ccxt.async_support as ccxt
        from src.exchanges.base import make_exchange_config

        if exchange_name == "binance":
            futures = ccxt.binance(make_exchange_config(
                self.config.BINANCE_API_KEY,
                self.config.BINANCE_API_SECRET,
                {"defaultType": futures_type}
            ))
        else:
            futures = ccxt.bybit(make_exchange_config(
                self.config.BYBIT_API_KEY,
                self.config.BYBIT_API_SECRET,
                {"defaultType": futures_type}
            ))

        records = []
        try:
            await futures.load_markets()

            # Bybit는 선물 심볼 형식 변환
            query_symbol = symbol
            if exchange_name == "bybit" and ":" not in symbol:
                base = symbol.split("/")[1]
                query_symbol = f"{symbol}:{base}"

            # 페이지네이션으로 전체 기간 수집
            current_since = since
            while True:
                batch = await futures.fetch_funding_rate_history(
                    query_symbol, since=current_since, limit=1000
                )
                if not batch:
                    break
                records.extend(batch)
                if len(batch) < 1000:
                    break
                current_since = batch[-1]["timestamp"] + 1
                await asyncio.sleep(0.3)

        except Exception as e:
            logger.error(f"[{exchange_name}] {symbol} 펀딩피 히스토리 오류: {e}")
        finally:
            await futures.close()

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame([{
            "timestamp": r["timestamp"],
            "datetime": r["datetime"],
            "funding_rate": float(r["fundingRate"]) * 100,
        } for r in records])
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def simulate(
        self,
        df: pd.DataFrame,
        symbol: str,
        exchange_name: str,
        entry_fee_pct: float = 0.15,   # 진입 왕복 수수료
        exit_fee_pct: float = 0.15,    # 청산 왕복 수수료
        min_rate: float = 0.005,       # 최소 진입 기준 펀딩피 (%)
    ) -> BacktestResult:
        if df.empty:
            return None

        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        equity_curve = []
        in_position = False
        total_fee = 0.0
        positive_count = 0

        # 진입 수수료 (처음 한 번)
        total_fee += entry_fee_pct

        for _, row in df.iterrows():
            rate = row["funding_rate"]

            if rate > 0:
                positive_count += 1

            # 포지션 진입 조건: 펀딩피가 기준 이상
            if rate >= min_rate:
                if not in_position:
                    in_position = True

                income = rate  # 8h당 수입
                cumulative += income

            else:
                if in_position:
                    in_position = False

            equity_curve.append(cumulative - total_fee)
            peak = max(peak, cumulative - total_fee)
            dd = peak - (cumulative - total_fee)
            max_dd = max(max_dd, dd)

        # 청산 수수료
        total_fee += exit_fee_pct
        net = cumulative - total_fee
        total_days = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]) / (1000 * 86400)
        annual = net / total_days * 365 if total_days > 0 else 0

        # 샤프 비율
        rates = df["funding_rate"].values
        sharpe = (np.mean(rates) / np.std(rates) * np.sqrt(3 * 365)) if np.std(rates) > 0 else 0

        return BacktestResult(
            symbol=symbol,
            exchange=exchange_name,
            start_date=df["datetime"].iloc[0][:10],
            end_date=df["datetime"].iloc[-1][:10],
            total_days=int(total_days),
            total_funding_income=round(cumulative, 4),
            total_fee=round(total_fee, 4),
            net_return=round(net, 4),
            annual_return=round(annual, 2),
            max_drawdown=round(max_dd, 4),
            sharpe_ratio=round(sharpe, 2),
            positive_rate=round(positive_count / len(df) * 100, 1),
            funding_records=df.to_dict("records"),
        )

    async def run(self, days: int = 90) -> list[BacktestResult]:
        results = []
        symbols = self.config.TARGET_SYMBOLS
        exchanges = ["binance", "bybit"]

        logger.info(f"백테스트 시작: 최근 {days}일 | {len(symbols)}개 코인 | {len(exchanges)}개 거래소")

        for ex in exchanges:
            for symbol in symbols:
                logger.info(f"  [{ex}] {symbol} 데이터 수집 중...")
                df = await self.fetch_funding_history(ex, symbol, days)
                if df.empty:
                    logger.warning(f"  [{ex}] {symbol} 데이터 없음")
                    continue

                fee = (
                    (self.config.BINANCE_SPOT_FEE + self.config.BINANCE_FUTURES_FEE)
                    if ex == "binance"
                    else (self.config.BYBIT_SPOT_FEE + self.config.BYBIT_FUTURES_FEE)
                )
                result = self.simulate(df, symbol, ex, entry_fee_pct=fee, exit_fee_pct=fee)
                if result:
                    results.append(result)
                await asyncio.sleep(0.5)

        return results

    def print_report(self, results: list[BacktestResult]):
        if not results:
            logger.info("백테스트 결과 없음")
            return

        results.sort(key=lambda x: x.annual_return, reverse=True)

        print("\n" + "=" * 75)
        print(f"{'백테스트 결과':^75}")
        print("=" * 75)
        print(f"{'거래소':<10} {'코인':<12} {'기간':<6} {'펀딩수입':>9} {'수수료':>8} {'순수익':>8} {'연환산':>8} {'MDD':>7} {'샤프':>6}")
        print("-" * 75)
        for r in results:
            print(
                f"{r.exchange:<10} {r.symbol:<12} {r.total_days:>4}일 "
                f"{r.total_funding_income:>8.2f}% {r.total_fee:>7.2f}% "
                f"{r.net_return:>7.2f}% {r.annual_return:>7.1f}% "
                f"{r.max_drawdown:>6.2f}% {r.sharpe_ratio:>5.2f}"
            )
        print("=" * 75)
        best = results[0]
        print(f"\n최고 수익: {best.exchange} {best.symbol} | 연환산 {best.annual_return:.1f}% | 샤프 {best.sharpe_ratio:.2f}")
        print(f"기간: {best.start_date} ~ {best.end_date} ({best.total_days}일)\n")

    def format_telegram_report(self, results: list[BacktestResult], days: int) -> str:
        if not results:
            return "백테스트 결과 없음"

        results.sort(key=lambda x: x.annual_return, reverse=True)
        top5 = results[:5]

        lines = [
            f"📊 <b>백테스트 결과 (최근 {days}일)</b>",
            "━━━━━━━━━━━━━━━━━━━",
        ]
        for i, r in enumerate(top5, 1):
            emoji = "🥇🥈🥉🏅🏅"[i - 1]
            lines.append(
                f"{emoji} {r.exchange.upper()} {r.symbol}\n"
                f"   연환산: <b>{r.annual_return:+.1f}%</b> | MDD: {r.max_drawdown:.2f}%\n"
                f"   펀딩수입: {r.total_funding_income:.2f}% | 샤프: {r.sharpe_ratio:.2f}"
            )
        lines.append("━━━━━━━━━━━━━━━━━━━")
        lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return "\n".join(lines)
