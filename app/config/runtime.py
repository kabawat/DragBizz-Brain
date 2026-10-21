from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

from app.config.base import _empty_as_none, _group_config


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
    # Durable chat archive (existing Mongo). Empty = history APIs fail-open.
    mongodb_uri: str | None = Field(
        default=None,
        validation_alias="AI_MONGODB_URI",
    )

    @field_validator("mongodb_uri", mode="before")
    @classmethod
    def empty_mongodb_as_none(cls, value: object) -> object:
        return _empty_as_none(value)


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
    chat_rate_per_minute: int = Field(
        default=30,
        ge=0,
        validation_alias="AI_CHAT_RATE_PER_MINUTE",
    )
    confirm_rate_per_minute: int = Field(
        default=20,
        ge=0,
        validation_alias="AI_CONFIRM_RATE_PER_MINUTE",
    )
    max_concurrent_chats: int = Field(
        default=2,
        ge=0,
        validation_alias="AI_MAX_CONCURRENT_CHATS_PER_STORE_USER",
    )
    max_concurrent_confirms: int = Field(
        default=2,
        ge=0,
        validation_alias="AI_MAX_CONCURRENT_CONFIRMS_PER_STORE_USER",
    )
    concurrency_lease_seconds: int = Field(
        default=60,
        ge=5,
        le=600,
        validation_alias="AI_CONCURRENCY_LEASE_SECONDS",
    )
    max_model_calls: int = Field(
        default=6,
        ge=1,
        le=20,
        validation_alias="AI_MAX_MODEL_CALLS",
    )
    max_tool_calls: int = Field(
        default=15,
        ge=1,
        le=40,
        validation_alias="AI_MAX_TOOL_CALLS",
    )
    max_estimated_input_tokens: int = Field(
        default=30_000,
        ge=1_000,
        le=200_000,
        validation_alias="AI_MAX_ESTIMATED_INPUT_TOKENS",
    )
    max_estimated_output_tokens: int = Field(
        default=4_000,
        ge=256,
        le=64_000,
        validation_alias="AI_MAX_ESTIMATED_OUTPUT_TOKENS",
    )
    request_deadline_seconds: float = Field(
        default=90.0,
        gt=1,
        le=300,
        validation_alias="AI_REQUEST_DEADLINE_SECONDS",
    )
    tool_timeout_seconds: float = Field(
        default=5.0,
        gt=0.5,
        le=5.0,
        validation_alias="AI_TOOL_TIMEOUT_SECONDS",
    )
    breaker_failure_threshold: int = Field(
        default=5,
        ge=1,
        le=50,
        validation_alias="AI_BREAKER_FAILURE_THRESHOLD",
    )
    breaker_cooldown_seconds: float = Field(
        default=30.0,
        gt=0,
        le=600,
        validation_alias="AI_BREAKER_COOLDOWN_SECONDS",
    )
    pricing_version: str = Field(
        default="v1",
        min_length=1,
        max_length=32,
        validation_alias="AI_PRICING_VERSION",
    )
    embedding_usd_per_million_tokens: float = Field(
        default=0.02,
        ge=0,
        validation_alias="AI_EMBEDDING_USD_PER_MILLION_TOKENS",
    )

    @field_validator("redis_url", "audit_trail_path", mode="before")
    @classmethod
    def empty_as_none(cls, value: object) -> object:
        return _empty_as_none(value)


class EventSettings(BaseSettings):
    model_config = _group_config()

    stream_name: str = Field(
        default="stream:events:domain",
        validation_alias="AI_EVENTS_STREAM_NAME",
    )
    consumer_group: str = Field(
        default="group:brain-ai",
        validation_alias="AI_EVENTS_CONSUMER_GROUP",
    )
    consumer_min_idle_ms: int = Field(
        default=30000,
        ge=1000,
        validation_alias="AI_EVENTS_CONSUMER_MIN_IDLE_MS",
    )
    consumer_poll_timeout_ms: int = Field(
        default=2000,
        ge=100,
        le=30000,
        validation_alias="AI_EVENTS_POLL_TIMEOUT_MS",
    )
    consumer_max_retries: int = Field(
        default=3,
        ge=1,
        le=20,
        validation_alias="AI_EVENTS_MAX_RETRIES",
    )
    consumer_batch_size: int = Field(
        default=10,
        ge=1,
        le=100,
        validation_alias="AI_EVENTS_BATCH_SIZE",
    )
    consumer_enabled: bool = Field(
        default=True,
        validation_alias="AI_EVENTS_CONSUMER_ENABLED",
    )


class ProactiveSettings(BaseSettings):
    model_config = _group_config()

    alerts_enabled: bool = Field(
        default=False,
        validation_alias="AI_PROACTIVE_ALERTS_ENABLED",
    )
    daily_brief_enabled: bool = Field(
        default=False,
        validation_alias="AI_DAILY_BRIEF_ENABLED",
    )
    low_stock_cooldown_seconds: int = Field(
        default=86400,
        ge=60,
        validation_alias="AI_LOW_STOCK_COOLDOWN_SECONDS",
    )
    daily_brief_time: str = Field(
        default="08:00",
        validation_alias="AI_DAILY_BRIEF_TIME",
    )
    daily_brief_timezone: str = Field(
        default="Asia/Kolkata",
        validation_alias="AI_DAILY_BRIEF_TIMEZONE",
    )
    claim_ttl_seconds: int = Field(
        default=60,
        ge=10,
        le=600,
        validation_alias="AI_PROACTIVE_CLAIM_TTL_SECONDS",
    )
