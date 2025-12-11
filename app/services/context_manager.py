"""
Context Manager Service
Manages conversation context and sessions
"""
from app.database.mongodb import get_database
from app.config.settings import settings
from app.utils.logger import logger
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import uuid


class ContextManager:
    """Manages voice command sessions and context"""
    
    async def create_session(self, user_id: str, store_id: str) -> str:
        """Create a new voice session"""
        try:
            session_id = f"session_{uuid.uuid4().hex[:12]}"
            expires_at = datetime.utcnow() + timedelta(seconds=settings.SESSION_TIMEOUT_SEC)
            
            session_data = {
                "userId": user_id,
                "storeId": store_id,
                "sessionId": session_id,
                "status": "active",
                "context": {
                    "lastCommand": None,
                    "lastIntent": None,
                    "pendingAction": None,
                    "variables": {}
                },
                "commands": [],
                "startedAt": datetime.utcnow(),
                "lastActivityAt": datetime.utcnow(),
                "expiresAt": expires_at
            }
            
            db = get_database()
            await db.voice_sessions.insert_one(session_data)
            
            logger.info(f"✅ Session created: {session_id}")
            return session_id
            
        except Exception as e:
            logger.error(f"❌ Failed to create session: {str(e)}")
            raise
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session by ID"""
        try:
            db = get_database()
            session = await db.voice_sessions.find_one({"sessionId": session_id})
            
            if session:
                session["id"] = str(session["_id"])
                session["_id"] = str(session["_id"])
                return session
            return None
            
        except Exception as e:
            logger.error(f"❌ Failed to get session: {str(e)}")
            return None
    
    async def update_session_context(
        self,
        session_id: str,
        intent: str,
        command_id: str
    ):
        """Update session context"""
        try:
            db = get_database()
            await db.voice_sessions.update_one(
                {"sessionId": session_id},
                {
                    "$set": {
                        "context.lastCommand": command_id,
                        "context.lastIntent": intent,
                        "lastActivityAt": datetime.utcnow()
                    },
                    "$push": {"commands": command_id}
                }
            )
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to update session context: {str(e)}")
    
    async def expire_session(self, session_id: str):
        """Mark session as expired"""
        try:
            db = get_database()
            await db.voice_sessions.update_one(
                {"sessionId": session_id},
                {"$set": {"status": "expired"}}
            )
        except Exception as e:
            logger.warning(f"⚠️ Failed to expire session: {str(e)}")


# Create service instance
context_manager = ContextManager()
