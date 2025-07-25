# src/layers/application/api/device_config.py

from fastapi import APIRouter, Depends, HTTPException, Path, Body, status
from typing import Dict, List, Any, Optional
from uuid import UUID
import logging

from src.layers.application.schemas.device_config import (
    ProtocolAdapterConfig, DeviceConnectionConfig, DeviceCommandRequest,
    DeviceResponse, ProtocolAdapterResponse, ProtocolType
)
from src.layers.application.api import get_gateway
from src.layers.application.api_gateway import APIGateway
from src.core.services.device_configuration_service import get_device_configuration_service
from src.utils.exceptions import ServiceError, ConfigurationError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/devices",
    tags=["Device Configuration"],
    responses={
        404: {"description": "Device or adapter not found"},
        400: {"description": "Invalid configuration"},
        500: {"description": "Internal server error"}
    }
)

# =========================
# PROTOCOL ADAPTERS
# =========================

@router.post("/adapters", summary="Create Protocol Adapter", status_code=status.HTTP_201_CREATED)
async def create_protocol_adapter(
    adapter_config: ProtocolAdapterConfig = Body(...),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """
    Create a new protocol adapter.
    
    Protocol adapters handle communication with devices using specific protocols.
    You need to create adapters before registering devices.
    """
    try:
        device_service = await get_device_configuration_service()
        
        adapter = await device_service.create_protocol_adapter(
            adapter_config.adapter_id,
            adapter_config.protocol_type.value,
            adapter_config.config
        )
        
        return {
            "message": f"Protocol adapter {adapter_config.adapter_id} created successfully",
            "adapter_id": adapter_config.adapter_id,
            "protocol_type": adapter_config.protocol_type.value,
            "status": "created"
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.get("/adapters", summary="List Protocol Adapters")
async def list_protocol_adapters(
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get list of all protocol adapters and their status."""
    try:
        device_service = await get_device_configuration_service()
        status_info = await device_service.get_protocol_status()
        
        adapters = []
        for adapter_id, adapter_info in status_info.get("adapters", {}).items():
            adapters.append(ProtocolAdapterResponse(**adapter_info))
        
        return {
            "total_adapters": status_info.get("total_adapters", 0),
            "total_devices": status_info.get("total_devices", 0),
            "available_protocols": status_info.get("available_protocols", []),
            "adapters": adapters
        }
        
    except Exception as e:
        logger.error(f"Failed to list protocol adapters: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve adapters: {e}"
        )

@router.delete("/adapters/{adapter_id}", summary="Remove Protocol Adapter")
async def remove_protocol_adapter(
    adapter_id: str = Path(..., description="Protocol adapter ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, str]:
    """Remove a protocol adapter and disconnect all its devices."""
    try:
        device_service = await get_device_configuration_service()
        await device_service.protocol_registry.remove_adapter(adapter_id)
        
        return {
            "message": f"Protocol adapter {adapter_id} removed successfully",
            "adapter_id": adapter_id,
            "status": "removed"
        }
        
    except Exception as e:
        logger.error(f"Failed to remove adapter {adapter_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove adapter: {e}"
        )

# =========================
# DEVICE CONFIGURATION
# =========================

@router.post("/register", summary="Register Device", status_code=status.HTTP_201_CREATED)
async def register_device(
    device_config: DeviceConnectionConfig = Body(...),
    replica_id: Optional[UUID] = Body(None, description="Associate with Digital Replica"),
    gateway: APIGateway = Depends(get_gateway)
) -> DeviceResponse:
    """
    Register a new physical device with its connection configuration.
    
    The device will be added to the specified protocol adapter and can optionally
    be associated with a Digital Replica for automatic data routing.
    """
    try:
        device_service = await get_device_configuration_service()
        
        config = await device_service.register_device(
            device_id=device_config.device_id,
            protocol_type=device_config.protocol_type.value,
            adapter_id=device_config.adapter_id,
            connection_config=device_config.connection_config,
            replica_id=replica_id,
            metadata=device_config.metadata
        )
        
        return DeviceResponse(**config.to_dict())
        
    except ConfigurationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.get("/{device_id}", summary="Get Device Configuration")
async def get_device_configuration(
    device_id: str = Path(..., description="Device ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> DeviceResponse:
    """Get configuration for a specific device."""
    try:
        device_service = await get_device_configuration_service()
        config = await device_service.get_device_config(device_id)
        
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Device {device_id} not found"
            )
        
        return DeviceResponse(**config.to_dict())
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get device {device_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve device: {e}"
        )

@router.put("/{device_id}/config", summary="Update Device Configuration")
async def update_device_configuration(
    device_id: str = Path(..., description="Device ID"),
    new_connection_config: Dict[str, Any] = Body(..., description="New connection configuration"),
    new_metadata: Optional[Dict[str, Any]] = Body(None, description="Updated metadata"),
    gateway: APIGateway = Depends(get_gateway)
) -> DeviceResponse:
    """Update device connection configuration."""
    try:
        device_service = await get_device_configuration_service()
        
        config = await device_service.update_device_config(
            device_id, new_connection_config, new_metadata
        )
        
        return DeviceResponse(**config.to_dict())
        
    except ConfigurationError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to update device {device_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update device: {e}"
        )

@router.delete("/{device_id}", summary="Unregister Device")
async def unregister_device(
    device_id: str = Path(..., description="Device ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, str]:
    """Unregister a device and remove it from its protocol adapter."""
    try:
        device_service = await get_device_configuration_service()
        await device_service.unregister_device(device_id)
        
        return {
            "message": f"Device {device_id} unregistered successfully",
            "device_id": device_id,
            "status": "unregistered"
        }
        
    except ConfigurationError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to unregister device {device_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to unregister device: {e}"
        )

@router.post("/{device_id}/command", summary="Send Command to Device")
async def send_device_command(
    device_id: str = Path(..., description="Device ID"),
    command: DeviceCommandRequest = Body(...),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Send a command to a physical device through its protocol adapter."""
    try:
        device_service = await get_device_configuration_service()
        
        await device_service.send_command_to_device(
            device_id, command.command_data, command.command_type
        )
        
        return {
            "message": f"Command sent to device {device_id}",
            "device_id": device_id,
            "command_type": command.command_type,
            "status": "sent"
        }
        
    except ConfigurationError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except ServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.get("", summary="List All Devices")
async def list_devices(
    replica_id: Optional[UUID] = None,
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """List all registered devices or devices for a specific replica."""
    try:
        device_service = await get_device_configuration_service()
        devices = await device_service.list_devices(replica_id)
        
        device_responses = [DeviceResponse(**device.to_dict()) for device in devices]
        
        return {
            "total_devices": len(device_responses),
            "replica_id": str(replica_id) if replica_id else None,
            "devices": device_responses
        }
        
    except Exception as e:
        logger.error(f"Failed to list devices: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve devices: {e}"
        )

# =========================
# HEALTH & STATUS
# =========================

@router.get("/health", summary="Device Service Health Check")
async def device_service_health(
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Check health status of device configuration service and all protocol adapters."""
    try:
        device_service = await get_device_configuration_service()
        health_status = await device_service.health_check()
        
        return health_status
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "service_status": "error",
            "error": str(e),
            "initialized": False
        }