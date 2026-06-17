"""
현물-선물 펀딩피 아비트라지 전략
- 현물 매수 + 선물 숏 동시 진입 (델타 중립)
- 펀딩피 수취 후 포지션 청산
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from src.core.config import Config
from src.core.logger import setup_logger
from src.utils.notifier import Notifier
from src.exchanges.account_manager import AccountManager

logger = setup_logger()

@dataclass
class FundingOpportunity:
    symbol: str
    exchange: str
    funding_rate: float
    annual_rate: float
    spot_price: float
    futures_price: float
    basis: float
    next_funding_time: str
    is_profitable: bool

@dataclass
class FundingPosition:
    symbol: str
    exchange: str
    coin_amount: float
    spot_entry: float
    futures_entry: float
    usdt_amount: float
    spot_order_id: str
    futures_order_id: str
    funding_collected: float = 0.0
    total_fee: float = 0.0
    enter_time: datetime = field(default_factory=datetime.now)

class FundingRateStrategy:
    def __init__(self, exchanges: dict, config: Config, notifier: Notifier = None):
        self.exchanges = exchanges
        self.config = config
        self.notifier = notifier
        self.active_positions: dict[str, FundingPosition] = {}
        self.running = False
        # 일일 통계
        self.daily_funding_income = 0.0
        self.daily_fee = 0.0
        self.trade_count = 0
        self.win_count = 0

    def _calc_annual_rate(self, funding_rate: float) -> float:
        return funding_rate * 3 * 365

    def _calc_cost_per_8h(self, exchange_name: str) -> tuple[float, str]:
        """
        8시간당 실질 비용
        - 수수료: 진입+청산 왕복 / 보유 기간(8h 단위) 로 분할
        - 슬리피지: 진입+청산 왕복 / 보유 기간 분할
        - 레버리지: 선물 마진은 줄지만 청산 리스크 증가
        """
        round_trip = self.config.get_funding_round_trip_cost(exchange_name)
        # 평균 보유 기간을 3 사이클(24h)로 가정 → 8h당 비용
        cost_per_8h = round_trip / 3
        leverage = self.config.FUTURES_LEVERAGE
        detail = (f"왕복비용 {round_trip:.3f}% / 3사이클 "
                  f"= {cost_per_8h:.4f}%/8h | 레버리지 {leverage}x")
        return cost_per_8h, detail

    def _calc_net_rate(self, funding_rate: float, exchange_name: str) -> float:
        cost_per_8h, _ = self._calc_cost_per_8h(exchange_name)
        return funding_rate - cost_per_8h

    def _calc_capital_efficiency(self, usdt_amount: float) -> dict:
        """레버리지 적용 시 자본 효율 계산"""
        lev = self.config.FUTURES_LEVERAGE
        spot_required   = usdt_amount
        futures_margin  = usdt_amount / lev   # 레버리지로 줄어드는 마진
        total_required  = spot_required + futures_margin
        saved           = usdt_amount - futures_margin
        return {
            "leverage":        lev,
            "spot_required":   spot_required,
            "futures_margin":  futures_margin,
            "total_required":  total_required,
            "capital_saved":   saved,
        }

    async def scan_opportunities(self) -> list[FundingOpportunity]:
        opportunities = []
        for ex_name, exchange in self.exchanges.items():
            for symbol in self.config.TARGET_SYMBOLS:
                try:
                    fr_info = await exchange.get_futures_funding_rate(symbol)
                    spot_price = await exchange.get_spot_price(symbol)
                    futures_price = await exchange.get_futures_price(symbol)

                    funding_rate = fr_info["funding_rate"]
                    annual_rate = self._calc_annual_rate(funding_rate)
                    basis = (futures_price - spot_price) / spot_price * 100
                    net = self._calc_net_rate(funding_rate, ex_name)

                    cost_8h, cost_detail = self._calc_cost_per_8h(ex_name)
                    cap = self._calc_capital_efficiency(100)  # $100 기준 예시

                    opp = FundingOpportunity(
                        symbol=symbol,
                        exchange=ex_name,
                        funding_rate=funding_rate,
                        annual_rate=annual_rate,
                        spot_price=spot_price,
                        futures_price=futures_price,
                        basis=basis,
                        next_funding_time=fr_info["next_funding_time"],
                        is_profitable=(funding_rate > self.config.MIN_FUNDING_RATE and net > 0),
                    )
                    opportunities.append(opp)

                    if opp.is_profitable:
                        logger.info(
                            f"[펀딩피 기회] {ex_name} {symbol} | "
                            f"펀딩피: {funding_rate:.4f}% | 연환산: {annual_rate:.1f}% | "
                            f"비용: {cost_8h:.4f}%/8h ({cost_detail}) | "
                            f"레버리지{cap['leverage']}x → 필요자금 ${cap['total_required']:.0f}/$200"
                        )
                        if self.notifier:
                            await self.notifier.notify_funding_opportunity(opp)

                except Exception as e:
                    logger.warning(f"[{ex_name}] {symbol} 조회 실패: {e}")
                    await asyncio.sleep(0.3)

        return sorted(opportunities, key=lambda x: x.annual_rate, reverse=True)

    def print_top_opportunities(self, opportunities: list[FundingOpportunity]):
        profitable = [o for o in opportunities if o.is_profitable]
        if not profitable:
            logger.info("현재 수익성 있는 펀딩피 기회 없음")
            return
        logger.info(f"{'='*65}")
        logger.info(f"펀딩피 기회 TOP {min(5, len(profitable))}개")
        logger.info(f"{'='*65}")
        for o in profitable[:5]:
            logger.info(
                f"  {o.exchange:8} | {o.symbol:12} | "
                f"펀딩피: {o.funding_rate:+.4f}% | 연환산: {o.annual_rate:+.1f}% | "
                f"베이시스: {o.basis:+.3f}%"
            )

    async def enter_position(self, opp: FundingOpportunity, usdt_amount: float):
        if opp.symbol in self.active_positions:
            logger.warning(f"{opp.symbol} 이미 포지션 보유 중")
            return

        exchange = self.exchanges[opp.exchange]
        lev = self.config.FUTURES_LEVERAGE
        futures_margin = usdt_amount / lev   # 레버리지 적용 마진
        coin_amount = usdt_amount / opp.spot_price

        # ── 계정 잔고 확인 및 자동 이체 ──────────────────
        from src.core.config import Config
        ex_cfg = Config()
        acct = AccountManager(
            opp.exchange,
            ex_cfg.BINANCE_API_KEY if opp.exchange == "binance" else
            ex_cfg.BYBIT_API_KEY   if opp.exchange == "bybit"   else
            ex_cfg.MEXC_API_KEY    if opp.exchange == "mexc"    else
            ex_cfg.GATEIO_API_KEY,
            ex_cfg.BINANCE_API_SECRET if opp.exchange == "binance" else
            ex_cfg.BYBIT_API_SECRET   if opp.exchange == "bybit"   else
            ex_cfg.MEXC_API_SECRET    if opp.exchange == "mexc"    else
            ex_cfg.GATEIO_API_SECRET,
        )

        # Spot 잔고 확인 (현물 매수용)
        spot_bal = await acct.get_spot_balance("USDT")
        if spot_bal < usdt_amount:
            msg = f"Spot 잔고 부족: ${spot_bal:.2f} < ${usdt_amount:.2f}"
            logger.warning(f"[진입 취소] {opp.symbol} - {msg}")
            if self.notifier:
                await self.notifier.notify_error(f"진입 취소: {opp.symbol}", msg)
            return

        # Futures 계정 잔고 확인 + 부족 시 자동 이체
        ok, msg = await acct.ensure_futures_balance(futures_margin, "USDT")
        if not ok:
            logger.warning(f"[진입 취소] {opp.symbol} - {msg}")
            if self.notifier:
                await self.notifier.notify_error(f"진입 취소: {opp.symbol}", msg)
            return
        if "자동 이체" in msg:
            logger.info(f"[계정 이체] {msg}")
            if self.notifier:
                await self.notifier.send(
                    f"🔄 <b>계정 내부 이체</b>\n"
                    f"{opp.exchange.upper()} Spot→Futures\n"
                    f"금액: ${futures_margin:.2f} USDT\n{msg}"
                )

        balances = await acct.get_all_balances("USDT")
        balance_before = balances["total"]
        logger.info(
            f"[진입] {opp.symbol} | {opp.exchange} | ${usdt_amount:.2f} | "
            f"레버리지 {lev}x | 선물마진 ${futures_margin:.2f} | "
            f"계정구조: {'통합' if balances['unified'] else '분리'}"
        )

        cost_per_8h, _ = self._calc_cost_per_8h(opp.exchange)
        fee = cost_per_8h * usdt_amount / 100

        try:
            spot_order, futures_order = await asyncio.gather(
                exchange.place_spot_order(opp.symbol, "buy", coin_amount),
                exchange.place_futures_order(opp.symbol, "sell", coin_amount),
            )
            pos = FundingPosition(
                symbol=opp.symbol,
                exchange=opp.exchange,
                coin_amount=coin_amount,
                spot_entry=opp.spot_price,
                futures_entry=opp.futures_price,
                usdt_amount=usdt_amount,
                spot_order_id=spot_order["id"],
                futures_order_id=futures_order["id"],
                total_fee=fee,
            )
            self.active_positions[opp.symbol] = pos
            logger.info(f"[진입 완료] {opp.symbol}")

            if self.notifier:
                await self.notifier.notify_position_enter(
                    strategy="funding",
                    symbol=opp.symbol,
                    exchange=opp.exchange,
                    usdt_amount=usdt_amount,
                    spot_price=opp.spot_price,
                    futures_price=opp.futures_price,
                    funding_rate=opp.funding_rate,
                    balance_before=balance_before,
                )
        except Exception as e:
            logger.error(f"[진입 실패] {opp.symbol}: {e}")
            if self.notifier:
                await self.notifier.notify_error(f"진입 실패: {opp.symbol}", str(e))

    async def collect_funding(self, symbol: str, funding_rate: float):
        """펀딩피 수취 기록 (실제 지급은 거래소가 자동 처리)"""
        if symbol not in self.active_positions:
            return
        pos = self.active_positions[symbol]
        income = pos.usdt_amount * funding_rate / 100
        pos.funding_collected += income
        self.daily_funding_income += income
        logger.info(f"[펀딩피 수취] {symbol} +${income:.4f} (누적: +${pos.funding_collected:.4f})")

    async def exit_position(self, symbol: str):
        if symbol not in self.active_positions:
            logger.warning(f"{symbol} 보유 포지션 없음")
            return

        pos = self.active_positions[symbol]
        exchange = self.exchanges[pos.exchange]
        balance_before = await exchange.get_balance("USDT")

        logger.info(f"[청산] {symbol}")
        try:
            spot_price_now = await exchange.get_spot_price(symbol)
            futures_price_now = await exchange.get_futures_price(symbol)

            await asyncio.gather(
                exchange.place_spot_order(symbol, "sell", pos.coin_amount),
                exchange.place_futures_order(symbol, "buy", pos.coin_amount),
            )

            # 가격 손익 계산 (델타 중립이라 이론상 0, 슬리피지 반영)
            spot_pnl = (spot_price_now - pos.spot_entry) * pos.coin_amount
            futures_pnl = (pos.futures_entry - futures_price_now) * pos.coin_amount
            realized_pnl = spot_pnl + futures_pnl

            exit_fee = pos.total_fee  # 청산도 동일 수수료
            pos.total_fee += exit_fee
            self.daily_fee += pos.total_fee

            net_pnl = realized_pnl + pos.funding_collected - pos.total_fee
            if net_pnl >= 0:
                self.win_count += 1
            self.trade_count += 1

            duration = str(datetime.now() - pos.enter_time).split(".")[0]

            # ── 청산 후 Futures → Spot 수익금 자동 회수 (분리 계정만) ──
            from src.core.config import Config as _Config
            _cfg = _Config()
            acct = AccountManager(
                pos.exchange,
                getattr(_cfg, f"{pos.exchange.upper()}_API_KEY", ""),
                getattr(_cfg, f"{pos.exchange.upper()}_API_SECRET", ""),
            )
            if not acct.is_unified and realized_pnl + pos.funding_collected > 0:
                profit_back = realized_pnl + pos.funding_collected
                await acct.rebalance_after_exit(profit_back, "USDT")
                logger.info(f"[수익 회수] Futures→Spot ${profit_back:.4f} USDT")

            balance_after = await exchange.get_balance("USDT")
            del self.active_positions[symbol]
            logger.info(f"[청산 완료] {symbol} | 순손익: ${net_pnl:+.4f}")

            if self.notifier:
                await self.notifier.notify_position_exit(
                    strategy="funding",
                    symbol=symbol,
                    exchange=pos.exchange,
                    usdt_amount=pos.usdt_amount,
                    entry_price=pos.spot_entry,
                    exit_price=spot_price_now,
                    realized_pnl=realized_pnl,
                    funding_collected=pos.funding_collected,
                    total_fee=pos.total_fee,
                    balance_before=balance_before,
                    balance_after=balance_after,
                    hold_duration=duration,
                )
        except Exception as e:
            logger.error(f"[청산 실패] {symbol}: {e}")
            if self.notifier:
                await self.notifier.notify_error(f"청산 실패: {symbol}", str(e))

    async def run(self):
        self.running = True
        logger.info("펀딩피 아비트라지 전략 시작")
        while self.running:
            try:
                opportunities = await self.scan_opportunities()
                self.print_top_opportunities(opportunities)
            except Exception as e:
                logger.error(f"펀딩피 스캔 오류: {e}")
            await asyncio.sleep(self.config.FUNDING_SCAN_INTERVAL)

    def stop(self):
        self.running = False
