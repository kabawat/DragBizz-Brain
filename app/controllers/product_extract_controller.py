from fastapi import Request, HTTPException, UploadFile, File
import logging

from app.services.product_extract_service import ProductExtractService
from app.utils.responseHandler.standardized import (
    success_response,
    error_response,
    parse_error_for_response
)

logger = logging.getLogger(__name__)


async def extract_product_from_image(
    request: Request,
    image: UploadFile = File(...)
):
    try:
        user = getattr(request.state, 'user', None)
        user_id = None
        if user and isinstance(user, dict):
            user_id = user.get('sub') or user.get('id')
        
        logger.info(f"Product extraction request from user: {user_id}")
        
        if not image.content_type or not image.content_type.startswith('image/'):
            logger.warning(f"Invalid file type attempted: {image.content_type}")
            return error_response(
                message="Invalid file type. Please upload an image file (JPEG, PNG, GIF, or WebP).",
                status_code=400
            )
        
        allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
        if image.content_type.lower() not in allowed_types:
            logger.warning(f"Unsupported image type: {image.content_type}")
            return error_response(
                message=f"Unsupported image type: {image.content_type}. Allowed types: JPEG, PNG, GIF, WebP.",
                status_code=400
            )
        
        try:
            image_bytes = await image.read()
        except Exception as e:
            logger.error(f"Error reading image file: {str(e)}", exc_info=True)
            return error_response(
                message="Failed to read image file. Please ensure the file is valid and not corrupted.",
                status_code=400
            )
        
        if len(image_bytes) == 0:
            logger.warning("Empty image file uploaded")
            return error_response(
                message="Image file is empty. Please upload a valid image file.",
                status_code=400
            )
        
        max_size = 10 * 1024 * 1024
        if len(image_bytes) > max_size:
            file_size_mb = len(image_bytes) / 1024 / 1024
            logger.warning(f"Image file too large: {file_size_mb:.2f}MB")
            return error_response(
                message=f"Image file is too large. Maximum size is 10MB. Current size: {file_size_mb:.2f}MB",
                status_code=400
            )
        
        min_size = 1024
        if len(image_bytes) < min_size:
            logger.warning(f"Image file too small: {len(image_bytes)} bytes")
            return error_response(
                message="Image file is too small. Please upload a valid image file.",
                status_code=400
            )
        
        logger.info(f"Processing image extraction. File size: {len(image_bytes) / 1024:.2f}KB, Type: {image.content_type}")
        
        async with ProductExtractService() as service:
            response = await service.extract_product_data(image_bytes, None)
            
            logger.info(f"Product extraction successful for user: {user_id}")
            
            return success_response(
                message=response.message,
                data=response.payload.model_dump(exclude_none=True) if response.payload else None
            )
    
    except HTTPException as e:
        error_detail = e.detail
        
        if isinstance(error_detail, dict):
            error_message = error_detail.get("message", "An error occurred")
        else:
            error_message = str(error_detail)
        
        return error_response(
            message=error_message,
            error=error_message,
            status_code=e.status_code
        )
    
    except Exception as err:
        logger.error(f"Unexpected error in extract_product_from_image: {str(err)}", exc_info=True)
        error_data = parse_error_for_response(err)
        return error_response(
            message=error_data.get("message", "An error occurred during product extraction"),
            status_code=error_data.get("status_code", 500)
        )

