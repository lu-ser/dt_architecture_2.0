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
    """Metrics collection for registry operations."""
    
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
        """Record a registry operation."""
        self.total_operations += 1
        if success:
            self.successful_operations += 1
        else:
            self.failed_operations += 1
        
        # Update average response time
        self.average_response_time = (
            (self.average_response_time * (self.total_operations - 1) + response_time) 
            / self.total_operations
        )
    
    def record_cache_hit(self) -> None:
        """Record a cache hit."""
        self.cache_hits += 1
    
    def record_cache_miss(self) -> None:
        """Record a cache miss."""
        self.cache_misses += 1
    
    def get_cache_hit_ratio(self) -> float:
        """Get cache hit ratio."""
        total_cache_requests = self.cache_hits + self.cache_misses
        if total_cache_requests == 0:
            return 0.0
        return self.cache_hits / total_cache_requests
    
    def get_success_ratio(self) -> float:
        """Get operation success ratio."""
        if self.total_operations == 0:
            return 0.0
        return self.successful_operations / self.total_operations
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "total_operations": self.total_operations,
            "successful_operations": self.successful_operations,
            "failed_operations": self.failed_operations,
            "average_response_time": self.average_response_time,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_ratio": self.get_cache_hit_ratio(),
            "success_ratio": self.get_success_ratio(),
            "last_health_check": self.last_health_check.isoformat() if self.last_health_check else None,
            "entity_count": self.entity_count
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
    
    def __init__(
        self,
        entity_type: Type[T],
        storage_adapter: IStorageAdapter[T],
        cache_enabled: bool = True,
        cache_size: int = 1000,
        cache_ttl: int = 300
    ):
        self.entity_type = entity_type
        self.storage_adapter = storage_adapter
        self.cache_enabled = cache_enabled
        self.metrics = RegistryMetrics()
        
        # Initialize cache if enabled
        if cache_enabled:
            self.cache = BaseCache(max_size=cache_size, ttl_seconds=cache_ttl)
        else:
            self.cache = None
        
        # Registry configuration
        self.config = get_config()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Connection state
        self._connected = False
        self._connection_lock = asyncio.Lock()
    
    @property
    def registry_name(self) -> str:
        """Get the name of this registry."""
        return f"{self.entity_type.__name__}Registry"
    
    @property
    def is_connected(self) -> bool:
        """Check if registry is connected to storage."""
        return self._connected
    
    async def connect(self) -> None:
        """Connect to storage backend."""
        async with self._connection_lock:
            if not self._connected:
                try:
                    await self.storage_adapter.connect()
                    self._connected = True
                    self.logger.info(f"{self.registry_name} connected to storage")
                except Exception as e:
                    self.logger.error(f"Failed to connect {self.registry_name}: {e}")
                    raise RegistryConnectionError(f"Connection failed: {e}")
    
    async def disconnect(self) -> None:
        """Disconnect from storage backend."""
        async with self._connection_lock:
            if self._connected:
                try:
                    await self.storage_adapter.disconnect()
                    self._connected = False
                    self.logger.info(f"{self.registry_name} disconnected from storage")
                except Exception as e:
                    self.logger.error(f"Failed to disconnect {self.registry_name}: {e}")
    
    async def register(self, entity: T) -> None:
        """Register a new entity in the registry."""
        start_time = datetime.now(timezone.utc)
        
        try:
            # Ensure connection
            await self._ensure_connected()
            
            # Validate entity
            if not entity.validate():
                raise RegistryError(f"Entity validation failed for {entity.id}")
            
            # Check if entity already exists
            if await self.exists(entity.id):
                raise EntityAlreadyExistsError(
                    entity_type=self.entity_type.__name__,
                    entity_id=str(entity.id)
                )
            
            # Perform pre-registration hook
            await self._pre_register_hook(entity)
            
            # Save to storage
            await self.storage_adapter.save(entity)
            
            # Update cache
            if self.cache_enabled and self.cache:
                self.cache.set(str(entity.id), entity)
                self.metrics.record_cache_miss()  # Initial registration is a cache miss
            
            # Update metrics
            self.metrics.entity_count += 1
            
            # Perform post-registration hook
            await self._post_register_hook(entity)
            
            # Record successful operation
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(True, response_time)
            
            self.logger.info(f"Registered entity {entity.id} in {self.registry_name}")
            
        except Exception as e:
            # Record failed operation
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(False, response_time)
            
            self.logger.error(f"Failed to register entity {entity.id}: {e}")
            raise
    
    async def unregister(self, entity_id: UUID) -> None:
        """Unregister an entity from the registry."""
        start_time = datetime.now(timezone.utc)
        
        try:
            # Ensure connection
            await self._ensure_connected()
            
            # Check if entity exists
            if not await self.exists(entity_id):
                raise EntityNotFoundError(
                    entity_type=self.entity_type.__name__,
                    entity_id=str(entity_id)
                )
            
            # Get entity for hooks
            entity = await self.get(entity_id)
            
            # Perform pre-unregistration hook
            await self._pre_unregister_hook(entity)
            
            # Remove from storage
            await self.storage_adapter.delete(entity_id)
            
            # Remove from cache
            if self.cache_enabled and self.cache:
                self.cache.remove(str(entity_id))
            
            # Update metrics
            self.metrics.entity_count -= 1
            
            # Perform post-unregistration hook
            await self._post_unregister_hook(entity)
            
            # Record successful operation
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(True, response_time)
            
            self.logger.info(f"Unregistered entity {entity_id} from {self.registry_name}")
            
        except Exception as e:
            # Record failed operation
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(False, response_time)
            
            self.logger.error(f"Failed to unregister entity {entity_id}: {e}")
            raise
    
    async def get(self, entity_id: UUID) -> T:
        """Retrieve an entity by its ID."""
        start_time = datetime.now(timezone.utc)
        
        try:
            # Check cache first
            if self.cache_enabled and self.cache:
                cached_entity = self.cache.get(str(entity_id))
                if cached_entity:
                    self.metrics.record_cache_hit()
                    response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
                    self.metrics.record_operation(True, response_time)
                    return cached_entity
                else:
                    self.metrics.record_cache_miss()
            
            # Ensure connection
            await self._ensure_connected()
            
            # Load from storage
            entity = await self.storage_adapter.load(entity_id)
            
            # Update cache
            if self.cache_enabled and self.cache:
                self.cache.set(str(entity_id), entity)
            
            # Record successful operation
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(True, response_time)
            
            return entity
            
        except Exception as e:
            # Record failed operation
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(False, response_time)
            
            if isinstance(e, StorageError):
                raise EntityNotFoundError(
                    entity_type=self.entity_type.__name__,
                    entity_id=str(entity_id)
                )
            raise
    
    async def list(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[T]:
        """List entities with optional filtering and pagination."""
        start_time = datetime.now(timezone.utc)
        
        try:
            # Ensure connection
            await self._ensure_connected()
            
            # Query storage
            entities = await self.storage_adapter.query(
                filters or {},
                limit=limit,
                offset=offset
            )
            
            # Update cache for retrieved entities
            if self.cache_enabled and self.cache:
                for entity in entities:
                    self.cache.set(str(entity.id), entity)
            
            # Record successful operation
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(True, response_time)
            
            return entities
            
        except Exception as e:
            # Record failed operation
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(False, response_time)
            
            self.logger.error(f"Failed to list entities: {e}")
            raise
    
    async def exists(self, entity_id: UUID) -> bool:
        """Check if an entity exists in the registry."""
        try:
            await self.get(entity_id)
            return True
        except EntityNotFoundError:
            return False
    
    async def update(self, entity: T) -> None:
        """Update an existing entity in the registry."""
        start_time = datetime.now(timezone.utc)
        
        try:
            # Ensure connection
            await self._ensure_connected()
            
            # Validate entity
            if not entity.validate():
                raise RegistryError(f"Entity validation failed for {entity.id}")
            
            # Check if entity exists
            if not await self.exists(entity.id):
                raise EntityNotFoundError(
                    entity_type=self.entity_type.__name__,
                    entity_id=str(entity.id)
                )
            
            # Perform pre-update hook
            await self._pre_update_hook(entity)
            
            # Update in storage
            await self.storage_adapter.save(entity)
            
            # Update cache
            if self.cache_enabled and self.cache:
                self.cache.set(str(entity.id), entity)
            
            # Perform post-update hook
            await self._post_update_hook(entity)
            
            # Record successful operation
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(True, response_time)
            
            self.logger.info(f"Updated entity {entity.id} in {self.registry_name}")
            
        except Exception as e:
            # Record failed operation
            response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_operation(False, response_time)
            
            self.logger.error(f"Failed to update entity {entity.id}: {e}")
            raise
    
    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """Count entities with optional filtering."""
        try:
            # For now, get all entities and count
            # In a production implementation, this would be optimized
            entities = await self.list(filters=filters)
            return len(entities)
        except Exception as e:
            self.logger.error(f"Failed to count entities: {e}")
            raise
    
    async def health_check(self) -> bool:
        """Check the health status of the registry."""
        try:
            # Check storage adapter health
            storage_healthy = await self.storage_adapter.health_check()
            
            # Check connection status
            connection_healthy = self._connected
            
            # Update metrics
            self.metrics.last_health_check = datetime.now(timezone.utc)
            
            overall_health = storage_healthy and connection_healthy
            
            self.logger.debug(
                f"{self.registry_name} health check: "
                f"storage={storage_healthy}, connection={connection_healthy}"
            )
            
            return overall_health
            
        except Exception as e:
            self.logger.error(f"Health check failed for {self.registry_name}: {e}")
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
        """Hook called before entity registration."""
        pass
    
    async def _post_register_hook(self, entity: T) -> None:
        """Hook called after entity registration."""
        pass
    
    async def _pre_unregister_hook(self, entity: T) -> None:
        """Hook called before entity unregistration."""
        pass
    
    async def _post_unregister_hook(self, entity: T) -> None:
        """Hook called after entity unregistration."""
        pass
    
    async def _pre_update_hook(self, entity: T) -> None:
        """Hook called before entity update."""
        pass
    
    async def _post_update_hook(self, entity: T) -> None:
        """Hook called after entity update."""
        pass
    
    # Private helper methods
    async def _ensure_connected(self) -> None:
        """Ensure registry is connected to storage."""
        if not self._connected:
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