import ccxt.async_support as ccxt
from abc import ABC, abstractmethod
from src.core.logger import setup_logger

logger = setup_logger()

class BaseExchange(ABC):
    def __init__(self, name: str, api_key: str, api_secret: str):
        self.name = name
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange: ccxt.Exchange = None

    @abstractmethod
    async def init(self): ...

    async def close(self):
        if self.exchange:
            await self.exchange.close()

    async def get_spot_price(self, symbol: str) -> float:
        ticker = await self.exchange.fetch_ticker(symbol)
        return float(ticker["last"])

    async def get_orderbook(self, symbol: str, limit: int = 5) -> dict:
        ob = await self.exchange.fetch_order_book(symbol, limit)
        return {
            "bid": ob["bids"][0][0] if ob["bids"] else 0,
            "ask": ob["asks"][0][0] if ob["asks"] else 0,
            "bid_volume": ob["bids"][0][1] if ob["bids"] else 0,
            "ask_volume": ob["asks"][0][1] if ob["asks"] else 0,
        }

    async def get_balance(self, currency: str = "USDT") -> float:
        balance = await self.exchange.fetch_balance()
        return float(balance.get(currency, {}).get("free", 0))
