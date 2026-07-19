from functools import lru_cache
from typing import Literal

from pydantic import Field
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
    retailer_service_url: str = "http://host.docker.internal:4001"
    auth_service_url: str = "http://host.docker.internal:4000"
    utility_service_url: str = "http://host.docker.internal:4003"
    request_timeout_seconds: float = Field(default=10.0, gt=0, le=60)


@lru_cache
def get_settings() -> Settings:
    return Settings()
