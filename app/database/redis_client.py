"""
Redis Client for Caching and Session Management
"""
import redis.asyncio as redis
from app.config.settings import settings
from app.utils.logger import logger

# Global Redis client
redis_client: redis.Redis = None


async def init_redis():
    """Initialize Redis connection"""
    global redis_client
    
    try:
        redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
            db=settings.REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=5
        )
        
        # Test connection
        await redis_client.ping()
        
        logger.info("✅ Redis connected successfully")
        
    except Exception as e:
        logger.warning(f"⚠️ Redis connection failed: {str(e)}")
        logger.warning("⚠️ Continuing without Redis cache")
        redis_client = None


async def close_redis():
    """Close Redis connection"""
    global redis_client
    
    if redis_client:
        await redis_client.close()
        logger.info("✅ Redis connection closed")


def get_redis():
    """Get Redis client instance"""
    return redis_client
