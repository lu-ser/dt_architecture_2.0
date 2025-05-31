"""
Digital Replica Factory implementation for the Digital Twin Platform.

This module provides the factory for creating Digital Replica instances
based on type and configuration, handling the complete instantiation process.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type
from uuid import UUID, uuid4

from src.core.interfaces.base import BaseMetadata, EntityStatus
from src.core.interfaces.replica import (
    IDigitalReplica,
    IReplicaFactory,
    IDataAggregator,
    ReplicaType,
    ReplicaConfiguration,
    DataAggregationMode,
    DataQuality,
    DeviceData,
    AggregatedData
)
from src.utils.exceptions import (
    FactoryError,
    FactoryConfigurationError,
    EntityCreationError,
    InvalidConfigurationError
)
from src.utils.config import get_config

logger = logging.getLogger(__name__)


class StandardDataAggregator(IDataAggregator):
    """Standard implementation of data aggregator."""
    
    def __init__(self, aggregation_method: str = "average"):
        self._aggregation_method = aggregation_method
        self._config: Dict[str, Any] = {}
    
    @property
    def aggregation_method(self) -> str:
        return self._aggregation_method
    
    async def configure(self, config: Dict[str, Any]) -> None:
        """Configure the aggregator with specific parameters."""
        self._config = config
        if "method" in config:
            self._aggregation_method = config["method"]
    
    async def aggregate(
        self,
        data_batch: List[DeviceData],
        context: Optional[Dict[str, Any]] = None
    ) -> AggregatedData:
        """Perform data aggregation on the provided batch."""
        if not data_batch:
            raise ValueError("Cannot aggregate empty data batch")
        
        # Validate all data has same device_id or is from compatible devices
        device_ids = list(set(d.device_id for d in data_batch))
        
        # Aggregate based on method
        aggregated_values = {}
        quality_scores = []
        
        for data in data_batch:
            quality_scores.append(self._quality_to_score(data.quality))
            for key, value in data.data.items():
                if key not in aggregated_values:
                    aggregated_values[key] = []
                if isinstance(value, (int, float)):
                    aggregated_values[key].append(value)
        
        # Apply aggregation method
        final_data = {}
        for key, values in aggregated_values.items():
            if self._aggregation_method == "average":
                final_data[key] = sum(values) / len(values) if values else 0
            elif self._aggregation_method == "sum":
                final_data[key] = sum(values)
            elif self._aggregation_method == "max":
                final_data[key] = max(values) if values else 0
            elif self._aggregation_method == "min":
                final_data[key] = min(values) if values else 0
            else:
                final_data[key] = values[-1] if values else 0  # Latest value
        
        # Calculate quality score
        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.5
        
        return AggregatedData(
            source_replica_id=uuid4(),  # Will be set by the replica
            aggregation_timestamp=datetime.now(timezone.utc),
            aggregated_data=final_data,
            source_count=len(data_batch),
            aggregation_method=self._aggregation_method,
            quality_score=avg_quality
        )
    
    def validate_data(self, device_data: DeviceData) -> DataQuality:
        """Validate the quality of incoming device data."""
        # Simple validation rules
        if not device_data.data:
            return DataQuality.INVALID
        
        # Check for null/None values
        null_count = sum(1 for v in device_data.data.values() if v is None)
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
        """Check if the current data batch can be aggregated."""
        if not data_batch:
            return False
        
        # Check minimum quality requirements
        high_quality_count = sum(
            1 for data in data_batch 
            if self.validate_data(data) in [DataQuality.HIGH, DataQuality.MEDIUM]
        )
        
        quality_ratio = high_quality_count / len(data_batch)
        return quality_ratio >= 0.6  # At least 60% good quality data
    
    def _quality_to_score(self, quality: DataQuality) -> float:
        """Convert quality enum to numeric score."""
        quality_map = {
            DataQuality.HIGH: 1.0,
            DataQuality.MEDIUM: 0.7,
            DataQuality.LOW: 0.4,
            DataQuality.INVALID: 0.0,
            DataQuality.UNKNOWN: 0.5
        }
        return quality_map.get(quality, 0.5)


class DigitalReplica(IDigitalReplica):
    """Standard implementation of Digital Replica."""
    
    def __init__(
        self,
        replica_id: UUID,
        configuration: ReplicaConfiguration,
        metadata: BaseMetadata,
        aggregator: IDataAggregator
    ):
        self._id = replica_id
        self._configuration = configuration
        self._metadata = metadata
        self._aggregator = aggregator
        self._status = EntityStatus.CREATED
        
        # Data storage
        self._pending_data: List[DeviceData] = []
        self._data_lock = asyncio.Lock()
        
        # Statistics
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
        """Initialize the replica."""
        from src.core.interfaces.base import EntityStatus
        self._status = EntityStatus.INITIALIZING
        
        # Configure aggregator
        await self._aggregator.configure(self._configuration.aggregation_config)
        
        self._status = EntityStatus.ACTIVE
        logger.info(f"Digital Replica {self._id} initialized")
    
    async def start(self) -> None:
        """Start the replica operations."""
        from src.core.interfaces.base import EntityStatus
        self._status = EntityStatus.ACTIVE
        logger.info(f"Digital Replica {self._id} started")
    
    async def stop(self) -> None:
        """Stop the replica operations."""
        from src.core.interfaces.base import EntityStatus
        self._status = EntityStatus.INACTIVE
        logger.info(f"Digital Replica {self._id} stopped")
    
    async def terminate(self) -> None:
        """Terminate the replica."""
        from src.core.interfaces.base import EntityStatus
        await self.stop()
        self._status = EntityStatus.TERMINATED
        logger.info(f"Digital Replica {self._id} terminated")
    
    async def receive_device_data(self, device_data: DeviceData) -> None:
        """Receive data from a physical device."""
        if device_data.device_id not in self._configuration.device_ids:
            logger.warning(f"Received data from unknown device {device_data.device_id}")
            return
        
        # Validate data quality
        quality = self._aggregator.validate_data(device_data)
        device_data.quality = quality
        
        async with self._data_lock:
            self._pending_data.append(device_data)
            self._data_received_count += 1
        
        # Check if we should trigger aggregation
        await self._check_aggregation_trigger()
    
    async def aggregate_data(
        self,
        data_batch: List[DeviceData],
        force_aggregation: bool = False
    ) -> Optional[AggregatedData]:
        """Aggregate device data according to the configured mode."""
        if not data_batch and not force_aggregation:
            return None
        
        if not force_aggregation and not self._aggregator.can_aggregate(data_batch):
            logger.debug(f"Data quality too low for aggregation in replica {self._id}")
            return None
        
        try:
            aggregated = await self._aggregator.aggregate(data_batch)
            aggregated.source_replica_id = self._id
            
            self._aggregations_performed += 1
            self._last_aggregation_time = datetime.now(timezone.utc)
            
            logger.debug(f"Aggregated {len(data_batch)} data points in replica {self._id}")
            return aggregated
            
        except Exception as e:
            logger.error(f"Aggregation failed in replica {self._id}: {e}")
            return None
    
    async def send_to_digital_twin(self, aggregated_data: AggregatedData) -> None:
        """Send aggregated data to the parent Digital Twin."""
        # This would normally send via messaging system or direct call
        # For now, we'll log it
        logger.info(
            f"Sending aggregated data from replica {self._id} "
            f"to Digital Twin {self._configuration.parent_digital_twin_id}"
        )
        # TODO: Implement actual messaging to Digital Twin
    
    async def add_device(self, device_id: str) -> None:
        """Add a new device to this replica's management."""
        if device_id not in self._configuration.device_ids:
            self._configuration.device_ids.append(device_id)
            logger.info(f"Added device {device_id} to replica {self._id}")
    
    async def remove_device(self, device_id: str) -> None:
        """Remove a device from this replica's management."""
        if device_id in self._configuration.device_ids:
            self._configuration.device_ids.remove(device_id)
            logger.info(f"Removed device {device_id} from replica {self._id}")
    
    async def update_configuration(self, new_config: ReplicaConfiguration) -> None:
        """Update the replica configuration."""
        old_config = self._configuration
        self._configuration = new_config
        
        # Reconfigure aggregator if needed
        if old_config.aggregation_config != new_config.aggregation_config:
            await self._aggregator.configure(new_config.aggregation_config)
        
        logger.info(f"Updated configuration for replica {self._id}")
    
    async def get_data_quality_report(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Generate a data quality report."""
        return {
            "replica_id": str(self._id),
            "total_data_received": self._data_received_count,
            "aggregations_performed": self._aggregations_performed,
            "last_aggregation": self._last_aggregation_time.isoformat() if self._last_aggregation_time else None,
            "pending_data_count": len(self._pending_data),
            "device_count": len(self._configuration.device_ids)
        }
    
    async def get_aggregation_statistics(self) -> Dict[str, Any]:
        """Get statistics about data aggregation performance."""
        return {
            "aggregation_method": self._aggregator.aggregation_method,
            "total_aggregations": self._aggregations_performed,
            "data_received": self._data_received_count,
            "aggregation_ratio": (
                self._aggregations_performed / max(self._data_received_count, 1)
            ),
            "last_aggregation": self._last_aggregation_time.isoformat() if self._last_aggregation_time else None
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize the replica to dictionary."""
        return {
            "id": str(self._id),
            "replica_type": self._configuration.replica_type.value,
            "parent_digital_twin_id": str(self._configuration.parent_digital_twin_id),
            "device_ids": self._configuration.device_ids,
            "aggregation_mode": self._configuration.aggregation_mode.value,
            "status": self._status.value,
            "metadata": self._metadata.to_dict(),
            "statistics": {
                "data_received": self._data_received_count,
                "aggregations_performed": self._aggregations_performed
            }
        }
    
    def validate(self) -> bool:
        """Validate the replica configuration and state."""
        if not self._configuration.device_ids:
            return False
        if not self._configuration.parent_digital_twin_id:
            return False
        return True
    
    async def _check_aggregation_trigger(self) -> None:
        """Check if aggregation should be triggered based on mode."""
        async with self._data_lock:
            should_aggregate = False
            
            if self._configuration.aggregation_mode == DataAggregationMode.REAL_TIME:
                should_aggregate = len(self._pending_data) > 0
            elif self._configuration.aggregation_mode == DataAggregationMode.BATCH:
                batch_size = self._configuration.aggregation_config.get("batch_size", 10)
                should_aggregate = len(self._pending_data) >= batch_size
            elif self._configuration.aggregation_mode == DataAggregationMode.WINDOW:
                # Time-based windowing
                window_seconds = self._configuration.aggregation_config.get("window_seconds", 60)
                if self._last_aggregation_time:
                    time_since_last = (datetime.now(timezone.utc) - self._last_aggregation_time).total_seconds()
                    should_aggregate = time_since_last >= window_seconds and len(self._pending_data) > 0
                else:
                    should_aggregate = len(self._pending_data) > 0
            
            if should_aggregate:
                data_to_process = self._pending_data.copy()
                self._pending_data.clear()
                
                # Process aggregation
                aggregated = await self.aggregate_data(data_to_process)
                if aggregated:
                    await self.send_to_digital_twin(aggregated)


class DigitalReplicaFactory(IReplicaFactory):
    """Factory for creating Digital Replica instances."""
    
    def __init__(self):
        self.config = get_config()
        self._supported_types = list(ReplicaType)
        self._aggregator_registry: Dict[str, Type[IDataAggregator]] = {
            "standard": StandardDataAggregator
        }
    
    async def create(
        self, 
        config: Dict[str, Any], 
        metadata: Optional[BaseMetadata] = None
    ) -> IDigitalReplica:
        """Create a new Digital Replica based on configuration."""
        try:
            # Validate configuration
            if not self.validate_config(config):
                raise FactoryConfigurationError("Invalid Digital Replica configuration")
            
            # Extract configuration
            replica_type = ReplicaType(config["replica_type"])
            parent_dt_id = UUID(config["parent_digital_twin_id"])
            device_ids = config["device_ids"]
            aggregation_mode = DataAggregationMode(config["aggregation_mode"])
            
            # Create replica configuration
            replica_config = ReplicaConfiguration(
                replica_type=replica_type,
                parent_digital_twin_id=parent_dt_id,
                device_ids=device_ids,
                aggregation_mode=aggregation_mode,
                aggregation_config=config.get("aggregation_config", {}),
                data_retention_policy=config.get("data_retention_policy", {}),
                quality_thresholds=config.get("quality_thresholds", {}),
                custom_config=config.get("custom_config", {})
            )
            
            # Create metadata if not provided
            if metadata is None:
                metadata = BaseMetadata(
                    entity_id=uuid4(),
                    timestamp=datetime.now(timezone.utc),
                    version="1.0.0",
                    created_by=uuid4()  # Should be actual user ID
                )
            
            # Create aggregator
            aggregator_type = config.get("aggregator_type", "standard")
            aggregator_class = self._aggregator_registry.get(aggregator_type, StandardDataAggregator)
            aggregator = aggregator_class()
            
            # Create replica
            replica = DigitalReplica(
                replica_id=metadata.id,
                configuration=replica_config,
                metadata=metadata,
                aggregator=aggregator
            )
            
            logger.info(f"Created Digital Replica {metadata.id} of type {replica_type}")
            return replica
            
        except Exception as e:
            logger.error(f"Failed to create Digital Replica: {e}")
            raise EntityCreationError(f"Digital Replica creation failed: {e}")
    
    async def create_replica(
        self,
        replica_type: ReplicaType,
        parent_digital_twin_id: UUID,
        config: ReplicaConfiguration,
        metadata: Optional[BaseMetadata] = None
    ) -> IDigitalReplica:
        """Create a new Digital Replica instance."""
        config_dict = {
            "replica_type": replica_type.value,
            "parent_digital_twin_id": str(parent_digital_twin_id),
            "device_ids": config.device_ids,
            "aggregation_mode": config.aggregation_mode.value,
            "aggregation_config": config.aggregation_config,
            "data_retention_policy": config.data_retention_policy,
            "quality_thresholds": config.quality_thresholds,
            "custom_config": config.custom_config
        }
        
        return await self.create(config_dict, metadata)
    
    async def create_from_template(
        self, 
        template_id: str, 
        config_overrides: Optional[Dict[str, Any]] = None,
        metadata: Optional[BaseMetadata] = None
    ) -> IDigitalReplica:
        """Create a Digital Replica from a predefined template."""
        template = self._get_template(template_id)
        if not template:
            raise FactoryConfigurationError(f"Template {template_id} not found")
        
        # Merge template with overrides
        final_config = template.copy()
        if config_overrides:
            final_config.update(config_overrides)
        
        return await self.create(final_config, metadata)
    
    def get_supported_replica_types(self) -> List[ReplicaType]:
        """Get the list of replica types this factory can create."""
        return self._supported_types.copy()
    
    def get_default_configuration(self, replica_type: ReplicaType) -> ReplicaConfiguration:
        """Get default configuration for a specific replica type."""
        default_configs = {
            ReplicaType.SENSOR_AGGREGATOR: {
                "aggregation_mode": DataAggregationMode.BATCH,
                "aggregation_config": {"batch_size": 10, "method": "average"},
                "data_retention_policy": {"retention_days": 30},
                "quality_thresholds": {"min_quality": 0.6}
            },
            ReplicaType.DEVICE_PROXY: {
                "aggregation_mode": DataAggregationMode.REAL_TIME,
                "aggregation_config": {"method": "latest"},
                "data_retention_policy": {"retention_days": 7},
                "quality_thresholds": {"min_quality": 0.8}
            }
        }
        
        config_dict = default_configs.get(replica_type, default_configs[ReplicaType.SENSOR_AGGREGATOR])
        
        return ReplicaConfiguration(
            replica_type=replica_type,
            parent_digital_twin_id=uuid4(),  # Placeholder
            device_ids=[],
            aggregation_mode=DataAggregationMode(config_dict["aggregation_mode"]),
            aggregation_config=config_dict["aggregation_config"],
            data_retention_policy=config_dict["data_retention_policy"],
            quality_thresholds=config_dict["quality_thresholds"]
        )
    
    def validate_replica_config(
        self,
        replica_type: ReplicaType,
        config: ReplicaConfiguration
    ) -> bool:
        """Validate a replica configuration for the specified type."""
        try:
            # Basic validation
            if config.replica_type != replica_type:
                return False
            
            if not config.device_ids:
                return False
            
            if not config.parent_digital_twin_id:
                return False
            
            # Type-specific validation
            if replica_type == ReplicaType.DEVICE_PROXY and len(config.device_ids) != 1:
                return False  # Device proxy should handle exactly one device
            
            return True
            
        except Exception:
            return False
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate the configuration before entity creation."""
        required_fields = [
            "replica_type", "parent_digital_twin_id", 
            "device_ids", "aggregation_mode"
        ]
        
        for field in required_fields:
            if field not in config:
                return False
        
        try:
            ReplicaType(config["replica_type"])
            DataAggregationMode(config["aggregation_mode"])
            UUID(config["parent_digital_twin_id"])
            
            if not isinstance(config["device_ids"], list) or not config["device_ids"]:
                return False
            
            return True
            
        except (ValueError, TypeError):
            return False
    
    def get_supported_types(self) -> List[str]:
        """Get the list of entity types this factory can create."""
        return [rt.value for rt in self._supported_types]
    
    def get_config_schema(self, entity_type: str) -> Dict[str, Any]:
        """Get the configuration schema for a specific entity type."""
        return {
            "type": "object",
            "properties": {
                "replica_type": {"type": "string", "enum": [rt.value for rt in ReplicaType]},
                "parent_digital_twin_id": {"type": "string", "format": "uuid"},
                "device_ids": {"type": "array", "items": {"type": "string"}},
                "aggregation_mode": {"type": "string", "enum": [am.value for am in DataAggregationMode]},
                "aggregation_config": {"type": "object"},
                "data_retention_policy": {"type": "object"},
                "quality_thresholds": {"type": "object"},
                "custom_config": {"type": "object"}
            },
            "required": ["replica_type", "parent_digital_twin_id", "device_ids", "aggregation_mode"]
        }
    
    def register_aggregator(self, name: str, aggregator_class: Type[IDataAggregator]) -> None:
        """Register a new aggregator type."""
        self._aggregator_registry[name] = aggregator_class
        logger.info(f"Registered aggregator type: {name}")
    
    def _get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Get a predefined template by ID."""
        templates = {
            "iot_sensor": {
                "replica_type": ReplicaType.SENSOR_AGGREGATOR.value,
                "aggregation_mode": DataAggregationMode.BATCH.value,
                "aggregation_config": {"batch_size": 5, "method": "average"},
                "data_retention_policy": {"retention_days": 30},
                "quality_thresholds": {"min_quality": 0.7}
            },
            "industrial_device": {
                "replica_type": ReplicaType.DEVICE_PROXY.value,
                "aggregation_mode": DataAggregationMode.REAL_TIME.value,
                "aggregation_config": {"method": "latest"},
                "data_retention_policy": {"retention_days": 90},
                "quality_thresholds": {"min_quality": 0.9}
            }
        }
        return templates.get(template_id)