"""
Base interfaces for the Digital Twin Platform.

This module defines the fundamental interfaces that all platform components
must implement, ensuring consistency and interoperability across the system.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, TypeVar, Generic, Union
from uuid import UUID
from enum import Enum


# Type variables for generic interfaces
T = TypeVar('T')
K = TypeVar('K')


class EntityStatus(Enum):
    """Standard entity statuses across the platform."""
    CREATED = "created"
    INITIALIZING = "initializing"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class BaseMetadata:
    """Base metadata structure for all entities - con supporto .get()"""
    
    def __init__(
        self,
        entity_id: UUID,
        timestamp: datetime,
        version: str,
        created_by: UUID,
        custom: Optional[Dict[str, Any]] = None
    ):
        self.id = entity_id
        self.timestamp = timestamp
        self.version = version
        self.created_by = created_by
        self.custom = custom or {}
    
    # ✅ AGGIUNGI QUESTO METODO
    def get(self, key: str, default: Any = None) -> Any:
        """Get value from custom metadata (compatibility with dict.get())"""
        return self.custom.get(key, default)
    
    # ✅ AGGIUNGI ANCHE QUESTO per essere sicuri
    def __getitem__(self, key: str) -> Any:
        """Allow dict-like access to custom metadata"""
        return self.custom[key]
    
    def __setitem__(self, key: str, value: Any) -> None:
        """Prevent direct assignment with helpful error"""
        raise TypeError(
            f"BaseMetadata object does not support item assignment. "
            f"Use entity.update_metadata('{key}', {value}) instead."
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary representation."""
        return {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "version": self.version,
            "created_by": str(self.created_by),
            "custom": self.custom
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BaseMetadata':
        """Create metadata from dictionary representation."""
        return cls(
            entity_id=UUID(data["id"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            version=data["version"],
            created_by=UUID(data["created_by"]),
            custom=data.get("custom", {})
        )


class IEntity(ABC):
    """
    Base interface for all entities in the Digital Twin Platform.
    
    All entities (Digital Twins, Services, Digital Replicas) must implement
    this interface to ensure consistent behavior and metadata management.
    """
    
    @property
    @abstractmethod
    def id(self) -> UUID:
        """Get the unique identifier of the entity."""
        pass
    
    @property
    @abstractmethod
    def metadata(self) -> BaseMetadata:
        """Get the metadata associated with the entity."""
        pass
    
    @property
    @abstractmethod
    def status(self) -> EntityStatus:
        """Get the current status of the entity."""
        pass
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the entity and prepare it for operation."""
        pass
    
    @abstractmethod
    async def start(self) -> None:
        """Start the entity operations."""
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """Stop the entity operations gracefully."""
        pass
    
    @abstractmethod
    async def terminate(self) -> None:
        """Terminate the entity and cleanup resources."""
        pass
    
    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Serialize the entity to a dictionary representation."""
        pass
    
    @abstractmethod
    def validate(self) -> bool:
        """Validate the entity configuration and state."""
        pass


class IRegistry(ABC, Generic[T]):
    """
    Base interface for all registries in the platform.
    
    Registries are responsible for managing and discovering entities
    of a specific type (Digital Twins, Services, Digital Replicas).
    """
    
    @abstractmethod
    async def register(self, entity: T) -> None:
        """Register a new entity in the registry."""
        pass
    
    @abstractmethod
    async def unregister(self, entity_id: UUID) -> None:
        """Unregister an entity from the registry."""
        pass
    
    @abstractmethod
    async def get(self, entity_id: UUID) -> T:
        """Retrieve an entity by its ID."""
        pass
    
    @abstractmethod
    async def list(
        self, 
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[T]:
        """List entities with optional filtering and pagination."""
        pass
    
    @abstractmethod
    async def exists(self, entity_id: UUID) -> bool:
        """Check if an entity exists in the registry."""
        pass
    
    @abstractmethod
    async def update(self, entity: T) -> None:
        """Update an existing entity in the registry."""
        pass
    
    @abstractmethod
    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """Count entities with optional filtering."""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check the health status of the registry."""
        pass


class IFactory(ABC, Generic[T]):
    """
    Base interface for all factories in the platform.
    
    Factories are responsible for creating and configuring entities
    according to specified templates or configurations.
    """
    
    @abstractmethod
    async def create(
        self, 
        config: Dict[str, Any], 
        metadata: Optional[BaseMetadata] = None
    ) -> T:
        """Create a new entity based on the provided configuration."""
        pass
    
    @abstractmethod
    async def create_from_template(
        self, 
        template_id: str, 
        config_overrides: Optional[Dict[str, Any]] = None,
        metadata: Optional[BaseMetadata] = None
    ) -> T:
        """Create a new entity from a predefined template."""
        pass
    
    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate the configuration before entity creation."""
        pass
    
    @abstractmethod
    def get_supported_types(self) -> List[str]:
        """Get the list of entity types this factory can create."""
        pass
    
    @abstractmethod
    def get_config_schema(self, entity_type: str) -> Dict[str, Any]:
        """Get the configuration schema for a specific entity type."""
        pass


class IProtocolAdapter(ABC):
    """
    Base interface for protocol adapters.
    
    Protocol adapters handle communication between devices and the platform
    using specific protocols (HTTP, MQTT, etc.).
    """
    
    @property
    @abstractmethod
    def protocol_name(self) -> str:
        """Get the name of the protocol this adapter handles."""
        pass
    
    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the protocol adapter is connected and ready."""
        pass
    
    @abstractmethod
    async def initialize(self, config: Dict[str, Any]) -> None:
        """Initialize the protocol adapter with configuration."""
        pass
    
    @abstractmethod
    async def connect(self) -> None:
        """Establish connection for the protocol."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the protocol."""
        pass
    
    @abstractmethod
    async def send_message(
        self, 
        destination: str, 
        message: Dict[str, Any]
    ) -> None:
        """Send a message to a specific destination."""
        pass
    
    @abstractmethod
    async def receive_message(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Receive a message with optional timeout."""
        pass
    
    @abstractmethod
    def setup_message_handler(
        self, 
        handler: callable,
        topic_pattern: Optional[str] = None
    ) -> None:
        """Setup a message handler for incoming messages."""
        pass


class IStorageAdapter(ABC, Generic[T]):
    """
    Base interface for storage adapters.
    
    Storage adapters provide abstraction over different storage backends
    (PostgreSQL, SQLite, Redis, etc.).
    """
    
    @property
    @abstractmethod
    def storage_type(self) -> str:
        """Get the type of storage this adapter handles."""
        pass
    
    @abstractmethod
    async def connect(self) -> None:
        """Connect to the storage backend."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the storage backend."""
        pass
    
    @abstractmethod
    async def save(self, entity: T) -> None:
        """Save an entity to storage."""
        pass
    
    @abstractmethod
    async def load(self, entity_id: UUID) -> T:
        """Load an entity from storage by ID."""
        pass
    
    @abstractmethod
    async def delete(self, entity_id: UUID) -> None:
        """Delete an entity from storage."""
        pass
    
    @abstractmethod
    async def query(
        self, 
        filters: Dict[str, Any],
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[T]:
        """Query entities with filters and pagination."""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check the health of the storage backend."""
        pass


class IAuthProvider(ABC):
    """
    Base interface for authentication providers.
    
    Authentication providers handle user authentication and authorization
    using different methods (JWT, OAuth2, etc.).
    """
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Get the name of the authentication provider."""
        pass
    
    @abstractmethod
    async def authenticate(
        self, 
        credentials: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Authenticate user and return authentication result."""
        pass
    
    @abstractmethod
    async def validate_token(self, token: str) -> Dict[str, Any]:
        """Validate an authentication token."""
        pass
    
    @abstractmethod
    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh an authentication token."""
        pass
    
    @abstractmethod
    async def revoke_token(self, token: str) -> None:
        """Revoke an authentication token."""
        pass
    
    @abstractmethod
    def get_user_permissions(self, user_id: UUID) -> List[str]:
        """Get user permissions."""
        pass


class ILifecycleManager(ABC, Generic[T]):
    """
    Base interface for lifecycle managers.
    
    Lifecycle managers handle the complete lifecycle of entities
    from creation to termination.
    """
    
    @abstractmethod
    async def create_entity(
        self, 
        config: Dict[str, Any], 
        metadata: Optional[BaseMetadata] = None
    ) -> T:
        """Create a new entity."""
        pass
    
    @abstractmethod
    async def start_entity(self, entity_id: UUID) -> None:
        """Start an entity."""
        pass
    
    @abstractmethod
    async def stop_entity(self, entity_id: UUID) -> None:
        """Stop an entity."""
        pass
    
    @abstractmethod
    async def restart_entity(self, entity_id: UUID) -> None:
        """Restart an entity."""
        pass
    
    @abstractmethod
    async def terminate_entity(self, entity_id: UUID) -> None:
        """Terminate an entity."""
        pass
    
    @abstractmethod
    async def get_entity_status(self, entity_id: UUID) -> EntityStatus:
        """Get the current status of an entity."""
        pass
    
    @abstractmethod
    async def monitor_entity(self, entity_id: UUID) -> Dict[str, Any]:
        """Get monitoring information for an entity."""
        pass