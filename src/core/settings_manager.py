"""
런타임 설정 관리자
- 텔레그램으로 실시간 파라미터 변경
- 변경사항 .env 파일에 자동 저장 (재시작 후에도 유지)
- 변경 이력 로깅
"""
import os
import re
from pathlib import Path
from datetime import datetime
from src.core.logger import setup_logger

logger = setup_logger()

ENV_PATH = Path(__file__).parent.parent.parent / ".env"

# 제어 가능한 파라미터 정의
# key: (설명, 타입, 최솟값, 최댓값, 단위)
CONTROLLABLE_PARAMS = {
    # ── ON/OFF ──────────────────────────────────
    "AUTO_TRADE":          ("자동 주문 실행",      bool,  None, None, "on/off"),
    "FUNDING_STRATEGY":    ("펀딩피 전략",          bool,  None, None, "on/off"),
    "ARBITRAGE_STRATEGY":  ("차익거래 전략",        bool,  None, None, "on/off"),
    "TELEGRAM_NOTIFY":     ("텔레그램 알림",        bool,  None, None, "on/off"),

    # ── 레버리지 & 리스크 ────────────────────────
    "FUTURES_LEVERAGE":    ("선물 레버리지",        int,   1,    3,    "배"),
    "MAX_POSITION_USDT":   ("포지션당 최대금액",    float, 10,   10000,"USDT"),
    "MAX_TOTAL_USDT":      ("전체 최대투자금",      float, 50,   50000,"USDT"),
    "MAX_DAILY_LOSS_PCT":  ("일일 최대손실 한도",   float, 0.5,  10,   "%"),

    # ── 전략 임계값 ──────────────────────────────
    "MIN_FUNDING_RATE":    ("최소 펀딩피 기준",     float, 0.001,1.0,  "%/8h"),
    "MIN_ARBITRAGE_SPREAD":("최소 차익 스프레드",   float, 0.1,  5.0,  "%"),
    "ARBITRAGE_FEE_BUFFER":("차익 수수료 버퍼",     float, 0.0,  1.0,  "%"),

    # ── 스캔 주기 ────────────────────────────────
    "FUNDING_SCAN_INTERVAL":   ("펀딩피 스캔 주기",     int, 10, 3600, "초"),
    "ARBITRAGE_SCAN_INTERVAL": ("차익거래 스캔 주기",   int, 1,  60,   "초"),
}

# 런타임 상태 (메모리, 재시작 시 .env 값으로 초기화)
_runtime: dict = {}


def _load_env_value(key: str):
    """현재 .env 파일에서 값 읽기"""
    if not ENV_PATH.exists():
        return None
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return None


def get(key: str):
    """현재 런타임 값 조회 (없으면 .env → 기본값 순)"""
    if key in _runtime:
        return _runtime[key]
    raw = _load_env_value(key)
    if raw is not None:
        return _parse(key, raw)
    # 기본값
    defaults = {
        "AUTO_TRADE": False,
        "FUNDING_STRATEGY": True,
        "ARBITRAGE_STRATEGY": True,
        "TELEGRAM_NOTIFY": True,
        "FUTURES_LEVERAGE": 2,
        "MAX_POSITION_USDT": 100.0,
        "MAX_TOTAL_USDT": 500.0,
        "MAX_DAILY_LOSS_PCT": 2.0,
        "MIN_FUNDING_RATE": 0.01,
        "MIN_ARBITRAGE_SPREAD": 0.3,
        "ARBITRAGE_FEE_BUFFER": 0.2,
        "FUNDING_SCAN_INTERVAL": 60,
        "ARBITRAGE_SCAN_INTERVAL": 5,
    }
    return defaults.get(key)


def set_value(key: str, raw_value: str) -> tuple[bool, str]:
    """
    텔레그램 명령으로 값 변경
    반환: (성공 여부, 결과 메시지)
    """
    if key not in CONTROLLABLE_PARAMS:
        return False, f"알 수 없는 파라미터: {key}"

    desc, typ, vmin, vmax, unit = CONTROLLABLE_PARAMS[key]

    try:
        new_val = _parse(key, raw_value)
    except Exception as e:
        return False, f"값 형식 오류: {e}"

    # 범위 검사
    if typ in (int, float) and vmin is not None and vmax is not None:
        if not (vmin <= new_val <= vmax):
            return False, f"범위 초과: {vmin}~{vmax} {unit}"

    old_val = get(key)
    _runtime[key] = new_val
    _save_to_env(key, raw_value)

    logger.info(f"[설정 변경] {key}: {old_val} → {new_val}")
    return True, f"✅ {desc} 변경\n{old_val} → <b>{new_val} {unit}</b>"


def _parse(key: str, raw: str):
    if key not in CONTROLLABLE_PARAMS:
        return raw
    _, typ, *_ = CONTROLLABLE_PARAMS[key]
    if typ == bool:
        return raw.strip().lower() in ("1", "true", "on", "yes")
    return typ(raw.strip())


def _save_to_env(key: str, value: str):
    """변경사항을 .env 파일에 즉시 저장"""
    if not ENV_PATH.exists():
        return
    content = ENV_PATH.read_text(encoding="utf-8")
    pattern = rf"^{re.escape(key)}=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        content += f"\n{key}={value}"
    ENV_PATH.write_text(content, encoding="utf-8")


def get_all_status() -> str:
    """전체 설정 현황 텔레그램 메시지"""
    lines = [
        "⚙️ <b>현재 설정값</b>",
        "━━━━━━━━━━━━━━━━━━━",
        "<b>[ON/OFF]</b>",
    ]
    for key in ["AUTO_TRADE", "FUNDING_STRATEGY", "ARBITRAGE_STRATEGY", "TELEGRAM_NOTIFY"]:
        desc, *_, unit = CONTROLLABLE_PARAMS[key]
        val = get(key)
        icon = "✅" if val else "❌"
        lines.append(f"  {icon} {desc}")

    lines.append("<b>[레버리지 & 리스크]</b>")
    for key in ["FUTURES_LEVERAGE", "MAX_POSITION_USDT", "MAX_TOTAL_USDT", "MAX_DAILY_LOSS_PCT"]:
        desc, _, _, _, unit = CONTROLLABLE_PARAMS[key]
        val = get(key)
        lines.append(f"  • {desc}: <b>{val} {unit}</b>")

    lines.append("<b>[전략 임계값]</b>")
    for key in ["MIN_FUNDING_RATE", "MIN_ARBITRAGE_SPREAD", "ARBITRAGE_FEE_BUFFER"]:
        desc, _, _, _, unit = CONTROLLABLE_PARAMS[key]
        val = get(key)
        lines.append(f"  • {desc}: <b>{val} {unit}</b>")

    lines.append("<b>[스캔 주기]</b>")
    for key in ["FUNDING_SCAN_INTERVAL", "ARBITRAGE_SCAN_INTERVAL"]:
        desc, _, _, _, unit = CONTROLLABLE_PARAMS[key]
        val = get(key)
        lines.append(f"  • {desc}: <b>{val} {unit}</b>")

    lines.append("━━━━━━━━━━━━━━━━━━━")
    lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines)


def get_help_text() -> str:
    """설정 명령어 도움말"""
    lines = [
        "⚙️ <b>설정 명령어</b>",
        "━━━━━━━━━━━━━━━━━━━",
        "/set [항목] [값]  으로 변경",
        "",
        "<b>[ON/OFF 항목]</b> (값: on / off)",
    ]
    for key in ["AUTO_TRADE", "FUNDING_STRATEGY", "ARBITRAGE_STRATEGY", "TELEGRAM_NOTIFY"]:
        desc, *_, unit = CONTROLLABLE_PARAMS[key]
        val = get(key)
        lines.append(f"  /set {key} on|off  ({desc}, 현재: {'on' if val else 'off'})")

    lines.append("")
    lines.append("<b>[수치 항목]</b>")
    for key in ["FUTURES_LEVERAGE", "MAX_POSITION_USDT", "MAX_TOTAL_USDT",
                "MAX_DAILY_LOSS_PCT", "MIN_FUNDING_RATE", "MIN_ARBITRAGE_SPREAD",
                "FUNDING_SCAN_INTERVAL", "ARBITRAGE_SCAN_INTERVAL"]:
        desc, _, vmin, vmax, unit = CONTROLLABLE_PARAMS[key]
        val = get(key)
        lines.append(f"  /set {key} {val}  ({desc}, 범위: {vmin}~{vmax} {unit})")

    lines.append("━━━━━━━━━━━━━━━━━━━")
    lines.append("예시: /set FUTURES_LEVERAGE 3")
    lines.append("예시: /set AUTO_TRADE on")
    lines.append("예시: /set MAX_POSITION_USDT 200")
    return "\n".join(lines)
