from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ToolRisk(StrEnum):
    READ = "read"
    WRITE = "write"
    SENSITIVE = "sensitive"


class ToolDefinition(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    description: str = Field(min_length=1, max_length=500)
    risk: ToolRisk
    allows_parallel: bool = False
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )


class ToolCall(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Gemini 3 rejects the next tool round unless this is echoed back.
    # Excluded from API responses and persisted history.
    thought_signature: str | None = Field(
        default=None, exclude=True, max_length=16_384
    )


class ToolResult(BaseModel):
    tool: str
    success: bool
    data: dict[str, Any] | None = None
