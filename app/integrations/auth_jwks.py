from __future__ import annotations

import time
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

from app.config import Settings, get_settings
from app.core.exceptions import AppError


def normalize_access_claims(payload: dict[str, Any]) -> dict[str, Any]:
    claims = dict(payload)
    if claims.get("sub") is not None:
        claims["sub"] = str(claims["sub"])
    if claims.get("agencyId") is not None:
        claims["agencyId"] = str(claims["agencyId"])
    if claims.get("tenant") is not None:
        claims["tenant"] = str(claims["tenant"]).strip().lower()
    return claims


class JwksTokenVerifier:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        jwks_client: PyJWKClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._jwks_client = jwks_client or PyJWKClient(
            self._settings.jwt.url,
            cache_keys=True,
            lifespan=self._settings.jwt.cache_ttl_seconds,
        )

    async def verify(
        self, token: str, http_client: httpx.AsyncClient
    ) -> dict[str, Any]:
        # PyJWKClient fetches JWKS; keep client for a shared transport later.
        del http_client
        try:
            signing_key = await self._get_signing_key(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=self._settings.jwt.algorithms,
                audience=self._settings.jwt.audience,
                issuer=self._settings.jwt.issuer,
                leeway=self._settings.jwt.clock_skew_seconds,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AppError(
                code="AUTH_EXPIRED",
                message="Access token expired",
                status_code=401,
            ) from exc
        except jwt.InvalidTokenError as exc:
            raise AppError(
                code="AUTH_INVALID",
                message="Invalid access token",
                status_code=401,
            ) from exc

        return normalize_access_claims(payload)

    async def _get_signing_key(self, token: str):
        # Sync JWKS lookup; to_thread can wrap this later if needed.
        # Phase 1 keeps it simple — keys are cached after first fetch.
        return self._jwks_client.get_signing_key_from_jwt(token)


_verifier: JwksTokenVerifier | None = None
_verifier_created_at = 0.0


def get_token_verifier(settings: Settings | None = None) -> JwksTokenVerifier:
    global _verifier, _verifier_created_at
    settings = settings or get_settings()
    now = time.monotonic()
    ttl = settings.jwt.cache_ttl_seconds
    if _verifier is None or now - _verifier_created_at > ttl:
        _verifier = JwksTokenVerifier(settings)
        _verifier_created_at = now
    return _verifier


def reset_token_verifier() -> None:
    global _verifier, _verifier_created_at
    _verifier = None
    _verifier_created_at = 0.0
