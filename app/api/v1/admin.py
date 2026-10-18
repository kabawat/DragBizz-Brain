"""Platform-admin endpoints: model switch, per-tenant usage, metrics.

Model selection is service-global, so these require a platform admin
token (dragbizz-auth Admin collection, role admin/super_admin) — the
same roles the retailer admin middleware accepts. Store owners/staff
cannot change the model other tenants use.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.security import get_current_user
from app.observability.metrics import MetricsRegistry
from app.orchestrator.model_config import ModelSelection, ModelSelectionStore
from app.orchestrator.model_router import ModelRouter
from app.providers.openai_compatible import (
    CHEAPER_PROVIDER_NAME,
    GOOGLE_PROVIDER_NAME,
)
from app.schemas.admin import (
    ModelSelectionRequest,
    ModelSelectionResponse,
    TenantUsageResponse,
)
from app.schemas.chat import assert_valid_store_id
from app.usage import UsageStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

PLATFORM_ADMIN_ROLES = frozenset({"admin", "super_admin"})


async def require_platform_admin(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    if user.get("role") not in PLATFORM_ADMIN_ROLES:
        raise AppError(
            code="ADMIN_FORBIDDEN",
            message="Platform admin role required",
            status_code=403,
        )
    return user


def _model_router(request: Request) -> ModelRouter:
    return request.app.state.model_router


def _selection_store(request: Request) -> ModelSelectionStore:
    return request.app.state.model_selection_store


def _usage_store(request: Request) -> UsageStore:
    return request.app.state.usage_store


def _metrics(request: Request) -> MetricsRegistry:
    return request.app.state.metrics


def _configured_model(settings: Settings, provider: str) -> str:
    if provider == GOOGLE_PROVIDER_NAME:
        return settings.google.model
    if provider == CHEAPER_PROVIDER_NAME:
        return settings.cheaper_inference.model
    return settings.openai.model


def _allowed_models(settings: Settings) -> list[str]:
    models = {settings.openai.model, *settings.openai.allowed_models}
    if settings.google.api_key and settings.google.model:
        models.add(settings.google.model)
    if settings.cheaper_inference.api_key and settings.cheaper_inference.model:
        models.add(settings.cheaper_inference.model)
    return sorted(models)


async def _selection_response(
    model_router: ModelRouter,
    selection_store: ModelSelectionStore,
    settings: Settings,
) -> ModelSelectionResponse:
    selection = await selection_store.get()
    if selection is not None and model_router.get(selection.provider) is not None:
        return ModelSelectionResponse(
            provider=selection.provider,
            model=selection.model,
            available_providers=list(model_router.available_providers()),
            allowed_models=_allowed_models(settings),
            updated_by=selection.updated_by,
            updated_at=selection.updated_at,
        )
    return ModelSelectionResponse(
        provider=model_router.get_active().name,
        model=_configured_model(settings, model_router.get_active().name),
        available_providers=list(model_router.available_providers()),
        allowed_models=_allowed_models(settings),
    )


@router.get(
    "/model",
    response_model=ModelSelectionResponse,
    response_model_by_alias=True,
)
async def get_model_selection(
    request: Request,
    _admin: Annotated[dict[str, Any], Depends(require_platform_admin)],
) -> ModelSelectionResponse:
    return await _selection_response(
        _model_router(request), _selection_store(request), get_settings()
    )


@router.put(
    "/model",
    response_model=ModelSelectionResponse,
    response_model_by_alias=True,
)
async def set_model_selection(
    body: ModelSelectionRequest,
    request: Request,
    admin: Annotated[dict[str, Any], Depends(require_platform_admin)],
) -> ModelSelectionResponse:
    settings = get_settings()
    model_router = _model_router(request)

    if model_router.get(body.provider) is None:
        raise AppError(
            code="ADMIN_PROVIDER_UNKNOWN",
            message=f"Provider '{body.provider}' is not registered",
            status_code=400,
        )
    if body.model not in _allowed_models(settings):
        raise AppError(
            code="ADMIN_MODEL_NOT_ALLOWED",
            message=(
                f"Model '{body.model}' is not in the allowed model list "
                "(AI_OPENAI_ALLOWED_MODELS, AI_GOOGLE_MODEL, "
                "or CHEAPER_INFERENCE_MODEL)"
            ),
            status_code=400,
        )

    selection = ModelSelection(
        provider=body.provider,
        model=body.model,
        updated_by=str(admin["sub"]),
        updated_at=datetime.now(UTC).isoformat(),
    )
    await _selection_store(request).set(selection)
    logger.info(
        "Model selection changed",
        extra={
            "audit": {
                "action": "model_selection",
                "provider": selection.provider,
                "model": selection.model,
                "updatedBy": selection.updated_by,
            }
        },
    )
    return await _selection_response(
        model_router, _selection_store(request), settings
    )


@router.get(
    "/usage/{store_id}",
    response_model=TenantUsageResponse,
    response_model_by_alias=True,
)
async def get_tenant_usage(
    store_id: str,
    request: Request,
    _admin: Annotated[dict[str, Any], Depends(require_platform_admin)],
) -> TenantUsageResponse:
    settings = get_settings()
    valid_store_id = assert_valid_store_id(store_id)
    usage = await _usage_store(request).get_today(valid_store_id)
    return TenantUsageResponse(
        store_id=valid_store_id,
        day=usage.day,
        requests=usage.requests,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        cost_usd=usage.cost_usd,
        daily_token_cap=settings.limits.tenant_daily_token_cap,
        daily_cost_cap_usd=settings.limits.tenant_daily_cost_cap_usd,
    )


@router.get("/metrics")
async def get_metrics(
    request: Request,
    _admin: Annotated[dict[str, Any], Depends(require_platform_admin)],
) -> dict:
    return _metrics(request).snapshot()
