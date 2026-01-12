"""Rate limiting middleware for cost saving and abuse prevention."""
from typing import Callable
import time
import logging
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config.settings import get_settings
from app.services.redis_manager import get_redis_client
from app.constants.status_code import STATUS_CODES

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using Redis for distributed rate limiting."""
    
    def __init__(self, app, enabled: bool = True):
        super().__init__(app)
        self.settings = get_settings()
        self.enabled = enabled and self.settings.rate_limit_enabled
        self.per_minute = self.settings.rate_limit_per_minute
        self.per_hour = self.settings.rate_limit_per_hour
        
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Check rate limits before processing request."""
        if request.url.path.startswith("/api/v1/health"):
            return await call_next(request)
        
        if not self.enabled:
            return await call_next(request)
        
        user_id = None
        if hasattr(request.state, 'user'):
            user_obj = request.state.user
            if isinstance(user_obj, dict):
                user_id = user_obj.get('sub') or user_obj.get('id')
        
        if user_id:
            client_id = user_id
        else:
            import hashlib
            ip_address = request.client.host if request.client else "unknown"
            unique_string = f"{ip_address}:{request.url.path}"
            client_id = f"ip_{hashlib.md5(unique_string.encode()).hexdigest()[:12]}"
        
        if not await self._check_rate_limit(client_id, request.url.path):
            logger.warning(f"Rate limit exceeded for client: {client_id}, path: {request.url.path}")
            raise HTTPException(
                status_code=STATUS_CODES["TOO_MANY_REQUESTS"],
                detail="Rate limit exceeded. Please try again later."
            )
        
        return await call_next(request)
    
    async def _check_rate_limit(self, client_id: str, path: str) -> bool:
        """Check if client has exceeded rate limits using async Redis operations."""
        try:
            client = await get_redis_client(raise_on_error=False)
            if client is None:
                logger.warning(f"Redis unavailable for rate limiting, allowing request for client: {client_id}")
                return True
            
            now = int(time.time())
            
            minute_key = f"rate_limit:minute:{client_id}:{path}:{now // 60}"
            hour_key = f"rate_limit:hour:{client_id}:{path}:{now // 3600}"
            
            async with client.pipeline(transaction=False) as pipe:
                await pipe.incr(minute_key)
                await pipe.expire(minute_key, 60)
                await pipe.incr(hour_key)
                await pipe.expire(hour_key, 3600)
                results = await pipe.execute()
            
            minute_count = results[0]
            hour_count = results[2]
            
            if minute_count > self.per_minute:
                return False
            
            if hour_count > self.per_hour:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Rate limit check failed: {str(e)}", exc_info=True)
            return True
