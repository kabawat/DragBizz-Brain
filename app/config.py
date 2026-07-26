from functools import lru_cache
from typing import Literal
from urllib.parse import urljoin

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AI_",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "DragBizz AI"
    environment: Literal["development", "test", "production"] = "development"
    host: str = "0.0.0.0"
    port: int = Field(default=4004, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_v1_prefix: str = "/api/v1"
    docs_enabled: bool = True
    cors_origins: list[str] = Field(default_factory=list)
    retailer_service_url: str = "http://dragbizz.local/retailer"
    auth_service_url: str = "http://dragbizz.local/auth"
    utility_service_url: str = "http://dragbizz.local/utility"
    request_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    jwt_issuer: str = "DragBizz-auth"
    jwt_audience: str = "DRAGBIZZ"
    jwt_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    jwks_url: str | None = None
    jwks_cache_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)
    jwt_clock_skew_seconds: int = Field(default=60, ge=0, le=300)
    active_provider: str = "openai_compatible"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    chat_max_tokens: int = Field(default=1024, ge=1, le=8192)
    # Second-turn grounded answer after tools (cost/latency cap).
    chat_synthesis_max_tokens: int = Field(default=512, ge=1, le=4096)
    chat_temperature: float = Field(default=0.2, ge=0, le=2)
    provider_timeout_seconds: float = Field(default=30.0, gt=0, le=60)
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "dragbizz_docs"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, ge=1, le=4096)
    rag_top_k: int = Field(default=5, ge=1, le=20)
    rag_score_threshold: float = Field(default=0.3, ge=0, le=1)
    rag_context_max_tokens: int = Field(default=2000, ge=100, le=8000)
    input_guard_mode: Literal["off", "log", "enforce"] = "log"
    output_guard_mode: Literal["off", "log", "enforce"] = "log"
    # Short-lived multi-turn memory (in-process until Redis).
    session_ttl_seconds: int = Field(default=1_800, ge=60, le=86_400)
    session_max_turns: int = Field(default=10, ge=1, le=50)
    session_history_max_tokens: int = Field(default=2_000, ge=200, le=16_000)
    # Chat pricing for per-request cost metrics (defaults: gpt-4o-mini).
    chat_input_usd_per_million_tokens: float = Field(default=0.15, ge=0)
    chat_output_usd_per_million_tokens: float = Field(default=0.60, ge=0)

    @field_validator(
        "auth_service_url",
        "retailer_service_url",
        "utility_service_url",
        "openai_base_url",
        "qdrant_url",
    )
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("openai_api_key", "qdrant_api_key", mode="before")
    @classmethod
    def empty_key_as_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @model_validator(mode="after")
    def resolve_jwks_url_and_guards(self) -> "Settings":
        resolved = self.jwks_url or urljoin(
            f"{self.auth_service_url}/",
            ".well-known/jwks.json",
        )
        object.__setattr__(self, "jwks_url", resolved)

        if self.environment == "production" and not resolved.startswith("https://"):
            raise ValueError("JWKS URL must use HTTPS in production")

        if self.environment == "production" and not self.openai_base_url.startswith(
            "https://"
        ):
            raise ValueError("OpenAI base URL must use HTTPS in production")

        if self.environment == "production":
            if self.input_guard_mode != "enforce":
                raise ValueError(
                    "AI_INPUT_GUARD_MODE must be 'enforce' in production "
                    "(use 'log' in staging to tune false positives first)"
                )
            if self.output_guard_mode != "enforce":
                raise ValueError(
                    "AI_OUTPUT_GUARD_MODE must be 'enforce' in production "
                    "(use 'log' in staging to tune false positives first)"
                )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
