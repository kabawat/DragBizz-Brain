from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

from app.config.base import _group_config

_BIND_HOST = "0.0.0.0"
_BIND_PORT = 4004


class ServerSettings(BaseSettings):
    model_config = _group_config()

    app_name: str = Field(default="DragBizz AI", validation_alias="AI_APP_NAME")
    environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias="AI_ENVIRONMENT",
    )
    # Fixed bind — never taken from AI_HOST / AI_PORT env.
    host: str = _BIND_HOST
    port: int = _BIND_PORT
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

    @model_validator(mode="after")
    def _lock_bind_address(self) -> "ServerSettings":
        self.host = _BIND_HOST
        self.port = _BIND_PORT
        return self
