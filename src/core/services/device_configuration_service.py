# src/core/services/device_configuration_service.py

import asyncio
import logging
from typing import Dict, List, Any, Optional
from uuid import UUID
from datetime import datetime

from src.core.protocols.protocol_registry import get_protocol_registry, ProtocolMessage
from src.core.protocols.base_adapter import BaseProtocolAdapter
from src.utils.exceptions import ServiceError, ConfigurationError

logger = logging.getLogger(__name__)

class DeviceConfiguration:
    """Configuration for a physical device."""
    
    def __init__(
        self,
        device_id: str,
        protocol_type: str,
        adapter_id: str,
        connection_config: Dict[str, Any],
        replica_id: Optional[UUID] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.device_id = device_id
        self.protocol_type = protocol_type
        self.adapter_id = adapter_id
        self.connection_config = connection_config
        self.replica_id = replica_id
        self.metadata = metadata or {}
        self.created_at = datetime.utcnow()
        self.last_updated = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "protocol_type": self.protocol_type,
            "adapter_id": self.adapter_id,
            "connection_config": self.connection_config,
            "replica_id": str(self.replica_id) if self.replica_id else None,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat()
        }


class DeviceConfigurationService:
    """
    Service per gestire le configurazioni dei dispositivi fisici.
    Orchestrates protocol adapters and device connections.
    """
    
    def __init__(self):
        self.device_configs: Dict[str, DeviceConfiguration] = {}
        self.replica_devices: Dict[UUID, List[str]] = {}  # replica_id -> [device_ids]
        self.protocol_registry = None
        self._initialized = False
        
        logger.info("Device Configuration Service initialized")
    
    async def initialize(self) -> None:
        """Initialize the service."""
        if self._initialized:
            return
        
        self.protocol_registry = await get_protocol_registry()
        
        # Add message handler to route incoming messages
        await self.protocol_registry.add_message_handler_to_all(
            self._handle_device_message
        )
        
        self._initialized = True
        logger.info("Device Configuration Service ready")
    
    async def create_protocol_adapter(
        self,
        adapter_id: str,
        protocol_type: str,
        adapter_config: Dict[str, Any]
    ) -> BaseProtocolAdapter:
        """Create a new protocol adapter."""
        if not self._initialized:
            await self.initialize()
        
        try:
            adapter = await self.protocol_registry.create_adapter(
                adapter_id, protocol_type, adapter_config
            )
            logger.info(f"Created protocol adapter: {adapter_id} ({protocol_type})")
            return adapter
            
        except Exception as e:
            logger.error(f"Failed to create protocol adapter {adapter_id}: {e}")
            raise ServiceError(f"Protocol adapter creation failed: {e}")
    
    async def register_device(
        self,
        device_id: str,
        protocol_type: str,
        adapter_id: str,
        connection_config: Dict[str, Any],
        replica_id: Optional[UUID] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> DeviceConfiguration:
        """Register a new device configuration."""
        if not self._initialized:
            await self.initialize()
        
        if device_id in self.device_configs:
            raise ConfigurationError(f"Device {device_id} already registered")
        
        # Validate adapter exists
        adapter = await self.protocol_registry.get_adapter(adapter_id)
        if not adapter:
            raise ConfigurationError(f"Protocol adapter {adapter_id} not found")
        
        if adapter.protocol_name != protocol_type:
            raise ConfigurationError(
                f"Protocol mismatch: adapter {adapter_id} is {adapter.protocol_name}, "
                f"but {protocol_type} was requested"
            )
        
        # Create device configuration
        device_config = DeviceConfiguration(
            device_id=device_id,
            protocol_type=protocol_type,
            adapter_id=adapter_id,
            connection_config=connection_config,
            replica_id=replica_id,
            metadata=metadata
        )
        
        # Add device to protocol adapter
        try:
            await self.protocol_registry.add_device_to_adapter(
                device_id, adapter_id, connection_config
            )
            
            # Store configuration
            self.device_configs[device_id] = device_config
            
            # Update replica mapping
            if replica_id:
                if replica_id not in self.replica_devices:
                    self.replica_devices[replica_id] = []
                self.replica_devices[replica_id].append(device_id)
            
            logger.info(f"Registered device {device_id} with adapter {adapter_id}")
            return device_config
            
        except Exception as e:
            logger.error(f"Failed to register device {device_id}: {e}")
            raise ServiceError(f"Device registration failed: {e}")
    
    async def unregister_device(self, device_id: str) -> None:
        """Unregister a device."""
        if device_id not in self.device_configs:
            raise ConfigurationError(f"Device {device_id} not registered")
        
        device_config = self.device_configs[device_id]
        
        # Remove from protocol adapter
        await self.protocol_registry.remove_device(device_id)
        
        # Remove from replica mapping
        if device_config.replica_id and device_config.replica_id in self.replica_devices:
            devices = self.replica_devices[device_config.replica_id]
            if device_id in devices:
                devices.remove(device_id)
                if not devices:
                    del self.replica_devices[device_config.replica_id]
        
        # Remove configuration
        del self.device_configs[device_id]
        
        logger.info(f"Unregistered device {device_id}")
    
    async def update_device_config(
        self,
        device_id: str,
        new_connection_config: Dict[str, Any],
        new_metadata: Optional[Dict[str, Any]] = None
    ) -> DeviceConfiguration:
        """Update device connection configuration."""
        if device_id not in self.device_configs:
            raise ConfigurationError(f"Device {device_id} not registered")
        
        device_config = self.device_configs[device_id]
        
        # Remove and re-add device with new config
        await self.protocol_registry.remove_device(device_id)
        await self.protocol_registry.add_device_to_adapter(
            device_id, device_config.adapter_id, new_connection_config
        )
        
        # Update stored configuration
        device_config.connection_config = new_connection_config
        device_config.last_updated = datetime.utcnow()
        if new_metadata:
            device_config.metadata.update(new_metadata)
        
        logger.info(f"Updated configuration for device {device_id}")
        return device_config
    
    async def send_command_to_device(
        self,
        device_id: str,
        command_data: Dict[str, Any],
        command_type: str = "command"
    ) -> None:
        """Send command to a specific device."""
        if device_id not in self.device_configs:
            raise ConfigurationError(f"Device {device_id} not registered")
        
        message = ProtocolMessage(
            device_id=device_id,
            data=command_data,
            message_type=command_type,
            metadata={"source": "digital_replica", "timestamp": datetime.utcnow().isoformat()}
        )
        
        try:
            await self.protocol_registry.send_message_to_device(device_id, message)
            logger.debug(f"Command sent to device {device_id}")
            
        except Exception as e:
            logger.error(f"Failed to send command to device {device_id}: {e}")
            raise ServiceError(f"Command delivery failed: {e}")
    
    async def get_replica_devices(self, replica_id: UUID) -> List[DeviceConfiguration]:
        """Get all devices associated with a replica."""
        device_ids = self.replica_devices.get(replica_id, [])
        return [self.device_configs[device_id] for device_id in device_ids]
    
    async def get_device_config(self, device_id: str) -> Optional[DeviceConfiguration]:
        """Get device configuration."""
        return self.device_configs.get(device_id)
    
    async def list_devices(self, replica_id: Optional[UUID] = None) -> List[DeviceConfiguration]:
        """List all devices or devices for a specific replica."""
        if replica_id:
            return await self.get_replica_devices(replica_id)
        
        return list(self.device_configs.values())
    
    async def get_protocol_status(self) -> Dict[str, Any]:
        """Get status of all protocol adapters."""
        if not self.protocol_registry:
            return {"error": "Protocol registry not initialized"}
        
        return self.protocol_registry.get_registry_status()
    
    async def health_check(self) -> Dict[str, Any]:
        """Check health of device configuration service."""
        service_health = {
            "service_status": "healthy",
            "total_devices": len(self.device_configs),
            "total_replicas": len(self.replica_devices),
            "initialized": self._initialized
        }
        
        if self.protocol_registry:
            protocol_health = await self.protocol_registry.health_check()
            service_health["protocols"] = protocol_health
        
        return service_health
    
    async def _handle_device_message(self, message: ProtocolMessage) -> None:
        """Handle incoming message from devices."""
        device_config = self.device_configs.get(message.device_id)
        if not device_config:
            logger.warning(f"Received message from unregistered device: {message.device_id}")
            return
        
        # If device is associated with a replica, route message there
        if device_config.replica_id:
            # Import here to avoid circular imports
            from src.layers.virtualization.dr_registry import get_dr_registry
            
            try:
                registry = await get_dr_registry()
                
                # Convert ProtocolMessage to DeviceData
                from src.core.interfaces.replica import DeviceData, DataQuality
                
                device_data = DeviceData(
                    device_id=message.device_id,
                    timestamp=message.timestamp,
                    data=message.data,
                    data_type=message.message_type,
                    quality=DataQuality.HIGH,  # TODO: Implement quality assessment
                    metadata=message.metadata
                )
                
                # Record in registry and forward to replica
                await registry.record_device_data(
                    message.device_id,
                    device_config.replica_id,
                    device_data.quality
                )
                
                # Get replica and send data
                replica = await registry.get_digital_replica(device_config.replica_id)
                if replica:
                    await replica.receive_device_data(device_data)
                    logger.debug(f"Routed message from {message.device_id} to replica {device_config.replica_id}")
                
            except Exception as e:
                logger.error(f"Failed to route message from device {message.device_id}: {e}")
        
        logger.debug(f"Processed message from device {message.device_id}")


# Global service instance
_device_config_service: Optional[DeviceConfigurationService] = None

async def get_device_configuration_service() -> DeviceConfigurationService:
    """Get the global device configuration service instance."""
    global _device_config_service
    if _device_config_service is None:
        _device_config_service = DeviceConfigurationService()
        await _device_config_service.initialize()
    return _device_config_service