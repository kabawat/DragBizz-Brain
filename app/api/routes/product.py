from fastapi import APIRouter, Depends, Request, UploadFile, File
from typing import Optional

from app.controllers.product_extract_controller import extract_product_from_image
from app.middlewares.auth_middleware import verify_token
from app.middlewares.ai_feature_middleware import check_ai_feature_access

router = APIRouter(tags=["product"])


@router.post("/extract-from-image")
async def extract_product(
    request: Request,
    image: UploadFile = File(..., description="Product image file (JPEG, PNG, etc.)"),
    user: dict = Depends(verify_token),  # First verify authentication
    ai_access: dict = Depends(check_ai_feature_access)  # Then check AI feature access
):
    return await extract_product_from_image(request, image)

