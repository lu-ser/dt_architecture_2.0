"""
Service Management Module for the Digital Twin Platform.

This module provides comprehensive lifecycle management for Services,
including creation, deployment, orchestration, scaling, and monitoring.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple, Callable
from uuid import UUID, uuid4
from enum import Enum

from src.core.interfaces.base import BaseMetadata, EntityStatus
from src.core.interfaces.service import (
    IService,
    IServiceFactory,
    IServiceLifecycleManager,
    IServiceOrchestrator,
    ServiceType,
    ServiceDefinition,
    ServiceConfiguration,
    ServiceState,
    ServicePriority,
    ServiceRequest,
    ServiceResponse
)
from src.utils.exceptions import (
    ServiceError,
    ServiceNotFoundError,
    ServiceConfigurationError,
    EntityCreationError
)
from src.utils.config import get_config

logger = logging.getLogger(__name__)


class ServiceOperationStatus(Enum):
    """Status of service operations."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ServiceOperation:
    """Represents an operation performed on a Service."""
    
    def __init__(
        self,
        operation_id: UUID,
        operation_type: str,
        service_id: UUID,
        parameters: Dict[str, Any],
        requester_id: Optional[UUID] = None
    ):
        self.operation_id = operation_id
        self.operation_type = operation_type  # create, start, stop, scale, deploy, etc.
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
        """Mark operation as started."""
        self.status = ServiceOperationStatus.IN_PROGRESS
        self.started_at = datetime.now(timezone.utc)
    
    def complete_operation(self, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark operation as completed."""
        self.status = ServiceOperationStatus.COMPLETED
        self.completed_at = datetime.now(timezone.utc)
        self.result = result
    
    def fail_operation(self, error_message: str) -> None:
        """Mark operation as failed."""
        self.status = ServiceOperationStatus.FAILED
        self.completed_at = datetime.now(timezone.utc)
        self.error_message = error_message
    
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
            "service_id": str(self.service_id),
            "status": self.status.value,
            "parameters": self.parameters,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.get_duration(),
            "error_message": self.error_message,
            "result": self.result
        }


class ServiceHealthStatus(Enum):
    """Health status of Services."""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class ServiceHealthCheck:
    """Health check result for a Service."""
    
    def __init__(
        self,
        service_id: UUID,
        status: ServiceHealthStatus,
        last_check: datetime,
        checks: Dict[str, bool],
        metrics: Dict[str, float],
        issues: List[str]
    ):
        self.service_id = service_id
        self.status = status
        self.last_check = last_check
        self.checks = checks  # state_check, performance_check, dependency_check
        self.metrics = metrics  # response_time, memory_usage, success_rate
        self.issues = issues
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert health check to dictionary representation."""
        return {
            "service_id": str(self.service_id),
            "status": self.status.value,
            "last_check": self.last_check.isoformat(),
            "checks": self.checks,
            "metrics": self.metrics,
            "issues": self.issues
        }


class ServiceDeploymentTarget:
    """Represents a deployment target for Services."""
    
    def __init__(
        self,
        target_id: str,
        target_type: str,  # container, serverless, cloud_instance, edge_device
        capacity: Dict[str, Any],
        location: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.target_id = target_id
        self.target_type = target_type
        self.capacity = capacity
        self.location = location
        self.metadata = metadata or {}
        self.deployed_services: Set[UUID] = set()
    
    def can_deploy(self, service_requirements: Dict[str, Any]) -> bool:
        """Check if this target can deploy a service with given requirements."""
        required_memory = service_requirements.get("memory_mb", 0)
        required_cpu = service_requirements.get("cpu_cores", 0)
        
        available_memory = self.capacity.get("memory_mb", 0) - self.get_used_memory()
        available_cpu = self.capacity.get("cpu_cores", 0) - self.get_used_cpu()
        
        return available_memory >= required_memory and available_cpu >= required_cpu
    
    def get_used_memory(self) -> float:
        """Get currently used memory."""
        return len(self.deployed_services) * 256  # 256MB per service
    
    def get_used_cpu(self) -> float:
        """Get currently used CPU."""
        return len(self.deployed_services) * 0.5  # 0.5 CPU units per service
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert deployment target to dictionary representation."""
        return {
            "target_id": self.target_id,
            "target_type": self.target_type,
            "capacity": self.capacity,
            "location": self.location,
            "metadata": self.metadata,
            "deployed_services": len(self.deployed_services),
            "used_memory_mb": self.get_used_memory(),
            "used_cpu_cores": self.get_used_cpu()
        }


class ServiceWorkflow:
    """Represents a service workflow."""
    
    def __init__(
        self,
        workflow_id: UUID,
        name: str,
        digital_twin_id: UUID,
        service_chain: List[Dict[str, Any]],
        workflow_config: Dict[str, Any]
    ):
        self.workflow_id = workflow_id
        self.name = name
        self.digital_twin_id = digital_twin_id
        self.service_chain = service_chain
        self.workflow_config = workflow_config
        self.created_at = datetime.now(timezone.utc)
        self.status = "created"
        self.execution_history: List[Dict[str, Any]] = []
        self.current_execution_id: Optional[UUID] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert workflow to dictionary representation."""
        return {
            "workflow_id": str(self.workflow_id),
            "name": self.name,
            "digital_twin_id": str(self.digital_twin_id),
            "service_chain": self.service_chain,
            "workflow_config": self.workflow_config,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
            "execution_count": len(self.execution_history),
            "current_execution_id": str(self.current_execution_id) if self.current_execution_id else None
        }


class ServiceLifecycleManager(IServiceLifecycleManager):
    """Lifecycle manager for Services."""
    
    def __init__(
        self,
        factory: IServiceFactory,
        registry: Any,  # ServiceRegistry
        orchestrator: Optional['ServiceOrchestrator'] = None
    ):
        self.factory = factory
        self.registry = registry
        self.orchestrator = orchestrator
        self.config = get_config()
        
        # Operation tracking
        self.operations: Dict[UUID, ServiceOperation] = {}
        self.operation_lock = asyncio.Lock()
        
        # Health monitoring
        self.health_checks: Dict[UUID, ServiceHealthCheck] = {}
        self.health_check_interval = 60  # seconds
        self.health_check_task: Optional[asyncio.Task] = None
        
        # Deployment targets
        self.deployment_targets: Dict[str, ServiceDeploymentTarget] = {}
        self.service_deployments: Dict[UUID, str] = {}  # service_id -> target_id
        
        # Auto-scaling
        self.auto_scaling_configs: Dict[UUID, Dict[str, Any]] = {}
        self.scaling_lock = asyncio.Lock()
    
    async def create_entity(
        self,
        config: Dict[str, Any],
        metadata: Optional[BaseMetadata] = None
    ) -> IService:
        """Create a new Service entity."""
        operation_id = uuid4()
        operation = ServiceOperation(
            operation_id=operation_id,
            operation_type="create",
            service_id=uuid4(),  # Will be updated with actual ID
            parameters=config
        )
        
        async with self.operation_lock:
            self.operations[operation_id] = operation
        
        try:
            operation.start_operation()
            
            # Create service using factory
            service = await self.factory.create(config, metadata)
            
            # Update operation with actual service ID
            operation.service_id = service.id
            
            # Register service
            await self.registry.register_service(service)
            
            # Initialize service
            await service.initialize()
            
            operation.complete_operation({"service_id": str(service.id)})
            logger.info(f"Successfully created Service {service.id}")
            
            return service
            
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f"Failed to create Service: {e}")
            raise EntityCreationError(f"Service creation failed: {e}")
    
    async def start_entity(self, entity_id: UUID) -> None:
        """Start a Service entity."""
        await self._execute_service_operation("start", entity_id, {})
    
    async def stop_entity(self, entity_id: UUID) -> None:
        """Stop a Service entity."""
        await self._execute_service_operation("stop", entity_id, {})
    
    async def restart_entity(self, entity_id: UUID) -> None:
        """Restart a Service entity."""
        await self.stop_entity(entity_id)
        await asyncio.sleep(1)  # Brief pause
        await self.start_entity(entity_id)
    
    async def terminate_entity(self, entity_id: UUID) -> None:
        """Terminate a Service entity."""
        operation_id = uuid4()
        operation = ServiceOperation(
            operation_id=operation_id,
            operation_type="terminate",
            service_id=entity_id,
            parameters={}
        )
        
        async with self.operation_lock:
            self.operations[operation_id] = operation
        
        try:
            operation.start_operation()
            
            # Get service
            service = await self.registry.get_service(entity_id)
            
            # Terminate service
            await service.terminate()
            
            # Remove from deployment if deployed
            if entity_id in self.service_deployments:
                target_id = self.service_deployments[entity_id]
                if target_id in self.deployment_targets:
                    self.deployment_targets[target_id].deployed_services.discard(entity_id)
                del self.service_deployments[entity_id]
            
            # Remove auto-scaling config
            if entity_id in self.auto_scaling_configs:
                del self.auto_scaling_configs[entity_id]
            
            # Unregister service
            await self.registry.unregister(entity_id)
            
            # Remove health check
            if entity_id in self.health_checks:
                del self.health_checks[entity_id]
            
            operation.complete_operation()
            logger.info(f"Successfully terminated Service {entity_id}")
            
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f"Failed to terminate Service {entity_id}: {e}")
            raise ServiceError(f"Failed to terminate service: {e}")
    
    async def get_entity_status(self, entity_id: UUID) -> EntityStatus:
        """Get the current status of a Service entity."""
        try:
            service = await self.registry.get_service(entity_id)
            return service.status
        except ServiceNotFoundError:
            return EntityStatus.TERMINATED
    
    async def monitor_entity(self, entity_id: UUID) -> Dict[str, Any]:
        """Get monitoring information for a Service entity."""
        try:
            service = await self.registry.get_service(entity_id)
            
            # Get basic monitoring info
            monitoring_data = {
                "service_id": str(entity_id),
                "status": service.status.value,
                "current_state": service.current_state.value,
                "service_type": service.service_type.value,
                "digital_twin_id": str(service.digital_twin_id),
                "capabilities": list(service.capabilities)
            }
            
            # Add health check data
            if entity_id in self.health_checks:
                monitoring_data["health_check"] = self.health_checks[entity_id].to_dict()
            
            # Add deployment info
            if entity_id in self.service_deployments:
                target_id = self.service_deployments[entity_id]
                monitoring_data["deployment_target"] = target_id
                if target_id in self.deployment_targets:
                    monitoring_data["deployment_info"] = self.deployment_targets[target_id].to_dict()
            
            # Add performance metrics
            try:
                performance = await self.registry.get_service_performance(entity_id)
                monitoring_data["performance"] = performance
            except Exception as e:
                monitoring_data["performance_error"] = str(e)
            
            # Add auto-scaling info
            if entity_id in self.auto_scaling_configs:
                monitoring_data["auto_scaling"] = self.auto_scaling_configs[entity_id]
            
            return monitoring_data
            
        except ServiceNotFoundError:
            return {"error": f"Service {entity_id} not found"}
    
    async def deploy_service(
        self,
        service: IService,
        deployment_target: str,
        deployment_config: Dict[str, Any]
    ) -> str:
        """Deploy a service to a specific target."""
        operation_id = uuid4()
        operation = ServiceOperation(
            operation_id=operation_id,
            operation_type="deploy",
            service_id=service.id,
            parameters={"deployment_target": deployment_target, "deployment_config": deployment_config}
        )
        
        async with self.operation_lock:
            self.operations[operation_id] = operation
        
        try:
            operation.start_operation()
            
            # Check if target exists and has capacity
            if deployment_target not in self.deployment_targets:
                raise ServiceError(f"Deployment target {deployment_target} not found")
            
            target = self.deployment_targets[deployment_target]
            
            # Get service resource requirements
            service_requirements = {
                "memory_mb": deployment_config.get("memory_mb", 256),
                "cpu_cores": deployment_config.get("cpu_cores", 0.5)
            }
            
            if not target.can_deploy(service_requirements):
                raise ServiceError(f"Deployment target {deployment_target} has insufficient capacity")
            
            # Deploy service
            deployment_id = f"deployment-{service.id}-{deployment_target}"
            
            # Track deployment
            target.deployed_services.add(service.id)
            self.service_deployments[service.id] = deployment_target
            
            operation.complete_operation({"deployment_id": deployment_id})
            logger.info(f"Successfully deployed service {service.id} to {deployment_target}")
            
            return deployment_id
            
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f"Failed to deploy service {service.id}: {e}")
            raise ServiceError(f"Deployment failed: {e}")
    
    async def scale_service(
        self,
        service_id: UUID,
        target_instances: int,
        scaling_strategy: str = "gradual"
    ) -> None:
        """Scale a service horizontally."""
        async with self.scaling_lock:
            operation_id = uuid4()
            operation = ServiceOperation(
                operation_id=operation_id,
                operation_type="scale",
                service_id=service_id,
                parameters={"target_instances": target_instances, "scaling_strategy": scaling_strategy}
            )
            
            async with self.operation_lock:
                self.operations[operation_id] = operation
            
            try:
                operation.start_operation()
                
                # Get original service
                original_service = await self.registry.get_service(service_id)
                
                if target_instances > 1:
                    # Scale up - create additional service instances
                    for i in range(target_instances - 1):
                        # Create scaled service configuration
                        config = {
                            "service_definition_id": original_service.service_definition_id,
                            "instance_name": f"{original_service.instance_name}-scale-{i+1}",
                            "digital_twin_id": str(original_service.digital_twin_id),
                            "parameters": original_service.configuration.parameters,
                            "execution_config": original_service.configuration.execution_config,
                            "resource_limits": original_service.configuration.resource_limits,
                            "priority": original_service.configuration.priority.value
                        }
                        
                        # Create scaled service
                        scaled_service = await self.factory.create(config)
                        await self.registry.register_service(scaled_service)
                        await scaled_service.initialize()
                        await scaled_service.start()
                        
                        logger.info(f"Created scaled service {scaled_service.id} from {service_id}")
                
                operation.complete_operation({"target_instances": target_instances})
                logger.info(f"Successfully scaled service {service_id} to {target_instances} instances")
                
            except Exception as e:
                operation.fail_operation(str(e))
                logger.error(f"Failed to scale service {service_id}: {e}")
                raise ServiceError(f"Scaling failed: {e}")
    
    async def update_service(
        self,
        service_id: UUID,
        new_definition: ServiceDefinition,
        update_strategy: str = "rolling"
    ) -> None:
        """Update a service to a new definition."""
        operation_id = uuid4()
        operation = ServiceOperation(
            operation_id=operation_id,
            operation_type="update",
            service_id=service_id,
            parameters={"new_definition_id": new_definition.definition_id, "update_strategy": update_strategy}
        )
        
        async with self.operation_lock:
            self.operations[operation_id] = operation
        
        try:
            operation.start_operation()
            
            # Get current service
            service = await self.registry.get_service(service_id)
            
            # Create new configuration
            new_config = ServiceConfiguration(
                service_definition_id=new_definition.definition_id,
                instance_name=service.instance_name,
                digital_twin_id=service.digital_twin_id,
                parameters=service.configuration.parameters,
                execution_config=service.configuration.execution_config,
                resource_limits=service.configuration.resource_limits,
                priority=service.configuration.priority
            )
            
            # Update service configuration
            await service.update_configuration(new_config)
            
            operation.complete_operation({"new_definition_id": new_definition.definition_id})
            logger.info(f"Successfully updated service {service_id}")
            
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f"Failed to update service {service_id}: {e}")
            raise ServiceError(f"Update failed: {e}")
    
    async def rollback_service(
        self,
        service_id: UUID,
        target_version: Optional[str] = None
    ) -> None:
        """Rollback a service to a previous version."""
        # This would require versioning support in the service definitions
        # For now, we'll just log the operation
        logger.info(f"Rollback requested for service {service_id} to version {target_version or 'previous'}")
    
    async def get_service_instances(
        self,
        digital_twin_id: Optional[UUID] = None,
        service_type: Optional[ServiceType] = None
    ) -> List[IService]:
        """Get service instances with optional filtering."""
        criteria = {}
        
        if digital_twin_id:
            criteria["digital_twin_id"] = str(digital_twin_id)
        if service_type:
            criteria["type"] = service_type.value
        
        return await self.registry.discover_services(criteria)
    
    async def add_deployment_target(self, target: ServiceDeploymentTarget) -> None:
        """Add a new deployment target."""
        self.deployment_targets[target.target_id] = target
        logger.info(f"Added deployment target {target.target_id}")
    
    async def remove_deployment_target(self, target_id: str) -> None:
        """Remove a deployment target."""
        if target_id in self.deployment_targets:
            target = self.deployment_targets[target_id]
            
            # Check if any services are deployed
            if target.deployed_services:
                raise ServiceError(
                    f"Cannot remove target {target_id}: {len(target.deployed_services)} services deployed"
                )
            
            del self.deployment_targets[target_id]
            logger.info(f"Removed deployment target {target_id}")
    
    async def configure_auto_scaling(
        self,
        service_id: UUID,
        auto_scaling_config: Dict[str, Any]
    ) -> None:
        """Configure auto-scaling for a service."""
        self.auto_scaling_configs[service_id] = auto_scaling_config
        logger.info(f"Configured auto-scaling for service {service_id}")
    
    async def perform_health_check(self, service_id: UUID) -> ServiceHealthCheck:
        """Perform a health check on a specific service."""
        try:
            service = await self.registry.get_service(service_id)
            
            # Perform various health checks
            checks = {}
            metrics = {}
            issues = []
            
            # Check service state
            checks["state_check"] = service.current_state in [ServiceState.READY, ServiceState.IDLE]
            if not checks["state_check"]:
                issues.append(f"Service state is {service.current_state.value}")
            
            # Check service status
            checks["status_check"] = service.status == EntityStatus.ACTIVE
            if not checks["status_check"]:
                issues.append(f"Service status is {service.status.value}")
            
            # Get service metrics
            service_metrics = await service.get_metrics()
            metrics["success_rate"] = service_metrics.get("success_rate", 0.0)
            metrics["average_response_time"] = service_metrics.get("average_response_time", 0.0)
            metrics["error_count"] = service_metrics.get("error_count", 0)
            
            # Check performance
            checks["performance_check"] = metrics["success_rate"] > 0.8 and metrics["average_response_time"] < 5.0
            if not checks["performance_check"]:
                issues.append(f"Poor performance: success_rate={metrics['success_rate']:.2f}, response_time={metrics['average_response_time']:.2f}s")
            
            # Determine overall health status
            failed_checks = sum(1 for check in checks.values() if not check)
            if failed_checks == 0:
                status = ServiceHealthStatus.HEALTHY
            elif failed_checks <= 1:
                status = ServiceHealthStatus.WARNING
            else:
                status = ServiceHealthStatus.CRITICAL
            
            health_check = ServiceHealthCheck(
                service_id=service_id,
                status=status,
                last_check=datetime.now(timezone.utc),
                checks=checks,
                metrics=metrics,
                issues=issues
            )
            
            self.health_checks[service_id] = health_check
            return health_check
            
        except Exception as e:
            logger.error(f"Health check failed for service {service_id}: {e}")
            return ServiceHealthCheck(
                service_id=service_id,
                status=ServiceHealthStatus.UNKNOWN,
                last_check=datetime.now(timezone.utc),
                checks={},
                metrics={},
                issues=[str(e)]
            )
    
    async def start_health_monitoring(self) -> None:
        """Start periodic health monitoring for all services."""
        async def health_monitor():
            while True:
                try:
                    # Get all registered services
                    services = await self.registry.list()
                    
                    # Perform health checks
                    for service in services:
                        await self.perform_health_check(service.id)
                    
                    # Check auto-scaling triggers
                    await self._check_auto_scaling_triggers()
                    
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
    
    async def get_operation_status(self, operation_id: UUID) -> Optional[ServiceOperation]:
        """Get the status of a specific operation."""
        return self.operations.get(operation_id)
    
    async def get_service_operations(
        self,
        service_id: UUID,
        limit: Optional[int] = None
    ) -> List[ServiceOperation]:
        """Get operations for a specific service."""
        operations = [
            op for op in self.operations.values()
            if op.service_id == service_id
        ]
        
        # Sort by creation time (most recent first)
        operations.sort(key=lambda op: op.created_at, reverse=True)
        
        if limit:
            operations = operations[:limit]
        
        return operations
    
    async def get_management_statistics(self) -> Dict[str, Any]:
        """Get comprehensive management statistics."""
        services = await self.registry.list()
        
        # Operation statistics
        operation_stats = {}
        for op_type in ["create", "start", "stop", "deploy", "scale", "update"]:
            ops = [op for op in self.operations.values() if op.operation_type == op_type]
            operation_stats[op_type] = {
                "total": len(ops),
                "completed": len([op for op in ops if op.status == ServiceOperationStatus.COMPLETED]),
                "failed": len([op for op in ops if op.status == ServiceOperationStatus.FAILED]),
                "pending": len([op for op in ops if op.status == ServiceOperationStatus.PENDING])
            }
        
        # Health statistics
        health_stats = {}
        for status in ServiceHealthStatus:
            health_stats[status.value] = len([
                hc for hc in self.health_checks.values()
                if hc.status == status
            ])
        
        # Deployment statistics
        deployment_stats = {
            "total_targets": len(self.deployment_targets),
            "deployed_services": len(self.service_deployments),
            "target_utilization": {}
        }
        
        for target_id, target in self.deployment_targets.items():
            max_services = target.capacity.get("max_services", 10)
            utilization = len(target.deployed_services) / max(max_services, 1)
            deployment_stats["target_utilization"][target_id] = utilization
        
        # Auto-scaling statistics
        auto_scaling_stats = {
            "services_with_auto_scaling": len(self.auto_scaling_configs),
            "auto_scaling_enabled": sum(1 for config in self.auto_scaling_configs.values() if config.get("enabled", False))
        }
        
        return {
            "total_services": len(services),
            "operation_statistics": operation_stats,
            "health_statistics": health_stats,
            "deployment_statistics": deployment_stats,
            "auto_scaling_statistics": auto_scaling_stats,
            "health_monitoring_active": self.health_check_task is not None and not self.health_check_task.done()
        }
    
    # Private helper methods
    async def _execute_service_operation(
        self,
        operation_type: str,
        service_id: UUID,
        parameters: Dict[str, Any]
    ) -> None:
        """Execute a generic service operation."""
        operation_id = uuid4()
        operation = ServiceOperation(
            operation_id=operation_id,
            operation_type=operation_type,
            service_id=service_id,
            parameters=parameters
        )
        
        async with self.operation_lock:
            self.operations[operation_id] = operation
        
        try:
            operation.start_operation()
            
            # Get service
            service = await self.registry.get_service(service_id)
            
            # Execute operation
            if operation_type == "start":
                await service.start()
            elif operation_type == "stop":
                await service.stop()
            elif operation_type == "pause":
                await service.pause()
            elif operation_type == "resume":
                await service.resume()
            else:
                raise ServiceError(f"Unknown operation type: {operation_type}")
            
            operation.complete_operation()
            logger.info(f"Successfully executed {operation_type} on service {service_id}")
            
        except Exception as e:
            operation.fail_operation(str(e))
            logger.error(f"Failed to execute {operation_type} on service {service_id}: {e}")
            raise ServiceError(f"Operation {operation_type} failed: {e}")
    
    async def _check_auto_scaling_triggers(self) -> None:
        """Check auto-scaling triggers for all configured services."""
        for service_id, config in self.auto_scaling_configs.items():
            if not config.get("enabled", False):
                continue
            
            try:
                # Get service metrics
                service_metrics = await self.registry.get_service_performance(service_id)
                
                # Check scaling triggers (simplified)
                current_instances = 1  # Would be tracked properly in real implementation
                min_instances = config.get("min_instances", 1)
                max_instances = config.get("max_instances", 5)
                
                # Scale up trigger (example: high success rate and low response time indicate high load)
                success_rate = service_metrics.get("success_rate", 0.0)
                response_time = service_metrics.get("average_execution_time", 0.0)
                
                if success_rate > 0.9 and response_time > 2.0 and current_instances < max_instances:
                    logger.info(f"Auto-scaling up service {service_id}")
                    # Would trigger scaling here
                
                # Scale down trigger
                elif success_rate > 0.95 and response_time < 0.5 and current_instances > min_instances:
                    logger.info(f"Auto-scaling down service {service_id}")
                    # Would trigger scaling down here
                
            except Exception as e:
                logger.error(f"Auto-scaling check failed for service {service_id}: {e}")


class ServiceOrchestrator(IServiceOrchestrator):
    """Service orchestrator for managing service workflows and compositions."""
    
    def __init__(
        self,
        lifecycle_manager: ServiceLifecycleManager,
        registry: Any  # ServiceRegistry
    ):
        self.lifecycle_manager = lifecycle_manager
        self.registry = registry
        self.workflows: Dict[UUID, ServiceWorkflow] = {}
        self.workflow_lock = asyncio.Lock()
    
    async def create_workflow(
        self,
        workflow_name: str,
        service_chain: List[Dict[str, Any]],
        workflow_config: Dict[str, Any]
    ) -> UUID:
        """Create a service workflow."""
        workflow_id = uuid4()
        
        async with self.workflow_lock:
            workflow = ServiceWorkflow(
                workflow_id=workflow_id,
                name=workflow_name,
                digital_twin_id=UUID(workflow_config.get("digital_twin_id", str(uuid4()))),
                service_chain=service_chain,
                workflow_config=workflow_config
            )
            
            self.workflows[workflow_id] = workflow
        
        logger.info(f"Created workflow {workflow_name} with ID {workflow_id}")
        return workflow_id
    
    async def execute_workflow(
        self,
        workflow_id: UUID,
        input_data: Dict[str, Any],
        execution_config: Optional[Dict[str, Any]] = None
    ) -> UUID:
        """Execute a workflow."""
        if workflow_id not in self.workflows:
            raise ServiceError(f"Workflow {workflow_id} not found")
        
        workflow = self.workflows[workflow_id]
        execution_id = uuid4()
        
        async def execute_workflow_async():
            try:
                workflow.status = "running"
                workflow.current_execution_id = execution_id
                
                current_data = input_data
                results = []
                
                # Execute service chain
                for step_idx, step in enumerate(workflow.service_chain):
                    step_name = step.get("step_name", f"step_{step_idx}")
                    service_id = UUID(step["service_id"])
                    step_config = step.get("config", {})
                    
                    logger.info(f"Executing workflow step {step_name} with service {service_id}")
                    
                    # Get service and execute
                    service = await self.registry.get_service(service_id)
                    
                    request = ServiceRequest(
                        request_id=uuid4(),
                        requester_id=uuid4(),
                        service_instance_id=service_id,
                        input_data=current_data,
                        execution_parameters=step_config
                    )
                    
                    response = await service.execute(request)
                    
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
                        workflow.status = "failed"
                        workflow.execution_history.append({
                            "execution_id": str(execution_id),
                            "status": "failed",
                            "results": results,
                            "error": f"Step {step_name} failed: {response.error_message}",
                            "completed_at": datetime.now(timezone.utc).isoformat()
                        })
                        return
                
                # Workflow completed successfully
                workflow.status = "completed"
                workflow.execution_history.append({
                    "execution_id": str(execution_id),
                    "status": "completed",
                    "results": results,
                    "completed_at": datetime.now(timezone.utc).isoformat()
                })
                
                logger.info(f"Workflow {workflow_id} completed successfully")
                
            except Exception as e:
                workflow.status = "failed"
                workflow.execution_history.append({
                    "execution_id": str(execution_id),
                    "status": "failed",
                    "error": str(e),
                    "completed_at": datetime.now(timezone.utc).isoformat()
                })
                logger.error(f"Workflow {workflow_id} failed: {e}")
        
        # Start async execution
        asyncio.create_task(execute_workflow_async())
        
        return execution_id
    
    async def monitor_workflow(self, execution_id: UUID) -> Dict[str, Any]:
        """Monitor workflow execution progress."""
        for workflow in self.workflows.values():
            if workflow.current_execution_id == execution_id:
                return {
                    "execution_id": str(execution_id),
                    "workflow_id": str(workflow.workflow_id),
                    "workflow_name": workflow.name,
                    "status": workflow.status,
                    "execution_history": workflow.execution_history[-1] if workflow.execution_history else None
                }
        
        return {"error": "Execution not found"}
    
    async def compose_services(
        self,
        service_ids: List[UUID],
        composition_rules: Dict[str, Any]
    ) -> UUID:
        """Compose multiple services into a composite service."""
        # This would create a composite service that orchestrates the individual services
        # For now, we'll create a workflow
        
        service_chain = []
        for idx, service_id in enumerate(service_ids):
            service_chain.append({
                "step_name": f"service_{idx}",
                "service_id": str(service_id),
                "config": composition_rules.get(f"service_{idx}_config", {})
            })
        
        return await self.create_workflow(
            workflow_name=f"Composed Service - {len(service_ids)} services",
            service_chain=service_chain,
            workflow_config=composition_rules
        )