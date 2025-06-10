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
from src.storage.adapters.mongodb_adapter import MongoStorageAdapter

logger = logging.getLogger(__name__)

class UserRole:
    ADMIN = 'admin'
    OPERATOR = 'operator'
    VIEWER = 'viewer'
    ROLE_PERMISSIONS = {
        ADMIN: ['admin:*'],
        OPERATOR: [
            'digital_twin:read', 'digital_twin:write', 'digital_twin:execute',
            'service:read', 'service:write', 'service:execute',
            'replica:read', 'replica:write', 'replica:manage',
            'workflow:read', 'workflow:write', 'workflow:execute',
            'system:monitor'
        ],
        VIEWER: [
            'digital_twin:read', 'service:read', 'replica:read', 
            'workflow:read', 'system:monitor'
        ]
    }

    @classmethod
    def get_permissions(cls, role: str) -> List[str]:
        return cls.ROLE_PERMISSIONS.get(role, [])

    @classmethod
    def is_valid_role(cls, role: str) -> bool:
        return role in cls.ROLE_PERMISSIONS

class User:
    """User class compatibile con il sistema storage E con il codice esistente"""
    
    def __init__(self, user_id: UUID, username: str, email: str, password_hash: str, 
                 role: str, is_active: bool = True, metadata: Optional[Dict[str, Any]] = None,
                 created_at: Optional[datetime] = None, last_login: Optional[datetime] = None):
        # Proprietà principali
        self.id = user_id  # Per compatibilità con IEntity
        self.user_id = user_id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.role = role
        self.is_active = is_active
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.now(timezone.utc)
        self.last_login = last_login
        
        # Per compatibilità con storage
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

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        user_dict = {
            'id': str(self.user_id),
            'user_id': str(self.user_id),
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'is_active': self.is_active,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat(),
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'status': self.status.value if hasattr(self.status, 'value') else str(self.status)
        }
        if include_sensitive:
            user_dict['password_hash'] = self.password_hash
        return user_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'User':
        return cls(
            user_id=UUID(data['user_id']) if isinstance(data['user_id'], str) else data['user_id'],
            username=data['username'],
            email=data['email'],
            password_hash=data['password_hash'],
            role=data['role'],
            is_active=data.get('is_active', True),
            metadata=data.get('metadata', {}),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else None,
            last_login=datetime.fromisoformat(data['last_login']) if data.get('last_login') else None
        )

class TokenPair:
    def __init__(self, access_token: str, refresh_token: str, token_type: str = 'Bearer',
                 expires_in: int = 3600, refresh_expires_in: int = 86400):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_type = token_type
        self.expires_in = expires_in
        self.refresh_expires_in = refresh_expires_in
        self.issued_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'token_type': self.token_type,
            'expires_in': self.expires_in,
            'refresh_expires_in': self.refresh_expires_in,
            'issued_at': self.issued_at.isoformat()
        }

class RefreshToken:
    def __init__(self, token_id: UUID, user_id: UUID, token_hash: str, 
                 expires_at: datetime, is_revoked: bool = False, 
                 metadata: Optional[Dict[str, Any]] = None):
        self.id = token_id  # Per compatibilità con storage
        self.token_id = token_id
        self.user_id = user_id
        self.token_hash = token_hash
        self.expires_at = expires_at
        self.is_revoked = is_revoked
        self.metadata = metadata or {}
        self.created_at = datetime.now(timezone.utc)
        
        # Per compatibilità con storage
        from src.core.interfaces.base import EntityStatus
        self.status = EntityStatus.ACTIVE

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    def is_valid(self) -> bool:
        return not self.is_expired() and not self.is_revoked

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': str(self.token_id),
            'token_id': str(self.token_id),
            'user_id': str(self.user_id),
            'token_hash': self.token_hash,
            'expires_at': self.expires_at.isoformat(),
            'is_revoked': self.is_revoked,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat(),
            'status': self.status.value if hasattr(self.status, 'value') else str(self.status)
        }

class JWTProvider:
    def __init__(self, secret_key: str = None, algorithm: str = 'HS256'):
        """Costruttore corretto che accetta parametri"""
        from src.utils.config import get_config
        config = get_config()
        
        self.secret_key = secret_key or config.get('jwt.secret_key', 'dev-secret-key')
        self.algorithm = algorithm
        self.users = {}
        self.users_by_id = {}
        self.revoked_tokens = set()
        self._initialized = False
        self._user_adapter = None

    async def initialize(self):
        """Metodo initialize richiesto da __init__.py"""
        if self._initialized:
            return
        
        try:
            # Carica users da MongoDB se disponibile
            from src.layers.application.auth.user_registration import EnhancedUser
            
            self._user_adapter = MongoStorageAdapter(EnhancedUser, twin_id=None)
            await self._user_adapter.connect()
            
            # Carica users esistenti in memoria
            user_entities = await self._user_adapter.query({'is_active': True})
            for user in user_entities:
                self.users[user.username] = user
                self.users_by_id[user.user_id] = user
                
            logger.info(f"JWTProvider loaded {len(self.users)} users from database")
                
        except Exception as e:
            logger.info(f"JWTProvider fallback to memory-only mode: {e}")
        
        self._initialized = True

    async def get_user_by_username(self, username: str) -> Optional['User']:
        """Get user by username - check memory first, then database"""
        # Ensure initialization
        if not self._initialized:
            await self.initialize()
            
        # First check in-memory cache
        user = self.users.get(username.lower().strip())
        if user:
            return user
            
        # If not found in memory and we have database access, check database
        if self._user_adapter:
            try:
                user_entities = await self._user_adapter.query({'username': username.lower().strip()})
                if user_entities:
                    user = user_entities[0]
                    
                    # Cache the user for future access
                    self.users[user.username] = user
                    self.users_by_id[user.user_id] = user
                    
                    return user
            except Exception as e:
                logger.error(f"Error querying user from database: {e}")
        
        return None

    async def get_user_by_id(self, user_id: UUID) -> Optional['User']:
        """Get user by ID - check memory first, then database"""
        # Ensure initialization
        if not self._initialized:
            await self.initialize()
            
        # First check in-memory cache
        user = self.users_by_id.get(user_id)
        if user:
            return user
            
        # If not found in memory and we have database access, check database
        if self._user_adapter:
            try:
                user_entities = await self._user_adapter.query({'entity_id': str(user_id)})
                if user_entities:
                    user = user_entities[0]
                    
                    # Cache the user for future access
                    self.users[user.username] = user
                    self.users_by_id[user.user_id] = user
                    
                    return user
            except Exception as e:
                logger.error(f"Error querying user by ID from database: {e}")
        
        return None

    async def authenticate(self, credentials: Dict[str, str]) -> 'AuthContext':
        """Authenticate user with username/password"""
        # Ensure initialization before authentication
        if not self._initialized:
            await self.initialize()
        
        username = credentials.get('username')
        password = credentials.get('password')
        
        if not username or not password:
            raise AuthenticationError('Username and password required')
        
        user = await self.get_user_by_username(username)
        if not user:
            raise AuthenticationError('Invalid credentials')
        
        # Verify password
        import bcrypt
        if not bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
            raise AuthenticationError('Invalid credentials')
        
        if not user.is_active:
            raise AuthenticationError('User account is inactive')
        
        # Update last login
        await self.update_user_login(username)
        
        # Create AuthContext
        from src.layers.application.auth import AuthContext, AuthSubject, AuthSubjectType, AuthMethod
        
        subject = AuthSubject(
            subject_id=user.user_id,
            subject_type=AuthSubjectType.USER,
            roles=[user.role],
            metadata=user.metadata
        )
        
        return AuthContext(
            subject=subject,
            method=AuthMethod.PASSWORD,
            metadata={'login_time': datetime.now(timezone.utc).isoformat()}
        )

    async def generate_token_pair(self, user: 'User') -> 'TokenPair':
        """Generate JWT token pair for user"""
        import jwt
        from datetime import datetime, timezone, timedelta
        
        now = datetime.now(timezone.utc)
        access_exp = now + timedelta(hours=1)
        refresh_exp = now + timedelta(days=7)
        
        # Access token payload
        access_payload = {
            'sub': str(user.user_id),
            'username': user.username,
            'email': user.email,
            'role': user.role,
            'permissions': user.metadata.get('tenant_permissions', []),
            'iat': now.timestamp(),
            'exp': access_exp.timestamp(),
            'type': 'access'
        }
        
        # Refresh token payload
        refresh_payload = {
            'sub': str(user.user_id),
            'username': user.username,
            'iat': now.timestamp(),
            'exp': refresh_exp.timestamp(),
            'type': 'refresh'
        }
        
        access_token = jwt.encode(access_payload, self.secret_key, algorithm=self.algorithm)
        refresh_token = jwt.encode(refresh_payload, self.secret_key, algorithm=self.algorithm)
        
        # Create TokenPair object
        from collections import namedtuple
        TokenPair = namedtuple('TokenPair', ['access_token', 'refresh_token', 'token_type', 'expires_in'])
        
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type='Bearer',
            expires_in=3600
        )

    async def refresh_token(self, refresh_token: str) -> 'TokenPair':
        """Refresh access token using refresh token"""
        import jwt
        
        try:
            payload = jwt.decode(refresh_token, self.secret_key, algorithms=[self.algorithm])
            
            if payload.get('type') != 'refresh':
                raise AuthenticationError('Invalid token type')
            
            if refresh_token in self.revoked_tokens:
                raise AuthenticationError('Token has been revoked')
            
            user_id = UUID(payload['sub'])
            user = await self.get_user_by_id(user_id)
            
            if not user or not user.is_active:
                raise AuthenticationError('User not found or inactive')
            
            # Generate new token pair
            return await self.generate_token_pair(user)
            
        except jwt.ExpiredSignatureError:
            raise AuthenticationError('Refresh token expired')
        except jwt.InvalidTokenError:
            raise AuthenticationError('Invalid refresh token')

    async def revoke_token(self, token: str) -> None:
        """Revoke a token"""
        self.revoked_tokens.add(token)

    async def revoke_all_user_tokens(self, user_id: UUID) -> None:
        """Revoke all tokens for a user"""
        # In a real implementation, you'd track tokens per user
        # For now, we'll just add a placeholder
        pass

    async def update_user_login(self, username: str) -> None:
        """Update user's last login timestamp in both memory and database"""
        user = await self.get_user_by_username(username)
        if not user:
            return
            
        # Update in memory
        user.last_login = datetime.now(timezone.utc)
        
        # Update in database if available
        if self._user_adapter:
            try:
                user_entities = await self._user_adapter.query({'username': username.lower().strip()})
                if user_entities:
                    user_entity = user_entities[0]
                    user_entity.last_login = user.last_login
                    await self._user_adapter.save(user_entity)
            except Exception as e:
                logger.error(f"Error updating user login in database: {e}")

    async def list_users(self, include_inactive: bool = True) -> List[Dict[str, Any]]:
        """List all users from database"""
        # Ensure initialization
        if not self._initialized:
            await self.initialize()
            
        users = []
        
        if self._user_adapter:
            try:
                query = {} if include_inactive else {'is_active': True}
                user_entities = await self._user_adapter.query(query)
                
                for user_entity in user_entities:
                    user_dict = user_entity.to_dict() if hasattr(user_entity, 'to_dict') else user_entity.__dict__
                    users.append(user_dict)
                    
            except Exception as e:
                logger.error(f"Error listing users from database: {e}")
                # Fallback to in-memory users
                users = [user.to_dict() for user in self.users.values() 
                        if include_inactive or user.is_active]
        else:
            # Fallback to in-memory users
            users = [user.to_dict() for user in self.users.values() 
                    if include_inactive or user.is_active]
        
        return users