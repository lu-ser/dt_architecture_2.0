import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from uuid import UUID
from enum import Enum
from src.layers.digital_twin import get_digital_twin_orchestrator
from src.layers.service import get_service_orchestrator
from src.layers.virtualization import get_virtualization_orchestrator
from src.utils.type_converter import TypeConverter
from src.core.interfaces.digital_twin import TwinCapability
from src.core.interfaces.service import ServiceType, ServicePriority
from src.core.interfaces.replica import ReplicaType
from src.utils.exceptions import ValidationError
from src.utils.exceptions import APIGatewayError
from src.utils.config import get_config
from src.core.interfaces.replica import DataAggregationMode
from src.layers.application.auth import AuthContext, AuthSubjectType
from src.layers.digital_twin.dt_factory import DTAccessLevel
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

class RequestType(Enum):
    DIGITAL_TWIN = 'digital_twin'
    SERVICE = 'service'
    REPLICA = 'replica'
    WORKFLOW = 'workflow'
    ANALYTICS = 'analytics'
    REAL_TIME = 'real_time'

class APIGateway:

    def __init__(self):
        self.config = get_config()
        self.dt_orchestrator = None
        self.service_orchestrator = None
        self.virtualization_orchestrator = None
        self._initialized = False
        self._layer_connections = {}
        logger.info('API Gateway initialized')
        self.security_enabled = self.config.get('security.enabled', True)
        self.enforce_tenant_isolation = self.config.get('security.enforce_tenant_isolation', True)
        self.require_ownership_for_write = self.config.get('security.require_ownership_for_write', True)

    async def initialize(self) -> None:
        if self._initialized:
            return
        try:
            logger.info('Initializing API Gateway...')
            await self._connect_to_layers()
            self._initialized = True
            logger.info('API Gateway initialization completed')
        except Exception as e:
            logger.error(f'Failed to initialize API Gateway: {e}')
            raise APIGatewayError(f'Gateway initialization failed: {e}')

    async def _connect_to_layers(self) -> None:
        try:
            self.dt_orchestrator = get_digital_twin_orchestrator()
            if not self.dt_orchestrator._initialized:
                await self.dt_orchestrator.initialize()
            self._layer_connections['digital_twin'] = True
            self.service_orchestrator = get_service_orchestrator()
            if not self.service_orchestrator._initialized:
                await self.service_orchestrator.initialize()
            self._layer_connections['service'] = True
            self.virtualization_orchestrator = get_virtualization_orchestrator()
            if not self.virtualization_orchestrator._initialized:
                await self.virtualization_orchestrator.initialize()
            self._layer_connections['virtualization'] = True
            logger.info('Connected to all platform layers')
        except Exception as e:
            logger.error(f'Failed to connect to layers: {e}')
            raise APIGatewayError(f'Layer connection failed: {e}')

    async def get_digital_twin(self, twin_id: UUID, auth_context: Optional[AuthContext]=None) -> Dict[str, Any]:
        try:
            twin = await self.dt_orchestrator.registry.get_digital_twin(twin_id)
            if self.security_enabled and auth_context and hasattr(twin, 'security_enabled') and twin.security_enabled:
                user_id = auth_context.subject_id
                user_tenant_id = self._get_user_tenant_id(auth_context)
                if self.enforce_tenant_isolation and (not twin.is_accessible_by_tenant_user(user_id, user_tenant_id)):
                    raise APIGatewayError(f'Digital Twin {twin_id} not accessible from your tenant')
                if not twin.check_access(user_id, DTAccessLevel.READ):
                    raise APIGatewayError(f'Insufficient permissions to access Digital Twin {twin_id}')
                twin.log_access(user_id, 'read', True)
                include_security_details = twin.check_access(user_id, DTAccessLevel.ADMIN)
                return twin.to_dict(include_security_details=include_security_details)
            return twin.to_dict()
        except Exception as e:
            logger.error(f'Failed to get Digital Twin {twin_id}: {e}')
            raise APIGatewayError(f'Failed to retrieve Digital Twin: {e}')

    async def create_digital_twin(self, twin_config: Dict[str, Any], user_id: Optional[UUID]=None, auth_context: Optional[AuthContext]=None) -> Dict[str, Any]:
        try:
            try:
                converted_config = TypeConverter.convert_digital_twin_config(twin_config)
            except ValidationError as e:
                raise APIGatewayError(str(e))
            twin_type = converted_config['twin_type']
            capabilities = converted_config['capabilities']
            name = twin_config['name']
            description = twin_config.get('description', '')
            template_id = twin_config.get('template_id')
            customization = twin_config.get('customization')
            parent_twin_id = twin_config.get('parent_twin_id')
            security_enabled = twin_config.get('security_enabled', self.security_enabled)
            owner_id = user_id
            tenant_id = None
            if auth_context and auth_context.subject_type == AuthSubjectType.USER:
                owner_id = auth_context.subject_id
                tenant_id = self._get_user_tenant_id(auth_context)
                if not tenant_id and security_enabled:
                    raise APIGatewayError('User must belong to a tenant to create secure Digital Twins')
            if template_id:
                if security_enabled and owner_id and tenant_id:
                    twin = await self._create_secure_twin_from_template(template_id, owner_id, tenant_id, customization, twin_config)
                else:
                    twin = await self.dt_orchestrator.create_digital_twin(twin_type=twin_type, name=name, description=description, capabilities=capabilities, template_id=template_id, customization=customization, parent_twin_id=parent_twin_id)
            else:
                twin = await self.dt_orchestrator.create_digital_twin(twin_type=twin_type, name=name, description=description, capabilities=capabilities, template_id=template_id, customization=customization, parent_twin_id=parent_twin_id)
                if security_enabled and owner_id and tenant_id:
                    await self._upgrade_twin_to_secure(twin, owner_id, tenant_id)
            logger.info(f'Created Digital Twin {twin.id} (security: {security_enabled})')
            return twin.to_dict()
        except Exception as e:
            logger.error(f'Failed to create Digital Twin: {e}')
            raise APIGatewayError(f'Digital Twin creation failed: {e}')

    async def execute_twin_capability(self, twin_id: UUID, capability: str, input_data: Dict[str, Any], execution_config: Optional[Dict[str, Any]]=None, auth_context: Optional[AuthContext]=None) -> Dict[str, Any]:
        try:
            twin = await self.dt_orchestrator.registry.get_digital_twin(twin_id)
            if self.security_enabled and auth_context and hasattr(twin, 'security_enabled') and twin.security_enabled:
                user_id = auth_context.subject_id
                user_tenant_id = self._get_user_tenant_id(auth_context)
                if self.enforce_tenant_isolation and (not twin.is_accessible_by_tenant_user(user_id, user_tenant_id)):
                    raise APIGatewayError('Twin not accessible from your tenant')
                if not twin.check_access(user_id, DTAccessLevel.EXECUTE):
                    raise APIGatewayError('Insufficient permissions to execute capabilities')
                twin.log_access(user_id, f'execute_{capability}', True)
            capability_enum = TwinCapability(capability)
            result = await self.dt_orchestrator.execute_twin_capability(twin_id=twin_id, capability=capability_enum, input_data=input_data, execution_config=execution_config)
            return {'twin_id': str(twin_id), 'capability': capability, 'result': result, 'executed_at': datetime.now(timezone.utc).isoformat(), 'executed_by': str(auth_context.subject_id) if auth_context else None}
        except Exception as e:
            logger.error(f'Failed to execute capability {capability} on twin {twin_id}: {e}')
            if auth_context:
                try:
                    twin = await self.dt_orchestrator.registry.get_digital_twin(twin_id)
                    if hasattr(twin, 'security_enabled') and twin.security_enabled:
                        twin.log_access(auth_context.subject_id, f'execute_{capability}', False)
                except:
                    pass
            raise APIGatewayError(f'Capability execution failed: {e}')

    async def get_twin_ecosystem_status(self, twin_id: UUID) -> Dict[str, Any]:
        try:
            return await self.dt_orchestrator.get_twin_ecosystem_status(twin_id)
        except Exception as e:
            logger.error(f'Failed to get ecosystem status for twin {twin_id}: {e}')
            raise APIGatewayError(f'Ecosystem status retrieval failed: {e}')

    async def get_service(self, service_id: UUID) -> Dict[str, Any]:
        try:
            service = await self.service_orchestrator.registry.get_service(service_id)
            return service.to_dict()
        except Exception as e:
            logger.error(f'Failed to get Service {service_id}: {e}')
            raise APIGatewayError(f'Failed to retrieve Service: {e}')

    async def create_service(self, service_config: Dict[str, Any], user_id: Optional[UUID]=None) -> Dict[str, Any]:
        try:
            if 'template_id' in service_config:
                service = await self.service_orchestrator.create_service_from_template(template_id=service_config['template_id'], digital_twin_id=UUID(service_config['digital_twin_id']), instance_name=service_config['instance_name'], overrides=service_config.get('overrides', {}))
            else:
                service = await self.service_orchestrator.create_service_from_definition(definition_id=service_config['definition_id'], digital_twin_id=UUID(service_config['digital_twin_id']), instance_name=service_config['instance_name'], parameters=service_config.get('parameters', {}), execution_config=service_config.get('execution_config', {}))
            logger.info(f'Created Service {service.id} via API Gateway')
            return service.to_dict()
        except Exception as e:
            logger.error(f'Failed to create Service: {e}')
            raise APIGatewayError(f'Service creation failed: {e}')

    async def execute_service(self, service_id: UUID, input_data: Dict[str, Any], execution_parameters: Optional[Dict[str, Any]]=None, async_execution: bool=False) -> Dict[str, Any]:
        try:
            result = await self.service_orchestrator.execute_service(service_id=service_id, input_data=input_data, execution_parameters=execution_parameters, async_execution=async_execution)
            if async_execution:
                return {'execution_id': str(result), 'service_id': str(service_id), 'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat()}
            else:
                return result.to_dict() if hasattr(result, 'to_dict') else result
        except Exception as e:
            logger.error(f'Failed to execute Service {service_id}: {e}')
            raise APIGatewayError(f'Service execution failed: {e}')

    async def get_replica(self, replica_id: UUID) -> Dict[str, Any]:
        try:
            replica = await self.virtualization_orchestrator.registry.get_digital_replica(replica_id)
            return replica.to_dict()
        except Exception as e:
            logger.error(f'Failed to get Digital Replica {replica_id}: {e}')
            raise APIGatewayError(f'Failed to retrieve Digital Replica: {e}')

    async def create_replica(self, replica_config: Dict[str, Any], user_id: Optional[UUID]=None) -> Dict[str, Any]:
        try:
            if 'parent_digital_twin_id' in replica_config:
                twin_id = replica_config['parent_digital_twin_id']
                if isinstance(twin_id, str):
                    try:
                        replica_config['parent_digital_twin_id'] = UUID(twin_id)
                    except ValueError as e:
                        raise APIGatewayError(f'Invalid parent_digital_twin_id format: {twin_id}')
                elif not isinstance(twin_id, UUID):
                    raise APIGatewayError(f'parent_digital_twin_id must be UUID or string, got {type(twin_id)}')
            if 'template_id' in replica_config:
                replica = await self.virtualization_orchestrator.create_replica_from_template(template_id=replica_config['template_id'], parent_digital_twin_id=replica_config['parent_digital_twin_id'], device_ids=replica_config['device_ids'], overrides=replica_config.get('overrides', {}))
            else:
                replica = await self.virtualization_orchestrator.create_replica_from_configuration(replica_type=ReplicaType(replica_config['replica_type']), parent_digital_twin_id=replica_config['parent_digital_twin_id'], device_ids=replica_config['device_ids'], aggregation_mode=DataAggregationMode(replica_config['aggregation_mode']), configuration=replica_config.get('configuration', {}))
            logger.info(f'Created Digital Replica {replica.id} via API Gateway')
            return replica.to_dict()
        except Exception as e:
            logger.error(f'Failed to create Digital Replica: {e}')
            raise APIGatewayError(f'Digital Replica creation failed: {e}')

    async def create_cross_twin_workflow(self, workflow_config: Dict[str, Any], user_id: Optional[UUID]=None) -> Dict[str, Any]:
        try:
            workflow_id = await self.dt_orchestrator.create_cross_twin_workflow(workflow_name=workflow_config['workflow_name'], twin_operations=workflow_config['twin_operations'], workflow_config=workflow_config.get('config', {}))
            return {'workflow_id': str(workflow_id), 'workflow_name': workflow_config['workflow_name'], 'status': 'created', 'created_at': datetime.now(timezone.utc).isoformat()}
        except Exception as e:
            logger.error(f'Failed to create cross-twin workflow: {e}')
            raise APIGatewayError(f'Workflow creation failed: {e}')

    async def execute_workflow(self, workflow_id: UUID, input_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            execution_id = await self.dt_orchestrator.execute_cross_twin_workflow(workflow_id=workflow_id, input_data=input_data)
            return {'workflow_id': str(workflow_id), 'execution_id': str(execution_id), 'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat()}
        except Exception as e:
            logger.error(f'Failed to execute workflow {workflow_id}: {e}')
            raise APIGatewayError(f'Workflow execution failed: {e}')

    async def discover_entities(self, entity_type: RequestType, criteria: Dict[str, Any], auth_context: Optional[AuthContext]=None) -> List[Dict[str, Any]]:
        try:
            if self.security_enabled and auth_context and self.enforce_tenant_isolation:
                user_tenant_id = self._get_user_tenant_id(auth_context)
                if user_tenant_id:
                    criteria['tenant_id'] = str(user_tenant_id)
            if entity_type == RequestType.DIGITAL_TWIN:
                twins = await self.dt_orchestrator.registry.discover_twins_advanced(criteria)
                accessible_twins = []
                for twin in twins:
                    if self._can_access_twin(twin, auth_context, DTAccessLevel.READ):
                        accessible_twins.append(twin.to_dict())
                return accessible_twins
            elif entity_type == RequestType.SERVICE:
                services = await self.service_orchestrator.discover_services(criteria)
                return services
            elif entity_type == RequestType.REPLICA:
                replicas = await self.virtualization_orchestrator.discover_replicas(criteria)
                return replicas
            else:
                raise APIGatewayError(f'Unsupported entity type for discovery: {entity_type}')
        except Exception as e:
            logger.error(f'Failed to discover {entity_type.value} entities: {e}')
            raise APIGatewayError(f'Entity discovery failed: {e}')

    async def manage_twin_access(self, twin_id: UUID, target_user_id: UUID, access_level: str, action: str, auth_context: AuthContext) -> Dict[str, Any]:
        if not self.security_enabled:
            raise APIGatewayError('Security not enabled - access management not available')
        twin = await self.dt_orchestrator.registry.get_digital_twin(twin_id)
        if not hasattr(twin, 'security_enabled') or not twin.security_enabled:
            raise APIGatewayError('Access management only available for secure twins')
        user_id = auth_context.subject_id
        if not twin.check_access(user_id, DTAccessLevel.ADMIN):
            raise APIGatewayError('Admin access required to manage permissions')
        try:
            if action == 'grant':
                access_level_enum = DTAccessLevel(access_level)
                twin.grant_access(target_user_id, access_level_enum, user_id)
                message = f'Granted {access_level} access to user {target_user_id}'
            elif action == 'revoke':
                twin.revoke_access(target_user_id, user_id)
                message = f'Revoked access for user {target_user_id}'
            else:
                raise ValidationError("Action must be 'grant' or 'revoke'")
            if self._registry_cache:
                await self._registry_cache.invalidate_entity(twin_id, 'DigitalTwin')
            return {'twin_id': str(twin_id), 'action': action, 'target_user': str(target_user_id), 'access_level': access_level if action == 'grant' else None, 'message': message, 'performed_by': str(user_id), 'timestamp': datetime.now(timezone.utc).isoformat()}
        except Exception as e:
            logger.error(f'Failed to {action} access: {e}')
            raise APIGatewayError(f'Access management failed: {e}')

    async def get_user_twins(self, auth_context: AuthContext) -> Dict[str, Any]:
        if not self.security_enabled:
            criteria = {}
            all_twins = await self.discover_entities(RequestType.DIGITAL_TWIN, criteria, auth_context)
            return {'user_id': str(auth_context.subject_id), 'twins': {'all': all_twins}, 'summary': {'total_accessible': len(all_twins)}, 'security_enabled': False}
        user_id = auth_context.subject_id
        user_tenant_id = self._get_user_tenant_id(auth_context)
        criteria = {'tenant_id': str(user_tenant_id)} if user_tenant_id else {}
        all_twins = await self.discover_entities(RequestType.DIGITAL_TWIN, criteria, auth_context)
        owned_twins = []
        admin_twins = []
        write_twins = []
        read_twins = []
        for twin_data in all_twins:
            twin_id = UUID(twin_data['id'])
            try:
                twin = await self.dt_orchestrator.registry.get_digital_twin(twin_id)
                if hasattr(twin, 'security_enabled') and twin.security_enabled:
                    if twin.owner_id == user_id:
                        owned_twins.append(twin_data)
                    elif twin.check_access(user_id, DTAccessLevel.ADMIN):
                        admin_twins.append(twin_data)
                    elif twin.check_access(user_id, DTAccessLevel.WRITE):
                        write_twins.append(twin_data)
                    else:
                        read_twins.append(twin_data)
                else:
                    read_twins.append(twin_data)
            except:
                continue
        return {'user_id': str(user_id), 'tenant_id': str(user_tenant_id) if user_tenant_id else None, 'twins': {'owned': owned_twins, 'admin_access': admin_twins, 'write_access': write_twins, 'read_access': read_twins}, 'summary': {'total_accessible': len(all_twins), 'owned_count': len(owned_twins), 'admin_count': len(admin_twins), 'write_count': len(write_twins), 'read_count': len(read_twins)}, 'security_enabled': True}

    async def get_platform_overview(self) -> Dict[str, Any]:
        try:
            return await self.dt_orchestrator.get_platform_overview()
        except Exception as e:
            logger.error(f'Failed to get platform overview: {e}')
            raise APIGatewayError(f'Platform overview retrieval failed: {e}')

    def _get_user_tenant_id(self, auth_context: AuthContext) -> Optional[UUID]:
        if not auth_context or not auth_context.metadata:
            return None
        tenant_id_str = auth_context.metadata.get('tenant_id')
        if tenant_id_str:
            try:
                return UUID(tenant_id_str)
            except ValueError:
                logger.warning(f'Invalid tenant_id format in auth context: {tenant_id_str}')
        return None

    def _can_access_twin(self, twin, auth_context: Optional[AuthContext], required_access: DTAccessLevel) -> bool:
        if not self.security_enabled or not auth_context:
            return True
        if not hasattr(twin, 'security_enabled') or not twin.security_enabled:
            return True
        user_id = auth_context.subject_id
        user_tenant_id = self._get_user_tenant_id(auth_context)
        if self.enforce_tenant_isolation and (not twin.is_accessible_by_tenant_user(user_id, user_tenant_id)):
            return False
        return twin.check_access(user_id, required_access)

    async def _create_secure_twin_from_template(self, template_id: str, owner_id: UUID, tenant_id: UUID, customization: Optional[Dict[str, Any]], twin_config: Dict[str, Any]) -> Any:
        authorized_users = {}
        if 'authorized_users' in twin_config:
            for user_data in twin_config['authorized_users']:
                user_id = UUID(user_data['user_id'])
                access_level = DTAccessLevel(user_data['access_level'])
                authorized_users[user_id] = access_level
        raise NotImplementedError('Secure template creation needs factory integration')

    async def _upgrade_twin_to_secure(self, twin, owner_id: UUID, tenant_id: UUID) -> None:
        if hasattr(twin, 'security_enabled'):
            twin.security_enabled = True
            twin.owner_id = owner_id
            twin.tenant_id = tenant_id
            twin.authorized_users = {owner_id: DTAccessLevel.ADMIN}
            twin.access_permissions = {owner_id: {'read', 'write', 'execute', 'admin', 'manage_access'}}
            twin.access_log = []
            twin.is_public = False
            twin.shared_with_tenant = True

    async def get_entity_full_context(self, entity_type: RequestType, entity_id: UUID) -> Dict[str, Any]:
        try:
            context = {'entity_id': str(entity_id), 'entity_type': entity_type.value, 'timestamp': datetime.now(timezone.utc).isoformat()}
            if entity_type == RequestType.DIGITAL_TWIN:
                context['twin'] = await self.get_digital_twin(entity_id)
                context['ecosystem'] = await self.get_twin_ecosystem_status(entity_id)
                replica_associations = await self.dt_orchestrator.registry.get_twin_associations(entity_id, 'data_source', 'digital_replica')
                context['replicas'] = [str(assoc.associated_entity_id) for assoc in replica_associations]
                service_associations = await self.dt_orchestrator.registry.get_twin_associations(entity_id, 'capability_provider', 'service')
                context['services'] = [str(assoc.associated_entity_id) for assoc in service_associations]
            return context
        except Exception as e:
            logger.error(f'Failed to get full context for {entity_type.value} {entity_id}: {e}')
            raise APIGatewayError(f'Context retrieval failed: {e}')

    async def get_gateway_status(self) -> Dict[str, Any]:
        return {'gateway': {'initialized': self._initialized, 'layer_connections': self._layer_connections, 'timestamp': datetime.now(timezone.utc).isoformat()}, 'layers': {'digital_twin': self.dt_orchestrator._initialized if self.dt_orchestrator else False, 'service': self.service_orchestrator._initialized if self.service_orchestrator else False, 'virtualization': self.virtualization_orchestrator._initialized if self.virtualization_orchestrator else False}}

    def is_ready(self) -> bool:
        return self._initialized and all(self._layer_connections.values()) and self.dt_orchestrator and self.service_orchestrator and self.virtualization_orchestrator
_api_gateway: Optional[APIGateway] = None

def get_api_gateway() -> APIGateway:
    global _api_gateway
    if _api_gateway is None:
        _api_gateway = APIGateway()
    return _api_gateway

async def initialize_api_gateway() -> APIGateway:
    global _api_gateway
    _api_gateway = APIGateway()
    await _api_gateway.initialize()
    return _api_gateway