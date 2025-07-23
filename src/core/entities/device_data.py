# src/core/entities/device_data.py - IMPLEMENTAZIONE COMPLETA DI IEntity

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from src.core.interfaces.base import IEntity, BaseMetadata, EntityStatus
from src.core.interfaces.replica import DataQuality


class DeviceDataEntity(IEntity):
    """
    Entity per salvare i device data in MongoDB.
    Implementa COMPLETAMENTE IEntity per essere compatibile con l'architettura.
    """
    
    def __init__(
        self,
        entity_id: UUID,
        metadata: BaseMetadata,
        device_id: str,
        replica_id: UUID,
        timestamp: datetime,
        data: Dict[str, Any],
        data_type: str,
        quality: DataQuality,
        device_metadata: Dict[str, Any],
        processed: bool = False,
        aggregation_batch_id: Optional[UUID] = None
    ):
        # IEntity required fields
        self._id = entity_id
        self._metadata = metadata
        self._status = EntityStatus.ACTIVE
        
        # Device data fields
        self.device_id = device_id
        self.replica_id = replica_id
        self.timestamp = timestamp
        self.data = data
        self.data_type = data_type
        self.quality = quality
        self.device_metadata = device_metadata
        
        # Optional fields
        self.processed = processed
        self.aggregation_batch_id = aggregation_batch_id
    
    # ================================
    # IEntity ABSTRACT METHODS IMPLEMENTATION
    # ================================
    
    @property
    def id(self) -> UUID:
        """Get entity ID."""
        return self._id
    
    @property
    def metadata(self) -> BaseMetadata:
        """Get entity metadata."""
        return self._metadata
    
    @property
    def status(self) -> EntityStatus:
        """Get entity status."""
        return self._status
    
    async def initialize(self) -> None:
        """Initialize the device data entity."""
        self._status = EntityStatus.ACTIVE
        # Device data entities are immediately active - no initialization needed
        pass
    
    async def start(self) -> None:
        """Start the device data entity (no-op for data entities)."""
        self._status = EntityStatus.ACTIVE
        pass
    
    async def stop(self) -> None:
        """Stop the device data entity (no-op for data entities)."""
        self._status = EntityStatus.INACTIVE
        pass
    
    async def terminate(self) -> None:
        """Terminate the device data entity."""
        self._status = EntityStatus.TERMINATED
        pass
    
    async def validate(self) -> bool:
        """Validate the device data entity."""
        # Basic validation
        if not self.device_id:
            return False
        if not self.replica_id:
            return False
        if not self.data:
            return False
        if not self.data_type:
            return False
        return True
    
    # ================================
    # DEVICE DATA SPECIFIC METHODS
    # ================================
    
    @classmethod
    def from_device_data(
        cls, 
        device_data, 
        replica_id: UUID,
        additional_metadata: Optional[Dict[str, Any]] = None
    ):
        """Create DeviceDataEntity from DeviceData interface."""
        entity_id = uuid4()
        
        metadata = BaseMetadata(
            entity_id=entity_id,
            timestamp=datetime.now(timezone.utc),
            version="1.0.0",
            created_by=replica_id,  # Created by replica
            custom=additional_metadata or {}
        )
        
        return cls(
            entity_id=entity_id,
            metadata=metadata,
            device_id=device_data.device_id,
            replica_id=replica_id,
            timestamp=device_data.timestamp,
            data=device_data.data,
            data_type=device_data.data_type,
            quality=device_data.quality,
            device_metadata=device_data.metadata,
            processed=False,
            aggregation_batch_id=None
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB storage."""
        return {
            "entity_id": str(self._id),
            "entity_type": "DeviceDataEntity",
            "status": self._status.value,
            "created_at": self._metadata.timestamp.isoformat(),
            "metadata": self._metadata.to_dict(),
            # Device data specific fields
            "device_id": self.device_id,
            "replica_id": str(self.replica_id),
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "data_type": self.data_type,
            "quality": self.quality.value,
            "device_metadata": self.device_metadata,
            "processed": self.processed,
            "aggregation_batch_id": str(self.aggregation_batch_id) if self.aggregation_batch_id else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """Create from dictionary (MongoDB deserialization)."""
        entity_id = UUID(data["entity_id"])
        metadata = BaseMetadata.from_dict(data["metadata"])
        
        instance = cls(
            entity_id=entity_id,
            metadata=metadata,
            device_id=data["device_id"],
            replica_id=UUID(data["replica_id"]),
            timestamp=datetime.fromisoformat(data["timestamp"].replace('Z', '+00:00')),
            data=data["data"],
            data_type=data["data_type"],
            quality=DataQuality(data["quality"]),
            device_metadata=data["device_metadata"],
            processed=data.get("processed", False),
            aggregation_batch_id=UUID(data["aggregation_batch_id"]) if data.get("aggregation_batch_id") else None
        )
        
        # Set status from data
        if "status" in data:
            instance._status = EntityStatus(data["status"])
        
        return instance
    
    def update_metadata(self, key: str, value: Any) -> None:
        """Update metadata with new key-value pair."""
        self._metadata.custom[key] = value
    
    def __str__(self) -> str:
        return f"DeviceDataEntity(id={self._id}, device={self.device_id}, type={self.data_type})"
    
    def __repr__(self) -> str:
        return f"DeviceDataEntity(id='{self._id}', device_id='{self.device_id}', timestamp='{self.timestamp}', quality='{self.quality.value}')"