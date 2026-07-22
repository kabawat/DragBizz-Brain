import re
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.tool import ToolCall, ToolDefinition, ToolResult

OBJECT_ID_PATTERN = re.compile(r"^[a-fA-F0-9]{24}$")


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(default="", max_length=20_000)


class GenerationRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=1_024, ge=1, le=8_192)
    tools: list[ToolDefinition] | None = None
    tool_choice: Literal["auto", "none"] = "auto"


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


class ChatResponse(BaseModel):
    message: str
    session_id: str = Field(serialization_alias="sessionId")
    request_id: str = Field(serialization_alias="requestId")
    user_id: str = Field(serialization_alias="userId")
    provider: str
    model: str
    tool_calls: list[ToolCall] = Field(
        default_factory=list, serialization_alias="toolCalls"
    )
    tool_results: list[ToolResult] = Field(
        default_factory=list, serialization_alias="toolResults"
    )

    model_config = {"populate_by_name": True}


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
