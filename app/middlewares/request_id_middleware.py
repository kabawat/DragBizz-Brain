"""Request ID middleware for request tracking and debugging."""
from typing import Callable
import uuid
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add request ID to all requests for tracking and debugging."""
    
    def __init__(self, app):
        super().__init__(app)
        self.settings = get_settings()
        self.enabled = self.settings.enable_request_id
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Add request ID to request state and response headers."""
        if self.enabled:
            # Get request ID from header or generate new one
            request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
            request.state.request_id = request_id
            
            # Add to logger context
            logger.info(f"Request started: {request.method} {request.url.path}", extra={"request_id": request_id})
        
        response = await call_next(request)
        
        if self.enabled and hasattr(request.state, 'request_id'):
            # Add request ID to response headers
            response.headers["X-Request-ID"] = request.state.request_id
        
        return response

