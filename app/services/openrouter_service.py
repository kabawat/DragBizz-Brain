from typing import Any, Dict, List

from fastapi import HTTPException

from app.config.settings import get_settings
from app.models.chat import ChatRequest
from app.services.http import HttpClient


class OpenRouterService:
    """Service for OpenRouter API interactions."""

    BASE_URL = "https://openrouter.ai/api/v1"
    CHAT_ENDPOINT = "/chat/completions"
    DEFAULT_MODEL = "openai/gpt-4o"
    FALLBACK_MODEL = "google/gemini-2.0-flash-exp:free"
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_MAX_TOKENS = 512
    HARD_MAX_TOKENS = 4000
    REQUEST_TIMEOUT = 30

    def __init__(self, http_client: HttpClient | None = None, settings=None):
        self.settings = settings or get_settings()
        self.http_client = http_client or HttpClient(timeout=self.REQUEST_TIMEOUT)

    @property
    def chat_url(self) -> str:
        return f"{self.BASE_URL}{self.CHAT_ENDPOINT}"

    # build header 
    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
        }
        if self.settings.openrouter_http_referer:
            headers["HTTP-Referer"] = self.settings.openrouter_http_referer
        if self.settings.openrouter_title:
            headers["X-Title"] = self.settings.openrouter_title
        return headers

    # build messages for the request
    def _prepare_messages(self, payload: ChatRequest) -> List[Dict[str, str]]:
        if payload.messages:
            return [msg.model_dump() for msg in payload.messages]
        return [{"role": "user", "content": payload.prompt}]

    # prepare the request data
    def _prepare_request_data(self, payload: ChatRequest, model: str | None = None) -> Dict[str, Any]:
        selected_model = model or payload.model or self.DEFAULT_MODEL
        temperature = (
            payload.temperature
            if payload.temperature is not None and payload.temperature > 0
            else self.DEFAULT_TEMPERATURE
        )
        if payload.max_tokens and payload.max_tokens > 0:
            max_tokens = min(payload.max_tokens, self.HARD_MAX_TOKENS)
        else:
            max_tokens = self.DEFAULT_MAX_TOKENS

        return {
            "model": selected_model,
            "messages": self._prepare_messages(payload),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    # chat with the openrouter api
    def chat(self, payload: ChatRequest) -> Dict[str, Any]:
        headers = self._build_headers()
        primary_model = payload.model or self.DEFAULT_MODEL
        
        try:
            data = self._prepare_request_data(payload, model=primary_model)
            return self.http_client.post(url=self.chat_url, headers=headers, json=data)
        except HTTPException as e:
            if primary_model == self.DEFAULT_MODEL and e.status_code >= 400:
                try:
                    data = self._prepare_request_data(payload, model=self.FALLBACK_MODEL)
                    return self.http_client.post(url=self.chat_url, headers=headers, json=data)
                except HTTPException:
                    raise e
            raise e

