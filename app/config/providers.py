from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

from app.config.base import _empty_as_none, _group_config, _strip_slash


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
        default=512,
        ge=1,
        le=8192,
        validation_alias="AI_CHAT_MAX_TOKENS",
    )
    synthesis_max_tokens: int = Field(
        default=256,
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
        default=15.0,
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
    domain_routing_enabled: bool = Field(
        default=True,
        validation_alias="AI_CHAT_DOMAIN_ROUTING_ENABLED",
    )


class GoogleAISettings(BaseSettings):
    """Gemini via the OpenAI-compatible endpoint.

    Switch chat with AI_ACTIVE_PROVIDER=google_ai or openai_compatible.
    Embeddings stay on OpenAI so the existing Qdrant index remains valid.
    """

    model_config = _group_config()

    api_key: str | None = Field(default=None, validation_alias="AI_GOOGLE_API_KEY")
    base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai",
        validation_alias="AI_GOOGLE_BASE_URL",
    )
    model: str = Field(
        default="gemini-3.1-flash-lite",
        validation_alias="AI_GOOGLE_MODEL",
    )
    input_usd_per_million_tokens: float = Field(
        default=0.25,
        ge=0,
        validation_alias="AI_GOOGLE_INPUT_USD_PER_MILLION_TOKENS",
    )
    output_usd_per_million_tokens: float = Field(
        default=1.50,
        ge=0,
        validation_alias="AI_GOOGLE_OUTPUT_USD_PER_MILLION_TOKENS",
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def empty_key_as_none(cls, value: object) -> object:
        return _empty_as_none(value)

    @field_validator("base_url")
    @classmethod
    def strip_slash(cls, value: str) -> str:
        return _strip_slash(value)


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
