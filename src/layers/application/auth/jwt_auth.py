"""
JWT Authentication Provider for the Digital Twin Platform.

This module handles JWT-based authentication for dashboard users,
including user management, token generation/validation, and role-based access control.

LOCATION: src/layers/application/auth/jwt_auth.py
"""

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
from src.utils.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ValidationError
)
from src.utils.config import get_config

logger = logging.getLogger(__name__)


class UserRole:
    """User roles with associated permissions."""
    
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    
    # Role-based permissions mapping
    ROLE_PERMISSIONS = {
        ADMIN: [
            "admin:*",  # Admin has all permissions
        ],
        OPERATOR: [
            "digital_twin:read", "digital_twin:write", "digital_twin:execute",
            "service:read", "service:write", "service:execute",
            "replica:read", "replica:write", "replica:manage",
            "workflow:read", "workflow:write", "workflow:execute",
            "system:monitor"
        ],
        VIEWER: [
            "digital_twin:read",
            "service:read",
            "replica:read", 
            "workflow:read",
            "system:monitor"
        ]
    }
    
    @classmethod
    def get_permissions(cls, role: str) -> List[str]:
        """Get permissions for a specific role."""
        return cls.ROLE_PERMISSIONS.get(role, [])
    
    @classmethod
    def is_valid_role(cls, role: str) -> bool:
        """Check if a role is valid."""
        return role in cls.ROLE_PERMISSIONS


class User:
    """User entity for JWT authentication."""
    
    def __init__(
        self,
        user_id: UUID,
        username: str,
        email: str,
        password_hash: str,
        role: str,
        is_active: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
        last_login: Optional[datetime] = None
    ):
        self.user_id = user_id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.role = role
        self.is_active = is_active
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.now(timezone.utc)
        self.last_login = last_login
    
    def check_password(self, password: str) -> bool:
        """Check if provided password matches the stored hash."""
        try:
            return bcrypt.checkpw(
                password.encode('utf-8'),
                self.password_hash.encode('utf-8')
            )
        except Exception as e:
            logger.error(f"Password check failed for user {self.username}: {e}")
            return False
    
    def get_permissions(self) -> List[str]:
        """Get user permissions based on role."""
        base_permissions = UserRole.get_permissions(self.role)
        
        # Add any custom permissions from metadata
        custom_permissions = self.metadata.get("custom_permissions", [])
        
        return base_permissions + custom_permissions
    
    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        """Convert user to dictionary representation."""
        user_dict = {
            "user_id": str(self.user_id),
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None
        }
        
        if include_sensitive:
            user_dict["password_hash"] = self.password_hash
        
        return user_dict
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'User':
        """Create user from dictionary representation."""
        return cls(
            user_id=UUID(data["user_id"]),
            username=data["username"],
            email=data["email"],
            password_hash=data["password_hash"],
            role=data["role"],
            is_active=data.get("is_active", True),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            last_login=datetime.fromisoformat(data["last_login"]) if data.get("last_login") else None
        )


class TokenPair:
    """Access and refresh token pair."""
    
    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        token_type: str = "Bearer",
        expires_in: int = 3600,
        refresh_expires_in: int = 86400
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_type = token_type
        self.expires_in = expires_in
        self.refresh_expires_in = refresh_expires_in
        self.issued_at = datetime.now(timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert token pair to dictionary representation."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
            "refresh_expires_in": self.refresh_expires_in,
            "issued_at": self.issued_at.isoformat()
        }


class RefreshToken:
    """Refresh token entity for token rotation."""
    
    def __init__(
        self,
        token_id: UUID,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
        is_revoked: bool = False,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.token_id = token_id
        self.user_id = user_id
        self.token_hash = token_hash
        self.expires_at = expires_at
        self.is_revoked = is_revoked
        self.metadata = metadata or {}
        self.created_at = datetime.now(timezone.utc)
    
    def is_expired(self) -> bool:
        """Check if refresh token is expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    def is_valid(self) -> bool:
        """Check if refresh token is valid (not expired and not revoked)."""
        return not self.is_expired() and not self.is_revoked
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert refresh token to dictionary representation."""
        return {
            "token_id": str(self.token_id),
            "user_id": str(self.user_id),
            "token_hash": self.token_hash,
            "expires_at": self.expires_at.isoformat(),
            "is_revoked": self.is_revoked,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat()
        }


class JWTProvider:
    """
    JWT Authentication Provider for the Digital Twin Platform.
    
    Handles user authentication, JWT token generation and validation,
    refresh token management, and user role-based permissions.
    """
    
    def __init__(self):
        self.config = get_config()
        
        # JWT configuration
        self.secret_key = self._get_jwt_secret()
        self.algorithm = "HS256"
        self.access_token_expire_minutes = 60  # 1 hour
        self.refresh_token_expire_days = 7     # 7 days
        
        # In-memory storage for development (replace with database in production)
        self.users: Dict[str, User] = {}           # username -> User
        self.users_by_id: Dict[UUID, User] = {}   # user_id -> User
        self.refresh_tokens: Dict[str, RefreshToken] = {}  # token_hash -> RefreshToken
        
        # Session tracking
        self.active_sessions: Dict[str, List[datetime]] = {}  # user_id -> login times
        self.max_sessions_per_user = 5
        
        self._initialized = False
        
        logger.info("JWT Provider initialized")
    
    async def initialize(self) -> None:
        """Initialize JWT provider with default users."""
        if self._initialized:
            return
        
        try:
            # Create default users for development
            await self._create_default_users()
            
            self._initialized = True
            logger.info(f"JWT Provider initialized with {len(self.users)} users")
            
        except Exception as e:
            logger.error(f"Failed to initialize JWT Provider: {e}")
            raise AuthenticationError(f"JWT Provider initialization failed: {e}")
    
    async def authenticate(self, credentials: Dict[str, Any]) -> AuthContext:
        """
        Authenticate user with username/password credentials.
        
        Args:
            credentials: Dictionary with 'username' and 'password'
            
        Returns:
            AuthContext for the authenticated user
        """
        username = credentials.get("username")
        password = credentials.get("password")
        
        if not username or not password:
            raise AuthenticationError("Username and password required")
        
        # Find user
        user = self.users.get(username.lower())
        if not user:
            logger.warning(f"Authentication attempt for unknown user: {username}")
            raise AuthenticationError("Invalid credentials")
        
        # Check if user is active
        if not user.is_active:
            logger.warning(f"Authentication attempt for inactive user: {username}")
            raise AuthenticationError("User account is disabled")
        
        # Verify password
        if not user.check_password(password):
            logger.warning(f"Invalid password for user: {username}")
            raise AuthenticationError("Invalid credentials")
        
        # Update last login
        user.last_login = datetime.now(timezone.utc)
        
        # Track session
        await self._track_user_session(user.user_id)
        
        # Create auth context
        context = AuthContext(
            subject_type=AuthSubjectType.USER,
            subject_id=user.user_id,
            auth_method=AuthMethod.JWT_TOKEN,
            permissions=user.get_permissions(),
            metadata={
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "last_login": user.last_login.isoformat()
            },
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=self.access_token_expire_minutes)
        )
        
        logger.info(f"User authenticated successfully: {username}")
        return context
    
    async def generate_token_pair(self, user: User) -> TokenPair:
        """Generate JWT access and refresh token pair for user."""
        now = datetime.now(timezone.utc)
        
        # Access token payload
        access_payload = {
            "sub": str(user.user_id),
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "permissions": user.get_permissions(),
            "iat": now.timestamp(),
            "exp": (now + timedelta(minutes=self.access_token_expire_minutes)).timestamp(),
            "type": "access"
        }
        
        # Generate access token
        access_token = jwt.encode(access_payload, self.secret_key, algorithm=self.algorithm)
        
        # Generate refresh token
        refresh_token_raw = secrets.token_urlsafe(32)
        refresh_token_hash = hashlib.sha256(refresh_token_raw.encode()).hexdigest()
        
        # Store refresh token
        refresh_token_entity = RefreshToken(
            token_id=uuid4(),
            user_id=user.user_id,
            token_hash=refresh_token_hash,
            expires_at=now + timedelta(days=self.refresh_token_expire_days),
            metadata={"username": user.username}
        )
        
        self.refresh_tokens[refresh_token_hash] = refresh_token_entity
        
        # Cleanup old refresh tokens for user
        await self._cleanup_user_refresh_tokens(user.user_id)
        
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token_raw,
            expires_in=self.access_token_expire_minutes * 60,
            refresh_expires_in=self.refresh_token_expire_days * 86400
        )
    
    async def validate_token(self, token: str) -> AuthContext:
        """
        Validate JWT access token and return auth context.
        
        Args:
            token: JWT access token string
            
        Returns:
            AuthContext for the token
        """
        try:
            # Decode token
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            
            # Validate token type
            if payload.get("type") != "access":
                raise AuthenticationError("Invalid token type")
            
            # Extract user information
            user_id = UUID(payload["sub"])
            username = payload["username"]
            role = payload["role"]
            permissions = payload.get("permissions", [])
            
            # Verify user still exists and is active
            user = self.users_by_id.get(user_id)
            if not user or not user.is_active:
                raise AuthenticationError("User no longer exists or is inactive")
            
            # Create auth context
            expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
            
            context = AuthContext(
                subject_type=AuthSubjectType.USER,
                subject_id=user_id,
                auth_method=AuthMethod.JWT_TOKEN,
                permissions=permissions,
                metadata={
                    "username": username,
                    "email": payload.get("email"),
                    "role": role,
                    "token_issued_at": datetime.fromtimestamp(payload["iat"], tz=timezone.utc).isoformat()
                },
                expires_at=expires_at
            )
            
            return context
            
        except jwt.ExpiredSignatureError:
            raise AuthenticationError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise AuthenticationError(f"Invalid token: {e}")
        except Exception as e:
            logger.error(f"Token validation failed: {e}")
            raise AuthenticationError("Token validation failed")
    
    async def refresh_token(self, refresh_token: str) -> TokenPair:
        """
        Refresh access token using refresh token.
        
        Args:
            refresh_token: Refresh token string
            
        Returns:
            New token pair
        """
        # Hash the refresh token
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        
        # Find refresh token
        refresh_token_entity = self.refresh_tokens.get(token_hash)
        if not refresh_token_entity:
            raise AuthenticationError("Invalid refresh token")
        
        # Validate refresh token
        if not refresh_token_entity.is_valid():
            # Remove invalid token
            self.refresh_tokens.pop(token_hash, None)
            raise AuthenticationError("Refresh token is expired or revoked")
        
        # Get user
        user = self.users_by_id.get(refresh_token_entity.user_id)
        if not user or not user.is_active:
            # Revoke token and cleanup
            refresh_token_entity.is_revoked = True
            raise AuthenticationError("User no longer exists or is inactive")
        
        # Revoke old refresh token
        refresh_token_entity.is_revoked = True
        
        # Generate new token pair
        new_token_pair = await self.generate_token_pair(user)
        
        logger.info(f"Token refreshed for user: {user.username}")
        return new_token_pair
    
    async def revoke_token(self, token: str) -> None:
        """Revoke a refresh token."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        refresh_token_entity = self.refresh_tokens.get(token_hash)
        if refresh_token_entity:
            refresh_token_entity.is_revoked = True
            logger.info(f"Refresh token revoked for user: {refresh_token_entity.user_id}")
    
    async def revoke_all_user_tokens(self, user_id: UUID) -> None:
        """Revoke all refresh tokens for a user."""
        revoked_count = 0
        for refresh_token in self.refresh_tokens.values():
            if refresh_token.user_id == user_id and not refresh_token.is_revoked:
                refresh_token.is_revoked = True
                revoked_count += 1
        
        logger.info(f"Revoked {revoked_count} tokens for user: {user_id}")
    
    async def create_user(
        self,
        username: str,
        email: str,
        password: str,
        role: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> User:
        """Create a new user."""
        # Validate input
        if not username or not email or not password:
            raise ValidationError("Username, email, and password are required")
        
        if not UserRole.is_valid_role(role):
            raise ValidationError(f"Invalid role: {role}")
        
        username = username.lower().strip()
        email = email.lower().strip()
        
        # Check for existing user
        if username in self.users:
            raise ValidationError(f"Username already exists: {username}")
        
        # Check for existing email
        for user in self.users.values():
            if user.email == email:
                raise ValidationError(f"Email already exists: {email}")
        
        # Hash password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Create user
        user = User(
            user_id=uuid4(),
            username=username,
            email=email,
            password_hash=password_hash,
            role=role,
            metadata=metadata or {}
        )
        
        # Store user
        self.users[username] = user
        self.users_by_id[user.user_id] = user
        
        logger.info(f"User created: {username} with role {role}")
        return user
    
    async def update_user(
        self,
        user_id: UUID,
        updates: Dict[str, Any]
    ) -> User:
        """Update user information."""
        user = self.users_by_id.get(user_id)
        if not user:
            raise ValidationError(f"User not found: {user_id}")
        
        # Update allowed fields
        if "email" in updates:
            user.email = updates["email"].lower().strip()
        
        if "role" in updates:
            if not UserRole.is_valid_role(updates["role"]):
                raise ValidationError(f"Invalid role: {updates['role']}")
            user.role = updates["role"]
        
        if "is_active" in updates:
            user.is_active = updates["is_active"]
        
        if "metadata" in updates:
            user.metadata.update(updates["metadata"])
        
        logger.info(f"User updated: {user.username}")
        return user
    
    async def change_password(
        self,
        user_id: UUID,
        old_password: str,
        new_password: str
    ) -> None:
        """Change user password."""
        user = self.users_by_id.get(user_id)
        if not user:
            raise ValidationError(f"User not found: {user_id}")
        
        # Verify old password
        if not user.check_password(old_password):
            raise AuthenticationError("Current password is incorrect")
        
        # Hash new password
        new_password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        user.password_hash = new_password_hash
        
        # Revoke all existing tokens to force re-authentication
        await self.revoke_all_user_tokens(user_id)
        
        logger.info(f"Password changed for user: {user.username}")
    
    def get_user_permissions(self, user_id: UUID) -> List[str]:
        """Get permissions for a user."""
        user = self.users_by_id.get(user_id)
        if user:
            return user.get_permissions()
        return []
    
    async def list_users(
        self,
        include_inactive: bool = False
    ) -> List[Dict[str, Any]]:
        """List all users."""
        users = []
        for user in self.users.values():
            if include_inactive or user.is_active:
                users.append(user.to_dict())
        return users
    
    async def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        """Get user by ID."""
        return self.users_by_id.get(user_id)
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        return self.users.get(username.lower())
    
    async def _create_default_users(self) -> None:
        """Create default users for development and testing."""
        default_users = [
            {
                "username": "admin",
                "email": "admin@digitaltwin.platform",
                "password": "admin123",
                "role": UserRole.ADMIN,
                "metadata": {"default_user": True, "description": "Default admin user"}
            },
            {
                "username": "operator",
                "email": "operator@digitaltwin.platform", 
                "password": "operator123",
                "role": UserRole.OPERATOR,
                "metadata": {"default_user": True, "description": "Default operator user"}
            },
            {
                "username": "viewer",
                "email": "viewer@digitaltwin.platform",
                "password": "viewer123", 
                "role": UserRole.VIEWER,
                "metadata": {"default_user": True, "description": "Default viewer user"}
            }
        ]
        
        for user_data in default_users:
            try:
                await self.create_user(**user_data)
            except ValidationError as e:
                # User already exists
                logger.debug(f"Default user already exists: {user_data['username']}")
    
    async def _track_user_session(self, user_id: UUID) -> None:
        """Track user session for concurrent session limiting."""
        user_id_str = str(user_id)
        now = datetime.now(timezone.utc)
        
        if user_id_str not in self.active_sessions:
            self.active_sessions[user_id_str] = []
        
        # Add current session
        self.active_sessions[user_id_str].append(now)
        
        # Remove old sessions (older than 24 hours)
        cutoff = now - timedelta(hours=24)
        self.active_sessions[user_id_str] = [
            session for session in self.active_sessions[user_id_str]
            if session > cutoff
        ]
        
        # Check session limit
        if len(self.active_sessions[user_id_str]) > self.max_sessions_per_user:
            logger.warning(f"User {user_id} exceeded max sessions limit")
    
    async def _cleanup_user_refresh_tokens(self, user_id: UUID) -> None:
        """Clean up expired refresh tokens for a user."""
        tokens_to_remove = []
        
        for token_hash, refresh_token in self.refresh_tokens.items():
            if (refresh_token.user_id == user_id and 
                (refresh_token.is_expired() or refresh_token.is_revoked)):
                tokens_to_remove.append(token_hash)
        
        for token_hash in tokens_to_remove:
            del self.refresh_tokens[token_hash]
        
        if tokens_to_remove:
            logger.debug(f"Cleaned up {len(tokens_to_remove)} expired tokens for user {user_id}")
    
    def _get_jwt_secret(self) -> str:
        """Get JWT secret key from configuration."""
        jwt_config = self.config.get("jwt", {})
        secret = jwt_config.get("secret_key")
        
        if not secret:
            # Generate a development secret (not for production!)
            secret = "dev-jwt-secret-key-change-in-production"
            logger.warning("Using development JWT secret. Change this in production!")
        
        return secret
    
    def get_provider_status(self) -> Dict[str, Any]:
        """Get JWT provider status and statistics."""
        active_tokens = len([
            token for token in self.refresh_tokens.values()
            if token.is_valid()
        ])
        
        return {
            "initialized": self._initialized,
            "total_users": len(self.users),
            "active_users": len([u for u in self.users.values() if u.is_active]),
            "active_refresh_tokens": active_tokens,
            "total_refresh_tokens": len(self.refresh_tokens),
            "active_sessions": sum(len(sessions) for sessions in self.active_sessions.values()),
            "configuration": {
                "access_token_expire_minutes": self.access_token_expire_minutes,
                "refresh_token_expire_days": self.refresh_token_expire_days,
                "max_sessions_per_user": self.max_sessions_per_user,
                "algorithm": self.algorithm
            }
        }