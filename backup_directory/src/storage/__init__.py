import logging
from typing import Type, TypeVar, Optional, Dict, Any
from uuid import UUID
from src.core.interfaces.base import IStorageAdapter, IEntity
from src.utils.config import get_config
from src.utils.exceptions import ConfigurationError
T = TypeVar('T', bound=IEntity)
logger = logging.getLogger(__name__)

class StorageFactory:

    @staticmethod
    def create_adapter(entity_type: Type[T], twin_id: Optional[UUID]=None) -> IStorageAdapter[T]:
        config = get_config()
        storage_type = config.get('storage.primary_type', 'memory')
        try:
            if storage_type == 'mongodb':
                from .adapters.mongodb_adapter import MongoStorageAdapterFactory
                return MongoStorageAdapterFactory.create_adapter(entity_type, twin_id)
            elif storage_type == 'memory':
                from tests.mocks.storage_adapter import InMemoryStorageAdapter
                return InMemoryStorageAdapter(entity_type)
            else:
                logger.warning(f"Unknown storage type '{storage_type}', falling back to memory")
                from tests.mocks.storage_adapter import InMemoryStorageAdapter
                return InMemoryStorageAdapter(entity_type)
        except Exception as e:
            logger.error(f'Failed to create {storage_type} adapter: {e}')
            logger.warning('Falling back to in-memory storage')
            try:
                from tests.mocks.storage_adapter import InMemoryStorageAdapter
                return InMemoryStorageAdapter(entity_type)
            except Exception as fallback_error:
                logger.error(f'Fallback to memory storage failed: {fallback_error}')
                raise ConfigurationError(f'Unable to create storage adapter: {fallback_error}')

    @staticmethod
    def create_global_adapter(entity_type: Type[T]) -> IStorageAdapter[T]:
        return StorageFactory.create_adapter(entity_type, twin_id=None)

    @staticmethod
    def create_twin_adapter(entity_type: Type[T], twin_id: UUID) -> IStorageAdapter[T]:
        return StorageFactory.create_adapter(entity_type, twin_id=twin_id)

def get_storage_adapter(entity_type: Type[T], twin_id: Optional[UUID]=None) -> IStorageAdapter[T]:
    return StorageFactory.create_adapter(entity_type, twin_id)

def get_global_storage_adapter(entity_type: Type[T]) -> IStorageAdapter[T]:
    return StorageFactory.create_global_adapter(entity_type)

def get_twin_storage_adapter(entity_type: Type[T], twin_id: UUID) -> IStorageAdapter[T]:
    return StorageFactory.create_twin_adapter(entity_type, twin_id)

async def initialize_storage() -> Dict[str, Any]:
    config = get_config()
    status = {'primary_storage': config.get('storage.primary_type', 'memory'), 'cache_storage': config.get('storage.cache_type', 'none'), 'separate_dbs_per_twin': config.get('storage.separate_dbs_per_twin', False), 'connections': {}}
    try:
        if status['primary_storage'] == 'mongodb':
            from .adapters.mongodb_adapter import MongoStorageAdapter
            from src.core.interfaces.digital_twin import IDigitalTwin
            test_adapter = MongoStorageAdapter(IDigitalTwin)
            await test_adapter.connect()
            health = await test_adapter.health_check()
            await test_adapter.disconnect()
            status['connections']['mongodb'] = {'connected': health, 'database_strategy': 'separate_per_twin' if status['separate_dbs_per_twin'] else 'global'}
        else:
            status['connections']['memory'] = {'connected': True}
    except Exception as e:
        logger.error(f'Failed to test primary storage: {e}')
        status['connections']['primary_error'] = str(e)
    try:
        if status['cache_storage'] == 'redis':
            from .adapters.redis_cache import get_redis_cache
            cache = await get_redis_cache()
            health = await cache.health_check()
            status['connections']['redis'] = {'connected': health, 'usage': 'caching_and_sessions'}
    except Exception as e:
        logger.error(f'Failed to test cache storage: {e}')
        status['connections']['cache_error'] = str(e)
    logger.info(f"Storage initialized: {status['primary_storage']} + {status['cache_storage']}")
    return status
__all__ = ['StorageFactory', 'get_storage_adapter', 'get_global_storage_adapter', 'get_twin_storage_adapter', 'initialize_storage']