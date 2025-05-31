"""
Mock storage adapter for testing the Digital Twin Platform.

Provides in-memory storage implementation for testing registries
and other components that depend on storage adapters.
"""

import asyncio
from typing import Any, Dict, List, Optional, TypeVar
from uuid import UUID
from datetime import datetime, timezone

from src.core.interfaces.base import IStorageAdapter, IEntity
from src.utils.exceptions import StorageError, DataPersistenceError


T = TypeVar('T', bound=IEntity)


class MockStorageAdapter(IStorageAdapter[T]):
    """
    Mock storage adapter for testing.
    
    Provides in-memory storage with full IStorageAdapter interface
    implementation for testing purposes.
    """
    
    def __init__(self, storage_type: str = "mock"):
        self._storage_type = storage_type
        self._entities: Dict[UUID, T] = {}
        self._connected = False
        self._connection_delay = 0.0  # Simulate connection delay
        self._failure_rate = 0.0  # Simulate random failures (0.0 to 1.0)
        self._health_status = True
        self._operation_count = 0
    
    @property
    def storage_type(self) -> str:
        """Get the type of storage this adapter handles."""
        return self._storage_type
    
    def set_connection_delay(self, delay: float) -> None:
        """Set connection delay for testing async behavior."""
        self._connection_delay = delay
    
    def set_failure_rate(self, rate: float) -> None:
        """Set failure rate for testing error handling."""
        self._failure_rate = max(0.0, min(1.0, rate))
    
    def set_health_status(self, healthy: bool) -> None:
        """Set health status for testing health checks."""
        self._health_status = healthy
    
    def get_operation_count(self) -> int:
        """Get the number of operations performed."""
        return self._operation_count
    
    def get_entity_count(self) -> int:
        """Get the number of stored entities."""
        return len(self._entities)
    
    def clear_storage(self) -> None:
        """Clear all stored entities."""
        self._entities.clear()
    
    async def connect(self) -> None:
        """Connect to the storage backend."""
        if self._connection_delay > 0:
            await asyncio.sleep(self._connection_delay)
        
        self._simulate_failure("Connection failed")
        self._connected = True
    
    async def disconnect(self) -> None:
        """Disconnect from the storage backend."""
        if self._connection_delay > 0:
            await asyncio.sleep(self._connection_delay)
        
        self._connected = False
    
    async def save(self, entity: T) -> None:
        """Save an entity to storage."""
        self._operation_count += 1
        self._ensure_connected()
        self._simulate_failure("Save operation failed")
        
        if not entity.validate():
            raise DataPersistenceError(f"Entity validation failed for {entity.id}")
        
        # Simulate some async operation
        await asyncio.sleep(0.001)
        
        self._entities[entity.id] = entity
    
    async def load(self, entity_id: UUID) -> T:
        """Load an entity from storage by ID."""
        self._operation_count += 1
        self._ensure_connected()
        self._simulate_failure("Load operation failed")
        
        # Simulate some async operation
        await asyncio.sleep(0.001)
        
        if entity_id not in self._entities:
            raise StorageError(f"Entity {entity_id} not found")
        
        return self._entities[entity_id]
    
    async def delete(self, entity_id: UUID) -> None:
        """Delete an entity from storage."""
        self._operation_count += 1
        self._ensure_connected()
        self._simulate_failure("Delete operation failed")
        
        # Simulate some async operation
        await asyncio.sleep(0.001)
        
        if entity_id not in self._entities:
            raise StorageError(f"Entity {entity_id} not found")
        
        del self._entities[entity_id]
    
    async def query(
        self,
        filters: Dict[str, Any],
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[T]:
        """Query entities with filters and pagination."""
        self._operation_count += 1
        self._ensure_connected()
        self._simulate_failure("Query operation failed")
        
        # Simulate some async operation
        await asyncio.sleep(0.001)
        
        # Simple filtering implementation for testing
        results = list(self._entities.values())
        
        # Apply filters (simplified implementation)
        for key, value in filters.items():
            filtered_results = []
            for entity in results:
                if hasattr(entity, key):
                    entity_value = getattr(entity, key)
                    # Handle enum values
                    if hasattr(entity_value, 'value'):
                        entity_value = entity_value.value
                    if entity_value == value:
                        filtered_results.append(entity)
            results = filtered_results
        
        # Apply pagination
        if offset:
            results = results[offset:]
        if limit:
            results = results[:limit]
        
        return results
    
    async def health_check(self) -> bool:
        """Check the health of the storage backend."""
        self._operation_count += 1
        
        # Simulate some async operation
        await asyncio.sleep(0.001)
        
        return self._health_status and self._connected
    
    def _ensure_connected(self) -> None:
        """Ensure storage is connected."""
        if not self._connected:
            raise StorageError("Storage adapter not connected")
    
    def _simulate_failure(self, error_message: str) -> None:
        """Simulate random failures based on failure rate."""
        import random
        if random.random() < self._failure_rate:
            raise StorageError(error_message)


class MockEntity(IEntity):
    """
    Mock entity implementation for testing.
    
    Provides a simple entity implementation that can be used
    with the mock storage adapter for testing.
    """
    
    def __init__(
        self,
        entity_id: UUID,
        name: str,
        entity_type: str = "mock",
        metadata: Optional[Dict[str, Any]] = None
    ):
        from src.core.interfaces.base import BaseMetadata, EntityStatus
        
        self._id = entity_id
        self._name = name
        self._entity_type = entity_type
        self._status = EntityStatus.CREATED
        self._metadata = BaseMetadata(
            entity_id=entity_id,
            timestamp=datetime.now(timezone.utc),
            version="1.0.0",
            created_by=entity_id,  # Self-created for testing
            custom=metadata or {}
        )
        self._validation_result = True
    
    @property
    def id(self) -> UUID:
        """Get the unique identifier of the entity."""
        return self._id
    
    @property
    def metadata(self):
        """Get the metadata associated with the entity."""
        return self._metadata
    
    @property
    def status(self):
        """Get the current status of the entity."""
        return self._status
    
    @property
    def name(self) -> str:
        """Get the name of the entity."""
        return self._name
    
    @property
    def entity_type(self) -> str:
        """Get the type of the entity."""
        return self._entity_type
    
    def set_validation_result(self, result: bool) -> None:
        """Set validation result for testing."""
        self._validation_result = result
    
    def set_status(self, status) -> None:
        """Set entity status."""
        self._status = status
    
    async def initialize(self) -> None:
        """Initialize the entity and prepare it for operation."""
        from src.core.interfaces.base import EntityStatus
        self._status = EntityStatus.INITIALIZING
        await asyncio.sleep(0.001)  # Simulate async initialization
        self._status = EntityStatus.ACTIVE
    
    async def start(self) -> None:
        """Start the entity operations."""
        from src.core.interfaces.base import EntityStatus
        self._status = EntityStatus.ACTIVE
        await asyncio.sleep(0.001)  # Simulate async start
    
    async def stop(self) -> None:
        """Stop the entity operations gracefully."""
        from src.core.interfaces.base import EntityStatus
        self._status = EntityStatus.INACTIVE
        await asyncio.sleep(0.001)  # Simulate async stop
    
    async def terminate(self) -> None:
        """Terminate the entity and cleanup resources."""
        from src.core.interfaces.base import EntityStatus
        self._status = EntityStatus.TERMINATED
        await asyncio.sleep(0.001)  # Simulate async termination
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize the entity to a dictionary representation."""
        return {
            "id": str(self._id),
            "name": self._name,
            "entity_type": self._entity_type,
            "status": self._status.value,
            "metadata": self._metadata.to_dict()
        }
    
    def validate(self) -> bool:
        """Validate the entity configuration and state."""
        return self._validation_result
    
    def __repr__(self) -> str:
        """String representation of the entity."""
        return f"MockEntity(id={self._id}, name={self._name}, type={self._entity_type})"


class FailingMockStorageAdapter(MockStorageAdapter):
    """
    Mock storage adapter that always fails.
    
    Useful for testing error handling scenarios.
    """
    
    def __init__(self):
        super().__init__("failing_mock")
        self.set_failure_rate(1.0)  # Always fail
        self.set_health_status(False)


class SlowMockStorageAdapter(MockStorageAdapter):
    """
    Mock storage adapter with artificial delays.
    
    Useful for testing timeout and performance scenarios.
    """
    
    def __init__(self, delay: float = 1.0):
        super().__init__("slow_mock")
        self.set_connection_delay(delay)
    
    async def save(self, entity: T) -> None:
        """Save with artificial delay."""
        await asyncio.sleep(self._connection_delay)
        await super().save(entity)
    
    async def load(self, entity_id: UUID) -> T:
        """Load with artificial delay."""
        await asyncio.sleep(self._connection_delay)
        return await super().load(entity_id)
    
    async def delete(self, entity_id: UUID) -> None:
        """Delete with artificial delay."""
        await asyncio.sleep(self._connection_delay)
        await super().delete(entity_id)
    
    async def query(
        self,
        filters: Dict[str, Any],
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[T]:
        """Query with artificial delay."""
        await asyncio.sleep(self._connection_delay)
        return await super().query(filters, limit, offset)


class InMemoryStorageAdapter(MockStorageAdapter):
    """
    In-memory storage adapter for testing.
    
    Provides fast, reliable in-memory storage without
    artificial delays or failures.
    """
    
    def __init__(self):
        super().__init__("in_memory")
        self.set_health_status(True)
        self.set_failure_rate(0.0)
        self.set_connection_delay(0.0)