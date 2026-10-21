import re
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.tool import ToolCall, ToolDefinition, ToolResult

OBJECT_ID_PATTERN = re.compile(r"^[a-fA-F0-9]{24}$")


class ChatMessage(BaseModel):
    """Provider-agnostic chat turn, including OpenAI-style tool protocol."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(default="", max_length=20_000)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_role_fields(self) -> Self:
        if self.role == "tool":
            if not self.tool_call_id:
                raise ValueError("tool messages require tool_call_id")
        elif self.tool_call_id is not None:
            raise ValueError("tool_call_id is only allowed on tool messages")
        if self.tool_calls and self.role != "assistant":
            raise ValueError("tool_calls are only allowed on assistant messages")
        return self


class GenerationRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=1_024, ge=1, le=8_192)
    tools: list[ToolDefinition] | None = None
    tool_choice: Literal["auto", "none"] = "auto"
    # Admin-selected model override; None = provider's configured default.
    model: str | None = Field(default=None, min_length=1, max_length=128)


class GenerationResponse(BaseModel):
    provider: str
    model: str
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8_000)
    session_id: str = Field(alias="sessionId", min_length=1, max_length=128)
    store_id: str = Field(alias="storeId", min_length=1, max_length=64)
    language: str = Field(default="hi-IN", min_length=2, max_length=32)

    model_config = {"populate_by_name": True}


class PendingConfirmation(BaseModel):
    confirmation_id: str = Field(alias="confirmationId", min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=64)
    draft_id: str = Field(alias="draftId", min_length=1, max_length=64)
    summary: dict[str, Any] = Field(default_factory=dict)
    expires_at: str = Field(alias="expiresAt", min_length=1, max_length=64)

    model_config = {"populate_by_name": True}


class ConfirmRequest(BaseModel):
    session_id: str = Field(alias="sessionId", min_length=1, max_length=128)
    store_id: str = Field(alias="storeId", min_length=1, max_length=64)
    confirmation_id: str = Field(alias="confirmationId", min_length=1, max_length=128)
    draft_id: str = Field(alias="draftId", min_length=1, max_length=64)
    action: Literal["approve", "reject"]
    updates: dict[str, Any] | None = Field(default=None)

    model_config = {"populate_by_name": True}


class PublicToolCall(BaseModel):
    """Safe tool metadata returned to clients without model arguments."""

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=64)

    model_config = {"from_attributes": True}


class ChatResponse(BaseModel):
    message: str
    session_id: str = Field(serialization_alias="sessionId")
    request_id: str = Field(serialization_alias="requestId")
    user_id: str = Field(serialization_alias="userId")
    provider: str
    model: str
    tool_calls: list[PublicToolCall] = Field(
        default_factory=list, serialization_alias="toolCalls"
    )
    tool_results: list[ToolResult] = Field(
        default_factory=list, serialization_alias="toolResults"
    )
    pending_confirmation: PendingConfirmation | None = Field(
        default=None, serialization_alias="pendingConfirmation"
    )

    model_config = {"populate_by_name": True}

    @field_validator("tool_calls", mode="before")
    @classmethod
    def _coerce_tool_calls(cls, value: Any) -> list[Any]:
        if not isinstance(value, list):
            return value
        coerced: list[Any] = []
        for item in value:
            if isinstance(item, PublicToolCall):
                coerced.append(item)
            elif isinstance(item, dict):
                coerced.append(
                    {"id": str(item.get("id", "")), "name": str(item.get("name", ""))}
                )
            elif hasattr(item, "id") and hasattr(item, "name"):
                coerced.append(
                    {"id": str(item.id), "name": str(item.name)}
                )
            else:
                coerced.append(item)
        return coerced


def assert_valid_store_id(store_id: str) -> str:
    from app.core.exceptions import AppError

    normalized = store_id.strip()
    if not normalized:
        raise AppError(
            code="STORE_ID_REQUIRED",
            message="storeId is required",
            status_code=400,
        )
    if not OBJECT_ID_PATTERN.fullmatch(normalized):
        raise AppError(
            code="STORE_ID_INVALID",
            message="storeId must be a 24-character hex ObjectId",
            status_code=400,
        )
    return normalized
