from fastapi import APIRouter, status

from app.controllers.health_controller import HealthController
from app.models.health import HealthResponse, PongResponse

router = APIRouter()
controller = HealthController()


@router.get("/", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def get_health():
    """Return a hello-style response to verify the service is running."""
    return controller.get_health()


@router.get("/ping", response_model=PongResponse, status_code=status.HTTP_200_OK)
def ping():
    """Lightweight ping endpoint for uptime monitoring."""
    return controller.ping()

