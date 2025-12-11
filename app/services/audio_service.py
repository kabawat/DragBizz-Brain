"""
Audio Processing Service
Handles speech-to-text conversion using OpenAI Whisper
"""
import openai
from app.config.settings import settings
from app.utils.logger import logger
from pathlib import Path
import tempfile
import os


class AudioService:
    """Audio processing service"""
    
    def __init__(self):
        openai.api_key = settings.OPENAI_API_KEY
        self.model = settings.WHISPER_MODEL
    
    async def transcribe_audio(self, audio_file_path: str, language: str = "hinglish") -> dict:
        """
        Convert audio to text using OpenAI Whisper
        
        Args:
            audio_file_path: Path to audio file
            language: Language code (en, hi, hinglish)
        
        Returns:
            dict: Transcription result with text and metadata
        """
        try:
            logger.info(f"🎤 Transcribing audio: {audio_file_path}")
            
            # Map language codes
            language_map = {
                "hinglish": None,  # Auto-detect
                "hi": "hi",
                "en": "en"
            }
            whisper_language = language_map.get(language.lower(), None)
            
            with open(audio_file_path, "rb") as audio_file:
                transcript = openai.Audio.transcribe(
                    model=self.model,
                    file=audio_file,
                    language=whisper_language,
                    response_format="verbose_json"
                )
            
            result = {
                "text": transcript.text,
                "language": transcript.language,
                "duration": transcript.duration,
                "segments": [
                    {
                        "start": seg.start,
                        "end": seg.end,
                        "text": seg.text
                    }
                    for seg in transcript.segments
                ] if hasattr(transcript, 'segments') else []
            }
            
            logger.info(f"✅ Transcription successful: {len(result['text'])} characters")
            return result
            
        except Exception as e:
            logger.error(f"❌ Transcription failed: {str(e)}")
            raise Exception(f"Audio transcription failed: {str(e)}")
    
    async def save_audio_file(self, audio_data: bytes, filename: str) -> str:
        """
        Save audio file to storage
        
        Args:
            audio_data: Audio file bytes
            filename: Original filename
        
        Returns:
            str: Path to saved file
        """
        try:
            storage_path = Path(settings.AUDIO_STORAGE_PATH)
            storage_path.mkdir(parents=True, exist_ok=True)
            
            # Generate unique filename
            import uuid
            file_extension = Path(filename).suffix or ".webm"
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            file_path = storage_path / unique_filename
            
            # Save file
            with open(file_path, "wb") as f:
                f.write(audio_data)
            
            logger.info(f"💾 Audio file saved: {file_path}")
            return str(file_path)
            
        except Exception as e:
            logger.error(f"❌ Failed to save audio file: {str(e)}")
            raise Exception(f"Failed to save audio file: {str(e)}")
    
    def validate_audio_file(self, file_size: int, duration: float = None) -> bool:
        """
        Validate audio file
        
        Args:
            file_size: File size in bytes
            duration: Audio duration in seconds (optional)
        
        Returns:
            bool: True if valid
        """
        max_size = settings.MAX_AUDIO_SIZE_MB * 1024 * 1024  # Convert to bytes
        
        if file_size > max_size:
            raise ValueError(f"Audio file too large. Max size: {settings.MAX_AUDIO_SIZE_MB}MB")
        
        if duration and duration > settings.MAX_AUDIO_DURATION_SEC:
            raise ValueError(f"Audio too long. Max duration: {settings.MAX_AUDIO_DURATION_SEC} seconds")
        
        return True


# Create service instance
audio_service = AudioService()
