import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID
import logging
from src.core.registry.base import AbstractRegistry, RegistryMetrics
from src.core.interfaces.base import IStorageAdapter
from src.core.interfaces.replica import IDigitalReplica, ReplicaType, DataAggregationMode, DeviceData, DataQuality
from src.utils.exceptions import DigitalReplicaError, DigitalReplicaNotFoundError, EntityNotFoundError, RegistryError
logger = logging.getLogger(__name__)

class DeviceAssociation:

    def __init__(self, device_id: str, replica_id: UUID, association_type: str='managed', created_at: Optional[datetime]=None, metadata: Optional[Dict[str, Any]]=None):
        self.device_id = device_id
        self.replica_id = replica_id
        self.association_type = association_type
        self.created_at = created_at or datetime.now(timezone.utc)
        self.metadata = metadata or {}
        self.last_data_timestamp: Optional[datetime] = None
        self.data_count = 0
        self.quality_history: List[Tuple[datetime, DataQuality]] = []

    def update_data_received(self, quality: DataQuality) -> None:
        self.last_data_timestamp = datetime.now(timezone.utc)
        self.data_count += 1
        self.quality_history.append((self.last_data_timestamp, quality))
        if len(self.quality_history) > 100:
            self.quality_history = self.quality_history[-100:]

    def get_average_quality_score(self) -> float:
        if not self.quality_history:
            return 0.5
        quality_scores = {DataQuality.HIGH: 1.0, DataQuality.MEDIUM: 0.7, DataQuality.LOW: 0.4, DataQuality.INVALID: 0.0, DataQuality.UNKNOWN: 0.5}
        scores = [quality_scores.get(quality, 0.5) for _, quality in self.quality_history]
        return sum(scores) / len(scores)

    def to_dict(self) -> Dict[str, Any]:
        return {'device_id': self.device_id, 'replica_id': str(self.replica_id), 'association_type': self.association_type, 'created_at': self.created_at.isoformat(), 'last_data_timestamp': self.last_data_timestamp.isoformat() if self.last_data_timestamp else None, 'data_count': self.data_count, 'average_quality_score': self.get_average_quality_score(), 'metadata': self.metadata}

class DataFlowMetrics:

    def __init__(self):
        self.total_data_points = 0
        self.data_by_device: Dict[str, int] = {}
        self.data_by_replica: Dict[UUID, int] = {}
        self.data_by_quality: Dict[DataQuality, int] = {}
        self.aggregations_performed = 0
        self.last_data_timestamp: Optional[datetime] = None
        self.data_rate_per_minute = 0.0
        self._data_timestamps: List[datetime] = []

    def record_data_point(self, device_id: str, replica_id: UUID, quality: DataQuality) -> None:
        now = datetime.now(timezone.utc)
        self.total_data_points += 1
        self.data_by_device[device_id] = self.data_by_device.get(device_id, 0) + 1
        self.data_by_replica[replica_id] = self.data_by_replica.get(replica_id, 0) + 1
        self.data_by_quality[quality] = self.data_by_quality.get(quality, 0) + 1
        self.last_data_timestamp = now
        self._data_timestamps.append(now)
        cutoff = now - timedelta(hours=1)
        self._data_timestamps = [ts for ts in self._data_timestamps if ts > cutoff]
        if len(self._data_timestamps) > 1:
            time_span = (self._data_timestamps[-1] - self._data_timestamps[0]).total_seconds() / 60
            self.data_rate_per_minute = len(self._data_timestamps) / max(time_span, 1)

    def record_aggregation(self) -> None:
        self.aggregations_performed += 1

    def get_quality_distribution(self) -> Dict[str, float]:
        if self.total_data_points == 0:
            return {}
        return {quality.value: count / self.total_data_points for quality, count in self.data_by_quality.items()}

    def to_dict(self) -> Dict[str, Any]:
        return {'total_data_points': self.total_data_points, 'devices_count': len(self.data_by_device), 'replicas_count': len(self.data_by_replica), 'aggregations_performed': self.aggregations_performed, 'data_rate_per_minute': self.data_rate_per_minute, 'quality_distribution': self.get_quality_distribution(), 'last_data_timestamp': self.last_data_timestamp.isoformat() if self.last_data_timestamp else None, 'top_devices': sorted(self.data_by_device.items(), key=lambda x: x[1], reverse=True)[:10]}

class DigitalReplicaMetrics(RegistryMetrics):

    def __init__(self):
        super().__init__()
        self.replicas_by_type: Dict[str, int] = {}
        self.replicas_by_mode: Dict[str, int] = {}
        self.total_devices_managed = 0
        self.active_replicas = 0
        self.data_flow_metrics = DataFlowMetrics()

    def update_replica_statistics(self, replica_type: ReplicaType, aggregation_mode: DataAggregationMode, device_count: int, is_active: bool) -> None:
        type_key = replica_type.value
        self.replicas_by_type[type_key] = self.replicas_by_type.get(type_key, 0) + 1
        mode_key = aggregation_mode.value
        self.replicas_by_mode[mode_key] = self.replicas_by_mode.get(mode_key, 0) + 1
        self.total_devices_managed += device_count
        if is_active:
            self.active_replicas += 1

    def to_dict(self) -> Dict[str, Any]:
        base_metrics = super().to_dict()
        base_metrics.update({'replicas_by_type': self.replicas_by_type, 'replicas_by_mode': self.replicas_by_mode, 'total_devices_managed': self.total_devices_managed, 'active_replicas': self.active_replicas, 'data_flow_metrics': self.data_flow_metrics.to_dict()})
        return base_metrics

class DigitalReplicaRegistry(AbstractRegistry[IDigitalReplica]):

    def __init__(self, storage_adapter: IStorageAdapter[IDigitalReplica], cache_enabled: bool=True, cache_size: int=1000, cache_ttl: int=300):
        super().__init__(entity_type=IDigitalReplica, storage_adapter=storage_adapter, cache_enabled=cache_enabled, cache_size=cache_size, cache_ttl=cache_ttl)
        self.device_associations: Dict[str, DeviceAssociation] = {}
        self.replica_to_devices: Dict[UUID, Set[str]] = {}
        self.digital_twin_replicas: Dict[UUID, Set[UUID]] = {}
        self.metrics = DigitalReplicaMetrics()
        self._association_lock = asyncio.Lock()
        self._flow_lock = asyncio.Lock()

    async def register_digital_replica(self, replica: IDigitalReplica, device_associations: Optional[List[DeviceAssociation]]=None) -> None:
        await self.register(replica)
        if device_associations:
            for association in device_associations:
                await self.associate_device(association)
        else:
            for device_id in replica.device_ids:
                association = DeviceAssociation(device_id=device_id, replica_id=replica.id, association_type='managed')
                await self.associate_device(association)
        dt_id = replica.parent_digital_twin_id
        if dt_id not in self.digital_twin_replicas:
            self.digital_twin_replicas[dt_id] = set()
        self.digital_twin_replicas[dt_id].add(replica.id)

    async def get_digital_replica(self, replica_id: UUID) -> IDigitalReplica:
        try:
            return await self.get(replica_id)
        except EntityNotFoundError:
            raise DigitalReplicaNotFoundError(replica_id=str(replica_id))

    async def find_replicas_by_type(self, replica_type: ReplicaType) -> List[IDigitalReplica]:
        filters = {'replica_type': replica_type.value}
        return await self.list(filters=filters)

    async def find_replicas_by_digital_twin(self, digital_twin_id: UUID) -> List[IDigitalReplica]:
        replica_ids = self.digital_twin_replicas.get(digital_twin_id, set())
        replicas = []
        for replica_id in replica_ids:
            try:
                replica = await self.get_digital_replica(replica_id)
                replicas.append(replica)
            except DigitalReplicaNotFoundError:
                self.digital_twin_replicas[digital_twin_id].discard(replica_id)
        return replicas

    async def find_replicas_by_device(self, device_id: str) -> List[IDigitalReplica]:
        replicas = []
        for association in self.device_associations.values():
            if association.device_id == device_id:
                try:
                    replica = await self.get_digital_replica(association.replica_id)
                    replicas.append(replica)
                except DigitalReplicaNotFoundError:
                    await self.disassociate_device(device_id, association.replica_id)
        return replicas

    async def associate_device(self, association: DeviceAssociation) -> None:
        async with self._association_lock:
            await self.get_digital_replica(association.replica_id)
            key = f'{association.device_id}:{association.replica_id}'
            self.device_associations[key] = association
            if association.replica_id not in self.replica_to_devices:
                self.replica_to_devices[association.replica_id] = set()
            self.replica_to_devices[association.replica_id].add(association.device_id)
            self.logger.info(f'Associated device {association.device_id} with replica {association.replica_id}')

    async def disassociate_device(self, device_id: str, replica_id: UUID) -> bool:
        async with self._association_lock:
            key = f'{device_id}:{replica_id}'
            if key in self.device_associations:
                del self.device_associations[key]
                if replica_id in self.replica_to_devices:
                    self.replica_to_devices[replica_id].discard(device_id)
                    if not self.replica_to_devices[replica_id]:
                        del self.replica_to_devices[replica_id]
                self.logger.info(f'Disassociated device {device_id} from replica {replica_id}')
                return True
            return False

    async def get_device_associations(self, device_id: str) -> List[DeviceAssociation]:
        associations = []
        for association in self.device_associations.values():
            if association.device_id == device_id:
                associations.append(association)
        return associations

    async def get_replica_devices(self, replica_id: UUID) -> List[str]:
        return list(self.replica_to_devices.get(replica_id, set()))

    async def record_device_data(self, device_id: str, replica_id: UUID, data_quality: DataQuality) -> None:
        async with self._flow_lock:
            key = f'{device_id}:{replica_id}'
            if key in self.device_associations:
                self.device_associations[key].update_data_received(data_quality)
            self.metrics.data_flow_metrics.record_data_point(device_id, replica_id, data_quality)

    async def record_aggregation(self, replica_id: UUID) -> None:
        async with self._flow_lock:
            self.metrics.data_flow_metrics.record_aggregation()

    async def get_data_flow_statistics(self, time_window_hours: int=24) -> Dict[str, Any]:
        return {'time_window_hours': time_window_hours, 'metrics': self.metrics.data_flow_metrics.to_dict(), 'device_count': len(set((assoc.device_id for assoc in self.device_associations.values()))), 'replica_count': len(self.replica_to_devices), 'associations_count': len(self.device_associations)}

    async def get_replica_performance(self, replica_id: UUID) -> Dict[str, Any]:
        try:
            replica = await self.get_digital_replica(replica_id)
            devices = await self.get_replica_devices(replica_id)
            associations = []
            for device_id in devices:
                key = f'{device_id}:{replica_id}'
                if key in self.device_associations:
                    associations.append(self.device_associations[key])
            total_data = sum((assoc.data_count for assoc in associations))
            avg_quality = sum((assoc.get_average_quality_score() for assoc in associations)) / len(associations) if associations else 0
            return {'replica_id': str(replica_id), 'replica_type': replica.replica_type.value, 'device_count': len(devices), 'total_data_received': total_data, 'average_quality_score': avg_quality, 'associations': [assoc.to_dict() for assoc in associations], 'aggregation_stats': await replica.get_aggregation_statistics()}
        except DigitalReplicaNotFoundError:
            return {'error': f'Replica {replica_id} not found'}

    async def discover_replicas(self, criteria: Dict[str, Any]) -> List[IDigitalReplica]:
        filters = {}
        if 'type' in criteria:
            filters['replica_type'] = criteria['type']
        if 'aggregation_mode' in criteria:
            filters['aggregation_mode'] = criteria['aggregation_mode']
        if 'parent_digital_twin_id' in criteria:
            filters['parent_digital_twin_id'] = criteria['parent_digital_twin_id']
        replicas = await self.list(filters=filters)
        if 'min_device_count' in criteria:
            min_devices = criteria['min_device_count']
            replicas = [r for r in replicas if len(r.device_ids) >= min_devices]
        if 'quality_threshold' in criteria:
            threshold = criteria['quality_threshold']
            filtered_replicas = []
            for replica in replicas:
                devices = await self.get_replica_devices(replica.id)
                if devices:
                    associations = []
                    for device_id in devices:
                        key = f'{device_id}:{replica.id}'
                        if key in self.device_associations:
                            associations.append(self.device_associations[key])
                    if associations:
                        avg_quality = sum((assoc.get_average_quality_score() for assoc in associations)) / len(associations)
                        if avg_quality >= threshold:
                            filtered_replicas.append(replica)
            replicas = filtered_replicas
        return replicas

    async def _post_register_hook(self, entity: IDigitalReplica) -> None:
        from src.core.interfaces.base import EntityStatus
        self.metrics.update_replica_statistics(replica_type=entity.replica_type, aggregation_mode=entity.aggregation_mode, device_count=len(entity.device_ids), is_active=entity.status == EntityStatus.ACTIVE)

    async def _pre_unregister_hook(self, entity: IDigitalReplica) -> None:
        replica_id = entity.id
        devices_to_remove = await self.get_replica_devices(replica_id)
        for device_id in devices_to_remove:
            await self.disassociate_device(device_id, replica_id)
        dt_id = entity.parent_digital_twin_id
        if dt_id in self.digital_twin_replicas:
            self.digital_twin_replicas[dt_id].discard(replica_id)
            if not self.digital_twin_replicas[dt_id]:
                del self.digital_twin_replicas[dt_id]