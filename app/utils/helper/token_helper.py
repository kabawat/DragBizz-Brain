"""Token helper utilities."""

from typing import Optional


def get_auth_token(authorization: Optional[str] = None, x_access_token: Optional[str] = None) -> Optional[str]:
    """Get auth token from Authorization header or x-access-token header."""
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0] == "Bearer":
            return parts[1]
    if x_access_token:
        return x_access_token
    return None

