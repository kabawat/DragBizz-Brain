from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import get_settings
from app.integrations.auth_jwks import JwksTokenVerifier, reset_token_verifier


@pytest.fixture(autouse=True)
def reset_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AI_ENVIRONMENT", "test")
    monkeypatch.setenv("AI_JWT_ISSUER", "DragBizz-auth")
    monkeypatch.setenv("AI_JWT_AUDIENCE", "DRAGBIZZ")
    monkeypatch.setenv("AI_OPENAI_API_KEY", "")
    get_settings.cache_clear()
    reset_token_verifier()
    yield
    get_settings.cache_clear()
    reset_token_verifier()


@pytest.fixture
def rsa_keypair() -> dict[str, Any]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return {"private_pem": private_pem, "public_pem": public_pem}


def make_access_token(
    private_pem: bytes,
    *,
    sub: str = "user-123",
    expired: bool = False,
    audience: str = "DRAGBIZZ",
    issuer: str = "DragBizz-auth",
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "agencyId": "agency-1",
        "tenant": "demo",
        "role": "store_owner",
        "iat": now - 10,
        "exp": now - 120 if expired else now + 3600,
        "iss": issuer,
        "aud": audience,
    }
    return jwt.encode(payload, private_pem, algorithm="RS256")


class StaticPemVerifier(JwksTokenVerifier):
    def __init__(self, public_pem: bytes) -> None:
        super().__init__()
        self._public_pem = public_pem

    async def _get_signing_key(self, token: str):
        class _Key:
            def __init__(self, key: bytes) -> None:
                self.key = key

        return _Key(self._public_pem)
