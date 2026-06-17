"""
텔레그램 알림 모듈
- 포착된 기회
- 포지션 진입
- 청산 후 손익 + 자산 변동
- 일일 리포트
"""
import asyncio
from datetime import datetime
from src.core.logger import setup_logger

logger = setup_logger()

class Notifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)
        self._bot = None

    async def _get_bot(self):
        if not self._bot:
            from telegram import Bot
            self._bot = Bot(token=self.bot_token)
        return self._bot

    async def send(self, message: str):
        if not self.enabled:
            logger.debug(f"[텔레그램 비활성] {message[:50]}")
            return
        try:
            bot = await self._get_bot()
            await bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"텔레그램 알림 실패: {e}")

    # ──────────────────────────────────────────
    # 펀딩피 기회 포착
    # ──────────────────────────────────────────
    async def notify_funding_opportunity(self, opp):
        msg = (
            f"🔍 <b>[펀딩피 기회 포착]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"거래소: {opp.exchange.upper()}\n"
            f"코인:   {opp.symbol}\n"
            f"펀딩피: <b>{opp.funding_rate:+.4f}%</b> (8h)\n"
            f"연환산: <b>{opp.annual_rate:+.1f}%</b>\n"
            f"현물가: ${opp.spot_price:,.4f}\n"
            f"선물가: ${opp.futures_price:,.4f}\n"
            f"베이시스: {opp.basis:+.3f}%\n"
            f"다음 지급: {opp.next_funding_time}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await self.send(msg)

    # ──────────────────────────────────────────
    # 차익거래 기회 포착
    # ──────────────────────────────────────────
    async def notify_arbitrage_opportunity(self, opp):
        msg = (
            f"⚡ <b>[차익거래 기회 포착]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"코인:   {opp.symbol}\n"
            f"매수:   {opp.buy_exchange.upper()} @ ${opp.buy_price:,.4f}\n"
            f"매도:   {opp.sell_exchange.upper()} @ ${opp.sell_price:,.4f}\n"
            f"스프레드: {opp.spread_pct:.3f}%\n"
            f"순수익:  <b>{opp.net_profit_pct:.3f}%</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await self.send(msg)

    # ──────────────────────────────────────────
    # 포지션 진입
    # ──────────────────────────────────────────
    async def notify_position_enter(
        self,
        strategy: str,
        symbol: str,
        exchange: str,
        usdt_amount: float,
        spot_price: float,
        futures_price: float,
        funding_rate: float = None,
        balance_before: float = None,
    ):
        if strategy == "funding":
            detail = (
                f"현물 매수 + 선물 숏 (델타 중립)\n"
                f"현물가:  ${spot_price:,.4f}\n"
                f"선물가:  ${futures_price:,.4f}\n"
                f"펀딩피:  {funding_rate:+.4f}% (8h)\n"
            )
        else:
            detail = (
                f"동시 매수/매도 차익거래\n"
                f"매수가:  ${spot_price:,.4f}\n"
                f"매도가:  ${futures_price:,.4f}\n"
            )

        balance_line = f"잔고 (진입 전): ${balance_before:,.2f}\n" if balance_before else ""

        msg = (
            f"✅ <b>[포지션 진입]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"전략:   {'펀딩피 아비트라지' if strategy == 'funding' else '거래소 간 차익거래'}\n"
            f"거래소: {exchange.upper()}\n"
            f"코인:   {symbol}\n"
            f"투자금: <b>${usdt_amount:,.2f}</b>\n"
            f"{detail}"
            f"{balance_line}"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await self.send(msg)

    # ──────────────────────────────────────────
    # 포지션 청산 + 손익 + 자산 변동
    # ──────────────────────────────────────────
    async def notify_position_exit(
        self,
        strategy: str,
        symbol: str,
        exchange: str,
        usdt_amount: float,
        entry_price: float,
        exit_price: float,
        realized_pnl: float,
        funding_collected: float = 0.0,
        total_fee: float = 0.0,
        balance_before: float = None,
        balance_after: float = None,
        hold_duration: str = None,
    ):
        net_pnl = realized_pnl + funding_collected - total_fee
        pnl_pct = net_pnl / usdt_amount * 100 if usdt_amount else 0
        emoji = "🟢" if net_pnl >= 0 else "🔴"

        funding_line = f"펀딩피 수취: +${funding_collected:.4f}\n" if funding_collected else ""
        fee_line = f"수수료:     -${total_fee:.4f}\n" if total_fee else ""
        duration_line = f"보유 기간:  {hold_duration}\n" if hold_duration else ""

        balance_line = ""
        if balance_before is not None and balance_after is not None:
            change = balance_after - balance_before
            change_sign = "+" if change >= 0 else ""
            balance_line = (
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"💰 <b>자산 변동</b>\n"
                f"청산 전: ${balance_before:,.2f}\n"
                f"청산 후: ${balance_after:,.2f}\n"
                f"변동:    <b>{change_sign}${change:,.4f}</b>\n"
            )

        msg = (
            f"{emoji} <b>[포지션 청산]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"전략:   {'펀딩피 아비트라지' if strategy == 'funding' else '거래소 간 차익거래'}\n"
            f"거래소: {exchange.upper()}\n"
            f"코인:   {symbol}\n"
            f"투자금: ${usdt_amount:,.2f}\n"
            f"진입가: ${entry_price:,.4f}\n"
            f"청산가: ${exit_price:,.4f}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>손익 내역</b>\n"
            f"가격 손익:  ${realized_pnl:+.4f}\n"
            f"{funding_line}"
            f"{fee_line}"
            f"순손익:    <b>${net_pnl:+.4f} ({pnl_pct:+.3f}%)</b>\n"
            f"{duration_line}"
            f"{balance_line}"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await self.send(msg)

    # ──────────────────────────────────────────
    # 일일 리포트
    # ──────────────────────────────────────────
    async def notify_daily_report(
        self,
        total_pnl: float,
        trade_count: int,
        win_count: int,
        funding_income: float,
        arb_income: float,
        total_fee: float,
        current_balance: float,
    ):
        win_rate = win_count / trade_count * 100 if trade_count else 0
        emoji = "🟢" if total_pnl >= 0 else "🔴"
        msg = (
            f"📈 <b>[일일 리포트]</b> {datetime.now().strftime('%Y-%m-%d')}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"총 거래:   {trade_count}건 (승률 {win_rate:.0f}%)\n"
            f"펀딩피 수익: +${funding_income:,.4f}\n"
            f"차익 수익:  +${arb_income:,.4f}\n"
            f"수수료:    -${total_fee:,.4f}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} 순수익: <b>${total_pnl:+,.4f}</b>\n"
            f"💰 현재 자산: <b>${current_balance:,.2f}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
        await self.send(msg)

    # ──────────────────────────────────────────
    # 에러 / 비상 알림
    # ──────────────────────────────────────────
    async def notify_error(self, title: str, detail: str):
        msg = (
            f"🚨 <b>[오류 발생]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{title}\n"
            f"{detail}\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await self.send(msg)

    async def notify_emergency_stop(self, reason: str, balance: float = None):
        balance_line = f"현재 자산: ${balance:,.2f}\n" if balance else ""
        msg = (
            f"🛑 <b>[비상 정지]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"사유: {reason}\n"
            f"{balance_line}"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await self.send(msg)
