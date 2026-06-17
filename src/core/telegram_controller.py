"""
텔레그램 봇 컨트롤러
- 봇 시작/정지/상태 명령어
- 실시간 설정 변경 (/set)
- 백테스트, 스캔, 포지션 조회
"""
import asyncio
from datetime import datetime
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes
from src.core.logger import setup_logger
from src.core import settings_manager as sm

logger = setup_logger()


class TelegramController:
    def __init__(self, bot_token: str, chat_id: str, bot_runner):
        self.bot_token = bot_token
        self.chat_id = int(chat_id)
        self.bot_runner = bot_runner
        self.app: Application = None

    async def _check_auth(self, update: Update) -> bool:
        if update.effective_chat.id != self.chat_id:
            await update.message.reply_text("❌ 권한 없음")
            return False
        return True

    # ── 기본 제어 ──────────────────────────────────────
    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        msg = (
            "<b>Crypto Arbitrage Bot 명령어</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "<b>[봇 제어]</b>\n"
            "/start_bot   - 봇 시작\n"
            "/stop_bot    - 봇 정지\n"
            "/status      - 현재 상태\n"
            "/scan        - 즉시 기회 스캔\n"
            "\n<b>[조회]</b>\n"
            "/positions   - 활성 포지션\n"
            "/pnl         - 오늘 손익\n"
            "/phase       - 자본 단계 조회\n"
            "/balances    - 거래소별 잔고\n"
            "\n<b>[설정]</b>\n"
            "/settings    - 현재 설정값 전체 조회\n"
            "/sethelp     - 변경 가능한 항목 목록\n"
            "/set [항목] [값]  - 설정 변경\n"
            "\n<b>[백테스트]</b>\n"
            "/backtest    - 백테스트 90일\n"
            "/backtest30  - 백테스트 30일\n"
            "/help        - 이 도움말"
        )
        await update.message.reply_text(msg, parse_mode="HTML")

    async def cmd_start_bot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        if self.bot_runner.is_running:
            await update.message.reply_text("⚠️ 이미 실행 중입니다.")
            return
        await update.message.reply_text("▶️ 봇 시작 중...")
        asyncio.create_task(self.bot_runner.start_strategies())

    async def cmd_stop_bot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        if not self.bot_runner.is_running:
            await update.message.reply_text("⚠️ 실행 중이 아닙니다.")
            return
        await update.message.reply_text("⏹️ 봇 정지 중...")
        await self.bot_runner.stop_strategies()
        await update.message.reply_text("✅ 봇 정지 완료")

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        await update.message.reply_text(self.bot_runner.get_status(), parse_mode="HTML")

    async def cmd_scan(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        await update.message.reply_text("🔍 즉시 스캔 시작...")
        asyncio.create_task(self.bot_runner.manual_scan(update))

    async def cmd_positions(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        await update.message.reply_text(self.bot_runner.get_positions(), parse_mode="HTML")

    async def cmd_pnl(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        await update.message.reply_text(self.bot_runner.get_daily_pnl(), parse_mode="HTML")

    async def cmd_balances(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        await update.message.reply_text("💰 잔고 조회 중...")
        asyncio.create_task(self.bot_runner.get_all_balances(update))

    # ── 설정 제어 ──────────────────────────────────────
    async def cmd_settings(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        await update.message.reply_text(sm.get_all_status(), parse_mode="HTML")

    async def cmd_sethelp(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        await update.message.reply_text(sm.get_help_text(), parse_mode="HTML")

    async def cmd_set(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        args = ctx.args
        if not args or len(args) < 2:
            await update.message.reply_text(
                "사용법: /set [항목] [값]\n예: /set FUTURES_LEVERAGE 3\n\n"
                "항목 목록: /sethelp",
                parse_mode="HTML"
            )
            return
        key = args[0].upper()
        value = args[1]
        ok, msg = sm.set_value(key, value)
        # 봇 러너에도 즉시 반영
        if ok:
            self.bot_runner.apply_setting(key, sm.get(key))
        await update.message.reply_text(msg, parse_mode="HTML")

    # ── 자본 단계 ──────────────────────────────────────
    async def cmd_phase(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        from src.core.config import Config
        config = Config()
        total = sm.get("MAX_TOTAL_USDT") or config.MAX_TOTAL_USDT
        phase = config.get_current_phase(total)
        lines = [
            "📊 <b>자본 단계별 거래소 조합</b>",
            "━━━━━━━━━━━━━━━━━━━",
        ]
        for p in config.EXCHANGE_PHASES:
            mark = "👉 " if p["label"] == phase["label"] else "    "
            lines.append(
                f"{mark}<b>{p['label']}</b>\n"
                f"    ${p['min_usdt']:,} ~ ${p['max_usdt']:,}\n"
                f"    거래소: {', '.join(p['exchanges']).upper()}\n"
                f"    사유: {p['reason']}"
            )
        lines += ["━━━━━━━━━━━━━━━━━━━", f"현재 기준 자본: ${total:,.0f}"]
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    # ── 백테스트 ──────────────────────────────────────
    async def cmd_backtest(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        await update.message.reply_text("⏳ 백테스트 실행 중...")
        asyncio.create_task(self.bot_runner.run_backtest(update, days=90))

    async def cmd_backtest30(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        await update.message.reply_text("⏳ 백테스트 실행 중 (30일)...")
        asyncio.create_task(self.bot_runner.run_backtest(update, days=30))

    # ── 앱 등록 & 시작 ────────────────────────────────
    async def start(self):
        self.app = Application.builder().token(self.bot_token).build()

        handlers = [
            ("help",        self.cmd_help),
            ("start",       self.cmd_help),
            ("start_bot",   self.cmd_start_bot),
            ("stop_bot",    self.cmd_stop_bot),
            ("status",      self.cmd_status),
            ("scan",        self.cmd_scan),
            ("positions",   self.cmd_positions),
            ("pnl",         self.cmd_pnl),
            ("balances",    self.cmd_balances),
            ("settings",    self.cmd_settings),
            ("sethelp",     self.cmd_sethelp),
            ("set",         self.cmd_set),
            ("phase",       self.cmd_phase),
            ("backtest",    self.cmd_backtest),
            ("backtest30",  self.cmd_backtest30),
        ]
        for cmd, handler in handlers:
            self.app.add_handler(CommandHandler(cmd, handler))

        await self.app.bot.set_my_commands([
            BotCommand("start_bot",  "봇 시작"),
            BotCommand("stop_bot",   "봇 정지"),
            BotCommand("status",     "현재 상태"),
            BotCommand("scan",       "즉시 스캔"),
            BotCommand("positions",  "활성 포지션"),
            BotCommand("pnl",        "오늘 손익"),
            BotCommand("balances",   "거래소 잔고"),
            BotCommand("settings",   "현재 설정 조회"),
            BotCommand("sethelp",    "변경 가능 항목"),
            BotCommand("set",        "설정 변경"),
            BotCommand("phase",      "자본 단계"),
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
