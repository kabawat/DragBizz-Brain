from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ToolRisk(StrEnum):
    READ = "read"
    WRITE = "write"
    SENSITIVE = "sensitive"


class ToolDomain(StrEnum):
    INVENTORY = "inventory"
    PROCUREMENT = "procurement"
    SALES = "sales"
    KHATA = "khata"
    FINANCE = "finance"
    GENERAL = "general"


class ToolAccessType(StrEnum):
    READ = "read"
    WRITE = "write"


class ToolDefinition(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    description: str = Field(min_length=1, max_length=500)
    risk: ToolRisk
    domain: ToolDomain = ToolDomain.GENERAL
    allows_parallel: bool = False
    required_permissions: tuple[str, ...] = Field(default_factory=tuple)
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    @property
    def access_type(self) -> ToolAccessType:
        return (
            ToolAccessType.READ
            if self.risk == ToolRisk.READ
            else ToolAccessType.WRITE
        )

    @property
    def requires_confirmation(self) -> bool:
        return self.risk == ToolRisk.SENSITIVE


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
