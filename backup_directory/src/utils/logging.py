import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional
from .config import get_config

def setup_logging(log_level: Optional[str]=None, log_file: Optional[str]=None) -> None:
    config = get_config()
    level = log_level or config.get_nested('logging.level', 'INFO')
    format_str = config.get_nested('logging.format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_path = log_file or config.get_nested('logging.file_path', 'logs/platform.log')
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    if file_path:
        log_dir = Path(file_path).parent
        log_dir.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    formatter = logging.Formatter(format_str)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    if file_path:
        try:
            file_handler = logging.handlers.RotatingFileHandler(file_path, maxBytes=10 * 1024 * 1024, backupCount=5)
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            print(f'Warning: Could not setup file logging: {e}')
    logging.getLogger('uvicorn').setLevel(logging.INFO)
    logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
    logging.getLogger('fastapi').setLevel(logging.INFO)
    logging.getLogger('digital_twin_platform').setLevel(numeric_level)
    logging.getLogger('src.layers').setLevel(numeric_level)
    logging.getLogger('src.core').setLevel(numeric_level)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

class LoggerMixin:

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(f'{self.__class__.__module__}.{self.__class__.__name__}')