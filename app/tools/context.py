from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.integrations.retailer_client import RetailerClient


@dataclass(frozen=True)
class ToolContext:
    access_token: str
    store_id: str
    retailer: RetailerClient
    question: str = ""
    insight_cache: Any = None
