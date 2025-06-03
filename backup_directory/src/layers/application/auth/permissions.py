import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID
from enum import Enum
from . import AuthContext, AuthSubject, AuthSubjectType, AuthMethod
from src.utils.exceptions import AuthorizationError, ValidationError, ConfigurationError
from src.utils.config import get_config
logger = logging.getLogger(__name__)

class PermissionLevel(Enum):
    NONE = 0
    READ = 1
    WRITE = 2
    EXECUTE = 3
    MANAGE = 4
    ADMIN = 5

class ResourceType(Enum):
    DIGITAL_TWIN = 'digital_twin'
    SERVICE = 'service'
    REPLICA = 'replica'
    WORKFLOW = 'workflow'
    USER = 'user'
    API_KEY = 'api_key'
    SYSTEM = 'system'
    PLATFORM = 'platform'

class Permission:

    def __init__(self, permission_string: str):
        self.original = permission_string
        self.parts = permission_string.split(':')
        if len(self.parts) < 2:
            raise ValidationError(f'Invalid permission format: {permission_string}')
        self.resource = self.parts[0]
        if len(self.parts) == 3:
            self.resource_id = self.parts[1]
            self.action = self.parts[2]
        else:
            self.resource_id = None
            self.action = self.parts[1]
        self.is_wildcard = self.action == '*'
        self.is_admin_wildcard = self.resource == 'admin' and self.is_wildcard

    def matches(self, other: 'Permission') -> bool:
        if self.is_admin_wildcard:
            return True
        if self.resource != other.resource:
            return False
        if other.resource_id:
            if not self.resource_id and (not self.is_wildcard):
                return False
            if self.resource_id and self.resource_id != other.resource_id:
                return False
        if self.is_wildcard:
            return True
        return self.action == other.action

    def get_level(self) -> PermissionLevel:
        if self.is_admin_wildcard:
            return PermissionLevel.ADMIN
        action_levels = {'read': PermissionLevel.READ, 'write': PermissionLevel.WRITE, 'execute': PermissionLevel.EXECUTE, 'manage': PermissionLevel.MANAGE, '*': PermissionLevel.ADMIN}
        return action_levels.get(self.action, PermissionLevel.NONE)

    def __str__(self) -> str:
        return self.original

    def __repr__(self) -> str:
        return f"Permission('{self.original}')"

    def __eq__(self, other) -> bool:
        if isinstance(other, Permission):
            return self.original == other.original
        return False

    def __hash__(self) -> int:
        return hash(self.original)

class PermissionTemplate:

    def __init__(self, name: str, description: str, permissions: List[str], metadata: Optional[Dict[str, Any]]=None):
        self.name = name
        self.description = description
        self.permissions = [Permission(p) for p in permissions]
        self.metadata = metadata or {}

    def get_permission_strings(self) -> List[str]:
        return [p.original for p in self.permissions]

    def to_dict(self) -> Dict[str, Any]:
        return {'name': self.name, 'description': self.description, 'permissions': self.get_permission_strings(), 'metadata': self.metadata}

class ResourcePermissionSet:

    def __init__(self, resource_type: ResourceType, resource_id: UUID, permissions: Dict[str, List[str]], metadata: Optional[Dict[str, Any]]=None):
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.permissions = permissions
        self.metadata = metadata or {}
        self.created_at = datetime.now(timezone.utc)

    def get_subject_permissions(self, subject_id: str) -> List[str]:
        return self.permissions.get(subject_id, [])

    def add_subject_permission(self, subject_id: str, action: str) -> None:
        if subject_id not in self.permissions:
            self.permissions[subject_id] = []
        if action not in self.permissions[subject_id]:
            self.permissions[subject_id].append(action)

    def remove_subject_permission(self, subject_id: str, action: str) -> None:
        if subject_id in self.permissions:
            if action in self.permissions[subject_id]:
                self.permissions[subject_id].remove(action)
            if not self.permissions[subject_id]:
                del self.permissions[subject_id]

    def to_dict(self) -> Dict[str, Any]:
        return {'resource_type': self.resource_type.value, 'resource_id': str(self.resource_id), 'permissions': self.permissions, 'metadata': self.metadata, 'created_at': self.created_at.isoformat()}

class PermissionManager:

    def __init__(self):
        self.config = get_config()
        self.templates: Dict[str, PermissionTemplate] = {}
        self.resource_permissions: Dict[str, ResourcePermissionSet] = {}
        self.role_hierarchy = {'admin': ['operator', 'viewer'], 'operator': ['viewer'], 'viewer': []}
        self._permission_cache: Dict[str, Set[Permission]] = {}
        self._cache_timeout = 300
        self._cache_timestamps: Dict[str, datetime] = {}
        self.permission_checks = 0
        self.permission_grants = 0
        self.permission_denials = 0
        self._initialized = False
        logger.info('Permission Manager initialized')

    async def initialize(self) -> None:
        if self._initialized:
            return
        try:
            await self._create_default_templates()
            await self._initialize_role_permissions()
            self._initialized = True
            logger.info(f'Permission Manager initialized with {len(self.templates)} templates')
        except Exception as e:
            logger.error(f'Failed to initialize Permission Manager: {e}')
            raise ConfigurationError(f'Permission Manager initialization failed: {e}')

    async def check_permission(self, auth_context: AuthContext, action: str, resource: str, resource_id: Optional[UUID]=None) -> bool:
        self.permission_checks += 1
        try:
            if resource_id:
                permission_string = f'{resource}:{resource_id}:{action}'
            else:
                permission_string = f'{resource}:{action}'
            required_permission = Permission(permission_string)
            subject_permissions = await self._get_subject_permissions(auth_context)
            for permission in subject_permissions:
                if permission.matches(required_permission):
                    self.permission_grants += 1
                    logger.debug(f'Permission granted: {auth_context.subject_id} can {permission_string}')
                    return True
            if resource_id:
                resource_key = f'{resource}:{resource_id}'
                if resource_key in self.resource_permissions:
                    resource_perms = self.resource_permissions[resource_key]
                    subject_actions = resource_perms.get_subject_permissions(str(auth_context.subject_id))
                    if action in subject_actions or '*' in subject_actions:
                        self.permission_grants += 1
                        logger.debug(f'Resource permission granted: {auth_context.subject_id} can {permission_string}')
                        return True
            if auth_context.subject_type == AuthSubjectType.USER:
                user_role = auth_context.metadata.get('role')
                if user_role and await self._check_role_permission(user_role, required_permission):
                    self.permission_grants += 1
                    logger.debug(f'Role permission granted: {user_role} can {permission_string}')
                    return True
            self.permission_denials += 1
            logger.debug(f'Permission denied: {auth_context.subject_id} cannot {permission_string}')
            return False
        except Exception as e:
            logger.error(f'Permission check failed: {e}')
            self.permission_denials += 1
            return False

    async def grant_resource_permission(self, resource_type: ResourceType, resource_id: UUID, subject_id: UUID, action: str, granted_by: UUID) -> None:
        resource_key = f'{resource_type.value}:{resource_id}'
        if resource_key not in self.resource_permissions:
            self.resource_permissions[resource_key] = ResourcePermissionSet(resource_type=resource_type, resource_id=resource_id, permissions={}, metadata={'granted_by': str(granted_by)})
        resource_perms = self.resource_permissions[resource_key]
        resource_perms.add_subject_permission(str(subject_id), action)
        await self._invalidate_permission_cache(str(subject_id))
        logger.info(f'Granted {action} permission on {resource_type.value}:{resource_id} to {subject_id}')

    async def revoke_resource_permission(self, resource_type: ResourceType, resource_id: UUID, subject_id: UUID, action: str) -> None:
        resource_key = f'{resource_type.value}:{resource_id}'
        if resource_key in self.resource_permissions:
            resource_perms = self.resource_permissions[resource_key]
            resource_perms.remove_subject_permission(str(subject_id), action)
            if not resource_perms.permissions:
                del self.resource_permissions[resource_key]
            await self._invalidate_permission_cache(str(subject_id))
            logger.info(f'Revoked {action} permission on {resource_type.value}:{resource_id} from {subject_id}')

    async def get_subject_resource_permissions(self, subject_id: UUID, resource_type: Optional[ResourceType]=None) -> Dict[str, List[str]]:
        permissions = {}
        for resource_key, resource_perms in self.resource_permissions.items():
            if resource_type and (not resource_key.startswith(resource_type.value)):
                continue
            subject_actions = resource_perms.get_subject_permissions(str(subject_id))
            if subject_actions:
                permissions[resource_key] = subject_actions
        return permissions

    def get_resource_permissions(self, resource_type: ResourceType) -> List[Permission]:
        resource_permissions = {ResourceType.DIGITAL_TWIN: ['read', 'write', 'delete', 'execute'], ResourceType.SERVICE: ['read', 'write', 'delete', 'execute'], ResourceType.REPLICA: ['read', 'write', 'delete', 'manage'], ResourceType.WORKFLOW: ['read', 'write', 'delete', 'execute'], ResourceType.USER: ['read', 'write', 'delete', 'manage'], ResourceType.API_KEY: ['read', 'write', 'delete', 'manage'], ResourceType.SYSTEM: ['read', 'monitor', 'config'], ResourceType.PLATFORM: ['read', 'admin']}
        actions = resource_permissions.get(resource_type, ['read', 'write'])
        return [Permission(f'{resource_type.value}:{action}') for action in actions]

    async def create_permission_template(self, name: str, description: str, permissions: List[str], metadata: Optional[Dict[str, Any]]=None) -> PermissionTemplate:
        if name in self.templates:
            raise ValidationError(f'Permission template already exists: {name}')
        template = PermissionTemplate(name, description, permissions, metadata)
        self.templates[name] = template
        logger.info(f'Created permission template: {name}')
        return template

    async def apply_permission_template(self, template_name: str, subject_id: UUID, resource_id: Optional[UUID]=None) -> None:
        template = self.templates.get(template_name)
        if not template:
            raise ValidationError(f'Permission template not found: {template_name}')
        for permission in template.permissions:
            if resource_id and (not permission.resource_id):
                await self.grant_resource_permission(resource_type=ResourceType(permission.resource), resource_id=resource_id, subject_id=subject_id, action=permission.action, granted_by=UUID('00000000-0000-0000-0000-000000000000'))
        logger.info(f'Applied template {template_name} to subject {subject_id}')

    def list_permission_templates(self) -> List[Dict[str, Any]]:
        return [template.to_dict() for template in self.templates.values()]

    async def validate_permissions(self, permissions: List[str]) -> Tuple[List[str], List[str]]:
        valid = []
        invalid = []
        for perm_string in permissions:
            try:
                Permission(perm_string)
                valid.append(perm_string)
            except ValidationError:
                invalid.append(perm_string)
        return (valid, invalid)

    async def _get_subject_permissions(self, auth_context: AuthContext) -> Set[Permission]:
        cache_key = f'{auth_context.subject_id}:{auth_context.auth_method.value}'
        if cache_key in self._permission_cache:
            cache_time = self._cache_timestamps.get(cache_key)
            if cache_time and (datetime.now(timezone.utc) - cache_time).total_seconds() < self._cache_timeout:
                return self._permission_cache[cache_key]
        permissions = set()
        for perm_string in auth_context.permissions:
            try:
                permissions.add(Permission(perm_string))
            except ValidationError as e:
                logger.warning(f'Invalid permission in auth context: {perm_string} - {e}')
        if auth_context.subject_type == AuthSubjectType.USER:
            user_role = auth_context.metadata.get('role')
            if user_role:
                role_permissions = await self._get_role_permissions(user_role)
                permissions.update(role_permissions)
        self._permission_cache[cache_key] = permissions
        self._cache_timestamps[cache_key] = datetime.now(timezone.utc)
        return permissions

    async def _get_role_permissions(self, role: str) -> Set[Permission]:
        permissions = set()
        role_permissions = {'admin': ['admin:*'], 'operator': ['digital_twin:read', 'digital_twin:write', 'digital_twin:execute', 'service:read', 'service:write', 'service:execute', 'replica:read', 'replica:write', 'replica:manage', 'workflow:read', 'workflow:write', 'workflow:execute', 'system:monitor'], 'viewer': ['digital_twin:read', 'service:read', 'replica:read', 'workflow:read', 'system:monitor']}
        role_perms = role_permissions.get(role, [])
        for perm_string in role_perms:
            try:
                permissions.add(Permission(perm_string))
            except ValidationError:
                pass
        inherited_roles = self.role_hierarchy.get(role, [])
        for inherited_role in inherited_roles:
            inherited_permissions = await self._get_role_permissions(inherited_role)
            permissions.update(inherited_permissions)
        return permissions

    async def _check_role_permission(self, role: str, required_permission: Permission) -> bool:
        role_permissions = await self._get_role_permissions(role)
        for permission in role_permissions:
            if permission.matches(required_permission):
                return True
        return False

    async def _invalidate_permission_cache(self, subject_id: str) -> None:
        keys_to_remove = [key for key in self._permission_cache.keys() if key.startswith(subject_id)]
        for key in keys_to_remove:
            del self._permission_cache[key]
            del self._cache_timestamps[key]

    async def _create_default_templates(self) -> None:
        default_templates = [{'name': 'digital_twin_admin', 'description': 'Full administrative access to Digital Twins', 'permissions': ['digital_twin:read', 'digital_twin:write', 'digital_twin:delete', 'digital_twin:execute']}, {'name': 'digital_twin_operator', 'description': 'Operational access to Digital Twins', 'permissions': ['digital_twin:read', 'digital_twin:write', 'digital_twin:execute']}, {'name': 'digital_twin_viewer', 'description': 'Read-only access to Digital Twins', 'permissions': ['digital_twin:read']}, {'name': 'service_executor', 'description': 'Execute services and view results', 'permissions': ['service:read', 'service:execute']}, {'name': 'replica_manager', 'description': 'Manage Digital Replicas and device connections', 'permissions': ['replica:read', 'replica:write', 'replica:manage']}, {'name': 'workflow_orchestrator', 'description': 'Create and execute workflows', 'permissions': ['workflow:read', 'workflow:write', 'workflow:execute']}, {'name': 'platform_monitor', 'description': 'Monitor platform health and performance', 'permissions': ['system:monitor', 'digital_twin:read', 'service:read', 'replica:read']}]
        for template_data in default_templates:
            try:
                await self.create_permission_template(**template_data)
            except ValidationError:
                pass

    async def _initialize_role_permissions(self) -> None:
        logger.debug('Role-based permissions initialized')

    def get_permission_statistics(self) -> Dict[str, Any]:
        total_checks = self.permission_checks
        grant_rate = self.permission_grants / max(total_checks, 1)
        return {'total_permission_checks': total_checks, 'permission_grants': self.permission_grants, 'permission_denials': self.permission_denials, 'grant_rate': grant_rate, 'cache_size': len(self._permission_cache), 'resource_permissions': len(self.resource_permissions), 'permission_templates': len(self.templates)}

    def get_manager_status(self) -> Dict[str, Any]:
        return {'initialized': self._initialized, 'statistics': self.get_permission_statistics(), 'role_hierarchy': self.role_hierarchy, 'available_templates': list(self.templates.keys()), 'cache_timeout': self._cache_timeout}