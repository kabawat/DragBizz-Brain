from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import AppError
from app.integrations.auth_jwks import get_token_verifier

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(
            code="AUTH_MISSING",
            message="Access token missing or invalid",
            status_code=401,
        )

    http_client = request.app.state.http_client
    verifier = get_token_verifier()
    claims = await verifier.verify(credentials.credentials, http_client)
    request.state.user = claims
    return claims
