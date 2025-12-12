from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.openrouter import router as ai_router

# Central place to register all versioned route groups.
api_router = APIRouter()

# Health and readiness endpoints.
api_router.include_router(health_router, prefix="/api/v1/health", tags=["health"])
api_router.include_router(ai_router, prefix="/api/v1/ai", tags=["ai"])

