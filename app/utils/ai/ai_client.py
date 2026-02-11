from typing import Dict, Any, Optional, List
import asyncio
import logging
from fastapi import HTTPException

from app.config.settings import get_settings
from app.services.http import HttpClient
from app.constants.ai import (
    AI_BASE_URL,
    AI_CHAT_ENDPOINT,
)
from app.utils.ai.model_manager import get_available_models, remove_model, remove_vision_model

logger = logging.getLogger(__name__)


def _extract_first_choice_content_type(ai_response: Any) -> str | None:
    if not isinstance(ai_response, dict):
        return None
    choices = ai_response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    msg = choices[0].get("message")
    if not isinstance(msg, dict):
        return None
    return type(msg.get("content")).__name__


def _has_nonempty_first_choice_text(ai_response: Any) -> bool:
    if not isinstance(ai_response, dict):
        return False
    if "error" in ai_response:
        return False
    choices = ai_response.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    first = choices[0]
    if not isinstance(first, dict):
        return False
    msg = first.get("message")
    if not isinstance(msg, dict):
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return bool("".join(parts).strip())
    return False


class AIClient:
    def __init__(self, http_client: Optional[HttpClient] = None, timeout: Optional[int] = None):
        self.settings = get_settings()
        self.http_client = http_client or HttpClient(timeout=timeout or self.settings.ai_request_timeout)
        self._models_cache: Optional[List[str]] = None
        self._cache_lock = asyncio.Lock()
    
    async def _get_models(self) -> List[str]:
        """Get current list of available models."""
        async with self._cache_lock:
            if self._models_cache is None:
                self._models_cache = await get_available_models()
            return self._models_cache.copy()
    
    async def _refresh_models(self) -> List[str]:
        """Refresh models list from file."""
        async with self._cache_lock:
            self._models_cache = await get_available_models()
            return self._models_cache.copy()
    
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
        max_retries: int = 2,
        is_vision: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Call AI with dynamic model fallback.
        - Uses models from file in order (first to last)
        - Removes model from file permanently if rate limit (429) is hit
        - Uses next model for temporary errors (500+) without removing
        
        Args:
            is_vision: If True, uses vision models and removes from vision models file on 429
        """
        models_to_try = models or await self._get_models()
        
        if not models_to_try:
            logger.error("No models available!")
            return None
        
        # Use appropriate remove function based on is_vision flag
        remove_func = remove_vision_model if is_vision else remove_model
        
        last_error = None
        last_model = None
        
        while models_to_try:
            model = models_to_try[0]
            last_model = model
            should_remove_model = False
            
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
                    # Light sanity debug (avoid printing full content)
                    # Treat "200 but empty content" (or non-text content) as failure → fallback to next model
                    if ("choices" in ai_response) and (not _has_nonempty_first_choice_text(ai_response)):
                        raise ValueError("Empty content in AI response")
                    
                    # If JSON format was requested, verify it can be parsed
                    if response_format and response_format.get("type") == "json_object":
                        try:
                            # Use late import to avoid circular dependency
                            from app.utils.ai.ai_parser import parse_json_response
                            parse_json_response(ai_response)
                        except Exception as e:
                            logger.warning(f"Model {model} returned invalid JSON for json_object request: {str(e)}")
                            # Treat invalid JSON as a retryable error - fallback to next model
                            raise ValueError(f"Invalid JSON content from model {model}: {str(e)}")

                    return ai_response
                    
                except HTTPException as e:
                    last_error = e
                    
                    if e.status_code == 429:
                        logger.warning(f"Rate limit (429) for model {model} - removing permanently")
                        should_remove_model = True
                        break
                    elif e.status_code == 404:
                        # Model not available / deprecated (common for free slugs ending)
                        detail_text = str(e.detail)
                        if "migrate" in detail_text.lower() or "not found" in detail_text.lower() or "ended" in detail_text.lower():
                            logger.warning(f"Model not available (404) for model {model} - removing permanently")
                            should_remove_model = True
                        break
                    elif e.status_code >= 500:
                        logger.warning(f"Server error ({e.status_code}) for model {model}, retrying...")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                        break
                    else:
                        logger.warning(f"Error {e.status_code} for model {model}, trying next model")
                        break
                        
                except (ValueError, KeyError, TypeError) as e:
                    last_error = e
                    logger.warning(f"Parse error for model {model}: {str(e)}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0.3)
                        continue
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(f"Unexpected error for model {model}: {str(e)}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    break
            
            if should_remove_model:
                await remove_func(model)
                if is_vision:
                    # For vision models, we need to refresh from vision models file
                    # But since we're passing models explicitly, we just remove from list
                    pass
                else:
                    await self._refresh_models()
            
            models_to_try.pop(0)
            
            if not models_to_try:
                if is_vision:
                    # For vision models, if list is empty, we can't fallback to text models
                    break
                else:
                    models_to_try = await self._get_models()
                    if not models_to_try:
                        break
        
        if last_error:
            logger.error(f"All AI models failed. Last error: {last_error} (model: {last_model})")
        
        return None
