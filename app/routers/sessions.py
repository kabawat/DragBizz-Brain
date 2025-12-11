"""
Voice Session Router
"""
from fastapi import APIRouter, Depends, HTTPException
from app.models.voice_session import VoiceSessionResponse
from app.services import context_manager
from app.middleware.auth import get_current_user
from app.utils.logger import logger

router = APIRouter()


@router.get("/sessions/{session_id}", response_model=VoiceSessionResponse)
async def get_session(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get voice session details"""
    try:
        user_id = current_user.get("sub") or current_user.get("id")
        
        session = await context_manager.get_session(session_id)
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        if session["userId"] != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        session["id"] = str(session["_id"])
        return VoiceSessionResponse(**session)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to get session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions")
async def create_session(current_user: dict = Depends(get_current_user)):
    """Create a new voice session"""
    try:
        user_id = current_user.get("sub") or current_user.get("id")
        store_id = current_user.get("storeId") or current_user.get("store")
        
        if not user_id or not store_id:
            raise HTTPException(status_code=400, detail="User or store information missing")
        
        session_id = await context_manager.create_session(user_id, store_id)
        
        return {
            "success": True,
            "sessionId": session_id,
            "message": "Session created successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to create session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
