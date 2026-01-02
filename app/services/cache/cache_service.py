from typing import Any, Optional
import json
import logging

from app.services.redis_manager import get_redis_client

logger = logging.getLogger(__name__)

DEFAULT_TTL = 600


def get_cache(key: str) -> Optional[Any]:
    try:
        client = get_redis_client()
        cached = client.get(key)
        if cached:
            logger.debug(f"Cache hit for key: {key[:50]}...")
            return json.loads(cached)
        logger.debug(f"Cache miss for key: {key[:50]}...")
    except Exception as e:
        logger.warning(f"Cache get error for key {key[:50]}...: {str(e)}", exc_info=logger.isEnabledFor(logging.DEBUG))
    return None


def set_cache(key: str, value: Any, ttl: int = DEFAULT_TTL) -> bool:
    try:
        client = get_redis_client()
        client.setex(
            key,
            ttl,
            json.dumps(value)
        )
        logger.debug(f"Cache set for key: {key[:50]}... with TTL: {ttl}s")
        return True
    except Exception as e:
        logger.warning(f"Cache set error for key {key[:50]}...: {str(e)}", exc_info=logger.isEnabledFor(logging.DEBUG))
        return False

