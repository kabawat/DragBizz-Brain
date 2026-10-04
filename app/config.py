from functools import lru_cache
from typing import Literal
from urllib.parse import urljoin

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _group_config() -> SettingsConfigDict:
    return SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )


def _empty_as_none(value: object) -> object:
    if value == "":
        return None
    return value


def _strip_slash(value: str) -> str:
    return value.rstrip("/")


class ServerSettings(BaseSettings):
    model_config = _group_config()

    app_name: str = Field(default="DragBizz AI", validation_alias="AI_APP_NAME")
    environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias="AI_ENVIRONMENT",
    )
    host: str = Field(default="0.0.0.0", validation_alias="AI_HOST")
    port: int = Field(default=4004, ge=1, le=65535, validation_alias="AI_PORT")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        validation_alias="AI_LOG_LEVEL",
    )
    api_v1_prefix: str = Field(default="/api/v1", validation_alias="AI_API_V1_PREFIX")
    docs_enabled: bool = Field(default=True, validation_alias="AI_DOCS_ENABLED")
    cors_origins: list[str] = Field(
        default_factory=list,
        validation_alias="AI_CORS_ORIGINS",
    )


class ServiceSettings(BaseSettings):
    model_config = _group_config()

    base_url: str = Field(
        default="http://dragbizz.local",
        validation_alias="AI_BASE_URL",
    )
    request_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=60,
        validation_alias="AI_REQUEST_TIMEOUT_SECONDS",
    )

    @property
    def retailer_url(self) -> str:
        return f"{self.base_url}/retailer"

    @property
    def auth_url(self) -> str:
        return f"{self.base_url}/auth"

    @property
    def utility_url(self) -> str:
        return f"{self.base_url}/utility"

    @field_validator("base_url")
    @classmethod
    def strip_slash(cls, value: str) -> str:
        return _strip_slash(value)


class JwtSettings(BaseSettings):
    model_config = _group_config()

    issuer: str = Field(default="DragBizz-auth", validation_alias="AI_JWT_ISSUER")
    audience: str = Field(default="DRAGBIZZ", validation_alias="AI_JWT_AUDIENCE")
    algorithms: list[str] = Field(
        default_factory=lambda: ["RS256"],
        validation_alias="AI_JWT_ALGORITHMS",
    )
    url: str | None = Field(default=None, validation_alias="AI_JWKS_URL")
    cache_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        le=86_400,
        validation_alias="AI_JWKS_CACHE_TTL_SECONDS",
    )
    clock_skew_seconds: int = Field(
        default=60,
        ge=0,
        le=300,
        validation_alias="AI_JWT_CLOCK_SKEW_SECONDS",
    )

    @field_validator("url", mode="before")
    @classmethod
    def empty_url_as_none(cls, value: object) -> object:
        return _empty_as_none(value)


class OpenAISettings(BaseSettings):
    model_config = _group_config()

    api_key: str | None = Field(default=None, validation_alias="AI_OPENAI_API_KEY")
    base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias="AI_OPENAI_BASE_URL",
    )
    model: str = Field(default="gpt-4o-mini", validation_alias="AI_OPENAI_MODEL")
    allowed_models: list[str] = Field(
        default_factory=list,
        validation_alias="AI_OPENAI_ALLOWED_MODELS",
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def empty_key_as_none(cls, value: object) -> object:
        return _empty_as_none(value)

    @field_validator("base_url")
    @classmethod
    def strip_slash(cls, value: str) -> str:
        return _strip_slash(value)


class ChatSettings(BaseSettings):
    model_config = _group_config()

    max_tokens: int = Field(
        default=1024,
        ge=1,
        le=8192,
        validation_alias="AI_CHAT_MAX_TOKENS",
    )
    synthesis_max_tokens: int = Field(
        default=512,
        ge=1,
        le=4096,
        validation_alias="AI_CHAT_SYNTHESIS_MAX_TOKENS",
    )
    max_tool_rounds: int = Field(
        default=3,
        ge=1,
        le=6,
        validation_alias="AI_CHAT_MAX_TOOL_ROUNDS",
    )
    temperature: float = Field(
        default=0.2,
        ge=0,
        le=2,
        validation_alias="AI_CHAT_TEMPERATURE",
    )
    provider_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=60,
        validation_alias="AI_PROVIDER_TIMEOUT_SECONDS",
    )
    input_usd_per_million_tokens: float = Field(
        default=0.15,
        ge=0,
        validation_alias="AI_CHAT_INPUT_USD_PER_MILLION_TOKENS",
    )
    output_usd_per_million_tokens: float = Field(
        default=0.60,
        ge=0,
        validation_alias="AI_CHAT_OUTPUT_USD_PER_MILLION_TOKENS",
    )


class CheaperInferenceSettings(BaseSettings):
    model_config = _group_config()

    api_key: str | None = Field(
        default=None,
        validation_alias="CHEAPER_INFERENCE_API_KEY",
    )
    base_url: str = Field(
        default="https://api.cheaperinference.com/v1",
        validation_alias="CHEAPER_INFERENCE_BASE_URL",
    )
    model: str = Field(
        default="deepseek-v4.1-flash",
        validation_alias="CHEAPER_INFERENCE_MODEL",
    )
    temperature: float = Field(
        default=0.2,
        ge=0,
        le=2,
        validation_alias="CHEAPER_INFERENCE_TEMPERATURE",
    )
    max_tokens: int = Field(
        default=1024,
        ge=1,
        le=8192,
        validation_alias="CHEAPER_INFERENCE_MAX_TOKENS",
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def empty_key_as_none(cls, value: object) -> object:
        return _empty_as_none(value)

    @field_validator("base_url")
    @classmethod
    def strip_slash(cls, value: str) -> str:
        return _strip_slash(value)


class RagSettings(BaseSettings):
    model_config = _group_config()

    qdrant_url: str = Field(
        default="http://localhost:6333",
        validation_alias="AI_QDRANT_URL",
    )
    qdrant_api_key: str | None = Field(
        default=None,
        validation_alias="AI_QDRANT_API_KEY",
    )
    collection: str = Field(
        default="dragbizz_docs",
        validation_alias="AI_QDRANT_COLLECTION",
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias="AI_EMBEDDING_MODEL",
    )
    embedding_dimensions: int = Field(
        default=1536,
        ge=1,
        le=4096,
        validation_alias="AI_EMBEDDING_DIMENSIONS",
    )
    top_k: int = Field(default=5, ge=1, le=20, validation_alias="AI_RAG_TOP_K")
    score_threshold: float = Field(
        default=0.3,
        ge=0,
        le=1,
        validation_alias="AI_RAG_SCORE_THRESHOLD",
    )
    context_max_tokens: int = Field(
        default=1000,
        ge=100,
        le=8000,
        validation_alias="AI_RAG_CONTEXT_MAX_TOKENS",
    )
    context_max_tokens_action: int = Field(
        default=512,
        ge=50,
        le=8000,
        validation_alias="AI_RAG_CONTEXT_MAX_TOKENS_ACTION",
    )
    cache_ttl_seconds: int = Field(
        default=1_800,
        ge=0,
        le=86_400,
        validation_alias="AI_RAG_CACHE_TTL_SECONDS",
    )

    @field_validator("qdrant_api_key", mode="before")
    @classmethod
    def empty_key_as_none(cls, value: object) -> object:
        return _empty_as_none(value)

    @field_validator("qdrant_url")
    @classmethod
    def strip_slash(cls, value: str) -> str:
        return _strip_slash(value)


class GuardSettings(BaseSettings):
    model_config = _group_config()

    input_mode: Literal["off", "log", "enforce"] = Field(
        default="log",
        validation_alias="AI_INPUT_GUARD_MODE",
    )
    output_mode: Literal["off", "log", "enforce"] = Field(
        default="log",
        validation_alias="AI_OUTPUT_GUARD_MODE",
    )


class SessionSettings(BaseSettings):
    model_config = _group_config()

    ttl_seconds: int = Field(
        default=1_800,
        ge=60,
        le=86_400,
        validation_alias="AI_SESSION_TTL_SECONDS",
    )
    max_turns: int = Field(
        default=5,
        ge=1,
        le=50,
        validation_alias="AI_SESSION_MAX_TURNS",
    )
    history_max_tokens: int = Field(
        default=1_200,
        ge=200,
        le=16_000,
        validation_alias="AI_SESSION_HISTORY_MAX_TOKENS",
    )
    idempotency_ttl_seconds: int = Field(
        default=86_400,
        ge=60,
        le=604_800,
        validation_alias="AI_IDEMPOTENCY_TTL_SECONDS",
    )
    confirmation_ttl_seconds: int = Field(
        default=300,
        ge=30,
        le=3_600,
        validation_alias="AI_CONFIRMATION_TTL_SECONDS",
    )


class LimitSettings(BaseSettings):
    model_config = _group_config()

    redis_url: str | None = Field(default=None, validation_alias="AI_REDIS_URL")
    tenant_daily_token_cap: int = Field(
        default=0,
        ge=0,
        validation_alias="AI_TENANT_DAILY_TOKEN_CAP",
    )
    tenant_daily_cost_cap_usd: float = Field(
        default=0,
        ge=0,
        validation_alias="AI_TENANT_DAILY_COST_CAP_USD",
    )
    audit_trail_path: str | None = Field(
        default="data/tool_audit.jsonl",
        validation_alias="AI_AUDIT_TRAIL_PATH",
    )

    @field_validator("redis_url", "audit_trail_path", mode="before")
    @classmethod
    def empty_as_none(cls, value: object) -> object:
        return _empty_as_none(value)


class Settings(BaseSettings):
    model_config = _group_config()

    server: ServerSettings = Field(default_factory=ServerSettings)
    services: ServiceSettings = Field(default_factory=ServiceSettings)
    jwt: JwtSettings = Field(default_factory=JwtSettings)
    active_provider: str = Field(
        default="openai_compatible",
        validation_alias="AI_ACTIVE_PROVIDER",
    )
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    chat: ChatSettings = Field(default_factory=ChatSettings)
    cheaper_inference: CheaperInferenceSettings = Field(
        default_factory=CheaperInferenceSettings
    )
    rag: RagSettings = Field(default_factory=RagSettings)
    guards: GuardSettings = Field(default_factory=GuardSettings)
    session: SessionSettings = Field(default_factory=SessionSettings)
    limits: LimitSettings = Field(default_factory=LimitSettings)

    @model_validator(mode="after")
    def resolve_jwks_url_and_guards(self) -> "Settings":
        resolved = self.jwt.url or urljoin(
            f"{self.services.auth_url}/",
            ".well-known/jwks.json",
        )
        object.__setattr__(self, "jwt", self.jwt.model_copy(update={"url": resolved}))

        if self.server.environment == "production" and not resolved.startswith(
            "https://"
        ):
            raise ValueError("JWKS URL must use HTTPS in production")

        openai_https = self.openai.base_url.startswith("https://")
        if self.server.environment == "production" and not openai_https:
            raise ValueError("OpenAI base URL must use HTTPS in production")

        if (
            self.server.environment == "production"
            and self.cheaper_inference.api_key
            and not self.cheaper_inference.base_url.startswith("https://")
        ):
            raise ValueError(
                "Cheaper Inference base URL must use HTTPS in production"
            )

        if self.server.environment == "production":
            if self.guards.input_mode != "enforce":
                raise ValueError(
                    "AI_INPUT_GUARD_MODE must be 'enforce' in production "
                    "(use 'log' in staging to tune false positives first)"
                )
            if self.guards.output_mode != "enforce":
                raise ValueError(
                    "AI_OUTPUT_GUARD_MODE must be 'enforce' in production "
                    "(use 'log' in staging to tune false positives first)"
                )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
