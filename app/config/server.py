from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings

from app.config.base import _group_config


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
