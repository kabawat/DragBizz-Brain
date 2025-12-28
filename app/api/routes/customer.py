from fastapi import APIRouter, Depends, Request

from app.controllers.customer_chat_controller import chat_customer as chat_customer_controller
from app.models.customer import CustomerChatRequest
from app.middlewares.auth_middleware import verify_token

router = APIRouter(tags=["customer"])


@router.post("/chat")
async def chat_customer(
    request: Request,
    payload: CustomerChatRequest,
    user: dict = Depends(verify_token)
):
    return await chat_customer_controller(request, payload)
