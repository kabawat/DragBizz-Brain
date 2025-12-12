from functools import lru_cache

from pydantic_settings import BaseSettings

from app.config.env import load_env

# Ensure environment variables from .env are available before settings load.
load_env()


class Settings(BaseSettings):
    project_name: str = "DragBizz Voice AI"
    version: str = "0.1.0"
    debug: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance to avoid re-parsing env files."""
    return Settings()

