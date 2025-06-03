import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID
from src.utils.exceptions import ConfigurationError, AuthenticationError
from src.utils.config import get_config
logger = logging.getLogger(__name__)

class ApplicationLayer:

    def __init__(self):
        self.config = get_config()
        self._initialized = False
        self._running = False
        self.api_gateway = None
        self.auth_manager = None
        logger.info('Application Layer initialized')

    async def initialize(self) -> None:
        if self._initialized:
            logger.warning('Application Layer already initialized')
            return
        try:
            logger.info('Initializing Application Layer...')
            self._initialized = True
            logger.info('Application Layer initialization completed')
        except Exception as e:
            logger.error(f'Failed to initialize Application Layer: {e}')
            raise ConfigurationError(f'Application Layer initialization failed: {e}')

    async def start(self) -> None:
        if not self._initialized:
            await self.initialize()
        if self._running:
            logger.warning('Application Layer already running')
            return
        try:
            logger.info('Starting Application Layer...')
            self._running = True
            logger.info('Application Layer started successfully')
        except Exception as e:
            logger.error(f'Failed to start Application Layer: {e}')
            raise ConfigurationError(f'Application Layer start failed: {e}')

    async def stop(self) -> None:
        if not self._running:
            return
        try:
            logger.info('Stopping Application Layer...')
            self._running = False
            logger.info('Application Layer stopped successfully')
        except Exception as e:
            logger.error(f'Error stopping Application Layer: {e}')

    def is_ready(self) -> bool:
        return self._initialized and self._running

    def get_status(self) -> Dict[str, Any]:
        return {'layer': 'application', 'initialized': self._initialized, 'running': self._running, 'timestamp': datetime.now(timezone.utc).isoformat()}
_application_layer: Optional[ApplicationLayer] = None

def get_application_layer() -> ApplicationLayer:
    global _application_layer
    if _application_layer is None:
        _application_layer = ApplicationLayer()
    return _application_layer

async def initialize_application_layer() -> ApplicationLayer:
    global _application_layer
    _application_layer = ApplicationLayer()
    await _application_layer.initialize()
    return _application_layer

async def start_application_services():
    app_layer = get_application_layer()
    await app_layer.start()

async def stop_application_services():
    app_layer = get_application_layer()
    await app_layer.stop()

def is_application_ready() -> bool:
    app_layer = get_application_layer()
    return app_layer.is_ready()