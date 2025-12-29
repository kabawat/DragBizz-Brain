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
        # Access user from request state (set by auth middleware)
        user = getattr(request.state, 'user', None)
        user_id = user.get('sub') or user.get('id') if user else None
        
        # Initialize service and use context manager for proper resource cleanup
        async with CustomerChatService() as service:
            # Handle conversation with user_id for subscription limits
            response = await service.handle_conversation(payload, user_id=user_id)
            
            # Return success response using standardized handler
            return success_response(
                message="Conversation processed successfully",
                data=response.model_dump()
            )
        
    except HTTPException:
        # Re-raise HTTP exceptions (from middleware, etc.)
        raise
    except Exception as err:
        # Use standardized error handler
        error_data = parse_error_for_response(err)
        return error_response(
            message=error_data.get("message", "An error occurred during conversation"),
            status_code=error_data.get("status_code", 500)
        )

