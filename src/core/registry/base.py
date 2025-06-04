"""
Base registry implementation for the Digital Twin Platform.

This module provides the abstract base implementation for all registries,
including common functionality for storage, caching, and basic operations.
"""

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypeVar, Generic, Type, Callable
from uuid import UUID
import logging

from src.core.interfaces.base import IRegistry, IEntity, IStorageAdapter, BaseMetadata
from src.utils.exceptions import (
    RegistryError,
    EntityNotFoundError,
    EntityAlreadyExistsError,
    RegistryConnectionError,
    StorageError
)
from src.utils.config import get_config

# Type variable for entities
T = TypeVar('T', bound=IEntity)

logger = logging.getLogger(__name__)


class RegistryMetrics:
    """Metriche per il registry"""
    
    def __init__(self):
        self.total_operations = 0
        self.successful_operations = 0
        self.failed_operations = 0
        self.average_response_time = 0.0
        self.cache_hits = 0
        self.cache_misses = 0
        self.last_health_check = None
        self.entity_count = 0

    def record_operation(self, success: bool, response_time: float) -> None:
        """Registra un'operazione"""
        self.total_operations += 1
        if success:
            self.successful_operations += 1
        else:
            self.failed_operations += 1
        
        # Aggiorna tempo di risposta medio
        self.average_response_time = (
            (self.average_response_time * (self.total_operations - 1) + response_time) 
            / self.total_operations
        )

    def record_cache_hit(self) -> None:
        """Registra un cache hit"""
        self.cache_hits += 1

    def record_cache_miss(self) -> None:
        """Registra un cache miss"""
        self.cache_misses += 1

    def get_cache_hit_ratio(self) -> float:
        """Calcola il rapporto di cache hit"""
        total_cache_requests = self.cache_hits + self.cache_misses
        if total_cache_requests == 0:
            return 0.0
        return self.cache_hits / total_cache_requests

    def get_success_ratio(self) -> float:
        """Calcola il rapporto di successo"""
        if self.total_operations == 0:
            return 0.0
        return self.successful_operations / self.total_operations

    def to_dict(self) -> Dict[str, Any]:
        """Converte le metriche in dizionario"""
        return {
            'total_operations': self.total_operations,
            'successful_operations': self.successful_operations,
            'failed_operations': self.failed_operations,
            'average_response_time': self.average_response_time,
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'cache_hit_ratio': self.get_cache_hit_ratio(),
            'success_ratio': self.get_success_ratio(),
            'last_health_check': self.last_health_check.isoformat() if self.last_health_check else None,
            'entity_count': self.entity_count
        }

class BaseCache:
    """Simple in-memory cache for registry operations."""
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._access_times: Dict[str, datetime] = {}
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        if key not in self._cache:
            return None
        
        # Check TTL
        access_time = self._access_times.get(key)
        if access_time and (datetime.now(timezone.utc) - access_time).total_seconds() > self.ttl_seconds:
            self.remove(key)
            return None
        
        # Update access time
        self._access_times[key] = datetime.now(timezone.utc)
        return self._cache[key]['value']
    
    def set(self, key: str, value: Any) -> None:
        """Set value in cache."""
        # Remove oldest entries if cache is full
        while len(self._cache) >= self.max_size:
            oldest_key = min(self._access_times.keys(), key=self._access_times.get)
            self.remove(oldest_key)
        
        self._cache[key] = {
            'value': value,
            'created_at': datetime.now(timezone.utc)
        }
        self._access_times[key] = datetime.now(timezone.utc)
    
    def remove(self, key: str) -> None:
        """Remove value from cache."""
        self._cache.pop(key, None)
        self._access_times.pop(key, None)
    
    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        self._access_times.clear()
    
    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)


class AbstractRegistry(IRegistry[T], ABC):
    """
    Abstract base implementation for all registries.
    
    Provides common functionality including caching, metrics collection,
    validation, and error handling that all specific registries can inherit.
    """
    def __init__(self, entity_type: Type[T], storage_adapter: IStorageAdapter[T], 
                 cache_enabled: bool = True, cache_size: int = 1000, cache_ttl: int = 300):
        self.entity_type = entity_type
        self.storage_adapter = storage_adapter
        self.cache_enabled = cache_enabled
        self.metrics = RegistryMetrics()
        
        # Inizializza cache se abilitata
        if cache_enabled:
            self.cache = BaseCache(max_size=cache_size, ttl_seconds=cache_ttl)
        else:
            self.cache = None
            
        self.config = get_config()
        self.logger = logging.getLogger(f'{__name__}.{self.__class__.__name__}')
        self._connected = False
        
        # Aggiungi connection lock se disponibile
        try:
            import asyncio
            self._connection_lock = asyncio.Lock()
        except:
            self._connection_lock = None
    @property
    def registry_name(self) -> str:
        return f'{self.entity_type.__name__}Registry'

    @property
    def is_connected(self) -> bool:
        return getattr(self, '_connected', False)

    async def connect(self) -> None:
        """Connetti al storage adapter"""
        if hasattr(self, '_connection_lock'):
            async with self._connection_lock:
                if not getattr(self, '_connected', False):
                    try:
                        await self.storage_adapter.connect()
                        self._connected = True
                        self.logger.info(f'{self.registry_name} connected to storage')
                    except Exception as e:
                        self.logger.error(f'Failed to connect {self.registry_name}: {e}')
                        from src.utils.exceptions import RegistryConnectionError
                        raise RegistryConnectionError(f'Connection failed: {e}')
        else:
            # Fallback senza lock
            try:
                await self.storage_adapter.connect()
                self._connected = True
                self.logger.info(f'{self.registry_name} connected to storage')
            except Exception as e:
                self.logger.error(f'Failed to connect {self.registry_name}: {e}')
                from src.utils.exceptions import RegistryConnectionError
                raise RegistryConnectionError(f'Connection failed: {e}')

    async def disconnect(self) -> None:
        """Disconnetti dal storage adapter"""
        if hasattr(self, '_connection_lock'):
            async with self._connection_lock:
                if getattr(self, '_connected', False):
                    try:
                        await self.storage_adapter.disconnect()
                        self._connected = False
                        self.logger.info(f'{self.registry_name} disconnected from storage')
                    except Exception as e:
                        self.logger.error(f'Failed to disconnect {self.registry_name}: {e}')
        else:
            # Fallback senza lock
            try:
                await self.storage_adapter.disconnect()
                self._connected = False
                self.logger.info(f'{self.registry_name} disconnected from storage')
            except Exception as e:
                self.logger.error(f'Failed to disconnect {self.registry_name}: {e}')
    
    async def register(self, entity: T) -> None:
        """Registra una nuova entità"""
        start_time = datetime.now(timezone.utc)
        try:
            await self._ensure_connected()
            
            # Validazione se l'entità ha il metodo validate
            if hasattr(entity, 'validate') and not entity.validate():
                raise RegistryError(f'Entity validation failed for {entity.id}')
            
            # Controlla se esiste già
            if await self.exists(entity.id):
                from src.utils.exceptions import EntityAlreadyExistsError
                raise EntityAlreadyExistsError(entity_type=self.entity_type.__name__, entity_id=str(entity.id))
            
            await self._pre_register_hook(entity)
            await self.storage_adapter.save(entity)
            
            # Aggiorna cache se abilitata
            if self.cache_enabled and self.cache:
                self.cache.set(str(entity.id), entity)
                self.metrics.record_cache_miss()
            
            self.metrics.entity_count += 1
            await self._post_register_hook(entity)
            
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(True, response_time)
            self.logger.info(f'Registered entity {entity.id} in {self.registry_name}')
            
        except Exception as e:
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(False, response_time)
            self.logger.error(f'Failed to register entity {entity.id}: {e}')
            raise
    
    async def unregister(self, entity_id: UUID) -> None:
        """Rimuove un'entità dal registry"""
        start_time = datetime.now(timezone.utc)
        try:
            await self._ensure_connected()
            
            if not await self.exists(entity_id):
                from src.utils.exceptions import EntityNotFoundError
                raise EntityNotFoundError(entity_type=self.entity_type.__name__, entity_id=str(entity_id))
            
            entity = await self.get(entity_id)
            await self._pre_unregister_hook(entity)
            await self.storage_adapter.delete(entity_id)
            
            if self.cache_enabled and self.cache:
                self.cache.remove(str(entity_id))
            
            self.metrics.entity_count -= 1
            await self._post_unregister_hook(entity)
            
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(True, response_time)
            self.logger.info(f'Unregistered entity {entity_id} from {self.registry_name}')
            
        except Exception as e:
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(False, response_time)
            self.logger.error(f'Failed to unregister entity {entity_id}: {e}')
            raise
    
    async def get(self, entity_id: UUID) -> T:
        """Recupera un'entità per ID"""
        start_time = datetime.now(timezone.utc)
        try:
            # Prova dalla cache prima
            if self.cache_enabled and self.cache:
                cached_entity = self.cache.get(str(entity_id))
                if cached_entity:
                    self.metrics.record_cache_hit()
                    response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
                    self.metrics.record_operation(True, response_time)
                    return cached_entity
                else:
                    self.metrics.record_cache_miss()
            
            await self._ensure_connected()
            entity = await self.storage_adapter.load(entity_id)
            
            if self.cache_enabled and self.cache:
                self.cache.set(str(entity_id), entity)
            
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(True, response_time)
            return entity
            
        except Exception as e:
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(False, response_time)
            from src.utils.exceptions import StorageError, EntityNotFoundError
            if isinstance(e, StorageError):
                raise EntityNotFoundError(entity_type=self.entity_type.__name__, entity_id=str(entity_id))
            raise
    
    async def list(self, filters: Optional[Dict[str, Any]] = None, 
                   limit: Optional[int] = None, offset: Optional[int] = None) -> List[T]:
        """Lista le entità con filtri opzionali"""
        start_time = datetime.now(timezone.utc)
        try:
            await self._ensure_connected()
            entities = await self.storage_adapter.query(filters or {}, limit=limit, offset=offset)
            
            # Aggiorna cache per le entità recuperate
            if self.cache_enabled and self.cache:
                for entity in entities:
                    self.cache.set(str(entity.id), entity)
            
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(True, response_time)
            return entities
            
        except Exception as e:
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(False, response_time)
            self.logger.error(f'Failed to list entities: {e}')
            raise
    
    async def exists(self, entity_id: UUID) -> bool:
        """Controlla se un'entità esiste"""
        try:
            await self.get(entity_id)
            return True
        except:
            return False
    
    async def update(self, entity: T) -> None:
        """Aggiorna un'entità"""
        start_time = datetime.now(timezone.utc)
        try:
            await self._ensure_connected()
            
            if hasattr(entity, 'validate') and not entity.validate():
                raise RegistryError(f'Entity validation failed for {entity.id}')
            
            if not await self.exists(entity.id):
                from src.utils.exceptions import EntityNotFoundError
                raise EntityNotFoundError(entity_type=self.entity_type.__name__, entity_id=str(entity.id))
            
            await self._pre_update_hook(entity)
            await self.storage_adapter.save(entity)
            
            if self.cache_enabled and self.cache:
                self.cache.set(str(entity.id), entity)
            
            await self._post_update_hook(entity)
            
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(True, response_time)
            self.logger.info(f'Updated entity {entity.id} in {self.registry_name}')
            
        except Exception as e:
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(False, response_time)
            self.logger.error(f'Failed to update entity {entity.id}: {e}')
            raise
    
    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """Conta le entità con filtri opzionali"""
        try:
            entities = await self.list(filters=filters)
            return len(entities)
        except Exception as e:
            self.logger.error(f'Failed to count entities: {e}')
            raise
    
    async def health_check(self) -> bool:
        """Controlla la salute del registry"""
        try:
            storage_healthy = await self.storage_adapter.health_check()
            connection_healthy = self._connected
            self.metrics.last_health_check = datetime.now(timezone.utc)
            overall_health = storage_healthy and connection_healthy
            self.logger.debug(f'{self.registry_name} health check: storage={storage_healthy}, connection={connection_healthy}')
            return overall_health
        except Exception as e:
            self.logger.error(f'Health check failed for {self.registry_name}: {e}')
            return False
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get registry metrics."""
        metrics_dict = self.metrics.to_dict()
        metrics_dict.update({
            "registry_name": self.registry_name,
            "entity_type": self.entity_type.__name__,
            "cache_enabled": self.cache_enabled,
            "cache_size": self.cache.size() if self.cache else 0,
            "connected": self._connected
        })
        return metrics_dict
    
    async def clear_cache(self) -> None:
        """Clear the registry cache."""
        if self.cache_enabled and self.cache:
            self.cache.clear()
            self.logger.info(f"Cleared cache for {self.registry_name}")
    
    # Hook methods for subclasses to override
    async def _pre_register_hook(self, entity: T) -> None:
        """Hook chiamato prima della registrazione di un'entità"""
        pass

    async def _post_register_hook(self, entity: T) -> None:
        """Hook chiamato dopo la registrazione di un'entità"""
        pass

    async def _pre_unregister_hook(self, entity: T) -> None:
        """Hook chiamato prima della rimozione di un'entità"""
        pass

    async def _post_unregister_hook(self, entity: T) -> None:
        """Hook chiamato dopo la rimozione di un'entità"""
        pass

    async def _pre_update_hook(self, entity: T) -> None:
        """Hook chiamato prima dell'aggiornamento di un'entità"""
        pass

    async def _post_update_hook(self, entity: T) -> None:
        """Hook chiamato dopo l'aggiornamento di un'entità"""
        pass
    
    # Private helper methods
    async def _ensure_connected(self) -> None:
        """Ensure registry is connected to storage."""
        if not getattr(self, '_connected', False):
            await self.connect()
    
    def __repr__(self) -> str:
        """String representation of the registry."""
        return (
            f"{self.__class__.__name__}("
            f"entity_type={self.entity_type.__name__}, "
            f"connected={self._connected}, "
            f"cache_enabled={self.cache_enabled})"
        )


class RegistryFactory:
    """Factory for creating registry instances."""
    
    @staticmethod
    def create_registry(
        entity_type: Type[T],
        storage_adapter: IStorageAdapter[T],
        registry_class: Optional[Type[AbstractRegistry]] = None,
        **kwargs
    ) -> AbstractRegistry[T]:
        """
        Create a registry instance.
        
        Args:
            entity_type: Type of entities this registry will manage
            storage_adapter: Storage adapter for persistence
            registry_class: Specific registry class to use
            **kwargs: Additional configuration parameters
            
        Returns:
            Created registry instance
        """
        if registry_class is None:
            registry_class = AbstractRegistry
        
        return registry_class(
            entity_type=entity_type,
            storage_adapter=storage_adapter,
            **kwargs
        )