from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.env import load_env

# Ensure environment variables from .env are available before settings load.
load_env()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignore any env vars we don't explicitly model
    )

    project_name: str = "DragBizz Voice AI"
    version: str = "0.1.0"
    debug: bool = False
    openrouter_api_key: str
    openrouter_http_referer: str | None = None
    openrouter_title: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance to avoid re-parsing env files."""
    return Settings()

