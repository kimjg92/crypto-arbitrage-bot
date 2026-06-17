"""
Crypto Arbitrage Bot v1.2.0
- 전략 1: 현물-선물 펀딩피 아비트라지
- 전략 2: 거래소 간 현물 차익거래
- 자본 단계별 거래소 자동 선택 (Phase 1~4)
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
from src.exchanges.mexc_exchange import MexcExchange
from src.exchanges.gateio_exchange import GateioExchange
from src.utils.notifier import Notifier

logger = setup_logger()

EXCHANGE_CLASSES = {
    "binance": (BinanceExchange, lambda c: (c.BINANCE_API_KEY, c.BINANCE_API_SECRET)),
    "bybit":   (BybitExchange,   lambda c: (c.BYBIT_API_KEY,   c.BYBIT_API_SECRET)),
    "mexc":    (MexcExchange,    lambda c: (c.MEXC_API_KEY,    c.MEXC_API_SECRET)),
    "gateio":  (GateioExchange,  lambda c: (c.GATEIO_API_KEY,  c.GATEIO_API_SECRET)),
}

def print_banner(phase: dict, active: list[str]):
    print("=" * 58)
    print("  Crypto Arbitrage Bot  v1.2.0")
    print(f"  {phase['label']}")
    print(f"  거래소: {' + '.join(e.upper() for e in active)}")
    print(f"  이유: {phase['reason']}")
    print("  제어: Telegram @jk_arb_api_telbot")
    print("=" * 58)
    print()

async def connect_exchanges(config: Config, active_names: list[str]) -> dict:
    exchanges = {}
    for name in active_names:
        if name not in EXCHANGE_CLASSES:
            continue
        cls, key_fn = EXCHANGE_CLASSES[name]
        key, secret = key_fn(config)
        if not key or key.startswith("your_"):
            logger.warning(f"{name} API 키 미설정 - 스킵")
            continue
        try:
            ex = cls(key, secret)
            await ex.init()
            exchanges[name] = ex
            logger.info(f"{name} 연결 완료")
        except Exception as e:
            logger.error(f"{name} 연결 실패: {e}")
    return exchanges

async def main():
    config = Config()
    notifier = Notifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)

    # 자본 기준 단계 결정 (MAX_TOTAL_USDT 기준)
    phase = config.get_current_phase(config.MAX_TOTAL_USDT)
    active_names = phase["exchanges"]

    print_banner(phase, active_names)
    logger.info(f"자본 단계: {phase['label']} (기준: ${config.MAX_TOTAL_USDT:.0f})")
    logger.info(f"활성 거래소: {active_names}")

    exchanges = await connect_exchanges(config, active_names)

    if not exchanges:
        logger.error("연결된 거래소 없음. .env 확인 필요.")
        input("엔터를 눌러 종료...")
        return

    runner = BotRunner(exchanges, config, notifier)
    controller = TelegramController(
        config.TELEGRAM_BOT_TOKEN,
        config.TELEGRAM_CHAT_ID,
        runner,
    )

    ex_list = ", ".join(e.upper() for e in exchanges.keys())
    await notifier.send(
        "🤖 <b>Crypto Arbitrage Bot v1.2 켜짐</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"단계: <b>{phase['label']}</b>\n"
        f"거래소: {ex_list}\n"
        f"사유: {phase['reason']}\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "/start_bot  - 봇 시작\n"
        "/stop_bot   - 봇 정지\n"
        "/status     - 상태 조회\n"
        "/phase      - 현재 단계 조회\n"
        "/backtest   - 백테스트\n"
        "/help       - 전체 명령어"
    )

    logger.info("텔레그램에서 /start_bot 으로 봇을 시작하세요.")

    try:
        await controller.start()
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
