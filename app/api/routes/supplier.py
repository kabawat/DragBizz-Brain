from fastapi import APIRouter, Depends, Request

from app.controllers.supplier_chat_controller import chat_supplier as chat_supplier_controller
from app.models.supplier import SupplierChatRequest
from app.middlewares.auth_middleware import verify_token
from app.middlewares.ai_feature_middleware import check_ai_feature_access

router = APIRouter(tags=["supplier"])


@router.post("/chat")
async def chat_supplier(
    request: Request,
    payload: SupplierChatRequest,
    user: dict = Depends(verify_token),  # First verify authentication
    ai_access: dict = Depends(check_ai_feature_access)  # Then check AI feature access
):
    return await chat_supplier_controller(request, payload)

