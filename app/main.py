from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import re

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

    # CORS Middleware - EXACT same logic as retailer service
    # Parse allowed origins from environment variable (comma-separated)
    allowed_origins_list = [
        origin.strip() 
        for origin in settings.allowed_origins_list.split(",") 
        if origin.strip()
    ]
    
    # Configure CORS - Development mode: Allow ALL localhost origins (any port)
    # Production mode: Use specific allowed origins only
    if settings.is_production:
        # Production: Use specific allowed origins only
        cors_kwargs = {
            "allow_origins": allowed_origins_list,
        }
    else:
        development_origins = allowed_origins_list.copy() if allowed_origins_list else []
        # Add common development origins explicitly
        development_origins.extend([
            "http://localhost:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
        ])
        # Remove duplicates
        development_origins = list(set(development_origins))
        
        cors_kwargs = {
            "allow_origin_regex": r"http://(localhost|127\.0\.0\.1)(:\d+)?(/.*)?$",
            "allow_origins": development_origins,
        }
    
    # Use FastAPI's built-in CORSMiddleware
    # This is more reliable and handles preflight requests automatically
    app.add_middleware(
        CORSMiddleware,
        **cors_kwargs,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "ngrok-skip-browser-warning"],
        expose_headers=["Content-Length", "Content-Type"],
        max_age=86400,
    )
    
    # Log CORS configuration in development (same as retailer service)
    if not settings.is_production:
        print("=" * 50)
        print("CORS Configuration:")
        print(f"  Environment: {settings.environment}")
        print(f"  Is Production: {settings.is_production}")
        print(f"  Allowed Origins List: {allowed_origins_list}")
        print(f"  Regex Pattern: {cors_kwargs.get('allow_origin_regex', 'None')}")
        print("=" * 50)
    
    # Add request ID middleware (for tracking and debugging)
    app.add_middleware(RequestIDMiddleware)
    
    # Add rate limiting middleware (for cost saving and abuse prevention)
    app.add_middleware(RateLimitMiddleware, enabled=settings.rate_limit_enabled)

    # Mount all versioned APIs here.
    app.include_router(api_router)

    return app


app = create_app()

