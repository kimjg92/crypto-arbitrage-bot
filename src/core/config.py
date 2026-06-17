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

    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # 리스크 한도
    MAX_POSITION_USDT = float(os.getenv("MAX_POSITION_USDT", "100"))
    MAX_TOTAL_USDT = float(os.getenv("MAX_TOTAL_USDT", "500"))

    # 펀딩피 전략 설정
    MIN_FUNDING_RATE = float(os.getenv("MIN_FUNDING_RATE", "0.01"))       # 최소 0.01% per 8h = 연 10.95%
    MIN_ANNUAL_RATE = 10.0                                                  # 연환산 최소 수익률 (%)

    # 거래소 간 아비트라지 설정
    MIN_ARBITRAGE_SPREAD = float(os.getenv("MIN_ARBITRAGE_SPREAD", "0.3")) # 최소 스프레드 (%)
    ARBITRAGE_FEE_BUFFER = 0.2                                              # 수수료 버퍼 (%)

    # 모니터링 주기 (초)
    FUNDING_SCAN_INTERVAL = 60
    ARBITRAGE_SCAN_INTERVAL = 5

    # 수수료 (Binance/Bybit VIP0 기준)
    BINANCE_SPOT_FEE = 0.1       # %
    BINANCE_FUTURES_FEE = 0.05   # %
    BYBIT_SPOT_FEE = 0.1         # %
    BYBIT_FUTURES_FEE = 0.055    # %

    # 대상 코인 (시가총액 상위 안정적 코인만)
    TARGET_SYMBOLS = [
        "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT",
        "XRP/USDT", "DOGE/USDT", "ADA/USDT", "AVAX/USDT",
    ]
