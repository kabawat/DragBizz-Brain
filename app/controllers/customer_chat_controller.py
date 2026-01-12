from fastapi import Request, HTTPException

from app.models.customer import CustomerChatRequest, CustomerChatResponse
from app.services.customer_chat_service import CustomerChatService
from app.utils.responseHandler.standardized import (
    success_response,
    error_response,
    parse_error_for_response
)


async def chat_customer(request: Request, payload: CustomerChatRequest):
    try:
        async with CustomerChatService() as service:
            response = await service.handle_conversation(payload)
            
            return success_response(
                message="Conversation processed successfully",
                data=response.model_dump()
            )
        
    except HTTPException as e:
        error_detail = e.detail
        
        # Safely handle error_detail - it can be dict or string
        if isinstance(error_detail, dict):
            error_message = error_detail.get("message", "An error occurred")
            error_type = error_detail.get("error_type", "unknown")
            quota = error_detail.get("quota", {}) if isinstance(error_detail.get("quota"), dict) else {}
            
            if error_type == "subscription_error":
                if quota.get("hasAccess") is False:
                    user_message = "Voice AI feature is not available in your current subscription plan. Please upgrade your plan to use this feature."
                else:
                    user_message = error_message
                
                return error_response(
                    message=user_message,
                    error=error_message if error_message != user_message else None,
                    status_code=e.status_code,
                    fields={"quota": quota} if quota else None
                )
        
        raise
    except Exception as err:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Unexpected error in chat_customer: {str(err)}", exc_info=True)
        error_data = parse_error_for_response(err)
        return error_response(
            message=error_data.get("message", "An error occurred during conversation"),
            status_code=error_data.get("status_code", 500)
        )

