import ccxt.async_support as ccxt
from src.exchanges.base import BaseExchange
from src.core.logger import setup_logger

logger = setup_logger()

class BybitExchange(BaseExchange):
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        super().__init__("Bybit", api_key, api_secret)
        self.testnet = testnet

    async def init(self):
        self.exchange = ccxt.bybit({
            "apiKey": self.api_key,
            "secret": self.api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })
        if self.testnet:
            self.exchange.set_sandbox_mode(True)
        await self.exchange.load_markets()
        logger.info(f"Bybit 연결 완료 (테스트넷: {self.testnet})")

    async def get_futures_funding_rate(self, symbol: str) -> dict:
        futures = ccxt.bybit({
            "apiKey": self.api_key,
            "secret": self.api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "linear"},
        })
        try:
            await futures.load_markets()
            info = await futures.fetch_funding_rate(symbol)
            return {
                "symbol": symbol,
                "exchange": "bybit",
                "funding_rate": float(info["fundingRate"]) * 100,
                "next_funding_time": info["fundingDatetime"],
            }
        finally:
            await futures.close()

    async def get_futures_price(self, symbol: str) -> float:
        futures = ccxt.bybit({
            "apiKey": self.api_key,
            "secret": self.api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "linear"},
        })
        try:
            await futures.load_markets()
            ticker = await futures.fetch_ticker(symbol)
            return float(ticker["last"])
        finally:
            await futures.close()

    async def place_spot_order(self, symbol: str, side: str, amount: float) -> dict:
        order = await self.exchange.create_order(symbol, "market", side, amount)
        logger.info(f"[Bybit 현물] {side.upper()} {symbol} {amount} - 주문ID: {order['id']}")
        return order

    async def place_futures_order(self, symbol: str, side: str, amount: float) -> dict:
        futures = ccxt.bybit({
            "apiKey": self.api_key,
            "secret": self.api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "linear"},
        })
        try:
            await futures.load_markets()
            order = await futures.create_order(symbol, "market", side, amount)
            logger.info(f"[Bybit 선물] {side.upper()} {symbol} {amount} - 주문ID: {order['id']}")
            return order
        finally:
            await futures.close()
