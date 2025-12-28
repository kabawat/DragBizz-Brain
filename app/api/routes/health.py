from fastapi import APIRouter

from app.controllers.health_controller import get_health as get_health_controller, ping as ping_controller

router = APIRouter()


@router.get("/")
async def get_health():
    return await get_health_controller()


@router.get("/ping")
async def ping():
    return await ping_controller()

