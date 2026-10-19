"""Deterministic Business Intelligence calculation engine package."""

from app.insights.cache import (
    InMemoryInsightCache,
    InsightCache,
    NoOpInsightCache,
    RedisInsightCache,
    build_insight_cache,
)
from app.insights.common import (
    CoverageMetadata,
    quantize_money,
    quantize_pct,
    resolve_window_dates,
    to_decimal,
)
from app.insights.inventory_velocity import calculate_inventory_velocity
from app.insights.payment_mix import calculate_payment_mix
from app.insights.sales_pareto import calculate_sales_pareto
from app.insights.store_brief import compile_store_brief

__all__ = [
    "CoverageMetadata",
    "InMemoryInsightCache",
    "InsightCache",
    "NoOpInsightCache",
    "RedisInsightCache",
    "build_insight_cache",
    "calculate_inventory_velocity",
    "calculate_payment_mix",
    "calculate_sales_pareto",
    "compile_store_brief",
    "quantize_money",
    "quantize_pct",
    "resolve_window_dates",
    "to_decimal",
]
