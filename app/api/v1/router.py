from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.chat import router as chat_router
from app.api.v1.health import router as health_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.sessions import router as sessions_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(chat_router)
api_v1_router.include_router(sessions_router)
api_v1_router.include_router(notifications_router)
api_v1_router.include_router(admin_router)
