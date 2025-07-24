"""
Digital Replica Management Module for the Digital Twin Platform.

This module provides comprehensive lifecycle management for Digital Replicas,
including creation, deployment, monitoring, scaling, and orchestration.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple, Callable
from uuid import UUID, uuid4
from enum import Enum

from src.core.interfaces.base import BaseMetadata, EntityStatus
from src.core.interfaces.replica import (
    IDigitalReplica,
    IReplicaFactory,
    IReplicaLifecycleManager,
    ReplicaType,
    ReplicaConfiguration,
    DataAggregationMode,
    DeviceData,
    DataQuality
)
from src.utils.exceptions import (
    DigitalReplicaError,
    DigitalReplicaNotFoundError,
    EntityCreationError,
    RegistryError
)
from src.utils.config import get_config

logger = logging.getLogger(__name__)


class ReplicaOperationStatus(Enum):
    """Status of replica operations."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def safe_enum_value(obj, default="unknown"):
    """Safely get enum value, handling both enum objects and strings."""
    if hasattr(obj, 'value'):
        return obj.value
    return str(obj) if obj is not None else default

class ReplicaOperation:
    """Represents an operation performed on a Digital Replica."""
    
    def __init__(
        self,
        operation_id: UUID,
        operation_type: str,
        replica_id: UUID,
        parameters: Dict[str, Any],
        requester_id: Optional[UUID] = None
    ):
        self.operation_id = operation_id
        self.operation_type = operation_type  # create, start, stop, scale, migrate, etc.
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
        """Mark operation as started."""
        self.status = ReplicaOperationStatus.IN_PROGRESS
        self.started_at = datetime.now(timezone.utc)
    
    def complete_operation(self, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark operation as completed."""
        self.status = ReplicaOperationStatus.COMPLETED
        self.completed_at = datetime.now(timezone.utc)
        self.result = result
    
    def fail_operation(self, error_message: str) -> None:
        """Mark operation as failed."""
        self.status = ReplicaOperationStatus.FAILED
        self.completed_at = datetime.now(timezone.utc)
        self.error_message = error_message
    
    def cancel_operation(self) -> None:
        """Mark operation as cancelled."""
        self.status = ReplicaOperationStatus.CANCELLED
        self.completed_at = datetime.now(timezone.utc)
    
    def get_duration(self) -> Optional[float]:
        """Get operation duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert operation to dictionary representation."""
        return {
            "operation_id": str(self.operation_id),
            "operation_type": self.operation_type,
            "replica_id": str(self.replica_id),
            "status": safe_enum_value(self.status),
            "parameters": self.parameters,
            "requester_id": str(self.requester_id) if self.requester_id else None,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.get_duration(),
            "error_message": self.error_message,
            "result": self.result
        }


class ReplicaHealthStatus(Enum):
    """Health status of Digital Replicas."""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class ReplicaHealthCheck:
    """Health check result for a Digital Replica."""
    
    def __init__(
        self,
        replica_id: UUID,
        status: ReplicaHealthStatus,
        last_check: datetime,
        checks: Dict[str, bool],
        metrics: Dict[str, float],
        issues: List[str]
    ):
        self.replica_id = replica_id
        self.status = status
        self.last_check = last_check
        self.checks = checks  # connectivity, data_flow, performance, etc.
        self.metrics = metrics  # response_time, memory_usage, cpu_usage, etc.
        self.issues = issues
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert health check to dictionary representation."""
        return {
            "replica_id": str(self.replica_id),
            "status": safe_enum_value(self.status),
            "last_check": self.last_check.isoformat(),
            "checks": self.checks,
            "metrics": self.metrics,
            "issues": self.issues
        }


class ReplicaDeploymentTarget:
    """Represents a deployment target for Digital Replicas."""
    
    def __init__(
        self,
        target_id: str,
        target_type: str,  # container, edge_device, cloud_instance
        capacity: Dict[str, Any],
        location: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.target_id = target_id
        self.target_type = target_type
        self.capacity = capacity
        self.location = location
        self.metadata = metadata or {}
        self.deployed_replicas: Set[UUID] = set()
    
    def can_deploy(self, replica_requirements: Dict[str, Any]) -> bool:
        """Check if this target can deploy a replica with given requirements."""
        # Simple capacity check
        required_memory = replica_requirements.get("memory", 0)
        required_cpu = replica_requirements.get("cpu", 0)
        
        available_memory = self.capacity.get("memory", 0) - self.get_used_memory()
        available_cpu = self.capacity.get("cpu", 0) - self.get_used_cpu()
        
        return available_memory >= required_memory and available_cpu >= required_cpu
    
    def get_used_memory(self) -> float:
        """Get currently used memory."""
        # Simplified calculation
        return len(self.deployed_replicas) * 100  # 100MB per replica
    
    def get_used_cpu(self) -> float:
        """Get currently used CPU."""
        # Simplified calculation
        return len(self.deployed_replicas) * 0.1  # 0.1 CPU units per replica
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert deployment target to dictionary representation."""
        return {
            "target_id": self.target_id,
            "target_type": self.target_type,
            "capacity": self.capacity,
            "location": self.location,
            "metadata": self.metadata,
            "deployed_replicas": len(self.deployed_replicas),
            "used_memory": self.get_used_memory(),
            "used_cpu": self.get_used_cpu()
        }


class DigitalReplicaLifecycleManager(IReplicaLifecycleManager):
    """Lifecycle manager for Digital Replicas."""
    
    def __init__(
        self,
        factory: IReplicaFactory,
        registry: Any,  # DigitalReplicaRegistry
        orchestrator: Optional['ReplicaOrchestrator'] = None
    ):
        self.factory = factory
        self.registry = registry
        self.orchestrator = orchestrator
        self.config = get_config()
        
        # Operation tracking
        self.operations: Dict[UUID, ReplicaOperation] = {}
        self.operation_lock = asyncio.Lock()
        
        # Health monitoring
        self.health_checks: Dict[UUID, ReplicaHealthCheck] = {}
        self.health_check_interval = 60  # seconds
        self.health_check_task: Optional[asyncio.Task] = None
        
        # Deployment targets
        self.deployment_targets: Dict[str, ReplicaDeploymentTarget] = {}
        self.replica_deployments: Dict[UUID, str] = {}  # replica_id -> target_id
    
    async def create_entity(
        self,
        config: Dict[str, Any],
        metadata: Optional[BaseMetadata] = None
    ) -> IDigitalReplica:
        """Create a new Digital Replica entity."""
        operation_id = uuid4()
        operation = ReplicaOperation(
            operation_id=operation_id,
            operation_type="create",
            replica_id=uuid4(),  # Will be updated with actual ID
            parameters=config
        )
        
        async with self.operation_lock:
            self.operations[operation_id] = operation
        
        try:
            operation.start_operation()
            
            # Create replica using factory
            replica = await self.factory.create(config, metadata)
            
            # Update operation with actual replica ID
            operation.replica_id = replica.id
            
            # Register replica
            await self.registry.register_digital_replica(replica)
            
            # Initialize replica
            await replica.initialize()
            
            operation.complete_operation({"replica_id": str(replica.id)})
            logger.info(f"Successfully created Digital Replica {replica.id}")
            
            return replica
            
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f"Failed to create Digital Replica: {e}")
            raise EntityCreationError(f"Digital Replica creation failed: {e}")
    
    async def start_entity(self, entity_id: UUID) -> None:
        """Start a Digital Replica entity."""
        operation_id = uuid4()
        operation = ReplicaOperation(
            operation_id=operation_id,
            operation_type="start",
            replica_id=entity_id,
            parameters={}
        )
        
        async with self.operation_lock:
            self.operations[operation_id] = operation
        
        try:
            operation.start_operation()
            
            # Get replica
            replica = await self.registry.get_digital_replica(entity_id)
            
            # Start replica
            await replica.start()
            
            operation.complete_operation()
            logger.info(f"Successfully started Digital Replica {entity_id}")
            
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f"Failed to start Digital Replica {entity_id}: {e}")
            raise DigitalReplicaError(f"Failed to start replica: {e}")
    
    async def stop_entity(self, entity_id: UUID) -> None:
        """Stop a Digital Replica entity."""
        operation_id = uuid4()
        operation = ReplicaOperation(
            operation_id=operation_id,
            operation_type="stop",
            replica_id=entity_id,
            parameters={}
        )
        
        async with self.operation_lock:
            self.operations[operation_id] = operation
        
        try:
            operation.start_operation()
            
            # Get replica
            replica = await self.registry.get_digital_replica(entity_id)
            
            # Stop replica
            await replica.stop()
            
            operation.complete_operation()
            logger.info(f"Successfully stopped Digital Replica {entity_id}")
            
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f"Failed to stop Digital Replica {entity_id}: {e}")
            raise DigitalReplicaError(f"Failed to stop replica: {e}")
    
    async def restart_entity(self, entity_id: UUID) -> None:
        """Restart a Digital Replica entity."""
        await self.stop_entity(entity_id)
        await asyncio.sleep(1)  # Brief pause
        await self.start_entity(entity_id)
    
    async def terminate_entity(self, entity_id: UUID) -> None:
        """Terminate a Digital Replica entity."""
        operation_id = uuid4()
        operation = ReplicaOperation(
            operation_id=operation_id,
            operation_type="terminate",
            replica_id=entity_id,
            parameters={}
        )
        
        async with self.operation_lock:
            self.operations[operation_id] = operation
        
        try:
            operation.start_operation()
            
            # Get replica
            replica = await self.registry.get_digital_replica(entity_id)
            
            # Terminate replica
            await replica.terminate()
            
            # Remove from deployment if deployed
            if entity_id in self.replica_deployments:
                target_id = self.replica_deployments[entity_id]
                if target_id in self.deployment_targets:
                    self.deployment_targets[target_id].deployed_replicas.discard(entity_id)
                del self.replica_deployments[entity_id]
            
            # Unregister replica
            await self.registry.unregister(entity_id)
            
            # Remove health check
            if entity_id in self.health_checks:
                del self.health_checks[entity_id]
            
            operation.complete_operation()
            logger.info(f"Successfully terminated Digital Replica {entity_id}")
            
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f"Failed to terminate Digital Replica {entity_id}: {e}")
            raise DigitalReplicaError(f"Failed to terminate replica: {e}")
    
    async def get_entity_status(self, entity_id: UUID) -> EntityStatus:
        """Get the current status of a Digital Replica entity."""
        try:
            replica = await self.registry.get_digital_replica(entity_id)
            return replica.status
        except DigitalReplicaNotFoundError:
            return EntityStatus.TERMINATED
    
    async def monitor_entity(self, entity_id: UUID) -> Dict[str, Any]:
        """Get monitoring information for a Digital Replica entity."""
        try:
            replica = await self.registry.get_digital_replica(entity_id)
            
            # Get basic monitoring info
            monitoring_data = {
                "replica_id": str(entity_id),
                "status": safe_enum_value(replica.status),
                "type": safe_enum_value(replica.replica_type),
                "aggregation_mode": safe_enum_value(replica.aggregation_mode),
                "device_count": len(replica.device_ids),
                "parent_digital_twin_id": str(replica.parent_digital_twin_id)
            }
            
            # Add health check data
            if entity_id in self.health_checks:
                monitoring_data["health_check"] = self.health_checks[entity_id].to_dict()
            
            # Add deployment info
            if entity_id in self.replica_deployments:
                target_id = self.replica_deployments[entity_id]
                monitoring_data["deployment_target"] = target_id
                if target_id in self.deployment_targets:
                    monitoring_data["deployment_info"] = self.deployment_targets[target_id].to_dict()
            
            # Add performance metrics
            try:
                performance = await self.registry.get_replica_performance(entity_id)
                monitoring_data["performance"] = performance
            except Exception as e:
                monitoring_data["performance_error"] = str(e)
            
            return monitoring_data
            
        except DigitalReplicaNotFoundError:
            return {"error": f"Replica {entity_id} not found"}
    
    async def deploy_replica(
        self,
        replica: IDigitalReplica,
        deployment_target: str
    ) -> str:
        """Deploy a replica to a specific target."""
        operation_id = uuid4()
        operation = ReplicaOperation(
            operation_id=operation_id,
            operation_type="deploy",
            replica_id=replica.id,
            parameters={"deployment_target": deployment_target}
        )
        
        async with self.operation_lock:
            self.operations[operation_id] = operation
        
        try:
            operation.start_operation()
            
            # Check if target exists and has capacity
            if deployment_target not in self.deployment_targets:
                raise DigitalReplicaError(f"Deployment target {deployment_target} not found")
            
            target = self.deployment_targets[deployment_target]
            replica_requirements = {
                "memory": 100,  # MB
                "cpu": 0.1     # CPU units
            }
            
            if not target.can_deploy(replica_requirements):
                raise DigitalReplicaError(f"Deployment target {deployment_target} has insufficient capacity")
            
            # Deploy replica (in a real implementation, this would interact with container orchestrator)
            deployment_id = f"deployment-{replica.id}-{deployment_target}"
            
            # Track deployment
            target.deployed_replicas.add(replica.id)
            self.replica_deployments[replica.id] = deployment_target
            
            operation.complete_operation({"deployment_id": deployment_id})
            logger.info(f"Successfully deployed replica {replica.id} to {deployment_target}")
            
            return deployment_id
            
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f"Failed to deploy replica {replica.id}: {e}")
            raise DigitalReplicaError(f"Deployment failed: {e}")
    
    async def scale_replica(
        self,
        replica_id: UUID,
        scale_factor: int
    ) -> None:
        """Scale a replica horizontally."""
        operation_id = uuid4()
        operation = ReplicaOperation(
            operation_id=operation_id,
            operation_type="scale",
            replica_id=replica_id,
            parameters={"scale_factor": scale_factor}
        )
        
        async with self.operation_lock:
            self.operations[operation_id] = operation
        
        try:
            operation.start_operation()
            
            # Get original replica
            original_replica = await self.registry.get_digital_replica(replica_id)
            
            if scale_factor > 1:
                # Scale up - create additional replica instances
                for i in range(scale_factor - 1):
                    # Create new configuration
                    config = {
                        "replica_type": safe_enum_value(original_replica.replica_type),
                        "parent_digital_twin_id": str(original_replica.parent_digital_twin_id),
                        "device_ids": original_replica.device_ids.copy(),
                        "aggregation_mode": safe_enum_value(original_replica.aggregation_mode),
                        "aggregation_config": original_replica.configuration.aggregation_config,
                        "data_retention_policy": original_replica.configuration.data_retention_policy,
                        "quality_thresholds": original_replica.configuration.quality_thresholds
                    }
                    
                    # Create scaled replica
                    scaled_replica = await self.factory.create(config)
                    await self.registry.register_digital_replica(scaled_replica)
                    await scaled_replica.initialize()
                    await scaled_replica.start()
                    
                    logger.info(f"Created scaled replica {scaled_replica.id} from {replica_id}")
            
            operation.complete_operation({"scale_factor": scale_factor})
            logger.info(f"Successfully scaled replica {replica_id} by factor {scale_factor}")
            
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f"Failed to scale replica {replica_id}: {e}")
            raise DigitalReplicaError(f"Scaling failed: {e}")
    
    async def migrate_replica(
        self,
        replica_id: UUID,
        target_location: str
    ) -> None:
        """Migrate a replica to a different location or host."""
        operation_id = uuid4()
        operation = ReplicaOperation(
            operation_id=operation_id,
            operation_type="migrate",
            replica_id=replica_id,
            parameters={"target_location": target_location}
        )
        
        async with self.operation_lock:
            self.operations[operation_id] = operation
        
        try:
            operation.start_operation()
            
            # Get replica
            replica = await self.registry.get_digital_replica(replica_id)
            
            # Create snapshot for migration
            snapshot = await replica.create_snapshot()
            
            # Stop current replica
            await replica.stop()
            
            # Deploy to new location (simplified)
            if target_location in self.deployment_targets:
                await self.deploy_replica(replica, target_location)
            
            # Start replica at new location
            await replica.start()
            
            operation.complete_operation({"snapshot_id": str(snapshot.twin_id)})
            logger.info(f"Successfully migrated replica {replica_id} to {target_location}")
            
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f"Failed to migrate replica {replica_id}: {e}")
            raise DigitalReplicaError(f"Migration failed: {e}")
    
    async def backup_replica_state(self, replica_id: UUID) -> str:
        """Create a backup of the replica's current state."""
        try:
            replica = await self.registry.get_digital_replica(replica_id)
            snapshot = await replica.create_snapshot()
            
            # In a real implementation, this would store the snapshot
            backup_reference = f"backup-{replica_id}-{datetime.now(timezone.utc).isoformat()}"
            
            logger.info(f"Created backup {backup_reference} for replica {replica_id}")
            return backup_reference
            
        except Exception as e:
            logger.error(f"Failed to backup replica {replica_id}: {e}")
            raise DigitalReplicaError(f"Backup failed: {e}")
    
    async def restore_replica_state(
        self,
        replica_id: UUID,
        backup_reference: str
    ) -> None:
        """Restore a replica from a previous backup."""
        try:
            replica = await self.registry.get_digital_replica(replica_id)
            
            # In a real implementation, this would load and restore the snapshot
            logger.info(f"Restored replica {replica_id} from backup {backup_reference}")
            
        except Exception as e:
            logger.error(f"Failed to restore replica {replica_id}: {e}")
            raise DigitalReplicaError(f"Restore failed: {e}")
    
    async def add_deployment_target(self, target: ReplicaDeploymentTarget) -> None:
        """Add a new deployment target."""
        self.deployment_targets[target.target_id] = target
        logger.info(f"Added deployment target {target.target_id}")
    
    async def remove_deployment_target(self, target_id: str) -> None:
        """Remove a deployment target."""
        if target_id in self.deployment_targets:
            target = self.deployment_targets[target_id]
            
            # Check if any replicas are deployed
            if target.deployed_replicas:
                raise DigitalReplicaError(
                    f"Cannot remove target {target_id}: {len(target.deployed_replicas)} replicas deployed"
                )
            
            del self.deployment_targets[target_id]
            logger.info(f"Removed deployment target {target_id}")
    
    async def perform_health_check(self, replica_id: UUID) -> ReplicaHealthCheck:
        """Perform a health check on a specific replica."""
        try:
            replica = await self.registry.get_digital_replica(replica_id)
            
            # Perform various health checks
            checks = {}
            metrics = {}
            issues = []
            
            # Check replica status
            checks["status_check"] = replica.status in [EntityStatus.ACTIVE, EntityStatus.INACTIVE]
            if not checks["status_check"]:
                issues.append(f"Replica status is {safe_enum_value(replica.status)}")
            # Check data flow
            performance = await self.registry.get_replica_performance(replica_id)
            data_received = performance.get("total_data_received", 0)
            checks["data_flow"] = data_received > 0
            if not checks["data_flow"]:
                issues.append("No data received")
            
            # Mock performance metrics
            metrics["response_time"] = 0.1  # seconds
            metrics["memory_usage"] = 50.0  # MB
            metrics["cpu_usage"] = 5.0      # percentage
            
            # Determine overall health status
            failed_checks = sum(1 for check in checks.values() if not check)
            if failed_checks == 0:
                status = ReplicaHealthStatus.HEALTHY
            elif failed_checks <= 1:
                status = ReplicaHealthStatus.WARNING
            else:
                status = ReplicaHealthStatus.CRITICAL
            
            health_check = ReplicaHealthCheck(
                replica_id=replica_id,
                status=status,
                last_check=datetime.now(timezone.utc),
                checks=checks,
                metrics=metrics,
                issues=issues
            )
            
            self.health_checks[replica_id] = health_check
            return health_check
            
        except Exception as e:
            logger.error(f"Health check failed for replica {replica_id}: {e}")
            return ReplicaHealthCheck(
                replica_id=replica_id,
                status=ReplicaHealthStatus.UNKNOWN,
                last_check=datetime.now(timezone.utc),
                checks={},
                metrics={},
                issues=[str(e)]
            )
    
    async def start_health_monitoring(self) -> None:
        """Start periodic health monitoring for all replicas."""
        async def health_monitor():
            while True:
                try:
                    # Get all registered replicas
                    replicas = await self.registry.list()
                    
                    # Perform health checks
                    for replica in replicas:
                        await self.perform_health_check(replica.id)
                    
                    # Wait for next check
                    await asyncio.sleep(self.health_check_interval)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Health monitoring error: {e}")
                    await asyncio.sleep(self.health_check_interval)
        
        if self.health_check_task is None or self.health_check_task.done():
            self.health_check_task = asyncio.create_task(health_monitor())
            logger.info("Started health monitoring")
    
    async def stop_health_monitoring(self) -> None:
        """Stop periodic health monitoring."""
        if self.health_check_task and not self.health_check_task.done():
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass
            logger.info("Stopped health monitoring")
    
    async def get_operation_status(self, operation_id: UUID) -> Optional[ReplicaOperation]:
        """Get the status of a specific operation."""
        return self.operations.get(operation_id)
    
    async def get_replica_operations(
        self,
        replica_id: UUID,
        limit: Optional[int] = None
    ) -> List[ReplicaOperation]:
        """Get operations for a specific replica."""
        operations = [
            op for op in self.operations.values()
            if op.replica_id == replica_id
        ]
        
        # Sort by creation time (most recent first)
        operations.sort(key=lambda op: op.created_at, reverse=True)
        
        if limit:
            operations = operations[:limit]
        
        return operations
    
    async def get_management_statistics(self) -> Dict[str, Any]:
        """Get comprehensive management statistics."""
        replicas = await self.registry.list()
        
        # Operation statistics
        operation_stats = {}
        for op_type in ["create", "start", "stop", "deploy", "scale", "migrate"]:
            ops = [op for op in self.operations.values() if op.operation_type == op_type]
            operation_stats[op_type] = {
                "total": len(ops),
                "completed": len([op for op in ops if op.status == ReplicaOperationStatus.COMPLETED]),
                "failed": len([op for op in ops if op.status == ReplicaOperationStatus.FAILED]),
                "pending": len([op for op in ops if op.status == ReplicaOperationStatus.PENDING])
            }
        
        # Health statistics
        health_stats = {}
        for status in ReplicaHealthStatus:
            health_stats[safe_enum_value(status.status)] = len([
                hc for hc in self.health_checks.values()
                if hc.status == status
            ])
        
        # Deployment statistics
        deployment_stats = {
            "total_targets": len(self.deployment_targets),
            "deployed_replicas": len(self.replica_deployments),
            "target_utilization": {}
        }
        
        for target_id, target in self.deployment_targets.items():
            utilization = len(target.deployed_replicas) / max(target.capacity.get("max_replicas", 10), 1)
            deployment_stats["target_utilization"][target_id] = utilization
        
        return {
            "total_replicas": len(replicas),
            "operation_statistics": operation_stats,
            "health_statistics": health_stats,
            "deployment_statistics": deployment_stats,
            "health_monitoring_active": self.health_check_task is not None and not self.health_check_task.done()
        }