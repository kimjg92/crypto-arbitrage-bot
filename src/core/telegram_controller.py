"""
텔레그램 봇 컨트롤러
- 봇 시작/정지/상태 명령어
- 실시간 스캔 결과 수신
- 백테스트 실행
"""
import asyncio
from datetime import datetime
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes
from src.core.logger import setup_logger

logger = setup_logger()

COMMANDS_HELP = """
/start_bot   - 아비트라지 봇 시작
/stop_bot    - 아비트라지 봇 정지
/status      - 현재 상태 및 포지션 조회
/scan        - 즉시 기회 스캔
/backtest    - 백테스트 실행 (최근 90일)
/backtest30  - 백테스트 실행 (최근 30일)
/positions   - 활성 포지션 조회
/pnl         - 오늘 손익 조회
/help        - 명령어 도움말
"""

class TelegramController:
    def __init__(self, bot_token: str, chat_id: str, bot_runner):
        self.bot_token = bot_token
        self.chat_id = int(chat_id)
        self.bot_runner = bot_runner   # BotRunner 인스턴스 (main에서 주입)
        self.app: Application = None

    async def _check_auth(self, update: Update) -> bool:
        if update.effective_chat.id != self.chat_id:
            await update.message.reply_text("❌ 권한 없음")
            return False
        return True

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        await update.message.reply_text(
            f"<b>Crypto Arbitrage Bot 명령어</b>\n{COMMANDS_HELP}",
            parse_mode="HTML"
        )

    async def cmd_start_bot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        if self.bot_runner.is_running:
            await update.message.reply_text("⚠️ 봇이 이미 실행 중입니다.")
            return
        await update.message.reply_text("▶️ 봇 시작 중...")
        asyncio.create_task(self.bot_runner.start_strategies())
        logger.info("[텔레그램] 봇 시작 명령 수신")

    async def cmd_stop_bot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        if not self.bot_runner.is_running:
            await update.message.reply_text("⚠️ 봇이 실행 중이 아닙니다.")
            return
        await update.message.reply_text("⏹️ 봇 정지 중...")
        await self.bot_runner.stop_strategies()
        await update.message.reply_text("✅ 봇이 정지되었습니다.")
        logger.info("[텔레그램] 봇 정지 명령 수신")

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        status = self.bot_runner.get_status()
        await update.message.reply_text(status, parse_mode="HTML")

    async def cmd_scan(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        await update.message.reply_text("🔍 즉시 스캔 시작...")
        asyncio.create_task(self.bot_runner.manual_scan(update))

    async def cmd_backtest(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        await update.message.reply_text("⏳ 백테스트 실행 중... (1~2분 소요)")
        asyncio.create_task(self.bot_runner.run_backtest(update, days=90))

    async def cmd_backtest30(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        await update.message.reply_text("⏳ 백테스트 실행 중 (30일)...")
        asyncio.create_task(self.bot_runner.run_backtest(update, days=30))

    async def cmd_positions(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        msg = self.bot_runner.get_positions()
        await update.message.reply_text(msg, parse_mode="HTML")

    async def cmd_pnl(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        msg = self.bot_runner.get_daily_pnl()
        await update.message.reply_text(msg, parse_mode="HTML")

    async def start(self):
        self.app = Application.builder().token(self.bot_token).build()

        handlers = [
            ("help", self.cmd_help),
            ("start", self.cmd_help),
            ("start_bot", self.cmd_start_bot),
            ("stop_bot", self.cmd_stop_bot),
            ("status", self.cmd_status),
            ("scan", self.cmd_scan),
            ("backtest", self.cmd_backtest),
            ("backtest30", self.cmd_backtest30),
            ("positions", self.cmd_positions),
            ("pnl", self.cmd_pnl),
        ]
        for cmd, handler in handlers:
            self.app.add_handler(CommandHandler(cmd, handler))

        # 봇 명령어 메뉴 등록
        await self.app.bot.set_my_commands([
            BotCommand("start_bot",  "봇 시작"),
            BotCommand("stop_bot",   "봇 정지"),
            BotCommand("status",     "현재 상태"),
            BotCommand("scan",       "즉시 스캔"),
            BotCommand("positions",  "활성 포지션"),
            BotCommand("pnl",        "오늘 손익"),
            BotCommand("backtest",   "백테스트 90일"),
            BotCommand("backtest30", "백테스트 30일"),
            BotCommand("help",       "도움말"),
        ])

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        logger.info("텔레그램 컨트롤러 시작")

    async def stop(self):
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
