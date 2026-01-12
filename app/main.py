from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.config.settings import get_settings
from app.config.logging_config import setup_logging
from app.services.http import HttpClient
from app.middlewares.rate_limit_middleware import RateLimitMiddleware
from app.middlewares.request_id_middleware import RequestIDMiddleware

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - startup and shutdown."""
    yield
    await HttpClient.close_shared_client()
    from app.services.redis_manager import close_redis_connections
    await close_redis_connections()


def create_app() -> FastAPI:
    """Application factory to keep setup modular and testable."""
    settings = get_settings()
    app = FastAPI(
        title=settings.project_name,
        version=settings.version,
        debug=settings.debug,
        lifespan=lifespan,
    )

    allowed_origins_list = [
        origin.strip() 
        for origin in settings.allowed_origins_list.split(",") 
        if origin.strip()
    ]
    
    if settings.is_production:
        cors_kwargs = {
            "allow_origins": allowed_origins_list,
        }
    else:
        development_origins = allowed_origins_list.copy() if allowed_origins_list else []
        development_origins.extend([
            "http://localhost:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
        ])
        development_origins = list(set(development_origins))
        
        cors_kwargs = {
            "allow_origin_regex": r"http://(localhost|127\.0\.0\.1)(:\d+)?(/.*)?$",
            "allow_origins": development_origins,
        }
    
    app.add_middleware(
        CORSMiddleware,
        **cors_kwargs,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "ngrok-skip-browser-warning"],
        expose_headers=["Content-Length", "Content-Type"],
        max_age=86400,
    )
    
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RateLimitMiddleware, enabled=settings.rate_limit_enabled)
    app.include_router(api_router)

    return app


app = create_app()

