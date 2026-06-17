"""
BotRunner - 전략 실행 및 텔레그램 컨트롤러 연결 허브
"""
import asyncio
from datetime import datetime
from src.core.config import Config
from src.core.logger import setup_logger
from src.core.backtest import Backtester
from src.strategies.funding_rate import FundingRateStrategy
from src.strategies.cross_exchange import CrossExchangeStrategy
from src.utils.notifier import Notifier
from src.utils.risk_manager import RiskManager

logger = setup_logger()

class BotRunner:
    def __init__(self, exchanges: dict, config: Config, notifier: Notifier):
        self.exchanges = exchanges
        self.config = config
        self.notifier = notifier
        self.risk_manager = RiskManager(config)

        self.funding_strategy = FundingRateStrategy(exchanges, config, notifier)
        self.arb_strategy = CrossExchangeStrategy(exchanges, config, notifier)
        self.backtester = Backtester(config)

        self.is_running = False
        self._tasks: list[asyncio.Task] = []
        self.start_time: datetime = None

    async def start_strategies(self):
        if self.is_running:
            return
        self.is_running = True
        self.start_time = datetime.now()

        self._tasks = [
            asyncio.create_task(self.funding_strategy.run()),
            asyncio.create_task(self.arb_strategy.run()),
        ]
        logger.info("전략 시작됨")
        await self.notifier.send(
            "▶️ <b>봇 시작</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "✅ 펀딩피 아비트라지 실행 중\n"
            "✅ 거래소 간 차익거래 실행 중\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    async def stop_strategies(self):
        self.funding_strategy.stop()
        self.arb_strategy.stop()
        for t in self._tasks:
            t.cancel()
        self._tasks = []
        self.is_running = False
        logger.info("전략 정지됨")
        await self.notifier.send(
            "⏹️ <b>봇 정지</b>\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def get_status(self) -> str:
        uptime = ""
        if self.start_time and self.is_running:
            delta = datetime.now() - self.start_time
            h, m = divmod(int(delta.total_seconds()), 3600)
            m, s = divmod(m, 60)
            uptime = f"{h}시간 {m}분 {s}초"

        state = "▶️ 실행 중" if self.is_running else "⏹️ 정지"
        active_pos = len(self.funding_strategy.active_positions)

        # 잔고 조회 (비동기라 별도 표시)
        lines = [
            "📊 <b>봇 상태</b>",
            "━━━━━━━━━━━━━━━━━━━",
            f"상태:      {state}",
            f"가동시간:  {uptime or '-'}",
            f"활성 포지션: {active_pos}개",
            "━━━━━━━━━━━━━━━━━━━",
            "<b>오늘 수익</b>",
            f"펀딩피:   +${self.funding_strategy.daily_funding_income:.4f}",
            f"차익거래: +${self.arb_strategy.daily_arb_income:.4f}",
            f"수수료:   -${self.funding_strategy.daily_fee + self.arb_strategy.daily_fee:.4f}",
            "━━━━━━━━━━━━━━━━━━━",
            self.risk_manager.status(),
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        return "\n".join(lines)

    def get_positions(self) -> str:
        positions = self.funding_strategy.active_positions
        if not positions:
            return "📭 활성 포지션 없음"

        lines = [f"📋 <b>활성 포지션 ({len(positions)}개)</b>", "━━━━━━━━━━━━━━━━━━━"]
        for symbol, pos in positions.items():
            duration = str(datetime.now() - pos.enter_time).split(".")[0]
            lines.append(
                f"<b>{pos.exchange.upper()} {symbol}</b>\n"
                f"  투자금: ${pos.usdt_amount:.2f} | 보유: {duration}\n"
                f"  펀딩 누적: +${pos.funding_collected:.4f}"
            )
        return "\n".join(lines)

    def get_daily_pnl(self) -> str:
        funding_income = self.funding_strategy.daily_funding_income
        arb_income = self.arb_strategy.daily_arb_income
        total_fee = self.funding_strategy.daily_fee + self.arb_strategy.daily_fee
        net = funding_income + arb_income - total_fee
        emoji = "🟢" if net >= 0 else "🔴"
        lines = [
            f"{emoji} <b>오늘 손익</b>",
            "━━━━━━━━━━━━━━━━━━━",
            f"펀딩피 수익:  +${funding_income:.4f}",
            f"차익거래 수익: +${arb_income:.4f}",
            f"수수료:      -${total_fee:.4f}",
            "━━━━━━━━━━━━━━━━━━━",
            f"순손익: <b>${net:+.4f}</b>",
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        return "\n".join(lines)

    async def manual_scan(self, update):
        """즉시 스캔 후 결과를 텔레그램으로 전송"""
        opportunities = await self.funding_strategy.scan_opportunities()
        profitable = [o for o in opportunities if o.is_profitable]

        arb_opps = await self.arb_strategy.scan_opportunities()

        if not profitable and not arb_opps:
            await update.message.reply_text("🔍 현재 수익성 있는 기회 없음")
            return

        lines = ["🔍 <b>즉시 스캔 결과</b>", "━━━━━━━━━━━━━━━━━━━"]

        if profitable:
            lines.append(f"<b>펀딩피 기회 {len(profitable)}개</b>")
            for o in profitable[:3]:
                lines.append(
                    f"• {o.exchange.upper()} {o.symbol}\n"
                    f"  펀딩피: {o.funding_rate:+.4f}% | 연환산: {o.annual_rate:+.1f}%"
                )

        if arb_opps:
            lines.append(f"\n<b>차익거래 기회 {len(arb_opps)}개</b>")
            for o in arb_opps[:3]:
                lines.append(
                    f"• {o.symbol} {o.buy_exchange}→{o.sell_exchange}\n"
                    f"  순수익: {o.net_profit_pct:+.3f}%"
                )

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    def apply_setting(self, key: str, value):
        """텔레그램 /set 명령으로 변경된 설정을 런타임에 즉시 반영"""
        if key == "FUTURES_LEVERAGE":
            self.config.FUTURES_LEVERAGE = int(value)
            logger.info(f"레버리지 변경: {value}x")
        elif key == "MAX_POSITION_USDT":
            self.config.MAX_POSITION_USDT = float(value)
            self.risk_manager.config.MAX_POSITION_USDT = float(value)
        elif key == "MAX_TOTAL_USDT":
            self.config.MAX_TOTAL_USDT = float(value)
            self.risk_manager.config.MAX_TOTAL_USDT = float(value)
        elif key == "MAX_DAILY_LOSS_PCT":
            self.risk_manager.MAX_DAILY_LOSS = -self.config.MAX_TOTAL_USDT * float(value) / 100
        elif key == "MIN_FUNDING_RATE":
            self.config.MIN_FUNDING_RATE = float(value)
        elif key == "MIN_ARBITRAGE_SPREAD":
            self.config.MIN_ARBITRAGE_SPREAD = float(value)
        elif key == "ARBITRAGE_FEE_BUFFER":
            self.config.ARBITRAGE_FEE_BUFFER = float(value)
        elif key == "FUNDING_SCAN_INTERVAL":
            self.config.FUNDING_SCAN_INTERVAL = int(value)
        elif key == "ARBITRAGE_SCAN_INTERVAL":
            self.config.ARBITRAGE_SCAN_INTERVAL = int(value)
        elif key == "FUNDING_STRATEGY":
            if not value and self.funding_strategy.running:
                self.funding_strategy.stop()
            elif value and not self.funding_strategy.running and self.is_running:
                asyncio.create_task(self.funding_strategy.run())
        elif key == "ARBITRAGE_STRATEGY":
            if not value and self.arb_strategy.running:
                self.arb_strategy.stop()
            elif value and not self.arb_strategy.running and self.is_running:
                asyncio.create_task(self.arb_strategy.run())

    async def get_all_balances(self, update):
        """거래소별 Spot + Futures 잔고 조회"""
        from src.exchanges.account_manager import AccountManager
        lines = ["💰 <b>거래소별 잔고</b>", "━━━━━━━━━━━━━━━━━━━"]
        total_all = 0.0
        for ex_name, exchange in self.exchanges.items():
            try:
                acct = AccountManager(
                    ex_name,
                    getattr(self.config, f"{ex_name.upper()}_API_KEY", ""),
                    getattr(self.config, f"{ex_name.upper()}_API_SECRET", ""),
                )
                bal = await acct.get_all_balances("USDT")
                total_all += bal["total"]
                if bal["unified"]:
                    lines.append(f"<b>{ex_name.upper()}</b> (통합)\n  USDT: ${bal['total']:,.2f}")
                else:
                    lines.append(
                        f"<b>{ex_name.upper()}</b> (분리)\n"
                        f"  Spot:    ${bal['spot']:,.2f}\n"
                        f"  Futures: ${bal['futures']:,.2f}\n"
                        f"  합계:    ${bal['total']:,.2f}"
                    )
            except Exception as e:
                lines.append(f"<b>{ex_name.upper()}</b>: 조회 실패 ({e})")
        lines += [
            "━━━━━━━━━━━━━━━━━━━",
            f"전체 합계: <b>${total_all:,.2f} USDT</b>",
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def run_backtest(self, update, days: int = 90):
        try:
            await update.message.reply_text(f"⏳ 펀딩피 백테스트 ({days}일) 실행 중...")
            funding = await self.backtester.run_funding(days=days)
            self.backtester.print_report(funding, "펀딩피 백테스트")

            await update.message.reply_text("⏳ 거래소간 차익거래 백테스트 (7일) 실행 중...")
            arbitrage = await self.backtester.run_arbitrage(days=7)
            self.backtester.print_report(arbitrage, "차익거래 백테스트")

            msg = self.backtester.format_telegram(funding, arbitrage, days, 7)
            await update.message.reply_text(msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"백테스트 오류: {e}")
            await update.message.reply_text(f"❌ 백테스트 오류: {e}")
