"""
Logger Utility
"""
import logging
import sys
from app.config.settings import settings

def setup_logging():
    """Setup application logging"""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper()),
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(settings.LOG_FILE) if settings.LOG_FILE else logging.NullHandler()
        ]
    )


logger = logging.getLogger("dragbizz_voice_ai")
