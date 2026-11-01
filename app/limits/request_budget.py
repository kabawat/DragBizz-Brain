"""Per-request work budget (Phase 4). Separate from Phase 3 context size."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.core.exceptions import AppError


class BudgetExceeded(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            code="AI_REQUEST_BUDGET_EXCEEDED",
            message=message,
            status_code=429,
        )


@dataclass
class RequestBudget:
    max_model_calls: int = 6
    max_tool_calls: int = 15
    max_estimated_input_tokens: int = 30_000
    max_estimated_output_tokens: int = 4_000
    deadline_seconds: float = 90.0
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def remaining_seconds(self) -> float:
        return self.deadline_seconds - (time.monotonic() - self.started_at)

    def check_deadline(self) -> None:
        if self.remaining_seconds() <= 0:
            raise BudgetExceeded("Request deadline reached")

    def begin_model_call(self, *, allow_synthesis: bool = False) -> None:
        self.check_deadline()
        if not allow_synthesis:
            if self.model_calls >= self.max_model_calls:
                raise BudgetExceeded("Maximum model calls for this request reached")
            if self.input_tokens >= self.max_estimated_input_tokens:
                raise BudgetExceeded("Maximum input tokens for this request reached")
            if self.output_tokens >= self.max_estimated_output_tokens:
                raise BudgetExceeded("Maximum output tokens for this request reached")
        self.model_calls += 1

    def record_tokens(
        self, *, input_tokens: int | None = None, output_tokens: int | None = None
    ) -> None:
        if input_tokens:
            self.input_tokens += input_tokens
        if output_tokens:
            self.output_tokens += output_tokens

    def begin_tool_batch(self, count: int) -> None:
        self.check_deadline()
        if count <= 0:
            return
        if self.tool_calls + count > self.max_tool_calls:
            raise BudgetExceeded("Maximum tool calls for this request reached")
        self.tool_calls += count

    def can_continue(self) -> bool:
        try:
            self.check_deadline()
        except BudgetExceeded:
            return False
        return (
            self.model_calls < self.max_model_calls
            and self.tool_calls < self.max_tool_calls
            and self.input_tokens < self.max_estimated_input_tokens
            and self.output_tokens < self.max_estimated_output_tokens
        )
