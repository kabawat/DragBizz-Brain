from typing import Any, Dict, Optional
from fastapi.responses import JSONResponse

from app.constants.status_code import STATUS_CODES


def success_response(
    message: str = "Operation completed successfully",
    data: Any = None,
    status_code: int = STATUS_CODES["OK"],
    meta: Optional[Dict[str, Any]] = None
) -> JSONResponse:
    response = {
        "status": "success",
        "message": message,
        "data": data,
    }
    if meta:
        response.update(meta)
    
    return JSONResponse(status_code=status_code, content=response)


def error_response(
    message: str = "An error occurred",
    error: Optional[str] = None,
    fields: Optional[Dict[str, Any]] = None,
    status_code: int = STATUS_CODES["INTERNAL_SERVER_ERROR"]
) -> JSONResponse:
    response = {
        "status": "error",
        "message": message,
    }
    
    # Only include error in development mode
    import os
    if os.getenv("DEBUG", "false").lower() == "true" and error:
        response["error"] = error
    
    if fields:
        response["fields"] = fields
    
    return JSONResponse(status_code=status_code, content=response)


def created_response(
    message: str = "Resource created successfully",
    data: Any = None
) -> JSONResponse:
    return success_response(
        message=message,
        data=data,
        status_code=STATUS_CODES["CREATED"]
    )


def parse_error_for_response(err: Exception) -> Dict[str, Any]:
    error_message = str(err)
    
    # Handle common error types
    if isinstance(err, ValueError):
        return {
            "message": error_message,
            "status_code": STATUS_CODES["BAD_REQUEST"]
        }
    elif isinstance(err, KeyError):
        return {
            "message": f"Missing required field: {error_message}",
            "status_code": STATUS_CODES["BAD_REQUEST"]
        }
    else:
        return {
            "message": error_message or "An unexpected error occurred",
            "status_code": STATUS_CODES["INTERNAL_SERVER_ERROR"]
        }

