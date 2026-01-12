import logging
from app.utils.responseHandler.standardized import success_response
from app.services.redis_manager import get_redis_client

logger = logging.getLogger(__name__)


async def get_health():
    """Health check endpoint with Redis connectivity check."""
    health_data = {
        "message": "Hello, world!",
        "status": "healthy"
    }
    
    try:
        redis_client = await get_redis_client(raise_on_error=False)
        if redis_client:
            await redis_client.ping()
            health_data["redis"] = "connected"
        else:
            health_data["redis"] = "disconnected"
            health_data["status"] = "degraded"
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