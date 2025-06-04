import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID
from enum import Enum
from fastapi import HTTPException, Request, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.utils.exceptions import AuthenticationError
from src.utils.config import get_config
from src.utils.exceptions import AuthenticationError
from src.utils.config import get_config
logger = logging.getLogger(__name__)

class AuthSubjectType(Enum):
    USER = 'user'
    APPLICATION = 'application'
    SYSTEM = 'system'

class AuthMethod(Enum):
    JWT_TOKEN = 'jwt_token'
    API_KEY = 'api_key'
    SYSTEM_TOKEN = 'system_token'

class AuthContext:

    def __init__(self, subject_type: AuthSubjectType, subject_id: UUID, auth_method: AuthMethod, permissions: List[str], metadata: Optional[Dict[str, Any]]=None, expires_at: Optional[datetime]=None):
        self.subject_type = subject_type
        self.subject_id = subject_id
        self.auth_method = auth_method
        self.permissions = permissions
        self.metadata = metadata or {}
        self.expires_at = expires_at
        self.authenticated_at = datetime.now(timezone.utc)

    def has_permission(self, permission: str) -> bool:
        for perm in self.permissions:
            if perm == permission:
                return True
            if perm.endswith(':*') and permission.startswith(perm[:-1]):
                return True
        return False

    def has_any_permission(self, permissions: List[str]) -> bool:
        return any((self.has_permission(perm) for perm in permissions))

    def has_all_permissions(self, permissions: List[str]) -> bool:
        return all((self.has_permission(perm) for perm in permissions))

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {'subject_type': self.subject_type.value, 'subject_id': str(self.subject_id), 'auth_method': self.auth_method.value, 'permissions': self.permissions, 'metadata': self.metadata, 'expires_at': self.expires_at.isoformat() if self.expires_at else None, 'authenticated_at': self.authenticated_at.isoformat()}

class AuthSubject:

    def __init__(self, subject_id: UUID, subject_type: AuthSubjectType, name: str, permissions: List[str], metadata: Optional[Dict[str, Any]]=None, is_active: bool=True):
        self.subject_id = subject_id
        self.subject_type = subject_type
        self.name = name
        self.permissions = permissions
        self.metadata = metadata or {}
        self.is_active = is_active
        self.created_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {'subject_id': str(self.subject_id), 'subject_type': self.subject_type.value, 'name': self.name, 'permissions': self.permissions, 'metadata': self.metadata, 'is_active': self.is_active, 'created_at': self.created_at.isoformat()}

class AuthenticationManager:

    def __init__(self):
        self.config = get_config()
        self.jwt_provider = None
        self.api_key_provider = None
        self.permission_manager = None
        self._auth_cache: Dict[str, AuthContext] = {}
        self._cache_timeout = 300
        self.max_auth_attempts = 5
        self.lockout_duration = 300
        self._failed_attempts: Dict[str, List[datetime]] = {}
        self._initialized = False
        self._redis_session_cache = None
        self._redis_rate_limiter = None
        self._use_redis = False
        logger.info('Authentication Manager initialized')

    async def initialize(self) -> None:
        if self._initialized:
            return
        try:
            from .jwt_auth import JWTProvider
            from .api_key_auth import APIKeyProvider
            from .permissions import PermissionManager
            self.jwt_provider = JWTProvider()
            self.api_key_provider = APIKeyProvider()
            self.permission_manager = PermissionManager()
            await self.jwt_provider.initialize()
            await self.api_key_provider.initialize()
            await self.permission_manager.initialize()
            await self._try_initialize_redis()
            self._initialized = True
            logger.info('Authentication Manager fully initialized')
        except ImportError:
            logger.warning('Authentication providers not yet implemented, using mock mode')
            self._initialized = True
        except Exception as e:
            logger.error(f'Failed to initialize Authentication Manager: {e}')
            raise AuthenticationError(f'Authentication initialization failed: {e}')

    async def _try_initialize_redis(self) -> None:
        try:
            cache_type = self.config.get('storage.cache_type', 'none')
            if cache_type != 'redis':
                logger.info('Redis caching disabled by configuration')
                return
            from src.storage.adapters import get_session_cache, get_rate_limit_cache
            self._redis_session_cache = await get_session_cache()
            self._redis_rate_limiter = await get_rate_limit_cache()
            cache_health = await self._redis_session_cache.cache.health_check()
            rate_health = await self._redis_rate_limiter.cache.health_check()
            if cache_health and rate_health:
                self._use_redis = True
                logger.info('✅ Redis session cache enabled')
            else:
                logger.warning('Redis health check failed, using in-memory cache')
        except ImportError:
            logger.info('Redis storage not available, using in-memory cache')
        except Exception as e:
            logger.warning(f'Redis initialization failed: {e}, using in-memory cache')

    async def authenticate_request(self, request: Request) -> AuthContext:
        if not self._initialized:
            await self.initialize()
        auth_header = request.headers.get('Authorization')
        api_key_header = request.headers.get('X-API-Key')
        client_ip = request.client.host if request.client else 'unknown'
        try:
            await self._check_rate_limit(client_ip)
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header[7:]
                return await self._authenticate_jwt(token)
            if api_key_header:
                return await self._authenticate_api_key(api_key_header)
            system_token = request.headers.get('X-System-Token')
            if system_token:
                return await self._authenticate_system_token(system_token)
            raise AuthenticationError('No authentication credentials provided')
        except Exception as e:
            logger.warning(f'Authentication failed from {client_ip}: {e}')
            await self._track_failed_attempt(client_ip)
            raise AuthenticationError(f'Authentication failed: {e}')

    async def _check_rate_limit(self, client_ip: str) -> None:
        try:
            if self._use_redis and self._redis_rate_limiter:
                identifier = f'auth:{client_ip}'
                allowed, remaining = await self._redis_rate_limiter.check_rate_limit(identifier, limit=self.max_auth_attempts, window_seconds=self.lockout_duration)
                if not allowed:
                    raise AuthenticationError(f'Too many failed attempts. Try again later.')
            else:
                now = datetime.now(timezone.utc)
                if client_ip in self._failed_attempts:
                    cutoff = now.timestamp() - self.lockout_duration
                    self._failed_attempts[client_ip] = [attempt for attempt in self._failed_attempts[client_ip] if attempt.timestamp() > cutoff]
                    if len(self._failed_attempts[client_ip]) >= self.max_auth_attempts:
                        raise AuthenticationError(f'Too many failed attempts. Try again in {self.lockout_duration} seconds.')
        except AuthenticationError:
            raise
        except Exception as e:
            logger.warning(f'Rate limit check failed: {e}')

    async def authenticate_credentials(self, credentials: Dict[str, Any], auth_method: AuthMethod) -> AuthContext:
        if not self._initialized:
            await self.initialize()
        try:
            if auth_method == AuthMethod.JWT_TOKEN:
                if self.jwt_provider:
                    return await self.jwt_provider.authenticate(credentials)
                else:
                    return await self._mock_jwt_auth(credentials)
            elif auth_method == AuthMethod.API_KEY:
                if self.api_key_provider:
                    return await self.api_key_provider.authenticate(credentials)
                else:
                    return await self._mock_api_key_auth(credentials)
            else:
                raise AuthenticationError(f'Unsupported authentication method: {auth_method}')
        except Exception as e:
            logger.error(f'Credential authentication failed: {e}')
            raise AuthenticationError(f'Authentication failed: {e}')

    async def authorize_operation(self, auth_context: AuthContext, operation: str, resource: str, resource_id: Optional[UUID]=None) -> bool:
        if not self._initialized:
            await self.initialize()
        try:
            if auth_context.is_expired():
                logger.warning(f'Expired auth context for {auth_context.subject_id}')
                return False
            if resource_id:
                permission = f'{resource}:{resource_id}:{operation}'
                general_permission = f'{resource}:{operation}'
            else:
                permission = f'{resource}:{operation}'
                general_permission = permission
            if auth_context.has_permission(permission):
                return True
            if resource_id and auth_context.has_permission(general_permission):
                return True
            if auth_context.has_permission('admin:*'):
                return True
            if self.permission_manager:
                return await self.permission_manager.check_permission(auth_context, operation, resource, resource_id)
            logger.warning(f'Authorization denied for {auth_context.subject_id}: {operation} on {resource}:{resource_id}')
            return False
        except Exception as e:
            logger.error(f'Authorization check failed: {e}')
            return False

    async def get_auth_context_from_cache(self, cache_key: str) -> Optional[AuthContext]:
        try:
            if self._use_redis and self._redis_session_cache:
                session_data = await self._redis_session_cache.get_session(cache_key)
                if session_data:
                    return AuthContext(subject_type=AuthSubjectType(session_data['subject_type']), subject_id=UUID(session_data['subject_id']), auth_method=AuthMethod(session_data['auth_method']), permissions=session_data['permissions'], metadata=session_data.get('metadata', {}), expires_at=datetime.fromisoformat(session_data['expires_at']) if session_data.get('expires_at') else None)
            if cache_key in self._auth_cache:
                context = self._auth_cache[cache_key]
                if not context.is_expired():
                    return context
                else:
                    del self._auth_cache[cache_key]
        except Exception as e:
            logger.warning(f'Cache retrieval failed: {e}')
        return None

    def cache_auth_context(self, cache_key: str, context: AuthContext) -> None:
        try:
            if len(self._auth_cache) > 1000:
                oldest_key = min(self._auth_cache.keys())
                del self._auth_cache[oldest_key]
            self._auth_cache[cache_key] = context
            if self._use_redis and self._redis_session_cache:
                asyncio.create_task(self._cache_in_redis(cache_key, context))
        except Exception as e:
            logger.warning(f'Cache storage failed: {e}')

    async def _cache_in_redis(self, cache_key: str, context: AuthContext) -> None:
        try:
            session_data = {'subject_type': context.subject_type.value, 'subject_id': str(context.subject_id), 'auth_method': context.auth_method.value, 'permissions': context.permissions, 'metadata': context.metadata, 'expires_at': context.expires_at.isoformat() if context.expires_at else None, 'authenticated_at': context.authenticated_at.isoformat()}
            await self._redis_session_cache.store_session(cache_key, session_data)
        except Exception as e:
            logger.warning(f'Redis cache storage failed: {e}')

    async def invalidate_auth_cache(self, subject_id: Optional[UUID]=None) -> None:
        if subject_id:
            keys_to_remove = [key for key, context in self._auth_cache.items() if context.subject_id == subject_id]
            for key in keys_to_remove:
                del self._auth_cache[key]
        else:
            self._auth_cache.clear()

    async def _authenticate_jwt(self, token: str) -> AuthContext:
        cache_key = f'jwt:{token[:16]}'
        cached_context = await self.get_auth_context_from_cache(cache_key)
        if cached_context:
            return cached_context
        if self.jwt_provider:
            context = await self.jwt_provider.validate_token(token)
        else:
            context = await self._mock_jwt_validation(token)
        self.cache_auth_context(cache_key, context)
        return context

    async def _authenticate_api_key(self, api_key: str) -> AuthContext:
        cache_key = f'api_key:{api_key[:16]}'
        cached_context = await self.get_auth_context_from_cache(cache_key)
        if cached_context:
            return cached_context
        if self.api_key_provider:
            context = await self.api_key_provider.validate_api_key(api_key)
        else:
            context = await self._mock_api_key_validation(api_key)
        self.cache_auth_context(cache_key, context)
        return context

    async def _authenticate_system_token(self, system_token: str) -> AuthContext:
        expected_token = self.config.get('system', {}).get('internal_token', 'system-token-123')
        if system_token != expected_token:
            raise AuthenticationError('Invalid system token')
        return AuthContext(subject_type=AuthSubjectType.SYSTEM, subject_id=UUID('00000000-0000-0000-0000-000000000000'), auth_method=AuthMethod.SYSTEM_TOKEN, permissions=['admin:*'], metadata={'system': True})

    async def _track_failed_attempt(self, identifier: str) -> None:
        now = datetime.now(timezone.utc)
        if identifier not in self._failed_attempts:
            self._failed_attempts[identifier] = []
        self._failed_attempts[identifier].append(now)
        cutoff = now.timestamp() - self.lockout_duration
        self._failed_attempts[identifier] = [attempt for attempt in self._failed_attempts[identifier] if attempt.timestamp() > cutoff]

    async def _mock_jwt_auth(self, credentials: Dict[str, Any]) -> AuthContext:
        username = credentials.get('username', 'mock_user')
        return AuthContext(subject_type=AuthSubjectType.USER, subject_id=UUID('12345678-1234-1234-1234-123456789012'), auth_method=AuthMethod.JWT_TOKEN, permissions=['digital_twin:*', 'service:*', 'replica:*'], metadata={'username': username, 'mock': True})

    async def _mock_jwt_validation(self, token: str) -> AuthContext:
        if token == 'mock-jwt-token':
            return AuthContext(subject_type=AuthSubjectType.USER, subject_id=UUID('12345678-1234-1234-1234-123456789012'), auth_method=AuthMethod.JWT_TOKEN, permissions=['digital_twin:*', 'service:*', 'replica:*'], metadata={'username': 'mock_user', 'mock': True})
        raise AuthenticationError('Invalid JWT token')

    async def _mock_api_key_auth(self, credentials: Dict[str, Any]) -> AuthContext:
        api_key = credentials.get('api_key', 'mock-api-key')
        return AuthContext(subject_type=AuthSubjectType.APPLICATION, subject_id=UUID('87654321-4321-4321-4321-210987654321'), auth_method=AuthMethod.API_KEY, permissions=['digital_twin:read', 'service:execute'], metadata={'application': 'mock_app', 'mock': True})

    async def _mock_api_key_validation(self, api_key: str) -> AuthContext:
        if api_key == 'mock-api-key-123':
            return AuthContext(subject_type=AuthSubjectType.APPLICATION, subject_id=UUID('87654321-4321-4321-4321-210987654321'), auth_method=AuthMethod.API_KEY, permissions=['digital_twin:read', 'service:execute'], metadata={'application': 'mock_app', 'mock': True})
        raise AuthenticationError('Invalid API key')

    def get_auth_status(self) -> Dict[str, Any]:
        return {'initialized': self._initialized, 'providers': {'jwt_provider': self.jwt_provider is not None, 'api_key_provider': self.api_key_provider is not None, 'permission_manager': self.permission_manager is not None}, 'cache_size': len(self._auth_cache), 'failed_attempts': len(self._failed_attempts), 'redis_enabled': self._use_redis, 'redis_health': self._redis_session_cache.cache.health_check() if self._use_redis and self._redis_session_cache else None, 'security_settings': {'max_auth_attempts': self.max_auth_attempts, 'lockout_duration': self.lockout_duration, 'cache_timeout': self._cache_timeout}}
_auth_manager: Optional[AuthenticationManager] = None

def get_auth_manager() -> AuthenticationManager:
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthenticationManager()
    return _auth_manager

async def initialize_authentication() -> AuthenticationManager:
    global _auth_manager
    _auth_manager = AuthenticationManager()
    await _auth_manager.initialize()
    return _auth_manager
security = HTTPBearer(auto_error=False)

async def get_auth_context(request: Request, credentials: Optional[HTTPAuthorizationCredentials]=Depends(security)) -> AuthContext:
    auth_manager = get_auth_manager()
    return await auth_manager.authenticate_request(request)

async def get_current_user(auth: AuthContext=Depends(get_auth_context)) -> AuthContext:
    if auth.subject_type != AuthSubjectType.USER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='User authentication required')
    return auth

async def get_current_application(auth: AuthContext=Depends(get_auth_context)) -> AuthContext:
    if auth.subject_type != AuthSubjectType.APPLICATION:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Application authentication required')
    return auth

def require_permission(permission: str):

    async def permission_checker(auth: AuthContext=Depends(get_auth_context)) -> AuthContext:
        if not auth.has_permission(permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f'Permission required: {permission}')
        return auth
    return permission_checker

def require_any_permission(permissions: List[str]):

    async def permission_checker(auth: AuthContext=Depends(get_auth_context)) -> AuthContext:
        if not auth.has_any_permission(permissions):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f'One of these permissions required: {permissions}')
        return auth
    return permission_checker

def require_all_permissions(permissions: List[str]):

    async def permission_checker(auth: AuthContext=Depends(get_auth_context)) -> AuthContext:
        if not auth.has_all_permissions(permissions):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f'All of these permissions required: {permissions}')
        return auth
    return permission_checker

class Permissions:
    DIGITAL_TWIN_READ = 'digital_twin:read'
    DIGITAL_TWIN_WRITE = 'digital_twin:write'
    DIGITAL_TWIN_DELETE = 'digital_twin:delete'
    DIGITAL_TWIN_EXECUTE = 'digital_twin:execute'
    SERVICE_READ = 'service:read'
    SERVICE_WRITE = 'service:write'
    SERVICE_DELETE = 'service:delete'
    SERVICE_EXECUTE = 'service:execute'
    REPLICA_READ = 'replica:read'
    REPLICA_WRITE = 'replica:write'
    REPLICA_DELETE = 'replica:delete'
    REPLICA_MANAGE = 'replica:manage'
    WORKFLOW_READ = 'workflow:read'
    WORKFLOW_WRITE = 'workflow:write'
    WORKFLOW_DELETE = 'workflow:delete'
    WORKFLOW_EXECUTE = 'workflow:execute'
    ADMIN_ALL = 'admin:*'
    USER_MANAGE = 'user:manage'
    API_KEY_MANAGE = 'api_key:manage'
    SYSTEM_MONITOR = 'system:monitor'
    SYSTEM_CONFIG = 'system:config'
require_digital_twin_read = require_permission(Permissions.DIGITAL_TWIN_READ)
require_digital_twin_write = require_permission(Permissions.DIGITAL_TWIN_WRITE)
require_service_execute = require_permission(Permissions.SERVICE_EXECUTE)
require_replica_manage = require_permission(Permissions.REPLICA_MANAGE)
require_workflow_execute = require_permission(Permissions.WORKFLOW_EXECUTE)
require_admin = require_permission(Permissions.ADMIN_ALL)