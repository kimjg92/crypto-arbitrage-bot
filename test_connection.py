import asyncio
import warnings
warnings.filterwarnings("ignore")

from src.exchanges.binance_exchange import BinanceExchange
from src.exchanges.bybit_exchange import BybitExchange
from src.core.config import Config

config = Config()

async def test():
    print("=== Binance ===")
    binance = BinanceExchange(config.BINANCE_API_KEY, config.BINANCE_API_SECRET)
    try:
        await binance.init()
        price = await binance.get_spot_price("BTC/USDT")
        print(f"BTC 현물가: ${price:,.2f}  OK")
        fr = await binance.get_futures_funding_rate("BTC/USDT")
        rate = fr["funding_rate"]
        print(f"펀딩피: {rate:.4f}%  연환산: {rate*3*365:.1f}%  OK")
        balance = await binance.get_balance("USDT")
        print(f"USDT 잔고: ${balance:,.2f}  OK")
    except Exception as e:
        print(f"오류: {str(e)[:150]}")
    finally:
        await binance.close()

    print()
    print("=== Bybit ===")
    bybit = BybitExchange(config.BYBIT_API_KEY, config.BYBIT_API_SECRET)
    try:
        await bybit.init()
        price = await bybit.get_spot_price("BTC/USDT")
        print(f"BTC 현물가: ${price:,.2f}  OK")
        fr = await bybit.get_futures_funding_rate("BTC/USDT")
        rate = fr["funding_rate"]
        print(f"펀딩피: {rate:.4f}%  연환산: {rate*3*365:.1f}%  OK")
        balance = await bybit.get_balance("USDT")
        print(f"USDT 잔고: ${balance:,.2f}  OK")
    except Exception as e:
        print(f"오류: {str(e)[:150]}")
    finally:
        await bybit.close()

asyncio.run(test())
