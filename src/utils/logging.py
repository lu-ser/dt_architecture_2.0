"""
Logging configuration for the Digital Twin Platform.

LOCATION: src/utils/logging.py
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional
from .config import get_config


def setup_logging(log_level: Optional[str] = None, log_file: Optional[str] = None) -> None:
    """Setup platform-wide logging configuration."""
    config = get_config()
    
    # Get logging configuration
    level = log_level or config.get_nested("logging.level", "INFO")
    format_str = config.get_nested("logging.format", 
                                   "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_path = log_file or config.get_nested("logging.file_path", "logs/platform.log")
    
    # Convert string level to logging constant
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    # Create logs directory if it doesn't exist
    if file_path:
        log_dir = Path(file_path).parent
        log_dir.mkdir(parents=True, exist_ok=True)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create formatter
    formatter = logging.Formatter(format_str)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (if file path specified)
    if file_path:
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                file_path,
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5
            )
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            print(f"Warning: Could not setup file logging: {e}")
    
    # Set specific logger levels
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.INFO)
    
    # Platform specific loggers
    logging.getLogger("digital_twin_platform").setLevel(numeric_level)
    logging.getLogger("src.layers").setLevel(numeric_level)
    logging.getLogger("src.core").setLevel(numeric_level)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the specified name."""
    return logging.getLogger(name)


class LoggerMixin:
    """Mixin class to add logging capabilities to any class."""
    
    @property
    def logger(self) -> logging.Logger:
        """Get logger for this class."""
        return logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")