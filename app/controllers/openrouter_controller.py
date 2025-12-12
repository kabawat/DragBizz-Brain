from typing import Any, Dict

from app.models.chat import ChatRequest
from app.services.openrouter_service import OpenRouterService


class OpenRouterController:
    """Handles forwarding chat completions to OpenRouter."""

    def __init__(self):
        self.service = OpenRouterService()

    def chat(self, payload: ChatRequest) -> Dict[str, Any]:
        return self.service.chat(payload)

