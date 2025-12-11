"""
Voice Session Model
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
from bson import ObjectId


class VoiceSessionContext(BaseModel):
    """Session context"""
    lastCommand: Optional[str] = None
    lastIntent: Optional[str] = None
    pendingAction: Optional[str] = None
    variables: Dict[str, Any] = {}


class VoiceSessionCreate(BaseModel):
    """Create voice session request"""
    userId: str
    storeId: str
    sessionId: Optional[str] = None


class VoiceSessionResponse(BaseModel):
    """Voice session response"""
    id: str
    userId: str
    storeId: str
    sessionId: str
    status: str
    context: VoiceSessionContext
    commands: List[str]
    startedAt: datetime
    lastActivityAt: datetime
    expiresAt: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            ObjectId: str,
            datetime: lambda v: v.isoformat()
        }


class VoiceSessionUpdate(BaseModel):
    """Update voice session"""
    status: Optional[str] = None
    context: Optional[VoiceSessionContext] = None
    lastActivityAt: Optional[datetime] = None
