"""
Digital Twins API endpoints for the Digital Twin Platform.

This module provides REST API endpoints for managing Digital Twins,
including CRUD operations, capability execution, and ecosystem management.

LOCATION: src/layers/application/api/digital_twins.py
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from src.layers.service.data_retrieval_service import DataRetrievalService, DataRetrievalQuery
from src.core.interfaces.base import BaseMetadata
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body, status
from pydantic import BaseModel, Field, validator

from src.layers.application.api_gateway import APIGateway
from src.layers.application.api import get_gateway
from src.core.interfaces.digital_twin import TwinCapability, DigitalTwinType
from src.utils.exceptions import EntityNotFoundError
from datetime import timezone, timedelta, datetime

from src.core.capabilities.capability_registry import get_capability_registry
from src.utils.type_converter import validate_capability, get_available_capabilities

logger = logging.getLogger(__name__)

# Create router
router = APIRouter()


# =========================
# PYDANTIC MODELS
# =========================

class DigitalTwinCreate(BaseModel):
    """Model for creating a Digital Twin."""
    twin_type: str = Field(..., description="Type of Digital Twin")
    name: str = Field(..., min_length=1, max_length=255, description="Human-readable name")
    description: str = Field("", max_length=1000, description="Description of the twin")
    capabilities: List[str] = Field(..., min_items=1, description="List of capabilities")
    template_id: Optional[str] = Field(None, description="Template ID for creation")
    customization: Optional[Dict[str, Any]] = Field(None, description="Template customization")
    parent_twin_id: Optional[UUID] = Field(None, description="Parent twin for hierarchy")
    
    @validator('twin_type')
    @classmethod
    def validate_twin_type(cls, v):
        try:
            DigitalTwinType(v)
            return v
        except ValueError:
            valid_types = [t.value for t in DigitalTwinType]
            raise ValueError(f"Invalid twin_type. Must be one of: {valid_types}")
    
    @validator('capabilities', pre=True)
    @classmethod
    def validate_capabilities(cls, v, values):
        """
        UPDATED: Now uses registry-based validation instead of hardcoded enum.
        """
        if not isinstance(v, list):
            raise ValueError("capabilities must be a list")
        
        if not v:  # Empty list
            raise ValueError("capabilities list cannot be empty")
        
        # Get twin_type for context-aware validation
        twin_type = values.get('twin_type', 'asset')  # Default to asset
        
        # Get registry instance
        registry = get_capability_registry()
        
        # Validate each capability
        invalid_capabilities = []
        valid_capabilities = []
        
        for cap in v:
            if not isinstance(cap, str):
                raise ValueError(f"All capabilities must be strings, got {type(cap)}")
            
            # Check if capability exists in registry
            if registry.has_capability(cap):
                # Check twin type compatibility
                cap_def = registry.get_capability(cap)
                if cap_def.required_twin_types and twin_type not in cap_def.required_twin_types:
                    invalid_capabilities.append(f"{cap} (not compatible with {twin_type})")
                else:
                    valid_capabilities.append(cap)
            else:
                invalid_capabilities.append(cap)
        
        if invalid_capabilities:
            # Get available capabilities for helpful error message
            available = get_available_capabilities(twin_type)
            core_caps = [cap for cap in available if not '.' in cap]
            domain_caps = [cap for cap in available if '.' in cap]
            
            error_msg = f"Invalid capabilities: {invalid_capabilities}.\n"
            error_msg += f"Available core capabilities: {core_caps}\n"
            if domain_caps:
                error_msg += f"Available domain capabilities: {domain_caps}"
            
            raise ValueError(error_msg)
        
        return valid_capabilities


class CapabilityExecution(BaseModel):
    """Model for executing a Digital Twin capability."""
    capability: str = Field(..., description="Capability to execute")
    input_data: Dict[str, Any] = Field(..., description="Input data for execution")
    execution_config: Optional[Dict[str, Any]] = Field(None, description="Execution configuration")
    
    @validator('capability')
    @classmethod
    def validate_capability(cls, v):
        """
        UPDATED: Now uses registry-based validation.
        """
        if not isinstance(v, str):
            raise ValueError("capability must be a string")
        
        registry = get_capability_registry()
        if not registry.has_capability(v):
            available = [cap.full_name for cap in registry.list_capabilities()]
            raise ValueError(f"Invalid capability '{v}'. Available capabilities: {available}")
        
        return v

class CapabilityInfo(BaseModel):
    """Model for capability information."""
    name: str
    namespace: str
    full_name: str
    description: str
    category: str
    required_permissions: List[str]
    required_twin_types: List[str]

class ReplicaAssociation(BaseModel):
    """Model for associating a replica with a Digital Twin."""
    replica_id: UUID = Field(..., description="ID of the Digital Replica")
    data_mapping: Optional[Dict[str, str]] = Field(None, description="Optional data field mapping")


class ServiceBinding(BaseModel):
    """Model for binding a service to a Digital Twin."""
    service_id: UUID = Field(..., description="ID of the Service")
    capability_binding: Dict[str, Any] = Field(..., description="Capability binding configuration")


class DigitalTwinResponse(BaseModel):
    """Response model for Digital Twin operations."""
    id: UUID
    twin_type: str
    name: str
    description: str
    current_state: str
    capabilities: List[str]
    created_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class CapabilityExecutionResponse(BaseModel):
    """Response model for capability execution."""
    twin_id: UUID
    capability: str
    result: Dict[str, Any]
    executed_at: str
    success: bool = True
    error: Optional[str] = None


# =========================
# DIGITAL TWIN CRUD
# =========================

@router.get("/", summary="List Digital Twins")
async def list_digital_twins(
    gateway: APIGateway = Depends(get_gateway),
    twin_type: Optional[str] = Query(None, description="Filter by twin type"),
    capabilities: Optional[List[str]] = Query(None, description="Filter by capabilities"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip")
) -> Dict[str, Any]:
    """List Digital Twins with optional filtering."""
    try:
        filters = {}
        if twin_type:
            filters['twin_type'] = twin_type
        if capabilities:
            filters['capabilities'] = capabilities
        
        return await gateway.list_digital_twins(
            filters=filters,
            limit=limit,
            offset=offset
        )
    except Exception as e:
        logger.error(f"Failed to list Digital Twins: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list Digital Twins: {e}"
        )


@router.post("/", summary="Create Digital Twin")
async def create_digital_twin(
    twin_data: DigitalTwinCreate = Body(...),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """
    Create a new Digital Twin.
    UPDATED: Now supports plugin-based capabilities.
    """
    try:
        # Convert to internal format (this now uses registry validation)
        twin_config = twin_data.dict()
        
        # Create the twin
        result = await gateway.create_digital_twin(twin_config)
        
        logger.info(f"Created Digital Twin {result.get('id')} with capabilities: {twin_data.capabilities}")
        return result
        
    except ValueError as e:
        # This catches capability validation errors
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to create Digital Twin: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create Digital Twin: {e}"
        )


@router.get("/capabilities", summary="List Available Capabilities")
async def list_capabilities(
    namespace: Optional[str] = Query(None, description="Filter by namespace"),
    category: Optional[str] = Query(None, description="Filter by category"),
    twin_type: Optional[str] = Query(None, description="Filter by twin type compatibility")
) -> Dict[str, Any]:
    """List all available capabilities with optional filtering."""
    try:
        registry = get_capability_registry()
        capabilities = registry.list_capabilities(
            namespace=namespace,
            category=category,
            twin_type=twin_type
        )
        
        capability_info = [
            CapabilityInfo(
                name=cap.name,
                namespace=cap.namespace,
                full_name=cap.full_name,
                description=cap.description,
                category=cap.category,
                required_permissions=cap.required_permissions,
                required_twin_types=cap.required_twin_types
            ).dict() for cap in capabilities
        ]
        
        return {
            "capabilities": capability_info,
            "total_count": len(capability_info),
            "namespaces": registry.get_namespaces(),
            "filters_applied": {
                "namespace": namespace,
                "category": category,
                "twin_type": twin_type
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to list capabilities: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve capabilities: {e}"
        )


@router.get("/capabilities/{capability_name}", summary="Get Capability Details")
async def get_capability_details(
    capability_name: str = Path(..., description="Full capability name (e.g., 'energy.blade_control')")
) -> Dict[str, Any]:
    """Get detailed information about a specific capability."""
    try:
        registry = get_capability_registry()
        capability = registry.get_capability(capability_name)
        
        if not capability:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Capability '{capability_name}' not found"
            )
        
        return {
            "capability": capability.to_dict(),
            "handler_available": registry.get_handler(capability_name) is not None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get capability details for {capability_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve capability details: {e}"
        )

@router.get("/{twin_id}", summary="Get Digital Twin")
async def get_digital_twin(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get Digital Twin information."""
    try:
        return await gateway.get_digital_twin(twin_id)
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Twin {twin_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to get Digital Twin {twin_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get Digital Twin: {e}"
        )


@router.delete("/{twin_id}", summary="Delete Digital Twin")
async def delete_digital_twin(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, str]:
    """Delete a Digital Twin."""
    try:
        # Note: This would need to be implemented in the gateway
        # For now, return a placeholder response
        return {
            "message": f"Digital Twin {twin_id} deletion requested",
            "status": "accepted"
        }
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Twin {twin_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to delete Digital Twin {twin_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete Digital Twin: {e}"
        )


# =========================
# CAPABILITY EXECUTION
# =========================

@router.post("/{twin_id}/execute", summary="Execute Digital Twin Capability")
async def execute_capability(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    execution_data: CapabilityExecution = Body(...),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """
    Execute a capability on a Digital Twin.
    UPDATED: Now works with plugin-based capability system.
    """
    try:
        result = await gateway.execute_twin_capability(
            twin_id=twin_id,
            capability=execution_data.capability,
            input_data=execution_data.input_data,
            execution_config=execution_data.execution_config
        )
        
        return result
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Twin {twin_id} not found"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to execute capability on twin {twin_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Capability execution failed: {e}"
        )

@router.post("/{twin_id}/predict", summary="Execute Prediction Capability")
async def predict(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    prediction_horizon: int = Body(300, ge=1, description="Prediction horizon in seconds"),
    scenario: Optional[Dict[str, Any]] = Body(None, description="Scenario parameters"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Execute prediction capability on a Digital Twin."""
    try:
        execution_data = {
            "horizon": prediction_horizon,
            "scenario": scenario
        }
        
        result = await gateway.execute_twin_capability(
            twin_id=twin_id,
            capability="prediction",
            input_data=execution_data
        )
        
        return result
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Twin {twin_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to execute prediction on twin {twin_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prediction failed: {e}"
        )


@router.post("/{twin_id}/simulate", summary="Execute Simulation Capability")
async def simulate(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    simulation_config: Dict[str, Any] = Body(..., description="Simulation configuration"),
    duration: int = Body(60, ge=1, description="Simulation duration in seconds"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Execute simulation capability on a Digital Twin."""
    try:
        execution_data = {
            "config": simulation_config,
            "duration": duration
        }
        
        result = await gateway.execute_twin_capability(
            twin_id=twin_id,
            capability="simulation",
            input_data=execution_data
        )
        
        return result
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Twin {twin_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to execute simulation on twin {twin_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Simulation failed: {e}"
        )

@router.get("/{twin_id}/data/latest", summary="Get Latest Device Data")
async def get_latest_data(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    device_ids: Optional[List[str]] = Query(None, description="Filter by device IDs"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of data points"),
    min_quality: float = Query(0.0, ge=0.0, le=1.0, description="Minimum quality threshold"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get latest data from all replicas associated with this Digital Twin."""
    try:
        # Get all replicas for this digital twin
        replicas = await gateway.virtualization_orchestrator.registry.find_replicas_by_digital_twin(twin_id)
        
        if not replicas:
            return {
                "twin_id": str(twin_id),
                "data": [],
                "message": "No replicas found for this Digital Twin",
                "retrieved_at": datetime.now(timezone.utc).isoformat()
            }
        
        # Create temporary data retrieval service
        service_id = uuid4()
        metadata = BaseMetadata(
            entity_id=service_id,
            timestamp=datetime.now(timezone.utc),
            version="1.0.0",
            created_by=uuid4()
        )
        
        data_service = DataRetrievalService(
            service_id=service_id,
            digital_twin_id=twin_id,
            metadata=metadata,
            virtualization_orchestrator=gateway.virtualization_orchestrator
        )
        
        # Collect data from all replicas
        all_data = []
        
        for replica in replicas:
            try:
                input_data = {
                    "retrieval_type": "latest",
                    "replica_id": str(replica.id),
                    "device_ids": device_ids,
                    "limit": limit,
                    "min_quality": min_quality,
                    "include_metadata": True
                }
                
                result = await data_service.execute(input_data)
                if result["status"] == "success":
                    replica_data = result["data"]
                    for data_point in replica_data:
                        data_point["replica_id"] = str(replica.id)
                    all_data.extend(replica_data)
                    
            except Exception as e:
                logger.warning(f"Failed to retrieve data from replica {replica.id}: {e}")
                continue
        
        # Sort by timestamp and apply global limit
        all_data.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        limited_data = all_data[:limit]
        
        return {
            "twin_id": str(twin_id),
            "data_points": len(limited_data),
            "replicas_queried": len(replicas),
            "data": limited_data,
            "query_params": {
                "device_ids": device_ids,
                "limit": limit,
                "min_quality": min_quality
            },
            "retrieved_at": datetime.now(timezone.utc).isoformat()
        }
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Twin {twin_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to get data summary for twin {twin_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Data summary retrieval failed: {e}"
        )

@router.get("/{twin_id}/devices", summary="Get Twin Device Information")
async def get_twin_devices(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    include_data: bool = Query(False, description="Include latest data for each device"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get information about all devices associated with this Digital Twin."""
    try:
        # Get all replicas for this digital twin
        replicas = await gateway.virtualization_orchestrator.registry.find_replicas_by_digital_twin(twin_id)
        
        if not replicas:
            return {
                "twin_id": str(twin_id),
                "devices": {},
                "message": "No replicas found for this Digital Twin"
            }
        
        # Create data retrieval service if needed
        data_service = None
        if include_data:
            service_id = uuid4()
            metadata = BaseMetadata(
                entity_id=service_id,
                timestamp=datetime.now(timezone.utc),
                version="1.0.0",
                created_by=uuid4()
            )
            
            data_service = DataRetrievalService(
                service_id=service_id,
                digital_twin_id=twin_id,
                metadata=metadata,
                virtualization_orchestrator=gateway.virtualization_orchestrator
            )
        
        # Collect device information from all replicas
        all_devices = {}
        
        for replica in replicas:
            try:
                input_data = {
                    "retrieval_type": "device_summary",
                    "replica_id": str(replica.id),
                    "include_metadata": True
                }
                
                if data_service:
                    result = await data_service.execute(input_data)
                    if result["status"] == "success":
                        devices_info = result["data"]["devices"]
                        for device_id, device_info in devices_info.items():
                            if device_id not in all_devices:
                                all_devices[device_id] = {
                                    "device_id": device_id,
                                    "replicas": [],
                                    "total_data_points": 0,
                                    "average_quality": 0,
                                    "last_data_time": None,
                                    "status": "inactive"
                                }
                            
                            # Add replica information
                            replica_info = {
                                "replica_id": str(replica.id),
                                "replica_type": getattr(replica, 'replica_type', 'unknown'),
                                "data_count": device_info.get("data_count", 0),
                                "quality_score": device_info.get("quality_score", 0),
                                "last_data": device_info.get("last_data"),
                                "association_type": device_info.get("association_type", "unknown")
                            }
                            
                            all_devices[device_id]["replicas"].append(replica_info)
                            all_devices[device_id]["total_data_points"] += device_info.get("data_count", 0)
                            
                            # Update status and timestamps
                            if device_info.get("status") == "active":
                                all_devices[device_id]["status"] = "active"
                            
                            device_last_time = device_info.get("last_data")
                            if device_last_time:
                                if not all_devices[device_id]["last_data_time"] or device_last_time > all_devices[device_id]["last_data_time"]:
                                    all_devices[device_id]["last_data_time"] = device_last_time
                else:
                    # Just get basic device list without data
                    registry = gateway.virtualization_orchestrator.registry
                    replica_devices = registry.replica_to_devices.get(replica.id, set())
                    
                    for device_id in replica_devices:
                        if device_id not in all_devices:
                            all_devices[device_id] = {
                                "device_id": device_id,
                                "replicas": [],
                                "status": "unknown"
                            }
                        
                        all_devices[device_id]["replicas"].append({
                            "replica_id": str(replica.id),
                            "replica_type": getattr(replica, 'replica_type', 'unknown')
                        })
                        
            except Exception as e:
                logger.warning(f"Failed to get device info from replica {replica.id}: {e}")
                continue
        
        # Calculate average quality for each device
        if include_data:
            for device_id, device_info in all_devices.items():
                if device_info["replicas"]:
                    quality_scores = [r.get("quality_score", 0) for r in device_info["replicas"] if "quality_score" in r]
                    if quality_scores:
                        device_info["average_quality"] = sum(quality_scores) / len(quality_scores)
        
        return {
            "twin_id": str(twin_id),
            "total_devices": len(all_devices),
            "total_replicas": len(replicas),
            "include_data": include_data,
            "devices": all_devices,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Twin {twin_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to get devices for twin {twin_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Device information retrieval failed: {e}"
        )

@router.post("/{twin_id}/data/query", summary="Advanced Data Query")
async def query_twin_data(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    query_params: Dict[str, Any] = Body(..., description="Advanced query parameters"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Execute advanced data query on Digital Twin."""
    try:
        # Validate query parameters
        retrieval_type = query_params.get("retrieval_type", "latest")
        if retrieval_type not in ["latest", "historical", "aggregated", "device_summary"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid retrieval_type. Must be one of: latest, historical, aggregated, device_summary"
            )
        
        # Get all replicas for this digital twin
        replicas = await gateway.virtualization_orchestrator.registry.find_replicas_by_digital_twin(twin_id)
        
        if not replicas:
            return {
                "twin_id": str(twin_id),
                "query": query_params,
                "results": [],
                "message": "No replicas found for this Digital Twin"
            }
        
        # Create data retrieval service
        service_id = uuid4()
        metadata = BaseMetadata(
            entity_id=service_id,
            timestamp=datetime.now(timezone.utc),
            version="1.0.0",
            created_by=uuid4()
        )
        
        data_service = DataRetrievalService(
            service_id=service_id,
            digital_twin_id=twin_id,
            metadata=metadata,
            virtualization_orchestrator=gateway.virtualization_orchestrator
        )
        
        # Execute query on all replicas
        results = []
        
        for replica in replicas:
            try:
                # Add replica_id to query parameters
                replica_query = query_params.copy()
                replica_query["replica_id"] = str(replica.id)
                
                result = await data_service.execute(replica_query)
                if result["status"] == "success":
                    replica_result = {
                        "replica_id": str(replica.id),
                        "replica_type": getattr(replica, 'replica_type', 'unknown'),
                        "query": result["query"],
                        "data": result["data"],
                        "retrieved_at": result["retrieved_at"]
                    }
                    results.append(replica_result)
                    
            except Exception as e:
                logger.warning(f"Failed to execute query on replica {replica.id}: {e}")
                error_result = {
                    "replica_id": str(replica.id),
                    "error": str(e),
                    "status": "failed"
                }
                results.append(error_result)
        
        return {
            "twin_id": str(twin_id),
            "query": query_params,
            "results_count": len(results),
            "successful_queries": len([r for r in results if "error" not in r]),
            "failed_queries": len([r for r in results if "error" in r]),
            "results": results,
            "executed_at": datetime.now(timezone.utc).isoformat()
        }
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Twin {twin_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to execute data query for twin {twin_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Data query execution failed: {e}"
        )

@router.get("/{twin_id}/data/historical", summary="Get Historical Device Data")
async def get_historical_data(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    start_time: Optional[str] = Query(None, description="Start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time (ISO format)"),
    device_ids: Optional[List[str]] = Query(None, description="Filter by device IDs"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of data points"),
    min_quality: float = Query(0.0, ge=0.0, le=1.0, description="Minimum quality threshold"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get historical data from replicas within a time range."""
    try:
        # 🔍 DEBUG: Check registry state
        dr_registry = gateway.virtualization_orchestrator.registry
        logger.info(f"🔍 DEBUG: Looking for replicas for twin {twin_id}")
        
        # Check the mapping directly
        replica_ids_in_mapping = set()
        try:
            from src.layers.digital_twin.association_manager import get_association_manager
            association_manager = await get_association_manager()
            replica_ids_in_mapping = await association_manager.get_replicas_for_twin(twin_id)
        except Exception as e:
            logger.error(f"Failed to get replicas from persistent storage: {e}")
        logger.info(f"🔍 DEBUG: Replica IDs in mapping for twin {twin_id}: {replica_ids_in_mapping}")
        
        # Try to get each replica manually
        found_replicas = []
        failed_replica_ids = []
        
        for replica_id in replica_ids_in_mapping:
            try:
                replica = await dr_registry.get_digital_replica(replica_id)
                found_replicas.append(replica)
                logger.info(f"✅ DEBUG: Successfully got replica {replica_id}")
            except Exception as e:
                failed_replica_ids.append(replica_id)
                logger.error(f"❌ DEBUG: Failed to get replica {replica_id}: {e}")
        
        logger.info(f"🔍 DEBUG: Manual check - Found {len(found_replicas)} replicas, Failed {len(failed_replica_ids)}")
        
        # Now call the official method
        replicas = await dr_registry.find_replicas_by_digital_twin(twin_id)
        logger.info(f"🔍 DEBUG: Official method found {len(replicas)} replicas")
        
        # Check mapping after official call
        replica_ids_after = dr_registry.digital_twin_replicas.get(twin_id, set())
        logger.info(f"🔍 DEBUG: Replica IDs in mapping AFTER official call: {replica_ids_after}")
        
        if not replicas:
            # 🔍 DEBUG: More detailed info
            all_replicas = await dr_registry.list()
            logger.info(f"🔍 DEBUG: Total replicas in system: {len(all_replicas)}")
            for replica in all_replicas[:3]:  # Show first 3
                parent_id = getattr(replica, 'parent_digital_twin_id', 'N/A')
                logger.info(f"🔍 DEBUG: Replica {replica.id} -> parent: {parent_id}")
            
            return {
                "twin_id": str(twin_id),
                "data": [],
                "message": "No replicas found for this Digital Twin",
                "debug_info": {
                    "replica_ids_in_mapping": [str(rid) for rid in replica_ids_in_mapping],
                    "found_replicas_manual": len(found_replicas),
                    "failed_replica_ids": [str(rid) for rid in failed_replica_ids],
                    "replica_ids_after_official_call": [str(rid) for rid in replica_ids_after],
                    "mapping_was_cleaned": len(replica_ids_in_mapping) != len(replica_ids_after)
                }
            }
        
        # Create data retrieval service
        service_id = uuid4()
        metadata = BaseMetadata(
            entity_id=service_id,
            timestamp=datetime.now(timezone.utc),
            version="1.0.0",
            created_by=uuid4()
        )
        
        data_service = DataRetrievalService(
            service_id=service_id,
            digital_twin_id=twin_id,
            metadata=metadata,
            virtualization_orchestrator=gateway.virtualization_orchestrator
        )
        
        # Collect historical data from all replicas
        all_data = []
        
        for replica in replicas:
            try:
                input_data = {
                    "retrieval_type": "historical",
                    "replica_id": str(replica.id),
                    "start_time": start_time,
                    "end_time": end_time,
                    "device_ids": device_ids,
                    "limit": limit,
                    "min_quality": min_quality,
                    "include_metadata": True
                }
                
                result = await data_service.execute(input_data)
                if result["status"] == "success":
                    replica_data = result["data"]
                    for data_point in replica_data:
                        data_point["replica_id"] = str(replica.id)
                    all_data.extend(replica_data)
                    
            except Exception as e:
                logger.warning(f"Failed to retrieve historical data from replica {replica.id}: {e}")
                continue
        
        # Sort by timestamp
        all_data.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        limited_data = all_data[:limit]
        
        return {
            "twin_id": str(twin_id),
            "data_points": len(limited_data),
            "replicas_queried": len(replicas),
            "time_range": {
                "start": start_time,
                "end": end_time
            },
            "data": limited_data,
            "retrieved_at": datetime.now(timezone.utc).isoformat()
        }
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Twin {twin_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to get historical data for twin {twin_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Historical data retrieval failed: {e}"
        )

@router.get("/{twin_id}/data/summary", summary="Get Data Summary")
async def get_data_summary(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    device_ids: Optional[List[str]] = Query(None, description="Filter by device IDs"),
    time_range_hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get aggregated data summary for this Digital Twin."""
    try:
        # Get all replicas for this digital twin
        replicas = await gateway.virtualization_orchestrator.registry.find_replicas_by_digital_twin(twin_id)
        
        if not replicas:
            return {
                "twin_id": str(twin_id),
                "summary": {"total_replicas": 0, "total_devices": 0, "total_data_points": 0},
                "devices": {},
                "message": "No replicas found for this Digital Twin"
            }
        
        # Create data retrieval service
        service_id = uuid4()
        metadata = BaseMetadata(
            entity_id=service_id,
            timestamp=datetime.now(timezone.utc),
            version="1.0.0",
            created_by=uuid4()
        )
        
        data_service = DataRetrievalService(
            service_id=service_id,
            digital_twin_id=twin_id,
            metadata=metadata,
            virtualization_orchestrator=gateway.virtualization_orchestrator
        )
        
        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=time_range_hours)
        
        # Collect summary data from all replicas
        all_summaries = []
        total_devices = set()
        total_data_points = 0
        
        for replica in replicas:
            try:
                input_data = {
                    "retrieval_type": "aggregated",
                    "replica_id": str(replica.id),
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "device_ids": device_ids,
                    "include_metadata": True
                }
                
                result = await data_service.execute(input_data)
                if result["status"] == "success":
                    summary_data = result["data"]
                    summary_data["replica_id"] = str(replica.id)
                    summary_data["replica_type"] = getattr(replica, 'replica_type', 'unknown')
                    all_summaries.append(summary_data)
                    
                    # Aggregate totals
                    if "devices" in summary_data:
                        total_devices.update(summary_data["devices"].keys())
                    if "summary" in summary_data and "total_data_points" in summary_data["summary"]:
                        total_data_points += summary_data["summary"]["total_data_points"]
                        
            except Exception as e:
                logger.warning(f"Failed to get summary from replica {replica.id}: {e}")
                continue
        
        # Combine device information
        combined_devices = {}
        for summary in all_summaries:
            if "devices" in summary:
                for device_id, device_info in summary["devices"].items():
                    if device_id not in combined_devices:
                        combined_devices[device_id] = {
                            "device_id": device_id,
                            "total_data_points": 0,
                            "average_quality": 0,
                            "last_data_time": None,
                            "replicas": []
                        }
                    
                    combined_devices[device_id]["total_data_points"] += device_info.get("total_data_points", 0)
                    combined_devices[device_id]["replicas"].append({
                        "replica_id": summary["replica_id"],
                        "data_points": device_info.get("total_data_points", 0),
                        "quality": device_info.get("average_quality", 0)
                    })
                    
                    # Update latest timestamp
                    device_last_time = device_info.get("last_data_time")
                    if device_last_time:
                        if not combined_devices[device_id]["last_data_time"] or device_last_time > combined_devices[device_id]["last_data_time"]:
                            combined_devices[device_id]["last_data_time"] = device_last_time
        
        # Calculate average quality per device
        for device_id, device_info in combined_devices.items():
            if device_info["replicas"]:
                avg_quality = sum(r["quality"] for r in device_info["replicas"]) / len(device_info["replicas"])
                device_info["average_quality"] = avg_quality
        
        return {
            "twin_id": str(twin_id),
            "summary": {
                "total_replicas": len(replicas),
                "total_devices": len(total_devices),
                "total_data_points": total_data_points,
                "time_range_hours": time_range_hours,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat()
            },
            "devices": combined_devices,
            "replicas": all_summaries,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
                logger.warning(f"Failed to get summary from replica {replica.id}: {e}")
                
# =========================
# ECOSYSTEM MANAGEMENT
# =========================

@router.get("/{twin_id}/ecosystem", summary="Get Digital Twin Ecosystem Status")
async def get_ecosystem_status(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get comprehensive ecosystem status for a Digital Twin."""
    try:
        return await gateway.get_twin_ecosystem_status(twin_id)
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Twin {twin_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to get ecosystem status for twin {twin_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get ecosystem status: {e}"
        )


@router.post("/{twin_id}/replicas", summary="Associate Digital Replica")
async def associate_replica(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    association_data: ReplicaAssociation = Body(...),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Associate a Digital Replica with a Digital Twin."""
    try:
        replica_id = association_data.replica_id
        data_mapping = association_data.data_mapping
        
        logger.info(f"Associating replica {replica_id} with twin {twin_id}")
        
        # 1. Verify both entities exist
        try:
            # Check if Digital Twin exists
            dt_registry = gateway.dt_orchestrator.registry
            twin = await dt_registry.get_digital_twin(twin_id)
            logger.info(f"Found Digital Twin: {twin_id}")
            
            # Check if Digital Replica exists
            replica_registry = gateway.virtualization_orchestrator.registry
            replica = await replica_registry.get_digital_replica(replica_id)
            logger.info(f"Found Digital Replica: {replica_id}")
            
        except EntityNotFoundError as e:
            logger.error(f"Entity not found: {e}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e)
            )
        
        # 2. Use the orchestrator to create association
        await gateway.dt_orchestrator.associate_replica_with_twin(
            twin_id, replica_id, data_mapping
        )
        
        return {
            "message": f"Replica {replica_id} associated with twin {twin_id}",
            "twin_id": str(twin_id),
            "replica_id": str(replica_id),
            "data_mapping": data_mapping, 
            "status": "success",
            "associated_at": datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to associate replica with twin {twin_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Replica association failed: {e}"
        )
@router.post("/{twin_id}/services", summary="Bind Service to Digital Twin")
async def bind_service(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    binding_data: ServiceBinding = Body(...),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, str]:
    """Bind a Service to a Digital Twin for capability provision."""
    try:
        # Note: This would need to be implemented in the gateway
        # For now, return a placeholder response
        return {
            "message": f"Service {binding_data.service_id} bound to twin {twin_id}",
            "status": "success"
        }
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Twin {twin_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to bind service to twin {twin_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Service binding failed: {e}"
        )


# =========================
# ANALYSIS & DISCOVERY
# =========================

@router.get("/{twin_id}/context", summary="Get Full Context")
async def get_full_context(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get full context for a Digital Twin across all layers."""
    try:
        from src.layers.application.api_gateway import RequestType
        return await gateway.get_entity_full_context(RequestType.DIGITAL_TWIN, twin_id)
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Twin {twin_id} not found"
        )
    except Exception as e:
        logger.error(f"Failed to get full context for twin {twin_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get full context: {e}"
        )


@router.get("/types/available", summary="Get Available Digital Twin Types")
async def get_available_types() -> Dict[str, List[str]]:
    """Get available Digital Twin types and capabilities."""
    return {
        "twin_types": [t.value for t in DigitalTwinType],
        "capabilities": [c.value for c in TwinCapability]
    }


@router.get("/templates/available", summary="Get Available Templates")
async def get_available_templates(
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get available Digital Twin templates."""
    try:
        # This would call the ontology manager through the gateway
        # For now, return placeholder data
        return {
            "templates": [
                {
                    "template_id": "industrial_asset",
                    "name": "Industrial Asset Twin",
                    "description": "Template for industrial asset monitoring"
                },
                {
                    "template_id": "smart_building",
                    "name": "Smart Building Twin", 
                    "description": "Template for smart building management"
                }
            ]
        }
    except Exception as e:
        logger.error(f"Failed to get available templates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get templates: {e}"
        )