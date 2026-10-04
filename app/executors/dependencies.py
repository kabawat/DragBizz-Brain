"""Server-owned tool execution staging: READ → WRITE → SENSITIVE."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.exceptions import AppError
from app.schemas.tool import ToolCall, ToolRisk
from app.tools.registry import ToolRegistry


class StageKind(StrEnum):
    PARALLEL_READ = "parallel_read"
    SEQUENTIAL_READ = "sequential_read"
    SEQUENTIAL_WRITE = "sequential_write"
    SEQUENTIAL_SENSITIVE = "sequential_sensitive"


@dataclass(frozen=True)
class ExecutionStage:
    kind: StageKind
    calls: tuple[ToolCall, ...]


def plan_execution(
    tool_calls: list[ToolCall],
    *,
    registry: ToolRegistry,
) -> list[ExecutionStage]:
    reads: list[ToolCall] = []
    writes: list[ToolCall] = []
    sensitive: list[ToolCall] = []
    for call in tool_calls:
        try:
            definition = registry.get_definition(call.name)
        except KeyError as exc:
            raise AppError(
                code="TOOL_NOT_EXECUTABLE",
                message=f"Tool '{call.name}' is not registered",
                status_code=400,
            ) from exc
        if definition.risk == ToolRisk.READ:
            reads.append(call)
        elif definition.risk == ToolRisk.WRITE:
            writes.append(call)
        elif definition.risk == ToolRisk.SENSITIVE:
            sensitive.append(call)
        else:
            raise AppError(
                code="TOOL_NOT_EXECUTABLE",
                message=f"Tool '{call.name}' has unsupported risk",
                status_code=400,
            )

    stages: list[ExecutionStage] = []
    if reads:
        can_parallel = len(reads) > 1 and all(
            registry.get_definition(call.name).allows_parallel for call in reads
        )
        stages.append(
            ExecutionStage(
                kind=(
                    StageKind.PARALLEL_READ
                    if can_parallel
                    else StageKind.SEQUENTIAL_READ
                ),
                calls=tuple(reads),
            )
        )
    for call in writes:
        stages.append(
            ExecutionStage(kind=StageKind.SEQUENTIAL_WRITE, calls=(call,))
        )
    for call in sensitive:
        stages.append(
            ExecutionStage(
                kind=StageKind.SEQUENTIAL_SENSITIVE, calls=(call,)
            )
        )
    return stages
