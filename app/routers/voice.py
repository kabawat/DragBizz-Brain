"""
Voice Command Router
"""
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form
from typing import Optional
from datetime import datetime
import tempfile
import os

from app.models.voice_command import VoiceCommandResponse
from app.services import (
    audio_service,
    nlp_service,
    api_client,
    context_manager
)
from app.database.mongodb import get_database
from app.middleware.auth import get_current_user
from app.utils.logger import logger

router = APIRouter()


@router.post("/command", response_model=VoiceCommandResponse)
async def process_voice_command(
    audio: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    language: str = Form("hinglish"),
    current_user: dict = Depends(get_current_user)
):
    """
    Process voice command
    
    - Upload audio file
    - Convert to text (Whisper)
    - Recognize intent (GPT-4)
    - Execute command (Retailer API)
    - Return result
    """
    try:
        user_id = current_user.get("sub") or current_user.get("id")
        store_id = current_user.get("storeId") or current_user.get("store")
        user_token = current_user.get("token")
        
        if not user_id or not store_id:
            raise HTTPException(status_code=400, detail="User or store information missing")
        
        # Create or get session
        if not session_id:
            session_id = await context_manager.create_session(user_id, store_id)
        else:
            session = await context_manager.get_session(session_id)
            if not session:
                session_id = await context_manager.create_session(user_id, store_id)
        
        # Save audio file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(audio.filename)[1]) as tmp_file:
            audio_data = await audio.read()
            tmp_file.write(audio_data)
            tmp_file_path = tmp_file.name
        
        try:
            # Validate audio
            audio_service.validate_audio_file(len(audio_data))
            
            # Step 1: Transcribe audio
            transcript_result = await audio_service.transcribe_audio(tmp_file_path, language)
            transcript = transcript_result["text"]
            
            # Step 2: Recognize intent
            nlp_result = await nlp_service.recognize_intent(transcript, language)
            intent = nlp_result["intent"]
            entities = nlp_result["entities"]
            confidence = nlp_result.get("confidence", 0.8)
            
            # Step 3: Execute command
            api_result = await api_client.execute_command(
                intent=intent,
                entities=entities,
                user_token=user_token,
                store_id=store_id,
                user_id=user_id
            )
            
            # Step 4: Save voice command record
            db = get_database()
            command_data = {
                "userId": user_id,
                "storeId": store_id,
                "sessionId": session_id,
                "transcript": transcript,
                "intent": intent,
                "entities": entities,
                "confidence": confidence,
                "status": "completed" if api_result["success"] else "failed",
                "language": language,
                "apiEndpoint": api_client._get_endpoint(intent),
                "apiPayload": api_client._build_payload(intent, entities, store_id),
                "apiResponse": api_result if api_result["success"] else None,
                "error": api_result.get("error") if not api_result["success"] else None,
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow(),
                "completedAt": datetime.utcnow() if api_result["success"] else None
            }
            
            result = await db.voice_commands.insert_one(command_data)
            command_id = str(result.inserted_id)
            
            # Update session context
            await context_manager.update_session_context(session_id, intent, command_id)
            
            # Build response
            command_data["id"] = command_id
            command_data["_id"] = command_id
            
            return VoiceCommandResponse(**command_data)
            
        finally:
            # Cleanup temp file
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)
    
    except Exception as e:
        logger.error(f"❌ Voice command processing failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/commands")
async def get_voice_commands(
    limit: int = 20,
    skip: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """Get user's voice command history"""
    try:
        user_id = current_user.get("sub") or current_user.get("id")
        store_id = current_user.get("storeId") or current_user.get("store")
        
        db = get_database()
        cursor = db.voice_commands.find(
            {"userId": user_id, "storeId": store_id}
        ).sort("createdAt", -1).skip(skip).limit(limit)
        
        commands = await cursor.to_list(length=limit)
        
        for cmd in commands:
            cmd["id"] = str(cmd["_id"])
            cmd["_id"] = str(cmd["_id"])
        
        total = await db.voice_commands.count_documents({"userId": user_id, "storeId": store_id})
        
        return {
            "success": True,
            "data": commands,
            "total": total,
            "limit": limit,
            "skip": skip
        }
    
    except Exception as e:
        logger.error(f"❌ Failed to get commands: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
