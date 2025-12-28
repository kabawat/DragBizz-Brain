from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.config.settings import get_settings
from app.config.logging_config import setup_logging
from app.services.redis_manager import close_redis_connections
from app.services.http import HttpClient
from app.middlewares.rate_limit_middleware import RateLimitMiddleware
from app.middlewares.request_id_middleware import RequestIDMiddleware

# Setup logging
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - startup and shutdown."""
    # Startup
    yield
    # Shutdown - cleanup resources
    await HttpClient.close_shared_client()
    close_redis_connections()


def create_app() -> FastAPI:
    """Application factory to keep setup modular and testable."""
    settings = get_settings()
    app = FastAPI(
        title=settings.project_name,
        version=settings.version,
        debug=settings.debug,
        lifespan=lifespan,
    )

    # CORS Middleware
    # Allow localhost with any port in development, specific origins in production
    if settings.debug:
        # In debug mode, allow localhost with any port
        allow_origin_regex = r"http://(localhost|127\.0\.0\.1)(:\d+)?"
        allow_origins = []
    else:
        allow_origin_regex = None
        allow_origins = [
            "http://localhost:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
        ]
    
    cors_kwargs = {
        "allow_origins": allow_origins if allow_origins else [],
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-Requested-With", "Accept", "ngrok-skip-browser-warning"],
        "expose_headers": ["Content-Length", "Content-Type"],
        "max_age": 86400,
    }
    
    if allow_origin_regex:
        cors_kwargs["allow_origin_regex"] = allow_origin_regex
    
    app.add_middleware(CORSMiddleware, **cors_kwargs)
    
    # Add request ID middleware (for tracking and debugging)
    app.add_middleware(RequestIDMiddleware)
    
    # Add rate limiting middleware (for cost saving and abuse prevention)
    app.add_middleware(RateLimitMiddleware, enabled=settings.rate_limit_enabled)

    # Mount all versioned APIs here.
    app.include_router(api_router)

    return app


app = create_app()

