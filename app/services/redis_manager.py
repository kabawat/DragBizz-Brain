"""Redis connection manager with connection pooling for high performance."""
from typing import Optional
import logging
import redis
from redis.connection import ConnectionPool
from fastapi import HTTPException

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

# Global connection pool - singleton pattern
_redis_pool: Optional[ConnectionPool] = None
_redis_client: Optional[redis.Redis] = None


def get_redis_client() -> redis.Redis:
    """Get or create Redis client with connection pooling."""
    global _redis_pool, _redis_client
    
    if _redis_client is not None:
        try:
            _redis_client.ping()
            return _redis_client
        except (redis.ConnectionError, redis.TimeoutError):
            # Connection lost, recreate
            _redis_pool = None
            _redis_client = None
    
    settings = get_settings()
    
    if _redis_pool is None:
        # Create connection pool for better performance
        _redis_pool = ConnectionPool(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            db=settings.redis_db,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            retry_on_timeout=True,
            max_connections=50,  # Allow up to 50 concurrent connections
            health_check_interval=30
        )
    
    try:
        _redis_client = redis.Redis(connection_pool=_redis_pool)
        _redis_client.ping()
        return _redis_client
    except (redis.ConnectionError, redis.TimeoutError) as e:
        logger.error(f"Redis connection failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Redis connection failed: {str(e)}. Please ensure Redis is running."
        )


def close_redis_connections():
    """Close all Redis connections (useful for cleanup)."""
    global _redis_pool, _redis_client
    if _redis_client:
        _redis_client.close()
        _redis_client = None
    if _redis_pool:
        _redis_pool.disconnect()
        _redis_pool = None

