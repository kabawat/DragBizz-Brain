"""Pydantic models and enums for Proactive Retail Intelligence."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.dates import current_ist_date_str


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(StrEnum):
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    DAILY_BRIEF = "DAILY_BRIEF"


class AlertState(StrEnum):
    HEALTHY = "HEALTHY"
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class NotificationRecord(BaseModel):
    """Store-scoped advisory notification record."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    store_id: str = Field(..., alias="storeId")
    notification_type: AlertType = Field(..., alias="notificationType")
    title: str
    message: str
    severity: AlertSeverity = AlertSeverity.WARNING
    entity_id: str | None = Field(None, alias="entityId")
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=current_ist_date_str, alias="createdAt")
    read: bool = False


class LowStockAlertData(BaseModel):
    """Structured data payload for low-stock notification."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    product_id: str = Field(..., alias="productId")
    product_name: str = Field(..., alias="productName")
    sku: str | None = None
    available_quantity: float = Field(..., alias="availableQuantity")
    threshold: float
    days_remaining: float | None = Field(None, alias="daysRemaining")
    unit: str | None = None
