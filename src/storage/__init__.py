"""Storage layer for Digital Twin Platform."""

import logging
from typing import Type, TypeVar, Optional, Dict, Any
from uuid import UUID

from src.core.interfaces.base import IStorageAdapter, IEntity
from src.utils.config import get_config
from src.utils.exceptions import ConfigurationError

# Import storage adapters
from .adapters.mongodb_adapter import MongoStorageAdapterFactory
from tests.mocks.storage_adapter import InMemoryStorageAdapter

T = TypeVar('T', bound=IEntity)
logger = logging.getLogger(__name__)

class StorageFactory:
    """Factory for creating appropriate storage adapters based on configuration."""
    
    @staticmethod
    def create_adapter(entity_type: Type[T], twin_id: Optional[UUID] = None) -> IStorageAdapter[T]:
        """
        Create storage adapter based on configuration.
        
        Args:
            entity_type: Type of entity to store
            twin_id: Optional Digital Twin ID for separate databases
            
        Returns:
            Configured storage adapter
        """
        config = get_config()
        storage_type = config.get('storage.primary_type', 'memory')
        
        try:
            if storage_type == 'mongodb':
                return MongoStorageAdapterFactory.create_adapter(entity_type, twin_id)
            elif storage_type == 'memory':
                return InMemoryStorageAdapter[T]()
            else:
                logger.warning(f"Unknown storage type '{storage_type}', falling back to memory")
                return InMemoryStorageAdapter[T]()
                
        except Exception as e:
            logger.error(f"Failed to create {storage_type} adapter: {e}")
            logger.warning("Falling back to in-memory storage")
            return InMemoryStorageAdapter[T]()
    
    @staticmethod
    def create_global_adapter(entity_type: Type[T]) -> IStorageAdapter[T]:
        """
        Create adapter for global entities (users, API keys, etc.).
        These entities are shared across all Digital Twins.
        """
        return StorageFactory.create_adapter(entity_type, twin_id=None)
    
    @staticmethod 
    def create_twin_adapter(entity_type: Type[T], twin_id: UUID) -> IStorageAdapter[T]:
        """
        Create adapter for twin-specific entities (replicas, services).
        These entities are stored in separate databases for migration support.
        """
        return StorageFactory.create_adapter(entity_type, twin_id=twin_id)


def get_storage_adapter(entity_type: Type[T], twin_id: Optional[UUID] = None) -> IStorageAdapter[T]:
    """
    Convenience function to get storage adapter.
    
    Args:
        entity_type: Type of entity
        twin_id: Optional twin ID for separate storage
        
    Returns:
        Storage adapter instance
    """
    return StorageFactory.create_adapter(entity_type, twin_id)


def get_global_storage_adapter(entity_type: Type[T]) -> IStorageAdapter[T]:
    """Get storage adapter for global entities."""
    return StorageFactory.create_global_adapter(entity_type)


def get_twin_storage_adapter(entity_type: Type[T], twin_id: UUID) -> IStorageAdapter[T]:
    """Get storage adapter for twin-specific entities."""
    return StorageFactory.create_twin_adapter(entity_type, twin_id)


async def initialize_storage() -> Dict[str, Any]:
    """
    Initialize storage subsystem and return status.
    
    Returns:
        Status dictionary with connection info
    """
    config = get_config()
    status = {
        'primary_storage': config.get('storage.primary_type', 'memory'),
        'cache_storage': config.get('storage.cache_type', 'none'),
        'separate_dbs_per_twin': config.get('storage.separate_dbs_per_twin', False),
        'connections': {}
    }
    
    # Test primary storage connection
    try:
        if status['primary_storage'] == 'mongodb':
            # Test MongoDB connection by creating a test adapter
            from .adapters.mongodb_adapter import MongoStorageAdapter
            from src.core.interfaces.digital_twin import IDigitalTwin
            
            test_adapter = MongoStorageAdapter(IDigitalTwin)
            await test_adapter.connect()
            health = await test_adapter.health_check()
            await test_adapter.disconnect()
            
            status['connections']['mongodb'] = {
                'connected': health,
                'database_strategy': 'separate_per_twin' if status['separate_dbs_per_twin'] else 'global'
            }
        else:
            status['connections']['memory'] = {'connected': True}
            
    except Exception as e:
        logger.error(f"Failed to test primary storage: {e}")
        status['connections']['primary_error'] = str(e)
    
    # Test cache storage connection
    try:
        if status['cache_storage'] == 'redis':
            from .adapters.redis_cache import get_redis_cache
            
            cache = await get_redis_cache()
            health = await cache.health_check()
            
            status['connections']['redis'] = {
                'connected': health,
                'usage': 'caching_and_sessions'
            }
            
    except Exception as e:
        logger.error(f"Failed to test cache storage: {e}")
        status['connections']['cache_error'] = str(e)
    
    logger.info(f"Storage initialized: {status['primary_storage']} + {status['cache_storage']}")
    return status


# Export main classes and functions
__all__ = [
    'StorageFactory',
    'get_storage_adapter',
    'get_global_storage_adapter', 
    'get_twin_storage_adapter',
    'initialize_storage'
]