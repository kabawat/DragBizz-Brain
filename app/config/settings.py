from functools import lru_cache
from typing import Union

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.env import load_env

load_env()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_name: str = "DragBizz Voice AI"
    version: str = "0.1.0"
    debug: bool = True
    environment: str = "development"
    
    base_url: str = "http://localhost"
    server_url: str | None = None
    allowed_origins: str | None = None
    
    openrouter_api_key: str
    openrouter_http_referer: str | None = None
    openrouter_title: str | None = None
    
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0
    session_ttl: int = 300
    
    jwt_issuer: str = "DragBizz-auth"
    jwt_algorithm: str = "RS256"
    jwt_audience: Union[str, list[str]] = ["DRAGBIZZ"]
    
    http_timeout: int = 30
    ai_request_timeout: int = 30
    
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60
    rate_limit_per_hour: int = 1000
    
    ai_response_cache_ttl: int = 300
    token_verify_cache_ttl: int = 300
    
    enable_request_id: bool = True
    subscription_enabled: bool = True

    # Internal service auth (Voice-AI → Retailer)
    internal_service_secret: str | None = None

    @property
    def is_production(self) -> bool:
        return self.environment == "production"
    
    @property
    def allowed_origins_list(self) -> str:
        """Get allowed origins from env or use default based on environment."""
        if self.allowed_origins:
            return self.allowed_origins
        # Default: same as retailer service
        if self.is_production:
            return "https://dragbizz.com"
        return "http://localhost:3000,https://test.dragbizz.com"
    
    @property
    def retailer_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/retailer"
    
    @property
    def auth_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/auth"
    
    @property
    def subscription_service_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/plans"
    
    @field_validator("jwt_audience", mode="before")
    @classmethod
    def parse_jwt_audience(cls, v):
        if isinstance(v, str):
            if "," in v:
                return [aud.strip() for aud in v.split(",") if aud.strip()]
            return v
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()

