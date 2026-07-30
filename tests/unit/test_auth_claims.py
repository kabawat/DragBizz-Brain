"""Unit tests for access-token claim normalization."""

from app.integrations.auth_jwks import normalize_access_claims


def test_normalize_access_claims() -> None:
    claims = normalize_access_claims(
        {"sub": 99, "agencyId": 12, "tenant": " Demo "}
    )
    assert claims["sub"] == "99"
    assert claims["agencyId"] == "12"
    assert claims["tenant"] == "demo"
