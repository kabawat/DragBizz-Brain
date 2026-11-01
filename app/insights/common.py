"""Common financial arithmetic and date window utilities for deterministic insights.

All financial totals MUST use Decimal arithmetic with exact rounding (ROUND_HALF_UP).
No floating-point arithmetic is permitted for monetary calculations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.core.dates import now_ist

_TWO_PLACES = Decimal("0.01")
_PCT_PLACES = Decimal("0.01")


def to_decimal(val: Any) -> Decimal:
    """Safely convert any numeric/string value to Decimal."""
    if val is None or val == "" or val is False:
        return Decimal("0.00")
    if isinstance(val, Decimal):
        return val
    if isinstance(val, (int, str)):
        try:
            return Decimal(str(val).strip())
        except Exception:
            return Decimal("0.00")
    if isinstance(val, float):
        try:
            return Decimal(str(round(val, 4)))
        except Exception:
            return Decimal("0.00")
    return Decimal("0.00")


def quantize_money(d: Decimal) -> Decimal:
    """Quantize to 2 decimal places with standard commercial rounding."""
    return d.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def quantize_pct(d: Decimal) -> Decimal:
    """Quantize percentage to 2 decimal places."""
    return d.quantize(_PCT_PLACES, rounding=ROUND_HALF_UP)


def resolve_window_dates(
    window: str | None,
    custom_start: str | None = None,
    custom_end: str | None = None,
) -> tuple[str, str, str]:
    """Resolve a window identifier (today, 7d, 30d, 90d) to start and end date strings.

    Returns (normalized_window_name, start_date_str, end_date_str).
    """
    now = now_ist()
    today_str = now.strftime("%Y-%m-%d")

    if custom_start and custom_end:
        try:
            datetime.strptime(custom_start, "%Y-%m-%d")
            datetime.strptime(custom_end, "%Y-%m-%d")
            return f"{custom_start}_to_{custom_end}", custom_start, custom_end
        except ValueError:
            pass

    normalized = (window or "7d").strip().lower()
    if normalized in ("today", "aaj", "1d"):
        return "today", today_str, today_str
    elif normalized in ("7d", "7_days", "week", "1w"):
        start = (now - timedelta(days=6)).strftime("%Y-%m-%d")
        return "7d", start, today_str
    elif normalized in ("30d", "30_days", "month", "1m"):
        start = (now - timedelta(days=29)).strftime("%Y-%m-%d")
        return "30d", start, today_str
    elif normalized in ("90d", "90_days", "3m", "quarter"):
        start = (now - timedelta(days=89)).strftime("%Y-%m-%d")
        return "90d", start, today_str

    start = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    return "7d", start, today_str


@dataclass(frozen=True)
class CoverageMetadata:
    scanned_bills: int
    window: str
    is_complete: bool
    scanned_stock_items: int | None = None
    scanned_expenses: int | None = None
    total_bills_in_window: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "scanned_bills": self.scanned_bills,
            "window": self.window,
            "is_complete": self.is_complete,
        }
        if self.total_bills_in_window is not None:
            out["total_bills_in_window"] = self.total_bills_in_window
        if self.scanned_stock_items is not None:
            out["scanned_stock_items"] = self.scanned_stock_items
        if self.scanned_expenses is not None:
            out["scanned_expenses"] = self.scanned_expenses
        return out
