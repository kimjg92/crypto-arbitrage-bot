import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Binance
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
    BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

    # Bybit
    BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
    BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")

    # MEXC
    MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
    MEXC_API_SECRET = os.getenv("MEXC_API_SECRET", "")

    # Gate.io
    GATEIO_API_KEY = os.getenv("GATEIO_API_KEY", "")
    GATEIO_API_SECRET = os.getenv("GATEIO_API_SECRET", "")

    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # 리스크 한도
    MAX_POSITION_USDT = float(os.getenv("MAX_POSITION_USDT", "100"))
    MAX_TOTAL_USDT = float(os.getenv("MAX_TOTAL_USDT", "500"))

    # 펀딩피 전략 설정
    MIN_FUNDING_RATE = float(os.getenv("MIN_FUNDING_RATE", "0.01"))
    MIN_ANNUAL_RATE = 10.0

    # 거래소 간 아비트라지 설정
    MIN_ARBITRAGE_SPREAD = float(os.getenv("MIN_ARBITRAGE_SPREAD", "0.3"))
    ARBITRAGE_FEE_BUFFER = 0.2

    # 모니터링 주기 (초)
    FUNDING_SCAN_INTERVAL = 60
    ARBITRAGE_SCAN_INTERVAL = 5

    # 수수료 (테이커 기준 — 시장가 주문 시 적용)
    BINANCE_SPOT_FEE     = 0.10   # 기본 0.10%, BNB 결제 시 0.075%
    BINANCE_FUTURES_FEE  = 0.05
    BYBIT_SPOT_FEE       = 0.10
    BYBIT_FUTURES_FEE    = 0.055
    MEXC_SPOT_FEE        = 0.05   # 테이커 0.05% (메이커 0%)
    MEXC_FUTURES_FEE     = 0.01   # 테이커 0.01%
    GATEIO_SPOT_FEE      = 0.10
    GATEIO_FUTURES_FEE   = 0.05
    HYPERLIQUID_FEE      = 0.05   # 테이커 0.05% (메이커 -0.002%)
    HYPERLIQUID_MAKER_FEE = -0.002 # 메이커 리베이트 (수익)

    # 슬리피지 추정 (시장가 주문 시 추가 비용)
    SLIPPAGE_HIGH_LIQ    = 0.02   # Binance/Bybit 등 고유동성 (%)
    SLIPPAGE_MID_LIQ     = 0.05   # Gate.io 등 중간 유동성 (%)
    SLIPPAGE_LOW_LIQ     = 0.15   # MEXC 알트코인 등 저유동성 (%)

    # 레버리지 설정 (펀딩피 아비트라지 선물 포지션)
    FUTURES_LEVERAGE     = int(os.getenv("FUTURES_LEVERAGE", "2"))  # 기본 2x
    MAX_FUTURES_LEVERAGE = 3       # 최대 3x (안전 한도)

    # 대상 코인
    TARGET_SYMBOLS = [
        "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT",
        "XRP/USDT", "DOGE/USDT", "ADA/USDT", "AVAX/USDT",
    ]

    # ── 자본 단계별 거래소 조합 ──────────────────────────
    # 각 단계에서 활성화할 거래소 목록
    # 소액: 유동성 낮은 거래소(스프레드 큼) 위주
    # 대액: 유동성 높은 거래소 위주
    EXCHANGE_PHASES = [
        {
            "label": "Phase 1 - 테스트",
            "min_usdt": 0,
            "max_usdt": 500,
            "exchanges": ["binance", "mexc", "gateio"],
            "reason": "소액 → 유동성 낮은 거래소 스프레드 극대화",
        },
        {
            "label": "Phase 2 - 초기 운영",
            "min_usdt": 500,
            "max_usdt": 2000,
            "exchanges": ["binance", "bybit", "mexc", "gateio"],
            "reason": "4개 거래소 12방향 스캔, 혼합 전략",
        },
        {
            "label": "Phase 3 - 안정 운영",
            "min_usdt": 2000,
            "max_usdt": 10000,
            "exchanges": ["binance", "bybit", "gateio"],
            "reason": "슬리피지 관리 필요 → 유동성 높은 거래소 비중 확대",
        },
        {
            "label": "Phase 4 - 대규모",
            "min_usdt": 10000,
            "max_usdt": 999999,
            "exchanges": ["binance", "bybit"],
            "reason": "최고 유동성만 사용, 안정성 최우선",
        },
    ]

    @classmethod
    def get_active_exchanges(cls, total_usdt: float) -> list[str]:
        """총 자본 기준으로 활성화할 거래소 목록 반환"""
        for phase in cls.EXCHANGE_PHASES:
            if phase["min_usdt"] <= total_usdt < phase["max_usdt"]:
                return phase["exchanges"]
        return ["binance", "bybit"]

    @classmethod
    def get_current_phase(cls, total_usdt: float) -> dict:
        for phase in cls.EXCHANGE_PHASES:
            if phase["min_usdt"] <= total_usdt < phase["max_usdt"]:
                return phase
        return cls.EXCHANGE_PHASES[-1]

    @classmethod
    def get_fee(cls, exchange_name: str, market: str = "spot") -> float:
        fee_map = {
            "binance":     {"spot": cls.BINANCE_SPOT_FEE,    "futures": cls.BINANCE_FUTURES_FEE},
            "bybit":       {"spot": cls.BYBIT_SPOT_FEE,      "futures": cls.BYBIT_FUTURES_FEE},
            "mexc":        {"spot": cls.MEXC_SPOT_FEE,       "futures": cls.MEXC_FUTURES_FEE},
            "gateio":      {"spot": cls.GATEIO_SPOT_FEE,     "futures": cls.GATEIO_FUTURES_FEE},
            "hyperliquid": {"spot": cls.HYPERLIQUID_FEE,     "futures": cls.HYPERLIQUID_FEE},
        }
        return fee_map.get(exchange_name, {}).get(market, 0.1)

    @classmethod
    def get_slippage(cls, exchange_name: str) -> float:
        """거래소 유동성 기반 슬리피지 추정값"""
        high_liq = {"binance", "bybit", "hyperliquid"}
        mid_liq  = {"gateio"}
        if exchange_name in high_liq:
            return cls.SLIPPAGE_HIGH_LIQ
        elif exchange_name in mid_liq:
            return cls.SLIPPAGE_MID_LIQ
        return cls.SLIPPAGE_LOW_LIQ  # mexc 등

    @classmethod
    def get_round_trip_cost(cls, buy_ex: str, sell_ex: str) -> float:
        """왕복 실질 비용 = 수수료 + 슬리피지 (양쪽 합산)"""
        buy_fee  = cls.get_fee(buy_ex, "spot")
        sell_fee = cls.get_fee(sell_ex, "spot")
        buy_slip = cls.get_slippage(buy_ex)
        sell_slip = cls.get_slippage(sell_ex)
        return buy_fee + sell_fee + buy_slip + sell_slip

    @classmethod
    def get_funding_round_trip_cost(cls, exchange_name: str) -> float:
        """펀딩피 전략 진입+청산 왕복 비용 (현물 + 선물 각각 2회)"""
        spot_fee    = cls.get_fee(exchange_name, "spot")
        futures_fee = cls.get_fee(exchange_name, "futures")
        slippage    = cls.get_slippage(exchange_name)
        return (spot_fee + futures_fee + slippage) * 2  # 진입 + 청산
