# src/core/protocols/mqtt_adapter.py

import asyncio
from datetime import datetime
from typing import Dict, Any
import json
import logging

from .base_adapter import BaseProtocolAdapter, ProtocolStatus, ProtocolMessage

logger = logging.getLogger(__name__)

class MQTTProtocolAdapter(BaseProtocolAdapter):
    """MQTT Protocol Adapter for device communication."""
    
    @property
    def protocol_name(self) -> str:
        return "mqtt"
    
    async def initialize(self) -> None:
        """Initialize MQTT adapter."""
        self.broker_host = self.config.get("broker", "localhost")
        self.broker_port = self.config.get("port", 1883)
        self.username = self.config.get("username")
        self.password = self.config.get("password")
        self.keepalive = self.config.get("keepalive", 60)
        self.subscriptions: Dict[str, str] = {}  # device_id -> topic
        
        logger.info(f"MQTT adapter {self.adapter_id} initialized for broker {self.broker_host}:{self.broker_port}")
    
    async def connect(self) -> None:
        """Connect to MQTT broker."""
        try:
            self.status = ProtocolStatus.CONNECTING
            
            # In production: create actual MQTT client connection
            # For now: simulate connection
            await asyncio.sleep(0.2)  # Simulate connection time
            
            self.status = ProtocolStatus.CONNECTED
            self.connection_time = datetime.utcnow()
            logger.info(f"MQTT adapter {self.adapter_id} connected to {self.broker_host}:{self.broker_port}")
            
        except Exception as e:
            self.status = ProtocolStatus.ERROR
            self.error_count += 1
            logger.error(f"MQTT adapter {self.adapter_id} connection failed: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        self.status = ProtocolStatus.DISCONNECTED
        self.subscriptions.clear()
        logger.info(f"MQTT adapter {self.adapter_id} disconnected")
    
    async def add_device(self, device_id: str, device_config: Dict[str, Any]) -> None:
        """Add MQTT device and subscribe to its topic."""
        self.connected_devices[device_id] = device_config
        
        # Subscribe to device topic
        topic = device_config.get("topic", f"devices/{device_id}/data")
        self.subscriptions[device_id] = topic
        
        # In production: actually subscribe to MQTT topic
        logger.info(f"Added MQTT device {device_id} with topic {topic}")
    
    async def remove_device(self, device_id: str) -> None:
        """Remove MQTT device and unsubscribe."""
        if device_id in self.subscriptions:
            topic = self.subscriptions[device_id]
            # In production: unsubscribe from MQTT topic
            del self.subscriptions[device_id]
            logger.info(f"Unsubscribed from topic {topic} for device {device_id}")
        
        if device_id in self.connected_devices:
            del self.connected_devices[device_id]
    
    async def send_message(self, device_id: str, message: ProtocolMessage) -> None:
        """Publish message to MQTT topic."""
        if not self.is_connected:
            raise ConnectionError("MQTT adapter not connected")
        
        device_config = self.connected_devices.get(device_id)
        if not device_config:
            raise ValueError(f"Device {device_id} not found in MQTT adapter")
        
        topic = device_config.get("command_topic", f"devices/{device_id}/commands")
        
        try:
            # In production: actually publish to MQTT
            payload = json.dumps(message.to_dict())
            logger.debug(f"Published message to MQTT topic {topic} for device {device_id}")
            
        except Exception as e:
            self.error_count += 1
            logger.error(f"Failed to publish MQTT message for device {device_id}: {e}")
            raise