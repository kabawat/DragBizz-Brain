from pydantic import BaseModel


class HealthResponse(BaseModel):
    message: str


class PongResponse(BaseModel):
    status: str

