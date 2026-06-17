"""
Crypto Arbitrage Bot v1.1.0
- 전략 1: 현물-선물 펀딩피 아비트라지
- 전략 2: 거래소 간 현물 차익거래
- 텔레그램으로 시작/정지/상태/백테스트 제어
"""
import asyncio
import sys
import os
from pathlib import Path

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
    os.chdir(BASE_DIR)
else:
    BASE_DIR = Path(__file__).parent

sys.path.insert(0, str(BASE_DIR))

from src.core.config import Config
from src.core.logger import setup_logger
from src.core.bot_runner import BotRunner
from src.core.telegram_controller import TelegramController
from src.exchanges.binance_exchange import BinanceExchange
from src.exchanges.bybit_exchange import BybitExchange
from src.utils.notifier import Notifier

logger = setup_logger()

def print_banner():
    print("=" * 54)
    print("  Crypto Arbitrage Bot  v1.1.0")
    print("  Strategy: Funding Rate + Cross-Exchange Arbitrage")
    print("  Exchange: Binance + Bybit")
    print("  Control:  Telegram @jk_arb_api_telbot")
    print("=" * 54)
    print()

async def main():
    print_banner()

    config = Config()
    notifier = Notifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)

    # 거래소 연결
    logger.info("거래소 연결 중...")
    exchanges = {}

    for name, cls, key, secret in [
        ("binance", BinanceExchange, config.BINANCE_API_KEY, config.BINANCE_API_SECRET),
        ("bybit",   BybitExchange,   config.BYBIT_API_KEY,   config.BYBIT_API_SECRET),
    ]:
        try:
            ex = cls(key, secret)
            await ex.init()
            exchanges[name] = ex
        except Exception as e:
            logger.error(f"{name} 연결 실패: {e}")

    if not exchanges:
        logger.error("연결된 거래소 없음. .env 확인 필요.")
        input("엔터를 눌러 종료...")
        return

    logger.info(f"연결된 거래소: {', '.join(exchanges.keys())}")

    # BotRunner + 텔레그램 컨트롤러 초기화
    runner = BotRunner(exchanges, config, notifier)
    controller = TelegramController(
        config.TELEGRAM_BOT_TOKEN,
        config.TELEGRAM_CHAT_ID,
        runner,
    )

    # 시작 알림
    await notifier.send(
        "🤖 <b>Crypto Arbitrage Bot 켜짐</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"거래소: {', '.join(exchanges.keys()).upper()}\n"
        "텔레그램으로 제어 가능\n"
        "/start_bot  - 봇 시작\n"
        "/stop_bot   - 봇 정지\n"
        "/status     - 상태 조회\n"
        "/backtest   - 백테스트\n"
        "/help       - 전체 명령어"
    )

    logger.info("텔레그램 컨트롤러 시작...")
    logger.info("텔레그램에서 /start_bot 으로 봇을 시작하세요.")
    logger.info("종료: Ctrl+C")

    try:
        await controller.start()
        # 텔레그램 폴링이 블로킹 실행됨 — 종료 신호 대기
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("종료 신호 수신")
    finally:
        await runner.stop_strategies()
        await controller.stop()
        for ex in exchanges.values():
            await ex.close()
        await notifier.send("🔴 <b>봇 종료됨</b>")
        logger.info("봇 종료 완료")

if __name__ == "__main__":
    asyncio.run(main())
