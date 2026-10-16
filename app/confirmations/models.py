from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

Clock = Callable[[], float]

CONFIRMATION_TYPE_INVOICE_RELEASE = "invoice_release"
CONFIRMATION_TYPE_LEDGER_CREDIT = "ledger_credit"
CONFIRMATION_TYPE_LEDGER_DEBIT = "ledger_debit"
CONFIRMATION_TYPE_ADD_STOCK = "add_stock"
CONFIRMATION_TYPE_MERGE_CUSTOMERS = "merge_customers"
CONFIRMATION_TYPE_SET_OPENING_BALANCE = "set_opening_balance"
CONFIRMATION_TYPE_RECORD_CUSTOMER_PAYMENT = "record_customer_payment"
CONFIRMATION_TYPE_UPDATE_CUSTOMER_PAYMENT = "update_customer_payment"
CONFIRMATION_TYPE_CREATE_COLLECT_LINK = "create_collect_link"
CONFIRMATION_TYPE_SEND_PAYMENT_REMINDER = "send_payment_reminder"

ConfirmationStatus = Literal[
    "PENDING",
    "EXECUTING",
    "SUCCEEDED",
    "FAILED",
    "UNKNOWN",
    "REJECTED",
]


@dataclass(frozen=True)
class PendingConfirmationRecord:
    confirmation_id: str
    user_id: str
    store_id: str
    session_id: str
    type: str
    draft_id: str
    summary: dict[str, Any]
    tool_name: str
    arguments: dict[str, Any]
    expires_at: float
    status: ConfirmationStatus = "PENDING"
    business_idempotency_key: str | None = None
    consumed: bool = False  # legacy alias: terminal non-PENDING

    def to_public(self) -> dict[str, Any]:
        return {
            "confirmationId": self.confirmation_id,
            "type": self.type,
            "draftId": self.draft_id,
            "summary": dict(self.summary),
            "expiresAt": datetime.fromtimestamp(
                self.expires_at, tz=UTC
            ).isoformat().replace("+00:00", "Z"),
        }


class ConfirmationStore(Protocol):
    async def create(
        self,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        type: str,
        draft_id: str,
        summary: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any],
    ) -> PendingConfirmationRecord: ...

    async def get(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
    ) -> PendingConfirmationRecord: ...

    async def claim(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        draft_id: str | None = None,
        business_idempotency_key: str | None = None,
    ) -> PendingConfirmationRecord: ...

    async def complete(
        self,
        confirmation_id: str,
        *,
        status: ConfirmationStatus,
    ) -> PendingConfirmationRecord: ...

    async def reject(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        draft_id: str | None = None,
    ) -> PendingConfirmationRecord: ...


