# src/core/protocols/base_adapter.py

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Callable, Awaitable
from uuid import UUID
from datetime import datetime
from enum import Enum
import asyncio
import logging

logger = logging.getLogger(__name__)

class ProtocolStatus(Enum):
    """Status of a protocol adapter."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    RECONNECTING = "reconnecting"

class ProtocolMessage:
    """Standard message format across all protocols."""
    
    def __init__(
        self,
        device_id: str,
        data: Dict[str, Any],
        timestamp: Optional[datetime] = None,
        message_type: str = "data",
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.device_id = device_id
        self.data = data
        self.timestamp = timestamp or datetime.utcnow()
        self.message_type = message_type
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "message_type": self.message_type,
            "metadata": self.metadata
        }

class BaseProtocolAdapter(ABC):
    """Base class for all protocol adapters."""
    
    def __init__(self, adapter_id: str, config: Dict[str, Any]):
        self.adapter_id = adapter_id
        self.config = config
        self.status = ProtocolStatus.DISCONNECTED
        self.connected_devices: Dict[str, Dict[str, Any]] = {}
        self.message_handlers: List[Callable[[ProtocolMessage], Awaitable[None]]] = []
        self.connection_time: Optional[datetime] = None
        self.last_activity: Optional[datetime] = None
        self.message_count = 0
        self.error_count = 0
        
        logger.info(f"Protocol adapter {self.adapter_id} ({self.protocol_name}) initialized")
    
    @property
    @abstractmethod
    def protocol_name(self) -> str:
        """Nome del protocollo."""
        pass
    
    @property
    def is_connected(self) -> bool:
        """Check if adapter is connected."""
        return self.status == ProtocolStatus.CONNECTED
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the protocol adapter."""
        pass
    
    @abstractmethod
    async def connect(self) -> None:
        """Establish connection for the protocol."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close protocol connection."""
        pass
    
    @abstractmethod
    async def send_message(self, device_id: str, message: ProtocolMessage) -> None:
        """Send message to a specific device."""
        pass
    
    @abstractmethod
    async def add_device(self, device_id: str, device_config: Dict[str, Any]) -> None:
        """Add a device to this protocol adapter."""
        pass
    
    @abstractmethod
    async def remove_device(self, device_id: str) -> None:
        """Remove a device from this protocol adapter."""
        pass
    
    async def add_message_handler(self, handler: Callable[[ProtocolMessage], Awaitable[None]]) -> None:
        """Add a message handler for incoming messages."""
        self.message_handlers.append(handler)
    
    async def _handle_incoming_message(self, message: ProtocolMessage) -> None:
        """Process incoming message through all handlers."""
        self.message_count += 1
        self.last_activity = datetime.utcnow()
        
        for handler in self.message_handlers:
            try:
                await handler(message)
            except Exception as e:
                logger.error(f"Error in message handler: {e}")
                self.error_count += 1
    
    def get_adapter_info(self) -> Dict[str, Any]:
        """Get comprehensive adapter information."""
        return {
            "adapter_id": self.adapter_id,
            "protocol_name": self.protocol_name,
            "status": self.status.value,
            "connected_devices": len(self.connected_devices),
            "devices": list(self.connected_devices.keys()),
            "connection_time": self.connection_time.isoformat() if self.connection_time else None,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
            "message_count": self.message_count,
            "error_count": self.error_count,
            "config": {k: v for k, v in self.config.items() if k not in ["password", "token", "secret"]}
        }