from typing import Literal

from pydantic import BaseModel


class ServiceStatus(BaseModel):
    name: str
    status: Literal["ok", "unavailable"]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    environment: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    service: str
    dependencies: list[ServiceStatus]
