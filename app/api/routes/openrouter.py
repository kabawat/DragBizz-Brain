from fastapi import APIRouter

from app.controllers.openrouter_controller import OpenRouterController
from app.models.chat import ChatRequest

router = APIRouter(tags=["ai"])
controller = OpenRouterController()


@router.post("/chat")
def chat(payload: ChatRequest):
    return controller.chat(payload)

