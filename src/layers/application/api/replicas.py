"""
Digital Replicas API endpoints for the Digital Twin Platform.

This module provides REST API endpoints for managing Digital Replicas,
including CRUD operations, device management, data aggregation, and container deployment.

LOCATION: src/layers/application/api/replicas.py
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body, status
from pydantic import BaseModel, Field, validator

from src.layers.application.api_gateway import APIGateway
from src.layers.application.api import get_gateway
from src.core.interfaces.replica import ReplicaType, DataAggregationMode
from src.utils.exceptions import EntityNotFoundError

logger = logging.getLogger(__name__)

# Create router
router = APIRouter()


# =========================
# PYDANTIC MODELS
# =========================

class ReplicaCreate(BaseModel):
    """Model for creating a Digital Replica."""
    replica_type: str = Field(..., description="Type of Digital Replica")
    template_id: Optional[str] = Field(None, description="Template ID for creation")
    parent_digital_twin_id: UUID = Field(..., description="Parent Digital Twin ID")
    device_ids: List[str] = Field(..., min_items=1, description="List of device IDs to manage")
    aggregation_mode: str = Field(..., description="Data aggregation mode")
    aggregation_config: Optional[Dict[str, Any]] = Field({}, description="Aggregation configuration")
    data_retention_policy: Optional[Dict[str, Any]] = Field({}, description="Data retention policy")
    quality_thresholds: Optional[Dict[str, float]] = Field({}, description="Data quality thresholds")
    overrides: Optional[Dict[str, Any]] = Field(None, description="Template overrides")
    
    @validator('replica_type')
    @classmethod
    def validate_replica_type(cls, v):
        try:
            ReplicaType(v)
            return v
        except ValueError:
            valid_types = [t.value for t in ReplicaType]
            raise ValueError(f"Invalid replica_type. Must be one of: {valid_types}")
    
    @validator('aggregation_mode')
    @classmethod
    def validate_aggregation_mode(cls, v):
        try:
            DataAggregationMode(v)
            return v
        except ValueError:
            valid_modes = [m.value for m in DataAggregationMode]
            raise ValueError(f"Invalid aggregation_mode. Must be one of: {valid_modes}")
    
    class Config:
        schema_extra = {
            "example": {
                "replica_type": "sensor_aggregator",
                "parent_digital_twin_id": "123e4567-e89b-12d3-a456-426614174000",
                "device_ids": ["sensor-001", "sensor-002", "sensor-003"],
                "aggregation_mode": "batch",
                "aggregation_config": {
                    "batch_size": 10,
                    "window_seconds": 60,
                    "quality_threshold": 0.7
                },
                "data_retention_policy": {
                    "retention_days": 30,
                    "cleanup_interval_hours": 24
                },
                "quality_thresholds": {
                    "min_quality": 0.6,
                    "alert_threshold": 0.4
                }
            }
        }


class DeviceData(BaseModel):
    """Model for device data sent to a Digital Replica."""
    device_id: str = Field(..., min_length=1, description="Unique device identifier")
    data: Dict[str, Any] = Field(..., description="Device data payload")
    data_type: str = Field(..., description="Type of data being sent")
    timestamp: Optional[datetime] = Field(None, description="Timestamp of the data (optional)")
    quality_hint: Optional[str] = Field(None, description="Quality hint: high, medium, low")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata about the data")
    
    @validator('quality_hint')
    @classmethod
    def validate_quality_hint(cls, v):
        if v is not None and v not in ["high", "medium", "low"]:
            raise ValueError("quality_hint must be 'high', 'medium', or 'low'")
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "device_id": "smartwatch-hr-001",
                "data": {
                    "heart_rate": 72,
                    "timestamp": "2025-07-23T10:30:00Z",
                    "value": 72,
                    "unit": "bpm",
                    "dataType": "heart_rate"
                },
                "data_type": "heart_rate_reading",
                "timestamp": "2025-07-23T10:30:00Z",
                "quality_hint": "high",
                "metadata": {
                    "battery_level": 85,
                    "signal_strength": "strong",
                    "firmware_version": "1.2.3"
                }
            }
        }


class DeviceAssociation(BaseModel):
    """Model for associating a device with a replica."""
    device_id: str = Field(..., description="Device ID to associate")
    association_type: str = Field("managed", description="Type of association")
    
    class Config:
        schema_extra = {
            "example": {
                "device_id": "smartwatch-hr-001",
                "association_type": "managed"
            }
        }


class ContainerDeployment(BaseModel):
    """Model for deploying replica as container."""
    deployment_target: str = Field(..., description="Deployment target")
    container_config: Optional[Dict[str, Any]] = Field(None, description="Container configuration")
    
    class Config:
        schema_extra = {
            "example": {
                "deployment_target": "local_docker",
                "container_config": {
                    "memory_mb": 512,
                    "cpu_cores": 0.5,
                    "health_check_interval": 30,
                    "protocols": {
                        "http": {"enabled": True, "port": 8080},
                        "mqtt": {"enabled": False}
                    }
                }
            }
        }


class ReplicaResponse(BaseModel):
    """Response model for Digital Replica operations."""
    id: UUID
    replica_type: str
    parent_digital_twin_id: UUID
    device_ids: List[str]
    aggregation_mode: str
    status: str  
    created_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# =========================
# DIGITAL REPLICA CRUD
# =========================

@router.get("/", summary="List Digital Replicas")
async def list_replicas(
    gateway: APIGateway = Depends(get_gateway),
    replica_type: Optional[str] = Query(None, description="Filter by replica type"),
    parent_digital_twin_id: Optional[UUID] = Query(None, description="Filter by parent Digital Twin"),
    device_id: Optional[str] = Query(None, description="Filter by managed device"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip")
) -> Dict[str, Any]:
    """List Digital Replicas with optional filtering."""
    try:
        # Build discovery criteria
        criteria = {}
        if replica_type:
            criteria["type"] = replica_type
        if parent_digital_twin_id:
            criteria["parent_digital_twin_id"] = str(parent_digital_twin_id)
        if device_id:
            criteria["manages_device"] = device_id
        
        # Discover replicas
        from src.layers.application.api_gateway import RequestType
        replicas = await gateway.discover_entities(RequestType.REPLICA, criteria)
        
        # Apply pagination
        total = len(replicas)
        paginated_replicas = replicas[offset:offset + limit]
        
        return {
            "replicas": paginated_replicas,
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "count": len(paginated_replicas)
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to list Digital Replicas: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list Digital Replicas: {e}"
        )


@router.post('/', summary='Create Digital Replica', response_model=ReplicaResponse)
async def create_replica(replica_data: ReplicaCreate, gateway: APIGateway = Depends(get_gateway)) -> Dict[str, Any]:
    try:
        replica_config = replica_data.dict()
        
        # FIX: Ensure parent_digital_twin_id is properly handled
        if 'parent_digital_twin_id' in replica_config:
            twin_id = replica_config['parent_digital_twin_id']
            # Pydantic already converts to UUID, but ensure it's not None
            if twin_id is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail='parent_digital_twin_id is required'
                )
        
        result = await gateway.create_replica(replica_config)
        return result
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, 
            detail=str(e)
        )
    except Exception as e:
        logger.error(f'Failed to create Digital Replica: {e}')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to create Digital Replica: {e}'
        )

@router.get("/{replica_id}", summary="Get Digital Replica", response_model=ReplicaResponse)
async def get_replica(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get a specific Digital Replica by ID."""
    try:
        return await gateway.get_replica(replica_id)
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Replica {replica_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to get Digital Replica {replica_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get Digital Replica: {e}"
        )


@router.delete("/{replica_id}", summary="Delete Digital Replica")
async def delete_replica(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, str]:
    """Delete a Digital Replica."""
    try:
        # Note: This would need to be implemented in the gateway
        return {
            "message": f"Digital Replica {replica_id} deletion requested",
            "status": "accepted"
        }
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Replica {replica_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to delete Digital Replica {replica_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete Digital Replica: {e}"
        )


# =========================
# DEVICE MANAGEMENT
# =========================

@router.get("/{replica_id}/devices", summary="Get Replica Devices")
async def get_replica_devices(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get devices managed by a Digital Replica."""
    try:
        # ✅ USA IL REGISTRY per device associations reali
        registry = gateway.virtualization_orchestrator.registry
        
        # Ottieni devices e associations
        devices = await registry.get_replica_devices(replica_id)
        
        device_details = []
        for device_id in devices:
            associations = await registry.get_device_associations(device_id)
            for assoc in associations:
                if assoc.replica_id == replica_id:
                    device_details.append(assoc.to_dict())
        
        return {
            "replica_id": str(replica_id),
            "device_count": len(devices),
            "devices": devices,
            "device_associations": device_details,
            "generated_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get devices for replica {replica_id}: {e}")
        return {
            "replica_id": str(replica_id),
            "error": f"Failed to get devices: {str(e)}",
            "generated_at": datetime.utcnow().isoformat()
        }

@router.post("/{replica_id}/restore-association", summary="Restore Replica-DT Association")
async def restore_replica_association(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Restore association between replica and digital twin after restart."""
    try:
        # Get replica info
        registry = gateway.virtualization_orchestrator.registry
        replica = await registry.get_digital_replica(replica_id)
        
        if not replica:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Digital Replica {replica_id} not found"
            )
        
        # Get parent twin ID from replica metadata
        parent_twin_id = None
        if hasattr(replica, 'parent_digital_twin_id'):
            parent_twin_id = replica.parent_digital_twin_id
        elif hasattr(replica, 'metadata') and replica.metadata:
            metadata_dict = replica.metadata.to_dict() if hasattr(replica.metadata, 'to_dict') else replica.metadata
            custom_data = metadata_dict.get('custom', {})
            parent_twin_id = custom_data.get('parent_twin_id')
            if isinstance(parent_twin_id, str):
                parent_twin_id = UUID(parent_twin_id)
        
        if not parent_twin_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot determine parent Digital Twin ID from replica"
            )
        
        # Restore association in Digital Twin orchestrator
        dt_orchestrator = gateway.dt_orchestrator
        await dt_orchestrator.associate_replica_with_twin(parent_twin_id, replica_id)
        
        # Re-create device associations
        device_ids = getattr(replica, 'device_ids', [])
        restored_devices = []
        
        for device_id in device_ids:
            try:
                # Check if association already exists
                existing_associations = await registry.get_device_associations(device_id)
                already_exists = any(
                    assoc.replica_id == replica_id 
                    for assoc in existing_associations
                )
                
                if not already_exists:
                    # Create new association
                    from src.layers.virtualization.dr_registry import DeviceAssociation
                    association = DeviceAssociation(
                        device_id=device_id,
                        replica_id=replica_id,
                        association_type="managed"
                    )
                    await registry.associate_device(association)
                    restored_devices.append(device_id)
                else:
                    logger.info(f"Association already exists for device {device_id}")
                    
            except Exception as e:
                logger.warning(f"Failed to restore device association {device_id}: {e}")
        
        return {
            "replica_id": str(replica_id),
            "parent_twin_id": str(parent_twin_id),
            "association_restored": True,
            "devices_restored": restored_devices,
            "total_devices": len(device_ids),
            "restored_at": datetime.now(timezone.utc).isoformat(),
            "message": "Association restored successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to restore association for replica {replica_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Association restoration failed: {e}"
        )

@router.get("/{replica_id}/raw", summary="Get Raw Replica Data")
async def get_raw_replica_data(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get raw replica data for debugging."""
    try:
        # ✅ Accesso diretto al registry e virtualization layer
        v_layer = gateway.virtualization_orchestrator
        
        # Try diversi modi per ottenere i dati
        registry_data = {}
        try:
            registry_data = await v_layer.registry.get_replica_performance(replica_id)
        except Exception as e:
            registry_data = {"registry_error": str(e)}
        
        # Try ottenere dalla storage diretta
        storage_data = {}
        try:
            replica_from_storage = await v_layer.registry.get_digital_replica(replica_id)
            storage_data = {
                "type": str(type(replica_from_storage)),
                "has_get_aggregation_statistics": hasattr(replica_from_storage, 'get_aggregation_statistics'),
                "attributes": [attr for attr in dir(replica_from_storage) if not attr.startswith('_')],
                "raw_data": getattr(replica_from_storage, 'to_dict', lambda: {})()
            }
        except Exception as e:
            storage_data = {"storage_error": str(e)}
        
        # Try ottenere devices
        devices_data = {}
        try:
            devices = await v_layer.registry.get_replica_devices(replica_id)
            devices_data = {"devices": devices, "count": len(devices)}
        except Exception as e:
            devices_data = {"devices_error": str(e)}
        
        return {
            "replica_id": str(replica_id),
            "registry_data": registry_data,
            "storage_data": storage_data,
            "devices_data": devices_data,
            "virtualization_layer_info": {
                "initialized": v_layer._initialized,
                "running": v_layer._running,
                "registry_type": str(type(v_layer.registry)),
                "factory_type": str(type(v_layer.factory))
            },
            "generated_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        return {
            "replica_id": str(replica_id),
            "error": f"Complete failure: {str(e)}",
            "generated_at": datetime.utcnow().isoformat()
        }


@router.post("/{replica_id}/devices", summary="Associate Device")
async def associate_device(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    device_association: DeviceAssociation = Body(...),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, str]:
    """Associate a new device with a Digital Replica."""
    try:
        # Note: This would call the virtualization layer to associate the device
        return {
            "message": f"Device {device_association.device_id} associated with replica {replica_id}",
            "device_id": device_association.device_id,
            "association_type": device_association.association_type,
            "status": "success"
        }
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Replica {replica_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to associate device with replica {replica_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Device association failed: {e}"
        )


@router.delete("/{replica_id}/devices/{device_id}", summary="Disassociate Device")
async def disassociate_device(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    device_id: str = Path(..., description="Device ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, str]:
    """Remove device association from a Digital Replica."""
    try:
        return {
            "message": f"Device {device_id} disassociated from replica {replica_id}",
            "device_id": device_id,
            "status": "success"
        }
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Replica {replica_id} or device {device_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to disassociate device {device_id} from replica {replica_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Device disassociation failed: {e}"
        )


# =========================
# DATA MANAGEMENT
# =========================

@router.post("/{replica_id}/data", summary="Send Device Data")
async def send_device_data(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    device_data: DeviceData = Body(...),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """
    Send data from a device to a Digital Replica.
    IMPLEMENTAZIONE DIRETTA CON MONGODB - BYPASS REPLICA WRAPPER!
    """
    try:
        logger.info(f"🔥 Processing device data for replica {replica_id}, device {device_data.device_id}")
        
        # ✅ STEP 1: Get replica info and validate
        registry = gateway.virtualization_orchestrator.registry
        replica_wrapper = await registry.get_digital_replica(replica_id)
        
        # Get parent twin ID
        if hasattr(replica_wrapper, 'parent_digital_twin_id'):
            twin_id = replica_wrapper.parent_digital_twin_id
        else:
            # Try from metadata
            metadata_dict = replica_wrapper.metadata.to_dict() if hasattr(replica_wrapper.metadata, 'to_dict') else replica_wrapper.metadata
            twin_id = UUID(metadata_dict.get('custom', {}).get('parent_twin_id'))
        
        logger.info(f"✅ Found parent twin ID: {twin_id}")
        
        # ✅ STEP 2: Convert API data to internal format
        from src.core.interfaces.replica import DeviceData as InternalDeviceData, DataQuality
        from datetime import datetime, timezone
        
        # Parse timestamp
        timestamp = device_data.timestamp
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        elif isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        
        # Convert quality
        quality_map = {
            "high": DataQuality.HIGH,
            "medium": DataQuality.MEDIUM, 
            "low": DataQuality.LOW,
            None: DataQuality.UNKNOWN
        }
        quality = quality_map.get(device_data.quality_hint, DataQuality.UNKNOWN)
        
        # Create internal device data - FIX metadata access
        metadata = {}
        if hasattr(device_data, 'metadata') and device_data.metadata is not None:
            metadata = device_data.metadata
        
        internal_device_data = InternalDeviceData(
            device_id=device_data.device_id,
            timestamp=timestamp,
            data=device_data.data,
            data_type=device_data.data_type,
            quality=quality,
            metadata=metadata
        )
        
        # ✅ STEP 3: DIRECT MONGODB PERSISTENCE - BYPASS WRAPPER!
        try:
            from src.core.entities.device_data import DeviceDataEntity
            from src.storage import get_twin_storage_adapter
            
            # Get MongoDB adapter for this twin's database
            storage_adapter = get_twin_storage_adapter(DeviceDataEntity, twin_id)
            
            # Create device data entity
            device_data_entity = DeviceDataEntity.from_device_data(
                internal_device_data, 
                replica_id,
                additional_metadata={
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "api_version": "1.0",
                    "source": "api_direct"
                }
            )
            
            # Save to MongoDB
            await storage_adapter.save(device_data_entity)
            logger.info(f"💾 Successfully saved device data to MongoDB - Twin DB: dt_twin_{str(twin_id).replace('-', '_')}")
            
            mongodb_success = True
            saved_entity_id = device_data_entity.id
            
        except Exception as e:
            logger.error(f"❌ Failed to save to MongoDB: {e}")
            mongodb_success = False
            saved_entity_id = None
        
        # ✅ STEP 4: REDIS CACHE (optional, non-blocking)
        redis_success = False
        try:
            from src.storage.adapters.redis_cache import get_redis_cache
            redis_cache = await get_redis_cache()
            
            # Cache latest data per device
            cache_key = f"latest_device_data:{device_data.device_id}:{replica_id}"
            await redis_cache.set(
                cache_key, 
                device_data_entity.to_dict(), 
                ttl=3600,  # 1 hour
                namespace="device_data"
            )
            logger.info(f"🚀 Cached device data in Redis: {cache_key}")
            redis_success = True
            
        except Exception as e:
            logger.warning(f"Failed to cache in Redis (non-critical): {e}")
        
        # ✅ STEP 5: Update registry associations (backward compatibility)
        try:
            await registry.record_device_data(
                device_id=device_data.device_id,
                replica_id=replica_id,
                data_quality=quality
            )
            logger.info(f"📊 Updated registry associations")
            registry_success = True
            
        except Exception as e:
            logger.warning(f"Failed to update registry: {e}")
            registry_success = False
        
        # ✅ STEP 6: Success Response
        return {
            "replica_id": str(replica_id),
            "device_id": device_data.device_id,
            "twin_id": str(twin_id),
            "data_received": True,
            "method": "direct_mongodb_persistence",
            "quality": quality.value,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "persistence_status": {
                "mongodb": mongodb_success,
                "redis_cache": redis_success,
                "registry_associations": registry_success
            },
            "database_info": {
                "database": f"dt_twin_{str(twin_id).replace('-', '_')}",
                "collection": "device_data",
                "entity_id": str(saved_entity_id) if mongodb_success and saved_entity_id else None
            },
            "message": "✅ Device data processed with direct MongoDB persistence"
        }
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Replica {replica_id} not found"
        )
    except Exception as e:
        logger.error(f"❌ Failed to process device data for replica {replica_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Device data processing failed: {str(e)}"
        )


@router.get("/{replica_id}/performance", summary="Get Performance Metrics")
async def get_performance_metrics(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    time_range: int = Query(3600, ge=60, description="Time range in seconds"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get performance metrics for a Digital Replica."""
    try:
        # ✅ BYPASS WRAPPER - Accesso diretto ai dati dal registry
        registry = gateway.virtualization_orchestrator.registry
        
        # Accesso diretto alle device associations (i VERI dati!)
        device_associations = []
        devices_managed = []
        total_data_received = 0
        
        # Cerca nelle associations del registry
        for key, association in registry.device_associations.items():
            if str(association.replica_id) == str(replica_id):
                device_associations.append({
                    "device_id": association.device_id,
                    "data_count": association.data_count,
                    "last_data": association.last_data_timestamp.isoformat() if association.last_data_timestamp else "Never",
                    "average_quality": association.get_average_quality_score(),
                    "association_type": association.association_type
                })
                devices_managed.append(association.device_id)
                total_data_received += association.data_count
        
        # Accesso diretto ai dispositivi gestiti
        replica_devices = registry.replica_to_devices.get(replica_id, set())
        devices_managed.extend(list(replica_devices))
        devices_managed = list(set(devices_managed))  # Rimuovi duplicati
        
        # Ottieni dati flow reali
        flow_metrics = registry.metrics.data_flow_metrics
        
        # Costruisci performance REALI
        real_performance = {
            "replica_id": str(replica_id),
            "time_range_seconds": time_range,
            "data_flow": {
                "total_data_received": total_data_received,
                "devices_count": len(devices_managed),
                "data_rate_per_minute": total_data_received / (time_range / 60) if time_range > 0 else 0,
                "total_flow_data_points": flow_metrics.total_data_points,
                "last_data_time": flow_metrics.last_data_timestamp.isoformat() if flow_metrics.last_data_timestamp else "Never"
            },
            "aggregation_performance": {
                "total_aggregations": flow_metrics.aggregations_performed,
                "aggregation_success_rate": 1.0 if flow_metrics.aggregations_performed > 0 else 0,
                "data_to_aggregation_ratio": flow_metrics.aggregations_performed / max(total_data_received, 1)
            },
            "device_performance": {
                assoc["device_id"]: {
                    "data_points": assoc["data_count"],
                    "average_quality": assoc["average_quality"],
                    "last_data": assoc["last_data"],
                    "status": "active" if assoc["data_count"] > 0 else "inactive"
                }
                for assoc in device_associations
            },
            "registry_info": {
                "associations_count": len(device_associations),
                "managed_devices": devices_managed,
                "registry_metrics": flow_metrics.to_dict()
            },
            "generated_at": datetime.utcnow().isoformat()
        }
        
        return real_performance
        
    except Exception as e:
        logger.error(f"Failed to get REAL performance metrics for replica {replica_id}: {e}")
        # Debug info quando fallisce
        try:
            registry = gateway.virtualization_orchestrator.registry
            debug_info = {
                "total_associations": len(registry.device_associations),
                "total_replicas": len(registry.replica_to_devices),
                "association_keys": list(registry.device_associations.keys())[:5],  # Prime 5
                "replica_keys": list(registry.replica_to_devices.keys())[:5]
            }
        except:
            debug_info = {"debug_failed": True}
        
        return {
            "replica_id": str(replica_id),
            "error": f"Direct access error: {str(e)}",
            "debug_info": debug_info,
            "time_range_seconds": time_range,
            "generated_at": datetime.utcnow().isoformat()
        }


@router.get("/{replica_id}/data/quality", summary="Get Data Quality Report")
async def get_data_quality_report(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    time_range: int = Query(3600, ge=60, description="Time range in seconds"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get data quality report for a Digital Replica."""
    try:
        # ✅ USA IL REGISTRY per dati reali
        registry = gateway.virtualization_orchestrator.registry
        
        # Ottieni performance che include quality data
        performance_data = await registry.get_replica_performance(replica_id)
        
        # Ottieni devices associati
        devices = await registry.get_replica_devices(replica_id)
        
        return {
            "replica_id": str(replica_id),
            "time_range_seconds": time_range,
            "quality_report": {
                "total_data_points": performance_data.get("total_data_received", 0),
                "overall_quality_score": performance_data.get("average_quality_score", 0),
                "device_count": len(devices),
                "devices_performance": {
                    assoc["device_id"]: {
                        "quality_score": assoc["average_quality_score"],
                        "data_points": assoc["data_count"],
                        "last_data": assoc["last_data_timestamp"]
                    }
                    for assoc in performance_data.get("associations", [])
                },
                "aggregation_info": performance_data.get("aggregation_stats", {}),
                "replica_type": performance_data.get("replica_type", "unknown")
            },
            "managed_devices": devices,
            "generated_at": datetime.utcnow().isoformat()
        }
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Replica {replica_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to get real data quality report for replica {replica_id}: {e}")
        return {
            "replica_id": str(replica_id),
            "error": f"Registry error: {str(e)}",
            "generated_at": datetime.utcnow().isoformat()
        }

@router.get("/{replica_id}/associations", summary="Get Device Associations")
async def get_device_associations(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get device associations for a Digital Replica."""
    try:
        # ✅ Accesso diretto alle associations reali
        registry = gateway.virtualization_orchestrator.registry
        
        associations = []
        for key, association in registry.device_associations.items():
            if str(association.replica_id) == str(replica_id):
                associations.append({
                    "device_id": association.device_id,
                    "replica_id": str(association.replica_id),
                    "association_type": association.association_type,
                    "created_at": association.created_at.isoformat(),
                    "data_count": association.data_count,
                    "last_data_timestamp": association.last_data_timestamp.isoformat() if association.last_data_timestamp else None,
                    "average_quality_score": association.get_average_quality_score(),
                    "quality_history_count": len(association.quality_history)
                })
        
        # Devices dalla lookup table
        managed_devices = list(registry.replica_to_devices.get(replica_id, set()))
        
        return {
            "replica_id": str(replica_id),
            "associations": associations,
            "managed_devices": managed_devices,
            "association_count": len(associations),
            "device_count": len(managed_devices),
            "generated_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        return {
            "replica_id": str(replica_id),
            "error": f"Failed to get associations: {str(e)}",
            "generated_at": datetime.utcnow().isoformat()
        }


@router.get("/{replica_id}/debug", summary="Debug Registry Data")
async def debug_registry_data(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Debug registry data for troubleshooting."""
    try:
        registry = gateway.virtualization_orchestrator.registry
        
        # Tutte le info di debug
        debug_data = {
            "replica_id": str(replica_id),
            "registry_type": str(type(registry)),
            "total_associations": len(registry.device_associations),
            "total_replica_devices": len(registry.replica_to_devices),
            "flow_metrics": registry.metrics.data_flow_metrics.to_dict(),
            "all_association_keys": list(registry.device_associations.keys()),
            "all_replica_keys": [str(k) for k in registry.replica_to_devices.keys()],
            "replica_exists_in_devices": replica_id in registry.replica_to_devices,
            "matching_associations": [],
            "replica_devices": list(registry.replica_to_devices.get(replica_id, set())),
            "generated_at": datetime.utcnow().isoformat()
        }
        
        # Trova associations che matchano
        for key, association in registry.device_associations.items():
            if str(association.replica_id) == str(replica_id):
                debug_data["matching_associations"].append({
                    "key": key,
                    "device_id": association.device_id,
                    "data_count": association.data_count,
                    "last_data": association.last_data_timestamp.isoformat() if association.last_data_timestamp else None
                })
        
        return debug_data
        
    except Exception as e:
        return {
            "replica_id": str(replica_id),
            "error": f"Debug failed: {str(e)}",
            "generated_at": datetime.utcnow().isoformat()
        }

@router.post("/{replica_id}/aggregation/trigger", summary="Force Data Aggregation")
async def trigger_aggregation(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    force: bool = Body(False, description="Force aggregation even if conditions not met"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Manually trigger data aggregation for a Digital Replica."""
    try:
        triggered_at = datetime.utcnow()
        
        return {
            "replica_id": str(replica_id),
            "aggregation_triggered": True,
            "forced": force,
            "triggered_at": triggered_at.isoformat(),
            "estimated_completion": (triggered_at.timestamp() + 30),  # 30 seconds estimate
            "aggregation_id": f"agg-{replica_id}-{int(triggered_at.timestamp())}"
        }
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Replica {replica_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to trigger aggregation for replica {replica_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Aggregation trigger failed: {e}"
        )


# =========================
# CONTAINER MANAGEMENT
# =========================

@router.post("/{replica_id}/deploy", summary="Deploy as Container")
async def deploy_as_container(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    deployment: ContainerDeployment = Body(...),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Deploy a Digital Replica as a container."""
    try:
        # Note: This would call the virtualization layer container deployment
        container_id = f"dr-container-{replica_id}"[:16]
        
        return {
            "replica_id": str(replica_id),
            "container_id": container_id,
            "deployment_target": deployment.deployment_target,
            "status": "deploying",
            "deployment_started": datetime.utcnow().isoformat(),
            "estimated_ready": datetime.utcnow().isoformat(),  # Would calculate based on target
            "container_config": deployment.container_config
        }
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Replica {replica_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to deploy replica {replica_id} as container: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Container deployment failed: {e}"
        )


@router.get("/{replica_id}/status", summary="Get Real Replica Status")
async def get_replica_status(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get REAL status of a Digital Replica."""
    try:
        # ✅ DATI REALI dalla replica
        replica = await gateway.virtualization_orchestrator.registry.get_digital_replica(replica_id)
        
        # Serializza replica a dict per ottenere tutti i dati reali
        replica_dict = replica.to_dict()
        
        return {
            "replica_id": str(replica_id),
            "real_data": replica_dict,
            "configuration": {
                "replica_type": replica.replica_type.value,
                "aggregation_mode": replica.aggregation_mode.value,
                "parent_digital_twin_id": str(replica.parent_digital_twin_id),
                "device_ids": replica.device_ids,
                "device_count": len(replica.device_ids)
            },
            "status_info": {
                "status": replica_dict.get("status", "unknown"),
                "metadata": replica_dict.get("metadata", {}),
                "statistics": replica_dict.get("statistics", {})
            },
            "generated_at": datetime.utcnow().isoformat()
        }
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Replica {replica_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to get REAL replica status for {replica_id}: {e}")
        return {
            "replica_id": str(replica_id),
            "error": f"Failed to get real status: {str(e)}",
            "note": "Replica might not be properly initialized",
            "generated_at": datetime.utcnow().isoformat()
        }


# =========================
# PERFORMANCE & MONITORING
# =========================

@router.get("/{replica_id}/performance", summary="Get Performance Metrics")
async def get_performance_metrics(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    time_range: int = Query(3600, ge=60, description="Time range in seconds"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get performance metrics for a Digital Replica."""
    try:
        # ✅ USA IL REGISTRY che ha i dati reali!
        registry = gateway.virtualization_orchestrator.registry
        
        # Il registry ha un metodo apposito per le performance
        performance_data = await registry.get_replica_performance(replica_id)
        
        # Ottieni anche statistics dal flow
        flow_stats = await registry.get_data_flow_statistics(time_range_hours=time_range//3600)
        
        # Combina i dati reali
        real_performance = {
            "replica_id": str(replica_id),
            "time_range_seconds": time_range,
            "registry_performance": performance_data,
            "flow_statistics": flow_stats,
            "data_flow": {
                "total_data_received": performance_data.get("total_data_received", 0),
                "average_quality_score": performance_data.get("average_quality_score", 0),
                "device_count": performance_data.get("device_count", 0)
            },
            "aggregation_performance": performance_data.get("aggregation_stats", {}),
            "device_performance": {
                assoc["device_id"]: {
                    "data_points": assoc["data_count"],
                    "average_quality": assoc["average_quality_score"],
                    "last_data": assoc["last_data_timestamp"]
                }
                for assoc in performance_data.get("associations", [])
            },
            "generated_at": datetime.utcnow().isoformat()
        }
        
        return real_performance
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Replica {replica_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to get real performance metrics for replica {replica_id}: {e}")
        return {
            "replica_id": str(replica_id),
            "error": f"Registry error: {str(e)}",
            "time_range_seconds": time_range,
            "note": "Check registry and storage connection",
            "generated_at": datetime.utcnow().isoformat()
        }
# =========================
# DISCOVERY & TEMPLATES
# =========================

@router.get("/types/available", summary="Get Available Replica Types")
async def get_available_types() -> Dict[str, List[str]]:
    """Get available Digital Replica types and aggregation modes."""
    return {
        "replica_types": [t.value for t in ReplicaType],
        "aggregation_modes": [m.value for m in DataAggregationMode]
    }


@router.get("/templates/available", summary="Get Available Templates")
async def get_available_templates(
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get available Digital Replica templates from OntologyManager (NO HARDCODING!)."""
    try:
        # Get templates from virtualization layer
        virtualization_orchestrator = gateway.virtualization_orchestrator
        
        if not virtualization_orchestrator._initialized:
            await virtualization_orchestrator.initialize()
        
        available_templates = await virtualization_orchestrator.get_available_templates()
        
        # Transform to API format
        templates = []
        for template_dict in available_templates:
            config = template_dict.get("configuration", {})
            templates.append({
                "template_id": template_dict.get("template_id"),
                "name": template_dict.get("name"),
                "description": template_dict.get("description"),
                "replica_type": config.get("replica_type"),
                "suggested_use": ", ".join(template_dict.get("metadata", {}).get("use_cases", [])[:2])
            })
        
        return {"templates": templates}
        
    except Exception as e:
        logger.error(f"Failed to get available templates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get templates: {e}"
        )

# =========================
# BULK OPERATIONS
# =========================

@router.post("/bulk/scale", summary="Scale Multiple Replicas")
async def bulk_scale_replicas(
    scaling_operations: List[Dict[str, Any]] = Body(..., description="List of scaling operations"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Scale multiple Digital Replicas horizontally."""
    try:
        results = []
        
        for operation in scaling_operations:
            try:
                replica_id = UUID(operation["replica_id"])
                scale_factor = operation.get("scale_factor", 2)
                
                # Note: Would call virtualization layer scaling
                results.append({
                    "replica_id": str(replica_id),
                    "scale_factor": scale_factor,
                    "success": True,
                    "status": "scaling_initiated"
                })
                
            except Exception as e:
                results.append({
                    "replica_id": operation.get("replica_id", "unknown"),
                    "success": False,
                    "error": str(e)
                })
        
        successful = len([r for r in results if r["success"]])
        
        return {
            "total_operations": len(scaling_operations),
            "successful": successful,
            "failed": len(scaling_operations) - successful,
            "results": results,
            "initiated_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to scale replicas in bulk: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk scaling failed: {e}"
        )

@router.get("/{replica_id}/mongodb-data", summary="Get Raw MongoDB Data for Replica")
async def get_replica_mongodb_data(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of records"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """
    Get raw device data from MongoDB for this replica.
    CAZZO DI ROUTE PER VEDERE I DATI VERI!
    """
    try:
        # Get replica info to find parent twin
        registry = gateway.virtualization_orchestrator.registry
        replica = await registry.get_digital_replica(replica_id)
        
        if hasattr(replica, 'parent_digital_twin_id'):
            twin_id = replica.parent_digital_twin_id
        else:
            metadata_dict = replica.metadata.to_dict() if hasattr(replica.metadata, 'to_dict') else replica.metadata
            twin_id = UUID(metadata_dict.get('custom', {}).get('parent_twin_id'))
        
        logger.info(f"🔍 Looking for MongoDB data - Replica: {replica_id}, Twin: {twin_id}")
        
        # Get MongoDB adapter
        from src.core.entities.device_data import DeviceDataEntity
        from src.storage import get_twin_storage_adapter
        
        storage_adapter = get_twin_storage_adapter(DeviceDataEntity, twin_id)
        
        # Query filters for this replica
        filters = {"replica_id": str(replica_id)}
        
        # Get raw data from MongoDB
        entities = await storage_adapter.query(filters, limit=limit)
        
        logger.info(f"📊 Found {len(entities)} entities in MongoDB")
        
        # Convert to readable format
        data_points = []
        for entity in entities:
            try:
                data_points.append({
                    "entity_id": str(entity.id),
                    "device_id": entity.device_id,
                    "timestamp": entity.timestamp.isoformat(),
                    "data_type": entity.data_type,
                    "quality": entity.quality.value,
                    "data": entity.data,
                    "device_metadata": entity.device_metadata,
                    "processed": entity.processed,
                    "created_at": entity.metadata.timestamp.isoformat()
                })
            except Exception as e:
                logger.warning(f"Failed to convert entity: {e}")
                continue
        
        # Sort by timestamp descending (newest first)
        data_points.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return {
            "replica_id": str(replica_id),
            "twin_id": str(twin_id),
            "database": f"dt_twin_{str(twin_id).replace('-', '_')}",
            "collection": "device_data",
            "total_records": len(data_points),
            "query_limit": limit,
            "data": data_points,
            "query_filters": filters,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "message": f"✅ Found {len(data_points)} real MongoDB records for replica {replica_id}"
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to get MongoDB data for replica {replica_id}: {e}")
        return {
            "replica_id": str(replica_id),
            "error": str(e),
            "message": "Failed to retrieve MongoDB data",
            "generated_at": datetime.now(timezone.utc).isoformat()
        }


@router.get("/{replica_id}/raw-debug", summary="Complete Debug Info for Replica")
async def get_replica_debug_info(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """
    Get EVERYTHING about this replica for debugging.
    CAZZO DI DEBUG COMPLETO!
    """
    try:
        registry = gateway.virtualization_orchestrator.registry
        
        # 1. Replica basic info
        replica = await registry.get_digital_replica(replica_id)
        replica_info = {
            "exists": True,
            "type": str(type(replica)),
            "parent_twin_id": getattr(replica, 'parent_digital_twin_id', 'N/A'),
            "device_ids": getattr(replica, 'device_ids', []),
            "metadata": replica.metadata.to_dict() if hasattr(replica.metadata, 'to_dict') else str(replica.metadata)
        }
        
        # 2. Device associations
        device_associations = []
        for key, association in registry.device_associations.items():
            if str(association.replica_id) == str(replica_id):
                device_associations.append({
                    "device_id": association.device_id,
                    "data_count": association.data_count,
                    "last_data": association.last_data_timestamp.isoformat() if association.last_data_timestamp else None,
                    "quality_score": association.get_average_quality_score(),
                    "association_type": association.association_type
                })
        
        # 3. Twin-Replica mapping
        twin_replica_mappings = {}
        for twin_id, replica_set in registry.digital_twin_replicas.items():
            if replica_id in replica_set:
                twin_replica_mappings[str(twin_id)] = list(str(r) for r in replica_set)
        
        # 4. MongoDB data count (if possible)
        mongodb_info = {"error": "Could not check MongoDB"}
        try:
            if hasattr(replica, 'parent_digital_twin_id'):
                twin_id = replica.parent_digital_twin_id
                from src.core.entities.device_data import DeviceDataEntity
                from src.storage import get_twin_storage_adapter
                
                storage_adapter = get_twin_storage_adapter(DeviceDataEntity, twin_id)
                entities = await storage_adapter.query({"replica_id": str(replica_id)}, limit=5)
                
                mongodb_info = {
                    "database": f"dt_twin_{str(twin_id).replace('-', '_')}",
                    "collection": "device_data",
                    "sample_count": len(entities),
                    "has_data": len(entities) > 0
                }
        except Exception as e:
            mongodb_info["error"] = str(e)
        
        return {
            "replica_id": str(replica_id),
            "replica_info": replica_info,
            "device_associations": {
                "count": len(device_associations),
                "associations": device_associations
            },
            "twin_replica_mappings": twin_replica_mappings,
            "mongodb_info": mongodb_info,
            "registry_stats": {
                "total_replicas": len(await registry.list()),
                "total_device_associations": len(registry.device_associations),
                "total_twin_mappings": len(registry.digital_twin_replicas)
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "debug_complete": True
        }
        
    except Exception as e:
        return {
            "replica_id": str(replica_id),
            "error": str(e),
            "debug_failed": True,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }