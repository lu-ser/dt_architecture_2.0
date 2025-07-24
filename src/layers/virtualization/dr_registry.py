"""
Digital Replica Registry implementation for the Digital Twin Platform.

This module provides the specialized registry for Digital Replicas,
including device association tracking, data flow monitoring, and DR discovery.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID
import logging
from src.layers.digital_twin.association_manager import get_association_manager
from src.core.registry.base import AbstractRegistry, RegistryMetrics
from src.core.interfaces.base import IStorageAdapter
from src.core.interfaces.replica import (
    IDigitalReplica,
    ReplicaType,
    DataAggregationMode,
    DeviceData,
    DataQuality
)
from src.utils.exceptions import (
    DigitalReplicaError,
    DigitalReplicaNotFoundError,
    EntityNotFoundError,
    RegistryError
)

logger = logging.getLogger(__name__)


class DeviceAssociation:
    """Represents the association between a device and a Digital Replica."""
    
    def __init__(
        self,
        device_id: str,
        replica_id: UUID,
        association_type: str = "managed",
        created_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.device_id = device_id
        self.replica_id = replica_id
        self.association_type = association_type  # managed, monitored, aggregated
        self.created_at = created_at or datetime.now(timezone.utc)
        self.metadata = metadata or {}
        self.last_data_timestamp: Optional[datetime] = None
        self.data_count = 0
        self.quality_history: List[Tuple[datetime, DataQuality]] = []
        self._association_manager = None
    def update_data_received(self, quality: DataQuality) -> None:
        """Update statistics when data is received."""
        self.last_data_timestamp = datetime.now(timezone.utc)
        self.data_count += 1
        self.quality_history.append((self.last_data_timestamp, quality))
        
        # Keep only last 100 quality entries
        if len(self.quality_history) > 100:
            self.quality_history = self.quality_history[-100:]
    
    def get_average_quality_score(self) -> float:
        """Get average quality score over recent history."""
        if not self.quality_history:
            return 0.5
        
        quality_scores = {
            DataQuality.HIGH: 1.0,
            DataQuality.MEDIUM: 0.7,
            DataQuality.LOW: 0.4,
            DataQuality.INVALID: 0.0,
            DataQuality.UNKNOWN: 0.5
        }
        
        scores = [quality_scores.get(quality, 0.5) for _, quality in self.quality_history]
        return sum(scores) / len(scores)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert association to dictionary representation."""
        return {
            "device_id": self.device_id,
            "replica_id": str(self.replica_id),
            "association_type": self.association_type,
            "created_at": self.created_at.isoformat(),
            "last_data_timestamp": self.last_data_timestamp.isoformat() if self.last_data_timestamp else None,
            "data_count": self.data_count,
            "average_quality_score": self.get_average_quality_score(),
            "metadata": self.metadata
        }


class DataFlowMetrics:
    """Metrics for data flow monitoring between devices and replicas."""
    
    def __init__(self):
        self.total_data_points = 0
        self.data_by_device: Dict[str, int] = {}
        self.data_by_replica: Dict[UUID, int] = {}
        self.data_by_quality: Dict[DataQuality, int] = {}
        self.aggregations_performed = 0
        self.last_data_timestamp: Optional[datetime] = None
        self.data_rate_per_minute = 0.0
        
        # Performance tracking
        self._data_timestamps: List[datetime] = []
    
    def record_data_point(self, device_id: str, replica_id: UUID, quality: DataQuality) -> None:
        """Record a data point received."""
        now = datetime.now(timezone.utc)
        
        self.total_data_points += 1
        self.data_by_device[device_id] = self.data_by_device.get(device_id, 0) + 1
        self.data_by_replica[replica_id] = self.data_by_replica.get(replica_id, 0) + 1
        self.data_by_quality[quality] = self.data_by_quality.get(quality, 0) + 1
        self.last_data_timestamp = now
        
        # Update rate calculation
        self._data_timestamps.append(now)
        # Keep only last hour of timestamps
        cutoff = now - timedelta(hours=1)
        self._data_timestamps = [ts for ts in self._data_timestamps if ts > cutoff]
        
        # Calculate data rate per minute
        if len(self._data_timestamps) > 1:
            time_span = (self._data_timestamps[-1] - self._data_timestamps[0]).total_seconds() / 60
            self.data_rate_per_minute = len(self._data_timestamps) / max(time_span, 1)
    
    def record_aggregation(self) -> None:
        """Record that an aggregation was performed."""
        self.aggregations_performed += 1
    
    def get_quality_distribution(self) -> Dict[str, float]:
        """Get distribution of data quality."""
        if self.total_data_points == 0:
            return {}
        
        return {
            quality.value: count / self.total_data_points
            for quality, count in self.data_by_quality.items()
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary representation."""
        return {
            "total_data_points": self.total_data_points,
            "devices_count": len(self.data_by_device),
            "replicas_count": len(self.data_by_replica),
            "aggregations_performed": self.aggregations_performed,
            "data_rate_per_minute": self.data_rate_per_minute,
            "quality_distribution": self.get_quality_distribution(),
            "last_data_timestamp": self.last_data_timestamp.isoformat() if self.last_data_timestamp else None,
            "top_devices": sorted(
                self.data_by_device.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]
        }


class DigitalReplicaMetrics(RegistryMetrics):
    """Extended metrics for Digital Replica Registry."""
    
    def __init__(self):
        super().__init__()
        self.replicas_by_type: Dict[str, int] = {}
        self.replicas_by_mode: Dict[str, int] = {}
        self.total_devices_managed = 0
        self.active_replicas = 0
        self.data_flow_metrics = DataFlowMetrics()
        
    def update_replica_statistics(
        self,
        replica_type: ReplicaType,
        aggregation_mode: DataAggregationMode,
        device_count: int,
        is_active: bool
    ) -> None:
        """Update statistics for a Digital Replica."""
        # Update by type
        type_key = replica_type.value
        self.replicas_by_type[type_key] = self.replicas_by_type.get(type_key, 0) + 1
        
        # Update by mode
        mode_key = aggregation_mode.value
        self.replicas_by_mode[mode_key] = self.replicas_by_mode.get(mode_key, 0) + 1
        
        # Update device count
        self.total_devices_managed += device_count
        
        # Update active count
        if is_active:
            self.active_replicas += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        base_metrics = super().to_dict()
        base_metrics.update({
            "replicas_by_type": self.replicas_by_type,
            "replicas_by_mode": self.replicas_by_mode,
            "total_devices_managed": self.total_devices_managed,
            "active_replicas": self.active_replicas,
            "data_flow_metrics": self.data_flow_metrics.to_dict()
        })
        return base_metrics


class DigitalReplicaRegistry(AbstractRegistry[IDigitalReplica]):
    """
    Registry for Digital Replica entities.
    
    Provides specialized functionality for Digital Replicas including
    device association tracking, data flow monitoring, and discovery.
    """
    
    def __init__(
        self,
        storage_adapter: IStorageAdapter[IDigitalReplica],
        cache_enabled: bool = True,
        cache_size: int = 1000,
        cache_ttl: int = 300
    ):
        super().__init__(
            entity_type=IDigitalReplica,
            storage_adapter=storage_adapter,
            cache_enabled=cache_enabled,
            cache_size=cache_size,
            cache_ttl=cache_ttl
        )
        # Digital Replica specific storage
        self.device_associations: Dict[str, DeviceAssociation] = {}
        self.replica_to_devices: Dict[UUID, Set[str]] = {}
        self.digital_twin_replicas: Dict[UUID, Set[UUID]] = {}
        self._association_manager = None
        self.metrics = DigitalReplicaMetrics()
        # Locks for thread safety
        self._association_lock = asyncio.Lock()
        self._flow_lock = asyncio.Lock()

    async def _get_association_manager(self):
        """Get association manager lazily"""
        if self._association_manager is None:
            self._association_manager = await get_association_manager()
        return self._association_manager
    
    async def connect(self) -> None:
        """Connect to storage and load associations."""
        await super().connect()
        await self.load_associations_from_storage()

    async def load_associations_from_storage(self) -> None:
        """Load associations from MongoDB into the Dict"""
        try:
            logger.info("🔄 Loading associations into digital_twin_replicas Dict...")
            
            association_manager = await self._get_association_manager()
            persistent_associations = await association_manager.get_all_associations()
            
            # 🔍 DEBUG: Log delle associazioni prima del caricamento
            logger.info(f"🔍 DEBUG: AssociationManager returned {len(persistent_associations)} twin mappings")
            for twin_id, replica_set in persistent_associations.items():
                logger.info(f"🔍 DEBUG: Twin {twin_id} (type: {type(twin_id)}) -> {len(replica_set)} replicas")
            
            # Clear and update the existing Dict
            self.digital_twin_replicas.clear()
            self.digital_twin_replicas.update(persistent_associations)
            
            # 🔍 DEBUG: Verifica che il caricamento sia avvenuto correttamente
            logger.info(f"🔍 DEBUG: After update, digital_twin_replicas has {len(self.digital_twin_replicas)} mappings")
            for twin_id, replica_set in self.digital_twin_replicas.items():
                logger.info(f"🔍 DEBUG: Loaded Twin {twin_id} (type: {type(twin_id)}) -> {len(replica_set)} replicas")
            
            total_associations = sum(len(replicas) for replicas in persistent_associations.values())
            logger.info(f"✅ Loaded {total_associations} associations into memory Dict")
            
        except Exception as e:
            logger.error(f"❌ Failed to load associations from storage: {e}")
    
    async def register_digital_replica(
    self,
    replica: IDigitalReplica,
    device_associations: Optional[List[DeviceAssociation]] = None
) -> None:
        """Register replica and update both storage and memory."""
        # Register the replica using base functionality
        await self.register(replica)
        
        # Add device associations
        if device_associations:
            for association in device_associations:
                await self.associate_device(association)
        else:
            # Create associations for devices in replica configuration
            for device_id in replica.device_ids:
                association = DeviceAssociation(
                    device_id=device_id,
                    replica_id=replica.id,
                    association_type="managed"
                )
                await self.associate_device(association)
        
        # NUOVO: Gestisci associazione twin-replica
        if hasattr(replica, 'parent_digital_twin_id') and replica.parent_digital_twin_id:
            dt_id = replica.parent_digital_twin_id
            
            # 1. Update memory Dict (for immediate compatibility)
            if dt_id not in self.digital_twin_replicas:
                self.digital_twin_replicas[dt_id] = set()
            self.digital_twin_replicas[dt_id].add(replica.id)
            
            # 2. ALSO save to persistent storage
            try:
                association_manager = await self._get_association_manager()
                await association_manager.create_association(
                    twin_id=dt_id,
                    replica_id=replica.id,
                    association_type='data_source'
                )
                logger.info(f"✅ Saved association to BOTH memory and storage: {dt_id} -> {replica.id}")
            except Exception as e:
                if "already exists" not in str(e):
                    logger.error(f"Failed to save to persistent storage: {e}")

    async def get_digital_replica(self, replica_id: UUID) -> IDigitalReplica:
        """
        Get a Digital Replica by ID.
        
        Args:
            replica_id: ID of the Digital Replica to retrieve
            
        Returns:
            Digital Replica instance
        """
        try:
            return await self.get(replica_id)
        except EntityNotFoundError:
            raise DigitalReplicaNotFoundError(replica_id=str(replica_id))
    
    async def find_replicas_by_type(self, replica_type: ReplicaType) -> List[IDigitalReplica]:
        """
        Find Digital Replicas by type.
        
        Args:
            replica_type: Type of Digital Replicas to find
            
        Returns:
            List of Digital Replicas of the specified type
        """
        filters = {"replica_type": replica_type.value}
        return await self.list(filters=filters)
    
    
    async def find_replicas_by_digital_twin(self, digital_twin_id: UUID) -> List[IDigitalReplica]:
        """Find replicas using PERSISTENT storage directly (bypassing memory dict)"""
        try:
            # Use AssociationManager directly instead of memory dict
            association_manager = await self._get_association_manager()
            replica_ids = await association_manager.get_replicas_for_twin(digital_twin_id)
            
            # Get the actual replica objects
            replicas = []
            for replica_id in replica_ids:
                try:
                    replica = await self.get_digital_replica(replica_id)
                    replicas.append(replica)
                except Exception as e:
                    logger.warning(f"Replica {replica_id} found in associations but not in storage: {e}")
            
            logger.info(f"✅ Found {len(replicas)} replicas for twin {digital_twin_id} (using PERSISTENT storage)")
            return replicas
            
        except Exception as e:
            logger.error(f"❌ Failed to find replicas for twin {digital_twin_id}: {e}")
            return []


    async def add_replica_twin_association(self, replica_id: UUID, twin_id: UUID, data_mapping: Optional[Dict] = None) -> None:
        """SOLO STORAGE PERSISTENTE"""
        try:
            association_manager = await self._get_association_manager()
            await association_manager.create_association(
                twin_id=twin_id,
                replica_id=replica_id,
                association_type='data_source',
                data_mapping=data_mapping
            )
            logger.info(f"✅ Added PERSISTENT replica-twin association: {replica_id} -> {twin_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to add replica-twin association: {e}")
            raise


    async def remove_replica_twin_association(self, replica_id: UUID, twin_id: UUID) -> bool:
        """SOLO STORAGE PERSISTENTE"""
        try:
            association_manager = await self._get_association_manager()
            success = await association_manager.remove_association(twin_id, replica_id)
            
            if success:
                logger.info(f"✅ Removed PERSISTENT replica-twin association: {replica_id} -> {twin_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Failed to remove replica-twin association: {e}")
            return False

    async def get_twin_for_replica(self, replica_id: UUID) -> Optional[UUID]:
        """Get twin ID for replica from PERSISTENT storage"""
        try:
            association_manager = await self._get_association_manager()
            return await association_manager.get_twin_for_replica(replica_id)
        except Exception as e:
            logger.error(f"Failed to get twin for replica {replica_id}: {e}")
            return None

    # AGGIORNARE tutti i metodi che usavano digital_twin_replicas
    async def get_replica_count_by_twin(self, twin_id: UUID) -> int:
        """Get replica count using persistent storage"""
        try:
            association_manager = await self._get_association_manager()
            replica_ids = await association_manager.get_replicas_for_twin(twin_id)
            return len(replica_ids)
        except Exception as e:
            logger.error(f"Failed to get replica count for twin {twin_id}: {e}")
            return 0

    async def get_all_twin_replica_mappings(self) -> Dict[str, List[str]]:
        """Get all mappings as strings for API responses"""
        try:
            association_manager = await self._get_association_manager()
            mappings = await association_manager.get_all_associations()
            
            # Convert to string format for APIs
            string_mappings = {}
            for twin_id, replica_ids in mappings.items():
                string_mappings[str(twin_id)] = [str(rid) for rid in replica_ids]
            
            return string_mappings
        except Exception as e:
            logger.error(f"Failed to get all twin-replica mappings: {e}")
            return {}

    async def find_replicas_by_device(self, device_id: str) -> List[IDigitalReplica]:
        """
        Find Digital Replicas managing a specific device.
        
        Args:
            device_id: ID of the device
            
        Returns:
            List of Digital Replicas managing the device
        """
        replicas = []
        
        for association in self.device_associations.values():
            if association.device_id == device_id:
                try:
                    replica = await self.get_digital_replica(association.replica_id)
                    replicas.append(replica)
                except DigitalReplicaNotFoundError:
                    # Clean up stale association
                    await self.disassociate_device(device_id, association.replica_id)
        
        return replicas
    
    async def associate_device(self, association: DeviceAssociation) -> None:
        """
        Associate a device with a Digital Replica.
        
        Args:
            association: Device association to add
        """
        async with self._association_lock:
            # Verify replica exists
            await self.get_digital_replica(association.replica_id)
            
            # Store association
            key = f"{association.device_id}:{association.replica_id}"
            self.device_associations[key] = association
            
            # Update replica to devices mapping
            if association.replica_id not in self.replica_to_devices:
                self.replica_to_devices[association.replica_id] = set()
            self.replica_to_devices[association.replica_id].add(association.device_id)
            
            self.logger.info(
                f"Associated device {association.device_id} "
                f"with replica {association.replica_id}"
            )
    
    async def disassociate_device(self, device_id: str, replica_id: UUID) -> bool:
        """
        Remove association between a device and Digital Replica.
        
        Args:
            device_id: ID of the device
            replica_id: ID of the Digital Replica
            
        Returns:
            True if association was removed, False if not found
        """
        async with self._association_lock:
            key = f"{device_id}:{replica_id}"
            
            if key in self.device_associations:
                del self.device_associations[key]
                
                # Update replica to devices mapping
                if replica_id in self.replica_to_devices:
                    self.replica_to_devices[replica_id].discard(device_id)
                    if not self.replica_to_devices[replica_id]:
                        del self.replica_to_devices[replica_id]
                
                self.logger.info(f"Disassociated device {device_id} from replica {replica_id}")
                return True
            
            return False
    
    async def get_device_associations(self, device_id: str) -> List[DeviceAssociation]:
        """
        Get all associations for a specific device.
        
        Args:
            device_id: ID of the device
            
        Returns:
            List of device associations
        """
        associations = []
        for association in self.device_associations.values():
            if association.device_id == device_id:
                associations.append(association)
        return associations
    
    async def get_replica_devices(self, replica_id: UUID) -> List[str]:
        """
        Get all devices managed by a specific replica.
        
        Args:
            replica_id: ID of the Digital Replica
            
        Returns:
            List of device IDs
        """
        return list(self.replica_to_devices.get(replica_id, set()))
    
    async def record_device_data(
    self,
    device_id: str,
    replica_id: UUID,
    data_quality: DataQuality
) -> None:
        """
        Record that data was received from a device by a replica.
        Auto-creates device association if it doesn't exist.
        
        Args:
            device_id: ID of the device that sent data
            replica_id: ID of the replica that received data
            data_quality: Quality of the received data
        """
        async with self._flow_lock:
            # Check if association exists
            key = f"{device_id}:{replica_id}"
            
            # 🔥 AUTO-CREATE ASSOCIATION SE NON ESISTE
            if key not in self.device_associations:
                logger.info(f"Auto-creating device association: {device_id} -> {replica_id}")
                
                # Create new association
                association = DeviceAssociation(
                    device_id=device_id,
                    replica_id=replica_id,
                    association_type="managed"
                )
                
                # Store association (without calling associate_device to avoid deadlock)
                self.device_associations[key] = association
                
                # Update replica to devices mapping
                if replica_id not in self.replica_to_devices:
                    self.replica_to_devices[replica_id] = set()
                self.replica_to_devices[replica_id].add(device_id)
                
                logger.info(f"✅ Auto-created association: {device_id} <-> {replica_id}")
            
            # Update association statistics
            self.device_associations[key].update_data_received(data_quality)
            
            # Update flow metrics
            self.metrics.data_flow_metrics.record_data_point(
                device_id, replica_id, data_quality
            )
            
            logger.debug(f"Recorded data: device={device_id}, replica={replica_id}, quality={data_quality.value}")
    
    async def record_aggregation(self, replica_id: UUID) -> None:
        """
        Record that an aggregation was performed by a replica.
        
        Args:
            replica_id: ID of the replica that performed aggregation
        """
        async with self._flow_lock:
            self.metrics.data_flow_metrics.record_aggregation()
    
    async def get_data_flow_statistics(
        self,
        time_window_hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get data flow statistics for the specified time window.
        
        Args:
            time_window_hours: Time window in hours
            
        Returns:
            Data flow statistics
        """
        return {
            "time_window_hours": time_window_hours,
            "metrics": self.metrics.data_flow_metrics.to_dict(),
            "device_count": len(set(assoc.device_id for assoc in self.device_associations.values())),
            "replica_count": len(self.replica_to_devices),
            "associations_count": len(self.device_associations)
        }
    
    async def get_replica_performance(self, replica_id: UUID) -> Dict[str, Any]:
        """
        Get performance metrics for a specific replica.
        
        Args:
            replica_id: ID of the Digital Replica
            
        Returns:
            Performance metrics
        """
        try:
            replica = await self.get_digital_replica(replica_id)
            
            # Get device associations
            devices = await self.get_replica_devices(replica_id)
            associations = []
            for device_id in devices:
                key = f"{device_id}:{replica_id}"
                if key in self.device_associations:
                    associations.append(self.device_associations[key])
            
            # Calculate metrics
            total_data = sum(assoc.data_count for assoc in associations)
            avg_quality = sum(assoc.get_average_quality_score() for assoc in associations) / len(associations) if associations else 0
            
            return {
                "replica_id": str(replica_id),
                "replica_type": replica.replica_type.value,
                "device_count": len(devices),
                "total_data_received": total_data,
                "average_quality_score": avg_quality,
                "associations": [assoc.to_dict() for assoc in associations],
                "aggregation_stats": await replica.get_aggregation_statistics()
            }
            
        except DigitalReplicaNotFoundError:
            return {"error": f"Replica {replica_id} not found"}
    
    async def discover_replicas(
        self,
        criteria: Dict[str, Any]
    ) -> List[IDigitalReplica]:
        """
        Discover Digital Replicas based on criteria.
        
        Args:
            criteria: Discovery criteria (type, capabilities, location, etc.)
            
        Returns:
            List of matching Digital Replicas
        """
        filters = {}
        
        # Map criteria to filters
        if "type" in criteria:
            filters["replica_type"] = criteria["type"]
        if "aggregation_mode" in criteria:
            filters["aggregation_mode"] = criteria["aggregation_mode"]
        if "parent_digital_twin_id" in criteria:
            filters["parent_digital_twin_id"] = criteria["parent_digital_twin_id"]
        
        replicas = await self.list(filters=filters)
        
        # Additional filtering based on complex criteria
        if "min_device_count" in criteria:
            min_devices = criteria["min_device_count"]
            replicas = [r for r in replicas if len(r.device_ids) >= min_devices]
        
        if "quality_threshold" in criteria:
            threshold = criteria["quality_threshold"]
            filtered_replicas = []
            for replica in replicas:
                devices = await self.get_replica_devices(replica.id)
                if devices:
                    associations = []
                    for device_id in devices:
                        key = f"{device_id}:{replica.id}"
                        if key in self.device_associations:
                            associations.append(self.device_associations[key])
                    
                    if associations:
                        avg_quality = sum(assoc.get_average_quality_score() for assoc in associations) / len(associations)
                        if avg_quality >= threshold:
                            filtered_replicas.append(replica)
            replicas = filtered_replicas
        
        return replicas
    
    # Override hook methods for Digital Replica specific behavior
    async def _post_register_hook(self, entity: IDigitalReplica) -> None:
        """Hook called after Digital Replica registration."""
        from src.core.interfaces.base import EntityStatus
        
        # Update metrics
        self.metrics.update_replica_statistics(
            replica_type=entity.replica_type,
            aggregation_mode=entity.aggregation_mode,
            device_count=len(entity.device_ids),
            is_active=(entity.status == EntityStatus.ACTIVE)
        )
    
    async def _pre_unregister_hook(self, entity: IDigitalReplica) -> None:
        """Hook called before Digital Replica unregistration."""
        replica_id = entity.id
        
        # Clean up device associations
        devices_to_remove = await self.get_replica_devices(replica_id)
        for device_id in devices_to_remove:
            await self.disassociate_device(device_id, replica_id)
        
        # Clean up digital twin associations
        dt_id = entity.parent_digital_twin_id
        if dt_id in self.digital_twin_replicas:
            self.digital_twin_replicas[dt_id].discard(replica_id)
            if not self.digital_twin_replicas[dt_id]:
                del self.digital_twin_replicas[dt_id]