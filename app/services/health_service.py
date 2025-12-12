from app.models.health import HealthResponse, PongResponse


class HealthService:
    """Encapsulates simple health/ping logic."""

    def get_health(self) -> HealthResponse:
        return HealthResponse(message="Hello, world!")

    def ping(self) -> PongResponse:
        return PongResponse(status="ok")

