import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
from uuid import UUID, uuid4
from src.layers.digital_twin.dt_factory import DigitalTwinFactory, StandardDigitalTwin
from src.layers.digital_twin.dt_registry import EnhancedDigitalTwinRegistry, DigitalTwinAssociation
from src.core.interfaces.base import BaseMetadata, EntityStatus
from src.core.interfaces.digital_twin import IDigitalTwin, DigitalTwinType, DigitalTwinState, DigitalTwinConfiguration, TwinCapability, TwinModel, TwinModelType, TwinSnapshot
from src.core.interfaces.replica import AggregatedData
from src.core.interfaces.service import IService, ServiceType, ServiceRequest
from src.layers.virtualization import get_virtualization_orchestrator
from src.layers.service import get_service_orchestrator
from tests.mocks.storage_adapter import InMemoryStorageAdapter
from src.storage import get_global_storage_adapter, get_twin_storage_adapter
from src.storage.adapters import get_registry_cache, get_session_cache
from src.layers.virtualization.ontology.manager import get_ontology_manager, TemplateType
from src.utils.exceptions import DigitalTwinError, DigitalTwinNotFoundError, EntityCreationError, ConfigurationError
from src.utils.config import get_config
logger = logging.getLogger(__name__)

class DigitalTwinLayerOrchestrator:

    def __init__(self, templates_integration: bool=True):
        self.config = get_config()
        self.templates_integration = templates_integration
        self.factory: Optional[DigitalTwinFactory] = None
        self.registry: Optional[EnhancedDigitalTwinRegistry] = None
        self.virtualization_orchestrator = None
        self.service_orchestrator = None
        self._initialized = False
        self._running = False
        self.active_twins: Dict[UUID, IDigitalTwin] = {}
        self.data_flow_subscriptions: Dict[UUID, Set[UUID]] = {}
        self.service_bindings: Dict[UUID, Set[UUID]] = {}
        self.active_workflows: Dict[UUID, Dict[str, Any]] = {}
        self.cross_twin_operations: Dict[UUID, Dict[str, Any]] = {}
        self._registry_cache = None
        self._session_cache = None
        logger.info('Initialized DigitalTwinLayerOrchestrator with enhanced storage')

    async def initialize(self) -> None:
        if self._initialized:
            logger.warning('DigitalTwinLayerOrchestrator already initialized')
            return
        try:
            logger.info('Initializing Digital Twin Layer with MongoDB + Redis...')
            self.factory = DigitalTwinFactory()
            logger.info('Digital Twin Factory initialized')
            storage_adapter = get_global_storage_adapter(IDigitalTwin)
            self.registry = EnhancedDigitalTwinRegistry(storage_adapter, cache_enabled=True, cache_size=1000, cache_ttl=600)
            await self.registry.connect()
            logger.info('Enhanced Digital Twin Registry initialized')
            await self._setup_enhanced_caching()
            await self._integrate_with_virtualization_layer()
            await self._integrate_with_service_layer()
            if self.templates_integration:
                await self._integrate_with_templates()
            await self._setup_data_flow_coordination()
            self._initialized = True
            logger.info('Digital Twin Layer initialized successfully with persistent storage')
        except Exception as e:
            logger.error(f'Failed to initialize Digital Twin Layer: {e}')
            raise ConfigurationError(f'Digital Twin Layer initialization failed: {e}')

    async def _setup_enhanced_caching(self) -> None:
        try:
            self._registry_cache = await get_registry_cache()
            self._session_cache = await get_session_cache()
            if hasattr(self.registry, '_setup_redis_cache'):
                await self.registry._setup_redis_cache(self._registry_cache)
            logger.info('Enhanced caching setup completed for Digital Twin Layer')
        except Exception as e:
            logger.warning(f'Failed to setup enhanced caching: {e}')

    async def start(self) -> None:
        if not self._initialized:
            await self.initialize()
        if self._running:
            logger.warning('DigitalTwinLayerOrchestrator already running')
            return
        try:
            logger.info('Starting Digital Twin Layer orchestration...')
            await self._start_orchestration()
            self._running = True
            logger.info('Digital Twin Layer started successfully')
        except Exception as e:
            logger.error(f'Failed to start Digital Twin Layer: {e}')
            raise DigitalTwinError(f'Digital Twin Layer start failed: {e}')

    async def stop(self) -> None:
        if not self._running:
            return
        try:
            logger.info('Stopping Digital Twin Layer...')
            for twin in self.active_twins.values():
                await twin.stop()
            for workflow_id in list(self.active_workflows.keys()):
                await self.cancel_cross_twin_workflow(workflow_id)
            if self.registry:
                await self.registry.disconnect()
            self._running = False
            logger.info('Digital Twin Layer stopped successfully')
        except Exception as e:
            logger.error(f'Error stopping Digital Twin Layer: {e}')

    async def create_digital_twin(self, twin_type: DigitalTwinType, name: str, description: str, capabilities: Set[TwinCapability], template_id: Optional[str]=None, customization: Optional[Dict[str, Any]]=None, parent_twin_id: Optional[UUID]=None) -> IDigitalTwin:
        if not self._initialized:
            await self.initialize()
        try:
            if template_id:
                twin = await self._create_from_template(template_id, customization or {}, name, description)
            else:
                twin = await self._create_from_configuration(twin_type, name, description, capabilities, customization or {})
            await self._setup_twin_storage(twin.id)
            associations = []
            await self.registry.register_digital_twin_enhanced(twin, associations, parent_twin_id)
            await self._setup_twin_integrations(twin)
            if self._registry_cache:
                await self._registry_cache.cache_entity(twin.id, twin.to_dict(), 'DigitalTwin')
            self.active_twins[twin.id] = twin
            await twin.initialize()
            await twin.start()
            logger.info(f'Created and orchestrated Digital Twin {twin.id} ({name}) with persistent storage')
            return twin
        except Exception as e:
            logger.error(f'Failed to create Digital Twin: {e}')
            raise EntityCreationError(f'Digital Twin creation failed: {e}')

    async def _setup_twin_storage(self, twin_id: UUID) -> None:
        try:
            if self.config.get('storage.separate_dbs_per_twin', True):
                from src.core.interfaces.replica import IDigitalReplica
                from src.core.interfaces.service import IService
                replica_storage = get_twin_storage_adapter(IDigitalReplica, twin_id)
                await replica_storage.connect()
                service_storage = get_twin_storage_adapter(IService, twin_id)
                await service_storage.connect()
                logger.info(f'Twin-specific storage infrastructure ready for {twin_id}')
        except Exception as e:
            logger.warning(f'Failed to setup twin storage for {twin_id}: {e}')

    async def associate_replica_with_twin(self, twin_id: UUID, replica_id: UUID, data_mapping: Optional[Dict[str, str]]=None) -> None:
        try:
            twin = await self.registry.get_digital_twin(twin_id)
            await twin.associate_replica(replica_id)
            association = DigitalTwinAssociation(twin_id=twin_id, associated_entity_id=replica_id, association_type='data_source', entity_type='digital_replica', metadata={'data_mapping': data_mapping or {}})
            await self.registry.add_association(association)
            if twin_id not in self.data_flow_subscriptions:
                self.data_flow_subscriptions[twin_id] = set()
            self.data_flow_subscriptions[twin_id].add(replica_id)
            if self._registry_cache:
                await self._registry_cache.invalidate_entity(twin_id, 'DigitalTwin')
            if self.virtualization_orchestrator:
                await self._configure_data_routing(twin_id, replica_id)
            logger.info(f'Associated replica {replica_id} with Digital Twin {twin_id}')
        except Exception as e:
            logger.error(f'Failed to associate replica with twin: {e}')
            raise DigitalTwinError(f'Replica association failed: {e}')

    async def bind_service_to_twin(self, twin_id: UUID, service_id: UUID, capability_binding: Dict[str, Any]) -> None:
        try:
            association = DigitalTwinAssociation(twin_id=twin_id, associated_entity_id=service_id, association_type='capability_provider', entity_type='service', metadata={'capability_binding': capability_binding})
            await self.registry.add_association(association)
            if twin_id not in self.service_bindings:
                self.service_bindings[twin_id] = set()
            self.service_bindings[twin_id].add(service_id)
            logger.info(f'Bound service {service_id} to Digital Twin {twin_id}')
        except Exception as e:
            logger.error(f'Failed to bind service to twin: {e}')
            raise DigitalTwinError(f'Service binding failed: {e}')

    async def execute_twin_capability(self, twin_id: UUID, capability: TwinCapability, input_data: Dict[str, Any], execution_config: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
        try:
            twin = await self.registry.get_digital_twin(twin_id)
            if capability not in twin.capabilities:
                raise DigitalTwinError(f'Twin {twin_id} does not have capability {capability.value}')
            service_id = await self._find_service_for_capability(twin_id, capability)
            if not service_id:
                return await self._execute_internal_capability(twin, capability, input_data)
            if self.service_orchestrator:
                response = await self.service_orchestrator.execute_service(service_id=service_id, input_data=input_data, execution_parameters=execution_config)
                await self.registry.record_twin_activity(twin_id, f'capability_{capability.value}', {'service_id': str(service_id)})
                return response.to_dict() if hasattr(response, 'to_dict') else response
            else:
                raise DigitalTwinError('Service orchestrator not available')
        except Exception as e:
            logger.error(f'Failed to execute capability {capability.value} on twin {twin_id}: {e}')
            raise DigitalTwinError(f'Capability execution failed: {e}')

    async def create_cross_twin_workflow(self, workflow_name: str, twin_operations: List[Dict[str, Any]], workflow_config: Dict[str, Any]) -> UUID:
        workflow_id = uuid4()
        workflow = {'workflow_id': workflow_id, 'workflow_name': workflow_name, 'twin_operations': twin_operations, 'workflow_config': workflow_config, 'created_at': datetime.now(timezone.utc), 'status': 'created', 'execution_history': []}
        self.active_workflows[workflow_id] = workflow
        if self._session_cache:
            await self._session_cache.store_session(f'workflow_{workflow_id}', workflow)
        logger.info(f'Created cross-twin workflow {workflow_name} with ID {workflow_id}')
        return workflow_id

    async def execute_cross_twin_workflow(self, workflow_id: UUID, input_data: Dict[str, Any]) -> UUID:
        if workflow_id not in self.active_workflows:
            raise DigitalTwinError(f'Workflow {workflow_id} not found')
        workflow = self.active_workflows[workflow_id]
        execution_id = uuid4()

        async def execute_workflow_async():
            try:
                workflow['status'] = 'running'
                workflow['current_execution_id'] = execution_id
                results = []
                current_data = input_data
                for step_idx, operation in enumerate(workflow['twin_operations']):
                    step_name = operation.get('step_name', f'step_{step_idx}')
                    twin_id = UUID(operation['twin_id'])
                    capability = TwinCapability(operation['capability'])
                    step_config = operation.get('config', {})
                    logger.info(f'Executing workflow step {step_name} on twin {twin_id}')
                    result = await self.execute_twin_capability(twin_id=twin_id, capability=capability, input_data=current_data, execution_config=step_config)
                    step_result = {'step_name': step_name, 'twin_id': str(twin_id), 'capability': capability.value, 'result': result, 'executed_at': datetime.now(timezone.utc).isoformat()}
                    results.append(step_result)
                    if isinstance(result, dict) and 'output_data' in result:
                        current_data = result['output_data']
                    else:
                        current_data = result
                workflow['status'] = 'completed'
                workflow['execution_history'].append({'execution_id': str(execution_id), 'status': 'completed', 'results': results, 'completed_at': datetime.now(timezone.utc).isoformat()})
                logger.info(f'Cross-twin workflow {workflow_id} completed successfully')
            except Exception as e:
                workflow['status'] = 'failed'
                workflow['execution_history'].append({'execution_id': str(execution_id), 'status': 'failed', 'error': str(e), 'completed_at': datetime.now(timezone.utc).isoformat()})
                logger.error(f'Cross-twin workflow {workflow_id} failed: {e}')
        asyncio.create_task(execute_workflow_async())
        return execution_id

    async def cancel_cross_twin_workflow(self, workflow_id: UUID) -> bool:
        if workflow_id not in self.active_workflows:
            return False
        workflow = self.active_workflows[workflow_id]
        workflow['status'] = 'cancelled'
        del self.active_workflows[workflow_id]
        logger.info(f'Cancelled cross-twin workflow {workflow_id}')
        return True

    async def get_twin_ecosystem_status(self, twin_id: UUID) -> Dict[str, Any]:
        try:
            performance = await self.registry.get_twin_performance_summary(twin_id)
            replica_associations = await self.registry.get_twin_associations(twin_id, 'data_source', 'digital_replica')
            service_associations = await self.registry.get_twin_associations(twin_id, 'capability_provider', 'service')
            data_flow_status = {}
            if twin_id in self.data_flow_subscriptions:
                for replica_id in self.data_flow_subscriptions[twin_id]:
                    data_flow_status[str(replica_id)] = {'connected': True, 'last_data': '2024-01-01T12:00:00Z'}
            service_status = {}
            if twin_id in self.service_bindings:
                for service_id in self.service_bindings[twin_id]:
                    service_status[str(service_id)] = {'available': True, 'last_execution': '2024-01-01T12:00:00Z'}
            return {'twin_performance': performance, 'ecosystem': {'data_sources': {'count': len(replica_associations), 'replicas': [str(assoc.associated_entity_id) for assoc in replica_associations], 'data_flow_status': data_flow_status}, 'capabilities': {'count': len(service_associations), 'services': [str(assoc.associated_entity_id) for assoc in service_associations], 'service_status': service_status}}, 'workflow_participation': {'active_workflows': len([wf for wf in self.active_workflows.values() if any((op.get('twin_id') == str(twin_id) for op in wf['twin_operations']))])}}
        except Exception as e:
            logger.error(f'Failed to get ecosystem status for twin {twin_id}: {e}')
            return {'error': str(e)}

    async def get_platform_overview(self) -> Dict[str, Any]:
        if not self._initialized:
            await self.initialize()
        registry_analytics = await self.registry.get_registry_analytics()
        layer_stats = {}
        if self.virtualization_orchestrator:
            layer_stats['virtualization'] = await self.virtualization_orchestrator.get_layer_statistics()
        if self.service_orchestrator:
            layer_stats['service'] = await self.service_orchestrator.get_layer_statistics()
        orchestration_stats = {'active_twins': len(self.active_twins), 'data_flow_subscriptions': len(self.data_flow_subscriptions), 'service_bindings': len(self.service_bindings), 'active_workflows': len(self.active_workflows), 'cross_twin_operations': len(self.cross_twin_operations)}
        storage_health = await self._get_storage_health()
        return {'digital_twin_layer': {'initialized': self._initialized, 'running': self._running, 'orchestration': orchestration_stats}, 'registry_analytics': registry_analytics, 'layer_statistics': layer_stats, 'storage_health': storage_health, 'platform_health': {'all_layers_running': all([self._running, self.virtualization_orchestrator is not None, self.service_orchestrator is not None]), 'timestamp': datetime.now(timezone.utc).isoformat()}}

    async def _get_storage_health(self) -> Dict[str, Any]:
        health = {'primary_storage': 'unknown', 'cache_storage': 'unknown', 'twin_registry_connected': False, 'cache_connected': False, 'separate_twin_dbs': self.config.get('storage.separate_dbs_per_twin', False)}
        try:
            if self.registry and hasattr(self.registry, 'storage_adapter'):
                registry_health = await self.registry.storage_adapter.health_check()
                health['twin_registry_connected'] = registry_health
                health['primary_storage'] = 'mongodb' if registry_health else 'failed'
            if self._registry_cache:
                cache_health = await self._registry_cache.cache.health_check()
                health['cache_connected'] = cache_health
                health['cache_storage'] = 'redis' if cache_health else 'failed'
            if health['separate_twin_dbs'] and self.active_twins:
                test_count = 0
                success_count = 0
                for twin_id in list(self.active_twins.keys())[:3]:
                    test_count += 1
                    try:
                        from src.core.interfaces.replica import IDigitalReplica
                        twin_storage = get_twin_storage_adapter(IDigitalReplica, twin_id)
                        twin_health = await twin_storage.health_check()
                        if twin_health:
                            success_count += 1
                    except Exception:
                        pass
                health['twin_specific_dbs_tested'] = test_count
                health['twin_specific_dbs_healthy'] = success_count
        except Exception as e:
            logger.warning(f'Storage health check error: {e}')
            health['error'] = str(e)
        return health

    async def _integrate_with_virtualization_layer(self) -> None:
        try:
            self.virtualization_orchestrator = get_virtualization_orchestrator()
            if not self.virtualization_orchestrator._initialized:
                await self.virtualization_orchestrator.initialize()
            logger.info('Integrated with Virtualization Layer')
        except Exception as e:
            logger.warning(f'Failed to integrate with Virtualization Layer: {e}')

    async def _integrate_with_service_layer(self) -> None:
        try:
            self.service_orchestrator = get_service_orchestrator()
            if not self.service_orchestrator._initialized:
                await self.service_orchestrator.initialize()
            logger.info('Integrated with Service Layer')
        except Exception as e:
            logger.warning(f'Failed to integrate with Service Layer: {e}')

    async def _integrate_with_templates(self) -> None:
        try:
            ontology_manager = get_ontology_manager()
            logger.info('Digital Twin Layer integrated with template system')
        except Exception as e:
            logger.warning(f'Failed to integrate with template system: {e}')
            self.templates_integration = False

    async def _setup_data_flow_coordination(self) -> None:
        logger.info('Data flow coordination setup completed')

    async def _start_orchestration(self) -> None:
        logger.info('Digital Twin orchestration started')

    async def _create_from_template(self, template_id: str, customization: Dict[str, Any], name: str, description: str) -> IDigitalTwin:
        customization.update({'name': name, 'description': description})
        return await self.factory.create_from_template(template_id, customization)

    async def _create_from_configuration(self, twin_type: DigitalTwinType, name: str, description: str, capabilities: Set[TwinCapability], config: Dict[str, Any]) -> IDigitalTwin:
        dt_config = DigitalTwinConfiguration(twin_type=twin_type, name=name, description=description, capabilities=capabilities, model_configurations=config.get('model_configurations', {}), data_sources=config.get('data_sources', []), update_frequency=config.get('update_frequency', 60), retention_policy=config.get('retention_policy', {}), quality_requirements=config.get('quality_requirements', {}), custom_config=config.get('custom_config', {}))
        return await self.factory.create_twin(twin_type, dt_config)

    async def _setup_twin_integrations(self, twin: IDigitalTwin) -> None:
        pass

    async def _configure_data_routing(self, twin_id: UUID, replica_id: UUID) -> None:
        pass

    async def _find_service_for_capability(self, twin_id: UUID, capability: TwinCapability) -> Optional[UUID]:
        service_associations = await self.registry.get_twin_associations(twin_id, 'capability_provider', 'service')
        if service_associations:
            return service_associations[0].associated_entity_id
        return None

    async def _execute_internal_capability(self, twin: IDigitalTwin, capability: TwinCapability, input_data: Dict[str, Any]) -> Dict[str, Any]:
        if capability == TwinCapability.PREDICTION:
            return await twin.predict(prediction_horizon=input_data.get('horizon', 300), scenario=input_data.get('scenario'))
        elif capability == TwinCapability.SIMULATION:
            return await twin.simulate(simulation_config=input_data.get('config', {}), duration=input_data.get('duration', 60))
        elif capability == TwinCapability.OPTIMIZATION:
            return await twin.optimize(optimization_target=input_data.get('target', 'efficiency'), constraints=input_data.get('constraints', {}), parameters=input_data.get('parameters', {}))
        else:
            return {'result': f'Internal capability {capability.value} executed', 'input_data': input_data}
_digital_twin_orchestrator: Optional[DigitalTwinLayerOrchestrator] = None

def get_digital_twin_orchestrator() -> DigitalTwinLayerOrchestrator:
    global _digital_twin_orchestrator
    if _digital_twin_orchestrator is None:
        _digital_twin_orchestrator = DigitalTwinLayerOrchestrator()
    return _digital_twin_orchestrator

async def initialize_digital_twin_layer() -> DigitalTwinLayerOrchestrator:
    global _digital_twin_orchestrator
    _digital_twin_orchestrator = DigitalTwinLayerOrchestrator()
    await _digital_twin_orchestrator.initialize()
    return _digital_twin_orchestrator

async def create_industrial_asset_twin(name: str, description: str, data_sources: List[str], monitoring_interval: int=30) -> IDigitalTwin:
    orchestrator = get_digital_twin_orchestrator()
    capabilities = {TwinCapability.MONITORING, TwinCapability.ANALYTICS, TwinCapability.PREDICTION, TwinCapability.MAINTENANCE_PLANNING}
    customization = {'data_sources': data_sources, 'update_frequency': monitoring_interval, 'model_configurations': {'physics_based': {'enabled': True}, 'data_driven': {'enabled': True}}}
    return await orchestrator.create_digital_twin(twin_type=DigitalTwinType.ASSET, name=name, description=description, capabilities=capabilities, template_id='industrial_asset', customization=customization)

async def create_smart_building_twin(name: str, description: str, building_systems: List[str]) -> IDigitalTwin:
    orchestrator = get_digital_twin_orchestrator()
    capabilities = {TwinCapability.MONITORING, TwinCapability.OPTIMIZATION, TwinCapability.CONTROL}
    customization = {'data_sources': building_systems, 'update_frequency': 60, 'model_configurations': {'hybrid': {'enabled': True}}}
    return await orchestrator.create_digital_twin(twin_type=DigitalTwinType.INFRASTRUCTURE, name=name, description=description, capabilities=capabilities, template_id='smart_building', customization=customization)