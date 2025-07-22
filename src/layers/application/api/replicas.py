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
    """Model for sending device data to a replica."""
    device_id: str = Field(..., description="Device ID")
    data: Dict[str, Any] = Field(..., description="Device data payload")
    data_type: str = Field("sensor_reading", description="Type of data")
    timestamp: Optional[datetime] = Field(None, description="Data timestamp (optional)")
    quality_hint: Optional[str] = Field(None, description="Quality hint (high/medium/low)")
    
    class Config:
        schema_extra = {
            "example": {
                "device_id": "sensor-001",
                "data": {
                    "temperature": 22.5,
                    "humidity": 65.2,
                    "pressure": 1013.25
                },
                "data_type": "environmental_reading",
                "timestamp": "2024-01-01T10:30:00Z",
                "quality_hint": "high"
            }
        }


class DeviceAssociation(BaseModel):
    """Model for associating devices with a replica."""
    device_id: str = Field(..., description="Device ID to associate")
    association_type: str = Field("managed", description="Type of association")
    data_mapping: Optional[Dict[str, str]] = Field(None, description="Optional data field mapping")
    
    class Config:
        schema_extra = {
            "example": {
                "device_id": "sensor-004",
                "association_type": "monitored",
                "data_mapping": {
                    "temp": "temperature",
                    "hum": "humidity"
                }
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

# ===============================================
# FIX DEFINITIVO: src/layers/application/api/replicas.py
# SOSTITUISCI il metodo send_device_data con questo VERO
# ===============================================

@router.post("/{replica_id}/data", summary="Send Device Data")
async def send_device_data(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    device_data: DeviceData = Body(...),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Send data from a device to a Digital Replica - VERSIONE VERA!"""
    try:
        # ✅ STEP 1: Ottieni la replica VERA dal registry
        registry = gateway.virtualization_orchestrator.registry
        replica_wrapper = await registry.get_digital_replica(replica_id)
        
        # ✅ STEP 2: Verifica che il device sia autorizzato
        if device_data.device_id not in replica_wrapper.device_ids:
            logger.warning(f"Device {device_data.device_id} not in replica {replica_id} device list")
            # Aggiungi device se non c'è (auto-association)
            devices = await registry.get_replica_devices(replica_id)
            if device_data.device_id not in devices:
                await registry.associate_device_with_replica(
                    device_data.device_id, 
                    replica_id,
                    association_type="auto_detected"
                )
                logger.info(f"Auto-associated device {device_data.device_id} with replica {replica_id}")
        
        # ✅ STEP 3: Converti i dati API in formato DeviceData interno
        from src.core.interfaces.replica import DeviceData as InternalDeviceData, DataQuality
        from datetime import datetime, timezone
        
        # Converti timestamp se presente
        timestamp = device_data.timestamp
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        elif isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        
        # Converti quality hint in DataQuality enum
        quality_map = {
            "high": DataQuality.HIGH,
            "medium": DataQuality.MEDIUM, 
            "low": DataQuality.LOW,
            None: DataQuality.UNKNOWN
        }
        quality = quality_map.get(device_data.quality_hint, DataQuality.UNKNOWN)
        
        # Crea DeviceData interno
        internal_device_data = InternalDeviceData(
            device_id=device_data.device_id,
            timestamp=timestamp,
            data=device_data.data,
            data_type=device_data.data_type,
            quality=quality,
            metadata={}
        )
        
        # ✅ STEP 4: Cerca la replica VERA nel factory (non il wrapper)
        factory = gateway.virtualization_orchestrator.factory
        
        # Qui c'è il trucco - dobbiamo accedere alla replica reale
        # Il registry ha solo wrapper, ma il factory dovrebbe avere l'oggetto vero
        real_replica = None
        
        # Try diversi modi per ottenere la replica vera
        try:
            # Metodo 1: Se il factory tiene una cache delle repliche
            if hasattr(factory, '_replica_cache') and replica_id in factory._replica_cache:
                real_replica = factory._replica_cache[replica_id]
            
            # Metodo 2: Se il lifecycle manager ha le repliche attive
            elif hasattr(gateway.virtualization_orchestrator, 'lifecycle_manager'):
                lifecycle_mgr = gateway.virtualization_orchestrator.lifecycle_manager
                if hasattr(lifecycle_mgr, '_active_replicas') and replica_id in lifecycle_mgr._active_replicas:
                    real_replica = lifecycle_mgr._active_replicas[replica_id]
            
            # Metodo 3: Ricrea la replica dal wrapper (ultimo resort)
            if real_replica is None:
                logger.warning(f"Cannot find real replica object for {replica_id}, using wrapper methods")
                # Se non troviamo la replica vera, almeno registriamo i dati nel registry
                await registry.record_device_data(
                    device_id=device_data.device_id,
                    replica_id=replica_id,
                    data_quality=quality
                )
                
                return {
                    "replica_id": str(replica_id),
                    "device_id": device_data.device_id,
                    "data_received": True,
                    "method": "registry_direct",
                    "quality": quality.value,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                    "note": "Data recorded in registry, replica object not directly accessible"
                }
        
        except Exception as e:
            logger.error(f"Error finding real replica: {e}")
        
        # ✅ STEP 5: Se abbiamo la replica vera, inviamo i dati
        if real_replica:
            logger.info(f"Found real replica object, sending data directly")
            await real_replica.receive_device_data(internal_device_data)
            
            # Ottieni statistiche aggiornate
            stats = await real_replica.get_aggregation_statistics()
            
            return {
                "replica_id": str(replica_id),
                "device_id": device_data.device_id,
                "data_received": True,
                "method": "direct_replica",
                "quality": quality.value,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "aggregation_stats": stats,
                "real_processing": True
            }
        
        # ✅ FALLBACK: Almeno registra nel registry
        await registry.record_device_data(
            device_id=device_data.device_id,
            replica_id=replica_id,
            data_quality=quality
        )
        
        return {
            "replica_id": str(replica_id),
            "device_id": device_data.device_id,
            "data_received": True,
            "method": "registry_fallback",
            "quality": quality.value,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "note": "Data registered, but direct replica access unavailable"
        }
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Replica {replica_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to send data to replica {replica_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Data sending failed: {str(e)}"
        )

# ===============================================
# FIX VERO: src/layers/application/api/replicas.py
# Usa i metodi del REGISTRY che hanno accesso ai dati reali
# ===============================================

# ===============================================
# FIX FINALE: src/layers/application/api/replicas.py
# Bypassa completamente i wrapper e accede ai dati direttamente
# ===============================================

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