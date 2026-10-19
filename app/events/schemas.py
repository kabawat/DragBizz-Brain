"""Pydantic schemas and validation for Domain Events."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

STORE_ID_PATTERN = re.compile(r"^[a-fA-F0-9]{24}$")
SUPPORTED_EVENT_VERSIONS = frozenset({"1.0", "1", "v1"})


class DomainEventEnvelope(BaseModel):
    """Envelope wrapping all domain events ingested via Redis Stream."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    event_id: str = Field(..., alias="eventId", min_length=1)
    event_type: str = Field(..., alias="eventType", min_length=1)
    event_version: str = Field("1.0", alias="eventVersion")
    store_id: str = Field(..., alias="storeId")
    entity_id: str | None = Field(None, alias="entityId")
    correlation_id: str | None = Field(None, alias="correlationId")
    occurred_at: str | None = Field(None, alias="occurredAt")
    seq: int | None = Field(None, alias="seq")
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("seq", mode="before")
    @classmethod
    def parse_seq(cls, v: Any) -> int | None:
        if v is None or v == "":
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    @field_validator("store_id")
    @classmethod
    def validate_store_id(cls, v: str) -> str:
        cleaned = str(v).strip()
        if not STORE_ID_PATTERN.match(cleaned):
            raise ValueError(f"Invalid store_id format: '{v}'")
        return cleaned

    @field_validator("event_version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        cleaned = str(v).strip()
        if cleaned not in SUPPORTED_EVENT_VERSIONS:
            raise ValueError(f"Unsupported schema version: '{cleaned}'")
        return cleaned

    @field_validator("payload", mode="before")
    @classmethod
    def parse_payload(cls, v: Any) -> dict[str, Any]:
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return parsed
                return {"data": parsed}
            except Exception as exc:
                raise ValueError(f"Invalid JSON string in payload: {exc}") from exc
        if isinstance(v, dict):
            return v
        return {}


class InvoiceReleasedPayload(BaseModel):
    """Payload schema for invoice.released event."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    invoice_id: str = Field(..., alias="invoiceId", min_length=1)
    invoice_number: str | None = Field(None, alias="invoiceNumber")
    total_amount: float | int | str | None = Field(None, alias="totalAmount")
    paid_amount: float | int | str | None = Field(None, alias="paidAmount")
    payment_status: str | None = Field(None, alias="paymentStatus")
    released_at: str | None = Field(None, alias="releasedAt")


class StockIntakePayload(BaseModel):
    """Payload schema for stock.intake event."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    bill_id: str = Field(..., alias="billId", min_length=1)
    supplier_id: str | None = Field(None, alias="supplierId")
    purchase_order_id: str | None = Field(None, alias="purchaseOrderId")
    item_count: int | None = Field(None, alias="itemCount")
    total_quantity: float | int | None = Field(None, alias="totalQuantity")
    received_at: str | None = Field(None, alias="receivedAt")
