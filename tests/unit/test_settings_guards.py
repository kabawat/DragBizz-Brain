"""Production settings + guard enforce rollout."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def _prod(**overrides: object) -> Settings:
    data: dict[str, object] = {
        "environment": "production",
        "auth_service_url": "https://auth.example.com",
        "openai_base_url": "https://api.openai.com/v1",
        "input_guard_mode": "enforce",
        "output_guard_mode": "enforce",
    }
    data.update(overrides)
    return Settings(**data)


def test_production_accepts_enforce_guards() -> None:
    settings = _prod()
    assert settings.input_guard_mode == "enforce"
    assert settings.output_guard_mode == "enforce"
    assert settings.jwks_url == "https://auth.example.com/.well-known/jwks.json"


@pytest.mark.parametrize(
    ("field", "mode"),
    [
        ("input_guard_mode", "log"),
        ("input_guard_mode", "off"),
        ("output_guard_mode", "log"),
        ("output_guard_mode", "off"),
    ],
)
def test_production_requires_enforce_guards(field: str, mode: str) -> None:
    with pytest.raises(ValidationError) as exc:
        _prod(**{field: mode})
    assert "must be 'enforce' in production" in str(exc.value)


def test_non_production_allows_log_guards() -> None:
    settings = Settings(
        environment="development",
        input_guard_mode="log",
        output_guard_mode="log",
    )
    assert settings.input_guard_mode == "log"
    assert settings.output_guard_mode == "log"


def test_production_still_requires_https_jwks() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(
            environment="production",
            auth_service_url="http://auth.example.com",
            openai_base_url="https://api.openai.com/v1",
            input_guard_mode="enforce",
            output_guard_mode="enforce",
        )
    assert "JWKS URL must use HTTPS" in str(exc.value)
