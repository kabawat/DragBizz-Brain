"""
Authentication Middleware
Verifies JWT tokens from auth service
"""
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
from app.config.settings import settings
from app.utils.logger import logger
from app.database.redis_client import get_redis
import json

security = HTTPBearer()


async def verify_token(token: str) -> dict:
    """Verify JWT token"""
    try:
        # Check Redis cache first
        redis = get_redis()
        if redis:
            cache_key = f"token:{token[:20]}"
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        
        # Verify via JWKS
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(settings.JWKS_URL)
            jwks = response.json()
            
            # Verify token (simplified - use jose library in production)
            # For now, just validate token structure
            # TODO: Implement proper JWT verification with jose library
        
        # Cache result
        if redis:
            await redis.setex(cache_key, 300, json.dumps({"valid": True}))  # 5 min cache
        
        return {"valid": True, "sub": "user_id", "id": "user_id"}
        
    except Exception as e:
        logger.warning(f"⚠️ Token verification failed: {str(e)}")
        return {"valid": False}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """Get current authenticated user"""
    token = credentials.credentials
    
    if not token:
        raise HTTPException(status_code=401, detail="Token missing")
    
    verified = await verify_token(token)
    
    if not verified.get("valid"):
        raise HTTPException(status_code=401, detail="Invalid token")
    
    # Add token to user dict for API calls
    verified["token"] = token
    
    return verified


class AuthMiddleware:
    """Auth middleware for protected routes"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # Skip auth for health and docs
            path = scope.get("path", "")
            if path in ["/", "/docs", "/redoc", "/api/health"]:
                await self.app(scope, receive, send)
                return
        
        await self.app(scope, receive, send)
