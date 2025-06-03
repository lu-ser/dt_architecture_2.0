from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, Union, Callable
from uuid import UUID
from enum import Enum
from .base import IEntity, IFactory, ILifecycleManager, BaseMetadata

class DataAggregationMode(Enum):
    REAL_TIME = 'real_time'
    BATCH = 'batch'
    WINDOW = 'window'
    EVENT_DRIVEN = 'event_driven'
    HYBRID = 'hybrid'

class DataQuality(Enum):
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'
    INVALID = 'invalid'
    UNKNOWN = 'unknown'

class ReplicaType(Enum):
    SENSOR_AGGREGATOR = 'sensor_aggregator'
    DEVICE_PROXY = 'device_proxy'
    MULTI_DEVICE = 'multi_device'
    EDGE_GATEWAY = 'edge_gateway'
    DATA_PROCESSOR = 'data_processor'
    VIRTUAL_SENSOR = 'virtual_sensor'

class DeviceData:

    def __init__(self, device_id: str, timestamp: datetime, data: Dict[str, Any], data_type: str, quality: DataQuality=DataQuality.UNKNOWN, metadata: Optional[Dict[str, Any]]=None):
        self.device_id = device_id
        self.timestamp = timestamp
        self.data = data
        self.data_type = data_type
        self.quality = quality
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {'device_id': self.device_id, 'timestamp': self.timestamp.isoformat(), 'data': self.data, 'data_type': self.data_type, 'quality': self.quality.value, 'metadata': self.metadata}

class AggregatedData:

    def __init__(self, source_replica_id: UUID, aggregation_timestamp: datetime, aggregated_data: Dict[str, Any], source_count: int, aggregation_method: str, quality_score: float, metadata: Optional[Dict[str, Any]]=None):
        self.source_replica_id = source_replica_id
        self.aggregation_timestamp = aggregation_timestamp
        self.aggregated_data = aggregated_data
        self.source_count = source_count
        self.aggregation_method = aggregation_method
        self.quality_score = quality_score
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {'source_replica_id': str(self.source_replica_id), 'aggregation_timestamp': self.aggregation_timestamp.isoformat(), 'aggregated_data': self.aggregated_data, 'source_count': self.source_count, 'aggregation_method': self.aggregation_method, 'quality_score': self.quality_score, 'metadata': self.metadata}

class ReplicaConfiguration:

    def __init__(self, replica_type: ReplicaType, parent_digital_twin_id: UUID, device_ids: List[str], aggregation_mode: DataAggregationMode, aggregation_config: Dict[str, Any], data_retention_policy: Dict[str, Any], quality_thresholds: Dict[str, float], custom_config: Optional[Dict[str, Any]]=None):
        self.replica_type = replica_type
        self.parent_digital_twin_id = parent_digital_twin_id
        self.device_ids = device_ids
        self.aggregation_mode = aggregation_mode
        self.aggregation_config = aggregation_config
        self.data_retention_policy = data_retention_policy
        self.quality_thresholds = quality_thresholds
        self.custom_config = custom_config or {}

    def to_dict(self) -> Dict[str, Any]:
        return {'replica_type': self.replica_type.value, 'parent_digital_twin_id': str(self.parent_digital_twin_id), 'device_ids': self.device_ids, 'aggregation_mode': self.aggregation_mode.value, 'aggregation_config': self.aggregation_config, 'data_retention_policy': self.data_retention_policy, 'quality_thresholds': self.quality_thresholds, 'custom_config': self.custom_config}

class IDigitalReplica(IEntity):

    @property
    @abstractmethod
    def replica_type(self) -> ReplicaType:
        pass

    @property
    @abstractmethod
    def parent_digital_twin_id(self) -> UUID:
        pass

    @property
    @abstractmethod
    def device_ids(self) -> List[str]:
        pass

    @property
    @abstractmethod
    def configuration(self) -> ReplicaConfiguration:
        pass

    @property
    @abstractmethod
    def aggregation_mode(self) -> DataAggregationMode:
        pass

    @abstractmethod
    async def receive_device_data(self, device_data: DeviceData) -> None:
        pass

    @abstractmethod
    async def aggregate_data(self, data_batch: List[DeviceData], force_aggregation: bool=False) -> Optional[AggregatedData]:
        pass

    @abstractmethod
    async def send_to_digital_twin(self, aggregated_data: AggregatedData) -> None:
        pass

    @abstractmethod
    async def add_device(self, device_id: str) -> None:
        pass

    @abstractmethod
    async def remove_device(self, device_id: str) -> None:
        pass

    @abstractmethod
    async def update_configuration(self, new_config: ReplicaConfiguration) -> None:
        pass

    @abstractmethod
    async def get_data_quality_report(self, start_time: Optional[datetime]=None, end_time: Optional[datetime]=None) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_aggregation_statistics(self) -> Dict[str, Any]:
        pass

class IDataAggregator(ABC):

    @property
    @abstractmethod
    def aggregation_method(self) -> str:
        pass

    @abstractmethod
    async def configure(self, config: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def aggregate(self, data_batch: List[DeviceData], context: Optional[Dict[str, Any]]=None) -> AggregatedData:
        pass

    @abstractmethod
    def validate_data(self, device_data: DeviceData) -> DataQuality:
        pass

    @abstractmethod
    def can_aggregate(self, data_batch: List[DeviceData]) -> bool:
        pass

class IReplicaFactory(IFactory[IDigitalReplica]):

    @abstractmethod
    async def create_replica(self, replica_type: ReplicaType, parent_digital_twin_id: UUID, config: ReplicaConfiguration, metadata: Optional[BaseMetadata]=None) -> IDigitalReplica:
        pass

    @abstractmethod
    def get_supported_replica_types(self) -> List[ReplicaType]:
        pass

    @abstractmethod
    def get_default_configuration(self, replica_type: ReplicaType) -> ReplicaConfiguration:
        pass

    @abstractmethod
    def validate_replica_config(self, replica_type: ReplicaType, config: ReplicaConfiguration) -> bool:
        pass

class IReplicaLifecycleManager(ILifecycleManager[IDigitalReplica]):

    @abstractmethod
    async def deploy_replica(self, replica: IDigitalReplica, deployment_target: str) -> str:
        pass

    @abstractmethod
    async def scale_replica(self, replica_id: UUID, scale_factor: int) -> None:
        pass

    @abstractmethod
    async def migrate_replica(self, replica_id: UUID, target_location: str) -> None:
        pass

    @abstractmethod
    async def backup_replica_state(self, replica_id: UUID) -> str:
        pass

    @abstractmethod
    async def restore_replica_state(self, replica_id: UUID, backup_reference: str) -> None:
        pass
ReplicaEventHandler = Callable[[UUID, str, Dict[str, Any]], None]

class IReplicaEventBus(ABC):

    @abstractmethod
    async def publish_event(self, event_type: str, replica_id: UUID, event_data: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    def subscribe_to_events(self, event_types: List[str], handler: ReplicaEventHandler, replica_filter: Optional[List[UUID]]=None) -> str:
        pass

    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> None:
        pass