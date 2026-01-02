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
    try:
        auth_header = request.headers.get("authorization")
        token = extract_bearer_token(auth_header)
        
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
                # Include actual error for debugging
                message = f"Invalid access token: {result.get('error')}"
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
        error_data = parse_error_for_response(err)
        raise HTTPException(
            status_code=error_data.get("status_code", STATUS_CODES["INTERNAL_SERVER_ERROR"]),
            detail=error_data.get("message", "Authentication error")
        )

