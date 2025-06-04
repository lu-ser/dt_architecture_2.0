import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type
from uuid import UUID, uuid4
from src.core.interfaces.base import BaseMetadata, EntityStatus
from src.core.interfaces.replica import IDigitalReplica, IReplicaFactory, IDataAggregator, ReplicaType, ReplicaConfiguration, DataAggregationMode, DataQuality, DeviceData, AggregatedData
from src.utils.exceptions import FactoryError, FactoryConfigurationError, EntityCreationError, InvalidConfigurationError
from src.utils.config import get_config
logger = logging.getLogger(__name__)

class StandardDataAggregator(IDataAggregator):

    def __init__(self, aggregation_method: str='average'):
        self._aggregation_method = aggregation_method
        self._config: Dict[str, Any] = {}

    @property
    def aggregation_method(self) -> str:
        return self._aggregation_method

    async def configure(self, config: Dict[str, Any]) -> None:
        self._config = config
        if 'method' in config:
            self._aggregation_method = config['method']

    async def aggregate(self, data_batch: List[DeviceData], context: Optional[Dict[str, Any]]=None) -> AggregatedData:
        if not data_batch:
            raise ValueError('Cannot aggregate empty data batch')
        device_ids = list(set((d.device_id for d in data_batch)))
        aggregated_values = {}
        quality_scores = []
        for data in data_batch:
            quality_scores.append(self._quality_to_score(data.quality))
            for key, value in data.data.items():
                if key not in aggregated_values:
                    aggregated_values[key] = []
                if isinstance(value, (int, float)):
                    aggregated_values[key].append(value)
        final_data = {}
        for key, values in aggregated_values.items():
            if self._aggregation_method == 'average':
                final_data[key] = sum(values) / len(values) if values else 0
            elif self._aggregation_method == 'sum':
                final_data[key] = sum(values)
            elif self._aggregation_method == 'max':
                final_data[key] = max(values) if values else 0
            elif self._aggregation_method == 'min':
                final_data[key] = min(values) if values else 0
            else:
                final_data[key] = values[-1] if values else 0
        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.5
        return AggregatedData(source_replica_id=uuid4(), aggregation_timestamp=datetime.now(timezone.utc), aggregated_data=final_data, source_count=len(data_batch), aggregation_method=self._aggregation_method, quality_score=avg_quality)

    def validate_data(self, device_data: DeviceData) -> DataQuality:
        if not device_data.data:
            return DataQuality.INVALID
        null_count = sum((1 for v in device_data.data.values() if v is None))
        null_ratio = null_count / len(device_data.data)
        if null_ratio > 0.5:
            return DataQuality.INVALID
        elif null_ratio > 0.2:
            return DataQuality.LOW
        elif null_ratio > 0.1:
            return DataQuality.MEDIUM
        else:
            return DataQuality.HIGH

    def can_aggregate(self, data_batch: List[DeviceData]) -> bool:
        if not data_batch:
            return False
        high_quality_count = sum((1 for data in data_batch if self.validate_data(data) in [DataQuality.HIGH, DataQuality.MEDIUM]))
        quality_ratio = high_quality_count / len(data_batch)
        return quality_ratio >= 0.6

    def _quality_to_score(self, quality: DataQuality) -> float:
        quality_map = {DataQuality.HIGH: 1.0, DataQuality.MEDIUM: 0.7, DataQuality.LOW: 0.4, DataQuality.INVALID: 0.0, DataQuality.UNKNOWN: 0.5}
        return quality_map.get(quality, 0.5)

class DigitalReplica(IDigitalReplica):

    def __init__(self, replica_id: UUID, configuration: ReplicaConfiguration, metadata: BaseMetadata, aggregator: IDataAggregator):
        self._id = replica_id
        self._configuration = configuration
        self._metadata = metadata
        self._aggregator = aggregator
        self._status = EntityStatus.CREATED
        self._pending_data: List[DeviceData] = []
        self._data_lock = asyncio.Lock()
        self._data_received_count = 0
        self._aggregations_performed = 0
        self._last_aggregation_time: Optional[datetime] = None

    @property
    def id(self) -> UUID:
        return self._id

    @property
    def metadata(self) -> BaseMetadata:
        return self._metadata

    @property
    def status(self):
        from src.core.interfaces.base import EntityStatus
        return self._status

    @property
    def replica_type(self) -> ReplicaType:
        return self._configuration.replica_type

    @property
    def parent_digital_twin_id(self) -> UUID:
        return self._configuration.parent_digital_twin_id

    @property
    def device_ids(self) -> List[str]:
        return self._configuration.device_ids.copy()

    @property
    def configuration(self) -> ReplicaConfiguration:
        return self._configuration

    @property
    def aggregation_mode(self) -> DataAggregationMode:
        return self._configuration.aggregation_mode

    async def initialize(self) -> None:
        from src.core.interfaces.base import EntityStatus
        self._status = EntityStatus.INITIALIZING
        await self._aggregator.configure(self._configuration.aggregation_config)
        self._status = EntityStatus.ACTIVE
        logger.info(f'Digital Replica {self._id} initialized')

    async def start(self) -> None:
        from src.core.interfaces.base import EntityStatus
        self._status = EntityStatus.ACTIVE
        logger.info(f'Digital Replica {self._id} started')

    async def stop(self) -> None:
        from src.core.interfaces.base import EntityStatus
        self._status = EntityStatus.INACTIVE
        logger.info(f'Digital Replica {self._id} stopped')

    async def terminate(self) -> None:
        from src.core.interfaces.base import EntityStatus
        await self.stop()
        self._status = EntityStatus.TERMINATED
        logger.info(f'Digital Replica {self._id} terminated')

    async def receive_device_data(self, device_data: DeviceData) -> None:
        if device_data.device_id not in self._configuration.device_ids:
            logger.warning(f'Received data from unknown device {device_data.device_id}')
            return
        quality = self._aggregator.validate_data(device_data)
        device_data.quality = quality
        async with self._data_lock:
            self._pending_data.append(device_data)
            self._data_received_count += 1
        await self._check_aggregation_trigger()

    async def aggregate_data(self, data_batch: List[DeviceData], force_aggregation: bool=False) -> Optional[AggregatedData]:
        if not data_batch and (not force_aggregation):
            return None
        if not force_aggregation and (not self._aggregator.can_aggregate(data_batch)):
            logger.debug(f'Data quality too low for aggregation in replica {self._id}')
            return None
        try:
            aggregated = await self._aggregator.aggregate(data_batch)
            aggregated.source_replica_id = self._id
            self._aggregations_performed += 1
            self._last_aggregation_time = datetime.now(timezone.utc)
            logger.debug(f'Aggregated {len(data_batch)} data points in replica {self._id}')
            return aggregated
        except Exception as e:
            logger.error(f'Aggregation failed in replica {self._id}: {e}')
            return None

    async def send_to_digital_twin(self, aggregated_data: AggregatedData) -> None:
        logger.info(f'Sending aggregated data from replica {self._id} to Digital Twin {self._configuration.parent_digital_twin_id}')

    async def add_device(self, device_id: str) -> None:
        if device_id not in self._configuration.device_ids:
            self._configuration.device_ids.append(device_id)
            logger.info(f'Added device {device_id} to replica {self._id}')

    async def remove_device(self, device_id: str) -> None:
        if device_id in self._configuration.device_ids:
            self._configuration.device_ids.remove(device_id)
            logger.info(f'Removed device {device_id} from replica {self._id}')

    async def update_configuration(self, new_config: ReplicaConfiguration) -> None:
        old_config = self._configuration
        self._configuration = new_config
        if old_config.aggregation_config != new_config.aggregation_config:
            await self._aggregator.configure(new_config.aggregation_config)
        logger.info(f'Updated configuration for replica {self._id}')

    async def get_data_quality_report(self, start_time: Optional[datetime]=None, end_time: Optional[datetime]=None) -> Dict[str, Any]:
        return {'replica_id': str(self._id), 'total_data_received': self._data_received_count, 'aggregations_performed': self._aggregations_performed, 'last_aggregation': self._last_aggregation_time.isoformat() if self._last_aggregation_time else None, 'pending_data_count': len(self._pending_data), 'device_count': len(self._configuration.device_ids)}

    async def get_aggregation_statistics(self) -> Dict[str, Any]:
        return {'aggregation_method': self._aggregator.aggregation_method, 'total_aggregations': self._aggregations_performed, 'data_received': self._data_received_count, 'aggregation_ratio': self._aggregations_performed / max(self._data_received_count, 1), 'last_aggregation': self._last_aggregation_time.isoformat() if self._last_aggregation_time else None}

    def to_dict(self) -> Dict[str, Any]:
        return {'id': str(self._id), 'replica_type': self._configuration.replica_type.value, 'parent_digital_twin_id': str(self._configuration.parent_digital_twin_id), 'device_ids': self._configuration.device_ids, 'aggregation_mode': self._configuration.aggregation_mode.value, 'status': self._status.value, 'metadata': self._metadata.to_dict(), 'statistics': {'data_received': self._data_received_count, 'aggregations_performed': self._aggregations_performed}}

    def validate(self) -> bool:
        if not self._configuration.device_ids:
            return False
        if not self._configuration.parent_digital_twin_id:
            return False
        return True

    async def _check_aggregation_trigger(self) -> None:
        async with self._data_lock:
            should_aggregate = False
            if self._configuration.aggregation_mode == DataAggregationMode.REAL_TIME:
                should_aggregate = len(self._pending_data) > 0
            elif self._configuration.aggregation_mode == DataAggregationMode.BATCH:
                batch_size = self._configuration.aggregation_config.get('batch_size', 10)
                should_aggregate = len(self._pending_data) >= batch_size
            elif self._configuration.aggregation_mode == DataAggregationMode.WINDOW:
                window_seconds = self._configuration.aggregation_config.get('window_seconds', 60)
                if self._last_aggregation_time:
                    time_since_last = (datetime.now(timezone.utc) - self._last_aggregation_time).total_seconds()
                    should_aggregate = time_since_last >= window_seconds and len(self._pending_data) > 0
                else:
                    should_aggregate = len(self._pending_data) > 0
            if should_aggregate:
                data_to_process = self._pending_data.copy()
                self._pending_data.clear()
                aggregated = await self.aggregate_data(data_to_process)
                if aggregated:
                    await self.send_to_digital_twin(aggregated)

class DigitalReplicaFactory(IReplicaFactory):

    def __init__(self):
        self.config = get_config()
        self._supported_types = list(ReplicaType)
        self._aggregator_registry: Dict[str, Type[IDataAggregator]] = {'standard': StandardDataAggregator}

    async def create(self, config: Dict[str, Any], metadata: Optional[BaseMetadata]=None) -> IDigitalReplica:
        try:
            if not self.validate_config(config):
                raise FactoryConfigurationError('Invalid Digital Replica configuration')
            replica_type = ReplicaType(config['replica_type'])
            parent_twin_id_raw = config['parent_digital_twin_id']
            if isinstance(parent_twin_id_raw, UUID):
                parent_dt_id = parent_twin_id_raw
            elif isinstance(parent_twin_id_raw, str):
                parent_dt_id = UUID(parent_twin_id_raw)
            else:
                raise FactoryConfigurationError(f'Invalid parent_digital_twin_id type: {type(parent_twin_id_raw)}')
            device_ids = config['device_ids']
            aggregation_mode = DataAggregationMode(config['aggregation_mode'])
            replica_config = ReplicaConfiguration(replica_type=replica_type, parent_digital_twin_id=parent_dt_id, device_ids=device_ids, aggregation_mode=aggregation_mode, aggregation_config=config.get('aggregation_config', {}), data_retention_policy=config.get('data_retention_policy', {}), quality_thresholds=config.get('quality_thresholds', {}), custom_config=config.get('custom_config', {}))
            if metadata is None:
                metadata = BaseMetadata(entity_id=uuid4(), timestamp=datetime.now(timezone.utc), version='1.0.0', created_by=uuid4())
            aggregator_type = config.get('aggregator_type', 'standard')
            aggregator_class = self._aggregator_registry.get(aggregator_type, StandardDataAggregator)
            aggregator = aggregator_class()
            replica = DigitalReplica(replica_id=metadata.id, configuration=replica_config, metadata=metadata, aggregator=aggregator)
            logger.info(f'Created Digital Replica {metadata.id} of type {replica_type}')
            return replica
        except Exception as e:
            logger.error(f'Failed to create Digital Replica: {e}')
            raise EntityCreationError(f'Digital Replica creation failed: {e}')

    async def create_replica(self, replica_type: ReplicaType, parent_digital_twin_id: UUID, config: ReplicaConfiguration, metadata: Optional[BaseMetadata]=None) -> IDigitalReplica:
        config_dict = {'replica_type': replica_type.value, 'parent_digital_twin_id': str(parent_digital_twin_id), 'device_ids': config.device_ids, 'aggregation_mode': config.aggregation_mode.value, 'aggregation_config': config.aggregation_config, 'data_retention_policy': config.data_retention_policy, 'quality_thresholds': config.quality_thresholds, 'custom_config': config.custom_config}
        return await self.create(config_dict, metadata)

    async def create_from_template(self, template_id: str, config_overrides: Optional[Dict[str, Any]]=None, metadata: Optional[BaseMetadata]=None) -> IDigitalReplica:
        template = self._get_template(template_id)
        if not template:
            raise FactoryConfigurationError(f'Template {template_id} not found')
        final_config = template.copy()
        if config_overrides:
            final_config.update(config_overrides)
        return await self.create(final_config, metadata)

    def get_supported_replica_types(self) -> List[ReplicaType]:
        return self._supported_types.copy()

    def get_default_configuration(self, replica_type: ReplicaType) -> ReplicaConfiguration:
        default_configs = {ReplicaType.SENSOR_AGGREGATOR: {'aggregation_mode': DataAggregationMode.BATCH, 'aggregation_config': {'batch_size': 10, 'method': 'average'}, 'data_retention_policy': {'retention_days': 30}, 'quality_thresholds': {'min_quality': 0.6}}, ReplicaType.DEVICE_PROXY: {'aggregation_mode': DataAggregationMode.REAL_TIME, 'aggregation_config': {'method': 'latest'}, 'data_retention_policy': {'retention_days': 7}, 'quality_thresholds': {'min_quality': 0.8}}}
        config_dict = default_configs.get(replica_type, default_configs[ReplicaType.SENSOR_AGGREGATOR])
        return ReplicaConfiguration(replica_type=replica_type, parent_digital_twin_id=uuid4(), device_ids=[], aggregation_mode=DataAggregationMode(config_dict['aggregation_mode']), aggregation_config=config_dict['aggregation_config'], data_retention_policy=config_dict['data_retention_policy'], quality_thresholds=config_dict['quality_thresholds'])

    def validate_replica_config(self, replica_type: ReplicaType, config: ReplicaConfiguration) -> bool:
        try:
            if config.replica_type != replica_type:
                return False
            if not config.device_ids:
                return False
            if not config.parent_digital_twin_id:
                return False
            if replica_type == ReplicaType.DEVICE_PROXY and len(config.device_ids) != 1:
                return False
            return True
        except Exception:
            return False

    def validate_config(self, config: Dict[str, Any]) -> bool:
        required_fields = ['replica_type', 'parent_digital_twin_id', 'device_ids', 'aggregation_mode']
        for field in required_fields:
            if field not in config:
                return False
        try:
            ReplicaType(config['replica_type'])
            DataAggregationMode(config['aggregation_mode'])
            UUID(config['parent_digital_twin_id'])
            if not isinstance(config['device_ids'], list) or not config['device_ids']:
                return False
            return True
        except (ValueError, TypeError):
            return False

    def get_supported_types(self) -> List[str]:
        return [rt.value for rt in self._supported_types]

    def get_config_schema(self, entity_type: str) -> Dict[str, Any]:
        return {'type': 'object', 'properties': {'replica_type': {'type': 'string', 'enum': [rt.value for rt in ReplicaType]}, 'parent_digital_twin_id': {'type': 'string', 'format': 'uuid'}, 'device_ids': {'type': 'array', 'items': {'type': 'string'}}, 'aggregation_mode': {'type': 'string', 'enum': [am.value for am in DataAggregationMode]}, 'aggregation_config': {'type': 'object'}, 'data_retention_policy': {'type': 'object'}, 'quality_thresholds': {'type': 'object'}, 'custom_config': {'type': 'object'}}, 'required': ['replica_type', 'parent_digital_twin_id', 'device_ids', 'aggregation_mode']}

    def register_aggregator(self, name: str, aggregator_class: Type[IDataAggregator]) -> None:
        self._aggregator_registry[name] = aggregator_class
        logger.info(f'Registered aggregator type: {name}')

    def _get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        templates = {'iot_sensor': {'replica_type': ReplicaType.SENSOR_AGGREGATOR.value, 'aggregation_mode': DataAggregationMode.BATCH.value, 'aggregation_config': {'batch_size': 5, 'method': 'average'}, 'data_retention_policy': {'retention_days': 30}, 'quality_thresholds': {'min_quality': 0.7}}, 'industrial_device': {'replica_type': ReplicaType.DEVICE_PROXY.value, 'aggregation_mode': DataAggregationMode.REAL_TIME.value, 'aggregation_config': {'method': 'latest'}, 'data_retention_policy': {'retention_days': 90}, 'quality_thresholds': {'min_quality': 0.9}}}
        return templates.get(template_id)