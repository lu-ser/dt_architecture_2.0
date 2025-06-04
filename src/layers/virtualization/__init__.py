"""
Virtualization Layer Integration for the Digital Twin Platform.

This module integrates all components of the Virtualization Layer:
- DR Factory with Template/Ontology support
- DR Registry with advanced querying
- DR Management with lifecycle control
- DR Container with deployment capabilities

LOCATION: src/layers/virtualization/__init__.py
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
from uuid import UUID, uuid4

# Import all virtualization layer components
from src.layers.virtualization.dr_factory import DigitalReplicaFactory, DigitalReplica
from src.layers.virtualization.dr_registry import DigitalReplicaRegistry, DigitalReplicaMetrics
from src.layers.virtualization.dr_management import DigitalReplicaLifecycleManager, ReplicaDeploymentTarget
from src.layers.virtualization.dr_container import DigitalReplicaContainer, DigitalReplicaContainerFactory
from src.layers.virtualization.ontology.manager import (
    OntologyManager, 
    get_ontology_manager, 
    initialize_ontology_system,
    Template,
    Ontology,
    TemplateType
)

# Import interfaces
from src.core.interfaces.base import BaseMetadata, EntityStatus
from src.core.interfaces.replica import (
    IDigitalReplica,
    ReplicaType,
    ReplicaConfiguration,
    DataAggregationMode,
    DeviceData,
    AggregatedData
)

# Import storage adapters (mock for now)
from tests.mocks.storage_adapter import InMemoryStorageAdapter
from src.storage import get_twin_storage_adapter, get_global_storage_adapter
from src.storage.adapters import get_registry_cache
from src.utils.exceptions import (
    DigitalReplicaError,
    ConfigurationError,
    EntityCreationError
)
from src.utils.config import get_config

logger = logging.getLogger(__name__)


class VirtualizationLayerOrchestrator:
    """
    Main orchestrator for the Virtualization Layer.
    
    Coordinates all components and provides a unified interface for
    Digital Replica management with template and ontology support.
    """
    
    def __init__(self, base_templates_path: Optional[Path] = None):
        self.config = get_config()
        self.base_templates_path = base_templates_path or Path("templates")
        
        # Initialize components
        self.ontology_manager: Optional[OntologyManager] = None
        self.factory: Optional[DigitalReplicaFactory] = None
        self.registry: Optional[DigitalReplicaRegistry] = None
        self.lifecycle_manager: Optional[DigitalReplicaLifecycleManager] = None
        self.container_factory = DigitalReplicaContainerFactory()
        
        # Component state
        self._initialized = False
        self._running = False
        
        # Deployment tracking
        self.deployment_targets: Dict[str, ReplicaDeploymentTarget] = {}
        self.active_containers: Dict[UUID, DigitalReplicaContainer] = {}
        self._registry_cache = None
        
        logger.info("Initialized VirtualizationLayerOrchestrator")
    
    async def initialize(self) -> None:
        """Initialize all virtualization layer components."""
        if self._initialized:
            logger.warning("VirtualizationLayerOrchestrator already initialized")
            return
        
        try:
            logger.info("Initializing Virtualization Layer with MongoDB + Redis...")
            
            # 1. Initialize Ontology Manager
            self.ontology_manager = await initialize_ontology_system(self.base_templates_path)
            logger.info(f"Loaded {len(self.ontology_manager.ontologies)} ontologies and {len(self.ontology_manager.templates)} templates")
            
            # 2. Initialize Factory with ontology support
            self.factory = DigitalReplicaFactory()
            await self._integrate_factory_with_ontology()
            
            # 3. Initialize Registry with storage adapter
            # NUOVO: Initialize storage with global adapter (replicas are tied to twins)
            # We'll create twin-specific adapters when creating replicas
            storage_adapter = get_global_storage_adapter(IDigitalReplica)
            
            # Initialize registry with enhanced caching
            self.registry = DigitalReplicaRegistry(
                storage_adapter, 
                cache_enabled=True,
                cache_size=2000,
                cache_ttl=600
            )
            await self.registry.connect()
            await self._setup_enhanced_caching()
            
            # 4. Initialize Lifecycle Manager
            self.lifecycle_manager = DigitalReplicaLifecycleManager(
                factory=self.factory, 
                registry=self.registry
            )
            
            # 5. Setup default deployment targets
            await self._setup_default_deployment_targets()
            
            self._initialized = True
            logger.info("Virtualization Layer initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Virtualization Layer: {e}")
            raise ConfigurationError(f"Virtualization Layer initialization failed: {e}")
    

    async def _setup_enhanced_caching(self) -> None:
        """Setup Redis-based caching for improved performance."""
        try:
            # Get Redis cache for registry operations
            self._registry_cache = await get_registry_cache()
            
            # Enhance registry with Redis cache if available
            if hasattr(self.registry, '_setup_redis_cache'):
                await self.registry._setup_redis_cache(self._registry_cache)
            
            logger.info('Enhanced caching setup completed')
            
        except Exception as e:
            logger.warning(f'Failed to setup enhanced caching: {e}')
            # Continue without Redis cache

    async def start(self) -> None:
        """Start the virtualization layer services."""
        if not self._initialized:
            await self.initialize()
        
        if self._running:
            logger.warning("VirtualizationLayerOrchestrator already running")
            return
        
        try:
            logger.info("Starting Virtualization Layer services...")
            
            # Start health monitoring
            await self.lifecycle_manager.start_health_monitoring()
            
            self._running = True
            logger.info("Virtualization Layer started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start Virtualization Layer: {e}")
            raise DigitalReplicaError(f"Virtualization Layer start failed: {e}")
    
    async def stop(self) -> None:
        """Stop the virtualization layer services."""
        if not self._running:
            return
        
        try:
            logger.info("Stopping Virtualization Layer services...")
            
            # Stop all containers
            for container in self.active_containers.values():
                await container.stop()
            self.active_containers.clear()
            
            # Stop health monitoring
            if self.lifecycle_manager:
                await self.lifecycle_manager.stop_health_monitoring()
            
            # Disconnect registry
            if self.registry:
                await self.registry.disconnect()
            
            self._running = False
            logger.info("Virtualization Layer stopped successfully")
            
        except Exception as e:
            logger.error(f"Error stopping Virtualization Layer: {e}")
    
    
    async def create_replica_from_template(self, template_id: str, parent_digital_twin_id: UUID, 
                                         device_ids: List[str], overrides: Optional[Dict[str, Any]] = None, 
                                         validate_ontology: bool = True) -> IDigitalReplica:
        """Create replica with twin-specific storage."""
        if not self._initialized:
            await self.initialize()
            
        try:
            template = self.ontology_manager.get_template(template_id)
            if not template:
                raise ConfigurationError(f'Template {template_id} not found')
            
            config = self.ontology_manager.apply_template(template_id, overrides)
            config['parent_digital_twin_id'] = str(parent_digital_twin_id)
            config['device_ids'] = device_ids
            
            # Ontology validation
            if validate_ontology and template.ontology_classes:
                for ontology_class in template.ontology_classes:
                    for ontology_name in self.ontology_manager.list_ontologies():
                        validation_errors = self.ontology_manager.validate_configuration(
                            config, ontology_name, ontology_class
                        )
                        if not validation_errors:
                            logger.info(f'Configuration validated against {ontology_name}#{ontology_class}')
                            break
                    else:
                        logger.warning(f'Could not validate against ontology class {ontology_class}')
            
            # NUOVO: Create twin-specific storage adapter for this replica
            await self._ensure_twin_storage(parent_digital_twin_id)
            
            # Create metadata
            metadata = BaseMetadata(
                entity_id=uuid4(),
                timestamp=datetime.now(timezone.utc),
                version=template.version,
                created_by=uuid4(),
                custom={
                    'template_id': template_id,
                    'template_name': template.name,
                    'created_from_template': True,
                    'parent_twin_id': str(parent_digital_twin_id)
                }
            )
            
            # Create replica through lifecycle manager (which handles storage)
            replica = await self.lifecycle_manager.create_entity(config, metadata)
            
            # NUOVO: Cache the replica for faster access
            if self._registry_cache:
                await self._registry_cache.cache_entity(
                    replica.id, replica.to_dict(), 'DigitalReplica'
                )
            
            logger.info(f'Created Digital Replica {replica.id} from template {template_id} with persistent storage')
            return replica
            
        except Exception as e:
            logger.error(f'Failed to create replica from template {template_id}: {e}')
            raise EntityCreationError(f'Template-based replica creation failed: {e}')
    
    async def _ensure_twin_storage(self, twin_id: UUID) -> None:
            """Ensure storage is configured for the specific Digital Twin."""
            try:
                # Check if we should create twin-specific storage
                if self.config.get('storage.separate_dbs_per_twin', True):
                    # Create twin-specific storage adapter
                    twin_storage = get_twin_storage_adapter(IDigitalReplica, twin_id)
                    await twin_storage.connect()
                    health = await twin_storage.health_check()
                    
                    if health:
                        logger.info(f'Twin-specific storage ready for {twin_id}')
                    else:
                        logger.warning(f'Twin-specific storage health check failed for {twin_id}')
                        
            except Exception as e:
                logger.warning(f'Failed to ensure twin storage for {twin_id}: {e}')

    async def create_replica_from_configuration(
        self,
        replica_type: ReplicaType,
        parent_digital_twin_id: UUID,
        device_ids: List[str],
        aggregation_mode: DataAggregationMode,
        configuration: Optional[Dict[str, Any]] = None
    ) -> IDigitalReplica:
        """
        Create a Digital Replica from direct configuration.
        
        Args:
            replica_type: Type of replica to create
            parent_digital_twin_id: ID of the parent Digital Twin
            device_ids: List of device IDs to associate
            aggregation_mode: Data aggregation mode
            configuration: Optional additional configuration
            
        Returns:
            Created Digital Replica instance
        """
        if not self._initialized:
            await self.initialize()
        
        config = {
            "replica_type": replica_type.value,
            "parent_digital_twin_id": str(parent_digital_twin_id),
            "device_ids": device_ids,
            "aggregation_mode": aggregation_mode.value,
            "aggregation_config": configuration.get("aggregation_config", {}),
            "data_retention_policy": configuration.get("data_retention_policy", {}),
            "quality_thresholds": configuration.get("quality_thresholds", {}),
            "custom_config": configuration.get("custom_config", {})
        }
        
        return await self.lifecycle_manager.create_entity(config)
    
    async def deploy_replica_as_container(
        self,
        replica_id: UUID,
        deployment_target: str,
        container_config: Optional[Dict[str, Any]] = None
    ) -> DigitalReplicaContainer:
        """
        Deploy a Digital Replica as a container.
        
        Args:
            replica_id: ID of the replica to deploy
            deployment_target: Target for deployment
            container_config: Optional container configuration
            
        Returns:
            Deployed container instance
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Get replica
            replica = await self.registry.get_digital_replica(replica_id)
            
            # Create container
            container = self.container_factory.create_container(replica, container_config)
            
            # Deploy using lifecycle manager
            deployment_id = await self.lifecycle_manager.deploy_replica(replica, deployment_target)
            
            # Initialize and start container
            await container.initialize()
            await container.start()
            
            # Track container
            self.active_containers[replica_id] = container
            
            logger.info(f"Deployed replica {replica_id} as container {container.container_id}")
            return container
            
        except Exception as e:
            logger.error(f"Failed to deploy replica {replica_id} as container: {e}")
            raise DigitalReplicaError(f"Container deployment failed: {e}")
    
    async def scale_replica_horizontally(
        self,
        replica_id: UUID,
        target_instances: int,
        deployment_strategy: str = "gradual"
    ) -> List[UUID]:
        """
        Scale a Digital Replica horizontally.
        
        Args:
            replica_id: ID of the replica to scale
            target_instances: Target number of instances
            deployment_strategy: Strategy for scaling
            
        Returns:
            List of replica IDs (including original and new instances)
        """
        if not self._initialized:
            await self.initialize()
        
        await self.lifecycle_manager.scale_replica(replica_id, target_instances)
        
        # Get all replicas for the same Digital Twin
        original_replica = await self.registry.get_digital_replica(replica_id)
        scaled_replicas = await self.registry.find_replicas_by_digital_twin(
            original_replica.parent_digital_twin_id
        )
        
        return [replica.id for replica in scaled_replicas]
    
    async def discover_replicas(
        self,
        criteria: Dict[str, Any],
        include_containers: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Discover Digital Replicas based on criteria.
        
        Args:
            criteria: Discovery criteria
            include_containers: Whether to include container information
            
        Returns:
            List of replica information
        """
        if not self._initialized:
            await self.initialize()
        
        replicas = await self.registry.discover_replicas(criteria)
        
        results = []
        for replica in replicas:
            result = {
                "replica": replica.to_dict(),
                "performance": await self.registry.get_replica_performance(replica.id)
            }
            
            if include_containers and replica.id in self.active_containers:
                container = self.active_containers[replica.id]
                result["container"] = container.get_container_status()
            
            results.append(result)
        
        return results
    
    async def get_available_templates(self, template_type: Optional[TemplateType] = None) -> List[Dict[str, Any]]:
        """Get available templates with their information."""
        if not self._initialized:
            await self.initialize()
        
        template_ids = self.ontology_manager.list_templates(template_type)
        templates = []
        
        for template_id in template_ids:
            template = self.ontology_manager.get_template(template_id)
            if template:
                templates.append(template.to_dict())
        
        return templates
    
    async def get_available_ontologies(self) -> List[Dict[str, Any]]:
        """Get available ontologies with their information."""
        if not self._initialized:
            await self.initialize()
        
        ontology_names = self.ontology_manager.list_ontologies()
        ontologies = []
        
        for ontology_name in ontology_names:
            ontology = self.ontology_manager.get_ontology(ontology_name)
            if ontology:
                ontologies.append(ontology.to_dict())
        
        return ontologies
    
    async def validate_configuration_against_ontology(
        self,
        configuration: Dict[str, Any],
        ontology_name: str,
        class_name: str
    ) -> Dict[str, Any]:
        """
        Validate a configuration against an ontology class.
        
        Returns:
            Validation result with errors and warnings
        """
        if not self._initialized:
            await self.initialize()
        
        errors = self.ontology_manager.validate_configuration(
            configuration, ontology_name, class_name
        )
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "ontology": ontology_name,
            "class": class_name
        }
    
    
    async def get_layer_statistics(self) -> Dict[str, Any]:
        """Enhanced statistics including storage health."""
        if not self._initialized:
            await self.initialize()
            
        # Get base statistics
        registry_stats = await self.registry.get_data_flow_statistics()
        management_stats = await self.lifecycle_manager.get_management_statistics()
        ontology_stats = self.ontology_manager.get_statistics()
        
        container_stats = {
            'active_containers': len(self.active_containers),
            'deployment_targets': len(self.deployment_targets),
            'container_health': {}
        }
        
        for replica_id, container in self.active_containers.items():
            container_stats['container_health'][str(replica_id)] = container.get_metrics()
        
        # NUOVO: Add storage health
        storage_stats = await self._get_storage_health()
        
        return {
            'virtualization_layer': {
                'initialized': self._initialized,
                'running': self._running,
                'components': {
                    'ontology_manager': bool(self.ontology_manager),
                    'factory': bool(self.factory),
                    'registry': bool(self.registry),
                    'lifecycle_manager': bool(self.lifecycle_manager)
                }
            },
            'registry': registry_stats,
            'management': management_stats,
            'ontology': ontology_stats,
            'containers': container_stats,
            'storage': storage_stats  # NUOVO
        }
    
    
    async def _get_storage_health(self) -> Dict[str, Any]:
        """Get storage system health information."""
        health = {
            'primary_storage': 'unknown',
            'cache_storage': 'unknown',
            'registry_connected': False,
            'cache_connected': False
        }
        
        try:
            # Check registry storage health
            if self.registry and hasattr(self.registry, 'storage_adapter'):
                registry_health = await self.registry.storage_adapter.health_check()
                health['registry_connected'] = registry_health
                health['primary_storage'] = 'mongodb' if registry_health else 'failed'
            
            # Check cache health
            if self._registry_cache:
                cache_health = await self._registry_cache.cache.health_check()
                health['cache_connected'] = cache_health
                health['cache_storage'] = 'redis' if cache_health else 'failed'
            
        except Exception as e:
            logger.warning(f'Storage health check error: {e}')
            health['error'] = str(e)
        
        return health

    async def _integrate_factory_with_ontology(self) -> None:
        """Integrate the factory with ontology validation."""
        if not self.factory or not self.ontology_manager:
            return
        
        # Create template-based factory methods
        original_create = self.factory.create
        
        async def enhanced_create(config: Dict[str, Any], metadata: Optional[BaseMetadata] = None):
            # Check if this is a template-based creation
            template_id = config.get("template_id")
            if template_id:
                template = self.ontology_manager.get_template(template_id)
                if template and template.ontology_classes:
                    # Validate against ontology
                    for ontology_class in template.ontology_classes:
                        for ontology_name in self.ontology_manager.list_ontologies():
                            errors = self.ontology_manager.validate_configuration(
                                config, ontology_name, ontology_class
                            )
                            if not errors:
                                logger.debug(f"Configuration validated against {ontology_name}#{ontology_class}")
                                break
            
            # Call original create method
            return await original_create(config, metadata)
        
        self.factory.create = enhanced_create
        logger.info("Integrated factory with ontology validation")
    
    async def _setup_default_deployment_targets(self) -> None:
        """Setup default deployment targets."""
        # Local container target
        local_target = ReplicaDeploymentTarget(
            target_id="local_docker",
            target_type="container",
            capacity={"memory": 4096, "cpu": 2.0, "max_replicas": 50},
            location="local",
            metadata={"runtime": "docker", "orchestrator": "local"}
        )
        await self.lifecycle_manager.add_deployment_target(local_target)
        self.deployment_targets["local_docker"] = local_target
        
        # Edge target
        edge_target = ReplicaDeploymentTarget(
            target_id="edge_devices",
            target_type="edge_device",
            capacity={"memory": 1024, "cpu": 1.0, "max_replicas": 20},
            location="edge",
            metadata={"runtime": "container", "connectivity": "limited"}
        )
        await self.lifecycle_manager.add_deployment_target(edge_target)
        self.deployment_targets["edge_devices"] = edge_target
        
        logger.info(f"Setup {len(self.deployment_targets)} default deployment targets")


# Global orchestrator instance
_virtualization_orchestrator: Optional[VirtualizationLayerOrchestrator] = None


def get_virtualization_orchestrator() -> VirtualizationLayerOrchestrator:
    global _virtualization_orchestrator
    if _virtualization_orchestrator is None:
        _virtualization_orchestrator = VirtualizationLayerOrchestrator()
    return _virtualization_orchestrator

async def initialize_virtualization_layer(base_templates_path: Optional[Path] = None) -> VirtualizationLayerOrchestrator:
    global _virtualization_orchestrator
    _virtualization_orchestrator = VirtualizationLayerOrchestrator(base_templates_path)
    await _virtualization_orchestrator.initialize()
    return _virtualization_orchestrator


# Convenience functions for common operations
async def create_iot_sensor_replica(
    parent_digital_twin_id: UUID,
    device_ids: List[str],
    batch_size: int = 10,
    quality_threshold: float = 0.7
) -> IDigitalReplica:
    """Convenience function to create an IoT sensor replica."""
    orchestrator = get_virtualization_orchestrator()
    
    overrides = {
        "aggregation_config": {
            "batch_size": batch_size,
            "quality_threshold": quality_threshold
        },
        "quality_thresholds": {
            "min_quality": quality_threshold
        }
    }
    
    return await orchestrator.create_replica_from_template(
        template_id="iot_sensor_aggregator",
        parent_digital_twin_id=parent_digital_twin_id,
        device_ids=device_ids,
        overrides=overrides
    )


async def create_industrial_device_replica(
    parent_digital_twin_id: UUID,
    device_id: str,
    real_time_required: bool = True,
    high_security: bool = True
) -> IDigitalReplica:
    """Convenience function to create an industrial device replica."""
    orchestrator = get_virtualization_orchestrator()
    
    overrides = {
        "device_constraints": {
            "real_time_required": real_time_required
        },
        "security_settings": {
            "encryption_required": high_security,
            "authentication_method": "certificate" if high_security else "password"
        }
    }
    
    return await orchestrator.create_replica_from_template(
        template_id="industrial_device_proxy",
        parent_digital_twin_id=parent_digital_twin_id,
        device_ids=[device_id],
        overrides=overrides
    )
