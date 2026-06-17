"""
리스크 관리 모듈
- 전체 투자금 한도 체크
- 일일 손실 한도 체크
- 비상 청산 트리거
"""
from src.core.config import Config
from src.core.logger import setup_logger

logger = setup_logger()

class RiskManager:
    def __init__(self, config: Config):
        self.config = config
        self.daily_pnl = 0.0
        self.total_invested = 0.0
        self.MAX_DAILY_LOSS = -config.MAX_TOTAL_USDT * 0.02   # 일일 최대 손실 2%
        self.emergency_stop = False

    def check_can_enter(self, usdt_amount: float) -> tuple[bool, str]:
        if self.emergency_stop:
            return False, "비상 정지 활성화됨"
        if self.total_invested + usdt_amount > self.config.MAX_TOTAL_USDT:
            return False, f"전체 투자 한도 초과 ({self.total_invested:.0f}+{usdt_amount:.0f} > {self.config.MAX_TOTAL_USDT:.0f})"
        if self.daily_pnl < self.MAX_DAILY_LOSS:
            return False, f"일일 손실 한도 초과 ({self.daily_pnl:.2f})"
        return True, "OK"

    def update_pnl(self, pnl: float):
        self.daily_pnl += pnl
        if self.daily_pnl < self.MAX_DAILY_LOSS:
            logger.error(f"일일 손실 한도 도달! PnL: ${self.daily_pnl:.2f} → 비상 정지")
            self.emergency_stop = True

    def add_invested(self, amount: float):
        self.total_invested += amount

    def remove_invested(self, amount: float):
        self.total_invested = max(0, self.total_invested - amount)

    def reset_daily(self):
        self.daily_pnl = 0.0
        if self.emergency_stop:
            logger.info("일일 리셋 - 비상 정지 해제")
            self.emergency_stop = False

    def status(self) -> str:
        return (
            f"투자중: ${self.total_invested:.2f} / ${self.config.MAX_TOTAL_USDT:.2f} | "
            f"오늘 PnL: ${self.daily_pnl:.2f} | "
            f"비상정지: {'ON' if self.emergency_stop else 'OFF'}"
        )
