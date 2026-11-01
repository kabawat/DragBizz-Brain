from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

from app.config.base import _empty_as_none, _group_config, _strip_slash


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
