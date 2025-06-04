import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID
import logging
from src.core.registry.base import AbstractRegistry, RegistryMetrics
from src.core.interfaces.base import IStorageAdapter, BaseMetadata
from src.core.interfaces.digital_twin import IDigitalTwin, DigitalTwinType, DigitalTwinState, TwinCapability, TwinSnapshot
from src.utils.exceptions import DigitalTwinError, DigitalTwinNotFoundError, EntityNotFoundError, RegistryError
logger = logging.getLogger(__name__)

class DigitalTwinRelationship:

    def __init__(self, source_twin_id: UUID, target_twin_id: UUID, relationship_type: str, metadata: Optional[Dict[str, Any]]=None, created_at: Optional[datetime]=None):
        self.source_twin_id = source_twin_id
        self.target_twin_id = target_twin_id
        self.relationship_type = relationship_type
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {'source_twin_id': str(self.source_twin_id), 'target_twin_id': str(self.target_twin_id), 'relationship_type': self.relationship_type, 'metadata': self.metadata, 'created_at': self.created_at.isoformat()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DigitalTwinRelationship':
        return cls(source_twin_id=UUID(data['source_twin_id']), target_twin_id=UUID(data['target_twin_id']), relationship_type=data['relationship_type'], metadata=data.get('metadata', {}), created_at=datetime.fromisoformat(data['created_at']))

class DigitalTwinComposition:

    def __init__(self, composite_twin_id: UUID, component_twin_ids: List[UUID], composition_rules: Dict[str, Any], created_at: Optional[datetime]=None):
        self.composite_twin_id = composite_twin_id
        self.component_twin_ids = component_twin_ids
        self.composition_rules = composition_rules
        self.created_at = created_at or datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {'composite_twin_id': str(self.composite_twin_id), 'component_twin_ids': [str(id) for id in self.component_twin_ids], 'composition_rules': self.composition_rules, 'created_at': self.created_at.isoformat()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DigitalTwinComposition':
        return cls(composite_twin_id=UUID(data['composite_twin_id']), component_twin_ids=[UUID(id) for id in data['component_twin_ids']], composition_rules=data['composition_rules'], created_at=datetime.fromisoformat(data['created_at']))

class DigitalTwinMetrics(RegistryMetrics):

    def __init__(self):
        super().__init__()
        self.twins_by_type: Dict[str, int] = {}
        self.twins_by_state: Dict[str, int] = {}
        self.active_twins = 0
        self.inactive_twins = 0
        self.total_relationships = 0
        self.total_compositions = 0
        self.snapshots_created = 0
        self.average_twin_age_days = 0.0

    def update_twin_statistics(self, twin_type: DigitalTwinType, twin_state: DigitalTwinState, is_active: bool) -> None:
        type_key = twin_type.value
        self.twins_by_type[type_key] = self.twins_by_type.get(type_key, 0) + 1
        state_key = twin_state.value
        self.twins_by_state[state_key] = self.twins_by_state.get(state_key, 0) + 1
        if is_active:
            self.active_twins += 1
        else:
            self.inactive_twins += 1

    def to_dict(self) -> Dict[str, Any]:
        base_metrics = super().to_dict()
        base_metrics.update({'twins_by_type': self.twins_by_type, 'twins_by_state': self.twins_by_state, 'active_twins': self.active_twins, 'inactive_twins': self.inactive_twins, 'total_relationships': self.total_relationships, 'total_compositions': self.total_compositions, 'snapshots_created': self.snapshots_created, 'average_twin_age_days': self.average_twin_age_days})
        return base_metrics

class DigitalTwinRegistry(AbstractRegistry[IDigitalTwin]):

    def __init__(self, storage_adapter: IStorageAdapter[IDigitalTwin], cache_enabled: bool=True, cache_size: int=1000, cache_ttl: int=300):
        super().__init__(entity_type=IDigitalTwin, storage_adapter=storage_adapter, cache_enabled=cache_enabled, cache_size=cache_size, cache_ttl=cache_ttl)
        self.relationships: Dict[UUID, List[DigitalTwinRelationship]] = {}
        self.compositions: Dict[UUID, DigitalTwinComposition] = {}
        self.snapshots: Dict[UUID, List[TwinSnapshot]] = {}
        self.metrics = DigitalTwinMetrics()
        self._relationship_lock = asyncio.Lock()
        self._composition_lock = asyncio.Lock()
        self._snapshot_lock = asyncio.Lock()

    async def register_digital_twin(self, twin: IDigitalTwin, initial_relationships: Optional[List[DigitalTwinRelationship]]=None) -> None:
        await self.register(twin)
        if initial_relationships:
            for relationship in initial_relationships:
                await self.add_relationship(relationship)

    async def get_digital_twin(self, twin_id: UUID) -> IDigitalTwin:
        try:
            return await self.get(twin_id)
        except EntityNotFoundError:
            raise DigitalTwinNotFoundError(twin_id=str(twin_id))

    async def find_twins_by_type(self, twin_type: DigitalTwinType) -> List[IDigitalTwin]:
        filters = {'twin_type': twin_type.value}
        return await self.list(filters=filters)

    async def find_twins_by_capability(self, capability: TwinCapability) -> List[IDigitalTwin]:
        all_twins = await self.list()
        matching_twins = []
        for twin in all_twins:
            if capability in twin.capabilities:
                matching_twins.append(twin)
        return matching_twins

    async def find_twins_by_state(self, state: DigitalTwinState) -> List[IDigitalTwin]:
        filters = {'current_state': state.value}
        return await self.list(filters=filters)

    async def add_relationship(self, relationship: DigitalTwinRelationship) -> None:
        async with self._relationship_lock:
            await self.get_digital_twin(relationship.source_twin_id)
            await self.get_digital_twin(relationship.target_twin_id)
            source_id = relationship.source_twin_id
            if source_id not in self.relationships:
                self.relationships[source_id] = []
            self.relationships[source_id].append(relationship)
            self.metrics.total_relationships += 1
            self.logger.info(f'Added relationship: {relationship.source_twin_id} -> {relationship.target_twin_id} ({relationship.relationship_type})')

    async def remove_relationship(self, source_twin_id: UUID, target_twin_id: UUID, relationship_type: Optional[str]=None) -> bool:
        async with self._relationship_lock:
            if source_twin_id not in self.relationships:
                return False
            relationships = self.relationships[source_twin_id]
            removed_count = 0
            filtered_relationships = []
            for rel in relationships:
                should_remove = rel.target_twin_id == target_twin_id and (relationship_type is None or rel.relationship_type == relationship_type)
                if should_remove:
                    removed_count += 1
                else:
                    filtered_relationships.append(rel)
            self.relationships[source_twin_id] = filtered_relationships
            self.metrics.total_relationships -= removed_count
            if removed_count > 0:
                self.logger.info(f'Removed {removed_count} relationship(s): {source_twin_id} -> {target_twin_id}')
            return removed_count > 0

    async def get_relationships(self, twin_id: UUID, relationship_type: Optional[str]=None) -> List[DigitalTwinRelationship]:
        relationships = self.relationships.get(twin_id, [])
        if relationship_type:
            relationships = [rel for rel in relationships if rel.relationship_type == relationship_type]
        return relationships

    async def get_related_twins(self, twin_id: UUID, relationship_type: Optional[str]=None, include_reverse: bool=False) -> List[Tuple[IDigitalTwin, str]]:
        related_twins = []
        relationships = await self.get_relationships(twin_id, relationship_type)
        for rel in relationships:
            try:
                related_twin = await self.get_digital_twin(rel.target_twin_id)
                related_twins.append((related_twin, rel.relationship_type))
            except DigitalTwinNotFoundError:
                await self.remove_relationship(twin_id, rel.target_twin_id, rel.relationship_type)
        if include_reverse:
            for source_id, relationships in self.relationships.items():
                for rel in relationships:
                    if rel.target_twin_id == twin_id:
                        if relationship_type is None or rel.relationship_type == relationship_type:
                            try:
                                related_twin = await self.get_digital_twin(source_id)
                                related_twins.append((related_twin, f'reverse_{rel.relationship_type}'))
                            except DigitalTwinNotFoundError:
                                pass
        return related_twins

    async def create_composition(self, composite_twin_id: UUID, component_twin_ids: List[UUID], composition_rules: Dict[str, Any]) -> None:
        async with self._composition_lock:
            await self.get_digital_twin(composite_twin_id)
            for component_id in component_twin_ids:
                await self.get_digital_twin(component_id)
            composition = DigitalTwinComposition(composite_twin_id=composite_twin_id, component_twin_ids=component_twin_ids, composition_rules=composition_rules)
            self.compositions[composite_twin_id] = composition
            self.metrics.total_compositions += 1
            self.logger.info(f'Created composition for twin {composite_twin_id} with {len(component_twin_ids)} components')

    async def get_composition(self, composite_twin_id: UUID) -> Optional[DigitalTwinComposition]:
        return self.compositions.get(composite_twin_id)

    async def decompose_twin(self, composite_twin_id: UUID) -> List[UUID]:
        async with self._composition_lock:
            composition = self.compositions.get(composite_twin_id)
            if not composition:
                raise DigitalTwinError(f'Twin {composite_twin_id} is not a composite twin')
            component_ids = composition.component_twin_ids.copy()
            del self.compositions[composite_twin_id]
            self.metrics.total_compositions -= 1
            self.logger.info(f'Decomposed twin {composite_twin_id}')
            return component_ids

    async def create_snapshot(self, twin_id: UUID) -> TwinSnapshot:
        async with self._snapshot_lock:
            twin = await self.get_digital_twin(twin_id)
            snapshot = await twin.create_snapshot()
            if twin_id not in self.snapshots:
                self.snapshots[twin_id] = []
            self.snapshots[twin_id].append(snapshot)
            self.metrics.snapshots_created += 1
            self.logger.info(f'Created snapshot for twin {twin_id}')
            return snapshot

    async def get_snapshots(self, twin_id: UUID, limit: Optional[int]=None) -> List[TwinSnapshot]:
        snapshots = self.snapshots.get(twin_id, [])
        snapshots.sort(key=lambda s: s.snapshot_time, reverse=True)
        if limit:
            snapshots = snapshots[:limit]
        return snapshots

    async def get_twin_statistics(self) -> Dict[str, Any]:
        all_twins = await self.list()
        stats = {'total_twins': len(all_twins), 'twins_by_type': {}, 'twins_by_state': {}, 'twins_with_relationships': len(self.relationships), 'total_relationships': sum((len(rels) for rels in self.relationships.values())), 'composite_twins': len(self.compositions), 'twins_with_snapshots': len(self.snapshots), 'total_snapshots': sum((len(snapshots) for snapshots in self.snapshots.values()))}
        for twin in all_twins:
            twin_type = twin.twin_type.value
            twin_state = twin.current_state.value
            stats['twins_by_type'][twin_type] = stats['twins_by_type'].get(twin_type, 0) + 1
            stats['twins_by_state'][twin_state] = stats['twins_by_state'].get(twin_state, 0) + 1
        return stats

    async def _post_register_hook(self, entity: IDigitalTwin) -> None:
        self.metrics.update_twin_statistics(twin_type=entity.twin_type, twin_state=entity.current_state, is_active=entity.current_state == DigitalTwinState.OPERATIONAL)

    async def _pre_unregister_hook(self, entity: IDigitalTwin) -> None:
        twin_id = entity.id
        if twin_id in self.relationships:
            del self.relationships[twin_id]
        for source_id in list(self.relationships.keys()):
            relationships = self.relationships[source_id]
            filtered_relationships = [rel for rel in relationships if rel.target_twin_id != twin_id]
            self.relationships[source_id] = filtered_relationships
        if twin_id in self.compositions:
            del self.compositions[twin_id]
        if twin_id in self.snapshots:
            del self.snapshots[twin_id]