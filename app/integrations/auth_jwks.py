from __future__ import annotations

import asyncio
import logging
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
            header = jwt.get_unverified_header(token)
            logger.info(
                "Auth verification started url=%s kid=%s alg=%s",
                self._settings.jwt.url,
                header.get("kid"),
                header.get("alg"),
            )
        except jwt.InvalidTokenError:
            logger.warning("Auth verification received an invalid JWT header")
        try:
            logger.info("Auth JWKS key lookup started")
            signing_key = await self._get_signing_key(token)
            logger.info("Auth JWKS key lookup succeeded kid=%s", signing_key.key_id)
            logger.info("Auth JWT decode started")
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=self._settings.jwt.algorithms,
                audience=self._settings.jwt.audience,
                issuer=self._settings.jwt.issuer,
                leeway=self._settings.jwt.clock_skew_seconds,
                options={"require": ["exp", "iat", "sub"]},
            )
            logger.info("Auth JWT decode succeeded sub=%s", payload.get("sub"))
        except jwt.ExpiredSignatureError as exc:
            logger.warning("Auth JWT expired")
            raise AppError(
                code="AUTH_EXPIRED",
                message="Access token expired",
                status_code=401,
            ) from exc
        except (
            jwt.PyJWKClientConnectionError,
            jwt.PyJWKSetError,
        ) as exc:
            logger.exception("Auth JWKS fetch or parse failed: %s", exc)
            raise AppError(
                code="AUTH_UNAVAILABLE",
                message="Auth service unavailable",
                status_code=503,
            ) from exc
        except jwt.PyJWKClientError as exc:
            logger.exception("Auth signing key lookup failed: %s", exc)
            err_msg = str(exc).lower()
            if "unable to find a signing key" in err_msg:
                raise AppError(
                    code="AUTH_INVALID",
                    message="Invalid access token",
                    status_code=401,
                ) from exc
            raise AppError(
                code="AUTH_UNAVAILABLE",
                message="Auth service unavailable",
                status_code=503,
            ) from exc
        except (jwt.InvalidTokenError, jwt.PyJWKError) as exc:
            logger.exception("Auth JWT validation failed: %s", exc)
            raise AppError(
                code="AUTH_INVALID",
                message="Invalid access token",
                status_code=401,
            ) from exc

        return normalize_access_claims(payload)

    async def _get_signing_key(self, token: str):
        return await asyncio.to_thread(
            self._jwks_client.get_signing_key_from_jwt, token
        )


_verifier: JwksTokenVerifier | None = None
_verifier_created_at = 0.0
logger = logging.getLogger(__name__)


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
