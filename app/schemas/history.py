from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    created_at: str = Field(serialization_alias="createdAt")
    updated_at: str = Field(serialization_alias="updatedAt")

    model_config = {"populate_by_name": True}


class ChatHistoryMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str = Field(serialization_alias="createdAt")
    tool_results: list[dict[str, Any]] | None = Field(
        default=None, serialization_alias="toolResults"
    )

    model_config = {"populate_by_name": True}


class ChatSessionDetail(BaseModel):
    id: str
    title: str
    created_at: str = Field(serialization_alias="createdAt")
    updated_at: str = Field(serialization_alias="updatedAt")
    messages: list[ChatHistoryMessage] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionSummary] = Field(default_factory=list)

    model_config = {"populate_by_name": True}
