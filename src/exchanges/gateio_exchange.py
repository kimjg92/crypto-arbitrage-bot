import ccxt.async_support as ccxt
from src.exchanges.base import BaseExchange, make_exchange_config
from src.core.logger import setup_logger

logger = setup_logger()

class GateioExchange(BaseExchange):
    def __init__(self, api_key: str, api_secret: str):
        super().__init__("Gate.io", api_key, api_secret)

    async def init(self):
        cfg = make_exchange_config(self.api_key, self.api_secret, {"defaultType": "spot"})
        self.exchange = ccxt.gateio(cfg)
        await self.exchange.load_markets()
        logger.info("Gate.io 연결 완료")

    def _make_futures(self):
        cfg = make_exchange_config(self.api_key, self.api_secret, {"defaultType": "future"})
        return ccxt.gateio(cfg)

    async def get_futures_funding_rate(self, symbol: str) -> dict:
        futures = self._make_futures()
        try:
            await futures.load_markets()
            fsymbol = f"{symbol}:{symbol.split('/')[1]}" if ":" not in symbol else symbol
            info = await futures.fetch_funding_rate(fsymbol)
            return {
                "symbol": symbol,
                "exchange": "gateio",
                "funding_rate": float(info["fundingRate"]) * 100,
                "next_funding_time": info.get("fundingDatetime", "N/A"),
            }
        except Exception as e:
            logger.debug(f"Gate.io 펀딩피 조회 실패 {symbol}: {e}")
            return {"symbol": symbol, "exchange": "gateio", "funding_rate": 0.0, "next_funding_time": "N/A"}
        finally:
            await futures.close()

    async def get_futures_price(self, symbol: str) -> float:
        futures = self._make_futures()
        try:
            await futures.load_markets()
            fsymbol = f"{symbol}:{symbol.split('/')[1]}" if ":" not in symbol else symbol
            ticker = await futures.fetch_ticker(fsymbol)
            return float(ticker["last"])
        except Exception as e:
            logger.debug(f"Gate.io 선물가 조회 실패 {symbol}: {e}")
            return await self.get_spot_price(symbol)
        finally:
            await futures.close()

    async def place_spot_order(self, symbol: str, side: str, amount: float) -> dict:
        order = await self.exchange.create_order(symbol, "market", side, amount)
        logger.info(f"[Gate.io 현물] {side.upper()} {symbol} {amount:.6f} - ID: {order['id']}")
        return order

    async def place_futures_order(self, symbol: str, side: str, amount: float) -> dict:
        futures = self._make_futures()
        try:
            await futures.load_markets()
            fsymbol = f"{symbol}:{symbol.split('/')[1]}" if ":" not in symbol else symbol
            order = await futures.create_order(fsymbol, "market", side, amount)
            logger.info(f"[Gate.io 선물] {side.upper()} {symbol} - ID: {order['id']}")
            return order
        finally:
            await futures.close()
