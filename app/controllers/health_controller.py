import logging
from app.models.health import HealthResponse, PongResponse
from app.utils.responseHandler.standardized import success_response
from app.services.redis_manager import get_redis_client

logger = logging.getLogger(__name__)


async def get_health():
    """Health check endpoint with Redis connectivity check."""
    health_data = {
        "message": "Hello, world!",
        "status": "healthy"
    }
    
    # Check Redis connectivity
    try:
        redis_client = get_redis_client()
        redis_client.ping()
        health_data["redis"] = "connected"
    except Exception as e:
        logger.warning(f"Redis health check failed: {str(e)}")
        health_data["redis"] = "disconnected"
        health_data["status"] = "degraded"
    
    return success_response(
        message="Service is healthy",
        data=health_data
    )


async def ping():
    """Simple ping endpoint for load balancer health checks."""
    return success_response(
        message="Service is alive",
        data={"status": "ok"}
    )

