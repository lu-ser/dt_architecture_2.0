import asyncio
import hashlib
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4
import jwt
import bcrypt
from . import AuthContext, AuthSubject, AuthSubjectType, AuthMethod
from src.utils.exceptions import AuthenticationError, AuthorizationError, ValidationError
from src.utils.config import get_config
logger = logging.getLogger(__name__)

class UserRole:
    ADMIN = 'admin'
    OPERATOR = 'operator'
    VIEWER = 'viewer'
    ROLE_PERMISSIONS = {ADMIN: ['admin:*'], OPERATOR: ['digital_twin:read', 'digital_twin:write', 'digital_twin:execute', 'service:read', 'service:write', 'service:execute', 'replica:read', 'replica:write', 'replica:manage', 'workflow:read', 'workflow:write', 'workflow:execute', 'system:monitor'], VIEWER: ['digital_twin:read', 'service:read', 'replica:read', 'workflow:read', 'system:monitor']}

    @classmethod
    def get_permissions(cls, role: str) -> List[str]:
        return cls.ROLE_PERMISSIONS.get(role, [])

    @classmethod
    def is_valid_role(cls, role: str) -> bool:
        return role in cls.ROLE_PERMISSIONS

class User:

    def __init__(self, user_id: UUID, username: str, email: str, password_hash: str, role: str, is_active: bool=True, metadata: Optional[Dict[str, Any]]=None, created_at: Optional[datetime]=None, last_login: Optional[datetime]=None):
        self.id = user_id
        self.user_id = user_id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.role = role
        self.is_active = is_active
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.now(timezone.utc)
        self.last_login = last_login
        from src.core.interfaces.base import EntityStatus
        self.status = EntityStatus.ACTIVE if is_active else EntityStatus.INACTIVE

    def check_password(self, password: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
        except Exception as e:
            logger.error(f'Password check failed for user {self.username}: {e}')
            return False

    def get_permissions(self) -> List[str]:
        base_permissions = UserRole.get_permissions(self.role)
        custom_permissions = self.metadata.get('custom_permissions', [])
        return base_permissions + custom_permissions

    def to_dict(self, include_sensitive: bool=False) -> Dict[str, Any]:
        user_dict = {'id': str(self.user_id), 'user_id': str(self.user_id), 'username': self.username, 'email': self.email, 'role': self.role, 'is_active': self.is_active, 'metadata': self.metadata, 'created_at': self.created_at.isoformat(), 'last_login': self.last_login.isoformat() if self.last_login else None, 'status': self.status.value if hasattr(self.status, 'value') else str(self.status)}
        if include_sensitive:
            user_dict['password_hash'] = self.password_hash
        return user_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'User':
        return cls(user_id=UUID(data['user_id']) if isinstance(data['user_id'], str) else data['user_id'], username=data['username'], email=data['email'], password_hash=data['password_hash'], role=data['role'], is_active=data.get('is_active', True), metadata=data.get('metadata', {}), created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else None, last_login=datetime.fromisoformat(data['last_login']) if data.get('last_login') else None)

class TokenPair:

    def __init__(self, access_token: str, refresh_token: str, token_type: str='Bearer', expires_in: int=3600, refresh_expires_in: int=86400):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_type = token_type
        self.expires_in = expires_in
        self.refresh_expires_in = refresh_expires_in
        self.issued_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {'access_token': self.access_token, 'refresh_token': self.refresh_token, 'token_type': self.token_type, 'expires_in': self.expires_in, 'refresh_expires_in': self.refresh_expires_in, 'issued_at': self.issued_at.isoformat()}

class RefreshToken:

    def __init__(self, token_id: UUID, user_id: UUID, token_hash: str, expires_at: datetime, is_revoked: bool=False, metadata: Optional[Dict[str, Any]]=None):
        self.id = token_id
        self.token_id = token_id
        self.user_id = user_id
        self.token_hash = token_hash
        self.expires_at = expires_at
        self.is_revoked = is_revoked
        self.metadata = metadata or {}
        self.created_at = datetime.now(timezone.utc)
        from src.core.interfaces.base import EntityStatus
        self.status = EntityStatus.ACTIVE

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    def is_valid(self) -> bool:
        return not self.is_expired() and (not self.is_revoked)

    def to_dict(self) -> Dict[str, Any]:
        return {'id': str(self.token_id), 'token_id': str(self.token_id), 'user_id': str(self.user_id), 'token_hash': self.token_hash, 'expires_at': self.expires_at.isoformat(), 'is_revoked': self.is_revoked, 'metadata': self.metadata, 'created_at': self.created_at.isoformat(), 'status': self.status.value if hasattr(self.status, 'value') else str(self.status)}

class JWTProvider:

    def __init__(self):
        self.config = get_config()
        self.secret_key = self._get_jwt_secret()
        self.algorithm = 'HS256'
        self.access_token_expire_minutes = 60
        self.refresh_token_expire_days = 7
        self.users: Dict[str, User] = {}
        self.users_by_id: Dict[UUID, User] = {}
        self.refresh_tokens: Dict[str, RefreshToken] = {}
        self.user_storage = None
        self.token_storage = None
        self._user_cache_ttl = 300
        self._cache_timestamps: Dict[str, datetime] = {}
        self.active_sessions: Dict[str, List[datetime]] = {}
        self.max_sessions_per_user = 5
        self._initialized = False
        logger.info('Enhanced JWT Provider initialized (with backward compatibility)')

    async def initialize(self) -> None:
        if self._initialized:
            return
        try:
            logger.info('🔄 Initializing JWT Provider with persistent storage...')
            await self._initialize_storage()
            await self._load_users_to_memory()
            await self._create_default_users()
            self._initialized = True
            logger.info(f'✅ JWT Provider initialized with {len(self.users)} users in memory')
        except Exception as e:
            logger.error(f'Failed to initialize JWT Provider: {e}')
            self._initialize_fallback()
            raise AuthenticationError(f'JWT Provider initialization failed: {e}')

    async def _initialize_storage(self):
        try:
            from src.storage import get_global_storage_adapter
            self.user_storage = get_global_storage_adapter(User)
            self.token_storage = get_global_storage_adapter(RefreshToken)
            await self.user_storage.connect()
            await self.token_storage.connect()
            user_health = await self.user_storage.health_check()
            token_health = await self.token_storage.health_check()
            if user_health and token_health:
                logger.info('✅ Connected to persistent storage (MongoDB)')
            else:
                logger.warning('⚠️  Storage health checks failed, using memory fallback')
                self.user_storage = None
                self.token_storage = None
        except Exception as e:
            logger.warning(f'⚠️  Failed to initialize storage: {e}')
            self.user_storage = None
            self.token_storage = None

    def _initialize_fallback(self):
        self.user_storage = None
        self.token_storage = None
        logger.warning('🔄 JWT Provider running in memory-only mode')

    async def _load_users_to_memory(self):
        if not self.user_storage:
            return
        try:
            users = await self.user_storage.query({})
            for user in users:
                self.users[user.username] = user
                self.users_by_id[user.user_id] = user
            logger.info(f'✅ Loaded {len(users)} users from database to memory')
        except Exception as e:
            logger.error(f'Failed to load users from database: {e}')

    async def _save_user_to_storage(self, user: User):
        try:
            if self.user_storage:
                await self.user_storage.save(user)
                logger.debug(f'✅ User {user.username} saved to database')
            self.users[user.username] = user
            self.users_by_id[user.user_id] = user
            self._cache_timestamps[f'user:{user.username}'] = datetime.now(timezone.utc)
        except Exception as e:
            logger.error(f'Failed to save user {user.username}: {e}')
            self.users[user.username] = user
            self.users_by_id[user.user_id] = user

    async def authenticate(self, credentials: Dict[str, Any]) -> AuthContext:
        username = credentials.get('username')
        password = credentials.get('password')
        if not username or not password:
            raise AuthenticationError('Username and password required')
        user = self.users.get(username.lower())
        if not user:
            logger.warning(f'Authentication attempt for unknown user: {username}')
            raise AuthenticationError('Invalid credentials')
        if not user.is_active:
            logger.warning(f'Authentication attempt for inactive user: {username}')
            raise AuthenticationError('User account is disabled')
        if not user.check_password(password):
            logger.warning(f'Invalid password for user: {username}')
            raise AuthenticationError('Invalid credentials')
        user.last_login = datetime.now(timezone.utc)
        await self._save_user_to_storage(user)
        await self._track_user_session(user.user_id)
        context = AuthContext(subject_type=AuthSubjectType.USER, subject_id=user.user_id, auth_method=AuthMethod.JWT_TOKEN, permissions=user.get_permissions(), metadata={'username': user.username, 'email': user.email, 'role': user.role, 'last_login': user.last_login.isoformat()}, expires_at=datetime.now(timezone.utc) + timedelta(minutes=self.access_token_expire_minutes))
        logger.info(f'User authenticated successfully: {username}')
        return context

    async def create_user(self, username: str, email: str, password: str, role: str, metadata: Optional[Dict[str, Any]]=None) -> User:
        if not username or not email or (not password):
            raise ValidationError('Username, email, and password are required')
        if not UserRole.is_valid_role(role):
            raise ValidationError(f'Invalid role: {role}')
        username = username.lower().strip()
        email = email.lower().strip()
        if username in self.users:
            raise ValidationError(f'Username already exists: {username}')
        for user in self.users.values():
            if user.email == email:
                raise ValidationError(f'Email already exists: {email}')
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        user = User(user_id=uuid4(), username=username, email=email, password_hash=password_hash, role=role, metadata=metadata or {})
        await self._save_user_to_storage(user)
        logger.info(f'✅ User created: {username} with role {role}')
        return user

    async def generate_token_pair(self, user: User) -> TokenPair:
        now = datetime.now(timezone.utc)
        access_payload = {'sub': str(user.user_id), 'username': user.username, 'email': user.email, 'role': user.role, 'permissions': user.get_permissions(), 'iat': now.timestamp(), 'exp': (now + timedelta(minutes=self.access_token_expire_minutes)).timestamp(), 'type': 'access'}
        access_token = jwt.encode(access_payload, self.secret_key, algorithm=self.algorithm)
        refresh_token_raw = secrets.token_urlsafe(32)
        refresh_token_hash = hashlib.sha256(refresh_token_raw.encode()).hexdigest()
        refresh_token_entity = RefreshToken(token_id=uuid4(), user_id=user.user_id, token_hash=refresh_token_hash, expires_at=now + timedelta(days=self.refresh_token_expire_days), metadata={'username': user.username})
        if self.token_storage:
            try:
                await self.token_storage.save(refresh_token_entity)
            except Exception as e:
                logger.error(f'Failed to save refresh token: {e}')
        self.refresh_tokens[refresh_token_hash] = refresh_token_entity
        await self._cleanup_user_refresh_tokens(user.user_id)
        return TokenPair(access_token=access_token, refresh_token=refresh_token_raw, expires_in=self.access_token_expire_minutes * 60, refresh_expires_in=self.refresh_token_expire_days * 86400)

    async def validate_token(self, token: str) -> AuthContext:
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            if payload.get('type') != 'access':
                raise AuthenticationError('Invalid token type')
            user_id = UUID(payload['sub'])
            username = payload['username']
            role = payload['role']
            permissions = payload.get('permissions', [])
            user = self.users_by_id.get(user_id)
            if not user or not user.is_active:
                raise AuthenticationError('User no longer exists or is inactive')
            expires_at = datetime.fromtimestamp(payload['exp'], tz=timezone.utc)
            context = AuthContext(subject_type=AuthSubjectType.USER, subject_id=user_id, auth_method=AuthMethod.JWT_TOKEN, permissions=permissions, metadata={'username': username, 'email': payload.get('email'), 'role': role, 'token_issued_at': datetime.fromtimestamp(payload['iat'], tz=timezone.utc).isoformat()}, expires_at=expires_at)
            return context
        except jwt.ExpiredSignatureError:
            raise AuthenticationError('Token has expired')
        except jwt.InvalidTokenError as e:
            raise AuthenticationError(f'Invalid token: {e}')
        except Exception as e:
            logger.error(f'Token validation failed: {e}')
            raise AuthenticationError('Token validation failed')

    async def refresh_token(self, refresh_token: str) -> TokenPair:
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        refresh_token_entity = self.refresh_tokens.get(token_hash)
        if not refresh_token_entity:
            raise AuthenticationError('Invalid refresh token')
        if not refresh_token_entity.is_valid():
            self.refresh_tokens.pop(token_hash, None)
            raise AuthenticationError('Refresh token is expired or revoked')
        user = self.users_by_id.get(refresh_token_entity.user_id)
        if not user or not user.is_active:
            refresh_token_entity.is_revoked = True
            raise AuthenticationError('User no longer exists or is inactive')
        refresh_token_entity.is_revoked = True
        new_token_pair = await self.generate_token_pair(user)
        logger.info(f'Token refreshed for user: {user.username}')
        return new_token_pair

    async def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        return self.users_by_id.get(user_id)

    async def get_user_by_username(self, username: str) -> Optional[User]:
        return self.users.get(username.lower())

    async def list_users(self, include_inactive: bool=False) -> List[Dict[str, Any]]:
        users = []
        for user in self.users.values():
            if include_inactive or user.is_active:
                users.append(user.to_dict())
        return users

    async def revoke_all_user_tokens(self, user_id: UUID) -> None:
        revoked_count = 0
        for refresh_token in self.refresh_tokens.values():
            if refresh_token.user_id == user_id and (not refresh_token.is_revoked):
                refresh_token.is_revoked = True
                revoked_count += 1
        logger.info(f'Revoked {revoked_count} tokens for user: {user_id}')

    async def _create_default_users(self) -> None:
        default_users = [{'username': 'admin', 'email': 'admin@digitaltwin.platform', 'password': 'admin123', 'role': UserRole.ADMIN, 'metadata': {'default_user': True, 'description': 'Default admin user'}}, {'username': 'operator', 'email': 'operator@digitaltwin.platform', 'password': 'operator123', 'role': UserRole.OPERATOR, 'metadata': {'default_user': True, 'description': 'Default operator user'}}, {'username': 'viewer', 'email': 'viewer@digitaltwin.platform', 'password': 'viewer123', 'role': UserRole.VIEWER, 'metadata': {'default_user': True, 'description': 'Default viewer user'}}]
        for user_data in default_users:
            try:
                if user_data['username'] not in self.users:
                    await self.create_user(**user_data)
                    logger.info(f"✅ Created default user: {user_data['username']}")
                else:
                    logger.debug(f"Default user already exists: {user_data['username']}")
            except ValidationError:
                logger.debug(f"Default user already exists: {user_data['username']}")

    async def _track_user_session(self, user_id: UUID) -> None:
        user_id_str = str(user_id)
        now = datetime.now(timezone.utc)
        if user_id_str not in self.active_sessions:
            self.active_sessions[user_id_str] = []
        self.active_sessions[user_id_str].append(now)
        cutoff = now - timedelta(hours=24)
        self.active_sessions[user_id_str] = [session for session in self.active_sessions[user_id_str] if session > cutoff]
        if len(self.active_sessions[user_id_str]) > self.max_sessions_per_user:
            logger.warning(f'User {user_id} exceeded max sessions limit')

    async def _cleanup_user_refresh_tokens(self, user_id: UUID) -> None:
        tokens_to_remove = []
        for token_hash, refresh_token in self.refresh_tokens.items():
            if refresh_token.user_id == user_id and (refresh_token.is_expired() or refresh_token.is_revoked):
                tokens_to_remove.append(token_hash)
        for token_hash in tokens_to_remove:
            del self.refresh_tokens[token_hash]
            if self.token_storage:
                try:
                    token_entity = self.refresh_tokens.get(token_hash)
                    if token_entity:
                        await self.token_storage.delete(token_entity.token_id)
                except Exception as e:
                    logger.error(f'Failed to delete token from database: {e}')
        if tokens_to_remove:
            logger.debug(f'Cleaned up {len(tokens_to_remove)} expired tokens for user {user_id}')

    def _get_jwt_secret(self) -> str:
        jwt_config = self.config.get('jwt', {})
        secret = jwt_config.get('secret_key')
        if not secret:
            secret = 'dev-jwt-secret-key-change-in-production'
            logger.warning('Using development JWT secret. Change this in production!')
        return secret

    def get_provider_status(self) -> Dict[str, Any]:
        active_tokens = len([token for token in self.refresh_tokens.values() if token.is_valid()])
        return {'initialized': self._initialized, 'storage_mode': 'persistent' if self.user_storage else 'memory', 'user_storage_connected': self.user_storage is not None, 'token_storage_connected': self.token_storage is not None, 'total_users': len(self.users), 'active_users': len([u for u in self.users.values() if u.is_active]), 'active_refresh_tokens': active_tokens, 'total_refresh_tokens': len(self.refresh_tokens), 'active_sessions': sum((len(sessions) for sessions in self.active_sessions.values())), 'configuration': {'access_token_expire_minutes': self.access_token_expire_minutes, 'refresh_token_expire_days': self.refresh_token_expire_days, 'max_sessions_per_user': self.max_sessions_per_user, 'algorithm': self.algorithm}}