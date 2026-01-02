from typing import Any, Dict
import json
import uuid
import logging
from datetime import datetime

import redis
from fastapi import HTTPException

from app.config.settings import get_settings
from app.services.redis_manager import get_redis_client

logger = logging.getLogger(__name__)


class SessionService:
    """Service for managing conversation sessions in Redis with connection pooling."""
    
    def __init__(self):
        self.settings = get_settings()
        self.session_ttl = self.settings.session_ttl
    
    @property
    def redis_client(self) -> redis.Redis:
        """Get Redis client from connection pool."""
        return get_redis_client()
    
    def _get_key(self, session_id: str) -> str:
        """Get Redis key for session."""
        return f"voice_ai:session:{session_id}"
    
    def create_session(self, initial_data: Dict[str, Any] | None = None) -> str:
        client = self.redis_client
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
                client.setex(
                    key,
                    self.session_ttl,
                    json.dumps(session_data)
                )
                return session_id
            except (redis.ConnectionError, redis.TimeoutError) as e:
                if attempt < max_retries - 1:
                    import time
                    time.sleep(0.1 * (attempt + 1))
                    continue
                logger.error(f"Error creating session after {max_retries} attempts: {str(e)}")
                raise HTTPException(status_code=503, detail="Session service unavailable")
            except Exception as e:
                logger.error(f"Error creating session: {str(e)}", exc_info=True)
                raise HTTPException(status_code=500, detail="Failed to create session")
    
    def get_session(self, session_id: str, refresh_ttl: bool = True) -> Dict[str, Any] | None:
        client = self.redis_client
        key = self._get_key(session_id)
        try:
            data = client.get(key)
            if not data:
                return None
            
            session = json.loads(data)
            if refresh_ttl:
                client.expire(key, self.session_ttl)
            return session
        except json.JSONDecodeError:
            logger.error(f"Error decoding session {session_id}")
            return None
        except (redis.ConnectionError, redis.TimeoutError) as e:
            logger.error(f"Redis error getting session {session_id}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error getting session {session_id}: {str(e)}", exc_info=True)
            return None
    
    def update_session(self, session_id: str, updates: Dict[str, Any]) -> bool:
        client = self.redis_client
        key = self._get_key(session_id)
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                pipe = client.pipeline()
                pipe.watch(key)
                data = client.get(key)
                if not data:
                    pipe.unwatch()
                    return False
                
                session = json.loads(data)
                session.update(updates)
                session["turn_count"] = session.get("turn_count", 0) + 1
                
                pipe.multi()
                pipe.setex(key, self.session_ttl, json.dumps(session))
                pipe.execute()
                return True
                
            except redis.WatchError:
                if attempt < max_retries - 1:
                    continue
                return False
            except (redis.ConnectionError, redis.TimeoutError) as e:
                if attempt < max_retries - 1:
                    import time
                    time.sleep(0.1 * (attempt + 1))
                    continue
                logger.error(f"Redis error updating session {session_id}: {str(e)}")
                return False
            except Exception as e:
                try:
                    pipe.unwatch()
                except:
                    pass
                logger.error(f"Error updating session {session_id}: {str(e)}", exc_info=True)
                return False
        
        return False
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        client = self.redis_client
        key = self._get_key(session_id)
        return bool(client.delete(key))
