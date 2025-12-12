from fastapi import APIRouter

from app.controllers.health_controller import router as health_router

# Central place to register all versioned route groups.
api_router = APIRouter(prefix="/api/v1")

# Health and readiness endpoints.
api_router.include_router(health_router, tags=["health"])

