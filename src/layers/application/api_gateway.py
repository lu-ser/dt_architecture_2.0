"""
API Gateway for the Digital Twin Platform.
This module provides the central bridge between external requests and internal
platform layers. It handles request routing, response aggregation, and serves
as the main interface for external applications and users.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from uuid import UUID
from enum import Enum

# Import layer orchestrators
from src.layers.digital_twin import get_digital_twin_orchestrator
from src.layers.service import get_service_orchestrator
from src.layers.virtualization import get_virtualization_orchestrator
from src.utils.type_converter import TypeConverter

# Import interfaces and types
from src.core.interfaces.digital_twin import TwinCapability
from src.core.interfaces.service import ServiceType, ServicePriority
from src.core.interfaces.replica import ReplicaType
from src.utils.exceptions import ValidationError
from src.utils.exceptions import (
    APIGatewayError)
from src.utils.config import get_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


class RequestType(Enum):
    """Types of requests that can be handled by the gateway."""
    DIGITAL_TWIN = "digital_twin"
    SERVICE = "service"
    REPLICA = "replica"
    WORKFLOW = "workflow"
    ANALYTICS = "analytics"
    REAL_TIME = "real_time"


class APIGateway:
    """
    Central bridge between external requests and internal platform layers.
    
    Provides simple request routing and response aggregation without
    complex orchestration - just clean interfacing with existing layer orchestrators.
    """
    
    def __init__(self):
        self.config = get_config()
        
        # Layer orchestrators (will be set during initialization)
        self.dt_orchestrator = None
        self.service_orchestrator = None
        self.virtualization_orchestrator = None
        
        # State tracking
        self._initialized = False
        self._layer_connections = {}
        
        logger.info("API Gateway initialized")
    
    async def initialize(self) -> None:
        """Initialize the API Gateway and connect to layer orchestrators."""
        if self._initialized:
            return
        
        try:
            logger.info("Initializing API Gateway...")
            
            # Connect to layer orchestrators
            await self._connect_to_layers()
            
            self._initialized = True
            logger.info("API Gateway initialization completed")
            
        except Exception as e:
            logger.error(f"Failed to initialize API Gateway: {e}")
            raise APIGatewayError(f"Gateway initialization failed: {e}")
    
    async def _connect_to_layers(self) -> None:
        """Connect to all platform layer orchestrators."""
        try:
            # Digital Twin Layer
            self.dt_orchestrator = get_digital_twin_orchestrator()
            if not self.dt_orchestrator._initialized:
                await self.dt_orchestrator.initialize()
            self._layer_connections["digital_twin"] = True
            
            # Service Layer  
            self.service_orchestrator = get_service_orchestrator()
            if not self.service_orchestrator._initialized:
                await self.service_orchestrator.initialize()
            self._layer_connections["service"] = True
            
            # Virtualization Layer
            self.virtualization_orchestrator = get_virtualization_orchestrator()
            if not self.virtualization_orchestrator._initialized:
                await self.virtualization_orchestrator.initialize()
            self._layer_connections["virtualization"] = True
            
            logger.info("Connected to all platform layers")
            
        except Exception as e:
            logger.error(f"Failed to connect to layers: {e}")
            raise APIGatewayError(f"Layer connection failed: {e}")
    
    # =========================
    # DIGITAL TWIN OPERATIONS
    # =========================
    
    async def get_digital_twin(self, twin_id: UUID) -> Dict[str, Any]:
        """Get Digital Twin information."""
        try:
            twin = await self.dt_orchestrator.registry.get_digital_twin(twin_id)
            return twin.to_dict()
        except Exception as e:
            logger.error(f"Failed to get Digital Twin {twin_id}: {e}")
            raise APIGatewayError(f"Failed to retrieve Digital Twin: {e}")
    
    async def create_digital_twin(self, twin_config: Dict[str, Any], user_id: Optional[UUID]=None) -> Dict[str, Any]:
        try:
            # ✅ Convert string to enum using TypeConverter
            try:
                converted_config = TypeConverter.convert_digital_twin_config(twin_config)
            except ValidationError as e:
                raise APIGatewayError(str(e))
            
            # Extract parameters (now with correct types)
            twin_type = converted_config['twin_type']  # DigitalTwinType enum
            capabilities = converted_config['capabilities']  # Set[TwinCapability]
            name = twin_config['name']
            description = twin_config.get('description', '')
            template_id = twin_config.get('template_id')
            customization = twin_config.get('customization')
            parent_twin_id = twin_config.get('parent_twin_id')
            
            # Now call orchestrator with correct types
            twin = await self.dt_orchestrator.create_digital_twin(
                twin_type=twin_type,
                name=name,
                description=description,
                capabilities=capabilities,
                template_id=template_id,
                customization=customization,
                parent_twin_id=parent_twin_id
            )
            
            logger.info(f'Created Digital Twin {twin.id} via API Gateway')
            return twin.to_dict()
            
        except Exception as e:
            logger.error(f'Failed to create Digital Twin: {e}')
            raise APIGatewayError(f'Digital Twin creation failed: {e}')
    
    async def execute_twin_capability(
        self,
        twin_id: UUID,
        capability: str,
        input_data: Dict[str, Any],
        execution_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute a capability on a Digital Twin."""
        try:
            capability_enum = TwinCapability(capability)
            
            result = await self.dt_orchestrator.execute_twin_capability(
                twin_id=twin_id,
                capability=capability_enum,
                input_data=input_data,
                execution_config=execution_config
            )
            
            return {
                "twin_id": str(twin_id),
                "capability": capability,
                "result": result,
                "executed_at": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to execute capability {capability} on twin {twin_id}: {e}")
            raise APIGatewayError(f"Capability execution failed: {e}")
    
    async def get_twin_ecosystem_status(self, twin_id: UUID) -> Dict[str, Any]:
        """Get comprehensive ecosystem status for a Digital Twin."""
        try:
            return await self.dt_orchestrator.get_twin_ecosystem_status(twin_id)
        except Exception as e:
            logger.error(f"Failed to get ecosystem status for twin {twin_id}: {e}")
            raise APIGatewayError(f"Ecosystem status retrieval failed: {e}")
    
    # =========================
    # SERVICE OPERATIONS
    # =========================
    
    async def get_service(self, service_id: UUID) -> Dict[str, Any]:
        """Get Service information."""
        try:
            service = await self.service_orchestrator.registry.get_service(service_id)
            return service.to_dict()
        except Exception as e:
            logger.error(f"Failed to get Service {service_id}: {e}")
            raise APIGatewayError(f"Failed to retrieve Service: {e}")
    
    async def create_service(
        self,
        service_config: Dict[str, Any],
        user_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """Create a new Service."""
        try:
            # Determine creation method
            if "template_id" in service_config:
                service = await self.service_orchestrator.create_service_from_template(
                    template_id=service_config["template_id"],
                    digital_twin_id=UUID(service_config["digital_twin_id"]),
                    instance_name=service_config["instance_name"],
                    overrides=service_config.get("overrides", {})
                )
            else:
                service = await self.service_orchestrator.create_service_from_definition(
                    definition_id=service_config["definition_id"],
                    digital_twin_id=UUID(service_config["digital_twin_id"]),
                    instance_name=service_config["instance_name"],
                    parameters=service_config.get("parameters", {}),
                    execution_config=service_config.get("execution_config", {})
                )
            
            logger.info(f"Created Service {service.id} via API Gateway")
            return service.to_dict()
            
        except Exception as e:
            logger.error(f"Failed to create Service: {e}")
            raise APIGatewayError(f"Service creation failed: {e}")
    
    async def execute_service(
        self,
        service_id: UUID,
        input_data: Dict[str, Any],
        execution_parameters: Optional[Dict[str, Any]] = None,
        async_execution: bool = False
    ) -> Dict[str, Any]:
        """Execute a Service."""
        try:
            result = await self.service_orchestrator.execute_service(
                service_id=service_id,
                input_data=input_data,
                execution_parameters=execution_parameters,
                async_execution=async_execution
            )
            
            if async_execution:
                return {
                    "execution_id": str(result),
                    "service_id": str(service_id),
                    "status": "running",
                    "started_at": datetime.now(timezone.utc).isoformat()
                }
            else:
                return result.to_dict() if hasattr(result, 'to_dict') else result
                
        except Exception as e:
            logger.error(f"Failed to execute Service {service_id}: {e}")
            raise APIGatewayError(f"Service execution failed: {e}")
    
    # =========================
    # DIGITAL REPLICA OPERATIONS
    # =========================
    
    async def get_replica(self, replica_id: UUID) -> Dict[str, Any]:
        """Get Digital Replica information."""
        try:
            replica = await self.virtualization_orchestrator.registry.get_digital_replica(replica_id)
            return replica.to_dict()
        except Exception as e:
            logger.error(f"Failed to get Digital Replica {replica_id}: {e}")
            raise APIGatewayError(f"Failed to retrieve Digital Replica: {e}")
    
    async def create_replica(self, replica_config: Dict[str, Any], user_id: Optional[UUID] = None) -> Dict[str, Any]:
        try:
            # FIX: Ensure consistent UUID handling in API Gateway
            if 'parent_digital_twin_id' in replica_config:
                twin_id = replica_config['parent_digital_twin_id']
                if isinstance(twin_id, str):
                    try:
                        replica_config['parent_digital_twin_id'] = UUID(twin_id)
                    except ValueError as e:
                        raise APIGatewayError(f'Invalid parent_digital_twin_id format: {twin_id}')
                elif not isinstance(twin_id, UUID):
                    raise APIGatewayError(f'parent_digital_twin_id must be UUID or string, got {type(twin_id)}')
            
            if 'template_id' in replica_config:
                replica = await self.virtualization_orchestrator.create_replica_from_template(
                    template_id=replica_config['template_id'],
                    parent_digital_twin_id=replica_config['parent_digital_twin_id'],
                    device_ids=replica_config['device_ids'],
                    overrides=replica_config.get('overrides', {})
                )
            else:
                replica = await self.virtualization_orchestrator.create_replica_from_configuration(
                    replica_type=ReplicaType(replica_config['replica_type']),
                    parent_digital_twin_id=replica_config['parent_digital_twin_id'],
                    device_ids=replica_config['device_ids'],
                    aggregation_mode=DataAggregationMode(replica_config['aggregation_mode']),
                    configuration=replica_config.get('configuration', {})
                )
            
            logger.info(f'Created Digital Replica {replica.id} via API Gateway')
            return replica.to_dict()
            
        except Exception as e:
            logger.error(f'Failed to create Digital Replica: {e}')
            raise APIGatewayError(f'Digital Replica creation failed: {e}')
    # =========================
    # WORKFLOW OPERATIONS
    # =========================
    
    async def create_cross_twin_workflow(
        self,
        workflow_config: Dict[str, Any],
        user_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """Create a cross-twin workflow."""
        try:
            workflow_id = await self.dt_orchestrator.create_cross_twin_workflow(
                workflow_name=workflow_config["workflow_name"],
                twin_operations=workflow_config["twin_operations"],
                workflow_config=workflow_config.get("config", {})
            )
            
            return {
                "workflow_id": str(workflow_id),
                "workflow_name": workflow_config["workflow_name"],
                "status": "created",
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to create cross-twin workflow: {e}")
            raise APIGatewayError(f"Workflow creation failed: {e}")
    
    async def execute_workflow(
        self,
        workflow_id: UUID,
        input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a workflow."""
        try:
            execution_id = await self.dt_orchestrator.execute_cross_twin_workflow(
                workflow_id=workflow_id,
                input_data=input_data
            )
            
            return {
                "workflow_id": str(workflow_id),
                "execution_id": str(execution_id),
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to execute workflow {workflow_id}: {e}")
            raise APIGatewayError(f"Workflow execution failed: {e}")
    
    # =========================
    # ANALYTICS & DISCOVERY
    # =========================
    
    async def discover_entities(
        self,
        entity_type: RequestType,
        criteria: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Discover entities based on criteria."""
        try:
            if entity_type == RequestType.DIGITAL_TWIN:
                twins = await self.dt_orchestrator.registry.discover_twins_advanced(criteria)
                return [twin.to_dict() for twin in twins]
            
            elif entity_type == RequestType.SERVICE:
                services = await self.service_orchestrator.discover_services(criteria)
                return services
            
            elif entity_type == RequestType.REPLICA:
                replicas = await self.virtualization_orchestrator.discover_replicas(criteria)
                return replicas
            
            else:
                raise APIGatewayError(f"Unsupported entity type for discovery: {entity_type}")
                
        except Exception as e:
            logger.error(f"Failed to discover {entity_type.value} entities: {e}")
            raise APIGatewayError(f"Entity discovery failed: {e}")
    
    async def get_platform_overview(self) -> Dict[str, Any]:
        """Get comprehensive platform overview."""
        try:
            return await self.dt_orchestrator.get_platform_overview()
        except Exception as e:
            logger.error(f"Failed to get platform overview: {e}")
            raise APIGatewayError(f"Platform overview retrieval failed: {e}")
    
    # =========================
    # CROSS-LAYER AGGREGATION
    # =========================
    
    async def get_entity_full_context(
        self,
        entity_type: RequestType,
        entity_id: UUID
    ) -> Dict[str, Any]:
        """Get full context for an entity across all layers."""
        try:
            context = {
                "entity_id": str(entity_id),
                "entity_type": entity_type.value,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            if entity_type == RequestType.DIGITAL_TWIN:
                # Get twin info
                context["twin"] = await self.get_digital_twin(entity_id)
                
                # Get ecosystem status
                context["ecosystem"] = await self.get_twin_ecosystem_status(entity_id)
                
                # Get associated replicas
                replica_associations = await self.dt_orchestrator.registry.get_twin_associations(
                    entity_id, "data_source", "digital_replica"
                )
                context["replicas"] = [str(assoc.associated_entity_id) for assoc in replica_associations]
                
                # Get bound services
                service_associations = await self.dt_orchestrator.registry.get_twin_associations(
                    entity_id, "capability_provider", "service"
                )
                context["services"] = [str(assoc.associated_entity_id) for assoc in service_associations]
            
            return context
            
        except Exception as e:
            logger.error(f"Failed to get full context for {entity_type.value} {entity_id}: {e}")
            raise APIGatewayError(f"Context retrieval failed: {e}")
    
    # =========================
    # HEALTH & STATUS
    # =========================
    
    async def get_gateway_status(self) -> Dict[str, Any]:
        """Get API Gateway status and health."""
        return {
            "gateway": {
                "initialized": self._initialized,
                "layer_connections": self._layer_connections,
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            "layers": {
                "digital_twin": self.dt_orchestrator._initialized if self.dt_orchestrator else False,
                "service": self.service_orchestrator._initialized if self.service_orchestrator else False,
                "virtualization": self.virtualization_orchestrator._initialized if self.virtualization_orchestrator else False
            }
        }
    
    def is_ready(self) -> bool:
        """Check if the gateway is ready to handle requests."""
        return (
            self._initialized and 
            all(self._layer_connections.values()) and
            self.dt_orchestrator and 
            self.service_orchestrator and 
            self.virtualization_orchestrator
        )


# Global gateway instance
_api_gateway: Optional[APIGateway] = None


def get_api_gateway() -> APIGateway:
    """Get the global API Gateway instance."""
    global _api_gateway
    if _api_gateway is None:
        _api_gateway = APIGateway()
    return _api_gateway


async def initialize_api_gateway() -> APIGateway:
    """Initialize the API Gateway."""
    global _api_gateway
    _api_gateway = APIGateway()
    await _api_gateway.initialize()
    return _api_gateway