from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from src.core.interfaces.base import IEntity, BaseMetadata, EntityStatus


class DigitalTwinAssociationEntity(IEntity):
    """
    Entity per salvare le associazioni Digital Twin in MongoDB.
    PERSISTENZA DELLE ASSOCIAZIONI!
    """
    
    def __init__(
        self,
        entity_id: UUID,
        metadata: BaseMetadata,
        twin_id: UUID,
        associated_entity_id: UUID,
        association_type: str,
        entity_type: str,
        association_metadata: Optional[Dict[str, Any]] = None,
        last_interaction: Optional[datetime] = None,
        interaction_count: int = 0
    ):
        # IEntity required fields
        self._id = entity_id
        self._metadata = metadata
        self._status = EntityStatus.ACTIVE
        
        # Association fields
        self.twin_id = twin_id
        self.associated_entity_id = associated_entity_id
        self.association_type = association_type
        self.entity_type = entity_type
        self.association_metadata = association_metadata or {}
        self.last_interaction = last_interaction
        self.interaction_count = interaction_count
    
    # IEntity methods
    @property
    def id(self) -> UUID:
        return self._id
    
    @property
    def metadata(self) -> BaseMetadata:
        return self._metadata
    
    @property
    def status(self) -> EntityStatus:
        return self._status
    
    async def initialize(self) -> None:
        self._status = EntityStatus.ACTIVE
        pass
    
    async def start(self) -> None:
        self._status = EntityStatus.ACTIVE
        pass
    
    async def stop(self) -> None:
        self._status = EntityStatus.INACTIVE
        pass
    
    async def terminate(self) -> None:
        self._status = EntityStatus.TERMINATED
        pass
    
    async def validate(self) -> bool:
        return all([self.twin_id, self.associated_entity_id, self.association_type, self.entity_type])
    
    # Association methods
    @classmethod
    def from_association(cls, association):
        """Create from DigitalTwinAssociation."""
        entity_id = uuid4()
        metadata = BaseMetadata(
            entity_id=entity_id,
            timestamp=datetime.now(timezone.utc),
            version="1.0.0",
            created_by=association.twin_id
        )
        
        return cls(
            entity_id=entity_id,
            metadata=metadata,
            twin_id=association.twin_id,
            associated_entity_id=association.associated_entity_id,
            association_type=association.association_type,
            entity_type=association.entity_type,
            association_metadata=association.metadata,
            last_interaction=association.last_interaction,
            interaction_count=association.interaction_count
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB storage."""
        return {
            "entity_id": str(self._id),
            "entity_type": "DigitalTwinAssociationEntity",
            "status": self._status.value,
            "created_at": self._metadata.timestamp.isoformat(),
            "metadata": self._metadata.to_dict(),
            # Association specific fields
            "twin_id": str(self.twin_id),
            "associated_entity_id": str(self.associated_entity_id),
            "association_type": self.association_type,
            "entity_type_associated": self.entity_type,
            "association_metadata": self.association_metadata,
            "last_interaction": self.last_interaction.isoformat() if self.last_interaction else None,
            "interaction_count": self.interaction_count
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """Create from dictionary (MongoDB deserialization)."""
        entity_id = UUID(data["entity_id"])
        metadata = BaseMetadata.from_dict(data["metadata"])
        
        instance = cls(
            entity_id=entity_id,
            metadata=metadata,
            twin_id=UUID(data["twin_id"]),
            associated_entity_id=UUID(data["associated_entity_id"]),
            association_type=data["association_type"],
            entity_type=data["entity_type_associated"],
            association_metadata=data.get("association_metadata", {}),
            last_interaction=datetime.fromisoformat(data["last_interaction"]) if data.get("last_interaction") else None,
            interaction_count=data.get("interaction_count", 0)
        )
        
        if "status" in data:
            instance._status = EntityStatus(data["status"])
        
        return instance