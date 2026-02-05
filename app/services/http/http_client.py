"""Async HTTP client for better concurrency and performance."""
from typing import Any, Dict, Optional
import hashlib
import json
import logging
import time

import httpx
from fastapi import HTTPException

from app.services.cache import get_cache, set_cache
 

logger = logging.getLogger(__name__)

def _extract_first_choice_text(result: Any) -> str:
    """Best-effort extract first choice message content as text."""
    if not isinstance(result, dict):
        return ""
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    msg = first.get("message")
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "".join(parts).strip()
    return ""


class HttpClient:
    """Async HTTP client with response caching for cost reduction."""
    
    # Shared client pool across all instances
    _shared_client: Optional[httpx.AsyncClient] = None
    
    def __init__(self, timeout: int | None = None):
        pass
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create shared async HTTP client with connection pooling."""
        if HttpClient._shared_client is None:
            from app.config.settings import get_settings
            settings = get_settings()
            HttpClient._shared_client = httpx.AsyncClient(
                timeout=settings.http_timeout,
                limits=httpx.Limits(
                    max_keepalive_connections=100,
                    max_connections=500
                ),
                http2=True
            )
        return HttpClient._shared_client
    
    def _get_cache_key(self, url: str, headers: Dict[str, str], json_data: Dict[str, Any]) -> str:
        """Generate cache key for request. Includes model name for AI requests."""
        # Extract model name from JSON if present (for AI requests)
        model_name = json_data.get("model", "")
        
        # Create hash of request for caching (exclude auth headers and timestamps)
        cache_data = {
            "url": url,
            "model": model_name,  # Include model in cache key for better cache separation
            "headers": {k: v for k, v in headers.items() if k.lower() not in ["authorization", "x-request-id", "x-title"]},
            "json": json_data
        }
        cache_str = json.dumps(cache_data, sort_keys=True)
        cache_hash = hashlib.sha256(cache_str.encode()).hexdigest()
        return f"http:cache:{cache_hash}"
    
    async def post(
        self,
        url: str,
        headers: Dict[str, str] | None = None,
        json: Dict[str, Any] | None = None,
        use_cache: bool = False,
    ) -> Dict[str, Any]:
        headers = headers or {}
        json_data = json or {}
        started = time.perf_counter()
        
        # Check cache for AI responses (cost reduction)
        if use_cache:
            cache_key = self._get_cache_key(url, headers, json_data)
            cached_response = await get_cache(cache_key)
            if cached_response:
                logger.debug(f"Cache hit for URL: {url}")
                return cached_response
            logger.debug(f"Cache miss for URL: {url}")
        
        client = await self._get_client()
        
        try:
            response = await client.post(
                url=url,
                headers=headers,
                json=json_data,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            response.raise_for_status()
            result = response.json()
            # Cache successful AI responses (only if no errors in response)
            if use_cache and response.status_code == 200:
                from app.config.settings import get_settings
                settings = get_settings()
                cache_ttl = settings.ai_response_cache_ttl
                
                # Check for error fields in response before caching
                if isinstance(result, dict):
                    # OpenRouter and similar APIs may return 200 with error in body
                    if "error" not in result:
                        # Avoid caching empty-content chat completions (can break UX for TTL duration)
                        extracted_text = _extract_first_choice_text(result)
                        if ("choices" in result) and (not extracted_text):
                            logger.warning("Not caching AI response with empty content")
                            return result
                        cache_key = self._get_cache_key(url, headers, json_data)
                        await set_cache(cache_key, result, cache_ttl)
                        logger.debug(f"Cached response for URL: {url}, TTL: {cache_ttl}s")
                    else:
                        logger.warning(f"Not caching response with error: {result.get('error')}")
                else:
                    # Non-dict responses are cached as-is
                    cache_key = self._get_cache_key(url, headers, json_data)
                    await set_cache(cache_key, result, cache_ttl)
                    logger.debug(f"Cached non-dict response for URL: {url}, TTL: {cache_ttl}s")
            
            return result
        except httpx.HTTPStatusError as e:
            detail = e.response.text if e.response else str(e)
            status = e.response.status_code if e.response else 500
            logger.error(f"HTTP error {status} for URL {url}: {detail}")
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            raise HTTPException(status_code=status, detail=detail) from e
        except httpx.RequestError as e:
            logger.error(f"Request error for URL {url}: {str(e)}")
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            raise HTTPException(status_code=500, detail=f"Request failed: {str(e)}") from e
    
    async def get(
        self,
        url: str,
        headers: Dict[str, str] | None = None,
        params: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        headers = headers or {}
        params = params or {}
        started = time.perf_counter()
        
        client = await self._get_client()
        
        try:
            response = await client.get(
                url=url,
                headers=headers,
                params=params,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            response.raise_for_status()
            result = response.json()
            
            return result
        except httpx.HTTPStatusError as e:
            detail = e.response.text if e.response else str(e)
            status = e.response.status_code if e.response else 500
            logger.error(f"HTTP error {status} for URL {url}: {detail}")
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            raise HTTPException(status_code=status, detail=detail) from e
        except httpx.RequestError as e:
            logger.error(f"Request error for URL {url}: {str(e)}")
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            raise HTTPException(status_code=500, detail=f"Request failed: {str(e)}") from e
    
    @classmethod
    async def close_shared_client(cls):
        """Close shared HTTP client (call at application shutdown)."""
        if cls._shared_client:
            await cls._shared_client.aclose()
            cls._shared_client = None
