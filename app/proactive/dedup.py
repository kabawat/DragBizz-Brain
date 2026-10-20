"""Alert state machine, deduplication, and atomic claim store."""

from __future__ import annotations

import abc
import contextlib
import json
import logging
import time
import uuid
from typing import Any

from app.proactive.models import AlertState, AlertType

logger = logging.getLogger(__name__)

ALERT_STATE_PREFIX = "ai:alert:state:"
ALERT_CLAIM_PREFIX = "ai:alert:claim:"


class AlertDedupStore(abc.ABC):
    """Abstract store for alert state machine and atomic claims."""

    @abc.abstractmethod
    async def check_and_claim(
        self,
        *,
        store_id: str,
        alert_type: AlertType,
        entity_id: str,
        current_stock: float,
        threshold: float,
        cooldown_seconds: int = 86400,
        claim_ttl_seconds: int = 60,
    ) -> tuple[bool, str, str | None]:
        """Check if alert should be emitted and atomically claim delivery lease.

        Returns: (should_alert, reason, claim_id_if_acquired)
        """

    @abc.abstractmethod
    async def commit_alert(
        self,
        *,
        store_id: str,
        alert_type: AlertType,
        entity_id: str,
        claim_id: str,
        current_stock: float,
        threshold: float,
    ) -> None:
        """Record successful alert delivery and release claim."""

    @abc.abstractmethod
    async def release_claim(
        self,
        *,
        store_id: str,
        alert_type: AlertType,
        entity_id: str,
        claim_id: str,
    ) -> None:
        """Release claim lease upon delivery failure so retries can redeliver."""

    @abc.abstractmethod
    async def record_recovery(
        self,
        *,
        store_id: str,
        alert_type: AlertType,
        entity_id: str,
        current_stock: float,
    ) -> None:
        """Record that stock has recovered above threshold (resets low-stock state)."""

    @abc.abstractmethod
    async def get_state(
        self,
        *,
        store_id: str,
        alert_type: AlertType,
        entity_id: str,
    ) -> dict[str, Any] | None:
        """Get current alert state."""


class InMemoryAlertDedupStore(AlertDedupStore):
    """Thread-safe in-memory alert dedup store for local testing."""

    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}
        self._claims: dict[str, tuple[str, float]] = {}

    def _state_key(self, store_id: str, alert_type: AlertType, entity_id: str) -> str:
        return f"{store_id}:{alert_type.value}:{entity_id}"

    async def check_and_claim(
        self,
        *,
        store_id: str,
        alert_type: AlertType,
        entity_id: str,
        current_stock: float,
        threshold: float,
        cooldown_seconds: int = 86400,
        claim_ttl_seconds: int = 60,
    ) -> tuple[bool, str, str | None]:
        if current_stock > threshold:
            await self.record_recovery(
                store_id=store_id,
                alert_type=alert_type,
                entity_id=entity_id,
                current_stock=current_stock,
            )
            return False, "stock_healthy", None

        key = self._state_key(store_id, alert_type, entity_id)
        now = time.time()
        record = self._states.get(key)

        should_alert = False
        reason = ""

        if not record or record.get("state") == AlertState.HEALTHY.value:
            should_alert = True
            reason = "threshold_crossed"
        else:
            last_notified = float(record.get("last_notified_at", 0))
            if now - last_notified >= cooldown_seconds:
                should_alert = True
                reason = "cooldown_expired"
            else:
                return False, "cooldown_active", None

        if should_alert:
            claim_info = self._claims.get(key)
            if claim_info:
                _, expires_at = claim_info
                if now < expires_at:
                    return False, "already_claimed", None

            claim_id = str(uuid.uuid4())
            self._claims[key] = (claim_id, now + claim_ttl_seconds)
            return True, reason, claim_id

        return False, "unknown", None

    async def commit_alert(
        self,
        *,
        store_id: str,
        alert_type: AlertType,
        entity_id: str,
        claim_id: str,
        current_stock: float,
        threshold: float,
    ) -> None:
        key = self._state_key(store_id, alert_type, entity_id)
        self._claims.pop(key, None)
        self._states[key] = {
            "state": (
                AlertState.OUT_OF_STOCK.value
                if current_stock <= 0
                else AlertState.LOW_STOCK.value
            ),
            "last_notified_at": time.time(),
            "stock": current_stock,
            "threshold": threshold,
        }

    async def release_claim(
        self,
        *,
        store_id: str,
        alert_type: AlertType,
        entity_id: str,
        claim_id: str,
    ) -> None:
        key = self._state_key(store_id, alert_type, entity_id)
        existing = self._claims.get(key)
        if existing and existing[0] == claim_id:
            self._claims.pop(key, None)

    async def record_recovery(
        self,
        *,
        store_id: str,
        alert_type: AlertType,
        entity_id: str,
        current_stock: float,
    ) -> None:
        key = self._state_key(store_id, alert_type, entity_id)
        self._claims.pop(key, None)
        self._states[key] = {
            "state": AlertState.HEALTHY.value,
            "recovered_at": time.time(),
            "stock": current_stock,
        }

    async def get_state(
        self,
        *,
        store_id: str,
        alert_type: AlertType,
        entity_id: str,
    ) -> dict[str, Any] | None:
        key = self._state_key(store_id, alert_type, entity_id)
        return self._states.get(key)


class RedisAlertDedupStore(AlertDedupStore):
    """Distributed Redis-backed alert state and atomic claim store."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    def _state_key(self, store_id: str, alert_type: AlertType, entity_id: str) -> str:
        return f"{ALERT_STATE_PREFIX}{store_id}:{alert_type.value}:{entity_id}"

    def _claim_key(self, store_id: str, alert_type: AlertType, entity_id: str) -> str:
        return f"{ALERT_CLAIM_PREFIX}{store_id}:{alert_type.value}:{entity_id}"

    async def check_and_claim(
        self,
        *,
        store_id: str,
        alert_type: AlertType,
        entity_id: str,
        current_stock: float,
        threshold: float,
        cooldown_seconds: int = 86400,
        claim_ttl_seconds: int = 60,
    ) -> tuple[bool, str, str | None]:
        if current_stock > threshold:
            await self.record_recovery(
                store_id=store_id,
                alert_type=alert_type,
                entity_id=entity_id,
                current_stock=current_stock,
            )
            return False, "stock_healthy", None

        state_key = self._state_key(store_id, alert_type, entity_id)
        raw_state = await self._redis.get(state_key)
        state_data: dict[str, Any] = {}
        if raw_state:
            with contextlib.suppress(Exception):
                state_data = json.loads(raw_state)

        now = time.time()
        should_alert = False
        reason = ""

        current_state = state_data.get("state")
        if not current_state or current_state == AlertState.HEALTHY.value:
            should_alert = True
            reason = "threshold_crossed"
        else:
            last_notified = float(state_data.get("last_notified_at", 0))
            if now - last_notified >= cooldown_seconds:
                should_alert = True
                reason = "cooldown_expired"
            else:
                return False, "cooldown_active", None

        if should_alert:
            claim_key = self._claim_key(store_id, alert_type, entity_id)
            claim_id = str(uuid.uuid4())
            acquired = await self._redis.set(
                claim_key, claim_id, nx=True, ex=claim_ttl_seconds
            )
            if acquired:
                return True, reason, claim_id
            return False, "already_claimed", None

        return False, "unknown", None

    async def commit_alert(
        self,
        *,
        store_id: str,
        alert_type: AlertType,
        entity_id: str,
        claim_id: str,
        current_stock: float,
        threshold: float,
    ) -> None:
        state_key = self._state_key(store_id, alert_type, entity_id)
        claim_key = self._claim_key(store_id, alert_type, entity_id)

        state_val = json.dumps(
            {
                "state": (
                    AlertState.OUT_OF_STOCK.value
                    if current_stock <= 0
                    else AlertState.LOW_STOCK.value
                ),
                "last_notified_at": time.time(),
                "stock": current_stock,
                "threshold": threshold,
            }
        )
        # Store state for up to 7 days
        await self._redis.set(state_key, state_val, ex=86400 * 7)
        # Release claim
        await self._redis.delete(claim_key)

    async def release_claim(
        self,
        *,
        store_id: str,
        alert_type: AlertType,
        entity_id: str,
        claim_id: str,
    ) -> None:
        claim_key = self._claim_key(store_id, alert_type, entity_id)
        current = await self._redis.get(claim_key)
        if isinstance(current, bytes):
            current = current.decode()
        if current == claim_id:
            await self._redis.delete(claim_key)

    async def record_recovery(
        self,
        *,
        store_id: str,
        alert_type: AlertType,
        entity_id: str,
        current_stock: float,
    ) -> None:
        state_key = self._state_key(store_id, alert_type, entity_id)
        claim_key = self._claim_key(store_id, alert_type, entity_id)

        state_val = json.dumps(
            {
                "state": AlertState.HEALTHY.value,
                "recovered_at": time.time(),
                "stock": current_stock,
            }
        )
        await self._redis.set(state_key, state_val, ex=86400 * 7)
        await self._redis.delete(claim_key)

    async def get_state(
        self,
        *,
        store_id: str,
        alert_type: AlertType,
        entity_id: str,
    ) -> dict[str, Any] | None:
        state_key = self._state_key(store_id, alert_type, entity_id)
        val = await self._redis.get(state_key)
        if not val:
            return None
        if isinstance(val, bytes):
            val = val.decode()
        try:
            return json.loads(val)
        except Exception:
            return None
