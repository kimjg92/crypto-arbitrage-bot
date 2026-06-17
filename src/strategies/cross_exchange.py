"""
거래소 간 현물 아비트라지 전략
- A 거래소 ask 매수 → B 거래소 bid 매도 동시 실행
- 수수료 + 슬리피지 차감 후 순수익 양수일 때만 실행
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime
from src.core.config import Config
from src.core.logger import setup_logger
from src.utils.notifier import Notifier

logger = setup_logger()

@dataclass
class ArbitrageOpportunity:
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    spread_pct: float
    net_profit_pct: float
    is_profitable: bool

class CrossExchangeStrategy:
    def __init__(self, exchanges: dict, config: Config, notifier: Notifier = None):
        self.exchanges = exchanges
        self.config = config
        self.notifier = notifier
        self.running = False
        # 일일 통계
        self.daily_arb_income = 0.0
        self.daily_fee = 0.0
        self.trade_count = 0
        self.win_count = 0
        self._last_notified: dict[str, float] = {}  # 동일 기회 알림 중복 방지

    def _calc_fees(self, buy_ex: str, sell_ex: str) -> float:
        fee_map = {
            "binance": self.config.BINANCE_SPOT_FEE,
            "bybit": self.config.BYBIT_SPOT_FEE,
        }
        return fee_map.get(buy_ex, 0.1) + fee_map.get(sell_ex, 0.1)

    async def scan_opportunities(self) -> list[ArbitrageOpportunity]:
        opportunities = []
        exchange_names = list(self.exchanges.keys())

        for symbol in self.config.TARGET_SYMBOLS:
            orderbooks = {}
            for ex_name in exchange_names:
                try:
                    ob = await self.exchanges[ex_name].get_orderbook(symbol)
                    orderbooks[ex_name] = ob
                except Exception as e:
                    logger.debug(f"[{ex_name}] {symbol} 호가 조회 실패: {e}")

            if len(orderbooks) < 2:
                continue

            for buy_ex in exchange_names:
                for sell_ex in exchange_names:
                    if buy_ex == sell_ex:
                        continue
                    if buy_ex not in orderbooks or sell_ex not in orderbooks:
                        continue

                    buy_price = orderbooks[buy_ex]["ask"]
                    sell_price = orderbooks[sell_ex]["bid"]
                    if buy_price <= 0 or sell_price <= 0:
                        continue

                    spread_pct = (sell_price - buy_price) / buy_price * 100
                    fees = self._calc_fees(buy_ex, sell_ex)
                    net_profit_pct = spread_pct - fees - self.config.ARBITRAGE_FEE_BUFFER

                    opp = ArbitrageOpportunity(
                        symbol=symbol,
                        buy_exchange=buy_ex,
                        sell_exchange=sell_ex,
                        buy_price=buy_price,
                        sell_price=sell_price,
                        spread_pct=spread_pct,
                        net_profit_pct=net_profit_pct,
                        is_profitable=net_profit_pct > self.config.MIN_ARBITRAGE_SPREAD,
                    )

                    if opp.is_profitable:
                        opportunities.append(opp)
                        logger.info(
                            f"[차익거래 기회] {symbol} | "
                            f"{buy_ex}→{sell_ex} | "
                            f"스프레드: {spread_pct:.3f}% | 순수익: {net_profit_pct:.3f}%"
                        )
                        # 같은 기회를 60초 안에 중복 알림 방지
                        key = f"{symbol}_{buy_ex}_{sell_ex}"
                        now = datetime.now().timestamp()
                        if now - self._last_notified.get(key, 0) > 60:
                            self._last_notified[key] = now
                            if self.notifier:
                                await self.notifier.notify_arbitrage_opportunity(opp)

        return sorted(opportunities, key=lambda x: x.net_profit_pct, reverse=True)

    async def execute_arbitrage(self, opp: ArbitrageOpportunity, usdt_amount: float):
        if usdt_amount > self.config.MAX_POSITION_USDT:
            return

        buy_exchange = self.exchanges[opp.buy_exchange]
        sell_exchange = self.exchanges[opp.sell_exchange]
        coin_amount = usdt_amount / opp.buy_price
        fees_usdt = usdt_amount * self._calc_fees(opp.buy_exchange, opp.sell_exchange) / 100

        balance_before_buy = await buy_exchange.get_balance("USDT")

        logger.info(f"[차익거래 실행] {opp.symbol} ${usdt_amount:.2f}")

        if self.notifier:
            await self.notifier.notify_position_enter(
                strategy="arbitrage",
                symbol=opp.symbol,
                exchange=f"{opp.buy_exchange}→{opp.sell_exchange}",
                usdt_amount=usdt_amount,
                spot_price=opp.buy_price,
                futures_price=opp.sell_price,
                balance_before=balance_before_buy,
            )

        try:
            await asyncio.gather(
                buy_exchange.place_spot_order(opp.symbol, "buy", coin_amount),
                sell_exchange.place_spot_order(opp.symbol, "sell", coin_amount),
            )

            profit_usdt = usdt_amount * opp.net_profit_pct / 100
            net_pnl = profit_usdt - fees_usdt
            self.daily_arb_income += net_pnl
            self.daily_fee += fees_usdt
            self.trade_count += 1
            if net_pnl >= 0:
                self.win_count += 1

            balance_after_buy = await buy_exchange.get_balance("USDT")

            logger.info(f"[차익거래 완료] {opp.symbol} | 순수익: ${net_pnl:+.4f}")

            if self.notifier:
                await self.notifier.notify_position_exit(
                    strategy="arbitrage",
                    symbol=opp.symbol,
                    exchange=f"{opp.buy_exchange}→{opp.sell_exchange}",
                    usdt_amount=usdt_amount,
                    entry_price=opp.buy_price,
                    exit_price=opp.sell_price,
                    realized_pnl=profit_usdt,
                    total_fee=fees_usdt,
                    balance_before=balance_before_buy,
                    balance_after=balance_after_buy,
                )
        except Exception as e:
            logger.error(f"[차익거래 실패] {opp.symbol}: {e}")
            if self.notifier:
                await self.notifier.notify_error(f"차익거래 실패: {opp.symbol}", str(e))

    async def run(self):
        self.running = True
        logger.info("거래소 간 차익거래 전략 시작")
        while self.running:
            try:
                opportunities = await self.scan_opportunities()
                if not opportunities:
                    logger.debug("차익거래 기회 없음")
            except Exception as e:
                logger.error(f"차익거래 스캔 오류: {e}")
            await asyncio.sleep(self.config.ARBITRAGE_SCAN_INTERVAL)

    def stop(self):
        self.running = False
