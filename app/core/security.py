from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import AppError
from app.integrations.auth_jwks import get_token_verifier

bearer_scheme = HTTPBearer(auto_error=False)

# Matches dragbizz-auth web session cookies (HttpOnly).
_ACCESS_COOKIE_NAMES = ("at", "__Host-at")


def _extract_access_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    if credentials is not None and credentials.scheme.lower() == "bearer":
        token = (credentials.credentials or "").strip()
        if token:
            return token

    for name in _ACCESS_COOKIE_NAMES:
        cookie_token = (request.cookies.get(name) or "").strip()
        if cookie_token:
            return cookie_token
    return None


async def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> dict[str, Any]:
    token = _extract_access_token(request, credentials)
    if not token:
        raise AppError(
            code="AUTH_MISSING",
            message="Access token missing or invalid",
            status_code=401,
        )

    http_client = request.app.state.http_client
    verifier = get_token_verifier()
    claims = await verifier.verify(token, http_client)
    request.state.user = claims
    request.state.access_token = token
    return claims
