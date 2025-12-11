"""
Voice Command Model
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from bson import ObjectId


class PyObjectId(ObjectId):
    """Custom ObjectId for Pydantic"""
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    @classmethod
    def __get_pydantic_json_schema__(cls, field_schema):
        field_schema.update(type="string")
        return field_schema


class VoiceCommandEntity(BaseModel):
    """Extracted entities from voice command"""
    productName: Optional[str] = None
    quantity: Optional[int] = None
    customerName: Optional[str] = None
    supplierName: Optional[str] = None
    amount: Optional[float] = None
    category: Optional[str] = None
    discount: Optional[float] = None
    # Add more fields as needed


class VoiceCommandCreate(BaseModel):
    """Create voice command request"""
    userId: str
    storeId: str
    sessionId: Optional[str] = None
    transcript: str
    intent: str
    entities: Dict[str, Any]
    confidence: float = Field(ge=0.0, le=1.0)
    language: str = "hinglish"
    audioUrl: Optional[str] = None


class VoiceCommandResponse(BaseModel):
    """Voice command response"""
    id: str
    userId: str
    storeId: str
    sessionId: Optional[str]
    transcript: str
    intent: str
    entities: Dict[str, Any]
    confidence: float
    status: str
    language: str
    apiEndpoint: Optional[str] = None
    apiPayload: Optional[Dict[str, Any]] = None
    apiResponse: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    audioUrl: Optional[str] = None
    createdAt: datetime
    updatedAt: datetime
    completedAt: Optional[datetime] = None

    class Config:
        from_attributes = True
        json_encoders = {
            ObjectId: str,
            datetime: lambda v: v.isoformat()
        }


class VoiceCommandUpdate(BaseModel):
    """Update voice command"""
    status: Optional[str] = None
    apiEndpoint: Optional[str] = None
    apiPayload: Optional[Dict[str, Any]] = None
    apiResponse: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    completedAt: Optional[datetime] = None
