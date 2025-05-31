"""
Digital Replica interfaces for the Digital Twin Platform.

This module defines interfaces specific to Digital Replicas (DR), which are
responsible for data aggregation, device communication, and serving as the
bridge between physical devices and Digital Twins.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, Union, Callable
from uuid import UUID
from enum import Enum

from .base import IEntity, IFactory, ILifecycleManager, BaseMetadata


class DataAggregationMode(Enum):
    """Data aggregation modes for Digital Replicas."""
    REAL_TIME = "real_time"         # Process data immediately
    BATCH = "batch"                 # Process data in batches
    WINDOW = "window"               # Time-based windowing
    EVENT_DRIVEN = "event_driven"   # Process on specific events
    HYBRID = "hybrid"               # Combination of modes


class DataQuality(Enum):
    """Data quality levels for incoming data."""
    HIGH = "high"           # Data passes all quality checks
    MEDIUM = "medium"       # Data has minor quality issues
    LOW = "low"            # Data has significant quality issues
    INVALID = "invalid"     # Data fails validation
    UNKNOWN = "unknown"     # Quality cannot be determined


class ReplicaType(Enum):
    """Types of Digital Replicas based on their function."""
    SENSOR_AGGREGATOR = "sensor_aggregator"       # Aggregates sensor data
    DEVICE_PROXY = "device_proxy"                 # Proxies single device
    MULTI_DEVICE = "multi_device"                 # Handles multiple devices
    EDGE_GATEWAY = "edge_gateway"                 # Edge computing gateway
    DATA_PROCESSOR = "data_processor"             # Processes and transforms data
    VIRTUAL_SENSOR = "virtual_sensor"             # Virtual/computed sensors


class DeviceData:
    """Represents data received from a physical device."""
    
    def __init__(
        self,
        device_id: str,
        timestamp: datetime,
        data: Dict[str, Any],
        data_type: str,
        quality: DataQuality = DataQuality.UNKNOWN,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.device_id = device_id
        self.timestamp = timestamp
        self.data = data
        self.data_type = data_type
        self.quality = quality
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert device data to dictionary representation."""
        return {
            "device_id": self.device_id,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "data_type": self.data_type,
            "quality": self.quality.value,
            "metadata": self.metadata
        }


class AggregatedData:
    """Represents aggregated data ready for Digital Twin consumption."""
    
    def __init__(
        self,
        source_replica_id: UUID,
        aggregation_timestamp: datetime,
        aggregated_data: Dict[str, Any],
        source_count: int,
        aggregation_method: str,
        quality_score: float,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.source_replica_id = source_replica_id
        self.aggregation_timestamp = aggregation_timestamp
        self.aggregated_data = aggregated_data
        self.source_count = source_count
        self.aggregation_method = aggregation_method
        self.quality_score = quality_score  # 0.0 to 1.0
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert aggregated data to dictionary representation."""
        return {
            "source_replica_id": str(self.source_replica_id),
            "aggregation_timestamp": self.aggregation_timestamp.isoformat(),
            "aggregated_data": self.aggregated_data,
            "source_count": self.source_count,
            "aggregation_method": self.aggregation_method,
            "quality_score": self.quality_score,
            "metadata": self.metadata
        }


class ReplicaConfiguration:
    """Configuration for Digital Replica instances."""
    
    def __init__(
        self,
        replica_type: ReplicaType,
        parent_digital_twin_id: UUID,
        device_ids: List[str],
        aggregation_mode: DataAggregationMode,
        aggregation_config: Dict[str, Any],
        data_retention_policy: Dict[str, Any],
        quality_thresholds: Dict[str, float],
        custom_config: Optional[Dict[str, Any]] = None
    ):
        self.replica_type = replica_type
        self.parent_digital_twin_id = parent_digital_twin_id
        self.device_ids = device_ids
        self.aggregation_mode = aggregation_mode
        self.aggregation_config = aggregation_config
        self.data_retention_policy = data_retention_policy
        self.quality_thresholds = quality_thresholds
        self.custom_config = custom_config or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary representation."""
        return {
            "replica_type": self.replica_type.value,
            "parent_digital_twin_id": str(self.parent_digital_twin_id),
            "device_ids": self.device_ids,
            "aggregation_mode": self.aggregation_mode.value,
            "aggregation_config": self.aggregation_config,
            "data_retention_policy": self.data_retention_policy,
            "quality_thresholds": self.quality_thresholds,
            "custom_config": self.custom_config
        }


class IDigitalReplica(IEntity):
    """
    Interface for Digital Replica entities.
    
    Digital Replicas are responsible for receiving data from physical devices,
    performing aggregation, and forwarding processed data to Digital Twins.
    They serve as the virtualization layer in the architecture.
    """
    
    @property
    @abstractmethod
    def replica_type(self) -> ReplicaType:
        """Get the type of this Digital Replica."""
        pass
    
    @property
    @abstractmethod
    def parent_digital_twin_id(self) -> UUID:
        """Get the ID of the parent Digital Twin."""
        pass
    
    @property
    @abstractmethod
    def device_ids(self) -> List[str]:
        """Get the list of device IDs this replica manages."""
        pass
    
    @property
    @abstractmethod
    def configuration(self) -> ReplicaConfiguration:
        """Get the current configuration of the replica."""
        pass
    
    @property
    @abstractmethod
    def aggregation_mode(self) -> DataAggregationMode:
        """Get the current aggregation mode."""
        pass
    
    @abstractmethod
    async def receive_device_data(self, device_data: DeviceData) -> None:
        """
        Receive data from a physical device.
        
        Args:
            device_data: Data received from the device
        """
        pass
    
    @abstractmethod
    async def aggregate_data(
        self,
        data_batch: List[DeviceData],
        force_aggregation: bool = False
    ) -> Optional[AggregatedData]:
        """
        Aggregate device data according to the configured aggregation mode.
        
        Args:
            data_batch: Batch of device data to aggregate
            force_aggregation: Force aggregation even if conditions aren't met
            
        Returns:
            Aggregated data if aggregation was performed, None otherwise
        """
        pass
    
    @abstractmethod
    async def send_to_digital_twin(self, aggregated_data: AggregatedData) -> None:
        """
        Send aggregated data to the parent Digital Twin.
        
        Args:
            aggregated_data: The aggregated data to send
        """
        pass
    
    @abstractmethod
    async def add_device(self, device_id: str) -> None:
        """
        Add a new device to this replica's management.
        
        Args:
            device_id: ID of the device to add
        """
        pass
    
    @abstractmethod
    async def remove_device(self, device_id: str) -> None:
        """
        Remove a device from this replica's management.
        
        Args:
            device_id: ID of the device to remove
        """
        pass
    
    @abstractmethod
    async def update_configuration(self, new_config: ReplicaConfiguration) -> None:
        """
        Update the replica configuration.
        
        Args:
            new_config: New configuration to apply
        """
        pass
    
    @abstractmethod
    async def get_data_quality_report(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Generate a data quality report for the specified time range.
        
        Args:
            start_time: Start of the time range (None for all-time)
            end_time: End of the time range (None for current time)
            
        Returns:
            Data quality report dictionary
        """
        pass
    
    @abstractmethod
    async def get_aggregation_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about data aggregation performance.
        
        Returns:
            Dictionary containing aggregation statistics
        """
        pass


class IDataAggregator(ABC):
    """
    Interface for data aggregation components.
    
    Data aggregators implement specific algorithms for combining
    and processing device data within Digital Replicas.
    """
    
    @property
    @abstractmethod
    def aggregation_method(self) -> str:
        """Get the name of the aggregation method."""
        pass
    
    @abstractmethod
    async def configure(self, config: Dict[str, Any]) -> None:
        """Configure the aggregator with specific parameters."""
        pass
    
    @abstractmethod
    async def aggregate(
        self,
        data_batch: List[DeviceData],
        context: Optional[Dict[str, Any]] = None
    ) -> AggregatedData:
        """
        Perform data aggregation on the provided batch.
        
        Args:
            data_batch: Batch of device data to aggregate
            context: Optional context information for aggregation
            
        Returns:
            Aggregated data result
        """
        pass
    
    @abstractmethod
    def validate_data(self, device_data: DeviceData) -> DataQuality:
        """
        Validate the quality of incoming device data.
        
        Args:
            device_data: Device data to validate
            
        Returns:
            Data quality assessment
        """
        pass
    
    @abstractmethod
    def can_aggregate(self, data_batch: List[DeviceData]) -> bool:
        """
        Check if the current data batch can be aggregated.
        
        Args:
            data_batch: Batch of device data to check
            
        Returns:
            True if aggregation can be performed, False otherwise
        """
        pass


class IReplicaFactory(IFactory[IDigitalReplica]):
    """
    Factory interface for creating Digital Replica instances.
    
    Handles the creation and configuration of Digital Replicas
    based on provided specifications and templates.
    """
    
    @abstractmethod
    async def create_replica(
        self,
        replica_type: ReplicaType,
        parent_digital_twin_id: UUID,
        config: ReplicaConfiguration,
        metadata: Optional[BaseMetadata] = None
    ) -> IDigitalReplica:
        """
        Create a new Digital Replica instance.
        
        Args:
            replica_type: Type of replica to create
            parent_digital_twin_id: ID of the parent Digital Twin
            config: Replica configuration
            metadata: Optional metadata for the replica
            
        Returns:
            Created Digital Replica instance
        """
        pass
    
    @abstractmethod
    def get_supported_replica_types(self) -> List[ReplicaType]:
        """Get the list of replica types this factory can create."""
        pass
    
    @abstractmethod
    def get_default_configuration(self, replica_type: ReplicaType) -> ReplicaConfiguration:
        """Get default configuration for a specific replica type."""
        pass
    
    @abstractmethod
    def validate_replica_config(
        self,
        replica_type: ReplicaType,
        config: ReplicaConfiguration
    ) -> bool:
        """Validate a replica configuration for the specified type."""
        pass


class IReplicaLifecycleManager(ILifecycleManager[IDigitalReplica]):
    """
    Lifecycle manager interface for Digital Replicas.
    
    Manages the complete lifecycle of Digital Replicas including
    creation, deployment, monitoring, and termination.
    """
    
    @abstractmethod
    async def deploy_replica(
        self,
        replica: IDigitalReplica,
        deployment_target: str
    ) -> str:
        """
        Deploy a replica to a specific target (container, edge device, etc.).
        
        Args:
            replica: The replica to deploy
            deployment_target: Target for deployment
            
        Returns:
            Deployment ID or reference
        """
        pass
    
    @abstractmethod
    async def scale_replica(
        self,
        replica_id: UUID,
        scale_factor: int
    ) -> None:
        """
        Scale a replica horizontally.
        
        Args:
            replica_id: ID of the replica to scale
            scale_factor: Number of instances to scale to
        """
        pass
    
    @abstractmethod
    async def migrate_replica(
        self,
        replica_id: UUID,
        target_location: str
    ) -> None:
        """
        Migrate a replica to a different location or host.
        
        Args:
            replica_id: ID of the replica to migrate
            target_location: Target location for migration
        """
        pass
    
    @abstractmethod
    async def backup_replica_state(self, replica_id: UUID) -> str:
        """
        Create a backup of the replica's current state.
        
        Args:
            replica_id: ID of the replica to backup
            
        Returns:
            Backup reference or path
        """
        pass
    
    @abstractmethod
    async def restore_replica_state(
        self,
        replica_id: UUID,
        backup_reference: str
    ) -> None:
        """
        Restore a replica from a previous backup.
        
        Args:
            replica_id: ID of the replica to restore
            backup_reference: Reference to the backup to restore from
        """
        pass


# Type alias for replica event handlers
ReplicaEventHandler = Callable[[UUID, str, Dict[str, Any]], None]


class IReplicaEventBus(ABC):
    """
    Event bus interface for Digital Replica events.
    
    Handles event-driven communication between replicas and other
    platform components.
    """
    
    @abstractmethod
    async def publish_event(
        self,
        event_type: str,
        replica_id: UUID,
        event_data: Dict[str, Any]
    ) -> None:
        """
        Publish an event related to a replica.
        
        Args:
            event_type: Type of the event
            replica_id: ID of the replica that generated the event
            event_data: Event payload data
        """
        pass
    
    @abstractmethod
    def subscribe_to_events(
        self,
        event_types: List[str],
        handler: ReplicaEventHandler,
        replica_filter: Optional[List[UUID]] = None
    ) -> str:
        """
        Subscribe to replica events.
        
        Args:
            event_types: List of event types to subscribe to
            handler: Event handler function
            replica_filter: Optional list of replica IDs to filter events
            
        Returns:
            Subscription ID
        """
        pass
    
    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> None:
        """
        Unsubscribe from events.
        
        Args:
            subscription_id: ID of the subscription to cancel
        """
        pass