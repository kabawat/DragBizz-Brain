from typing import Any, Dict, Optional
import json
import uuid
import logging
import asyncio
import re
from datetime import datetime

import redis.asyncio as aioredis
from fastapi import HTTPException

from app.config.settings import get_settings
from app.services.redis_manager import get_redis_client

logger = logging.getLogger(__name__)


class SessionService:
    """Service for managing conversation sessions in Redis with async connection pooling."""
    
    def __init__(self):
        self.settings = get_settings()
        self.session_ttl = self.settings.session_ttl
    
    async def _get_redis_client(self) -> Optional[aioredis.Redis]:
        """Get async Redis client from connection pool. Returns None if Redis is unavailable."""
        return await get_redis_client(raise_on_error=False)
    
    def _get_key(self, session_id: str) -> str:
        return f"voice_ai:session:{session_id}"
    
    def _validate_session_id(self, session_id: str) -> bool:
        """Validate session_id format (UUID format)."""
        if not session_id or not isinstance(session_id, str):
            return False
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        return bool(re.match(uuid_pattern, session_id.lower()))
    
    async def create_session(self, initial_data: Dict[str, Any] | None = None) -> str:
        client = await self._get_redis_client()
        if client is None:
            logger.error("Redis unavailable, cannot create session")
            raise HTTPException(status_code=503, detail="Session service temporarily unavailable")
        
        session_id = str(uuid.uuid4())
        session_data = {
            "session_id": session_id,
            "extracted_data": initial_data or {},
            "created_at": datetime.utcnow().isoformat(),
            "turn_count": 0
        }
        
        key = self._get_key(session_id)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await client.setex(
                    key,
                    self.session_ttl,
                    json.dumps(session_data)
                )
                return session_id
            except (aioredis.ConnectionError, aioredis.TimeoutError) as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                logger.error(f"Error creating session after {max_retries} attempts: {str(e)}")
                raise HTTPException(status_code=503, detail="Session service unavailable")
            except Exception as e:
                logger.error(f"Error creating session: {str(e)}", exc_info=True)
                raise HTTPException(status_code=500, detail="Failed to create session")
    
    async def get_session(self, session_id: str, refresh_ttl: bool = True) -> Dict[str, Any] | None:
        if not self._validate_session_id(session_id):
            logger.warning(f"Invalid session_id format: {session_id}")
            return None
        
        client = await self._get_redis_client()
        if client is None:
            logger.warning(f"Redis unavailable, cannot get session {session_id}")
            return None
        
        key = self._get_key(session_id)
        try:
            data = await client.get(key)
            if not data:
                return None
            
            session = json.loads(data)
            if refresh_ttl:
                await client.expire(key, self.session_ttl)
            return session
        except json.JSONDecodeError:
            logger.error(f"Error decoding session {session_id}")
            return None
        except (aioredis.ConnectionError, aioredis.TimeoutError) as e:
            logger.error(f"Redis error getting session {session_id}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error getting session {session_id}: {str(e)}", exc_info=True)
            return None
    
    async def update_session(self, session_id: str, updates: Dict[str, Any]) -> bool:
        if not self._validate_session_id(session_id):
            logger.warning(f"Invalid session_id format: {session_id}")
            return False
        
        client = await self._get_redis_client()
        if client is None:
            logger.warning(f"Redis unavailable, cannot update session {session_id}")
            return False
        
        key = self._get_key(session_id)
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                await client.watch(key)
                data = await client.get(key)
                if not data:
                    await client.unwatch()
                    return False
                
                session = json.loads(data)
                session.update(updates)
                session["turn_count"] = session.get("turn_count", 0) + 1
                
                pipe = client.pipeline(transaction=True)
                pipe.setex(key, self.session_ttl, json.dumps(session))
                await pipe.execute()
                return True
                
            except aioredis.WatchError:
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.05)
                    continue
                return False
            except (aioredis.ConnectionError, aioredis.TimeoutError) as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                logger.error(f"Redis error updating session {session_id}: {str(e)}")
                return False
            except Exception as e:
                logger.error(f"Error updating session {session_id}: {str(e)}", exc_info=True)
                return False
        
        return False
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        if not self._validate_session_id(session_id):
            logger.warning(f"Invalid session_id format: {session_id}")
            return False
        
        client = await self._get_redis_client()
        if client is None:
            logger.warning(f"Redis unavailable, cannot delete session {session_id}")
            return False
        key = self._get_key(session_id)
        try:
            result = await client.delete(key)
            return bool(result)
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {str(e)}")
            return False
