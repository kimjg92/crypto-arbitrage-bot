"""
거래소 계정 간 내부 이체 관리
- Binance: Spot ↔ Futures 분리 → API로 자동 이체
- Bybit:   Unified Trading Account → 이체 불필요
- MEXC:    Spot ↔ Futures 분리 → API로 자동 이체
- Gate.io: Spot ↔ Futures 분리 → API로 자동 이체
"""
import asyncio
import ccxt.async_support as ccxt
from src.exchanges.base import make_exchange_config
from src.core.logger import setup_logger

logger = setup_logger()

# 계정 구조 정의
ACCOUNT_TYPE = {
    "binance": "separated",   # Spot / Futures 분리
    "bybit":   "unified",     # Unified Trading Account
    "mexc":    "separated",
    "gateio":  "separated",
    "hyperliquid": "unified",
}


class AccountManager:
    def __init__(self, exchange_name: str, api_key: str, api_secret: str):
        self.exchange_name = exchange_name
        self.api_key = api_key
        self.api_secret = api_secret
        self.is_unified = ACCOUNT_TYPE.get(exchange_name, "separated") == "unified"

    # ──────────────────────────────────────────
    # 잔고 조회 (Spot / Futures 각각)
    # ──────────────────────────────────────────
    async def get_spot_balance(self, currency: str = "USDT") -> float:
        cfg = make_exchange_config(self.api_key, self.api_secret, {"defaultType": "spot"})
        ex = self._make_exchange(cfg)
        try:
            await ex.load_markets()
            bal = await ex.fetch_balance()
            return float(bal.get(currency, {}).get("free", 0))
        finally:
            await ex.close()

    async def get_futures_balance(self, currency: str = "USDT") -> float:
        if self.is_unified:
            return await self.get_spot_balance(currency)  # 통합 계정은 동일
        cfg = make_exchange_config(self.api_key, self.api_secret,
                                   {"defaultType": self._futures_type()})
        ex = self._make_exchange(cfg)
        try:
            await ex.load_markets()
            bal = await ex.fetch_balance()
            return float(bal.get(currency, {}).get("free", 0))
        finally:
            await ex.close()

    async def get_all_balances(self, currency: str = "USDT") -> dict:
        """Spot + Futures 잔고 동시 조회"""
        if self.is_unified:
            bal = await self.get_spot_balance(currency)
            return {"spot": bal, "futures": bal, "total": bal, "unified": True}

        spot_bal, futures_bal = await asyncio.gather(
            self.get_spot_balance(currency),
            self.get_futures_balance(currency),
        )
        return {
            "spot": spot_bal,
            "futures": futures_bal,
            "total": spot_bal + futures_bal,
            "unified": False,
        }

    # ──────────────────────────────────────────
    # 내부 이체 (Spot → Futures / Futures → Spot)
    # ──────────────────────────────────────────
    async def transfer_to_futures(self, amount: float, currency: str = "USDT") -> bool:
        """Spot → Futures 이체"""
        if self.is_unified:
            logger.debug(f"[{self.exchange_name}] 통합 계정 - 이체 불필요")
            return True

        logger.info(f"[{self.exchange_name}] Spot → Futures 이체: {amount:.2f} {currency}")
        try:
            if self.exchange_name == "binance":
                return await self._binance_transfer(amount, currency, direction="to_futures")
            elif self.exchange_name == "mexc":
                return await self._mexc_transfer(amount, currency, direction="to_futures")
            elif self.exchange_name == "gateio":
                return await self._gateio_transfer(amount, currency, direction="to_futures")
            else:
                logger.warning(f"[{self.exchange_name}] 자동 이체 미지원")
                return False
        except Exception as e:
            logger.error(f"[{self.exchange_name}] Spot→Futures 이체 실패: {e}")
            return False

    async def transfer_to_spot(self, amount: float, currency: str = "USDT") -> bool:
        """Futures → Spot 이체"""
        if self.is_unified:
            return True

        logger.info(f"[{self.exchange_name}] Futures → Spot 이체: {amount:.2f} {currency}")
        try:
            if self.exchange_name == "binance":
                return await self._binance_transfer(amount, currency, direction="to_spot")
            elif self.exchange_name == "mexc":
                return await self._mexc_transfer(amount, currency, direction="to_spot")
            elif self.exchange_name == "gateio":
                return await self._gateio_transfer(amount, currency, direction="to_spot")
            else:
                logger.warning(f"[{self.exchange_name}] 자동 이체 미지원")
                return False
        except Exception as e:
            logger.error(f"[{self.exchange_name}] Futures→Spot 이체 실패: {e}")
            return False

    async def ensure_futures_balance(
        self, required_usdt: float, currency: str = "USDT", buffer_pct: float = 0.1
    ) -> tuple[bool, str]:
        """
        선물 계정에 필요 금액 있는지 확인, 부족하면 Spot에서 자동 이체
        buffer_pct: 추가 여유 버퍼 (기본 10%)
        """
        if self.is_unified:
            total = await self.get_spot_balance(currency)
            if total >= required_usdt:
                return True, f"통합계정 잔고 충분 (${total:.2f})"
            return False, f"통합계정 잔고 부족 (${total:.2f} < ${required_usdt:.2f})"

        needed = required_usdt * (1 + buffer_pct)
        futures_bal = await self.get_futures_balance(currency)

        if futures_bal >= needed:
            return True, f"선물계정 잔고 충분 (${futures_bal:.2f})"

        shortfall = needed - futures_bal
        spot_bal = await self.get_spot_balance(currency)

        if spot_bal < shortfall:
            return False, (
                f"잔고 부족 - 선물: ${futures_bal:.2f}, "
                f"현물: ${spot_bal:.2f}, "
                f"필요: ${needed:.2f}"
            )

        # Spot → Futures 자동 이체
        success = await self.transfer_to_futures(shortfall, currency)
        if success:
            return True, f"자동 이체 완료: ${shortfall:.2f} Spot→Futures"
        return False, "자동 이체 실패"

    async def rebalance_after_exit(
        self, futures_profit: float, currency: str = "USDT"
    ) -> bool:
        """
        포지션 청산 후 선물 계정의 수익금을 Spot으로 회수
        """
        if self.is_unified or futures_profit <= 0:
            return True
        return await self.transfer_to_spot(futures_profit, currency)

    # ──────────────────────────────────────────
    # 거래소별 이체 구현
    # ──────────────────────────────────────────
    async def _binance_transfer(self, amount: float, currency: str, direction: str) -> bool:
        """
        Binance 내부 이체
        type 1: Spot → USDT-M Futures
        type 2: USDT-M Futures → Spot
        """
        cfg = make_exchange_config(self.api_key, self.api_secret)
        ex = ccxt.binance(cfg)
        try:
            transfer_type = 1 if direction == "to_futures" else 2
            await ex.sapi_post_futures_transfer({
                "asset": currency,
                "amount": str(amount),
                "type": transfer_type,
            })
            logger.info(f"[Binance] 이체 성공: {amount:.2f} {currency} "
                        f"({'Spot→Futures' if direction == 'to_futures' else 'Futures→Spot'})")
            return True
        except Exception as e:
            logger.error(f"[Binance] 이체 실패: {e}")
            return False
        finally:
            await ex.close()

    async def _mexc_transfer(self, amount: float, currency: str, direction: str) -> bool:
        """MEXC 내부 이체"""
        cfg = make_exchange_config(self.api_key, self.api_secret)
        ex = ccxt.mexc(cfg)
        try:
            # MEXC: account_type = SPOT / FUTURES
            from_acc = "SPOT" if direction == "to_futures" else "FUTURES"
            to_acc   = "FUTURES" if direction == "to_futures" else "SPOT"
            await ex.private_post_capital_transfer({
                "fromAccountType": from_acc,
                "toAccountType": to_acc,
                "asset": currency,
                "amount": str(amount),
            })
            logger.info(f"[MEXC] 이체 성공: {amount:.2f} {currency} {from_acc}→{to_acc}")
            return True
        except Exception as e:
            logger.error(f"[MEXC] 이체 실패: {e}")
            return False
        finally:
            await ex.close()

    async def _gateio_transfer(self, amount: float, currency: str, direction: str) -> bool:
        """Gate.io 내부 이체"""
        cfg = make_exchange_config(self.api_key, self.api_secret)
        ex = ccxt.gateio(cfg)
        try:
            from_acc = "spot" if direction == "to_futures" else "futures"
            to_acc   = "futures" if direction == "to_futures" else "spot"
            await ex.private_post_wallet_transfers({
                "currency": currency,
                "from": from_acc,
                "to": to_acc,
                "amount": str(amount),
            })
            logger.info(f"[Gate.io] 이체 성공: {amount:.2f} {currency} {from_acc}→{to_acc}")
            return True
        except Exception as e:
            logger.error(f"[Gate.io] 이체 실패: {e}")
            return False
        finally:
            await ex.close()

    # ──────────────────────────────────────────
    # 유틸
    # ──────────────────────────────────────────
    def _make_exchange(self, cfg: dict):
        ex_map = {
            "binance": ccxt.binance,
            "bybit":   ccxt.bybit,
            "mexc":    ccxt.mexc,
            "gateio":  ccxt.gateio,
        }
        return ex_map.get(self.exchange_name, ccxt.binance)(cfg)

    def _futures_type(self) -> str:
        return {
            "binance": "future",
            "mexc":    "swap",
            "gateio":  "future",
        }.get(self.exchange_name, "future")

    def account_structure_info(self) -> str:
        if self.is_unified:
            return f"{self.exchange_name}: 통합 계정 (이체 불필요)"
        return f"{self.exchange_name}: Spot/Futures 분리 (자동 이체 지원)"
