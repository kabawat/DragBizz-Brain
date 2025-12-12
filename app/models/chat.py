from typing import List, Optional

from pydantic import BaseModel, Field, model_validator
from pydantic import ConfigDict


class ChatMessage(BaseModel):
    role: str = Field(..., description="Message role, e.g., user/assistant/system")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "prompt": "Write a short welcome message for new users.",
            }
        }
    )

    prompt: str = Field(..., description="User prompt (frontend sends only this)")
    messages: Optional[List[ChatMessage]] = Field(
        default=None,
        description="Optional conversation history; backend uses prompt if omitted.",
    )
    model: Optional[str] = Field(
        default=None, description="Override model; defaults to openai/gpt-4o."
    )
    temperature: Optional[float] = Field(
        default=None, description="Optional temperature override."
    )
    max_tokens: Optional[int] = Field(default=None, description="Optional max tokens.")

    @model_validator(mode="after")
    def ensure_prompt_present(self):
        if not self.prompt:
            raise ValueError("prompt is required.")
        return self

