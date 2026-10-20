from functools import lru_cache
from urllib.parse import urljoin

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

from app.config.base import _group_config
from app.config.providers import (
    ChatSettings,
    CheaperInferenceSettings,
    GoogleAISettings,
    OpenAISettings,
)
from app.config.rag import RagSettings
from app.config.runtime import (
    EventSettings,
    GuardSettings,
    LimitSettings,
    ProactiveSettings,
    SessionSettings,
)
from app.config.server import ServerSettings
from app.config.services import JwtSettings, ServiceSettings


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
    google: GoogleAISettings = Field(default_factory=GoogleAISettings)
    chat: ChatSettings = Field(default_factory=ChatSettings)
    cheaper_inference: CheaperInferenceSettings = Field(
        default_factory=CheaperInferenceSettings
    )
    rag: RagSettings = Field(default_factory=RagSettings)
    guards: GuardSettings = Field(default_factory=GuardSettings)
    session: SessionSettings = Field(default_factory=SessionSettings)
    limits: LimitSettings = Field(default_factory=LimitSettings)
    events: EventSettings = Field(default_factory=EventSettings)
    proactive: ProactiveSettings = Field(default_factory=ProactiveSettings)

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
            raise ValueError("Cheaper Inference base URL must use HTTPS in production")

        if (
            self.server.environment == "production"
            and self.google.api_key
            and not self.google.base_url.startswith("https://")
        ):
            raise ValueError("Google AI base URL must use HTTPS in production")

        if self.server.environment == "production":
            if not self.limits.redis_url:
                raise ValueError(
                    "AI_REDIS_URL is required in production "
                    "(shared rate limits, concurrency, and confirmations)"
                )
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
