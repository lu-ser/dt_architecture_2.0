import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
from uuid import UUID, uuid4
from src.layers.virtualization.dr_factory import DigitalReplicaFactory, DigitalReplica
from src.layers.virtualization.dr_registry import DigitalReplicaRegistry, DigitalReplicaMetrics
from src.layers.virtualization.dr_management import DigitalReplicaLifecycleManager, ReplicaDeploymentTarget
from src.layers.virtualization.dr_container import DigitalReplicaContainer, DigitalReplicaContainerFactory
from src.layers.virtualization.ontology.manager import OntologyManager, get_ontology_manager, initialize_ontology_system, Template, Ontology, TemplateType
from src.core.interfaces.base import BaseMetadata, EntityStatus
from src.core.interfaces.replica import IDigitalReplica, ReplicaType, ReplicaConfiguration, DataAggregationMode, DeviceData, AggregatedData
from tests.mocks.storage_adapter import InMemoryStorageAdapter
from src.utils.exceptions import DigitalReplicaError, ConfigurationError, EntityCreationError
from src.utils.config import get_config
logger = logging.getLogger(__name__)

class VirtualizationLayerOrchestrator:

    def __init__(self, base_templates_path: Optional[Path]=None):
        self.config = get_config()
        self.base_templates_path = base_templates_path or Path('templates')
        self.ontology_manager: Optional[OntologyManager] = None
        self.factory: Optional[DigitalReplicaFactory] = None
        self.registry: Optional[DigitalReplicaRegistry] = None
        self.lifecycle_manager: Optional[DigitalReplicaLifecycleManager] = None
        self.container_factory = DigitalReplicaContainerFactory()
        self._initialized = False
        self._running = False
        self.deployment_targets: Dict[str, ReplicaDeploymentTarget] = {}
        self.active_containers: Dict[UUID, DigitalReplicaContainer] = {}
        logger.info('Initialized VirtualizationLayerOrchestrator')

    async def initialize(self) -> None:
        if self._initialized:
            logger.warning('VirtualizationLayerOrchestrator already initialized')
            return
        try:
            logger.info('Initializing Virtualization Layer components...')
            self.ontology_manager = await initialize_ontology_system(self.base_templates_path)
            logger.info(f'Loaded {len(self.ontology_manager.ontologies)} ontologies and {len(self.ontology_manager.templates)} templates')
            self.factory = DigitalReplicaFactory()
            await self._integrate_factory_with_ontology()
            storage_adapter = InMemoryStorageAdapter()
            self.registry = DigitalReplicaRegistry(storage_adapter)
            await self.registry.connect()
            self.lifecycle_manager = DigitalReplicaLifecycleManager(factory=self.factory, registry=self.registry)
            await self._setup_default_deployment_targets()
            self._initialized = True
            logger.info('Virtualization Layer initialized successfully')
        except Exception as e:
            logger.error(f'Failed to initialize Virtualization Layer: {e}')
            raise ConfigurationError(f'Virtualization Layer initialization failed: {e}')

    async def start(self) -> None:
        if not self._initialized:
            await self.initialize()
        if self._running:
            logger.warning('VirtualizationLayerOrchestrator already running')
            return
        try:
            logger.info('Starting Virtualization Layer services...')
            await self.lifecycle_manager.start_health_monitoring()
            self._running = True
            logger.info('Virtualization Layer started successfully')
        except Exception as e:
            logger.error(f'Failed to start Virtualization Layer: {e}')
            raise DigitalReplicaError(f'Virtualization Layer start failed: {e}')

    async def stop(self) -> None:
        if not self._running:
            return
        try:
            logger.info('Stopping Virtualization Layer services...')
            for container in self.active_containers.values():
                await container.stop()
            self.active_containers.clear()
            if self.lifecycle_manager:
                await self.lifecycle_manager.stop_health_monitoring()
            if self.registry:
                await self.registry.disconnect()
            self._running = False
            logger.info('Virtualization Layer stopped successfully')
        except Exception as e:
            logger.error(f'Error stopping Virtualization Layer: {e}')

    async def create_replica_from_template(self, template_id: str, parent_digital_twin_id: UUID, device_ids: List[str], overrides: Optional[Dict[str, Any]]=None, validate_ontology: bool=True) -> IDigitalReplica:
        if not self._initialized:
            await self.initialize()
        try:
            template = self.ontology_manager.get_template(template_id)
            if not template:
                raise ConfigurationError(f'Template {template_id} not found')
            config = self.ontology_manager.apply_template(template_id, overrides)
            config['parent_digital_twin_id'] = str(parent_digital_twin_id)
            config['device_ids'] = device_ids
            if validate_ontology and template.ontology_classes:
                for ontology_class in template.ontology_classes:
                    for ontology_name in self.ontology_manager.list_ontologies():
                        validation_errors = self.ontology_manager.validate_configuration(config, ontology_name, ontology_class)
                        if not validation_errors:
                            logger.info(f'Configuration validated against {ontology_name}#{ontology_class}')
                            break
                    else:
                        logger.warning(f'Could not validate against ontology class {ontology_class}')
            metadata = BaseMetadata(entity_id=uuid4(), timestamp=datetime.now(timezone.utc), version=template.version, created_by=uuid4(), custom={'template_id': template_id, 'template_name': template.name, 'created_from_template': True})
            replica = await self.lifecycle_manager.create_entity(config, metadata)
            logger.info(f'Created Digital Replica {replica.id} from template {template_id}')
            return replica
        except Exception as e:
            logger.error(f'Failed to create replica from template {template_id}: {e}')
            raise EntityCreationError(f'Template-based replica creation failed: {e}')

    async def create_replica_from_configuration(self, replica_type: ReplicaType, parent_digital_twin_id: UUID, device_ids: List[str], aggregation_mode: DataAggregationMode, configuration: Optional[Dict[str, Any]]=None) -> IDigitalReplica:
        if not self._initialized:
            await self.initialize()
        config = {'replica_type': replica_type.value, 'parent_digital_twin_id': str(parent_digital_twin_id), 'device_ids': device_ids, 'aggregation_mode': aggregation_mode.value, 'aggregation_config': configuration.get('aggregation_config', {}), 'data_retention_policy': configuration.get('data_retention_policy', {}), 'quality_thresholds': configuration.get('quality_thresholds', {}), 'custom_config': configuration.get('custom_config', {})}
        return await self.lifecycle_manager.create_entity(config)

    async def deploy_replica_as_container(self, replica_id: UUID, deployment_target: str, container_config: Optional[Dict[str, Any]]=None) -> DigitalReplicaContainer:
        if not self._initialized:
            await self.initialize()
        try:
            replica = await self.registry.get_digital_replica(replica_id)
            container = self.container_factory.create_container(replica, container_config)
            deployment_id = await self.lifecycle_manager.deploy_replica(replica, deployment_target)
            await container.initialize()
            await container.start()
            self.active_containers[replica_id] = container
            logger.info(f'Deployed replica {replica_id} as container {container.container_id}')
            return container
        except Exception as e:
            logger.error(f'Failed to deploy replica {replica_id} as container: {e}')
            raise DigitalReplicaError(f'Container deployment failed: {e}')

    async def scale_replica_horizontally(self, replica_id: UUID, target_instances: int, deployment_strategy: str='gradual') -> List[UUID]:
        if not self._initialized:
            await self.initialize()
        await self.lifecycle_manager.scale_replica(replica_id, target_instances)
        original_replica = await self.registry.get_digital_replica(replica_id)
        scaled_replicas = await self.registry.find_replicas_by_digital_twin(original_replica.parent_digital_twin_id)
        return [replica.id for replica in scaled_replicas]

    async def discover_replicas(self, criteria: Dict[str, Any], include_containers: bool=False) -> List[Dict[str, Any]]:
        if not self._initialized:
            await self.initialize()
        replicas = await self.registry.discover_replicas(criteria)
        results = []
        for replica in replicas:
            result = {'replica': replica.to_dict(), 'performance': await self.registry.get_replica_performance(replica.id)}
            if include_containers and replica.id in self.active_containers:
                container = self.active_containers[replica.id]
                result['container'] = container.get_container_status()
            results.append(result)
        return results

    async def get_available_templates(self, template_type: Optional[TemplateType]=None) -> List[Dict[str, Any]]:
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
        if not self._initialized:
            await self.initialize()
        ontology_names = self.ontology_manager.list_ontologies()
        ontologies = []
        for ontology_name in ontology_names:
            ontology = self.ontology_manager.get_ontology(ontology_name)
            if ontology:
                ontologies.append(ontology.to_dict())
        return ontologies

    async def validate_configuration_against_ontology(self, configuration: Dict[str, Any], ontology_name: str, class_name: str) -> Dict[str, Any]:
        if not self._initialized:
            await self.initialize()
        errors = self.ontology_manager.validate_configuration(configuration, ontology_name, class_name)
        return {'valid': len(errors) == 0, 'errors': errors, 'ontology': ontology_name, 'class': class_name}

    async def get_layer_statistics(self) -> Dict[str, Any]:
        if not self._initialized:
            await self.initialize()
        registry_stats = await self.registry.get_data_flow_statistics()
        management_stats = await self.lifecycle_manager.get_management_statistics()
        ontology_stats = self.ontology_manager.get_statistics()
        container_stats = {'active_containers': len(self.active_containers), 'deployment_targets': len(self.deployment_targets), 'container_health': {}}
        for replica_id, container in self.active_containers.items():
            container_stats['container_health'][str(replica_id)] = container.get_metrics()
        return {'virtualization_layer': {'initialized': self._initialized, 'running': self._running, 'components': {'ontology_manager': bool(self.ontology_manager), 'factory': bool(self.factory), 'registry': bool(self.registry), 'lifecycle_manager': bool(self.lifecycle_manager)}}, 'registry': registry_stats, 'management': management_stats, 'ontology': ontology_stats, 'containers': container_stats}

    async def _integrate_factory_with_ontology(self) -> None:
        if not self.factory or not self.ontology_manager:
            return
        original_create = self.factory.create

        async def enhanced_create(config: Dict[str, Any], metadata: Optional[BaseMetadata]=None):
            template_id = config.get('template_id')
            if template_id:
                template = self.ontology_manager.get_template(template_id)
                if template and template.ontology_classes:
                    for ontology_class in template.ontology_classes:
                        for ontology_name in self.ontology_manager.list_ontologies():
                            errors = self.ontology_manager.validate_configuration(config, ontology_name, ontology_class)
                            if not errors:
                                logger.debug(f'Configuration validated against {ontology_name}#{ontology_class}')
                                break
            return await original_create(config, metadata)
        self.factory.create = enhanced_create
        logger.info('Integrated factory with ontology validation')

    async def _setup_default_deployment_targets(self) -> None:
        local_target = ReplicaDeploymentTarget(target_id='local_docker', target_type='container', capacity={'memory': 4096, 'cpu': 2.0, 'max_replicas': 50}, location='local', metadata={'runtime': 'docker', 'orchestrator': 'local'})
        await self.lifecycle_manager.add_deployment_target(local_target)
        self.deployment_targets['local_docker'] = local_target
        edge_target = ReplicaDeploymentTarget(target_id='edge_devices', target_type='edge_device', capacity={'memory': 1024, 'cpu': 1.0, 'max_replicas': 20}, location='edge', metadata={'runtime': 'container', 'connectivity': 'limited'})
        await self.lifecycle_manager.add_deployment_target(edge_target)
        self.deployment_targets['edge_devices'] = edge_target
        logger.info(f'Setup {len(self.deployment_targets)} default deployment targets')
_virtualization_orchestrator: Optional[VirtualizationLayerOrchestrator] = None

def get_virtualization_orchestrator() -> VirtualizationLayerOrchestrator:
    global _virtualization_orchestrator
    if _virtualization_orchestrator is None:
        _virtualization_orchestrator = VirtualizationLayerOrchestrator()
    return _virtualization_orchestrator

async def initialize_virtualization_layer(base_templates_path: Optional[Path]=None) -> VirtualizationLayerOrchestrator:
    global _virtualization_orchestrator
    _virtualization_orchestrator = VirtualizationLayerOrchestrator(base_templates_path)
    await _virtualization_orchestrator.initialize()
    return _virtualization_orchestrator

async def create_iot_sensor_replica(parent_digital_twin_id: UUID, device_ids: List[str], batch_size: int=10, quality_threshold: float=0.7) -> IDigitalReplica:
    orchestrator = get_virtualization_orchestrator()
    overrides = {'aggregation_config': {'batch_size': batch_size, 'quality_threshold': quality_threshold}, 'quality_thresholds': {'min_quality': quality_threshold}}
    return await orchestrator.create_replica_from_template(template_id='iot_sensor_aggregator', parent_digital_twin_id=parent_digital_twin_id, device_ids=device_ids, overrides=overrides)

async def create_industrial_device_replica(parent_digital_twin_id: UUID, device_id: str, real_time_required: bool=True, high_security: bool=True) -> IDigitalReplica:
    orchestrator = get_virtualization_orchestrator()
    overrides = {'device_constraints': {'real_time_required': real_time_required}, 'security_settings': {'encryption_required': high_security, 'authentication_method': 'certificate' if high_security else 'password'}}
    return await orchestrator.create_replica_from_template(template_id='industrial_device_proxy', parent_digital_twin_id=parent_digital_twin_id, device_ids=[device_id], overrides=overrides)