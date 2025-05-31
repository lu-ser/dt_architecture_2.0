"""
Unit tests for base registry implementation in the Digital Twin Platform.

Tests the abstract registry functionality including caching, metrics,
error handling, and storage integration.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4, UUID
from datetime import datetime, timezone

from src.core.registry.base import (
    AbstractRegistry,
    RegistryMetrics,
    BaseCache,
    RegistryFactory
)
from src.core.interfaces.base import EntityStatus
from src.utils.exceptions import (
    RegistryError,
    EntityNotFoundError,
    EntityAlreadyExistsError,
    RegistryConnectionError
)

# Import mock classes
from tests.mocks.storage_adapter import (
    MockStorageAdapter,
    MockEntity,
    InMemoryStorageAdapter,
    FailingMockStorageAdapter,
    SlowMockStorageAdapter
)


class TestRegistryMetrics:
    """Test registry metrics functionality."""
    
    def test_metrics_initialization(self):
        """Test metrics are properly initialized."""
        metrics = RegistryMetrics()
        
        assert metrics.total_operations == 0
        assert metrics.successful_operations == 0
        assert metrics.failed_operations == 0
        assert metrics.average_response_time == 0.0
        assert metrics.cache_hits == 0
        assert metrics.cache_misses == 0
        assert metrics.last_health_check is None
        assert metrics.entity_count == 0
    
    def test_record_operation_success(self):
        """Test recording successful operations."""
        metrics = RegistryMetrics()
        
        metrics.record_operation(True, 0.1)
        metrics.record_operation(True, 0.2)
        
        assert metrics.total_operations == 2
        assert metrics.successful_operations == 2
        assert metrics.failed_operations == 0
        assert metrics.average_response_time == 0.15
        assert metrics.get_success_ratio() == 1.0
    
    def test_record_operation_failure(self):
        """Test recording failed operations."""
        metrics = RegistryMetrics()
        
        metrics.record_operation(False, 0.1)
        metrics.record_operation(True, 0.2)
        metrics.record_operation(False, 0.3)
        
        assert metrics.total_operations == 3
        assert metrics.successful_operations == 1
        assert metrics.failed_operations == 2
        assert metrics.average_response_time == 0.2
        assert metrics.get_success_ratio() == 1/3
    
    def test_cache_metrics(self):
        """Test cache hit/miss tracking."""
        metrics = RegistryMetrics()
        
        metrics.record_cache_hit()
        metrics.record_cache_hit()
        metrics.record_cache_miss()
        
        assert metrics.cache_hits == 2
        assert metrics.cache_misses == 1
        assert metrics.get_cache_hit_ratio() == 2/3
    
    def test_metrics_to_dict(self):
        """Test metrics dictionary conversion."""
        metrics = RegistryMetrics()
        metrics.record_operation(True, 0.1)
        metrics.record_cache_hit()
        
        metrics_dict = metrics.to_dict()
        
        assert isinstance(metrics_dict, dict)
        assert metrics_dict["total_operations"] == 1
        assert metrics_dict["cache_hits"] == 1
        assert "success_ratio" in metrics_dict
        assert "cache_hit_ratio" in metrics_dict


class TestBaseCache:
    """Test base cache functionality."""
    
    def test_cache_initialization(self):
        """Test cache is properly initialized."""
        cache = BaseCache(max_size=10, ttl_seconds=60)
        
        assert cache.max_size == 10
        assert cache.ttl_seconds == 60
        assert cache.size() == 0
    
    def test_cache_set_get(self):
        """Test basic cache set/get operations."""
        cache = BaseCache()
        
        cache.set("key1", "value1")
        cache.set("key2", {"nested": "value"})
        
        assert cache.get("key1") == "value1"
        assert cache.get("key2") == {"nested": "value"}
        assert cache.get("nonexistent") is None
        assert cache.size() == 2
    
    def test_cache_ttl_expiration(self):
        """Test cache TTL expiration."""
        cache = BaseCache(ttl_seconds=0.1)  # Very short TTL
        
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        
        # Wait for TTL expiration
        import time
        time.sleep(0.2)
        
        assert cache.get("key1") is None
        assert cache.size() == 0
    
    def test_cache_max_size_eviction(self):
        """Test cache LRU eviction when max size is reached."""
        cache = BaseCache(max_size=2)
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        assert cache.size() == 2
        
        # Add third item, should evict oldest
        cache.set("key3", "value3")
        assert cache.size() == 2
        assert cache.get("key1") is None  # Evicted
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"
    
    def test_cache_remove(self):
        """Test cache item removal."""
        cache = BaseCache()
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        assert cache.size() == 2
        
        cache.remove("key1")
        assert cache.size() == 1
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
    
    def test_cache_clear(self):
        """Test cache clearing."""
        cache = BaseCache()
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        assert cache.size() == 2
        
        cache.clear()
        assert cache.size() == 0
        assert cache.get("key1") is None
        assert cache.get("key2") is None


class TestAbstractRegistry:
    """Test abstract registry implementation."""
    
    @pytest.fixture
    def storage_adapter(self):
        """Create a mock storage adapter for testing."""
        return InMemoryStorageAdapter()
    
    @pytest.fixture
    def registry(self, storage_adapter):
        """Create a registry instance for testing."""
        return AbstractRegistry(
            entity_type=MockEntity,
            storage_adapter=storage_adapter,
            cache_enabled=True,
            cache_size=10,
            cache_ttl=300
        )
    
    @pytest.fixture
    def sample_entity(self):
        """Create a sample entity for testing."""
        return MockEntity(
            entity_id=uuid4(),
            name="test-entity",
            entity_type="test"
        )
    
    @pytest.mark.asyncio
    async def test_registry_initialization(self, registry):
        """Test registry initialization."""
        assert registry.entity_type == MockEntity
        assert registry.cache_enabled is True
        assert registry.cache is not None
        assert isinstance(registry.metrics, RegistryMetrics)
        assert registry.is_connected is False
    
    @pytest.mark.asyncio
    async def test_registry_connection(self, registry):
        """Test registry connection to storage."""
        assert not registry.is_connected
        
        await registry.connect()
        
        assert registry.is_connected
        
        await registry.disconnect()
        
        assert not registry.is_connected
    
    @pytest.mark.asyncio
    async def test_register_entity(self, registry, sample_entity):
        """Test entity registration."""
        await registry.connect()
        
        # Register entity
        await registry.register(sample_entity)
        
        # Verify registration
        assert await registry.exists(sample_entity.id)
        assert registry.metrics.entity_count == 1
        
        # Verify entity can be retrieved
        retrieved_entity = await registry.get(sample_entity.id)
        assert retrieved_entity.id == sample_entity.id
        assert retrieved_entity.name == sample_entity.name
    
    @pytest.mark.asyncio
    async def test_register_duplicate_entity(self, registry, sample_entity):
        """Test registering duplicate entity raises error."""
        await registry.connect()
        
        # Register entity first time
        await registry.register(sample_entity)
        
        # Try to register same entity again
        with pytest.raises(EntityAlreadyExistsError) as exc_info:
            await registry.register(sample_entity)
        
        assert str(sample_entity.id) in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_register_invalid_entity(self, registry):
        """Test registering invalid entity raises error."""
        await registry.connect()
        
        # Create invalid entity
        invalid_entity = MockEntity(uuid4(), "invalid", "test")
        invalid_entity.set_validation_result(False)
        
        with pytest.raises(RegistryError):
            await registry.register(invalid_entity)
    
    @pytest.mark.asyncio
    async def test_unregister_entity(self, registry, sample_entity):
        """Test entity unregistration."""
        await registry.connect()
        
        # Register entity
        await registry.register(sample_entity)
        assert await registry.exists(sample_entity.id)
        
        # Unregister entity
        await registry.unregister(sample_entity.id)
        
        # Verify unregistration
        assert not await registry.exists(sample_entity.id)
        assert registry.metrics.entity_count == 0
        
        # Verify entity cannot be retrieved
        with pytest.raises(EntityNotFoundError):
            await registry.get(sample_entity.id)
    
    @pytest.mark.asyncio
    async def test_unregister_nonexistent_entity(self, registry):
        """Test unregistering nonexistent entity raises error."""
        await registry.connect()
        
        nonexistent_id = uuid4()
        
        with pytest.raises(EntityNotFoundError) as exc_info:
            await registry.unregister(nonexistent_id)
        
        assert str(nonexistent_id) in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_get_entity(self, registry, sample_entity):
        """Test getting entity by ID."""
        await registry.connect()
        
        # Register entity
        await registry.register(sample_entity)
        
        # Get entity
        retrieved_entity = await registry.get(sample_entity.id)
        
        assert retrieved_entity.id == sample_entity.id
        assert retrieved_entity.name == sample_entity.name
        assert retrieved_entity.entity_type == sample_entity.entity_type
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_entity(self, registry):
        """Test getting nonexistent entity raises error."""
        await registry.connect()
        
        nonexistent_id = uuid4()
        
        with pytest.raises(EntityNotFoundError) as exc_info:
            await registry.get(nonexistent_id)
        
        assert str(nonexistent_id) in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_update_entity(self, registry, sample_entity):
        """Test updating existing entity."""
        await registry.connect()
        
        # Register entity
        await registry.register(sample_entity)
        
        # Modify entity
        sample_entity._name = "updated-name"
        
        # Update entity
        await registry.update(sample_entity)
        
        # Verify update
        retrieved_entity = await registry.get(sample_entity.id)
        assert retrieved_entity.name == "updated-name"
    
    @pytest.mark.asyncio
    async def test_update_nonexistent_entity(self, registry, sample_entity):
        """Test updating nonexistent entity raises error."""
        await registry.connect()
        
        with pytest.raises(EntityNotFoundError):
            await registry.update(sample_entity)
    
    @pytest.mark.asyncio
    async def test_list_entities(self, registry):
        """Test listing entities."""
        await registry.connect()
        
        # Register multiple entities
        entities = []
        for i in range(3):
            entity = MockEntity(uuid4(), f"entity-{i}", "test")
            entities.append(entity)
            await registry.register(entity)
        
        # List all entities
        retrieved_entities = await registry.list()
        
        assert len(retrieved_entities) == 3
        retrieved_ids = [e.id for e in retrieved_entities]
        for entity in entities:
            assert entity.id in retrieved_ids
    
    @pytest.mark.asyncio
    async def test_list_entities_with_filters(self, registry):
        """Test listing entities with filters."""
        await registry.connect()
        
        # Register entities with different types
        entity1 = MockEntity(uuid4(), "entity-1", "type-a")
        entity2 = MockEntity(uuid4(), "entity-2", "type-b")
        entity3 = MockEntity(uuid4(), "entity-3", "type-a")
        
        await registry.register(entity1)
        await registry.register(entity2)
        await registry.register(entity3)
        
        # List entities with filter
        filtered_entities = await registry.list(filters={"entity_type": "type-a"})
        
        assert len(filtered_entities) == 2
        assert all(e.entity_type == "type-a" for e in filtered_entities)
    
    @pytest.mark.asyncio
    async def test_list_entities_with_pagination(self, registry):
        """Test listing entities with pagination."""
        await registry.connect()
        
        # Register multiple entities
        for i in range(5):
            entity = MockEntity(uuid4(), f"entity-{i}", "test")
            await registry.register(entity)
        
        # Test pagination
        page1 = await registry.list(limit=2, offset=0)
        page2 = await registry.list(limit=2, offset=2)
        
        assert len(page1) == 2
        assert len(page2) == 2
        
        # Ensure no overlap
        page1_ids = [e.id for e in page1]
        page2_ids = [e.id for e in page2]
        assert not any(id in page2_ids for id in page1_ids)
    
    @pytest.mark.asyncio
    async def test_count_entities(self, registry):
        """Test counting entities."""
        await registry.connect()
        
        # Initially no entities
        assert await registry.count() == 0
        
        # Register entities
        for i in range(3):
            entity = MockEntity(uuid4(), f"entity-{i}", "test")
            await registry.register(entity)
        
        # Count entities
        assert await registry.count() == 3
    
    @pytest.mark.asyncio
    async def test_health_check(self, registry):
        """Test registry health check."""
        # Health check should fail when not connected
        assert not await registry.health_check()
        
        # Connect and test again
        await registry.connect()
        assert await registry.health_check()
        
        # Disconnect and test
        await registry.disconnect()
        assert not await registry.health_check()
    
    @pytest.mark.asyncio
    async def test_cache_functionality(self, registry, sample_entity):
        """Test registry cache functionality."""
        await registry.connect()
        
        # Register entity
        await registry.register(sample_entity)
        
        # First get should be a cache miss
        entity1 = await registry.get(sample_entity.id)
        assert registry.metrics.cache_misses > 0
        
        # Second get should be a cache hit
        initial_misses = registry.metrics.cache_misses
        entity2 = await registry.get(sample_entity.id)
        assert registry.metrics.cache_hits > 0
        assert registry.metrics.cache_misses == initial_misses
        
        # Entities should be the same
        assert entity1.id == entity2.id
    
    @pytest.mark.asyncio
    async def test_clear_cache(self, registry, sample_entity):
        """Test clearing registry cache."""
        await registry.connect()
        
        # Register and cache entity
        await registry.register(sample_entity)
        await registry.get(sample_entity.id)  # Cache the entity
        
        assert registry.cache.size() > 0
        
        # Clear cache
        await registry.clear_cache()
        
        assert registry.cache.size() == 0
    
    @pytest.mark.asyncio
    async def test_metrics_collection(self, registry, sample_entity):
        """Test metrics are properly collected."""
        await registry.connect()
        
        initial_operations = registry.metrics.total_operations
        
        # Perform operations
        await registry.register(sample_entity)
        await registry.get(sample_entity.id)
        await registry.update(sample_entity)
        
        # Check metrics
        assert registry.metrics.total_operations > initial_operations
        assert registry.metrics.successful_operations > 0
        assert registry.metrics.entity_count == 1
    
    @pytest.mark.asyncio
    async def test_get_metrics(self, registry):
        """Test getting registry metrics."""
        await registry.connect()
        
        metrics_dict = await registry.get_metrics()
        
        assert isinstance(metrics_dict, dict)
        assert "registry_name" in metrics_dict
        assert "entity_type" in metrics_dict
        assert "cache_enabled" in metrics_dict
        assert "connected" in metrics_dict
        assert metrics_dict["entity_type"] == "MockEntity"
        assert metrics_dict["connected"] is True


class TestRegistryErrorHandling:
    """Test registry error handling scenarios."""
    
    @pytest.mark.asyncio
    async def test_storage_connection_failure(self):
        """Test handling of storage connection failures."""
        failing_adapter = FailingMockStorageAdapter()
        registry = AbstractRegistry(
            entity_type=MockEntity,
            storage_adapter=failing_adapter
        )
        
        with pytest.raises(RegistryConnectionError):
            await registry.connect()
    
    @pytest.mark.asyncio
    async def test_storage_operation_failure(self):
        """Test handling of storage operation failures."""
        failing_adapter = FailingMockStorageAdapter()
        registry = AbstractRegistry(
            entity_type=MockEntity,
            storage_adapter=failing_adapter
        )
        
        # Force connection for testing
        failing_adapter._connected = True
        registry._connected = True
        
        entity = MockEntity(uuid4(), "test", "test")
        
        # Operations should fail due to storage failures
        with pytest.raises((RegistryError, Exception)):
            await registry.register(entity)


class TestRegistryFactory:
    """Test registry factory functionality."""
    
    def test_create_registry(self):
        """Test creating registry with factory."""
        storage_adapter = InMemoryStorageAdapter()
        
        registry = RegistryFactory.create_registry(
            entity_type=MockEntity,
            storage_adapter=storage_adapter
        )
        
        assert isinstance(registry, AbstractRegistry)
        assert registry.entity_type == MockEntity
        assert registry.storage_adapter == storage_adapter
    
    def test_create_registry_with_custom_class(self):
        """Test creating registry with custom registry class."""
        storage_adapter = InMemoryStorageAdapter()
        
        class CustomRegistry(AbstractRegistry):
            pass
        
        registry = RegistryFactory.create_registry(
            entity_type=MockEntity,
            storage_adapter=storage_adapter,
            registry_class=CustomRegistry
        )
        
        assert isinstance(registry, CustomRegistry)
        assert isinstance(registry, AbstractRegistry)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])