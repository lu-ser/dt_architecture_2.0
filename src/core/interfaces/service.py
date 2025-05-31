"""
Service interfaces for the Digital Twin Platform.

This module defines interfaces for services that provide analytics, prediction,
optimization, and other capabilities to Digital Twins. Services follow a
template-instance pattern and can be deployed as containers.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Union, Callable, AsyncGenerator
from uuid import UUID
from enum import Enum

from .base import IEntity, IFactory, ILifecycleManager, BaseMetadata


class ServiceType(Enum):
    """Types of services available in the platform."""
    ANALYTICS = "analytics"                 # Data analytics service
    PREDICTION = "prediction"               # Predictive analytics
    OPTIMIZATION = "optimization"           # Optimization algorithms
    ALERTING = "alerting"                  # Alert and notification service
    MONITORING = "monitoring"              # System monitoring
    ANOMALY_DETECTION = "anomaly_detection" # Anomaly detection
    SIMULATION = "simulation"              # Simulation service
    TRANSFORMATION = "transformation"       # Data transformation
    AGGREGATION = "aggregation"            # Data aggregation
    VISUALIZATION = "visualization"         # Data visualization
    REPORTING = "reporting"                # Report generation
    CONTROL = "control"                    # Control system interface
    INTEGRATION = "integration"            # External system integration
    VALIDATION = "validation"              # Data validation
    CUSTOM = "custom"                      # Custom user-defined service


class ServiceExecutionMode(Enum):
    """Execution modes for services."""
    SYNCHRONOUS = "synchronous"            # Blocking execution
    ASYNCHRONOUS = "asynchronous"          # Non-blocking execution
    STREAMING = "streaming"                # Continuous data streaming
    BATCH = "batch"                        # Batch processing
    SCHEDULED = "scheduled"                # Scheduled execution
    EVENT_DRIVEN = "event_driven"          # Triggered by events
    REACTIVE = "reactive"                  # Reactive to data changes


class ServiceState(Enum):
    """Operational states for service instances."""
    INITIALIZING = "initializing"          # Service starting up
    READY = "ready"                        # Ready to accept requests
    RUNNING = "running"                    # Currently executing
    IDLE = "idle"                          # Waiting for work
    BUSY = "busy"                          # At capacity
    PAUSED = "paused"                      # Temporarily paused
    DRAINING = "draining"                  # Finishing current work
    ERROR = "error"                        # Error state
    TERMINATED = "terminated"              # Shut down


class ServicePriority(Enum):
    """Priority levels for service execution."""
    CRITICAL = 1    # Highest priority
    HIGH = 2        # High priority
    NORMAL = 3      # Normal priority
    LOW = 4         # Low priority
    BACKGROUND = 5  # Lowest priority


class ServiceDefinition:
    """Template definition for creating service instances."""
    
    def __init__(
        self,
        definition_id: str,
        name: str,
        service_type: ServiceType,
        version: str,
        description: str,
        execution_mode: ServiceExecutionMode,
        resource_requirements: Dict[str, Any],
        input_schema: Dict[str, Any],
        output_schema: Dict[str, Any],
        configuration_schema: Dict[str, Any],
        dependencies: List[str],
        capabilities: Set[str],
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.definition_id = definition_id
        self.name = name
        self.service_type = service_type
        self.version = version
        self.description = description
        self.execution_mode = execution_mode
        self.resource_requirements = resource_requirements
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.configuration_schema = configuration_schema
        self.dependencies = dependencies
        self.capabilities = capabilities
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert service definition to dictionary representation."""
        return {
            "definition_id": self.definition_id,
            "name": self.name,
            "service_type": self.service_type.value,
            "version": self.version,
            "description": self.description,
            "execution_mode": self.execution_mode.value,
            "resource_requirements": self.resource_requirements,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "configuration_schema": self.configuration_schema,
            "dependencies": self.dependencies,
            "capabilities": list(self.capabilities),
            "metadata": self.metadata
        }


class ServiceConfiguration:
    """Configuration for service instances."""
    
    def __init__(
        self,
        service_definition_id: str,
        instance_name: str,
        digital_twin_id: UUID,
        parameters: Dict[str, Any],
        execution_config: Dict[str, Any],
        resource_limits: Dict[str, Any],
        priority: ServicePriority = ServicePriority.NORMAL,
        auto_scaling: Optional[Dict[str, Any]] = None,
        custom_config: Optional[Dict[str, Any]] = None
    ):
        self.service_definition_id = service_definition_id
        self.instance_name = instance_name
        self.digital_twin_id = digital_twin_id
        self.parameters = parameters
        self.execution_config = execution_config
        self.resource_limits = resource_limits
        self.priority = priority
        self.auto_scaling = auto_scaling or {}
        self.custom_config = custom_config or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert service configuration to dictionary representation."""
        return {
            "service_definition_id": self.service_definition_id,
            "instance_name": self.instance_name,
            "digital_twin_id": str(self.digital_twin_id),
            "parameters": self.parameters,
            "execution_config": self.execution_config,
            "resource_limits": self.resource_limits,
            "priority": self.priority.value,
            "auto_scaling": self.auto_scaling,
            "custom_config": self.custom_config
        }


class ServiceRequest:
    """Represents a request to execute a service."""
    
    def __init__(
        self,
        request_id: UUID,
        requester_id: UUID,
        service_instance_id: UUID,
        input_data: Dict[str, Any],
        execution_parameters: Optional[Dict[str, Any]] = None,
        priority: ServicePriority = ServicePriority.NORMAL,
        timeout: Optional[int] = None,
        callback_url: Optional[str] = None
    ):
        self.request_id = request_id
        self.requester_id = requester_id
        self.service_instance_id = service_instance_id
        self.input_data = input_data
        self.execution_parameters = execution_parameters or {}
        self.priority = priority
        self.timeout = timeout
        self.callback_url = callback_url
        self.created_at = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert service request to dictionary representation."""
        return {
            "request_id": str(self.request_id),
            "requester_id": str(self.requester_id),
            "service_instance_id": str(self.service_instance_id),
            "input_data": self.input_data,
            "execution_parameters": self.execution_parameters,
            "priority": self.priority.value,
            "timeout": self.timeout,
            "callback_url": self.callback_url,
            "created_at": self.created_at.isoformat()
        }


class ServiceResponse:
    """Represents a response from service execution."""
    
    def __init__(
        self,
        request_id: UUID,
        service_instance_id: UUID,
        output_data: Dict[str, Any],
        execution_time: float,
        success: bool,
        error_message: Optional[str] = None,
        execution_metadata: Optional[Dict[str, Any]] = None
    ):
        self.request_id = request_id
        self.service_instance_id = service_instance_id
        self.output_data = output_data
        self.execution_time = execution_time
        self.success = success
        self.error_message = error_message
        self.execution_metadata = execution_metadata or {}
        self.completed_at = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert service response to dictionary representation."""
        return {
            "request_id": str(self.request_id),
            "service_instance_id": str(self.service_instance_id),
            "output_data": self.output_data,
            "execution_time": self.execution_time,
            "success": self.success,
            "error_message": self.error_message,
            "execution_metadata": self.execution_metadata,
            "completed_at": self.completed_at.isoformat()
        }


class IService(IEntity):
    """
    Interface for service instances.
    
    Services provide specific capabilities to Digital Twins such as analytics,
    prediction, optimization, etc. Each service instance is created from a
    service definition and can be containerized for deployment.
    """
    
    @property
    @abstractmethod
    def service_type(self) -> ServiceType:
        """Get the type of this service."""
        pass
    
    @property
    @abstractmethod
    def service_definition_id(self) -> str:
        """Get the ID of the service definition this instance was created from."""
        pass
    
    @property
    @abstractmethod
    def digital_twin_id(self) -> UUID:
        """Get the ID of the Digital Twin this service is associated with."""
        pass
    
    @property
    @abstractmethod
    def instance_name(self) -> str:
        """Get the name of this service instance."""
        pass
    
    @property
    @abstractmethod
    def configuration(self) -> ServiceConfiguration:
        """Get the current configuration of the service."""
        pass
    
    @property
    @abstractmethod
    def current_state(self) -> ServiceState:
        """Get the current state of the service instance."""
        pass
    
    @property
    @abstractmethod
    def execution_mode(self) -> ServiceExecutionMode:
        """Get the execution mode of this service."""
        pass
    
    @property
    @abstractmethod
    def capabilities(self) -> Set[str]:
        """Get the capabilities provided by this service."""
        pass
    
    @abstractmethod
    async def execute(self, request: ServiceRequest) -> ServiceResponse:
        """
        Execute the service with the provided request.
        
        Args:
            request: Service execution request
            
        Returns:
            Service execution response
        """
        pass
    
    @abstractmethod
    async def execute_async(self, request: ServiceRequest) -> UUID:
        """
        Execute the service asynchronously.
        
        Args:
            request: Service execution request
            
        Returns:
            Execution ID for tracking
        """
        pass
    
    @abstractmethod
    async def get_execution_status(self, execution_id: UUID) -> Dict[str, Any]:
        """
        Get the status of an asynchronous execution.
        
        Args:
            execution_id: ID of the execution to check
            
        Returns:
            Execution status information
        """
        pass
    
    @abstractmethod
    async def cancel_execution(self, execution_id: UUID) -> bool:
        """
        Cancel an ongoing execution.
        
        Args:
            execution_id: ID of the execution to cancel
            
        Returns:
            True if cancellation was successful
        """
        pass
    
    @abstractmethod
    async def pause(self) -> None:
        """Pause the service instance."""
        pass
    
    @abstractmethod
    async def resume(self) -> None:
        """Resume the service instance."""
        pass
    
    @abstractmethod
    async def drain(self) -> None:
        """Drain the service instance (finish current work, accept no new work)."""
        pass
    
    @abstractmethod
    async def update_configuration(self, new_config: ServiceConfiguration) -> None:
        """
        Update the service configuration.
        
        Args:
            new_config: New configuration to apply
        """
        pass
    
    @abstractmethod
    async def get_metrics(self) -> Dict[str, Any]:
        """
        Get performance and operational metrics for the service.
        
        Returns:
            Service metrics dictionary
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check on the service.
        
        Returns:
            Health status information
        """
        pass


class IStreamingService(IService):
    """
    Interface for streaming services that process continuous data flows.
    
    Extends the base service interface with streaming-specific methods
    for handling continuous data processing.
    """
    
    @abstractmethod
    async def start_stream(
        self,
        stream_config: Dict[str, Any]
    ) -> str:
        """
        Start a streaming processing session.
        
        Args:
            stream_config: Configuration for the stream
            
        Returns:
            Stream ID for tracking
        """
        pass
    
    @abstractmethod
    async def stop_stream(self, stream_id: str) -> None:
        """
        Stop a streaming processing session.
        
        Args:
            stream_id: ID of the stream to stop
        """
        pass
    
    @abstractmethod
    async def process_stream_data(
        self,
        stream_id: str,
        data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Process streaming data.
        
        Args:
            stream_id: ID of the stream
            data: Data to process
            
        Returns:
            Processed data if available immediately
        """
        pass
    
    @abstractmethod
    async def get_stream_results(
        self,
        stream_id: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Get streaming results as they become available.
        
        Args:
            stream_id: ID of the stream
            
        Yields:
            Streaming results
        """
        pass


class IServiceFactory(IFactory[IService]):
    """
    Factory interface for creating service instances.
    
    Handles the creation and configuration of service instances
    based on service definitions and configurations.
    """
    
    @abstractmethod
    async def create_service_instance(
        self,
        service_definition: ServiceDefinition,
        config: ServiceConfiguration,
        metadata: Optional[BaseMetadata] = None
    ) -> IService:
        """
        Create a new service instance from a definition.
        
        Args:
            service_definition: Service definition template
            config: Instance configuration
            metadata: Optional metadata for the instance
            
        Returns:
            Created service instance
        """
        pass
    
    @abstractmethod
    async def register_service_definition(
        self,
        definition: ServiceDefinition
    ) -> None:
        """
        Register a new service definition.
        
        Args:
            definition: Service definition to register
        """
        pass
    
    @abstractmethod
    async def get_service_definition(
        self,
        definition_id: str
    ) -> ServiceDefinition:
        """
        Get a service definition by ID.
        
        Args:
            definition_id: ID of the definition to retrieve
            
        Returns:
            Service definition
        """
        pass
    
    @abstractmethod
    def get_available_service_types(self) -> List[ServiceType]:
        """Get the list of available service types."""
        pass
    
    @abstractmethod
    def get_service_definitions(
        self,
        service_type: Optional[ServiceType] = None
    ) -> List[ServiceDefinition]:
        """
        Get available service definitions.
        
        Args:
            service_type: Optional filter by service type
            
        Returns:
            List of service definitions
        """
        pass
    
    @abstractmethod
    def validate_service_config(
        self,
        definition_id: str,
        config: ServiceConfiguration
    ) -> bool:
        """
        Validate a service configuration against its definition.
        
        Args:
            definition_id: ID of the service definition
            config: Configuration to validate
            
        Returns:
            True if configuration is valid
        """
        pass


class IServiceLifecycleManager(ILifecycleManager[IService]):
    """
    Lifecycle manager interface for services.
    
    Manages the complete lifecycle of service instances including
    creation, deployment, scaling, and termination.
    """
    
    @abstractmethod
    async def deploy_service(
        self,
        service: IService,
        deployment_target: str,
        deployment_config: Dict[str, Any]
    ) -> str:
        """
        Deploy a service instance to a specific target.
        
        Args:
            service: Service instance to deploy
            deployment_target: Target for deployment
            deployment_config: Deployment configuration
            
        Returns:
            Deployment ID or reference
        """
        pass
    
    @abstractmethod
    async def scale_service(
        self,
        service_id: UUID,
        target_instances: int,
        scaling_strategy: str = "gradual"
    ) -> None:
        """
        Scale a service horizontally.
        
        Args:
            service_id: ID of the service to scale
            target_instances: Target number of instances
            scaling_strategy: Strategy for scaling
        """
        pass
    
    @abstractmethod
    async def update_service(
        self,
        service_id: UUID,
        new_definition: ServiceDefinition,
        update_strategy: str = "rolling"
    ) -> None:
        """
        Update a service to a new definition.
        
        Args:
            service_id: ID of the service to update
            new_definition: New service definition
            update_strategy: Strategy for update deployment
        """
        pass
    
    @abstractmethod
    async def rollback_service(
        self,
        service_id: UUID,
        target_version: Optional[str] = None
    ) -> None:
        """
        Rollback a service to a previous version.
        
        Args:
            service_id: ID of the service to rollback
            target_version: Target version (None for previous)
        """
        pass
    
    @abstractmethod
    async def get_service_instances(
        self,
        digital_twin_id: Optional[UUID] = None,
        service_type: Optional[ServiceType] = None
    ) -> List[IService]:
        """
        Get service instances with optional filtering.
        
        Args:
            digital_twin_id: Filter by Digital Twin ID
            service_type: Filter by service type
            
        Returns:
            List of service instances
        """
        pass


class IServiceOrchestrator(ABC):
    """
    Interface for service orchestration and workflow management.
    
    Handles coordination between multiple services and manages
    complex workflows and service compositions.
    """
    
    @abstractmethod
    async def create_workflow(
        self,
        workflow_name: str,
        service_chain: List[Dict[str, Any]],
        workflow_config: Dict[str, Any]
    ) -> UUID:
        """
        Create a service workflow.
        
        Args:
            workflow_name: Name of the workflow
            service_chain: Chain of services to execute
            workflow_config: Workflow configuration
            
        Returns:
            Workflow ID
        """
        pass
    
    @abstractmethod
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
        pass
    
    @abstractmethod
    async def monitor_workflow(
        self,
        execution_id: UUID
    ) -> Dict[str, Any]:
        """
        Monitor workflow execution progress.
        
        Args:
            execution_id: ID of the execution to monitor
            
        Returns:
            Workflow execution status
        """
        pass
    
    @abstractmethod
    async def compose_services(
        self,
        service_ids: List[UUID],
        composition_rules: Dict[str, Any]
    ) -> UUID:
        """
        Compose multiple services into a composite service.
        
        Args:
            service_ids: IDs of services to compose
            composition_rules: Rules for composition
            
        Returns:
            Composite service ID
        """
        pass


# Type aliases for service event handlers
ServiceEventHandler = Callable[[UUID, str, Dict[str, Any]], None]


class IServiceEventBus(ABC):
    """
    Event bus interface for service events.
    
    Handles event-driven communication between services and other
    platform components.
    """
    
    @abstractmethod
    async def publish_service_event(
        self,
        event_type: str,
        service_id: UUID,
        event_data: Dict[str, Any]
    ) -> None:
        """
        Publish a service-related event.
        
        Args:
            event_type: Type of the event
            service_id: ID of the service that generated the event
            event_data: Event payload data
        """
        pass
    
    @abstractmethod
    def subscribe_to_service_events(
        self,
        event_types: List[str],
        handler: ServiceEventHandler,
        service_filter: Optional[List[UUID]] = None
    ) -> str:
        """
        Subscribe to service events.
        
        Args:
            event_types: List of event types to subscribe to
            handler: Event handler function
            service_filter: Optional list of service IDs to filter events
            
        Returns:
            Subscription ID
        """
        pass
    
    @abstractmethod
    async def unsubscribe_from_service_events(self, subscription_id: str) -> None:
        """
        Unsubscribe from service events.
        
        Args:
            subscription_id: ID of the subscription to cancel
        """
        pass