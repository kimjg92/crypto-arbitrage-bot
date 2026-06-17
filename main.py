"""
Crypto Arbitrage Bot
- 전략 1: 현물-선물 펀딩피 아비트라지
- 전략 2: 거래소 간 현물 차익거래
"""
import asyncio
import sys
import os
from pathlib import Path

# EXE 실행 시 경로 처리
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
    os.chdir(BASE_DIR)
else:
    BASE_DIR = Path(__file__).parent

sys.path.insert(0, str(BASE_DIR))

from src.core.config import Config
from src.core.logger import setup_logger
from src.exchanges.binance_exchange import BinanceExchange
from src.exchanges.bybit_exchange import BybitExchange
from src.strategies.funding_rate import FundingRateStrategy
from src.strategies.cross_exchange import CrossExchangeStrategy
from src.utils.notifier import Notifier
from src.utils.risk_manager import RiskManager

logger = setup_logger()

def check_env():
    """API 키 설정 확인"""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        logger.error(".env 파일이 없습니다. .env.example을 복사하여 .env를 만들고 API 키를 입력하세요.")
        return False
    config = Config()
    if not config.BINANCE_API_KEY or config.BINANCE_API_KEY == "your_binance_api_key_here":
        logger.warning("Binance API 키가 설정되지 않았습니다. 모니터링 전용 모드로 실행합니다.")
    if not config.BYBIT_API_KEY or config.BYBIT_API_KEY == "your_bybit_api_key_here":
        logger.warning("Bybit API 키가 설정되지 않았습니다. 모니터링 전용 모드로 실행합니다.")
    return True

def print_banner():
    banner = """
╔══════════════════════════════════════════════════════╗
║          Crypto Arbitrage Bot v1.0.0                 ║
║  전략: 펀딩피 아비트라지 + 거래소 간 차익거래           ║
║  거래소: Binance + Bybit                             ║
╚══════════════════════════════════════════════════════╝
    """
    print(banner)

async def main():
    print_banner()

    if not check_env():
        input("\n엔터를 눌러 종료...")
        return

    config = Config()
    notifier = Notifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)
    risk_manager = RiskManager(config)

    # 거래소 초기화
    logger.info("거래소 연결 중...")
    exchanges = {}

    binance = BinanceExchange(config.BINANCE_API_KEY, config.BINANCE_API_SECRET)
    bybit = BybitExchange(config.BYBIT_API_KEY, config.BYBIT_API_SECRET)

    try:
        await binance.init()
        exchanges["binance"] = binance
    except Exception as e:
        logger.error(f"Binance 연결 실패: {e}")

    try:
        await bybit.init()
        exchanges["bybit"] = bybit
    except Exception as e:
        logger.error(f"Bybit 연결 실패: {e}")

    if not exchanges:
        logger.error("연결된 거래소가 없습니다. .env 파일의 API 키를 확인하세요.")
        input("\n엔터를 눌러 종료...")
        return

    logger.info(f"연결된 거래소: {', '.join(exchanges.keys())}")
    logger.info(f"모니터링 대상: {', '.join(config.TARGET_SYMBOLS)}")
    logger.info(f"최대 포지션: ${config.MAX_POSITION_USDT} | 총 한도: ${config.MAX_TOTAL_USDT}")
    logger.info("")
    logger.info("전략 실행 중... (중지: Ctrl+C)")
    logger.info("")

    # 전략 초기화
    funding_strategy = FundingRateStrategy(exchanges, config, notifier)
    arbitrage_strategy = CrossExchangeStrategy(exchanges, config, notifier)

    try:
        await asyncio.gather(
            funding_strategy.run(),
            arbitrage_strategy.run(),
        )
    except KeyboardInterrupt:
        logger.info("사용자 종료 요청")
    finally:
        funding_strategy.stop()
        arbitrage_strategy.stop()
        for ex in exchanges.values():
            await ex.close()
        logger.info("봇 종료 완료")
        logger.info(f"최종 리스크 상태: {risk_manager.status()}")

if __name__ == "__main__":
    asyncio.run(main())
