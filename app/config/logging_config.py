"""Logging configuration for the application."""
import logging
import sys
from typing import Any, Dict

from app.config.settings import get_settings


def setup_logging() -> None:
    """Configure application logging based on settings."""
    settings = get_settings()
    
    # Determine log level
    log_level = logging.DEBUG if settings.debug else logging.INFO
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set specific logger levels
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    # Application loggers
    logging.getLogger("app").setLevel(log_level)


class RequestIDFilter(logging.Filter):
    """Logging filter to add request ID to log records."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Add request_id to log record if available."""
        if not hasattr(record, 'request_id'):
            record.request_id = getattr(record, 'request_id', '-')
        return True

