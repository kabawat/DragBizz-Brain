"""Async Redis connection manager with connection pooling for high performance."""
from typing import Optional
import logging
import redis.asyncio as aioredis
from redis.asyncio.connection import ConnectionPool
from fastapi import HTTPException

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_redis_pool: Optional[ConnectionPool] = None
_redis_client: Optional[aioredis.Redis] = None


async def get_redis_client(raise_on_error: bool = False) -> Optional[aioredis.Redis]:
    """
    Get or create async Redis client with connection pooling.
    
    Args:
        raise_on_error: If True, raises HTTPException on connection failure.
                       If False, returns None on failure (graceful degradation).
    
    Returns:
        Async Redis client or None if connection fails and raise_on_error is False.
    """
    global _redis_pool, _redis_client
    
    if _redis_client is not None:
        try:
            await _redis_client.ping()
            return _redis_client
        except (aioredis.ConnectionError, aioredis.TimeoutError):
            logger.warning("Redis connection lost, attempting to reconnect")
            _redis_pool = None
            _redis_client = None
    
    settings = get_settings()
    
    if _redis_pool is None:
        _redis_pool = ConnectionPool(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            db=settings.redis_db,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            retry_on_timeout=True,
            max_connections=1000,
            health_check_interval=30
        )
    
    try:
        _redis_client = aioredis.Redis(connection_pool=_redis_pool)
        await _redis_client.ping()
        return _redis_client
    except (aioredis.ConnectionError, aioredis.TimeoutError) as e:
        logger.error(f"Redis connection failed: {str(e)}")
        if raise_on_error:
            raise HTTPException(
                status_code=500,
                detail=f"Redis connection failed: {str(e)}. Please ensure Redis is running."
            )
        return None


async def close_redis_connections():
    """Close all Redis connections."""
    global _redis_pool, _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
    if _redis_pool:
        await _redis_pool.aclose()
        _redis_pool = None
