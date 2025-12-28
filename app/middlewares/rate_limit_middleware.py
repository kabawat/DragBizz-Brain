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
        # Skip rate limiting for health checks
        if request.url.path.startswith("/api/v1/health"):
            return await call_next(request)
        
        if not self.enabled:
            return await call_next(request)
        
        # Get user ID from request state (set by auth middleware)
        user_id = None
        if hasattr(request.state, 'user'):
            user_id = request.state.user.get('sub') or request.state.user.get('id')
        
        # Use IP address as fallback identifier
        client_id = user_id or request.client.host if request.client else "unknown"
        
        # Check rate limits
        if not self._check_rate_limit(client_id, request.url.path):
            logger.warning(f"Rate limit exceeded for client: {client_id}, path: {request.url.path}")
            raise HTTPException(
                status_code=STATUS_CODES["TOO_MANY_REQUESTS"],
                detail="Rate limit exceeded. Please try again later."
            )
        
        return await call_next(request)
    
    def _check_rate_limit(self, client_id: str, path: str) -> bool:
        """Check if client has exceeded rate limits."""
        try:
            client = get_redis_client()
            now = int(time.time())
            
            # Per-minute limit
            minute_key = f"rate_limit:minute:{client_id}:{path}:{now // 60}"
            minute_count = client.incr(minute_key)
            if minute_count == 1:
                client.expire(minute_key, 60)
            
            if minute_count > self.per_minute:
                return False
            
            # Per-hour limit
            hour_key = f"rate_limit:hour:{client_id}:{path}:{now // 3600}"
            hour_count = client.incr(hour_key)
            if hour_count == 1:
                client.expire(hour_key, 3600)
            
            if hour_count > self.per_hour:
                return False
            
            return True
            
        except Exception as e:
            # If Redis fails, allow request (fail open for availability)
            logger.error(f"Rate limit check failed: {str(e)}", exc_info=logger.isEnabledFor(logging.DEBUG))
            return True

