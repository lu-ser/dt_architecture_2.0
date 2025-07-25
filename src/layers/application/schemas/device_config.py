# src/layers/application/schemas/device_config.py

from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List
from enum import Enum
from uuid import UUID

class ProtocolType(str, Enum):
    """Supported protocol types."""
    HTTP = "http"
    MQTT = "mqtt"
    TCP = "tcp"
    WEBSOCKET = "websocket"
    COAP = "coap"

class ProtocolAdapterConfig(BaseModel):
    """Configuration for creating a protocol adapter."""
    adapter_id: str = Field(..., description="Unique identifier for the adapter")
    protocol_type: ProtocolType = Field(..., description="Type of protocol")
    config: Dict[str, Any] = Field(..., description="Protocol-specific configuration")
    
    class Config:
        schema_extra = {
            "examples": [
                {
                    "adapter_id": "main_http_adapter",
                    "protocol_type": "http",
                    "config": {
                        "base_url": "http://devices.local",
                        "timeout": 30,
                        "polling_interval": 60
                    }
                },
                {
                    "adapter_id": "iot_mqtt_adapter", 
                    "protocol_type": "mqtt",
                    "config": {
                        "broker": "mqtt.iot-platform.com",
                        "port": 1883,
                        "username": "iot_user",
                        "password": "iot_pass",
                        "keepalive": 60
                    }
                }
            ]
        }

class HTTPDeviceConfig(BaseModel):
    """HTTP-specific device configuration."""
    host: str = Field(..., description="Device IP address or hostname")
    port: int = Field(..., description="Device port", ge=1, le=65535)
    endpoint: str = Field("/data", description="API endpoint path")
    enable_polling: bool = Field(True, description="Enable automatic polling")
    polling_interval: int = Field(30, description="Polling interval in seconds", ge=1)
    timeout: int = Field(10, description="Request timeout in seconds", ge=1)
    authentication: Optional[Dict[str, Any]] = Field(None, description="Authentication config")
    
    @validator('endpoint')
    def endpoint_must_start_with_slash(cls, v):
        if not v.startswith('/'):
            return f'/{v}'
        return v

class MQTTDeviceConfig(BaseModel):
    """MQTT-specific device configuration."""
    topic: str = Field(..., description="MQTT topic for device data")
    command_topic: Optional[str] = Field(None, description="Topic for sending commands")
    qos: int = Field(1, description="MQTT QoS level", ge=0, le=2)
    retain: bool = Field(False, description="Retain MQTT messages")
    device_metadata: Optional[Dict[str, Any]] = Field(None, description="Device-specific metadata")

class DeviceConnectionConfig(BaseModel):
    """Generic device connection configuration."""
    device_id: str = Field(..., description="Unique device identifier")
    adapter_id: str = Field(..., description="Protocol adapter to use")
    protocol_type: ProtocolType = Field(..., description="Protocol type")
    connection_config: Dict[str, Any] = Field(..., description="Protocol-specific configuration")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional device metadata")
    
    class Config:
        schema_extra = {
            "examples": [
                {
                    "device_id": "sensor-001",
                    "adapter_id": "main_http_adapter",
                    "protocol_type": "http",
                    "connection_config": {
                        "host": "192.168.1.100",
                        "port": 8080,
                        "endpoint": "/sensor/data",
                        "enable_polling": True,
                        "polling_interval": 30
                    },
                    "metadata": {
                        "location": "Building A, Floor 2",
                        "sensor_type": "temperature"
                    }
                }
            ]
        }

class DeviceCommandRequest(BaseModel):
    """Request to send command to device."""
    command_data: Dict[str, Any] = Field(..., description="Command payload")
    command_type: str = Field("command", description="Type of command")
    timeout: Optional[int] = Field(30, description="Command timeout in seconds")

class DeviceResponse(BaseModel):
    """Device configuration response."""
    device_id: str
    protocol_type: str
    adapter_id: str
    connection_config: Dict[str, Any]
    replica_id: Optional[str]
    metadata: Dict[str, Any]
    created_at: str
    last_updated: str

class ProtocolAdapterResponse(BaseModel):
    """Protocol adapter status response."""
    adapter_id: str
    protocol_name: str
    status: str
    connected_devices: int
    devices: List[str]
    connection_time: Optional[str]
    last_activity: Optional[str]
    message_count: int
    error_count: int
    config: Dict[str, Any]