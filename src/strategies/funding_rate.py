"""
현물-선물 펀딩피 아비트라지 전략
- 현물 매수 + 선물 숏 동시 진입
- 펀딩피 수취 후 포지션 청산
- 방향성 리스크 없음 (델타 중립)
"""
import asyncio
from dataclasses import dataclass
from src.core.config import Config
from src.core.logger import setup_logger
from src.utils.notifier import Notifier

logger = setup_logger()

@dataclass
class FundingOpportunity:
    symbol: str
    exchange: str
    funding_rate: float        # % per 8h
    annual_rate: float         # % 연환산
    spot_price: float
    futures_price: float
    basis: float               # (선물-현물)/현물 * 100 (%)
    next_funding_time: str
    is_profitable: bool

class FundingRateStrategy:
    def __init__(self, exchanges: dict, config: Config, notifier: Notifier = None):
        self.exchanges = exchanges   # {"binance": BinanceExchange, "bybit": BybitExchange}
        self.config = config
        self.notifier = notifier
        self.active_positions = {}   # symbol -> position info
        self.running = False

    def _calc_annual_rate(self, funding_rate: float) -> float:
        """8시간 펀딩피 → 연환산"""
        return funding_rate * 3 * 365

    def _calc_net_profit(self, funding_rate: float, exchange_name: str) -> float:
        """수수료 차감 후 실질 수익률 (8h 기준 %)"""
        if exchange_name == "binance":
            fee = self.config.BINANCE_SPOT_FEE + self.config.BINANCE_FUTURES_FEE
        else:
            fee = self.config.BYBIT_SPOT_FEE + self.config.BYBIT_FUTURES_FEE
        entry_cost = fee * 2       # 진입 왕복
        exit_cost = fee * 2        # 청산 왕복
        return funding_rate - (entry_cost + exit_cost) / 3  # 8h당 비용

    async def scan_opportunities(self) -> list[FundingOpportunity]:
        """모든 거래소/코인의 펀딩피 기회 스캔"""
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
                    net = self._calc_net_profit(funding_rate, ex_name)

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
                            f"베이시스: {basis:.3f}%"
                        )

                except Exception as e:
                    logger.warning(f"[{ex_name}] {symbol} 조회 실패: {e}")
                    await asyncio.sleep(0.5)

        return sorted(opportunities, key=lambda x: x.annual_rate, reverse=True)

    def print_opportunities(self, opportunities: list[FundingOpportunity]):
        profitable = [o for o in opportunities if o.is_profitable]
        if not profitable:
            logger.info("현재 수익성 있는 펀딩피 기회 없음")
            return

        logger.info("=" * 60)
        logger.info(f"펀딩피 기회 {len(profitable)}개 발견")
        logger.info("=" * 60)
        for o in profitable:
            logger.info(
                f"  {o.exchange:8} | {o.symbol:12} | "
                f"펀딩피: {o.funding_rate:+.4f}% | 연환산: {o.annual_rate:+.1f}% | "
                f"다음 지급: {o.next_funding_time}"
            )

    async def enter_position(self, opp: FundingOpportunity, usdt_amount: float):
        """포지션 진입: 현물 매수 + 선물 숏"""
        if opp.symbol in self.active_positions:
            logger.warning(f"{opp.symbol} 이미 포지션 보유 중")
            return

        if usdt_amount > self.config.MAX_POSITION_USDT:
            logger.warning(f"포지션 한도 초과: {usdt_amount} > {self.config.MAX_POSITION_USDT}")
            return

        exchange = self.exchanges[opp.exchange]
        coin_amount = usdt_amount / opp.spot_price

        logger.info(f"[진입 시작] {opp.symbol} | {opp.exchange} | ${usdt_amount:.2f}")
        try:
            # 현물 매수 + 선물 숏 동시 실행
            spot_order, futures_order = await asyncio.gather(
                exchange.place_spot_order(opp.symbol, "buy", coin_amount),
                exchange.place_futures_order(opp.symbol, "sell", coin_amount),
            )
            self.active_positions[opp.symbol] = {
                "exchange": opp.exchange,
                "coin_amount": coin_amount,
                "spot_entry": opp.spot_price,
                "futures_entry": opp.futures_price,
                "usdt_amount": usdt_amount,
                "spot_order_id": spot_order["id"],
                "futures_order_id": futures_order["id"],
            }
            logger.info(f"[진입 완료] {opp.symbol} 현물매수 + 선물숏 완료")
            if self.notifier:
                await self.notifier.send(
                    f"✅ 포지션 진입\n{opp.exchange} {opp.symbol}\n"
                    f"금액: ${usdt_amount:.2f}\n펀딩피: {opp.funding_rate:.4f}%\n연환산: {opp.annual_rate:.1f}%"
                )
        except Exception as e:
            logger.error(f"[진입 실패] {opp.symbol}: {e}")

    async def exit_position(self, symbol: str):
        """포지션 청산: 현물 매도 + 선물 롱"""
        if symbol not in self.active_positions:
            logger.warning(f"{symbol} 보유 포지션 없음")
            return

        pos = self.active_positions[symbol]
        exchange = self.exchanges[pos["exchange"]]
        coin_amount = pos["coin_amount"]

        logger.info(f"[청산 시작] {symbol}")
        try:
            await asyncio.gather(
                exchange.place_spot_order(symbol, "sell", coin_amount),
                exchange.place_futures_order(symbol, "buy", coin_amount),
            )
            del self.active_positions[symbol]
            logger.info(f"[청산 완료] {symbol}")
            if self.notifier:
                await self.notifier.send(f"🔴 포지션 청산\n{symbol} 청산 완료")
        except Exception as e:
            logger.error(f"[청산 실패] {symbol}: {e}")

    async def run(self):
        """펀딩피 스캔 루프"""
        self.running = True
        logger.info("펀딩피 아비트라지 전략 시작")
        while self.running:
            opportunities = await self.scan_opportunities()
            self.print_opportunities(opportunities)
            await asyncio.sleep(self.config.FUNDING_SCAN_INTERVAL)

    def stop(self):
        self.running = False
