from fastapi import APIRouter, status

from app.models.health import HealthResponse, PongResponse
from app.services.health_service import HealthService

router = APIRouter(prefix="/health")
service = HealthService()


@router.get("/", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def get_health():
    """Return a hello-style response to verify the service is running."""
    return service.get_health()


@router.get("/ping", response_model=PongResponse, status_code=status.HTTP_200_OK)
def ping():
    """Lightweight ping endpoint for uptime monitoring."""
    return service.ping()

