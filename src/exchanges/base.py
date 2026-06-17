import aiohttp
import ccxt.async_support as ccxt
from abc import ABC, abstractmethod
from src.core.logger import setup_logger

logger = setup_logger()

def make_session() -> aiohttp.ClientSession:
    """Windows aiodns 문제 우회 - asyncio 기본 resolver 사용"""
    connector = aiohttp.TCPConnector(resolver=aiohttp.resolver.AsyncResolver() if False else aiohttp.resolver.ThreadedResolver())
    return aiohttp.ClientSession(connector=connector)

def make_exchange_config(api_key: str, api_secret: str, options: dict = None) -> dict:
    base_options = {
        "adjustForTimeDifference": True,   # 시스템 시계 자동 보정
        "recvWindow": 60000,               # 타임스탬프 허용 오차 60초
    }
    if options:
        base_options.update(options)
    cfg = {
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "aiohttp_trust_env": True,
        "session": make_session(),
        "options": base_options,
    }
    return cfg

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
