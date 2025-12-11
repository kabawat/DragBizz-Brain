"""
FastAPI Application Entry Point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from app.config.settings import settings
from app.routers import voice, sessions, health
from app.middleware.auth import AuthMiddleware
from app.utils.logger import setup_logging

# Setup logging
setup_logging()

# Initialize FastAPI app
app = FastAPI(
    title="DragBizz Voice AI Service",
    description="AI-powered voice command processing for DragBizz retail management",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth Middleware (for protected routes)
app.add_middleware(AuthMiddleware)

# Include Routers
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(voice.router, prefix="/api/voice", tags=["Voice Commands"])
app.include_router(sessions.router, prefix="/api/voice", tags=["Sessions"])


# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Handle all unhandled exceptions"""
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "Internal server error",
            "error": str(exc) if settings.DEBUG else "An unexpected error occurred"
        }
    )


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    from app.database.mongodb import init_db
    from app.database.redis_client import init_redis
    
    await init_db()
    await init_redis()
    
    print("🚀 DragBizz Voice AI Service started successfully!")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    from app.database.mongodb import close_db
    from app.database.redis_client import close_redis
    
    await close_db()
    await close_redis()
    
    print("👋 DragBizz Voice AI Service shutting down...")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "DragBizz Voice AI Service",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info"
    )
