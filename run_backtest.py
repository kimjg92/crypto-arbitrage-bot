"""백테스트 단독 실행 - 펀딩피 + 거래소 간 차익거래"""
import asyncio
import sys
sys.path.insert(0, "D:/crypto-arbitrage-bot")

from src.core.config import Config
from src.core.backtest import Backtester

async def main():
    config = Config()
    bt = Backtester(config)

    print("\n[1/2] 펀딩피 아비트라지 백테스트 (90일)...")
    funding = await bt.run_funding(days=90)
    bt.print_report(funding, "펀딩피 아비트라지 백테스트 결과")

    print("\n[2/2] 거래소 간 차익거래 백테스트 (7일, 1분봉)...")
    arbitrage = await bt.run_arbitrage(days=7)
    bt.print_report(arbitrage, "거래소 간 차익거래 백테스트 결과")

asyncio.run(main())
