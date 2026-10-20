from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

from app.config.base import _empty_as_none, _group_config, _strip_slash


class ServiceSettings(BaseSettings):
    model_config = _group_config()

    base_url: str = Field(
        default="http://dragbizz.local",
        validation_alias="AI_BASE_URL",
    )
    request_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=60,
        validation_alias="AI_REQUEST_TIMEOUT_SECONDS",
    )
    retailer_grpc_host: str = Field(
        default="localhost",
        validation_alias="RETAILER_GRPC_HOST",
    )
    retailer_grpc_port: int = Field(
        default=5001,
        validation_alias="RETAILER_GRPC_PORT",
    )

    @property
    def retailer_grpc_address(self) -> str:
        return f"{self.retailer_grpc_host}:{self.retailer_grpc_port}"

    @property
    def retailer_url(self) -> str:
        return f"{self.base_url}/retailer"

    @property
    def auth_url(self) -> str:
        return f"{self.base_url}/auth"

    @field_validator("base_url")
    @classmethod
    def strip_slash(cls, value: str) -> str:
        return _strip_slash(value)


class JwtSettings(BaseSettings):
    model_config = _group_config()

    issuer: str = Field(default="DragBizz-auth", validation_alias="AI_JWT_ISSUER")
    audience: str = Field(default="DRAGBIZZ", validation_alias="AI_JWT_AUDIENCE")
    algorithms: list[str] = Field(
        default_factory=lambda: ["RS256"],
        validation_alias="AI_JWT_ALGORITHMS",
    )
    url: str | None = Field(default=None, validation_alias="AI_JWKS_URL")
    cache_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        le=86_400,
        validation_alias="AI_JWKS_CACHE_TTL_SECONDS",
    )
    clock_skew_seconds: int = Field(
        default=60,
        ge=0,
        le=300,
        validation_alias="AI_JWT_CLOCK_SKEW_SECONDS",
    )

    @field_validator("url", mode="before")
    @classmethod
    def empty_url_as_none(cls, value: object) -> object:
        return _empty_as_none(value)
