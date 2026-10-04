"""Centralized provider/model pricing (Phase 5).

Cost is ``calculated`` only when usage tokens are actual AND an
authoritative rate exists for that provider/model. Otherwise cost is
``estimated``. Always stamp ``pricingVersion``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

UsageSource = Literal["actual", "estimated"]
CostSource = Literal["calculated", "estimated"]


@dataclass(frozen=True)
class ModelRate:
    input_usd_per_million: float
    output_usd_per_million: float
    authoritative: bool = True


@dataclass(frozen=True)
class CostResult:
    cost_usd: float | None
    usage_source: UsageSource
    cost_source: CostSource
    pricing_version: str


class PricingConfig:
    def __init__(
        self,
        *,
        pricing_version: str,
        rates: dict[tuple[str, str], ModelRate],
        default_rate: ModelRate | None = None,
        embedding_usd_per_million: float = 0.02,
        embedding_authoritative: bool = True,
    ) -> None:
        self.pricing_version = pricing_version
        self._rates = dict(rates)
        self._default = default_rate
        self._embedding_usd_per_million = embedding_usd_per_million
        self._embedding_authoritative = embedding_authoritative

    def rate_for(self, provider: str, model: str) -> ModelRate | None:
        exact = self._rates.get((provider, model))
        if exact is not None:
            return exact
        return self._default

    def compute_chat_cost(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        usage_source: UsageSource,
    ) -> CostResult:
        rate = self.rate_for(provider, model)
        if (
            usage_source == "actual"
            and rate is not None
            and rate.authoritative
            and input_tokens is not None
            and output_tokens is not None
        ):
            cost = round(
                input_tokens * rate.input_usd_per_million / 1_000_000
                + output_tokens * rate.output_usd_per_million / 1_000_000,
                8,
            )
            return CostResult(
                cost_usd=cost,
                usage_source="actual",
                cost_source="calculated",
                pricing_version=self.pricing_version,
            )
        # Estimated path: may still produce a number for caps/ops, but labeled.
        if (
            rate is not None
            and input_tokens is not None
            and output_tokens is not None
        ):
            cost = round(
                input_tokens * rate.input_usd_per_million / 1_000_000
                + output_tokens * rate.output_usd_per_million / 1_000_000,
                8,
            )
            return CostResult(
                cost_usd=cost,
                usage_source=usage_source,
                cost_source="estimated",
                pricing_version=self.pricing_version,
            )
        return CostResult(
            cost_usd=None,
            usage_source=usage_source,
            cost_source="estimated",
            pricing_version=self.pricing_version,
        )

    def estimate_embedding_cost(self, tokens: int) -> CostResult:
        # Indexer token counts are local estimates → cost cannot be calculated.
        cost = round(tokens * self._embedding_usd_per_million / 1_000_000, 8)
        return CostResult(
            cost_usd=cost,
            usage_source="estimated",
            cost_source="estimated",
            pricing_version=self.pricing_version,
        )


def pricing_from_settings(settings) -> PricingConfig:
    """Build PricingConfig from Settings (chat rates + version)."""
    chat = settings.chat
    default = ModelRate(
        input_usd_per_million=chat.input_usd_per_million_tokens,
        output_usd_per_million=chat.output_usd_per_million_tokens,
        authoritative=True,
    )
    rates: dict[tuple[str, str], ModelRate] = {
        ("openai_compatible", settings.openai.model): default,
    }
    if settings.cheaper_inference.model:
        rates[("cheaper_inference", settings.cheaper_inference.model)] = default
    version = getattr(settings.limits, "pricing_version", None) or "v1"
    embedding_rate = getattr(settings.limits, "embedding_usd_per_million_tokens", 0.02)
    return PricingConfig(
        pricing_version=version,
        rates=rates,
        default_rate=default,
        embedding_usd_per_million=embedding_rate,
        embedding_authoritative=True,
    )
