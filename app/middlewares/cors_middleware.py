"""Custom CORS middleware matching retailer service behavior."""
import re
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class CustomCORSMiddleware(BaseHTTPMiddleware):
    """CORS middleware that matches retailer service behavior."""
    
    def __init__(
        self,
        app,
        allowed_origins: list[str],
        server_url: str | None = None,
        is_production: bool = False,
    ):
        super().__init__(app)
        self.allowed_origins = allowed_origins
        self.server_url = server_url
        self.is_production = is_production
        
        # Regex patterns for localhost matching (same as retailer service)
        self.localhost_patterns = [
            re.compile(r"^http://localhost(:\d+)?(/.*)?$"),
            re.compile(r"^http://127\.0\.0\.1(:\d+)?(/.*)?$"),
        ]
    
    def is_origin_allowed(self, origin: str | None) -> bool:
        """Check if origin is allowed (same logic as retailer service)."""
        # Allow requests with no origin (like curl/postman)
        if not origin:
            return True
        
        # Always allow server url itself
        if self.server_url and origin == self.server_url:
            return True
        
        # In development, allow any localhost origin (any port) - improved regex
        if not self.is_production:
            # Check regex patterns first
            for pattern in self.localhost_patterns:
                if pattern.match(origin):
                    return True
            # Also check simple startsWith for flexibility (same as retailer service)
            if origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1"):
                return True
        
        # Check against allowed origins list
        if origin in self.allowed_origins:
            return True
        
        return False
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Handle CORS headers."""
        origin = request.headers.get("origin")
        is_allowed = self.is_origin_allowed(origin)
        
        # Log in development (same as retailer service)
        if not self.is_production:
            print(f"CORS check - isAllowed: {is_allowed}, origin: {origin}, method: {request.method}")
        
        # Handle preflight OPTIONS requests
        if request.method == "OPTIONS":
            response = Response(status_code=200)
            if is_allowed and origin:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, Accept, ngrok-skip-browser-warning"
                response.headers["Access-Control-Expose-Headers"] = "Content-Length, Content-Type"
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Access-Control-Max-Age"] = "86400"
            # Always return 200 for OPTIONS, even if origin not allowed
            # (browser will handle the rejection based on missing headers)
            return response
        
        # Handle actual requests
        response = await call_next(request)
        
        # Add CORS headers to response if origin is allowed
        if is_allowed and origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Expose-Headers"] = "Content-Length, Content-Type"
        
        return response

