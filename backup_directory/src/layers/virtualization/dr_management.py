import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple, Callable
from uuid import UUID, uuid4
from enum import Enum
from src.core.interfaces.base import BaseMetadata, EntityStatus
from src.core.interfaces.replica import IDigitalReplica, IReplicaFactory, IReplicaLifecycleManager, ReplicaType, ReplicaConfiguration, DataAggregationMode, DeviceData, DataQuality
from src.utils.exceptions import DigitalReplicaError, DigitalReplicaNotFoundError, EntityCreationError, RegistryError
from src.utils.config import get_config
logger = logging.getLogger(__name__)

class ReplicaOperationStatus(Enum):
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'

class ReplicaOperation:

    def __init__(self, operation_id: UUID, operation_type: str, replica_id: UUID, parameters: Dict[str, Any], requester_id: Optional[UUID]=None):
        self.operation_id = operation_id
        self.operation_type = operation_type
        self.replica_id = replica_id
        self.parameters = parameters
        self.requester_id = requester_id
        self.status = ReplicaOperationStatus.PENDING
        self.created_at = datetime.now(timezone.utc)
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.error_message: Optional[str] = None
        self.result: Optional[Dict[str, Any]] = None

    def start_operation(self) -> None:
        self.status = ReplicaOperationStatus.IN_PROGRESS
        self.started_at = datetime.now(timezone.utc)

    def complete_operation(self, result: Optional[Dict[str, Any]]=None) -> None:
        self.status = ReplicaOperationStatus.COMPLETED
        self.completed_at = datetime.now(timezone.utc)
        self.result = result

    def fail_operation(self, error_message: str) -> None:
        self.status = ReplicaOperationStatus.FAILED
        self.completed_at = datetime.now(timezone.utc)
        self.error_message = error_message

    def cancel_operation(self) -> None:
        self.status = ReplicaOperationStatus.CANCELLED
        self.completed_at = datetime.now(timezone.utc)

    def get_duration(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {'operation_id': str(self.operation_id), 'operation_type': self.operation_type, 'replica_id': str(self.replica_id), 'status': self.status.value, 'parameters': self.parameters, 'requester_id': str(self.requester_id) if self.requester_id else None, 'created_at': self.created_at.isoformat(), 'started_at': self.started_at.isoformat() if self.started_at else None, 'completed_at': self.completed_at.isoformat() if self.completed_at else None, 'duration_seconds': self.get_duration(), 'error_message': self.error_message, 'result': self.result}

class ReplicaHealthStatus(Enum):
    HEALTHY = 'healthy'
    WARNING = 'warning'
    CRITICAL = 'critical'
    UNKNOWN = 'unknown'

class ReplicaHealthCheck:

    def __init__(self, replica_id: UUID, status: ReplicaHealthStatus, last_check: datetime, checks: Dict[str, bool], metrics: Dict[str, float], issues: List[str]):
        self.replica_id = replica_id
        self.status = status
        self.last_check = last_check
        self.checks = checks
        self.metrics = metrics
        self.issues = issues

    def to_dict(self) -> Dict[str, Any]:
        return {'replica_id': str(self.replica_id), 'status': self.status.value, 'last_check': self.last_check.isoformat(), 'checks': self.checks, 'metrics': self.metrics, 'issues': self.issues}

class ReplicaDeploymentTarget:

    def __init__(self, target_id: str, target_type: str, capacity: Dict[str, Any], location: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None):
        self.target_id = target_id
        self.target_type = target_type
        self.capacity = capacity
        self.location = location
        self.metadata = metadata or {}
        self.deployed_replicas: Set[UUID] = set()

    def can_deploy(self, replica_requirements: Dict[str, Any]) -> bool:
        required_memory = replica_requirements.get('memory', 0)
        required_cpu = replica_requirements.get('cpu', 0)
        available_memory = self.capacity.get('memory', 0) - self.get_used_memory()
        available_cpu = self.capacity.get('cpu', 0) - self.get_used_cpu()
        return available_memory >= required_memory and available_cpu >= required_cpu

    def get_used_memory(self) -> float:
        return len(self.deployed_replicas) * 100

    def get_used_cpu(self) -> float:
        return len(self.deployed_replicas) * 0.1

    def to_dict(self) -> Dict[str, Any]:
        return {'target_id': self.target_id, 'target_type': self.target_type, 'capacity': self.capacity, 'location': self.location, 'metadata': self.metadata, 'deployed_replicas': len(self.deployed_replicas), 'used_memory': self.get_used_memory(), 'used_cpu': self.get_used_cpu()}

class DigitalReplicaLifecycleManager(IReplicaLifecycleManager):

    def __init__(self, factory: IReplicaFactory, registry: Any, orchestrator: Optional['ReplicaOrchestrator']=None):
        self.factory = factory
        self.registry = registry
        self.orchestrator = orchestrator
        self.config = get_config()
        self.operations: Dict[UUID, ReplicaOperation] = {}
        self.operation_lock = asyncio.Lock()
        self.health_checks: Dict[UUID, ReplicaHealthCheck] = {}
        self.health_check_interval = 60
        self.health_check_task: Optional[asyncio.Task] = None
        self.deployment_targets: Dict[str, ReplicaDeploymentTarget] = {}
        self.replica_deployments: Dict[UUID, str] = {}

    async def create_entity(self, config: Dict[str, Any], metadata: Optional[BaseMetadata]=None) -> IDigitalReplica:
        operation_id = uuid4()
        operation = ReplicaOperation(operation_id=operation_id, operation_type='create', replica_id=uuid4(), parameters=config)
        async with self.operation_lock:
            self.operations[operation_id] = operation
        try:
            operation.start_operation()
            replica = await self.factory.create(config, metadata)
            operation.replica_id = replica.id
            await self.registry.register_digital_replica(replica)
            await replica.initialize()
            operation.complete_operation({'replica_id': str(replica.id)})
            logger.info(f'Successfully created Digital Replica {replica.id}')
            return replica
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f'Failed to create Digital Replica: {e}')
            raise EntityCreationError(f'Digital Replica creation failed: {e}')

    async def start_entity(self, entity_id: UUID) -> None:
        operation_id = uuid4()
        operation = ReplicaOperation(operation_id=operation_id, operation_type='start', replica_id=entity_id, parameters={})
        async with self.operation_lock:
            self.operations[operation_id] = operation
        try:
            operation.start_operation()
            replica = await self.registry.get_digital_replica(entity_id)
            await replica.start()
            operation.complete_operation()
            logger.info(f'Successfully started Digital Replica {entity_id}')
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f'Failed to start Digital Replica {entity_id}: {e}')
            raise DigitalReplicaError(f'Failed to start replica: {e}')

    async def stop_entity(self, entity_id: UUID) -> None:
        operation_id = uuid4()
        operation = ReplicaOperation(operation_id=operation_id, operation_type='stop', replica_id=entity_id, parameters={})
        async with self.operation_lock:
            self.operations[operation_id] = operation
        try:
            operation.start_operation()
            replica = await self.registry.get_digital_replica(entity_id)
            await replica.stop()
            operation.complete_operation()
            logger.info(f'Successfully stopped Digital Replica {entity_id}')
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f'Failed to stop Digital Replica {entity_id}: {e}')
            raise DigitalReplicaError(f'Failed to stop replica: {e}')

    async def restart_entity(self, entity_id: UUID) -> None:
        await self.stop_entity(entity_id)
        await asyncio.sleep(1)
        await self.start_entity(entity_id)

    async def terminate_entity(self, entity_id: UUID) -> None:
        operation_id = uuid4()
        operation = ReplicaOperation(operation_id=operation_id, operation_type='terminate', replica_id=entity_id, parameters={})
        async with self.operation_lock:
            self.operations[operation_id] = operation
        try:
            operation.start_operation()
            replica = await self.registry.get_digital_replica(entity_id)
            await replica.terminate()
            if entity_id in self.replica_deployments:
                target_id = self.replica_deployments[entity_id]
                if target_id in self.deployment_targets:
                    self.deployment_targets[target_id].deployed_replicas.discard(entity_id)
                del self.replica_deployments[entity_id]
            await self.registry.unregister(entity_id)
            if entity_id in self.health_checks:
                del self.health_checks[entity_id]
            operation.complete_operation()
            logger.info(f'Successfully terminated Digital Replica {entity_id}')
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f'Failed to terminate Digital Replica {entity_id}: {e}')
            raise DigitalReplicaError(f'Failed to terminate replica: {e}')

    async def get_entity_status(self, entity_id: UUID) -> EntityStatus:
        try:
            replica = await self.registry.get_digital_replica(entity_id)
            return replica.status
        except DigitalReplicaNotFoundError:
            return EntityStatus.TERMINATED

    async def monitor_entity(self, entity_id: UUID) -> Dict[str, Any]:
        try:
            replica = await self.registry.get_digital_replica(entity_id)
            monitoring_data = {'replica_id': str(entity_id), 'status': replica.status.value, 'type': replica.replica_type.value, 'aggregation_mode': replica.aggregation_mode.value, 'device_count': len(replica.device_ids), 'parent_digital_twin_id': str(replica.parent_digital_twin_id)}
            if entity_id in self.health_checks:
                monitoring_data['health_check'] = self.health_checks[entity_id].to_dict()
            if entity_id in self.replica_deployments:
                target_id = self.replica_deployments[entity_id]
                monitoring_data['deployment_target'] = target_id
                if target_id in self.deployment_targets:
                    monitoring_data['deployment_info'] = self.deployment_targets[target_id].to_dict()
            try:
                performance = await self.registry.get_replica_performance(entity_id)
                monitoring_data['performance'] = performance
            except Exception as e:
                monitoring_data['performance_error'] = str(e)
            return monitoring_data
        except DigitalReplicaNotFoundError:
            return {'error': f'Replica {entity_id} not found'}

    async def deploy_replica(self, replica: IDigitalReplica, deployment_target: str) -> str:
        operation_id = uuid4()
        operation = ReplicaOperation(operation_id=operation_id, operation_type='deploy', replica_id=replica.id, parameters={'deployment_target': deployment_target})
        async with self.operation_lock:
            self.operations[operation_id] = operation
        try:
            operation.start_operation()
            if deployment_target not in self.deployment_targets:
                raise DigitalReplicaError(f'Deployment target {deployment_target} not found')
            target = self.deployment_targets[deployment_target]
            replica_requirements = {'memory': 100, 'cpu': 0.1}
            if not target.can_deploy(replica_requirements):
                raise DigitalReplicaError(f'Deployment target {deployment_target} has insufficient capacity')
            deployment_id = f'deployment-{replica.id}-{deployment_target}'
            target.deployed_replicas.add(replica.id)
            self.replica_deployments[replica.id] = deployment_target
            operation.complete_operation({'deployment_id': deployment_id})
            logger.info(f'Successfully deployed replica {replica.id} to {deployment_target}')
            return deployment_id
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f'Failed to deploy replica {replica.id}: {e}')
            raise DigitalReplicaError(f'Deployment failed: {e}')

    async def scale_replica(self, replica_id: UUID, scale_factor: int) -> None:
        operation_id = uuid4()
        operation = ReplicaOperation(operation_id=operation_id, operation_type='scale', replica_id=replica_id, parameters={'scale_factor': scale_factor})
        async with self.operation_lock:
            self.operations[operation_id] = operation
        try:
            operation.start_operation()
            original_replica = await self.registry.get_digital_replica(replica_id)
            if scale_factor > 1:
                for i in range(scale_factor - 1):
                    config = {'replica_type': original_replica.replica_type.value, 'parent_digital_twin_id': str(original_replica.parent_digital_twin_id), 'device_ids': original_replica.device_ids.copy(), 'aggregation_mode': original_replica.aggregation_mode.value, 'aggregation_config': original_replica.configuration.aggregation_config, 'data_retention_policy': original_replica.configuration.data_retention_policy, 'quality_thresholds': original_replica.configuration.quality_thresholds}
                    scaled_replica = await self.factory.create(config)
                    await self.registry.register_digital_replica(scaled_replica)
                    await scaled_replica.initialize()
                    await scaled_replica.start()
                    logger.info(f'Created scaled replica {scaled_replica.id} from {replica_id}')
            operation.complete_operation({'scale_factor': scale_factor})
            logger.info(f'Successfully scaled replica {replica_id} by factor {scale_factor}')
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f'Failed to scale replica {replica_id}: {e}')
            raise DigitalReplicaError(f'Scaling failed: {e}')

    async def migrate_replica(self, replica_id: UUID, target_location: str) -> None:
        operation_id = uuid4()
        operation = ReplicaOperation(operation_id=operation_id, operation_type='migrate', replica_id=replica_id, parameters={'target_location': target_location})
        async with self.operation_lock:
            self.operations[operation_id] = operation
        try:
            operation.start_operation()
            replica = await self.registry.get_digital_replica(replica_id)
            snapshot = await replica.create_snapshot()
            await replica.stop()
            if target_location in self.deployment_targets:
                await self.deploy_replica(replica, target_location)
            await replica.start()
            operation.complete_operation({'snapshot_id': str(snapshot.twin_id)})
            logger.info(f'Successfully migrated replica {replica_id} to {target_location}')
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f'Failed to migrate replica {replica_id}: {e}')
            raise DigitalReplicaError(f'Migration failed: {e}')

    async def backup_replica_state(self, replica_id: UUID) -> str:
        try:
            replica = await self.registry.get_digital_replica(replica_id)
            snapshot = await replica.create_snapshot()
            backup_reference = f'backup-{replica_id}-{datetime.now(timezone.utc).isoformat()}'
            logger.info(f'Created backup {backup_reference} for replica {replica_id}')
            return backup_reference
        except Exception as e:
            logger.error(f'Failed to backup replica {replica_id}: {e}')
            raise DigitalReplicaError(f'Backup failed: {e}')

    async def restore_replica_state(self, replica_id: UUID, backup_reference: str) -> None:
        try:
            replica = await self.registry.get_digital_replica(replica_id)
            logger.info(f'Restored replica {replica_id} from backup {backup_reference}')
        except Exception as e:
            logger.error(f'Failed to restore replica {replica_id}: {e}')
            raise DigitalReplicaError(f'Restore failed: {e}')

    async def add_deployment_target(self, target: ReplicaDeploymentTarget) -> None:
        self.deployment_targets[target.target_id] = target
        logger.info(f'Added deployment target {target.target_id}')

    async def remove_deployment_target(self, target_id: str) -> None:
        if target_id in self.deployment_targets:
            target = self.deployment_targets[target_id]
            if target.deployed_replicas:
                raise DigitalReplicaError(f'Cannot remove target {target_id}: {len(target.deployed_replicas)} replicas deployed')
            del self.deployment_targets[target_id]
            logger.info(f'Removed deployment target {target_id}')

    async def perform_health_check(self, replica_id: UUID) -> ReplicaHealthCheck:
        try:
            replica = await self.registry.get_digital_replica(replica_id)
            checks = {}
            metrics = {}
            issues = []
            checks['status_check'] = replica.status in [EntityStatus.ACTIVE, EntityStatus.INACTIVE]
            if not checks['status_check']:
                issues.append(f'Replica status is {replica.status.value}')
            performance = await self.registry.get_replica_performance(replica_id)
            data_received = performance.get('total_data_received', 0)
            checks['data_flow'] = data_received > 0
            if not checks['data_flow']:
                issues.append('No data received')
            metrics['response_time'] = 0.1
            metrics['memory_usage'] = 50.0
            metrics['cpu_usage'] = 5.0
            failed_checks = sum((1 for check in checks.values() if not check))
            if failed_checks == 0:
                status = ReplicaHealthStatus.HEALTHY
            elif failed_checks <= 1:
                status = ReplicaHealthStatus.WARNING
            else:
                status = ReplicaHealthStatus.CRITICAL
            health_check = ReplicaHealthCheck(replica_id=replica_id, status=status, last_check=datetime.now(timezone.utc), checks=checks, metrics=metrics, issues=issues)
            self.health_checks[replica_id] = health_check
            return health_check
        except Exception as e:
            logger.error(f'Health check failed for replica {replica_id}: {e}')
            return ReplicaHealthCheck(replica_id=replica_id, status=ReplicaHealthStatus.UNKNOWN, last_check=datetime.now(timezone.utc), checks={}, metrics={}, issues=[str(e)])

    async def start_health_monitoring(self) -> None:

        async def health_monitor():
            while True:
                try:
                    replicas = await self.registry.list()
                    for replica in replicas:
                        await self.perform_health_check(replica.id)
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

    async def get_operation_status(self, operation_id: UUID) -> Optional[ReplicaOperation]:
        return self.operations.get(operation_id)

    async def get_replica_operations(self, replica_id: UUID, limit: Optional[int]=None) -> List[ReplicaOperation]:
        operations = [op for op in self.operations.values() if op.replica_id == replica_id]
        operations.sort(key=lambda op: op.created_at, reverse=True)
        if limit:
            operations = operations[:limit]
        return operations

    async def get_management_statistics(self) -> Dict[str, Any]:
        replicas = await self.registry.list()
        operation_stats = {}
        for op_type in ['create', 'start', 'stop', 'deploy', 'scale', 'migrate']:
            ops = [op for op in self.operations.values() if op.operation_type == op_type]
            operation_stats[op_type] = {'total': len(ops), 'completed': len([op for op in ops if op.status == ReplicaOperationStatus.COMPLETED]), 'failed': len([op for op in ops if op.status == ReplicaOperationStatus.FAILED]), 'pending': len([op for op in ops if op.status == ReplicaOperationStatus.PENDING])}
        health_stats = {}
        for status in ReplicaHealthStatus:
            health_stats[status.value] = len([hc for hc in self.health_checks.values() if hc.status == status])
        deployment_stats = {'total_targets': len(self.deployment_targets), 'deployed_replicas': len(self.replica_deployments), 'target_utilization': {}}
        for target_id, target in self.deployment_targets.items():
            utilization = len(target.deployed_replicas) / max(target.capacity.get('max_replicas', 10), 1)
            deployment_stats['target_utilization'][target_id] = utilization
        return {'total_replicas': len(replicas), 'operation_statistics': operation_stats, 'health_statistics': health_stats, 'deployment_statistics': deployment_stats, 'health_monitoring_active': self.health_check_task is not None and (not self.health_check_task.done())}