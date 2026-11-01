from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

from app.config.base import _group_config


class MiddlewareObservabilitySettings(BaseSettings):
    model_config = _group_config()

    mw_uid: str | None = Field(default=None, validation_alias="MW_UID")
    mw_api_key: str | None = Field(default=None, validation_alias="MW_API_KEY")
    mw_project_name: str = Field(
        default="dragbizz-brain", validation_alias="MW_PROJECT_NAME"
    )
    service_name: str = Field(
        default="dragbizz-brain", validation_alias="OTEL_SERVICE_NAME"
    )
    deployment_environment: str = Field(
        default="development", validation_alias="OTEL_DEPLOYMENT_ENVIRONMENT"
    )
    otlp_endpoint: str | None = Field(
        default=None, validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )

    @property
    def is_configured(self) -> bool:
        """True if either direct OTLP endpoint or MW_UID is present."""
        return bool(self.otlp_endpoint or (self.mw_uid and self.mw_api_key))

    @property
    def endpoint_url(self) -> str:
        if self.otlp_endpoint:
            return self.otlp_endpoint.rstrip("/")
        if self.mw_uid:
            return f"https://{self.mw_uid}.middleware.io:443"
        return "http://localhost:9320"
