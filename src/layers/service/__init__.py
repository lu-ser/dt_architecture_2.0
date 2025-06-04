"""
Service Layer Integration for the Digital Twin Platform.

This module integrates all components of the Service Layer:
- Service Factory with template support
- Service Registry with performance tracking
- Service Management with lifecycle control
- Service orchestration and workflow management

LOCATION: src/layers/service/__init__.py
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
from uuid import UUID, uuid4

# Import all service layer components
from src.layers.service.service_factory import ServiceFactory, StandardService
from src.layers.service.service_registry import ServiceRegistry, ServiceMetrics, ServiceAssociation

# Import interfaces
from src.core.interfaces.base import BaseMetadata, EntityStatus
from src.core.interfaces.service import (
    IService,
    ServiceType,
    ServiceDefinition,
    ServiceConfiguration,
    ServiceExecutionMode,
    ServiceState,
    ServicePriority,
    ServiceRequest,
    ServiceResponse
)
from src.storage import get_twin_storage_adapter, get_global_storage_adapter
from src.storage.adapters import get_registry_cache, get_session_cache
# Import storage adapters (mock for now)
from tests.mocks.storage_adapter import InMemoryStorageAdapter

# Import ontology system for template integration
from src.layers.virtualization.ontology.manager import (
    get_ontology_manager,
    TemplateType
)

from src.utils.exceptions import (
    ServiceError,
    ServiceConfigurationError,
    EntityCreationError
)
from src.utils.config import get_config

logger = logging.getLogger(__name__)


class ServiceLayerOrchestrator:
    """
    Main orchestrator for the Service Layer.
    
    Coordinates all service components and provides a unified interface for
    service management with template and workflow support.
    """
    
    def __init__(self, templates_integration: bool = True):
        self.config = get_config()
        self.templates_integration = templates_integration
        self.factory: Optional[ServiceFactory] = None
        self.registry: Optional[ServiceRegistry] = None
        self._initialized = False
        self._running = False
        
        # Service management
        self.active_workflows: Dict[UUID, Dict[str, Any]] = {}
        self.service_dependencies: Dict[UUID, Set[UUID]] = {}
        
        # NUEVO: Cache instances
        self._registry_cache = None
        self._session_cache = None
        
        logger.info('Initialized ServiceLayerOrchestrator with enhanced storage')
        
    async def initialize(self) -> None:
        if self._initialized:
            logger.warning('ServiceLayerOrchestrator already initialized')
            return
            
        try:
            logger.info('Initializing Service Layer with MongoDB + Redis...')
            
            # Initialize factory
            self.factory = ServiceFactory()
            logger.info('Service Factory initialized')
            
            # NUEVO: Use global storage for services (they can be shared across twins)
            # But we'll create twin-specific adapters when needed
            storage_adapter = get_global_storage_adapter(IService)
            
            # Initialize registry with enhanced caching
            self.registry = ServiceRegistry(
                storage_adapter,
                cache_enabled=True,
                cache_size=1500,
                cache_ttl=600
            )
            await self.registry.connect()
            logger.info('Service Registry initialized with persistent storage')
            
            # NUEVO: Setup caching
            await self._setup_enhanced_caching()
            
            if self.templates_integration:
                await self._integrate_with_templates()
            
            await self._load_default_service_definitions()
            
            self._initialized = True
            logger.info('Service Layer initialized successfully')
            
        except Exception as e:
            logger.error(f'Failed to initialize Service Layer: {e}')
            raise ServiceConfigurationError(f'Service Layer initialization failed: {e}')
    
    async def _setup_enhanced_caching(self) -> None:
        """Setup Redis caching for services."""
        try:
            self._registry_cache = await get_registry_cache()
            self._session_cache = await get_session_cache()
            
            # Integrate with registry
            if hasattr(self.registry, '_setup_redis_cache'):
                await self.registry._setup_redis_cache(self._registry_cache)
            
            logger.info('Service Layer caching setup completed')
            
        except Exception as e:
            logger.warning(f'Failed to setup service caching: {e}')


    async def start(self) -> None:
        """Start the service layer."""
        if not self._initialized:
            await self.initialize()
        
        if self._running:
            logger.warning("ServiceLayerOrchestrator already running")
            return
        
        try:
            logger.info("Starting Service Layer...")
            self._running = True
            logger.info("Service Layer started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start Service Layer: {e}")
            raise ServiceError(f"Service Layer start failed: {e}")
    
    async def stop(self) -> None:
        """Stop the service layer."""
        if not self._running:
            return
        
        try:
            logger.info("Stopping Service Layer...")
            
            # Stop all active workflows
            for workflow_id in list(self.active_workflows.keys()):
                await self.cancel_workflow(workflow_id)
            
            # Disconnect registry
            if self.registry:
                await self.registry.disconnect()
            
            self._running = False
            logger.info("Service Layer stopped successfully")
            
        except Exception as e:
            logger.error(f"Error stopping Service Layer: {e}")
    
    
    async def create_service_from_template(self, template_id: str, digital_twin_id: UUID, 
                                         instance_name: str, overrides: Optional[Dict[str, Any]] = None) -> IService:
        """Create service with twin-specific storage if configured."""
        if not self._initialized:
            await self.initialize()
            
        try:
            ontology_manager = get_ontology_manager()
            template = ontology_manager.get_template(template_id)
            if not template or template.template_type != TemplateType.SERVICE:
                raise ServiceConfigurationError(f'Service template {template_id} not found')
            
            config = ontology_manager.apply_template(template_id, overrides)
            config['digital_twin_id'] = str(digital_twin_id)
            config['instance_name'] = instance_name
            
            # NUEVO: Setup twin-specific storage if enabled
            await self._ensure_twin_service_storage(digital_twin_id)
            
            metadata = BaseMetadata(
                entity_id=uuid4(),
                timestamp=datetime.now(timezone.utc),
                version=template.version,
                created_by=uuid4(),
                custom={
                    'template_id': template_id,
                    'template_name': template.name,
                    'created_from_template': True,
                    'digital_twin_id': str(digital_twin_id)
                }
            )
            
            service = await self.factory.create(config, metadata)
            
            # Register with associations
            associations = [ServiceAssociation(
                service_id=service.id,
                digital_twin_id=digital_twin_id,
                association_type='provides_capability'
            )]
            await self.registry.register_service(service, associations)
            
            # NUOVO: Cache the service
            if self._registry_cache:
                await self._registry_cache.cache_entity(
                    service.id, service.to_dict(), 'Service'
                )
            
            logger.info(f'Created Service {service.id} from template {template_id}')
            return service
            
        except Exception as e:
            logger.error(f'Failed to create service from template {template_id}: {e}')
            raise EntityCreationError(f'Template-based service creation failed: {e}')

    async def _ensure_twin_service_storage(self, twin_id: UUID) -> None:
        """Ensure service storage for specific twin."""
        try:
            if self.config.get('storage.separate_dbs_per_twin', True):
                # Test twin-specific storage
                twin_storage = get_twin_storage_adapter(IService, twin_id)
                await twin_storage.connect()
                health = await twin_storage.health_check()
                
                if health:
                    logger.debug(f'Twin service storage ready for {twin_id}')
                else:
                    logger.warning(f'Twin service storage health check failed for {twin_id}')
                    
        except Exception as e:
            logger.warning(f'Failed to ensure twin service storage for {twin_id}: {e}')

    async def create_workflow(self, workflow_name: str, service_chain: List[Dict[str, Any]], 
                            digital_twin_id: UUID, workflow_config: Optional[Dict[str, Any]] = None) -> UUID:
        """Create workflow with session persistence."""
        workflow_id = uuid4()
        workflow = {
            'workflow_id': workflow_id,
            'workflow_name': workflow_name,
            'digital_twin_id': digital_twin_id,
            'service_chain': service_chain,
            'workflow_config': workflow_config or {},
            'created_at': datetime.now(timezone.utc),
            'status': 'created',
            'execution_history': []
        }
        
        self.active_workflows[workflow_id] = workflow
        
        # NUEVO: Persist in session cache
        if self._session_cache:
            await self._session_cache.store_session(
                f"service_workflow_{workflow_id}",
                workflow
            )
        
        logger.info(f'Created service workflow {workflow_name} with ID {workflow_id}')
        return workflow_id

    async def create_service_from_definition(
        self,
        definition_id: str,
        digital_twin_id: UUID,
        instance_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        execution_config: Optional[Dict[str, Any]] = None
    ) -> IService:
        """
        Create a Service from a service definition.
        
        Args:
            definition_id: ID of the service definition
            digital_twin_id: ID of the Digital Twin
            instance_name: Name for the service instance
            parameters: Service parameters
            execution_config: Execution configuration
            
        Returns:
            Created Service instance
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Get service definition
            definition = await self.registry.get_service_definition(definition_id)
            
            # Create service configuration
            config = ServiceConfiguration(
                service_definition_id=definition_id,
                instance_name=instance_name,
                digital_twin_id=digital_twin_id,
                parameters=parameters or {},
                execution_config=execution_config or {},
                resource_limits={},
                priority=ServicePriority.NORMAL
            )
            
            # Create service
            service = await self.factory.create_service_instance(definition, config)
            
            # Register service
            await self.registry.register_service(service)
            
            logger.info(f"Created Service {service.id} from definition {definition_id}")
            return service
            
        except Exception as e:
            logger.error(f"Failed to create service from definition {definition_id}: {e}")
            raise EntityCreationError(f"Service creation failed: {e}")
    
    async def execute_service(
        self,
        service_id: UUID,
        input_data: Dict[str, Any],
        execution_parameters: Optional[Dict[str, Any]] = None,
        priority: ServicePriority = ServicePriority.NORMAL,
        async_execution: bool = False
    ) -> Union[ServiceResponse, UUID]:
        """
        Execute a service.
        
        Args:
            service_id: ID of the service to execute
            input_data: Input data for execution
            execution_parameters: Optional execution parameters
            priority: Execution priority
            async_execution: Whether to execute asynchronously
            
        Returns:
            ServiceResponse for sync execution, execution_id for async
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Get service
            service = await self.registry.get_service(service_id)
            
            # Create service request
            request = ServiceRequest(
                request_id=uuid4(),
                requester_id=uuid4(),  # Should be actual requester ID
                service_instance_id=service_id,
                input_data=input_data,
                execution_parameters=execution_parameters,
                priority=priority
            )
            
            # Execute service
            start_time = datetime.now(timezone.utc)
            
            if async_execution:
                execution_id = await service.execute_async(request)
                return execution_id
            else:
                response = await service.execute(request)
                
                # Record execution metrics
                execution_time = (datetime.now(timezone.utc) - start_time).total_seconds()
                await self.registry.record_service_execution(
                    service_id, execution_time, response.success, priority
                )
                
                return response
            
        except Exception as e:
            logger.error(f"Failed to execute service {service_id}: {e}")
            raise ServiceError(f"Service execution failed: {e}")
    
    async def create_service_workflow(
        self,
        workflow_name: str,
        service_chain: List[Dict[str, Any]],
        digital_twin_id: UUID,
        workflow_config: Optional[Dict[str, Any]] = None
    ) -> UUID:
        """
        Create a service workflow.
        
        Args:
            workflow_name: Name of the workflow
            service_chain: Chain of services to execute
            digital_twin_id: Digital Twin ID for context
            workflow_config: Workflow configuration
            
        Returns:
            Workflow ID
        """
        if not self._initialized:
            await self.initialize()
        
        workflow_id = uuid4()
        
        workflow = {
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "digital_twin_id": digital_twin_id,
            "service_chain": service_chain,
            "workflow_config": workflow_config or {},
            "created_at": datetime.now(timezone.utc),
            "status": "created",
            "execution_history": []
        }
        
        self.active_workflows[workflow_id] = workflow
        
        logger.info(f"Created workflow {workflow_name} with ID {workflow_id}")
        return workflow_id
    
    async def execute_workflow(
        self,
        workflow_id: UUID,
        input_data: Dict[str, Any],
        execution_config: Optional[Dict[str, Any]] = None
    ) -> UUID:
        """
        Execute a workflow.
        
        Args:
            workflow_id: ID of the workflow to execute
            input_data: Input data for the workflow
            execution_config: Optional execution configuration
            
        Returns:
            Execution ID
        """
        if workflow_id not in self.active_workflows:
            raise ServiceError(f"Workflow {workflow_id} not found")
        
        workflow = self.active_workflows[workflow_id]
        execution_id = uuid4()
        
        async def execute_workflow_async():
            try:
                workflow["status"] = "running"
                workflow["current_execution_id"] = execution_id
                
                current_data = input_data
                results = []
                
                # Execute service chain
                for step_idx, step in enumerate(workflow["service_chain"]):
                    step_name = step.get("step_name", f"step_{step_idx}")
                    service_id = UUID(step["service_id"])
                    step_config = step.get("config", {})
                    
                    logger.info(f"Executing workflow step {step_name} with service {service_id}")
                    
                    # Execute service
                    response = await self.execute_service(
                        service_id=service_id,
                        input_data=current_data,
                        execution_parameters=step_config
                    )
                    
                    # Store result
                    step_result = {
                        "step_name": step_name,
                        "service_id": str(service_id),
                        "response": response.to_dict(),
                        "executed_at": datetime.now(timezone.utc).isoformat()
                    }
                    results.append(step_result)
                    
                    # Prepare data for next step
                    if response.success:
                        current_data = response.output_data
                    else:
                        # Handle step failure
                        workflow["status"] = "failed"
                        workflow["error"] = f"Step {step_name} failed: {response.error_message}"
                        workflow["execution_history"].append({
                            "execution_id": str(execution_id),
                            "status": "failed",
                            "results": results,
                            "error": workflow["error"],
                            "completed_at": datetime.now(timezone.utc).isoformat()
                        })
                        return
                
                # Workflow completed successfully
                workflow["status"] = "completed"
                workflow["execution_history"].append({
                    "execution_id": str(execution_id),
                    "status": "completed",
                    "results": results,
                    "completed_at": datetime.now(timezone.utc).isoformat()
                })
                
                logger.info(f"Workflow {workflow_id} completed successfully")
                
            except Exception as e:
                workflow["status"] = "failed"
                workflow["error"] = str(e)
                workflow["execution_history"].append({
                    "execution_id": str(execution_id),
                    "status": "failed",
                    "error": str(e),
                    "completed_at": datetime.now(timezone.utc).isoformat()
                })
                logger.error(f"Workflow {workflow_id} failed: {e}")
        
        # Start async execution
        asyncio.create_task(execute_workflow_async())
        
        return execution_id
    
    async def get_workflow_status(self, workflow_id: UUID) -> Dict[str, Any]:
        """Get workflow status."""
        if workflow_id not in self.active_workflows:
            return {"error": "Workflow not found"}
        
        workflow = self.active_workflows[workflow_id]
        return {
            "workflow_id": str(workflow_id),
            "workflow_name": workflow["workflow_name"],
            "status": workflow["status"],
            "created_at": workflow["created_at"].isoformat(),
            "service_chain_length": len(workflow["service_chain"]),
            "execution_count": len(workflow["execution_history"]),
            "current_execution_id": workflow.get("current_execution_id"),
            "error": workflow.get("error")
        }
    
    async def cancel_workflow(self, workflow_id: UUID) -> bool:
        """Cancel a workflow."""
        if workflow_id not in self.active_workflows:
            return False
        
        workflow = self.active_workflows[workflow_id]
        workflow["status"] = "cancelled"
        
        # Remove from active workflows
        del self.active_workflows[workflow_id]
        
        logger.info(f"Cancelled workflow {workflow_id}")
        return True
    
    async def discover_services(
        self,
        criteria: Dict[str, Any],
        include_performance: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Discover Services based on criteria.
        
        Args:
            criteria: Discovery criteria
            include_performance: Whether to include performance metrics
            
        Returns:
            List of service information
        """
        if not self._initialized:
            await self.initialize()
        
        services = await self.registry.discover_services(criteria)
        
        results = []
        for service in services:
            result = {
                "service": service.to_dict()
            }
            
            if include_performance:
                result["performance"] = await self.registry.get_service_performance(service.id)
            
            results.append(result)
        
        return results
    
    async def get_available_service_definitions(
        self,
        service_type: Optional[ServiceType] = None
    ) -> List[Dict[str, Any]]:
        """Get available service definitions."""
        if not self._initialized:
            await self.initialize()
        
        definitions = await self.registry.list_service_definitions(service_type)
        return [definition.to_dict() for definition in definitions]
    
    async def get_service_templates(self) -> List[Dict[str, Any]]:
        """Get available service templates."""
        if not self.templates_integration:
            return []
        
        ontology_manager = get_ontology_manager()
        template_ids = ontology_manager.list_templates(TemplateType.SERVICE)
        templates = []
        
        for template_id in template_ids:
            template = ontology_manager.get_template(template_id)
            if template:
                templates.append(template.to_dict())
        
        return templates
    
    
    async def get_layer_statistics(self) -> Dict[str, Any]:
        """Enhanced statistics with storage health."""
        if not self._initialized:
            await self.initialize()
            
        registry_stats = await self.registry.get_service_statistics()
        factory_stats = {
            'supported_service_types': len(self.factory.get_available_service_types()),
            'available_definitions': len(self.factory._service_definitions)
        }
        
        workflow_stats = {
            'active_workflows': len(self.active_workflows),
            'workflows_by_status': {},
            'total_service_dependencies': len(self.service_dependencies)
        }
        
        for workflow in self.active_workflows.values():
            status = workflow['status']
            workflow_stats['workflows_by_status'][status] = workflow_stats['workflows_by_status'].get(status, 0) + 1
        
        # NUOVO: Storage health
        storage_health = await self._get_storage_health()
        
        return {
            'service_layer': {
                'initialized': self._initialized,
                'running': self._running,
                'templates_integration': self.templates_integration,
                'components': {
                    'factory': bool(self.factory),
                    'registry': bool(self.registry)
                }
            },
            'registry': registry_stats,
            'factory': factory_stats,
            'workflows': workflow_stats,
            'storage': storage_health  # NUOVO
        }
    
    # Private helper methods
    async def _integrate_with_templates(self) -> None:
        """Integrate with the ontology system for template support."""
        try:
            ontology_manager = get_ontology_manager()
            logger.info("Service Layer integrated with template system")
        except Exception as e:
            logger.warning(f"Failed to integrate with template system: {e}")
            self.templates_integration = False
    
    async def _get_storage_health(self) -> Dict[str, Any]:
        """Get service storage health."""
        health = {
            'primary_storage': 'unknown',
            'cache_storage': 'unknown',
            'registry_connected': False,
            'cache_connected': False
        }
        
        try:
            # Registry storage
            if self.registry and hasattr(self.registry, 'storage_adapter'):
                registry_health = await self.registry.storage_adapter.health_check()
                health['registry_connected'] = registry_health
                health['primary_storage'] = 'mongodb' if registry_health else 'failed'
            
            # Cache
            if self._registry_cache:
                cache_health = await self._registry_cache.cache.health_check()
                health['cache_connected'] = cache_health
                health['cache_storage'] = 'redis' if cache_health else 'failed'
            
        except Exception as e:
            logger.warning(f'Service storage health check error: {e}')
            health['error'] = str(e)
        
        return health

    async def _load_default_service_definitions(self) -> None:
        """Load default service definitions."""
        if not self.factory or not self.registry:
            return
        
        # Get definitions from factory and register in registry
        for definition in self.factory._service_definitions.values():
            await self.registry.register_service_definition(definition)
        
        logger.info(f"Loaded {len(self.factory._service_definitions)} service definitions")


# Global orchestrator instance
_service_orchestrator: Optional[ServiceLayerOrchestrator] = None


def get_service_orchestrator() -> ServiceLayerOrchestrator:
    """Get the global service layer orchestrator."""
    global _service_orchestrator
    if _service_orchestrator is None:
        _service_orchestrator = ServiceLayerOrchestrator()
    return _service_orchestrator


async def initialize_service_layer() -> ServiceLayerOrchestrator:
    """Initialize the complete service layer."""
    global _service_orchestrator
    _service_orchestrator = ServiceLayerOrchestrator()
    await _service_orchestrator.initialize()
    return _service_orchestrator


# Convenience functions for common operations
async def create_analytics_service(
    digital_twin_id: UUID,
    data_sources: List[str],
    analytics_type: str = "basic_statistics"
) -> IService:
    """Convenience function to create an analytics service."""
    orchestrator = get_service_orchestrator()
    
    parameters = {
        "data_sources": data_sources,
        "analytics_type": analytics_type
    }
    
    return await orchestrator.create_service_from_definition(
        definition_id="analytics_basic",
        digital_twin_id=digital_twin_id,
        instance_name=f"Analytics Service - {analytics_type}",
        parameters=parameters
    )


async def create_prediction_service(
    digital_twin_id: UUID,
    model_type: str = "linear",
    prediction_horizon: int = 300
) -> IService:
    """Convenience function to create a prediction service."""
    orchestrator = get_service_orchestrator()
    
    parameters = {
        "model_type": model_type,
        "prediction_horizon": prediction_horizon
    }
    
    return await orchestrator.create_service_from_definition(
        definition_id="prediction_linear",
        digital_twin_id=digital_twin_id,
        instance_name=f"Prediction Service - {model_type}",
        parameters=parameters
    )


async def create_alerting_service(
    digital_twin_id: UUID,
    notification_channels: List[str] = None
) -> IService:
    """Convenience function to create an alerting service."""
    orchestrator = get_service_orchestrator()
    
    parameters = {
        "notification_channels": notification_channels or ["email"]
    }
    
    return await orchestrator.create_service_from_definition(
        definition_id="alerting_threshold",
        digital_twin_id=digital_twin_id,
        instance_name="Alerting Service",
        parameters=parameters
    )

