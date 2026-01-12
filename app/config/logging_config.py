"""Logging configuration for the application."""
import logging
import sys

from app.config.settings import get_settings


def setup_logging() -> None:
    """Configure application logging based on settings."""
    settings = get_settings()
    
    # Determine log level
    log_level = logging.DEBUG if settings.debug else logging.INFO
    
    # Create formatter with request_id handling
    class RequestIDFormatter(logging.Formatter):
        def format(self, record):
            if not hasattr(record, 'request_id'):
                record.request_id = '-'
            return super().format(record)
    
    formatter = RequestIDFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        handlers=[handler]
    )
    
    # Set specific logger levels
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    # Application loggers
    logging.getLogger("app").setLevel(log_level)