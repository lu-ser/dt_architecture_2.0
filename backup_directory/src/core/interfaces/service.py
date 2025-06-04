from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Union, Callable, AsyncGenerator
from uuid import UUID
from enum import Enum
from .base import IEntity, IFactory, ILifecycleManager, BaseMetadata

class ServiceType(Enum):
    ANALYTICS = 'analytics'
    PREDICTION = 'prediction'
    OPTIMIZATION = 'optimization'
    ALERTING = 'alerting'
    MONITORING = 'monitoring'
    ANOMALY_DETECTION = 'anomaly_detection'
    SIMULATION = 'simulation'
    TRANSFORMATION = 'transformation'
    AGGREGATION = 'aggregation'
    VISUALIZATION = 'visualization'
    REPORTING = 'reporting'
    CONTROL = 'control'
    INTEGRATION = 'integration'
    VALIDATION = 'validation'
    CUSTOM = 'custom'

class ServiceExecutionMode(Enum):
    SYNCHRONOUS = 'synchronous'
    ASYNCHRONOUS = 'asynchronous'
    STREAMING = 'streaming'
    BATCH = 'batch'
    SCHEDULED = 'scheduled'
    EVENT_DRIVEN = 'event_driven'
    REACTIVE = 'reactive'

class ServiceState(Enum):
    INITIALIZING = 'initializing'
    READY = 'ready'
    RUNNING = 'running'
    IDLE = 'idle'
    BUSY = 'busy'
    PAUSED = 'paused'
    DRAINING = 'draining'
    ERROR = 'error'
    TERMINATED = 'terminated'

class ServicePriority(Enum):
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4
    BACKGROUND = 5

class ServiceDefinition:

    def __init__(self, definition_id: str, name: str, service_type: ServiceType, version: str, description: str, execution_mode: ServiceExecutionMode, resource_requirements: Dict[str, Any], input_schema: Dict[str, Any], output_schema: Dict[str, Any], configuration_schema: Dict[str, Any], dependencies: List[str], capabilities: Set[str], metadata: Optional[Dict[str, Any]]=None):
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
        return {'definition_id': self.definition_id, 'name': self.name, 'service_type': self.service_type.value, 'version': self.version, 'description': self.description, 'execution_mode': self.execution_mode.value, 'resource_requirements': self.resource_requirements, 'input_schema': self.input_schema, 'output_schema': self.output_schema, 'configuration_schema': self.configuration_schema, 'dependencies': self.dependencies, 'capabilities': list(self.capabilities), 'metadata': self.metadata}

class ServiceConfiguration:

    def __init__(self, service_definition_id: str, instance_name: str, digital_twin_id: UUID, parameters: Dict[str, Any], execution_config: Dict[str, Any], resource_limits: Dict[str, Any], priority: ServicePriority=ServicePriority.NORMAL, auto_scaling: Optional[Dict[str, Any]]=None, custom_config: Optional[Dict[str, Any]]=None):
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
        return {'service_definition_id': self.service_definition_id, 'instance_name': self.instance_name, 'digital_twin_id': str(self.digital_twin_id), 'parameters': self.parameters, 'execution_config': self.execution_config, 'resource_limits': self.resource_limits, 'priority': self.priority.value, 'auto_scaling': self.auto_scaling, 'custom_config': self.custom_config}

class ServiceRequest:

    def __init__(self, request_id: UUID, requester_id: UUID, service_instance_id: UUID, input_data: Dict[str, Any], execution_parameters: Optional[Dict[str, Any]]=None, priority: ServicePriority=ServicePriority.NORMAL, timeout: Optional[int]=None, callback_url: Optional[str]=None):
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
        return {'request_id': str(self.request_id), 'requester_id': str(self.requester_id), 'service_instance_id': str(self.service_instance_id), 'input_data': self.input_data, 'execution_parameters': self.execution_parameters, 'priority': self.priority.value, 'timeout': self.timeout, 'callback_url': self.callback_url, 'created_at': self.created_at.isoformat()}

class ServiceResponse:

    def __init__(self, request_id: UUID, service_instance_id: UUID, output_data: Dict[str, Any], execution_time: float, success: bool, error_message: Optional[str]=None, execution_metadata: Optional[Dict[str, Any]]=None):
        self.request_id = request_id
        self.service_instance_id = service_instance_id
        self.output_data = output_data
        self.execution_time = execution_time
        self.success = success
        self.error_message = error_message
        self.execution_metadata = execution_metadata or {}
        self.completed_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {'request_id': str(self.request_id), 'service_instance_id': str(self.service_instance_id), 'output_data': self.output_data, 'execution_time': self.execution_time, 'success': self.success, 'error_message': self.error_message, 'execution_metadata': self.execution_metadata, 'completed_at': self.completed_at.isoformat()}

class IService(IEntity):

    @property
    @abstractmethod
    def service_type(self) -> ServiceType:
        pass

    @property
    @abstractmethod
    def service_definition_id(self) -> str:
        pass

    @property
    @abstractmethod
    def digital_twin_id(self) -> UUID:
        pass

    @property
    @abstractmethod
    def instance_name(self) -> str:
        pass

    @property
    @abstractmethod
    def configuration(self) -> ServiceConfiguration:
        pass

    @property
    @abstractmethod
    def current_state(self) -> ServiceState:
        pass

    @property
    @abstractmethod
    def execution_mode(self) -> ServiceExecutionMode:
        pass

    @property
    @abstractmethod
    def capabilities(self) -> Set[str]:
        pass

    @abstractmethod
    async def execute(self, request: ServiceRequest) -> ServiceResponse:
        pass

    @abstractmethod
    async def execute_async(self, request: ServiceRequest) -> UUID:
        pass

    @abstractmethod
    async def get_execution_status(self, execution_id: UUID) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def cancel_execution(self, execution_id: UUID) -> bool:
        pass

    @abstractmethod
    async def pause(self) -> None:
        pass

    @abstractmethod
    async def resume(self) -> None:
        pass

    @abstractmethod
    async def drain(self) -> None:
        pass

    @abstractmethod
    async def update_configuration(self, new_config: ServiceConfiguration) -> None:
        pass

    @abstractmethod
    async def get_metrics(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        pass

class IStreamingService(IService):

    @abstractmethod
    async def start_stream(self, stream_config: Dict[str, Any]) -> str:
        pass

    @abstractmethod
    async def stop_stream(self, stream_id: str) -> None:
        pass

    @abstractmethod
    async def process_stream_data(self, stream_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_stream_results(self, stream_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        pass

class IServiceFactory(IFactory[IService]):

    @abstractmethod
    async def create_service_instance(self, service_definition: ServiceDefinition, config: ServiceConfiguration, metadata: Optional[BaseMetadata]=None) -> IService:
        pass

    @abstractmethod
    async def register_service_definition(self, definition: ServiceDefinition) -> None:
        pass

    @abstractmethod
    async def get_service_definition(self, definition_id: str) -> ServiceDefinition:
        pass

    @abstractmethod
    def get_available_service_types(self) -> List[ServiceType]:
        pass

    @abstractmethod
    def get_service_definitions(self, service_type: Optional[ServiceType]=None) -> List[ServiceDefinition]:
        pass

    @abstractmethod
    def validate_service_config(self, definition_id: str, config: ServiceConfiguration) -> bool:
        pass

class IServiceLifecycleManager(ILifecycleManager[IService]):

    @abstractmethod
    async def deploy_service(self, service: IService, deployment_target: str, deployment_config: Dict[str, Any]) -> str:
        pass

    @abstractmethod
    async def scale_service(self, service_id: UUID, target_instances: int, scaling_strategy: str='gradual') -> None:
        pass

    @abstractmethod
    async def update_service(self, service_id: UUID, new_definition: ServiceDefinition, update_strategy: str='rolling') -> None:
        pass

    @abstractmethod
    async def rollback_service(self, service_id: UUID, target_version: Optional[str]=None) -> None:
        pass

    @abstractmethod
    async def get_service_instances(self, digital_twin_id: Optional[UUID]=None, service_type: Optional[ServiceType]=None) -> List[IService]:
        pass

class IServiceOrchestrator(ABC):

    @abstractmethod
    async def create_workflow(self, workflow_name: str, service_chain: List[Dict[str, Any]], workflow_config: Dict[str, Any]) -> UUID:
        pass

    @abstractmethod
    async def execute_workflow(self, workflow_id: UUID, input_data: Dict[str, Any], execution_config: Optional[Dict[str, Any]]=None) -> UUID:
        pass

    @abstractmethod
    async def monitor_workflow(self, execution_id: UUID) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def compose_services(self, service_ids: List[UUID], composition_rules: Dict[str, Any]) -> UUID:
        pass
ServiceEventHandler = Callable[[UUID, str, Dict[str, Any]], None]

class IServiceEventBus(ABC):

    @abstractmethod
    async def publish_service_event(self, event_type: str, service_id: UUID, event_data: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    def subscribe_to_service_events(self, event_types: List[str], handler: ServiceEventHandler, service_filter: Optional[List[UUID]]=None) -> str:
        pass

    @abstractmethod
    async def unsubscribe_from_service_events(self, subscription_id: str) -> None:
        pass