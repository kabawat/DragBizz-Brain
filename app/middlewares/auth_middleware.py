from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.lib.token import verify_access_token, extract_bearer_token
from app.constants.status_code import STATUS_CODES
from app.utils.responseHandler.standardized import parse_error_for_response

security = HTTPBearer()


async def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    import logging
    logger = logging.getLogger(__name__)
    
    from app.config.settings import get_settings
    
    try:
        settings = get_settings()
        cookie_name = "__Host-at" if settings.is_production else "at"
        token = request.cookies.get(cookie_name)

        # Debug log for troubleshooting similar to other services
        logger.info(f"AuthMiddleware: Checking cookie '{cookie_name}', Token found: {bool(token)}")
        
        if not token:
            raise HTTPException(
                status_code=STATUS_CODES["UNAUTHORIZED"],
                detail="Access token missing or invalid."
            )
        
        result = await verify_access_token(token)
        
        if not result["valid"]:
            if result.get("expired"):
                message = "Access token expired."
            elif result.get("error"):
                error_obj = result.get("error")
                error_str = str(error_obj) if error_obj else "Unknown error"
                logger.warning(f"Token verification failed: {error_str}")
                message = f"Invalid access token: {error_str}"
            else:
                message = "Invalid access token."
            raise HTTPException(
                status_code=STATUS_CODES["UNAUTHORIZED"],
                detail=message
            )
        
        # Attach user and token to request (similar to req.user in Express)
        request.state.user = result["decoded"]
        request.state.token = token
        return result["decoded"]
        
    except HTTPException:
        raise
    except Exception as err:
        logger.error(f"Authentication error: {str(err)}", exc_info=True)
        error_data = parse_error_for_response(err)
        raise HTTPException(
            status_code=error_data.get("status_code", STATUS_CODES["INTERNAL_SERVER_ERROR"]),
            detail=error_data.get("message", "Authentication error")
        )

