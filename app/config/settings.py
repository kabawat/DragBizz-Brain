"""
Application Configuration
"""
from pydantic_settings import BaseSettings
from typing import List
import os
from pathlib import Path


class Settings(BaseSettings):
    """Application settings"""
    
    # App Settings
    APP_NAME: str = "DragBizz Voice AI Service"
    VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 8000))
    
    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "https://dragbizz.com",
    ]
    
    # MongoDB
    MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME", "dragbizz")
    
    # Redis
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")
    REDIS_DB: int = int(os.getenv("REDIS_DB", 0))
    
    # JWT/Auth
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "RS256")
    JWT_ISSUER: str = os.getenv("JWT_ISSUER", "dragbizz-auth")
    JWT_AUDIENCE: str = os.getenv("JWT_AUDIENCE", "dragbizz-services")
    JWKS_URL: str = os.getenv("JWKS_URL", "http://localhost:3001/auth/.well-known/jwks.json")
    
    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4")
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "whisper-1")
    
    # Retailer Service
    RETAILER_SERVICE_URL: str = os.getenv("RETAILER_SERVICE_URL", "http://localhost:3002/api")
    AUTH_SERVICE_URL: str = os.getenv("AUTH_SERVICE_URL", "http://localhost:3001/auth")
    
    # Voice Settings
    MAX_AUDIO_SIZE_MB: int = int(os.getenv("MAX_AUDIO_SIZE_MB", 10))
    MAX_AUDIO_DURATION_SEC: int = int(os.getenv("MAX_AUDIO_DURATION_SEC", 60))
    SUPPORTED_AUDIO_FORMATS: List[str] = ["webm", "wav", "mp3", "m4a", "ogg"]
    
    # Session Settings
    SESSION_TIMEOUT_SEC: int = int(os.getenv("SESSION_TIMEOUT_SEC", 3600))  # 1 hour
    MAX_COMMANDS_PER_SESSION: int = int(os.getenv("MAX_COMMANDS_PER_SESSION", 50))
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", 10))
    RATE_LIMIT_PER_HOUR: int = int(os.getenv("RATE_LIMIT_PER_HOUR", 100))
    
    # File Storage
    AUDIO_STORAGE_PATH: str = os.getenv("AUDIO_STORAGE_PATH", "./storage/audio")
    AUDIO_RETENTION_HOURS: int = int(os.getenv("AUDIO_RETENTION_HOURS", 24))
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "./logs/voice-ai.log")
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Create settings instance
settings = Settings()

# Create necessary directories
Path(settings.AUDIO_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
Path(settings.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
