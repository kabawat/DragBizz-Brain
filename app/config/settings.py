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
    debug: bool = False
    
    openrouter_api_key: str
    openrouter_http_referer: str | None = None
    openrouter_title: str | None = None
    
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0
    session_ttl: int = 300
    
    # Base URL for all services (routed through nginx)
    base_url: str = "http://testapi.dragbizz.com"  # Change to your nginx domain
    
    jwt_issuer: str = "DragBizz-auth"
    jwt_algorithm: str = "RS256"
    jwt_audience: Union[str, list[str]] = ["VOICE-AI", "RETAILER"]
    
    @property
    def server_url(self) -> str:
        """Get retailer service URL (routed through nginx /retailer/)."""
        return f"{self.base_url.rstrip('/')}/retailer"
    
    @property
    def auth_url(self) -> str:
        """Get auth service URL (routed through nginx /auth/)."""
        return f"{self.base_url.rstrip('/')}/auth"
    
    # HTTP and API timeouts (for cost optimization and performance)
    http_timeout: int = 30
    ai_request_timeout: int = 30
    
    # Rate limiting (for cost saving and abuse prevention)
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60
    rate_limit_per_hour: int = 1000
    
    # Cache TTL settings (for cost optimization)
    ai_response_cache_ttl: int = 300  # 5 minutes
    token_verify_cache_ttl: int = 300  # 5 minutes
    
    # Request tracking
    enable_request_id: bool = True
    
    # Subscription service configuration
    subscription_enabled: bool = True  # Enable/disable subscription checks
    
    @property
    def subscription_service_url(self) -> str:
        """Get subscription service URL (routed through nginx /plans/)."""
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

