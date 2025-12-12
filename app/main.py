from fastapi import FastAPI

from app.api.routes import api_router
from app.config.settings import get_settings


def create_app() -> FastAPI:
    """Application factory to keep setup modular and testable."""
    settings = get_settings()
    app = FastAPI(
        title=settings.project_name,
        version=settings.version,
        debug=settings.debug,
    )

    # Mount all versioned APIs here.
    app.include_router(api_router)

    return app


app = create_app()

