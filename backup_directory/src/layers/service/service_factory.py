import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type, Set
from uuid import UUID, uuid4
from src.core.interfaces.base import BaseMetadata, EntityStatus
from src.core.interfaces.service import IService, IServiceFactory, ServiceType, ServiceDefinition, ServiceConfiguration, ServiceExecutionMode, ServiceState, ServicePriority, ServiceRequest, ServiceResponse
from src.utils.exceptions import FactoryError, FactoryConfigurationError, EntityCreationError, ServiceConfigurationError
from src.utils.config import get_config
logger = logging.getLogger(__name__)

class StandardService(IService):

    def __init__(self, service_id: UUID, service_definition: ServiceDefinition, configuration: ServiceConfiguration, metadata: BaseMetadata):
        self._id = service_id
        self._service_definition = service_definition
        self._configuration = configuration
        self._metadata = metadata
        self._current_state = ServiceState.INITIALIZING
        self._status = EntityStatus.CREATED
        self._executions: Dict[UUID, Dict[str, Any]] = {}
        self._execution_count = 0
        self._total_execution_time = 0.0
        self._last_execution: Optional[datetime] = None
        self._success_count = 0
        self._error_count = 0
        self._average_response_time = 0.0
        self._current_memory_usage = 0.0
        self._current_cpu_usage = 0.0

    @property
    def id(self) -> UUID:
        return self._id

    @property
    def metadata(self) -> BaseMetadata:
        return self._metadata

    @property
    def status(self) -> EntityStatus:
        return self._status

    @property
    def service_type(self) -> ServiceType:
        return self._service_definition.service_type

    @property
    def service_definition_id(self) -> str:
        return self._service_definition.definition_id

    @property
    def digital_twin_id(self) -> UUID:
        return self._configuration.digital_twin_id

    @property
    def instance_name(self) -> str:
        return self._configuration.instance_name

    @property
    def configuration(self) -> ServiceConfiguration:
        return self._configuration

    @property
    def current_state(self) -> ServiceState:
        return self._current_state

    @property
    def execution_mode(self) -> ServiceExecutionMode:
        return self._service_definition.execution_mode

    @property
    def capabilities(self) -> Set[str]:
        return self._service_definition.capabilities

    async def initialize(self) -> None:
        self._status = EntityStatus.INITIALIZING
        self._current_state = ServiceState.INITIALIZING
        await self._validate_configuration()
        await self._initialize_resources()
        self._status = EntityStatus.ACTIVE
        self._current_state = ServiceState.READY
        logger.info(f'Service {self._id} ({self.service_type.value}) initialized')

    async def start(self) -> None:
        if self._current_state not in [ServiceState.READY, ServiceState.PAUSED]:
            raise ServiceConfigurationError(f'Cannot start service in state {self._current_state}')
        self._status = EntityStatus.ACTIVE
        self._current_state = ServiceState.READY
        logger.info(f'Service {self._id} started')

    async def stop(self) -> None:
        self._current_state = ServiceState.DRAINING
        while any((exec_info.get('status') == 'running' for exec_info in self._executions.values())):
            await asyncio.sleep(0.1)
        self._status = EntityStatus.INACTIVE
        self._current_state = ServiceState.IDLE
        logger.info(f'Service {self._id} stopped')

    async def terminate(self) -> None:
        await self.stop()
        for execution_id, exec_info in self._executions.items():
            if exec_info.get('status') == 'running':
                await self.cancel_execution(execution_id)
        await self._cleanup_resources()
        self._status = EntityStatus.TERMINATED
        self._current_state = ServiceState.TERMINATED
        logger.info(f'Service {self._id} terminated')

    async def execute(self, request: ServiceRequest) -> ServiceResponse:
        if self._current_state not in [ServiceState.READY, ServiceState.IDLE]:
            raise ServiceConfigurationError(f'Service not ready for execution: {self._current_state}')
        execution_id = request.request_id
        start_time = datetime.now(timezone.utc)
        try:
            self._current_state = ServiceState.RUNNING
            self._executions[execution_id] = {'status': 'running', 'start_time': start_time, 'request': request}
            await self._validate_input_data(request.input_data)
            output_data = await self._execute_service_logic(request)
            await self._validate_output_data(output_data)
            end_time = datetime.now(timezone.utc)
            execution_time = (end_time - start_time).total_seconds()
            self._execution_count += 1
            self._success_count += 1
            self._total_execution_time += execution_time
            self._average_response_time = self._total_execution_time / self._execution_count
            self._last_execution = end_time
            self._executions[execution_id].update({'status': 'completed', 'end_time': end_time, 'execution_time': execution_time, 'success': True})
            self._current_state = ServiceState.READY
            response = ServiceResponse(request_id=request.request_id, service_instance_id=self._id, output_data=output_data, execution_time=execution_time, success=True, execution_metadata={'service_type': self.service_type.value, 'execution_mode': self.execution_mode.value, 'service_definition_id': self.service_definition_id})
            logger.info(f'Service {self._id} executed successfully in {execution_time:.3f}s')
            return response
        except Exception as e:
            end_time = datetime.now(timezone.utc)
            execution_time = (end_time - start_time).total_seconds()
            self._error_count += 1
            self._execution_count += 1
            self._total_execution_time += execution_time
            self._average_response_time = self._total_execution_time / self._execution_count
            self._executions[execution_id].update({'status': 'failed', 'end_time': end_time, 'execution_time': execution_time, 'success': False, 'error': str(e)})
            self._current_state = ServiceState.ERROR if self._error_count > 5 else ServiceState.READY
            response = ServiceResponse(request_id=request.request_id, service_instance_id=self._id, output_data={}, execution_time=execution_time, success=False, error_message=str(e))
            logger.error(f'Service {self._id} execution failed: {e}')
            return response

    async def execute_async(self, request: ServiceRequest) -> UUID:
        execution_id = uuid4()

        async def async_execution():
            modified_request = ServiceRequest(request_id=execution_id, requester_id=request.requester_id, service_instance_id=request.service_instance_id, input_data=request.input_data, execution_parameters=request.execution_parameters, priority=request.priority, timeout=request.timeout, callback_url=request.callback_url)
            response = await self.execute(modified_request)
            self._executions[execution_id]['result'] = response
            return response
        task = asyncio.create_task(async_execution())
        self._executions[execution_id] = {'status': 'running', 'start_time': datetime.now(timezone.utc), 'task': task, 'request': request}
        return execution_id

    async def get_execution_status(self, execution_id: UUID) -> Dict[str, Any]:
        if execution_id not in self._executions:
            return {'error': 'Execution not found'}
        exec_info = self._executions[execution_id]
        status_info = {'execution_id': str(execution_id), 'status': exec_info['status'], 'start_time': exec_info['start_time'].isoformat(), 'service_id': str(self._id)}
        if 'end_time' in exec_info:
            status_info['end_time'] = exec_info['end_time'].isoformat()
            status_info['execution_time'] = exec_info.get('execution_time', 0)
        if 'result' in exec_info:
            status_info['result'] = exec_info['result'].to_dict()
        if 'error' in exec_info:
            status_info['error'] = exec_info['error']
        return status_info

    async def cancel_execution(self, execution_id: UUID) -> bool:
        if execution_id not in self._executions:
            return False
        exec_info = self._executions[execution_id]
        if exec_info['status'] != 'running':
            return False
        if 'task' in exec_info:
            exec_info['task'].cancel()
        exec_info.update({'status': 'cancelled', 'end_time': datetime.now(timezone.utc)})
        logger.info(f'Cancelled execution {execution_id} for service {self._id}')
        return True

    async def pause(self) -> None:
        if self._current_state == ServiceState.RUNNING:
            while self._current_state == ServiceState.RUNNING:
                await asyncio.sleep(0.1)
        self._current_state = ServiceState.PAUSED
        logger.info(f'Service {self._id} paused')

    async def resume(self) -> None:
        if self._current_state == ServiceState.PAUSED:
            self._current_state = ServiceState.READY
            logger.info(f'Service {self._id} resumed')

    async def drain(self) -> None:
        self._current_state = ServiceState.DRAINING
        while any((exec_info.get('status') == 'running' for exec_info in self._executions.values())):
            await asyncio.sleep(0.1)
        self._current_state = ServiceState.IDLE
        logger.info(f'Service {self._id} drained')

    async def update_configuration(self, new_config: ServiceConfiguration) -> None:
        old_config = self._configuration
        self._configuration = new_config
        await self._validate_configuration()
        logger.info(f'Updated configuration for service {self._id}')

    async def get_metrics(self) -> Dict[str, Any]:
        return {'service_id': str(self._id), 'service_type': self.service_type.value, 'current_state': self._current_state.value, 'execution_count': self._execution_count, 'success_count': self._success_count, 'error_count': self._error_count, 'success_rate': self._success_count / max(self._execution_count, 1), 'average_response_time': self._average_response_time, 'total_execution_time': self._total_execution_time, 'last_execution': self._last_execution.isoformat() if self._last_execution else None, 'active_executions': len([e for e in self._executions.values() if e.get('status') == 'running']), 'memory_usage_mb': self._current_memory_usage, 'cpu_usage_percent': self._current_cpu_usage}

    async def health_check(self) -> Dict[str, Any]:
        health_status = 'healthy'
        issues = []
        if self._current_state == ServiceState.ERROR:
            health_status = 'unhealthy'
            issues.append('Service in error state')
        elif self._current_state in [ServiceState.DRAINING, ServiceState.PAUSED]:
            health_status = 'warning'
            issues.append(f'Service in {self._current_state.value} state')
        if self._execution_count > 10:
            error_rate = self._error_count / self._execution_count
            if error_rate > 0.5:
                health_status = 'unhealthy'
                issues.append(f'High error rate: {error_rate:.2%}')
            elif error_rate > 0.2:
                health_status = 'warning' if health_status == 'healthy' else health_status
                issues.append(f'Elevated error rate: {error_rate:.2%}')
        if self._average_response_time > 10.0:
            health_status = 'warning' if health_status == 'healthy' else health_status
            issues.append(f'Slow response time: {self._average_response_time:.2f}s')
        return {'service_id': str(self._id), 'health_status': health_status, 'timestamp': datetime.now(timezone.utc).isoformat(), 'checks': {'service_state': self._current_state.value, 'error_rate': self._error_count / max(self._execution_count, 1), 'response_time': self._average_response_time, 'active_executions': len([e for e in self._executions.values() if e.get('status') == 'running'])}, 'issues': issues}

    def to_dict(self) -> Dict[str, Any]:
        return {'id': str(self._id), 'service_type': self.service_type.value, 'service_definition_id': self.service_definition_id, 'digital_twin_id': str(self.digital_twin_id), 'instance_name': self.instance_name, 'current_state': self._current_state.value, 'status': self._status.value, 'execution_mode': self.execution_mode.value, 'capabilities': list(self.capabilities), 'metadata': self._metadata.to_dict(), 'statistics': {'execution_count': self._execution_count, 'success_count': self._success_count, 'error_count': self._error_count, 'average_response_time': self._average_response_time}}

    def validate(self) -> bool:
        try:
            if not self._configuration.digital_twin_id:
                return False
            if not self._configuration.instance_name:
                return False
            if not self._service_definition.definition_id:
                return False
            return True
        except Exception:
            return False

    async def _validate_configuration(self) -> None:
        if not self._configuration.instance_name:
            raise ServiceConfigurationError('Instance name is required')

    async def _initialize_resources(self) -> None:
        pass

    async def _cleanup_resources(self) -> None:
        pass

    async def _validate_input_data(self, input_data: Dict[str, Any]) -> None:
        pass

    async def _validate_output_data(self, output_data: Dict[str, Any]) -> None:
        pass

    async def _execute_service_logic(self, request: ServiceRequest) -> Dict[str, Any]:
        if self.service_type == ServiceType.ANALYTICS:
            return await self._execute_analytics(request)
        elif self.service_type == ServiceType.PREDICTION:
            return await self._execute_prediction(request)
        elif self.service_type == ServiceType.ALERTING:
            return await self._execute_alerting(request)
        else:
            return {'result': 'Service executed successfully', 'timestamp': datetime.now(timezone.utc).isoformat()}

    async def _execute_analytics(self, request: ServiceRequest) -> Dict[str, Any]:
        await asyncio.sleep(0.1)
        input_data = request.input_data
        data_points = input_data.get('data_points', [])
        if data_points:
            values = [dp.get('value', 0) for dp in data_points if isinstance(dp.get('value'), (int, float))]
            if values:
                result = {'analytics_type': 'basic_statistics', 'count': len(values), 'average': sum(values) / len(values), 'minimum': min(values), 'maximum': max(values), 'total': sum(values)}
            else:
                result = {'analytics_type': 'basic_statistics', 'error': 'No numeric values found'}
        else:
            result = {'analytics_type': 'basic_statistics', 'error': 'No data points provided'}
        return {'service_type': 'analytics', 'result': result, 'processed_at': datetime.now(timezone.utc).isoformat(), 'input_data_size': len(str(input_data))}

    async def _execute_prediction(self, request: ServiceRequest) -> Dict[str, Any]:
        await asyncio.sleep(0.2)
        input_data = request.input_data
        prediction_horizon = input_data.get('prediction_horizon', 60)
        historical_data = input_data.get('historical_data', [])
        if len(historical_data) >= 2:
            values = [d.get('value', 0) for d in historical_data[-10:]]
            if len(values) >= 2:
                trend = (values[-1] - values[0]) / len(values)
                predicted_value = values[-1] + trend * prediction_horizon / 60
            else:
                predicted_value = values[-1] if values else 0
        else:
            predicted_value = 0
        return {'service_type': 'prediction', 'result': {'predicted_value': predicted_value, 'prediction_horizon_seconds': prediction_horizon, 'confidence': 0.75, 'model_type': 'linear_trend'}, 'processed_at': datetime.now(timezone.utc).isoformat(), 'historical_data_points': len(historical_data)}

    async def _execute_alerting(self, request: ServiceRequest) -> Dict[str, Any]:
        await asyncio.sleep(0.05)
        input_data = request.input_data
        thresholds = input_data.get('thresholds', {})
        current_value = input_data.get('current_value', 0)
        alerts = []
        alert_level = 'info'
        if 'critical_high' in thresholds and current_value > thresholds['critical_high']:
            alerts.append({'level': 'critical', 'message': f"Value {current_value} exceeds critical threshold {thresholds['critical_high']}"})
            alert_level = 'critical'
        elif 'warning_high' in thresholds and current_value > thresholds['warning_high']:
            alerts.append({'level': 'warning', 'message': f"Value {current_value} exceeds warning threshold {thresholds['warning_high']}"})
            alert_level = 'warning'
        elif 'critical_low' in thresholds and current_value < thresholds['critical_low']:
            alerts.append({'level': 'critical', 'message': f"Value {current_value} below critical threshold {thresholds['critical_low']}"})
            alert_level = 'critical'
        elif 'warning_low' in thresholds and current_value < thresholds['warning_low']:
            alerts.append({'level': 'warning', 'message': f"Value {current_value} below warning threshold {thresholds['warning_low']}"})
            alert_level = 'warning'
        return {'service_type': 'alerting', 'result': {'alert_level': alert_level, 'alerts': alerts, 'current_value': current_value, 'thresholds': thresholds, 'alerts_count': len(alerts)}, 'processed_at': datetime.now(timezone.utc).isoformat()}

class ServiceFactory(IServiceFactory):

    def __init__(self):
        self.config = get_config()
        self._service_definitions: Dict[str, ServiceDefinition] = {}
        self._supported_types = list(ServiceType)
        self._load_default_definitions()

    async def create_service_instance(self, service_definition: ServiceDefinition, config: ServiceConfiguration, metadata: Optional[BaseMetadata]=None) -> IService:
        try:
            if not self.validate_service_config(service_definition.definition_id, config):
                raise FactoryConfigurationError('Invalid service configuration')
            if metadata is None:
                metadata = BaseMetadata(entity_id=uuid4(), timestamp=datetime.now(timezone.utc), version=service_definition.version, created_by=uuid4())
            service = StandardService(service_id=metadata.id, service_definition=service_definition, configuration=config, metadata=metadata)
            logger.info(f'Created service instance {metadata.id} from definition {service_definition.definition_id}')
            return service
        except Exception as e:
            logger.error(f'Failed to create service instance: {e}')
            raise EntityCreationError(f'Service instance creation failed: {e}')

    async def register_service_definition(self, definition: ServiceDefinition) -> None:
        self._service_definitions[definition.definition_id] = definition
        logger.info(f'Registered service definition: {definition.definition_id}')

    async def get_service_definition(self, definition_id: str) -> ServiceDefinition:
        if definition_id not in self._service_definitions:
            raise FactoryConfigurationError(f'Service definition {definition_id} not found')
        return self._service_definitions[definition_id]

    def get_available_service_types(self) -> List[ServiceType]:
        return self._supported_types.copy()

    def get_service_definitions(self, service_type: Optional[ServiceType]=None) -> List[ServiceDefinition]:
        definitions = list(self._service_definitions.values())
        if service_type:
            definitions = [d for d in definitions if d.service_type == service_type]
        return definitions

    def validate_service_config(self, definition_id: str, config: ServiceConfiguration) -> bool:
        try:
            if definition_id not in self._service_definitions:
                return False
            definition = self._service_definitions[definition_id]
            if config.service_definition_id != definition_id:
                return False
            if not config.instance_name:
                return False
            if not config.digital_twin_id:
                return False
            return True
        except Exception:
            return False

    async def create(self, config: Dict[str, Any], metadata: Optional[BaseMetadata]=None) -> IService:
        try:
            if not self.validate_config(config):
                raise FactoryConfigurationError('Invalid service configuration')
            definition_id = config['service_definition_id']
            definition = await self.get_service_definition(definition_id)
            service_config = ServiceConfiguration(service_definition_id=definition_id, instance_name=config['instance_name'], digital_twin_id=UUID(config['digital_twin_id']), parameters=config.get('parameters', {}), execution_config=config.get('execution_config', {}), resource_limits=config.get('resource_limits', {}), priority=ServicePriority(config.get('priority', ServicePriority.NORMAL.value)), auto_scaling=config.get('auto_scaling', {}), custom_config=config.get('custom_config', {}))
            return await self.create_service_instance(definition, service_config, metadata)
        except Exception as e:
            logger.error(f'Failed to create service: {e}')
            raise EntityCreationError(f'Service creation failed: {e}')

    async def create_from_template(self, template_id: str, config_overrides: Optional[Dict[str, Any]]=None, metadata: Optional[BaseMetadata]=None) -> IService:
        template = self._get_service_template(template_id)
        if not template:
            raise FactoryConfigurationError(f'Service template {template_id} not found')
        final_config = template.copy()
        if config_overrides:
            final_config.update(config_overrides)
        return await self.create(final_config, metadata)

    def validate_config(self, config: Dict[str, Any]) -> bool:
        required_fields = ['service_definition_id', 'instance_name', 'digital_twin_id']
        for field in required_fields:
            if field not in config:
                return False
        try:
            UUID(config['digital_twin_id'])
            return True
        except (ValueError, TypeError):
            return False

    def get_supported_types(self) -> List[str]:
        return [st.value for st in self._supported_types]

    def get_config_schema(self, entity_type: str) -> Dict[str, Any]:
        return {'type': 'object', 'properties': {'service_definition_id': {'type': 'string'}, 'instance_name': {'type': 'string'}, 'digital_twin_id': {'type': 'string', 'format': 'uuid'}, 'parameters': {'type': 'object'}, 'execution_config': {'type': 'object'}, 'resource_limits': {'type': 'object'}, 'priority': {'type': 'string', 'enum': [p.value for p in ServicePriority]}, 'auto_scaling': {'type': 'object'}, 'custom_config': {'type': 'object'}}, 'required': ['service_definition_id', 'instance_name', 'digital_twin_id']}

    def _load_default_definitions(self) -> None:
        analytics_def = ServiceDefinition(definition_id='analytics_basic', name='Basic Analytics Service', service_type=ServiceType.ANALYTICS, version='1.0.0', description='Basic data analytics service for Digital Twins', execution_mode=ServiceExecutionMode.SYNCHRONOUS, resource_requirements={'memory': 256, 'cpu': 0.5}, input_schema={'type': 'object', 'properties': {'data_points': {'type': 'array'}}}, output_schema={'type': 'object', 'properties': {'result': {'type': 'object'}}}, configuration_schema={'type': 'object'}, dependencies=[], capabilities={'basic_statistics', 'data_analysis'})
        self._service_definitions[analytics_def.definition_id] = analytics_def
        prediction_def = ServiceDefinition(definition_id='prediction_linear', name='Linear Prediction Service', service_type=ServiceType.PREDICTION, version='1.0.0', description='Simple linear prediction service', execution_mode=ServiceExecutionMode.SYNCHRONOUS, resource_requirements={'memory': 512, 'cpu': 1.0}, input_schema={'type': 'object', 'properties': {'historical_data': {'type': 'array'}}}, output_schema={'type': 'object', 'properties': {'predicted_value': {'type': 'number'}}}, configuration_schema={'type': 'object'}, dependencies=[], capabilities={'linear_prediction', 'trend_analysis'})
        self._service_definitions[prediction_def.definition_id] = prediction_def
        alerting_def = ServiceDefinition(definition_id='alerting_threshold', name='Threshold Alerting Service', service_type=ServiceType.ALERTING, version='1.0.0', description='Threshold-based alerting service', execution_mode=ServiceExecutionMode.SYNCHRONOUS, resource_requirements={'memory': 128, 'cpu': 0.2}, input_schema={'type': 'object', 'properties': {'current_value': {'type': 'number'}, 'thresholds': {'type': 'object'}}}, output_schema={'type': 'object', 'properties': {'alerts': {'type': 'array'}}}, configuration_schema={'type': 'object'}, dependencies=[], capabilities={'threshold_monitoring', 'alerting'})
        self._service_definitions[alerting_def.definition_id] = alerting_def
        logger.info(f'Loaded {len(self._service_definitions)} default service definitions')

    def _get_service_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        templates = {'analytics_template': {'service_definition_id': 'analytics_basic', 'instance_name': 'Analytics Service', 'parameters': {'analytics_type': 'basic_statistics'}, 'execution_config': {'timeout': 60}, 'resource_limits': {'memory': 256, 'cpu': 0.5}}, 'prediction_template': {'service_definition_id': 'prediction_linear', 'instance_name': 'Prediction Service', 'parameters': {'model_type': 'linear', 'prediction_horizon': 300}, 'execution_config': {'timeout': 120}, 'resource_limits': {'memory': 512, 'cpu': 1.0}}, 'alerting_template': {'service_definition_id': 'alerting_threshold', 'instance_name': 'Alerting Service', 'parameters': {'notification_channels': ['email', 'webhook']}, 'execution_config': {'timeout': 30}, 'resource_limits': {'memory': 128, 'cpu': 0.2}}}
        return templates.get(template_id)