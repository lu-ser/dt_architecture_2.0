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

from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body, status
from pydantic import BaseModel, Field, validator

from src.layers.application.api_gateway import APIGateway
from src.layers.application.api import get_gateway
from src.core.interfaces.digital_twin import TwinCapability, DigitalTwinType
from src.utils.exceptions import EntityNotFoundError

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
    def validate_twin_type(cls, v):
        try:
            DigitalTwinType(v)
            return v
        except ValueError:
            valid_types = [t.value for t in DigitalTwinType]
            raise ValueError(f"Invalid twin_type. Must be one of: {valid_types}")
    
    @validator('capabilities')
    def validate_capabilities(cls, v):
        try:
            for cap in v:
                TwinCapability(cap)
            return v
        except ValueError as e:
            valid_caps = [c.value for c in TwinCapability]
            raise ValueError(f"Invalid capability. Must be one of: {valid_caps}")


class CapabilityExecution(BaseModel):
    """Model for executing a Digital Twin capability."""
    capability: str = Field(..., description="Capability to execute")
    input_data: Dict[str, Any] = Field(..., description="Input data for execution")
    execution_config: Optional[Dict[str, Any]] = Field(None, description="Execution configuration")
    
    @validator('capability')
    def validate_capability(cls, v):
        try:
            TwinCapability(v)
            return v
        except ValueError:
            valid_caps = [c.value for c in TwinCapability]
            raise ValueError(f"Invalid capability. Must be one of: {valid_caps}")


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
        # Build discovery criteria
        criteria = {}
        if twin_type:
            criteria["type"] = twin_type
        if capabilities:
            criteria["has_capability"] = capabilities[0]  # For simplicity, use first capability
        
        # Discover twins
        from src.layers.application.api_gateway import RequestType
        twins = await gateway.discover_entities(RequestType.DIGITAL_TWIN, criteria)
        
        # Apply pagination
        total = len(twins)
        paginated_twins = twins[offset:offset + limit]
        
        return {
            "twins": paginated_twins,
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "count": len(paginated_twins)
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to list Digital Twins: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list Digital Twins: {e}"
        )


@router.post("/", summary="Create Digital Twin", response_model=DigitalTwinResponse)
async def create_digital_twin(
    twin_data: DigitalTwinCreate,
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Create a new Digital Twin."""
    try:
        # Convert Pydantic model to dict
        twin_config = twin_data.dict()
        
        # Create Digital Twin via gateway
        result = await gateway.create_digital_twin(twin_config)
        
        return result
        
    except ValueError as e:
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


@router.get("/{twin_id}", summary="Get Digital Twin", response_model=DigitalTwinResponse)
async def get_digital_twin(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get a specific Digital Twin by ID."""
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
    """Execute a capability on a Digital Twin."""
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
) -> Dict[str, str]:
    """Associate a Digital Replica with a Digital Twin."""
    try:
        # Note: This would need to be implemented in the gateway
        # For now, return a placeholder response
        return {
            "message": f"Replica {association_data.replica_id} associated with twin {twin_id}",
            "status": "success"
        }
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Digital Twin {twin_id} not found"
        )
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