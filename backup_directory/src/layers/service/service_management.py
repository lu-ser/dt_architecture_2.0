import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple, Callable
from uuid import UUID, uuid4
from enum import Enum
from src.core.interfaces.base import BaseMetadata, EntityStatus
from src.core.interfaces.service import IService, IServiceFactory, IServiceLifecycleManager, IServiceOrchestrator, ServiceType, ServiceDefinition, ServiceConfiguration, ServiceState, ServicePriority, ServiceRequest, ServiceResponse
from src.utils.exceptions import ServiceError, ServiceNotFoundError, ServiceConfigurationError, EntityCreationError
from src.utils.config import get_config
logger = logging.getLogger(__name__)

class ServiceOperationStatus(Enum):
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'

class ServiceOperation:

    def __init__(self, operation_id: UUID, operation_type: str, service_id: UUID, parameters: Dict[str, Any], requester_id: Optional[UUID]=None):
        self.operation_id = operation_id
        self.operation_type = operation_type
        self.service_id = service_id
        self.parameters = parameters
        self.requester_id = requester_id
        self.status = ServiceOperationStatus.PENDING
        self.created_at = datetime.now(timezone.utc)
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.error_message: Optional[str] = None
        self.result: Optional[Dict[str, Any]] = None

    def start_operation(self) -> None:
        self.status = ServiceOperationStatus.IN_PROGRESS
        self.started_at = datetime.now(timezone.utc)

    def complete_operation(self, result: Optional[Dict[str, Any]]=None) -> None:
        self.status = ServiceOperationStatus.COMPLETED
        self.completed_at = datetime.now(timezone.utc)
        self.result = result

    def fail_operation(self, error_message: str) -> None:
        self.status = ServiceOperationStatus.FAILED
        self.completed_at = datetime.now(timezone.utc)
        self.error_message = error_message

    def get_duration(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {'operation_id': str(self.operation_id), 'operation_type': self.operation_type, 'service_id': str(self.service_id), 'status': self.status.value, 'parameters': self.parameters, 'created_at': self.created_at.isoformat(), 'started_at': self.started_at.isoformat() if self.started_at else None, 'completed_at': self.completed_at.isoformat() if self.completed_at else None, 'duration_seconds': self.get_duration(), 'error_message': self.error_message, 'result': self.result}

class ServiceHealthStatus(Enum):
    HEALTHY = 'healthy'
    WARNING = 'warning'
    CRITICAL = 'critical'
    UNKNOWN = 'unknown'

class ServiceHealthCheck:

    def __init__(self, service_id: UUID, status: ServiceHealthStatus, last_check: datetime, checks: Dict[str, bool], metrics: Dict[str, float], issues: List[str]):
        self.service_id = service_id
        self.status = status
        self.last_check = last_check
        self.checks = checks
        self.metrics = metrics
        self.issues = issues

    def to_dict(self) -> Dict[str, Any]:
        return {'service_id': str(self.service_id), 'status': self.status.value, 'last_check': self.last_check.isoformat(), 'checks': self.checks, 'metrics': self.metrics, 'issues': self.issues}

class ServiceDeploymentTarget:

    def __init__(self, target_id: str, target_type: str, capacity: Dict[str, Any], location: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None):
        self.target_id = target_id
        self.target_type = target_type
        self.capacity = capacity
        self.location = location
        self.metadata = metadata or {}
        self.deployed_services: Set[UUID] = set()

    def can_deploy(self, service_requirements: Dict[str, Any]) -> bool:
        required_memory = service_requirements.get('memory_mb', 0)
        required_cpu = service_requirements.get('cpu_cores', 0)
        available_memory = self.capacity.get('memory_mb', 0) - self.get_used_memory()
        available_cpu = self.capacity.get('cpu_cores', 0) - self.get_used_cpu()
        return available_memory >= required_memory and available_cpu >= required_cpu

    def get_used_memory(self) -> float:
        return len(self.deployed_services) * 256

    def get_used_cpu(self) -> float:
        return len(self.deployed_services) * 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {'target_id': self.target_id, 'target_type': self.target_type, 'capacity': self.capacity, 'location': self.location, 'metadata': self.metadata, 'deployed_services': len(self.deployed_services), 'used_memory_mb': self.get_used_memory(), 'used_cpu_cores': self.get_used_cpu()}

class ServiceWorkflow:

    def __init__(self, workflow_id: UUID, name: str, digital_twin_id: UUID, service_chain: List[Dict[str, Any]], workflow_config: Dict[str, Any]):
        self.workflow_id = workflow_id
        self.name = name
        self.digital_twin_id = digital_twin_id
        self.service_chain = service_chain
        self.workflow_config = workflow_config
        self.created_at = datetime.now(timezone.utc)
        self.status = 'created'
        self.execution_history: List[Dict[str, Any]] = []
        self.current_execution_id: Optional[UUID] = None

    def to_dict(self) -> Dict[str, Any]:
        return {'workflow_id': str(self.workflow_id), 'name': self.name, 'digital_twin_id': str(self.digital_twin_id), 'service_chain': self.service_chain, 'workflow_config': self.workflow_config, 'created_at': self.created_at.isoformat(), 'status': self.status, 'execution_count': len(self.execution_history), 'current_execution_id': str(self.current_execution_id) if self.current_execution_id else None}

class ServiceLifecycleManager(IServiceLifecycleManager):

    def __init__(self, factory: IServiceFactory, registry: Any, orchestrator: Optional['ServiceOrchestrator']=None):
        self.factory = factory
        self.registry = registry
        self.orchestrator = orchestrator
        self.config = get_config()
        self.operations: Dict[UUID, ServiceOperation] = {}
        self.operation_lock = asyncio.Lock()
        self.health_checks: Dict[UUID, ServiceHealthCheck] = {}
        self.health_check_interval = 60
        self.health_check_task: Optional[asyncio.Task] = None
        self.deployment_targets: Dict[str, ServiceDeploymentTarget] = {}
        self.service_deployments: Dict[UUID, str] = {}
        self.auto_scaling_configs: Dict[UUID, Dict[str, Any]] = {}
        self.scaling_lock = asyncio.Lock()

    async def create_entity(self, config: Dict[str, Any], metadata: Optional[BaseMetadata]=None) -> IService:
        operation_id = uuid4()
        operation = ServiceOperation(operation_id=operation_id, operation_type='create', service_id=uuid4(), parameters=config)
        async with self.operation_lock:
            self.operations[operation_id] = operation
        try:
            operation.start_operation()
            service = await self.factory.create(config, metadata)
            operation.service_id = service.id
            await self.registry.register_service(service)
            await service.initialize()
            operation.complete_operation({'service_id': str(service.id)})
            logger.info(f'Successfully created Service {service.id}')
            return service
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f'Failed to create Service: {e}')
            raise EntityCreationError(f'Service creation failed: {e}')

    async def start_entity(self, entity_id: UUID) -> None:
        await self._execute_service_operation('start', entity_id, {})

    async def stop_entity(self, entity_id: UUID) -> None:
        await self._execute_service_operation('stop', entity_id, {})

    async def restart_entity(self, entity_id: UUID) -> None:
        await self.stop_entity(entity_id)
        await asyncio.sleep(1)
        await self.start_entity(entity_id)

    async def terminate_entity(self, entity_id: UUID) -> None:
        operation_id = uuid4()
        operation = ServiceOperation(operation_id=operation_id, operation_type='terminate', service_id=entity_id, parameters={})
        async with self.operation_lock:
            self.operations[operation_id] = operation
        try:
            operation.start_operation()
            service = await self.registry.get_service(entity_id)
            await service.terminate()
            if entity_id in self.service_deployments:
                target_id = self.service_deployments[entity_id]
                if target_id in self.deployment_targets:
                    self.deployment_targets[target_id].deployed_services.discard(entity_id)
                del self.service_deployments[entity_id]
            if entity_id in self.auto_scaling_configs:
                del self.auto_scaling_configs[entity_id]
            await self.registry.unregister(entity_id)
            if entity_id in self.health_checks:
                del self.health_checks[entity_id]
            operation.complete_operation()
            logger.info(f'Successfully terminated Service {entity_id}')
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f'Failed to terminate Service {entity_id}: {e}')
            raise ServiceError(f'Failed to terminate service: {e}')

    async def get_entity_status(self, entity_id: UUID) -> EntityStatus:
        try:
            service = await self.registry.get_service(entity_id)
            return service.status
        except ServiceNotFoundError:
            return EntityStatus.TERMINATED

    async def monitor_entity(self, entity_id: UUID) -> Dict[str, Any]:
        try:
            service = await self.registry.get_service(entity_id)
            monitoring_data = {'service_id': str(entity_id), 'status': service.status.value, 'current_state': service.current_state.value, 'service_type': service.service_type.value, 'digital_twin_id': str(service.digital_twin_id), 'capabilities': list(service.capabilities)}
            if entity_id in self.health_checks:
                monitoring_data['health_check'] = self.health_checks[entity_id].to_dict()
            if entity_id in self.service_deployments:
                target_id = self.service_deployments[entity_id]
                monitoring_data['deployment_target'] = target_id
                if target_id in self.deployment_targets:
                    monitoring_data['deployment_info'] = self.deployment_targets[target_id].to_dict()
            try:
                performance = await self.registry.get_service_performance(entity_id)
                monitoring_data['performance'] = performance
            except Exception as e:
                monitoring_data['performance_error'] = str(e)
            if entity_id in self.auto_scaling_configs:
                monitoring_data['auto_scaling'] = self.auto_scaling_configs[entity_id]
            return monitoring_data
        except ServiceNotFoundError:
            return {'error': f'Service {entity_id} not found'}

    async def deploy_service(self, service: IService, deployment_target: str, deployment_config: Dict[str, Any]) -> str:
        operation_id = uuid4()
        operation = ServiceOperation(operation_id=operation_id, operation_type='deploy', service_id=service.id, parameters={'deployment_target': deployment_target, 'deployment_config': deployment_config})
        async with self.operation_lock:
            self.operations[operation_id] = operation
        try:
            operation.start_operation()
            if deployment_target not in self.deployment_targets:
                raise ServiceError(f'Deployment target {deployment_target} not found')
            target = self.deployment_targets[deployment_target]
            service_requirements = {'memory_mb': deployment_config.get('memory_mb', 256), 'cpu_cores': deployment_config.get('cpu_cores', 0.5)}
            if not target.can_deploy(service_requirements):
                raise ServiceError(f'Deployment target {deployment_target} has insufficient capacity')
            deployment_id = f'deployment-{service.id}-{deployment_target}'
            target.deployed_services.add(service.id)
            self.service_deployments[service.id] = deployment_target
            operation.complete_operation({'deployment_id': deployment_id})
            logger.info(f'Successfully deployed service {service.id} to {deployment_target}')
            return deployment_id
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f'Failed to deploy service {service.id}: {e}')
            raise ServiceError(f'Deployment failed: {e}')

    async def scale_service(self, service_id: UUID, target_instances: int, scaling_strategy: str='gradual') -> None:
        async with self.scaling_lock:
            operation_id = uuid4()
            operation = ServiceOperation(operation_id=operation_id, operation_type='scale', service_id=service_id, parameters={'target_instances': target_instances, 'scaling_strategy': scaling_strategy})
            async with self.operation_lock:
                self.operations[operation_id] = operation
            try:
                operation.start_operation()
                original_service = await self.registry.get_service(service_id)
                if target_instances > 1:
                    for i in range(target_instances - 1):
                        config = {'service_definition_id': original_service.service_definition_id, 'instance_name': f'{original_service.instance_name}-scale-{i + 1}', 'digital_twin_id': str(original_service.digital_twin_id), 'parameters': original_service.configuration.parameters, 'execution_config': original_service.configuration.execution_config, 'resource_limits': original_service.configuration.resource_limits, 'priority': original_service.configuration.priority.value}
                        scaled_service = await self.factory.create(config)
                        await self.registry.register_service(scaled_service)
                        await scaled_service.initialize()
                        await scaled_service.start()
                        logger.info(f'Created scaled service {scaled_service.id} from {service_id}')
                operation.complete_operation({'target_instances': target_instances})
                logger.info(f'Successfully scaled service {service_id} to {target_instances} instances')
            except Exception as e:
                operation.fail_operation(str(e))
                logger.error(f'Failed to scale service {service_id}: {e}')
                raise ServiceError(f'Scaling failed: {e}')

    async def update_service(self, service_id: UUID, new_definition: ServiceDefinition, update_strategy: str='rolling') -> None:
        operation_id = uuid4()
        operation = ServiceOperation(operation_id=operation_id, operation_type='update', service_id=service_id, parameters={'new_definition_id': new_definition.definition_id, 'update_strategy': update_strategy})
        async with self.operation_lock:
            self.operations[operation_id] = operation
        try:
            operation.start_operation()
            service = await self.registry.get_service(service_id)
            new_config = ServiceConfiguration(service_definition_id=new_definition.definition_id, instance_name=service.instance_name, digital_twin_id=service.digital_twin_id, parameters=service.configuration.parameters, execution_config=service.configuration.execution_config, resource_limits=service.configuration.resource_limits, priority=service.configuration.priority)
            await service.update_configuration(new_config)
            operation.complete_operation({'new_definition_id': new_definition.definition_id})
            logger.info(f'Successfully updated service {service_id}')
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f'Failed to update service {service_id}: {e}')
            raise ServiceError(f'Update failed: {e}')

    async def rollback_service(self, service_id: UUID, target_version: Optional[str]=None) -> None:
        logger.info(f"Rollback requested for service {service_id} to version {target_version or 'previous'}")

    async def get_service_instances(self, digital_twin_id: Optional[UUID]=None, service_type: Optional[ServiceType]=None) -> List[IService]:
        criteria = {}
        if digital_twin_id:
            criteria['digital_twin_id'] = str(digital_twin_id)
        if service_type:
            criteria['type'] = service_type.value
        return await self.registry.discover_services(criteria)

    async def add_deployment_target(self, target: ServiceDeploymentTarget) -> None:
        self.deployment_targets[target.target_id] = target
        logger.info(f'Added deployment target {target.target_id}')

    async def remove_deployment_target(self, target_id: str) -> None:
        if target_id in self.deployment_targets:
            target = self.deployment_targets[target_id]
            if target.deployed_services:
                raise ServiceError(f'Cannot remove target {target_id}: {len(target.deployed_services)} services deployed')
            del self.deployment_targets[target_id]
            logger.info(f'Removed deployment target {target_id}')

    async def configure_auto_scaling(self, service_id: UUID, auto_scaling_config: Dict[str, Any]) -> None:
        self.auto_scaling_configs[service_id] = auto_scaling_config
        logger.info(f'Configured auto-scaling for service {service_id}')

    async def perform_health_check(self, service_id: UUID) -> ServiceHealthCheck:
        try:
            service = await self.registry.get_service(service_id)
            checks = {}
            metrics = {}
            issues = []
            checks['state_check'] = service.current_state in [ServiceState.READY, ServiceState.IDLE]
            if not checks['state_check']:
                issues.append(f'Service state is {service.current_state.value}')
            checks['status_check'] = service.status == EntityStatus.ACTIVE
            if not checks['status_check']:
                issues.append(f'Service status is {service.status.value}')
            service_metrics = await service.get_metrics()
            metrics['success_rate'] = service_metrics.get('success_rate', 0.0)
            metrics['average_response_time'] = service_metrics.get('average_response_time', 0.0)
            metrics['error_count'] = service_metrics.get('error_count', 0)
            checks['performance_check'] = metrics['success_rate'] > 0.8 and metrics['average_response_time'] < 5.0
            if not checks['performance_check']:
                issues.append(f"Poor performance: success_rate={metrics['success_rate']:.2f}, response_time={metrics['average_response_time']:.2f}s")
            failed_checks = sum((1 for check in checks.values() if not check))
            if failed_checks == 0:
                status = ServiceHealthStatus.HEALTHY
            elif failed_checks <= 1:
                status = ServiceHealthStatus.WARNING
            else:
                status = ServiceHealthStatus.CRITICAL
            health_check = ServiceHealthCheck(service_id=service_id, status=status, last_check=datetime.now(timezone.utc), checks=checks, metrics=metrics, issues=issues)
            self.health_checks[service_id] = health_check
            return health_check
        except Exception as e:
            logger.error(f'Health check failed for service {service_id}: {e}')
            return ServiceHealthCheck(service_id=service_id, status=ServiceHealthStatus.UNKNOWN, last_check=datetime.now(timezone.utc), checks={}, metrics={}, issues=[str(e)])

    async def start_health_monitoring(self) -> None:

        async def health_monitor():
            while True:
                try:
                    services = await self.registry.list()
                    for service in services:
                        await self.perform_health_check(service.id)
                    await self._check_auto_scaling_triggers()
                    await asyncio.sleep(self.health_check_interval)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f'Health monitoring error: {e}')
                    await asyncio.sleep(self.health_check_interval)
        if self.health_check_task is None or self.health_check_task.done():
            self.health_check_task = asyncio.create_task(health_monitor())
            logger.info('Started health monitoring')

    async def stop_health_monitoring(self) -> None:
        if self.health_check_task and (not self.health_check_task.done()):
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass
            logger.info('Stopped health monitoring')

    async def get_operation_status(self, operation_id: UUID) -> Optional[ServiceOperation]:
        return self.operations.get(operation_id)

    async def get_service_operations(self, service_id: UUID, limit: Optional[int]=None) -> List[ServiceOperation]:
        operations = [op for op in self.operations.values() if op.service_id == service_id]
        operations.sort(key=lambda op: op.created_at, reverse=True)
        if limit:
            operations = operations[:limit]
        return operations

    async def get_management_statistics(self) -> Dict[str, Any]:
        services = await self.registry.list()
        operation_stats = {}
        for op_type in ['create', 'start', 'stop', 'deploy', 'scale', 'update']:
            ops = [op for op in self.operations.values() if op.operation_type == op_type]
            operation_stats[op_type] = {'total': len(ops), 'completed': len([op for op in ops if op.status == ServiceOperationStatus.COMPLETED]), 'failed': len([op for op in ops if op.status == ServiceOperationStatus.FAILED]), 'pending': len([op for op in ops if op.status == ServiceOperationStatus.PENDING])}
        health_stats = {}
        for status in ServiceHealthStatus:
            health_stats[status.value] = len([hc for hc in self.health_checks.values() if hc.status == status])
        deployment_stats = {'total_targets': len(self.deployment_targets), 'deployed_services': len(self.service_deployments), 'target_utilization': {}}
        for target_id, target in self.deployment_targets.items():
            max_services = target.capacity.get('max_services', 10)
            utilization = len(target.deployed_services) / max(max_services, 1)
            deployment_stats['target_utilization'][target_id] = utilization
        auto_scaling_stats = {'services_with_auto_scaling': len(self.auto_scaling_configs), 'auto_scaling_enabled': sum((1 for config in self.auto_scaling_configs.values() if config.get('enabled', False)))}
        return {'total_services': len(services), 'operation_statistics': operation_stats, 'health_statistics': health_stats, 'deployment_statistics': deployment_stats, 'auto_scaling_statistics': auto_scaling_stats, 'health_monitoring_active': self.health_check_task is not None and (not self.health_check_task.done())}

    async def _execute_service_operation(self, operation_type: str, service_id: UUID, parameters: Dict[str, Any]) -> None:
        operation_id = uuid4()
        operation = ServiceOperation(operation_id=operation_id, operation_type=operation_type, service_id=service_id, parameters=parameters)
        async with self.operation_lock:
            self.operations[operation_id] = operation
        try:
            operation.start_operation()
            service = await self.registry.get_service(service_id)
            if operation_type == 'start':
                await service.start()
            elif operation_type == 'stop':
                await service.stop()
            elif operation_type == 'pause':
                await service.pause()
            elif operation_type == 'resume':
                await service.resume()
            else:
                raise ServiceError(f'Unknown operation type: {operation_type}')
            operation.complete_operation()
            logger.info(f'Successfully executed {operation_type} on service {service_id}')
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f'Failed to execute {operation_type} on service {service_id}: {e}')
            raise ServiceError(f'Operation {operation_type} failed: {e}')

    async def _check_auto_scaling_triggers(self) -> None:
        for service_id, config in self.auto_scaling_configs.items():
            if not config.get('enabled', False):
                continue
            try:
                service_metrics = await self.registry.get_service_performance(service_id)
                current_instances = 1
                min_instances = config.get('min_instances', 1)
                max_instances = config.get('max_instances', 5)
                success_rate = service_metrics.get('success_rate', 0.0)
                response_time = service_metrics.get('average_execution_time', 0.0)
                if success_rate > 0.9 and response_time > 2.0 and (current_instances < max_instances):
                    logger.info(f'Auto-scaling up service {service_id}')
                elif success_rate > 0.95 and response_time < 0.5 and (current_instances > min_instances):
                    logger.info(f'Auto-scaling down service {service_id}')
            except Exception as e:
                logger.error(f'Auto-scaling check failed for service {service_id}: {e}')

class ServiceOrchestrator(IServiceOrchestrator):

    def __init__(self, lifecycle_manager: ServiceLifecycleManager, registry: Any):
        self.lifecycle_manager = lifecycle_manager
        self.registry = registry
        self.workflows: Dict[UUID, ServiceWorkflow] = {}
        self.workflow_lock = asyncio.Lock()

    async def create_workflow(self, workflow_name: str, service_chain: List[Dict[str, Any]], workflow_config: Dict[str, Any]) -> UUID:
        workflow_id = uuid4()
        async with self.workflow_lock:
            workflow = ServiceWorkflow(workflow_id=workflow_id, name=workflow_name, digital_twin_id=UUID(workflow_config.get('digital_twin_id', str(uuid4()))), service_chain=service_chain, workflow_config=workflow_config)
            self.workflows[workflow_id] = workflow
        logger.info(f'Created workflow {workflow_name} with ID {workflow_id}')
        return workflow_id

    async def execute_workflow(self, workflow_id: UUID, input_data: Dict[str, Any], execution_config: Optional[Dict[str, Any]]=None) -> UUID:
        if workflow_id not in self.workflows:
            raise ServiceError(f'Workflow {workflow_id} not found')
        workflow = self.workflows[workflow_id]
        execution_id = uuid4()

        async def execute_workflow_async():
            try:
                workflow.status = 'running'
                workflow.current_execution_id = execution_id
                current_data = input_data
                results = []
                for step_idx, step in enumerate(workflow.service_chain):
                    step_name = step.get('step_name', f'step_{step_idx}')
                    service_id = UUID(step['service_id'])
                    step_config = step.get('config', {})
                    logger.info(f'Executing workflow step {step_name} with service {service_id}')
                    service = await self.registry.get_service(service_id)
                    request = ServiceRequest(request_id=uuid4(), requester_id=uuid4(), service_instance_id=service_id, input_data=current_data, execution_parameters=step_config)
                    response = await service.execute(request)
                    step_result = {'step_name': step_name, 'service_id': str(service_id), 'response': response.to_dict(), 'executed_at': datetime.now(timezone.utc).isoformat()}
                    results.append(step_result)
                    if response.success:
                        current_data = response.output_data
                    else:
                        workflow.status = 'failed'
                        workflow.execution_history.append({'execution_id': str(execution_id), 'status': 'failed', 'results': results, 'error': f'Step {step_name} failed: {response.error_message}', 'completed_at': datetime.now(timezone.utc).isoformat()})
                        return
                workflow.status = 'completed'
                workflow.execution_history.append({'execution_id': str(execution_id), 'status': 'completed', 'results': results, 'completed_at': datetime.now(timezone.utc).isoformat()})
                logger.info(f'Workflow {workflow_id} completed successfully')
            except Exception as e:
                workflow.status = 'failed'
                workflow.execution_history.append({'execution_id': str(execution_id), 'status': 'failed', 'error': str(e), 'completed_at': datetime.now(timezone.utc).isoformat()})
                logger.error(f'Workflow {workflow_id} failed: {e}')
        asyncio.create_task(execute_workflow_async())
        return execution_id

    async def monitor_workflow(self, execution_id: UUID) -> Dict[str, Any]:
        for workflow in self.workflows.values():
            if workflow.current_execution_id == execution_id:
                return {'execution_id': str(execution_id), 'workflow_id': str(workflow.workflow_id), 'workflow_name': workflow.name, 'status': workflow.status, 'execution_history': workflow.execution_history[-1] if workflow.execution_history else None}
        return {'error': 'Execution not found'}

    async def compose_services(self, service_ids: List[UUID], composition_rules: Dict[str, Any]) -> UUID:
        service_chain = []
        for idx, service_id in enumerate(service_ids):
            service_chain.append({'step_name': f'service_{idx}', 'service_id': str(service_id), 'config': composition_rules.get(f'service_{idx}_config', {})})
        return await self.create_workflow(workflow_name=f'Composed Service - {len(service_ids)} services', service_chain=service_chain, workflow_config=composition_rules)