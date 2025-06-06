import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Type
from uuid import UUID, uuid4
from src.core.interfaces.base import BaseMetadata, EntityStatus
from src.core.interfaces.digital_twin import IDigitalTwin, IDigitalTwinFactory, DigitalTwinType, DigitalTwinState, DigitalTwinConfiguration, TwinModelType, TwinModel, TwinSnapshot, TwinCapability
from src.core.interfaces.replica import AggregatedData
from src.utils.exceptions import FactoryError, FactoryConfigurationError, EntityCreationError, DigitalTwinError
from src.utils.config import get_config
from enum import Enum
logger = logging.getLogger(__name__)

class DTAccessLevel(Enum):
    NONE = 'none'
    READ = 'read'
    WRITE = 'write'
    EXECUTE = 'execute'
    ADMIN = 'admin'

class StandardDigitalTwin(IDigitalTwin):

    def __init__(self, twin_id: UUID, configuration: DigitalTwinConfiguration, metadata: BaseMetadata, models: Optional[List[TwinModel]]=None, owner_id: Optional[UUID]=None, tenant_id: Optional[UUID]=None, security_enabled: bool=False):
        self._id = twin_id
        self._configuration = configuration
        self._metadata = metadata
        self._current_state = DigitalTwinState.LEARNING
        self._status = EntityStatus.CREATED
        self._integrated_models: Dict[UUID, TwinModel] = {}
        if models:
            for model in models:
                self._integrated_models[model.model_id] = model
        self._associated_replicas: Set[UUID] = set()
        self._twin_state: Dict[str, Any] = {}
        self._last_update: Optional[datetime] = None
        self._model_executions = 0
        self._data_updates = 0
        self._predictions_made = 0
        self._last_prediction: Optional[datetime] = None
        self._data_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._processing_task: Optional[asyncio.Task] = None
        self.security_enabled = security_enabled
        if security_enabled:
            self.owner_id = owner_id or uuid4()
            self.tenant_id = tenant_id or uuid4()
            self.authorized_users: Dict[UUID, DTAccessLevel] = {self.owner_id: DTAccessLevel.ADMIN}
            self.access_permissions: Dict[UUID, Set[str]] = {self.owner_id: {'read', 'write', 'execute', 'admin', 'manage_access'}}
            self.access_log: List[Dict[str, Any]] = []
            self.last_accessed_by: Optional[UUID] = None
            self.is_public = False
            self.shared_with_tenant = True
            self.dt_identity: Optional[Any] = None
        else:
            self.owner_id = owner_id
            self.tenant_id = tenant_id
            self.authorized_users = {}
            self.access_permissions = {}
            self.access_log = []
            self.last_accessed_by = None
            self.is_public = True
            self.shared_with_tenant = True
            self.dt_identity = None

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
    def twin_type(self) -> DigitalTwinType:
        return self._configuration.twin_type

    @property
    def name(self) -> str:
        return self._configuration.name

    @property
    def configuration(self) -> DigitalTwinConfiguration:
        return self._configuration

    @property
    def current_state(self) -> DigitalTwinState:
        return self._current_state

    @property
    def capabilities(self) -> Set[TwinCapability]:
        return self._configuration.capabilities

    @property
    def associated_replicas(self) -> List[UUID]:
        return list(self._associated_replicas)

    @property
    def integrated_models(self) -> List[TwinModel]:
        return list(self._integrated_models.values())

    def check_access(self, user_id: UUID, required_access: DTAccessLevel) -> bool:
        if not self.security_enabled:
            return True
        if user_id == self.owner_id:
            return True
        user_access = self.authorized_users.get(user_id, DTAccessLevel.NONE)
        access_hierarchy = {DTAccessLevel.ADMIN: 4, DTAccessLevel.EXECUTE: 3, DTAccessLevel.WRITE: 2, DTAccessLevel.READ: 1, DTAccessLevel.NONE: 0}
        return access_hierarchy[user_access] >= access_hierarchy[required_access]

    def grant_access(self, user_id: UUID, access_level: DTAccessLevel, granted_by: UUID) -> None:
        if not self.security_enabled:
            logger.warning(f'Attempted to grant access on non-secure twin {self._id}')
            return
        if not (granted_by == self.owner_id or self.authorized_users.get(granted_by) == DTAccessLevel.ADMIN):
            raise PermissionError('Only owner or admin can grant access')
        self.authorized_users[user_id] = access_level
        permissions = set()
        if access_level in [DTAccessLevel.READ, DTAccessLevel.WRITE, DTAccessLevel.EXECUTE, DTAccessLevel.ADMIN]:
            permissions.add('read')
        if access_level in [DTAccessLevel.WRITE, DTAccessLevel.EXECUTE, DTAccessLevel.ADMIN]:
            permissions.add('write')
        if access_level in [DTAccessLevel.EXECUTE, DTAccessLevel.ADMIN]:
            permissions.add('execute')
        if access_level == DTAccessLevel.ADMIN:
            permissions.update({'admin', 'manage_access'})
        self.access_permissions[user_id] = permissions
        self._log_access_change('grant', user_id, access_level, granted_by)

    def revoke_access(self, user_id: UUID, revoked_by: UUID) -> None:
        if not self.security_enabled:
            return
        if user_id == self.owner_id:
            raise PermissionError('Cannot revoke owner access')
        if not (revoked_by == self.owner_id or self.authorized_users.get(revoked_by) == DTAccessLevel.ADMIN):
            raise PermissionError('Only owner or admin can revoke access')
        self.authorized_users.pop(user_id, None)
        self.access_permissions.pop(user_id, None)
        self._log_access_change('revoke', user_id, DTAccessLevel.NONE, revoked_by)

    def log_access(self, user_id: UUID, operation: str, success: bool=True) -> None:
        if not self.security_enabled:
            return
        self.last_accessed_by = user_id
        log_entry = {'user_id': str(user_id), 'operation': operation, 'success': success, 'timestamp': datetime.now(timezone.utc).isoformat(), 'user_access_level': self.authorized_users.get(user_id, DTAccessLevel.NONE).value}
        self.access_log.append(log_entry)
        if len(self.access_log) > 100:
            self.access_log = self.access_log[-100:]

    def is_accessible_by_tenant_user(self, user_id: UUID, user_tenant_id: UUID) -> bool:
        if not self.security_enabled:
            return True
        if not self.tenant_id or user_tenant_id != self.tenant_id:
            return False
        if user_id in self.authorized_users:
            return True
        return self.shared_with_tenant

    def _log_access_change(self, action: str, target_user: UUID, access_level: DTAccessLevel, changed_by: UUID) -> None:
        if not self.security_enabled:
            return
        log_entry = {'action': action, 'target_user': str(target_user), 'access_level': access_level.value, 'changed_by': str(changed_by), 'timestamp': datetime.now(timezone.utc).isoformat()}
        self.access_log.append(log_entry)

    async def initialize(self) -> None:
        self._status = EntityStatus.INITIALIZING
        self._current_state = DigitalTwinState.LEARNING
        for model in self._integrated_models.values():
            await self._initialize_model(model)
        if self.security_enabled and self.owner_id and self.tenant_id:
            try:
                from src.layers.application.auth.user_registration import DigitalTwinIdentityService
                identity_service = DigitalTwinIdentityService()
                self.dt_identity = await identity_service.create_identity(twin_id=self._id, owner_id=self.owner_id, tenant_id=self.tenant_id)
                logger.info(f'Created Digital Twin identity for {self._id}')
            except Exception as e:
                logger.warning(f'Failed to create DT identity: {e}')
        await self._start_data_processing()
        self._status = EntityStatus.ACTIVE
        self._current_state = DigitalTwinState.OPERATIONAL
        logger.info(f'Digital Twin {self._id} ({self.twin_type.value}) initialized (security: {self.security_enabled})')

    async def start(self) -> None:
        if self._current_state not in [DigitalTwinState.OPERATIONAL, DigitalTwinState.MAINTENANCE]:
            await self.initialize()
        self._status = EntityStatus.ACTIVE
        self._current_state = DigitalTwinState.OPERATIONAL
        if not self._processing_task or self._processing_task.done():
            await self._start_data_processing()
        logger.info(f'Digital Twin {self._id} started')

    async def stop(self) -> None:
        self._status = EntityStatus.INACTIVE
        self._current_state = DigitalTwinState.MAINTENANCE
        if self._processing_task and (not self._processing_task.done()):
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass
        logger.info(f'Digital Twin {self._id} stopped')

    async def terminate(self) -> None:
        await self.stop()
        self._twin_state.clear()
        self._integrated_models.clear()
        self._associated_replicas.clear()
        self._status = EntityStatus.TERMINATED
        self._current_state = DigitalTwinState.OPERATIONAL
        logger.info(f'Digital Twin {self._id} terminated')

    async def receive_aggregated_data(self, data: AggregatedData) -> None:
        try:
            await self._data_queue.put(data)
            logger.debug(f'Received aggregated data from replica {data.source_replica_id}')
        except asyncio.QueueFull:
            logger.warning(f'Data queue full, dropping data from replica {data.source_replica_id}')

    async def update_state(self, new_data: Dict[str, Any]) -> None:
        self._twin_state.update(new_data)
        self._last_update = datetime.now(timezone.utc)
        self._data_updates += 1
        update_frequency = self._configuration.update_frequency
        if self._data_updates % max(update_frequency, 1) == 0:
            await self._trigger_model_updates()
        logger.debug(f'Updated Digital Twin {self._id} state with {len(new_data)} data points')

    async def execute_models(self, model_ids: Optional[List[UUID]]=None, input_data: Optional[Dict[str, Any]]=None) -> Dict[UUID, Dict[str, Any]]:
        if model_ids is None:
            model_ids = list(self._integrated_models.keys())
        execution_data = input_data or self._twin_state
        results = {}
        for model_id in model_ids:
            if model_id in self._integrated_models:
                model = self._integrated_models[model_id]
                try:
                    result = await self._execute_model(model, execution_data)
                    results[model_id] = result
                    self._model_executions += 1
                    logger.debug(f'Executed model {model.name} for Digital Twin {self._id}')
                except Exception as e:
                    logger.error(f'Model execution failed for {model.name}: {e}')
                    results[model_id] = {'error': str(e)}
        return results

    async def add_model(self, model: TwinModel) -> None:
        self._integrated_models[model.model_id] = model
        await self._initialize_model(model)
        logger.info(f'Added model {model.name} to Digital Twin {self._id}')

    async def remove_model(self, model_id: UUID) -> None:
        if model_id in self._integrated_models:
            model_name = self._integrated_models[model_id].name
            del self._integrated_models[model_id]
            logger.info(f'Removed model {model_name} from Digital Twin {self._id}')

    async def update_model(self, model: TwinModel) -> None:
        if model.model_id in self._integrated_models:
            self._integrated_models[model.model_id] = model
            await self._initialize_model(model)
            logger.info(f'Updated model {model.name} in Digital Twin {self._id}')

    async def associate_replica(self, replica_id: UUID) -> None:
        self._associated_replicas.add(replica_id)
        logger.info(f'Associated replica {replica_id} with Digital Twin {self._id}')

    async def disassociate_replica(self, replica_id: UUID) -> None:
        self._associated_replicas.discard(replica_id)
        logger.info(f'Disassociated replica {replica_id} from Digital Twin {self._id}')

    async def create_snapshot(self) -> TwinSnapshot:
        model_states = {}
        for model_id, model in self._integrated_models.items():
            model_states[model_id] = {'parameters': model.parameters, 'accuracy_metrics': model.accuracy_metrics, 'last_trained': datetime.now(timezone.utc).isoformat()}
        metrics = {'model_executions': self._model_executions, 'data_updates': self._data_updates, 'predictions_made': self._predictions_made, 'last_update': self._last_update.isoformat() if self._last_update else None, 'state_size': len(self._twin_state), 'associated_replicas_count': len(self._associated_replicas)}
        snapshot = TwinSnapshot(twin_id=self._id, snapshot_time=datetime.now(timezone.utc), state=self._twin_state.copy(), model_states=model_states, metrics=metrics, metadata={'twin_type': self.twin_type.value, 'current_state': self._current_state.value, 'capabilities': [cap.value for cap in self.capabilities]})
        logger.info(f'Created snapshot for Digital Twin {self._id}')
        return snapshot

    async def restore_from_snapshot(self, snapshot: TwinSnapshot) -> None:
        if snapshot.twin_id != self._id:
            raise DigitalTwinError(f'Snapshot twin ID {snapshot.twin_id} does not match current twin {self._id}')
        self._twin_state = snapshot.state.copy()
        for model_id, model_state in snapshot.model_states.items():
            if model_id in self._integrated_models:
                model = self._integrated_models[model_id]
                model.parameters.update(model_state.get('parameters', {}))
                model.accuracy_metrics.update(model_state.get('accuracy_metrics', {}))
        metrics = snapshot.metrics
        self._model_executions = metrics.get('model_executions', 0)
        self._data_updates = metrics.get('data_updates', 0)
        self._predictions_made = metrics.get('predictions_made', 0)
        self._last_update = datetime.now(timezone.utc)
        logger.info(f'Restored Digital Twin {self._id} from snapshot')

    async def get_performance_metrics(self, start_time: Optional[datetime]=None, end_time: Optional[datetime]=None) -> Dict[str, Any]:
        return {'twin_id': str(self._id), 'twin_type': self.twin_type.value, 'current_state': self._current_state.value, 'model_executions': self._model_executions, 'data_updates': self._data_updates, 'predictions_made': self._predictions_made, 'last_update': self._last_update.isoformat() if self._last_update else None, 'last_prediction': self._last_prediction.isoformat() if self._last_prediction else None, 'state_size': len(self._twin_state), 'integrated_models_count': len(self._integrated_models), 'associated_replicas_count': len(self._associated_replicas), 'queue_size': self._data_queue.qsize() if self._data_queue else 0, 'capabilities': [cap.value for cap in self.capabilities]}

    async def predict(self, prediction_horizon: int, scenario: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
        prediction_models = [model for model in self._integrated_models.values() if model.model_type in [TwinModelType.DATA_DRIVEN, TwinModelType.HYBRID]]
        if not prediction_models:
            return {'error': 'No prediction models available'}
        predictions = {}
        for model in prediction_models:
            try:
                input_data = self._twin_state.copy()
                if scenario:
                    input_data.update(scenario)
                result = await self._execute_prediction_model(model, input_data, prediction_horizon)
                predictions[model.name] = result
            except Exception as e:
                logger.error(f'Prediction failed for model {model.name}: {e}')
                predictions[model.name] = {'error': str(e)}
        self._predictions_made += 1
        self._last_prediction = datetime.now(timezone.utc)
        return {'prediction_horizon_seconds': prediction_horizon, 'predicted_at': self._last_prediction.isoformat(), 'scenario': scenario, 'predictions': predictions, 'confidence': self._calculate_prediction_confidence(predictions)}

    async def simulate(self, simulation_config: Dict[str, Any], duration: int) -> Dict[str, Any]:
        simulation_models = [model for model in self._integrated_models.values() if model.model_type in [TwinModelType.PHYSICS_BASED, TwinModelType.HYBRID]]
        if not simulation_models:
            return {'error': 'No simulation models available'}
        simulation_results = {}
        for model in simulation_models:
            try:
                result = await self._execute_simulation_model(model, simulation_config, duration)
                simulation_results[model.name] = result
            except Exception as e:
                logger.error(f'Simulation failed for model {model.name}: {e}')
                simulation_results[model.name] = {'error': str(e)}
        return {'simulation_duration_seconds': duration, 'simulation_config': simulation_config, 'executed_at': datetime.now(timezone.utc).isoformat(), 'results': simulation_results}

    async def optimize(self, optimization_target: str, constraints: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
        return {'optimization_target': optimization_target, 'constraints': constraints, 'parameters': parameters, 'optimized_values': {'target_value': 0.85, 'optimal_parameters': parameters, 'improvement': 0.15}, 'optimization_time_seconds': 5.0, 'iterations': 100, 'converged': True, 'executed_at': datetime.now(timezone.utc).isoformat()}

    def to_dict(self, include_security_details: bool=False) -> Dict[str, Any]:
        base_dict = {'id': str(self._id), 'twin_type': self.twin_type.value, 'name': self.name, 'description': self._configuration.description, 'current_state': self._current_state.value, 'status': self._status.value, 'capabilities': [cap.value for cap in self.capabilities], 'configuration': self._configuration.to_dict(), 'metadata': self._metadata.to_dict(), 'integrated_models': [model.to_dict() for model in self._integrated_models.values()], 'associated_replicas': [str(rid) for rid in self._associated_replicas], 'statistics': {'model_executions': self._model_executions, 'data_updates': self._data_updates, 'predictions_made': self._predictions_made, 'last_update': self._last_update.isoformat() if self._last_update else None}}
        if self.security_enabled:
            base_dict.update({'security_enabled': True, 'owner_id': str(self.owner_id) if self.owner_id else None, 'tenant_id': str(self.tenant_id) if self.tenant_id else None, 'is_public': self.is_public, 'shared_with_tenant': self.shared_with_tenant, 'authorized_users_count': len(self.authorized_users), 'last_accessed_by': str(self.last_accessed_by) if self.last_accessed_by else None})
            if include_security_details:
                base_dict.update({'authorized_users': {str(uid): level.value for uid, level in self.authorized_users.items()}, 'access_permissions': {str(uid): list(perms) for uid, perms in self.access_permissions.items()}, 'recent_access_log': self.access_log[-10:] if self.access_log else [], 'dt_identity': self.dt_identity.to_dict() if self.dt_identity else None})
        else:
            base_dict['security_enabled'] = False
        return base_dict

    def validate(self) -> bool:
        try:
            if not self._configuration.name:
                return False
            if not self._configuration.capabilities:
                return False
            if self._configuration.update_frequency <= 0:
                return False
            return True
        except Exception:
            return False

    async def _start_data_processing(self) -> None:

        async def process_data():
            while True:
                try:
                    data = await asyncio.wait_for(self._data_queue.get(), timeout=1.0)
                    await self._process_aggregated_data(data)
                    self._data_queue.task_done()
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f'Data processing error in Digital Twin {self._id}: {e}')
        self._processing_task = asyncio.create_task(process_data())

    async def _process_aggregated_data(self, data: AggregatedData) -> None:
        new_state_data = {}
        for key, value in data.aggregated_data.items():
            if data.quality_score >= 0.7:
                new_state_data[f'replica_{data.source_replica_id}_{key}'] = value
        if new_state_data:
            await self.update_state(new_state_data)

    async def _trigger_model_updates(self) -> None:
        auto_update_models = [model for model in self._integrated_models.values() if model.model_type == TwinModelType.DATA_DRIVEN]
        if auto_update_models:
            model_ids = [model.model_id for model in auto_update_models]
            await self.execute_models(model_ids)

    async def _initialize_model(self, model: TwinModel) -> None:
        logger.debug(f'Initialized model {model.name} ({model.model_type.value})')

    async def _execute_model(self, model: TwinModel, input_data: Dict[str, Any]) -> Dict[str, Any]:
        if model.model_type == TwinModelType.PHYSICS_BASED:
            return await self._execute_physics_model(model, input_data)
        elif model.model_type == TwinModelType.DATA_DRIVEN:
            return await self._execute_ml_model(model, input_data)
        elif model.model_type == TwinModelType.HYBRID:
            physics_result = await self._execute_physics_model(model, input_data)
            ml_result = await self._execute_ml_model(model, input_data)
            return {'physics': physics_result, 'ml': ml_result}
        else:
            return {'result': 'Model executed', 'model_type': model.model_type.value}

    async def _execute_physics_model(self, model: TwinModel, input_data: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(0.1)
        return {'model_type': 'physics_based', 'calculated_values': {'temperature': 25.5, 'pressure': 101.3, 'efficiency': 0.87}, 'computation_time': 0.1}

    async def _execute_ml_model(self, model: TwinModel, input_data: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(0.05)
        return {'model_type': 'data_driven', 'predictions': {'next_value': 42.0, 'confidence': 0.85, 'trend': 'increasing'}, 'inference_time': 0.05}

    async def _execute_prediction_model(self, model: TwinModel, input_data: Dict[str, Any], horizon: int) -> Dict[str, Any]:
        await asyncio.sleep(0.2)
        return {'predicted_value': 50.0 + horizon / 100, 'confidence': 0.8, 'prediction_interval': [45.0, 55.0], 'horizon_seconds': horizon}

    async def _execute_simulation_model(self, model: TwinModel, config: Dict[str, Any], duration: int) -> Dict[str, Any]:
        await asyncio.sleep(0.5)
        return {'simulation_steps': duration // 10, 'final_state': {'value': 100.0, 'status': 'stable'}, 'trajectory': [i * 10 for i in range(duration // 10)], 'duration_seconds': duration}

    def _calculate_prediction_confidence(self, predictions: Dict[str, Any]) -> float:
        confidences = []
        for prediction in predictions.values():
            if isinstance(prediction, dict) and 'confidence' in prediction:
                confidences.append(prediction['confidence'])
        return sum(confidences) / len(confidences) if confidences else 0.5

class DigitalTwinFactory(IDigitalTwinFactory):

    def __init__(self):
        self.config = get_config()
        self._supported_types = list(DigitalTwinType)
        self._model_templates: Dict[str, TwinModel] = {}
        self._load_default_model_templates()

    async def create_twin(self, twin_type: DigitalTwinType, config: DigitalTwinConfiguration, models: Optional[List[TwinModel]]=None, metadata: Optional[BaseMetadata]=None, owner_id: Optional[UUID]=None, tenant_id: Optional[UUID]=None, security_enabled: bool=False) -> IDigitalTwin:
        try:
            if not self.validate_twin_config(twin_type, config):
                raise FactoryConfigurationError('Invalid Digital Twin configuration')
            if metadata is None:
                creator_id = owner_id or uuid4()
                custom_metadata = {'security_enabled': security_enabled}
                if tenant_id:
                    custom_metadata['tenant_id'] = str(tenant_id)
                metadata = BaseMetadata(entity_id=uuid4(), timestamp=datetime.now(timezone.utc), version='1.0.0', created_by=creator_id, custom=custom_metadata)
            twin = StandardDigitalTwin(twin_id=metadata.id, configuration=config, metadata=metadata, models=models, owner_id=owner_id, tenant_id=tenant_id, security_enabled=security_enabled)
            logger.info(f'Created Digital Twin {metadata.id} (security: {security_enabled})')
            return twin
        except Exception as e:
            logger.error(f'Failed to create Digital Twin: {e}')
            raise EntityCreationError(f'Digital Twin creation failed: {e}')

    async def create_secure_twin(self, twin_type: DigitalTwinType, config: DigitalTwinConfiguration, owner_id: UUID, tenant_id: UUID, models: Optional[List[TwinModel]]=None, metadata: Optional[BaseMetadata]=None, authorized_users: Optional[Dict[UUID, DTAccessLevel]]=None) -> StandardDigitalTwin:
        twin = await self.create_twin(twin_type=twin_type, config=config, models=models, metadata=metadata, owner_id=owner_id, tenant_id=tenant_id, security_enabled=True)
        if authorized_users:
            for user_id, access_level in authorized_users.items():
                twin.grant_access(user_id, access_level, owner_id)
        return twin

    async def create_from_template(self, template_name: str, customization: Optional[Dict[str, Any]]=None, metadata: Optional[BaseMetadata]=None) -> IDigitalTwin:
        template = self._get_twin_template(template_name)
        if not template:
            raise FactoryConfigurationError(f'Digital Twin template {template_name} not found')
        if customization:
            template = self._apply_template_customization(template, customization)
        twin_type = DigitalTwinType(template['twin_type'])
        config = DigitalTwinConfiguration(twin_type=twin_type, name=template['name'], description=template['description'], capabilities=set((TwinCapability(cap) for cap in template['capabilities'])), model_configurations=template.get('model_configurations', {}), data_sources=template.get('data_sources', []), update_frequency=template.get('update_frequency', 60), retention_policy=template.get('retention_policy', {}), quality_requirements=template.get('quality_requirements', {}), custom_config=template.get('custom_config', {}))
        models = []
        for model_template_id in template.get('model_templates', []):
            if model_template_id in self._model_templates:
                models.append(self._model_templates[model_template_id])
        return await self.create_twin(twin_type, config, models, metadata)

    def get_supported_twin_types(self) -> List[DigitalTwinType]:
        return self._supported_types.copy()

    def get_available_templates(self) -> List[str]:
        return ['industrial_asset', 'smart_building', 'iot_device_system', 'production_line', 'energy_system']

    def get_template_schema(self, template_name: str) -> Dict[str, Any]:
        return {'type': 'object', 'properties': {'twin_type': {'type': 'string', 'enum': [t.value for t in DigitalTwinType]}, 'name': {'type': 'string'}, 'description': {'type': 'string'}, 'capabilities': {'type': 'array', 'items': {'type': 'string'}}, 'model_configurations': {'type': 'object'}, 'data_sources': {'type': 'array', 'items': {'type': 'string'}}, 'update_frequency': {'type': 'integer', 'minimum': 1}, 'retention_policy': {'type': 'object'}, 'quality_requirements': {'type': 'object'}}, 'required': ['twin_type', 'name', 'capabilities']}

    def validate_twin_config(self, twin_type: DigitalTwinType, config: DigitalTwinConfiguration) -> bool:
        try:
            if config.twin_type != twin_type:
                return False
            if not config.name:
                return False
            if not config.capabilities:
                return False
            if config.update_frequency <= 0:
                return False
            if twin_type == DigitalTwinType.ASSET:
                if TwinCapability.MONITORING not in config.capabilities:
                    return False
            return True
        except Exception:
            return False

    async def create(self, config: Dict[str, Any], metadata: Optional[BaseMetadata]=None) -> IDigitalTwin:
        try:
            if not self.validate_config(config):
                raise FactoryConfigurationError('Invalid Digital Twin configuration')
            twin_type = DigitalTwinType(config['twin_type'])
            dt_config = DigitalTwinConfiguration(twin_type=twin_type, name=config['name'], description=config.get('description', ''), capabilities=set((TwinCapability(cap) for cap in config.get('capabilities', []))), model_configurations=config.get('model_configurations', {}), data_sources=config.get('data_sources', []), update_frequency=config.get('update_frequency', 60), retention_policy=config.get('retention_policy', {}), quality_requirements=config.get('quality_requirements', {}), custom_config=config.get('custom_config', {}))
            models = []
            for model_config in config.get('models', []):
                model = TwinModel(model_id=uuid4(), model_type=TwinModelType(model_config['model_type']), name=model_config['name'], version=model_config.get('version', '1.0.0'), parameters=model_config.get('parameters', {}), inputs=model_config.get('inputs', []), outputs=model_config.get('outputs', []), accuracy_metrics=model_config.get('accuracy_metrics', {}))
                models.append(model)
            return await self.create_twin(twin_type, dt_config, models, metadata)
        except Exception as e:
            logger.error(f'Failed to create Digital Twin: {e}')
            raise EntityCreationError(f'Digital Twin creation failed: {e}')

    async def create_from_template_v2(self, template_id: str, config_overrides: Optional[Dict[str, Any]]=None, metadata: Optional[BaseMetadata]=None) -> IDigitalTwin:
        return await self.create_from_template(template_id, config_overrides, metadata)

    def validate_config(self, config: Dict[str, Any]) -> bool:
        required_fields = ['twin_type', 'name', 'capabilities']
        for field in required_fields:
            if field not in config:
                return False
        try:
            DigitalTwinType(config['twin_type'])
            for cap in config['capabilities']:
                TwinCapability(cap)
            return True
        except (ValueError, TypeError):
            return False

    def get_supported_types(self) -> List[str]:
        return [dt.value for dt in self._supported_types]

    def get_config_schema(self, entity_type: str) -> Dict[str, Any]:
        return {'type': 'object', 'properties': {'twin_type': {'type': 'string', 'enum': [t.value for t in DigitalTwinType]}, 'name': {'type': 'string'}, 'description': {'type': 'string'}, 'capabilities': {'type': 'array', 'items': {'type': 'string'}}, 'model_configurations': {'type': 'object'}, 'data_sources': {'type': 'array', 'items': {'type': 'string'}}, 'update_frequency': {'type': 'integer', 'minimum': 1}, 'retention_policy': {'type': 'object'}, 'quality_requirements': {'type': 'object'}, 'models': {'type': 'array'}}, 'required': ['twin_type', 'name', 'capabilities']}

    def _load_default_model_templates(self) -> None:
        physics_model = TwinModel(model_id=uuid4(), model_type=TwinModelType.PHYSICS_BASED, name='Basic Physics Model', version='1.0.0', parameters={'gravity': 9.81, 'friction': 0.1}, inputs=['force', 'mass'], outputs=['acceleration', 'velocity'], accuracy_metrics={'rmse': 0.05})
        self._model_templates['basic_physics'] = physics_model
        ml_model = TwinModel(model_id=uuid4(), model_type=TwinModelType.DATA_DRIVEN, name='Basic ML Model', version='1.0.0', parameters={'learning_rate': 0.01, 'epochs': 100}, inputs=['sensor_data', 'historical_data'], outputs=['prediction', 'confidence'], accuracy_metrics={'accuracy': 0.92, 'f1_score': 0.89})
        self._model_templates['basic_ml'] = ml_model
        logger.info(f'Loaded {len(self._model_templates)} model templates')

    def _get_twin_template(self, template_name: str) -> Optional[Dict[str, Any]]:
        templates = {'industrial_asset': {'twin_type': DigitalTwinType.ASSET.value, 'name': 'Industrial Asset Twin', 'description': 'Digital Twin for industrial assets with monitoring and prediction', 'capabilities': [TwinCapability.MONITORING.value, TwinCapability.ANALYTICS.value, TwinCapability.PREDICTION.value, TwinCapability.MAINTENANCE_PLANNING.value], 'model_configurations': {TwinModelType.PHYSICS_BASED.value: {'enabled': True}, TwinModelType.DATA_DRIVEN.value: {'enabled': True}}, 'data_sources': ['sensors', 'maintenance_logs', 'operational_data'], 'update_frequency': 30, 'model_templates': ['basic_physics', 'basic_ml']}, 'smart_building': {'twin_type': DigitalTwinType.INFRASTRUCTURE.value, 'name': 'Smart Building Twin', 'description': 'Digital Twin for smart building management', 'capabilities': [TwinCapability.MONITORING.value, TwinCapability.OPTIMIZATION.value, TwinCapability.CONTROL.value], 'model_configurations': {TwinModelType.HYBRID.value: {'enabled': True}}, 'data_sources': ['hvac_sensors', 'occupancy_sensors', 'energy_meters'], 'update_frequency': 60, 'model_templates': ['basic_physics']}}
        return templates.get(template_name)

    def _apply_template_customization(self, template: Dict[str, Any], customization: Dict[str, Any]) -> Dict[str, Any]:
        customized = template.copy()
        for key, value in customization.items():
            if key in customized:
                if isinstance(customized[key], dict) and isinstance(value, dict):
                    customized[key].update(value)
                else:
                    customized[key] = value
        return customized