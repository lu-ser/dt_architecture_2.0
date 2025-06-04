from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, TypeVar, Generic, Union
from uuid import UUID
from enum import Enum
T = TypeVar('T')
K = TypeVar('K')

class EntityStatus(Enum):
    CREATED = 'created'
    INITIALIZING = 'initializing'
    ACTIVE = 'active'
    INACTIVE = 'inactive'
    ERROR = 'error'
    SUSPENDED = 'suspended'
    TERMINATED = 'terminated'

class BaseMetadata:

    def __init__(self, entity_id: UUID, timestamp: datetime, version: str, created_by: UUID, custom: Optional[Dict[str, Any]]=None):
        self.id = entity_id
        self.timestamp = timestamp
        self.version = version
        self.created_by = created_by
        self.custom = custom or {}

    def to_dict(self) -> Dict[str, Any]:
        return {'id': str(self.id), 'timestamp': self.timestamp.isoformat(), 'version': self.version, 'created_by': str(self.created_by), 'custom': self.custom}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BaseMetadata':
        return cls(entity_id=UUID(data['id']), timestamp=datetime.fromisoformat(data['timestamp']), version=data['version'], created_by=UUID(data['created_by']), custom=data.get('custom', {}))

class IEntity(ABC):

    @property
    @abstractmethod
    def id(self) -> UUID:
        pass

    @property
    @abstractmethod
    def metadata(self) -> BaseMetadata:
        pass

    @property
    @abstractmethod
    def status(self) -> EntityStatus:
        pass

    @abstractmethod
    async def initialize(self) -> None:
        pass

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass

    @abstractmethod
    async def terminate(self) -> None:
        pass

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def validate(self) -> bool:
        pass

class IRegistry(ABC, Generic[T]):

    @abstractmethod
    async def register(self, entity: T) -> None:
        pass

    @abstractmethod
    async def unregister(self, entity_id: UUID) -> None:
        pass

    @abstractmethod
    async def get(self, entity_id: UUID) -> T:
        pass

    @abstractmethod
    async def list(self, filters: Optional[Dict[str, Any]]=None, limit: Optional[int]=None, offset: Optional[int]=None) -> List[T]:
        pass

    @abstractmethod
    async def exists(self, entity_id: UUID) -> bool:
        pass

    @abstractmethod
    async def update(self, entity: T) -> None:
        pass

    @abstractmethod
    async def count(self, filters: Optional[Dict[str, Any]]=None) -> int:
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        pass

class IFactory(ABC, Generic[T]):

    @abstractmethod
    async def create(self, config: Dict[str, Any], metadata: Optional[BaseMetadata]=None) -> T:
        pass

    @abstractmethod
    async def create_from_template(self, template_id: str, config_overrides: Optional[Dict[str, Any]]=None, metadata: Optional[BaseMetadata]=None) -> T:
        pass

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> bool:
        pass

    @abstractmethod
    def get_supported_types(self) -> List[str]:
        pass

    @abstractmethod
    def get_config_schema(self, entity_type: str) -> Dict[str, Any]:
        pass

class IProtocolAdapter(ABC):

    @property
    @abstractmethod
    def protocol_name(self) -> str:
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        pass

    @abstractmethod
    async def initialize(self, config: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    @abstractmethod
    async def send_message(self, destination: str, message: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def receive_message(self, timeout: Optional[float]=None) -> Dict[str, Any]:
        pass

    @abstractmethod
    def setup_message_handler(self, handler: callable, topic_pattern: Optional[str]=None) -> None:
        pass

class IStorageAdapter(ABC, Generic[T]):

    @property
    @abstractmethod
    def storage_type(self) -> str:
        pass

    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    @abstractmethod
    async def save(self, entity: T) -> None:
        pass

    @abstractmethod
    async def load(self, entity_id: UUID) -> T:
        pass

    @abstractmethod
    async def delete(self, entity_id: UUID) -> None:
        pass

    @abstractmethod
    async def query(self, filters: Dict[str, Any], limit: Optional[int]=None, offset: Optional[int]=None) -> List[T]:
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        pass

class IAuthProvider(ABC):

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @abstractmethod
    async def authenticate(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def validate_token(self, token: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def revoke_token(self, token: str) -> None:
        pass

    @abstractmethod
    def get_user_permissions(self, user_id: UUID) -> List[str]:
        pass

class ILifecycleManager(ABC, Generic[T]):

    @abstractmethod
    async def create_entity(self, config: Dict[str, Any], metadata: Optional[BaseMetadata]=None) -> T:
        pass

    @abstractmethod
    async def start_entity(self, entity_id: UUID) -> None:
        pass

    @abstractmethod
    async def stop_entity(self, entity_id: UUID) -> None:
        pass

    @abstractmethod
    async def restart_entity(self, entity_id: UUID) -> None:
        pass

    @abstractmethod
    async def terminate_entity(self, entity_id: UUID) -> None:
        pass

    @abstractmethod
    async def get_entity_status(self, entity_id: UUID) -> EntityStatus:
        pass

    @abstractmethod
    async def monitor_entity(self, entity_id: UUID) -> Dict[str, Any]:
        pass