from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.customer import router as customer_router
from app.api.routes.supplier import router as supplier_router

# Central place to register all versioned route groups.
api_router = APIRouter()

# Health and readiness endpoints.
api_router.include_router(health_router, prefix="/api/v1/health", tags=["health"])
api_router.include_router(customer_router, prefix="/api/v1/customer", tags=["customer"])
api_router.include_router(supplier_router, prefix="/api/v1/supplier", tags=["supplier"])

