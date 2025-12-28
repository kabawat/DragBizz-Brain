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
        """Create a new session and return session ID."""
        client = self.redis_client
        session_id = str(uuid.uuid4())
        session_data = {
            "session_id": session_id,
            "extracted_data": initial_data or {},
            "created_at": datetime.utcnow().isoformat(),
            "turn_count": 0
        }
        
        key = self._get_key(session_id)
        try:
            client.setex(
                key,
                self.session_ttl,
                json.dumps(session_data)
            )
            logger.debug(f"Created new session: {session_id}")
            return session_id
        except Exception as e:
            logger.error(f"Error creating session: {str(e)}", exc_info=logger.isEnabledFor(logging.DEBUG))
            raise
    
    def get_session(self, session_id: str, refresh_ttl: bool = True) -> Dict[str, Any] | None:
        """Get session data by session ID. Optionally refresh TTL on access."""
        client = self.redis_client
        key = self._get_key(session_id)
        try:
            data = client.get(key)
            
            if not data:
                logger.debug(f"Session not found: {session_id}")
                return None
            
            try:
                session = json.loads(data)
                
                # Refresh TTL on access to keep active sessions alive
                if refresh_ttl:
                    client.expire(key, self.session_ttl)
                
                logger.debug(f"Retrieved session: {session_id}, turn_count: {session.get('turn_count', 0)}")
                return session
            except json.JSONDecodeError as e:
                logger.error(f"Error decoding session {session_id}: {str(e)}")
                return None
        except Exception as e:
            logger.error(f"Error getting session {session_id}: {str(e)}", exc_info=logger.isEnabledFor(logging.DEBUG))
            return None
    
    def update_session(self, session_id: str, updates: Dict[str, Any]) -> bool:
        """Update session data with atomic operation using Redis WATCH/MULTI for race condition prevention."""
        client = self.redis_client
        key = self._get_key(session_id)
        
        # Use WATCH/MULTI/EXEC for atomic read-modify-write (prevents race conditions)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                pipe = client.pipeline()
                pipe.watch(key)
                
                # Get current session data
                data = client.get(key)
                if not data:
                    pipe.unwatch()
                    logger.warning(f"Attempted to update non-existent session: {session_id}")
                    return False
                
                session = json.loads(data)
                
                # Merge updates
                session.update(updates)
                session["turn_count"] = session.get("turn_count", 0) + 1
                
                # Execute atomic update
                pipe.multi()
                pipe.setex(
                    key,
                    self.session_ttl,
                    json.dumps(session)
                )
                pipe.execute()
                
                logger.debug(f"Updated session: {session_id}, turn_count: {session['turn_count']}")
                return True
                
            except redis.WatchError:
                # Another client modified the key, retry
                if attempt < max_retries - 1:
                    logger.debug(f"Session {session_id} modified by another client, retrying...")
                    continue
                else:
                    logger.warning(f"Failed to update session {session_id} after {max_retries} retries")
                    return False
            except Exception as e:
                pipe.unwatch()
                logger.error(f"Error updating session {session_id}: {str(e)}", exc_info=logger.isEnabledFor(logging.DEBUG))
                return False
        
        return False
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        client = self.redis_client
        key = self._get_key(session_id)
        return bool(client.delete(key))
