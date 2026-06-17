"""백테스트 단독 실행 스크립트"""
import asyncio
import sys
sys.path.insert(0, "D:/crypto-arbitrage-bot")

from src.core.config import Config
from src.core.backtest import Backtester

async def main():
    config = Config()
    bt = Backtester(config)
    print("백테스트 시작 (최근 30일)...\n")
    results = await bt.run(days=30)
    bt.print_report(results)

asyncio.run(main())
