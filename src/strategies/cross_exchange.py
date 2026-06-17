"""
거래소 간 현물 아비트라지 전략
- A 거래소 낮은 ask 가격 매수 → B 거래소 높은 bid 가격 매도
- 수수료 + 슬리피지 차감 후 순수익 양수일 때만 실행
"""
import asyncio
from dataclasses import dataclass
from src.core.config import Config
from src.core.logger import setup_logger
from src.utils.notifier import Notifier

logger = setup_logger()

@dataclass
class ArbitrageOpportunity:
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float       # ask (매수가)
    sell_price: float      # bid (매도가)
    spread_pct: float      # (매도-매수)/매수 * 100
    net_profit_pct: float  # 수수료 차감 후
    is_profitable: bool

class CrossExchangeStrategy:
    def __init__(self, exchanges: dict, config: Config, notifier: Notifier = None):
        self.exchanges = exchanges
        self.config = config
        self.notifier = notifier
        self.running = False
        self.total_profit = 0.0

    def _calc_fees(self, buy_ex: str, sell_ex: str) -> float:
        """왕복 수수료 합계 (%)"""
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

            # 모든 거래소 쌍 비교
            for i, buy_ex in enumerate(exchange_names):
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
                        logger.info(
                            f"[차익거래 기회] {symbol} | "
                            f"{buy_ex}(${buy_price:.4f}) → {sell_ex}(${sell_price:.4f}) | "
                            f"스프레드: {spread_pct:.3f}% | 순수익: {net_profit_pct:.3f}%"
                        )
                        opportunities.append(opp)

        return sorted(opportunities, key=lambda x: x.net_profit_pct, reverse=True)

    async def execute_arbitrage(self, opp: ArbitrageOpportunity, usdt_amount: float):
        """차익거래 실행"""
        if usdt_amount > self.config.MAX_POSITION_USDT:
            logger.warning(f"포지션 한도 초과")
            return

        buy_exchange = self.exchanges[opp.buy_exchange]
        sell_exchange = self.exchanges[opp.sell_exchange]
        coin_amount = usdt_amount / opp.buy_price

        logger.info(
            f"[차익거래 실행] {opp.symbol} | "
            f"{opp.buy_exchange} 매수 / {opp.sell_exchange} 매도 | "
            f"예상 순수익: {opp.net_profit_pct:.3f}%"
        )

        try:
            buy_order, sell_order = await asyncio.gather(
                buy_exchange.place_spot_order(opp.symbol, "buy", coin_amount),
                sell_exchange.place_spot_order(opp.symbol, "sell", coin_amount),
            )
            profit_usdt = usdt_amount * opp.net_profit_pct / 100
            self.total_profit += profit_usdt
            logger.info(
                f"[차익거래 완료] 예상 수익: ${profit_usdt:.4f} | "
                f"누적 수익: ${self.total_profit:.4f}"
            )
            if self.notifier:
                await self.notifier.send(
                    f"⚡ 차익거래 실행\n{opp.symbol}\n"
                    f"{opp.buy_exchange} → {opp.sell_exchange}\n"
                    f"순수익: {opp.net_profit_pct:.3f}% (${profit_usdt:.4f})"
                )
        except Exception as e:
            logger.error(f"[차익거래 실패] {opp.symbol}: {e}")

    async def run(self):
        """차익거래 스캔 루프"""
        self.running = True
        logger.info("거래소 간 차익거래 전략 시작")
        while self.running:
            opportunities = await self.scan_opportunities()
            if not opportunities:
                logger.debug("차익거래 기회 없음")
            await asyncio.sleep(self.config.ARBITRAGE_SCAN_INTERVAL)

    def stop(self):
        self.running = False
