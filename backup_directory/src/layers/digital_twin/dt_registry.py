import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID
import logging
from src.core.registry.dt_registry import DigitalTwinRegistry as BaseDigitalTwinRegistry
from src.core.interfaces.base import IStorageAdapter
from src.core.interfaces.digital_twin import IDigitalTwin, DigitalTwinType, DigitalTwinState, TwinCapability, TwinSnapshot, TwinModel
from src.utils.exceptions import DigitalTwinError, DigitalTwinNotFoundError, EntityNotFoundError, RegistryError
logger = logging.getLogger(__name__)

class DigitalTwinAssociation:

    def __init__(self, twin_id: UUID, associated_entity_id: UUID, association_type: str, entity_type: str, created_at: Optional[datetime]=None, metadata: Optional[Dict[str, Any]]=None):
        self.twin_id = twin_id
        self.associated_entity_id = associated_entity_id
        self.association_type = association_type
        self.entity_type = entity_type
        self.created_at = created_at or datetime.now(timezone.utc)
        self.metadata = metadata or {}
        self.last_interaction: Optional[datetime] = None
        self.interaction_count = 0

    def update_interaction(self) -> None:
        self.last_interaction = datetime.now(timezone.utc)
        self.interaction_count += 1

    def to_dict(self) -> Dict[str, Any]:
        return {'twin_id': str(self.twin_id), 'associated_entity_id': str(self.associated_entity_id), 'association_type': self.association_type, 'entity_type': self.entity_type, 'created_at': self.created_at.isoformat(), 'last_interaction': self.last_interaction.isoformat() if self.last_interaction else None, 'interaction_count': self.interaction_count, 'metadata': self.metadata}

class DigitalTwinPerformanceMetrics:

    def __init__(self):
        self.total_twins = 0
        self.twins_by_type: Dict[DigitalTwinType, int] = {}
        self.twins_by_state: Dict[DigitalTwinState, int] = {}
        self.model_executions = 0
        self.predictions_made = 0
        self.simulations_run = 0
        self.data_updates = 0
        self.snapshots_created = 0
        self.last_activity: Optional[datetime] = None
        self.average_update_frequency = 0.0
        self._activity_timestamps: List[datetime] = []

    def record_activity(self, activity_type: str, twin_id: UUID, twin_type: DigitalTwinType) -> None:
        now = datetime.now(timezone.utc)
        self.last_activity = now
        self._activity_timestamps.append(now)
        if activity_type == 'model_execution':
            self.model_executions += 1
        elif activity_type == 'prediction':
            self.predictions_made += 1
        elif activity_type == 'simulation':
            self.simulations_run += 1
        elif activity_type == 'data_update':
            self.data_updates += 1
        elif activity_type == 'snapshot':
            self.snapshots_created += 1
        self.twins_by_type[twin_type] = self.twins_by_type.get(twin_type, 0) + 1
        cutoff = now - timedelta(hours=1)
        self._activity_timestamps = [ts for ts in self._activity_timestamps if ts > cutoff]
        if len(self._activity_timestamps) > 1:
            time_span = (self._activity_timestamps[-1] - self._activity_timestamps[0]).total_seconds() / 60
            self.average_update_frequency = len(self._activity_timestamps) / max(time_span, 1)

    def get_activity_rate_per_minute(self) -> float:
        return self.average_update_frequency

    def to_dict(self) -> Dict[str, Any]:
        return {'total_twins': self.total_twins, 'twins_by_type': {ttype.value: count for ttype, count in self.twins_by_type.items()}, 'twins_by_state': {state.value: count for state, count in self.twins_by_state.items()}, 'model_executions': self.model_executions, 'predictions_made': self.predictions_made, 'simulations_run': self.simulations_run, 'data_updates': self.data_updates, 'snapshots_created': self.snapshots_created, 'last_activity': self.last_activity.isoformat() if self.last_activity else None, 'activity_rate_per_minute': self.get_activity_rate_per_minute()}

class EnhancedDigitalTwinRegistry(BaseDigitalTwinRegistry):

    def __init__(self, storage_adapter: IStorageAdapter[IDigitalTwin], cache_enabled: bool=True, cache_size: int=1000, cache_ttl: int=300):
        super().__init__(storage_adapter=storage_adapter, cache_enabled=cache_enabled, cache_size=cache_size, cache_ttl=cache_ttl)
        self.twin_associations: Dict[str, DigitalTwinAssociation] = {}
        self.twin_hierarchies: Dict[UUID, Set[UUID]] = {}
        self.twin_performance_metrics = DigitalTwinPerformanceMetrics()
        self.model_registry: Dict[UUID, TwinModel] = {}
        self.twin_snapshots: Dict[UUID, List[TwinSnapshot]] = {}
        self._association_lock = asyncio.Lock()
        self._performance_lock = asyncio.Lock()
        self._hierarchy_lock = asyncio.Lock()

    async def register_digital_twin_enhanced(self, twin: IDigitalTwin, associations: Optional[List[DigitalTwinAssociation]]=None, parent_twin_id: Optional[UUID]=None) -> None:
        await self.register_digital_twin(twin)
        if associations:
            for association in associations:
                await self.add_association(association)
        if parent_twin_id:
            await self.add_twin_to_hierarchy(parent_twin_id, twin.id)
        for model in twin.integrated_models:
            await self.register_model(model)
        async with self._performance_lock:
            self.twin_performance_metrics.total_twins += 1
            self.twin_performance_metrics.twins_by_type[twin.twin_type] = self.twin_performance_metrics.twins_by_type.get(twin.twin_type, 0) + 1
            self.twin_performance_metrics.twins_by_state[twin.current_state] = self.twin_performance_metrics.twins_by_state.get(twin.current_state, 0) + 1

    async def add_association(self, association: DigitalTwinAssociation) -> None:
        async with self._association_lock:
            await self.get_digital_twin(association.twin_id)
            key = f'{association.twin_id}:{association.associated_entity_id}:{association.association_type}'
            self.twin_associations[key] = association
            logger.info(f'Added association: Twin {association.twin_id} -> {association.entity_type} {association.associated_entity_id} ({association.association_type})')

    async def remove_association(self, twin_id: UUID, associated_entity_id: UUID, association_type: str) -> bool:
        async with self._association_lock:
            key = f'{twin_id}:{associated_entity_id}:{association_type}'
            if key in self.twin_associations:
                del self.twin_associations[key]
                logger.info(f'Removed association: {key}')
                return True
            return False

    async def get_twin_associations(self, twin_id: UUID, association_type: Optional[str]=None, entity_type: Optional[str]=None) -> List[DigitalTwinAssociation]:
        associations = []
        for association in self.twin_associations.values():
            if association.twin_id == twin_id:
                if association_type and association.association_type != association_type:
                    continue
                if entity_type and association.entity_type != entity_type:
                    continue
                associations.append(association)
        return associations

    async def add_twin_to_hierarchy(self, parent_twin_id: UUID, child_twin_id: UUID) -> None:
        async with self._hierarchy_lock:
            await self.get_digital_twin(parent_twin_id)
            await self.get_digital_twin(child_twin_id)
            if parent_twin_id not in self.twin_hierarchies:
                self.twin_hierarchies[parent_twin_id] = set()
            self.twin_hierarchies[parent_twin_id].add(child_twin_id)
            association = DigitalTwinAssociation(twin_id=parent_twin_id, associated_entity_id=child_twin_id, association_type='child_twin', entity_type='digital_twin')
            await self.add_association(association)
            logger.info(f'Added twin {child_twin_id} to hierarchy under {parent_twin_id}')

    async def get_twin_children(self, parent_twin_id: UUID) -> List[IDigitalTwin]:
        child_ids = self.twin_hierarchies.get(parent_twin_id, set())
        children = []
        for child_id in child_ids:
            try:
                child_twin = await self.get_digital_twin(child_id)
                children.append(child_twin)
            except DigitalTwinNotFoundError:
                self.twin_hierarchies[parent_twin_id].discard(child_id)
        return children

    async def get_twin_hierarchy_tree(self, root_twin_id: UUID) -> Dict[str, Any]:
        try:
            root_twin = await self.get_digital_twin(root_twin_id)

            async def build_tree(twin_id: UUID) -> Dict[str, Any]:
                twin = await self.get_digital_twin(twin_id)
                children = await self.get_twin_children(twin_id)
                tree = {'twin_id': str(twin_id), 'name': twin.name, 'twin_type': twin.twin_type.value, 'current_state': twin.current_state.value, 'children': []}
                for child in children:
                    child_tree = await build_tree(child.id)
                    tree['children'].append(child_tree)
                return tree
            return await build_tree(root_twin_id)
        except DigitalTwinNotFoundError:
            return {'error': f'Twin {root_twin_id} not found'}

    async def register_model(self, model: TwinModel) -> None:
        self.model_registry[model.model_id] = model
        logger.info(f'Registered model {model.name} ({model.model_id})')

    async def get_model(self, model_id: UUID) -> TwinModel:
        if model_id not in self.model_registry:
            raise DigitalTwinError(f'Model {model_id} not found')
        return self.model_registry[model_id]

    async def find_models_by_type(self, model_type: str) -> List[TwinModel]:
        return [model for model in self.model_registry.values() if model.model_type.value == model_type]

    async def store_twin_snapshot(self, snapshot: TwinSnapshot) -> None:
        twin_id = snapshot.twin_id
        if twin_id not in self.twin_snapshots:
            self.twin_snapshots[twin_id] = []
        self.twin_snapshots[twin_id].append(snapshot)
        if len(self.twin_snapshots[twin_id]) > 10:
            self.twin_snapshots[twin_id] = self.twin_snapshots[twin_id][-10:]
        async with self._performance_lock:
            self.twin_performance_metrics.record_activity('snapshot', twin_id, snapshot.twin_id)
        logger.info(f'Stored snapshot for twin {twin_id}')

    async def get_twin_snapshots(self, twin_id: UUID, limit: Optional[int]=None) -> List[TwinSnapshot]:
        snapshots = self.twin_snapshots.get(twin_id, [])
        snapshots.sort(key=lambda s: s.snapshot_time, reverse=True)
        if limit:
            snapshots = snapshots[:limit]
        return snapshots

    async def record_twin_activity(self, twin_id: UUID, activity_type: str, activity_data: Optional[Dict[str, Any]]=None) -> None:
        try:
            twin = await self.get_digital_twin(twin_id)
            async with self._performance_lock:
                self.twin_performance_metrics.record_activity(activity_type, twin_id, twin.twin_type)
            if activity_data and 'associated_entity_id' in activity_data:
                associated_id = UUID(activity_data['associated_entity_id'])
                for association in self.twin_associations.values():
                    if association.twin_id == twin_id and association.associated_entity_id == associated_id:
                        association.update_interaction()
                        break
        except DigitalTwinNotFoundError:
            logger.warning(f'Activity recorded for non-existent twin {twin_id}')

    async def discover_twins_advanced(self, criteria: Dict[str, Any]) -> List[IDigitalTwin]:
        filters = {}
        if 'type' in criteria:
            filters['twin_type'] = criteria['type']
        if 'digital_twin_id' in criteria:
            filters['id'] = criteria['digital_twin_id']
        twins = await self.list(filters=filters)
        if 'has_capability' in criteria:
            required_capability = TwinCapability(criteria['has_capability'])
            twins = [t for t in twins if required_capability in t.capabilities]
        if 'model_type' in criteria:
            model_type = criteria['model_type']
            filtered_twins = []
            for twin in twins:
                for model in twin.integrated_models:
                    if model.model_type.value == model_type:
                        filtered_twins.append(twin)
                        break
            twins = filtered_twins
        if 'has_associations' in criteria:
            association_type = criteria['has_associations']
            filtered_twins = []
            for twin in twins:
                associations = await self.get_twin_associations(twin.id, association_type)
                if associations:
                    filtered_twins.append(twin)
            twins = filtered_twins
        if 'in_hierarchy' in criteria:
            parent_id = UUID(criteria['in_hierarchy'])
            children = await self.get_twin_children(parent_id)
            child_ids = set((child.id for child in children))
            twins = [t for t in twins if t.id in child_ids]
        if 'min_model_count' in criteria:
            min_count = criteria['min_model_count']
            twins = [t for t in twins if len(t.integrated_models) >= min_count]
        return twins

    async def get_twin_performance_summary(self, twin_id: UUID) -> Dict[str, Any]:
        try:
            twin = await self.get_digital_twin(twin_id)
            performance = await twin.get_performance_metrics()
            associations = await self.get_twin_associations(twin_id)
            snapshots = await self.get_twin_snapshots(twin_id, limit=5)
            children = await self.get_twin_children(twin_id)
            return {'twin_id': str(twin_id), 'name': twin.name, 'twin_type': twin.twin_type.value, 'current_state': twin.current_state.value, 'performance': performance, 'associations': {'total': len(associations), 'by_type': {}}, 'hierarchy': {'children_count': len(children), 'children': [str(child.id) for child in children]}, 'snapshots': {'total': len(self.twin_snapshots.get(twin_id, [])), 'recent': [s.to_dict() for s in snapshots]}, 'models': {'count': len(twin.integrated_models), 'types': list(set((model.model_type.value for model in twin.integrated_models)))}}
        except DigitalTwinNotFoundError:
            return {'error': f'Twin {twin_id} not found'}

    async def get_registry_analytics(self) -> Dict[str, Any]:
        all_twins = await self.list()
        analytics = {'total_twins': len(all_twins), 'twins_by_type': {}, 'twins_by_state': {}, 'capabilities_distribution': {}, 'model_statistics': {}, 'association_statistics': {}, 'hierarchy_statistics': {}, 'performance_metrics': self.twin_performance_metrics.to_dict()}
        for twin in all_twins:
            twin_type = twin.twin_type.value
            twin_state = twin.current_state.value
            analytics['twins_by_type'][twin_type] = analytics['twins_by_type'].get(twin_type, 0) + 1
            analytics['twins_by_state'][twin_state] = analytics['twins_by_state'].get(twin_state, 0) + 1
            for capability in twin.capabilities:
                cap_name = capability.value
                analytics['capabilities_distribution'][cap_name] = analytics['capabilities_distribution'].get(cap_name, 0) + 1
        all_models = list(self.model_registry.values())
        analytics['model_statistics'] = {'total_models': len(all_models), 'models_by_type': {}, 'average_models_per_twin': len(all_models) / max(len(all_twins), 1)}
        for model in all_models:
            model_type = model.model_type.value
            analytics['model_statistics']['models_by_type'][model_type] = analytics['model_statistics']['models_by_type'].get(model_type, 0) + 1
        analytics['association_statistics'] = {'total_associations': len(self.twin_associations), 'associations_by_type': {}, 'associations_by_entity_type': {}}
        for association in self.twin_associations.values():
            assoc_type = association.association_type
            entity_type = association.entity_type
            analytics['association_statistics']['associations_by_type'][assoc_type] = analytics['association_statistics']['associations_by_type'].get(assoc_type, 0) + 1
            analytics['association_statistics']['associations_by_entity_type'][entity_type] = analytics['association_statistics']['associations_by_entity_type'].get(entity_type, 0) + 1
        analytics['hierarchy_statistics'] = {'hierarchies_count': len(self.twin_hierarchies), 'total_parent_twins': len(self.twin_hierarchies), 'total_child_relationships': sum((len(children) for children in self.twin_hierarchies.values())), 'average_children_per_parent': sum((len(children) for children in self.twin_hierarchies.values())) / max(len(self.twin_hierarchies), 1)}
        return analytics

    async def optimize_registry_performance(self) -> Dict[str, Any]:
        optimization_results = {'cache_optimization': {}, 'data_cleanup': {}, 'performance_improvements': {}}
        if self.cache_enabled:
            cache_size_before = self.cache.size() if self.cache else 0
            await self.clear_cache()
            optimization_results['cache_optimization']['cache_cleared'] = cache_size_before
        snapshots_cleaned = 0
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
        for twin_id, snapshots in self.twin_snapshots.items():
            original_count = len(snapshots)
            self.twin_snapshots[twin_id] = [s for s in snapshots if s.snapshot_time > cutoff_date]
            snapshots_cleaned += original_count - len(self.twin_snapshots[twin_id])
        optimization_results['data_cleanup']['old_snapshots_removed'] = snapshots_cleaned
        stale_associations = []
        for key, association in list(self.twin_associations.items()):
            try:
                await self.get_digital_twin(association.twin_id)
            except DigitalTwinNotFoundError:
                stale_associations.append(key)
        for key in stale_associations:
            del self.twin_associations[key]
        optimization_results['data_cleanup']['stale_associations_removed'] = len(stale_associations)
        optimization_results['performance_improvements'] = {'total_twins': len(await self.list()), 'total_associations': len(self.twin_associations), 'total_models': len(self.model_registry), 'optimization_completed_at': datetime.now(timezone.utc).isoformat()}
        logger.info('Registry performance optimization completed')
        return optimization_results