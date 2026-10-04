from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.exceptions import AppError
from app.schemas.response import HealthResponse, ReadinessResponse, ServiceStatus

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.server.app_name,
        environment=settings.server.environment,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def readiness(request: Request) -> ReadinessResponse | JSONResponse:
    http_client_ready = getattr(request.app.state, "http_client", None) is not None
    provider_status = "unavailable"
    model_router = getattr(request.app.state, "model_router", None)
    if model_router is not None:
        try:
            model_router.get_active()
            provider_status = "ok"
        except AppError:
            provider_status = "unavailable"

    qdrant_status = "unavailable"
    vector_store = getattr(request.app.state, "vector_store", None)
    if vector_store is not None and await vector_store.is_ready():
        qdrant_status = "ok"

    response = ReadinessResponse(
        status="ready" if http_client_ready else "not_ready",
        service=get_settings().server.app_name,
        dependencies=[
            ServiceStatus(
                name="http_client",
                status="ok" if http_client_ready else "unavailable",
            ),
            ServiceStatus(name="ai_provider", status=provider_status),
            ServiceStatus(name="qdrant", status=qdrant_status),
        ],
    )

    if not http_client_ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump(),
        )

    return response
