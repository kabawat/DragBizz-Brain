from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class GenerationRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=1_024, ge=1, le=8_192)


class GenerationResponse(BaseModel):
    provider: str
    model: str
    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None
