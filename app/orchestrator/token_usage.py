"""Per-request LLM token accounting (Phase 7).

Provider usage is billing truth when present; chars//4 is never ``actual``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

UsageSource = Literal["actual", "estimated", "unavailable"]


@dataclass(frozen=True)
class ModelCallUsage:
    model: str
    call_type: str
    round: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    usage_source: UsageSource
    provider: str = ""
    retry: bool = False
    fallback: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "callType": self.call_type,
            "round": self.round,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "totalTokens": self.total_tokens,
            "usageSource": self.usage_source,
            "provider": self.provider,
            "retry": self.retry,
            "fallback": self.fallback,
        }


@dataclass
class RequestTokenUsage:
    calls: list[ModelCallUsage] = field(default_factory=list)

    def record(
        self,
        *,
        model: str,
        call_type: str,
        round: int,
        input_tokens: int | None,
        output_tokens: int | None,
        provider: str = "",
        retry: bool = False,
        fallback: bool = False,
    ) -> ModelCallUsage:
        if input_tokens is not None and output_tokens is not None:
            source: UsageSource = "actual"
            total: int | None = input_tokens + output_tokens
        elif input_tokens is not None or output_tokens is not None:
            source = "estimated"
            total = (input_tokens or 0) + (output_tokens or 0)
        else:
            source = "unavailable"
            total = None
        entry = ModelCallUsage(
            model=model or "",
            call_type=call_type,
            round=round,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
            usage_source=source,
            provider=provider,
            retry=retry,
            fallback=fallback,
        )
        self.calls.append(entry)
        return entry

    @property
    def model_calls(self) -> int:
        return len(self.calls)

    def _sum_field(self, field_name: str) -> int | None:
        values = [
            getattr(call, field_name)
            for call in self.calls
            if getattr(call, field_name) is not None
        ]
        if not values:
            return None
        return sum(values)

    @property
    def input_tokens(self) -> int | None:
        return self._sum_field("input_tokens")

    @property
    def output_tokens(self) -> int | None:
        return self._sum_field("output_tokens")

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None and self.output_tokens is None:
            return None
        return (self.input_tokens or 0) + (self.output_tokens or 0)

    @property
    def usage_source(self) -> UsageSource:
        if not self.calls:
            return "unavailable"
        sources = {call.usage_source for call in self.calls}
        if sources == {"actual"}:
            return "actual"
        if sources == {"unavailable"}:
            return "unavailable"
        return "estimated"

    def aggregate(self) -> dict[str, Any]:
        return {
            "modelCalls": self.model_calls,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "totalTokens": self.total_tokens,
            "usageSource": self.usage_source,
            "calls": [call.as_dict() for call in self.calls],
        }
