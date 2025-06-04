import asyncio
from typing import Any, Dict, List, Optional, TypeVar, Generic
from uuid import UUID
from datetime import datetime, timezone
from src.core.interfaces.base import IStorageAdapter, IEntity
from src.utils.exceptions import StorageError, DataPersistenceError
T = TypeVar('T', bound=IEntity)

class MockStorageAdapter(IStorageAdapter[T], Generic[T]):

    def __init__(self, storage_type: str='mock'):
        self._storage_type = storage_type
        self._entities: Dict[UUID, T] = {}
        self._connected = False
        self._connection_delay = 0.0
        self._failure_rate = 0.0
        self._health_status = True
        self._operation_count = 0

    @property
    def storage_type(self) -> str:
        return self._storage_type

    def set_connection_delay(self, delay: float) -> None:
        self._connection_delay = delay

    def set_failure_rate(self, rate: float) -> None:
        self._failure_rate = max(0.0, min(1.0, rate))

    def set_health_status(self, healthy: bool) -> None:
        self._health_status = healthy

    def get_operation_count(self) -> int:
        return self._operation_count

    def get_entity_count(self) -> int:
        return len(self._entities)

    def clear_storage(self) -> None:
        self._entities.clear()

    async def connect(self) -> None:
        if self._connection_delay > 0:
            await asyncio.sleep(self._connection_delay)
        self._simulate_failure('Connection failed')
        self._connected = True

    async def disconnect(self) -> None:
        if self._connection_delay > 0:
            await asyncio.sleep(self._connection_delay)
        self._connected = False

    async def save(self, entity: T) -> None:
        self._operation_count += 1
        self._ensure_connected()
        self._simulate_failure('Save operation failed')
        if not entity.validate():
            raise DataPersistenceError(f'Entity validation failed for {entity.id}')
        await asyncio.sleep(0.001)
        self._entities[entity.id] = entity

    async def load(self, entity_id: UUID) -> T:
        self._operation_count += 1
        self._ensure_connected()
        self._simulate_failure('Load operation failed')
        await asyncio.sleep(0.001)
        if entity_id not in self._entities:
            raise StorageError(f'Entity {entity_id} not found')
        return self._entities[entity_id]

    async def delete(self, entity_id: UUID) -> None:
        self._operation_count += 1
        self._ensure_connected()
        self._simulate_failure('Delete operation failed')
        await asyncio.sleep(0.001)
        if entity_id not in self._entities:
            raise StorageError(f'Entity {entity_id} not found')
        del self._entities[entity_id]

    async def query(self, filters: Dict[str, Any], limit: Optional[int]=None, offset: Optional[int]=None) -> List[T]:
        self._operation_count += 1
        self._ensure_connected()
        self._simulate_failure('Query operation failed')
        await asyncio.sleep(0.001)
        results = list(self._entities.values())
        for key, value in filters.items():
            filtered_results = []
            for entity in results:
                if hasattr(entity, key):
                    entity_value = getattr(entity, key)
                    if hasattr(entity_value, 'value'):
                        entity_value = entity_value.value
                    if entity_value == value:
                        filtered_results.append(entity)
            results = filtered_results
        if offset:
            results = results[offset:]
        if limit:
            results = results[:limit]
        return results

    async def health_check(self) -> bool:
        self._operation_count += 1
        await asyncio.sleep(0.001)
        return self._health_status and self._connected

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise StorageError('Storage adapter not connected')

    def _simulate_failure(self, error_message: str) -> None:
        import random
        if random.random() < self._failure_rate:
            raise StorageError(error_message)

class MockEntity(IEntity):

    def __init__(self, entity_id: UUID, name: str, entity_type: str='mock', metadata: Optional[Dict[str, Any]]=None):
        from src.core.interfaces.base import BaseMetadata, EntityStatus
        self._id = entity_id
        self._name = name
        self._entity_type = entity_type
        self._status = EntityStatus.CREATED
        self._metadata = BaseMetadata(entity_id=entity_id, timestamp=datetime.now(timezone.utc), version='1.0.0', created_by=entity_id, custom=metadata or {})
        self._validation_result = True

    @property
    def id(self) -> UUID:
        return self._id

    @property
    def metadata(self):
        return self._metadata

    @property
    def status(self):
        return self._status

    @property
    def name(self) -> str:
        return self._name

    @property
    def entity_type(self) -> str:
        return self._entity_type

    def set_validation_result(self, result: bool) -> None:
        self._validation_result = result

    def set_status(self, status) -> None:
        self._status = status

    async def initialize(self) -> None:
        from src.core.interfaces.base import EntityStatus
        self._status = EntityStatus.INITIALIZING
        await asyncio.sleep(0.001)
        self._status = EntityStatus.ACTIVE

    async def start(self) -> None:
        from src.core.interfaces.base import EntityStatus
        self._status = EntityStatus.ACTIVE
        await asyncio.sleep(0.001)

    async def stop(self) -> None:
        from src.core.interfaces.base import EntityStatus
        self._status = EntityStatus.INACTIVE
        await asyncio.sleep(0.001)

    async def terminate(self) -> None:
        from src.core.interfaces.base import EntityStatus
        self._status = EntityStatus.TERMINATED
        await asyncio.sleep(0.001)

    def to_dict(self) -> Dict[str, Any]:
        return {'id': str(self._id), 'name': self._name, 'entity_type': self._entity_type, 'status': self._status.value, 'metadata': self._metadata.to_dict()}

    def validate(self) -> bool:
        return self._validation_result

    def __repr__(self) -> str:
        return f'MockEntity(id={self._id}, name={self._name}, type={self._entity_type})'

class FailingMockStorageAdapter(MockStorageAdapter):

    def __init__(self):
        super().__init__('failing_mock')
        self.set_failure_rate(1.0)
        self.set_health_status(False)

class SlowMockStorageAdapter(MockStorageAdapter):

    def __init__(self, delay: float=1.0):
        super().__init__('slow_mock')
        self.set_connection_delay(delay)

    async def save(self, entity: T) -> None:
        await asyncio.sleep(self._connection_delay)
        await super().save(entity)

    async def load(self, entity_id: UUID) -> T:
        await asyncio.sleep(self._connection_delay)
        return await super().load(entity_id)

    async def delete(self, entity_id: UUID) -> None:
        await asyncio.sleep(self._connection_delay)
        await super().delete(entity_id)

    async def query(self, filters: Dict[str, Any], limit: Optional[int]=None, offset: Optional[int]=None) -> List[T]:
        await asyncio.sleep(self._connection_delay)
        return await super().query(filters, limit, offset)

class InMemoryStorageAdapter(MockStorageAdapter):

    def __init__(self):
        super().__init__('in_memory')
        self.set_health_status(True)
        self.set_failure_rate(0.0)
        self.set_connection_delay(0.0)
        asyncio.create_task(self.connect())