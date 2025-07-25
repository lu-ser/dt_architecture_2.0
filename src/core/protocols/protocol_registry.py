# src/core/protocols/protocol_registry.py

from typing import Dict, List, Type, Optional, Any, Callable, Awaitable
import asyncio
import logging

from src.core.protocols.base_adapter import BaseProtocolAdapter, ProtocolMessage
from src.core.protocols.http_adapter import HTTPProtocolAdapter
from src.core.protocols.mqtt_adapter import MQTTProtocolAdapter

logger = logging.getLogger(__name__)

class ProtocolRegistry:
    """
    Centralized registry for all protocol adapters.
    Manages protocol lifecycle and device routing.
    """
    
    def __init__(self):
        self.adapters: Dict[str, BaseProtocolAdapter] = {}
        self.protocol_types: Dict[str, Type[BaseProtocolAdapter]] = {}
        self.device_to_adapter: Dict[str, str] = {}  # device_id -> adapter_id
        self._initialized = False
        
        # Register built-in protocol types
        self._register_protocol_types()
        
        logger.info("Protocol registry initialized")
    
    def _register_protocol_types(self) -> None:
        """Register built-in protocol adapter types."""
        self.protocol_types["http"] = HTTPProtocolAdapter
        self.protocol_types["mqtt"] = MQTTProtocolAdapter
        # Future: TCP, WebSocket, CoAP, etc.
    
    async def initialize(self) -> None:
        """Initialize the protocol registry."""
        if self._initialized:
            return
        
        self._initialized = True
        logger.info("Protocol registry initialized")
    
    async def create_adapter(
        self,
        adapter_id: str,
        protocol_type: str,
        config: Dict[str, Any]
    ) -> BaseProtocolAdapter:
        """Create and register a new protocol adapter."""
        
        if protocol_type not in self.protocol_types:
            raise ValueError(f"Unknown protocol type: {protocol_type}")
        
        if adapter_id in self.adapters:
            raise ValueError(f"Adapter {adapter_id} already exists")
        
        # Create adapter instance
        adapter_class = self.protocol_types[protocol_type]
        adapter = adapter_class(adapter_id, config)
        
        # Initialize and connect
        await adapter.initialize()
        await adapter.connect()
        
        # Register in registry
        self.adapters[adapter_id] = adapter
        
        logger.info(f"Created and registered {protocol_type} adapter: {adapter_id}")
        return adapter
    
    async def get_adapter(self, adapter_id: str) -> Optional[BaseProtocolAdapter]:
        """Get adapter by ID."""
        return self.adapters.get(adapter_id)
    
    async def remove_adapter(self, adapter_id: str) -> None:
        """Remove and disconnect adapter."""
        if adapter_id in self.adapters:
            adapter = self.adapters[adapter_id]
            
            # Remove all devices from this adapter
            devices_to_remove = [
                device_id for device_id, aid in self.device_to_adapter.items()
                if aid == adapter_id
            ]
            for device_id in devices_to_remove:
                await self.remove_device(device_id)
            
            # Disconnect and remove adapter
            await adapter.disconnect()
            del self.adapters[adapter_id]
            
            logger.info(f"Removed adapter: {adapter_id}")
    
    async def add_device_to_adapter(
        self,
        device_id: str,
        adapter_id: str,
        device_config: Dict[str, Any]
    ) -> None:
        """Add device to specific adapter."""
        
        adapter = self.adapters.get(adapter_id)
        if not adapter:
            raise ValueError(f"Adapter {adapter_id} not found")
        
        await adapter.add_device(device_id, device_config)
        self.device_to_adapter[device_id] = adapter_id
        
        logger.info(f"Added device {device_id} to adapter {adapter_id}")
    
    async def remove_device(self, device_id: str) -> None:
        """Remove device from its adapter."""
        adapter_id = self.device_to_adapter.get(device_id)
        if adapter_id and adapter_id in self.adapters:
            await self.adapters[adapter_id].remove_device(device_id)
        
        if device_id in self.device_to_adapter:
            del self.device_to_adapter[device_id]
        
        logger.info(f"Removed device {device_id}")
    
    async def send_message_to_device(
        self,
        device_id: str,
        message: ProtocolMessage
    ) -> None:
        """Send message to device through its adapter."""
        adapter_id = self.device_to_adapter.get(device_id)
        if not adapter_id:
            raise ValueError(f"Device {device_id} not registered")
        
        adapter = self.adapters.get(adapter_id)
        if not adapter:
            raise ValueError(f"Adapter {adapter_id} not found")
        
        await adapter.send_message(device_id, message)
    
    async def add_message_handler_to_all(
        self,
        handler: Callable[[ProtocolMessage], Awaitable[None]]
    ) -> None:
        """Add message handler to all adapters."""
        for adapter in self.adapters.values():
            await adapter.add_message_handler(handler)
    
    def get_registry_status(self) -> Dict[str, Any]:
        """Get comprehensive registry status."""
        return {
            "total_adapters": len(self.adapters),
            "total_devices": len(self.device_to_adapter),
            "available_protocols": list(self.protocol_types.keys()),
            "adapters": {
                adapter_id: adapter.get_adapter_info()
                for adapter_id, adapter in self.adapters.items()
            },
            "device_routing": self.device_to_adapter
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Check health of all adapters."""
        health_status = {
            "overall_status": "healthy",
            "adapters": {}
        }
        
        unhealthy_count = 0
        for adapter_id, adapter in self.adapters.items():
            if adapter.is_connected:
                health_status["adapters"][adapter_id] = "connected"
            else:
                health_status["adapters"][adapter_id] = "disconnected"
                unhealthy_count += 1
        
        if unhealthy_count > 0:
            health_status["overall_status"] = f"warning: {unhealthy_count} adapters disconnected"
        
        return health_status


# Global registry instance
_protocol_registry: Optional[ProtocolRegistry] = None

async def get_protocol_registry() -> ProtocolRegistry:
    """Get the global protocol registry instance."""
    global _protocol_registry
    if _protocol_registry is None:
        _protocol_registry = ProtocolRegistry()
        await _protocol_registry.initialize()
    return _protocol_registry