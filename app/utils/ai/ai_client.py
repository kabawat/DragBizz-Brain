from typing import Dict, Any, Optional, List
import asyncio
import logging
from fastapi import HTTPException

from app.config.settings import get_settings
from app.services.http import HttpClient
from app.constants.ai import (
    AI_BASE_URL,
    AI_CHAT_ENDPOINT,
    DEFAULT_MODEL,
    FALLBACK_MODEL,
    SECONDARY_FALLBACK
)

logger = logging.getLogger(__name__)


class AIClient:
    def __init__(self, http_client: Optional[HttpClient] = None, timeout: Optional[int] = None):
        self.settings = get_settings()
        self.http_client = http_client or HttpClient(timeout=timeout or self.settings.ai_request_timeout)
        self.models = [DEFAULT_MODEL, FALLBACK_MODEL, SECONDARY_FALLBACK]
    
    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
        }
        if self.settings.openrouter_http_referer:
            headers["HTTP-Referer"] = self.settings.openrouter_http_referer
        if self.settings.openrouter_title:
            headers["X-Title"] = self.settings.openrouter_title
        return headers
    
    async def call_with_fallback(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        use_cache: bool = True,
        response_format: Optional[Dict[str, str]] = None,
        models: Optional[List[str]] = None,
        max_retries: int = 2
    ) -> Optional[Dict[str, Any]]:
        models_to_try = models or self.models
        last_error = None
        
        for model in models_to_try:
            for attempt in range(max_retries):
                try:
                    request_data = {
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens
                    }
                    
                    if response_format:
                        request_data["response_format"] = response_format
                    
                    ai_response = await self.http_client.post(
                        url=f"{AI_BASE_URL}{AI_CHAT_ENDPOINT}",
                        headers=self._build_headers(),
                        json=request_data,
                        use_cache=use_cache
                    )
                    
                    return ai_response
                    
                except HTTPException as e:
                    last_error = e
                    if e.status_code == 429:
                        if attempt < max_retries - 1:
                            await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                        if model != models_to_try[-1]:
                            break
                    elif e.status_code >= 500:
                        if attempt < max_retries - 1:
                            await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                    break
                except (ValueError, KeyError, TypeError) as e:
                    last_error = e
                    if model == models_to_try[-1] and attempt == max_retries - 1:
                        break
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0.3)
                        continue
                    break
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    break
        
        if last_error:
            logger.error(f"All AI models failed. Last error: {last_error}")
        
        return None

