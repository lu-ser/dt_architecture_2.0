"""
Authentication Layer for the Digital Twin Platform.

This module provides the central authentication and authorization system,
supporting both JWT authentication for dashboard users and API key authentication
for external applications.

LOCATION: src/layers/application/auth/__init__.py
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from uuid import UUID
from enum import Enum

from fastapi import HTTPException, Request, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.utils.exceptions import (
    AuthenticationError
)
from src.utils.config import get_config

logger = logging.getLogger(__name__)


class AuthSubjectType(Enum):
    """Types of authentication subjects."""
    USER = "user"               # Dashboard user with JWT
    APPLICATION = "application" # External app with API key
    SYSTEM = "system"          # Internal system operations


class AuthMethod(Enum):
    """Authentication methods supported."""
    JWT_TOKEN = "jwt_token"
    API_KEY = "api_key"
    SYSTEM_TOKEN = "system_token"


class AuthContext:
    """
    Authentication context for authenticated requests.
    
    Contains all information about the authenticated subject
    and their permissions within the platform.
    """
    
    def __init__(
        self,
        subject_type: AuthSubjectType,
        subject_id: UUID,
        auth_method: AuthMethod,
        permissions: List[str],
        metadata: Optional[Dict[str, Any]] = None,
        expires_at: Optional[datetime] = None
    ):
        self.subject_type = subject_type
        self.subject_id = subject_id
        self.auth_method = auth_method
        self.permissions = permissions
        self.metadata = metadata or {}
        self.expires_at = expires_at
        self.authenticated_at = datetime.now(timezone.utc)
    
    def has_permission(self, permission: str) -> bool:
        """Check if the subject has a specific permission."""
        # Support for wildcard permissions (admin:* grants all admin permissions)
        for perm in self.permissions:
            if perm == permission:
                return True
            if perm.endswith(':*') and permission.startswith(perm[:-1]):
                return True
        return False
    
    def has_any_permission(self, permissions: List[str]) -> bool:
        """Check if the subject has any of the specified permissions."""
        return any(self.has_permission(perm) for perm in permissions)
    
    def has_all_permissions(self, permissions: List[str]) -> bool:
        """Check if the subject has all of the specified permissions."""
        return all(self.has_permission(perm) for perm in permissions)
    
    def is_expired(self) -> bool:
        """Check if the authentication context has expired."""
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) > self.expires_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert auth context to dictionary representation."""
        return {
            "subject_type": self.subject_type.value,
            "subject_id": str(self.subject_id),
            "auth_method": self.auth_method.value,
            "permissions": self.permissions,
            "metadata": self.metadata,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "authenticated_at": self.authenticated_at.isoformat()
        }


class AuthSubject:
    """Represents an authenticated subject (user or application)."""
    
    def __init__(
        self,
        subject_id: UUID,
        subject_type: AuthSubjectType,
        name: str,
        permissions: List[str],
        metadata: Optional[Dict[str, Any]] = None,
        is_active: bool = True
    ):
        self.subject_id = subject_id
        self.subject_type = subject_type
        self.name = name
        self.permissions = permissions
        self.metadata = metadata or {}
        self.is_active = is_active
        self.created_at = datetime.now(timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert subject to dictionary representation."""
        return {
            "subject_id": str(self.subject_id),
            "subject_type": self.subject_type.value,
            "name": self.name,
            "permissions": self.permissions,
            "metadata": self.metadata,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat()
        }


class AuthenticationManager:
    """
    Central authentication manager for the Digital Twin Platform.
    
    Coordinates JWT authentication for users and API key authentication
    for external applications, providing a unified interface for all
    authentication and authorization operations.
    """
    
    def __init__(self):
        self.config = get_config()
        
        # Will be initialized with actual providers in the next files
        self.jwt_provider = None
        self.api_key_provider = None
        self.permission_manager = None
        
        # Authentication cache for performance
        self._auth_cache: Dict[str, AuthContext] = {}
        self._cache_timeout = 300  # 5 minutes
        
        # Security settings
        self.max_auth_attempts = 5
        self.lockout_duration = 300  # 5 minutes
        self._failed_attempts: Dict[str, List[datetime]] = {}
        
        self._initialized = False
        
        logger.info("Authentication Manager initialized")
    
    async def initialize(self) -> None:
        """Initialize authentication providers."""
        if self._initialized:
            return
        
        try:
            # Import and initialize providers
            # These will be implemented in the next files
            from .jwt_auth import JWTProvider
            from .api_key_auth import APIKeyProvider
            from .permissions import PermissionManager
            
            self.jwt_provider = JWTProvider()
            self.api_key_provider = APIKeyProvider()
            self.permission_manager = PermissionManager()
            
            # Initialize providers
            await self.jwt_provider.initialize()
            await self.api_key_provider.initialize()
            await self.permission_manager.initialize()
            
            self._initialized = True
            logger.info("Authentication Manager fully initialized")
            
        except ImportError:
            # Providers not yet implemented - use mock mode
            logger.warning("Authentication providers not yet implemented, using mock mode")
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize Authentication Manager: {e}")
            raise AuthenticationError(f"Authentication initialization failed: {e}")
    
    async def authenticate_request(self, request: Request) -> AuthContext:
        """
        Authenticate an incoming request using various methods.
        
        Args:
            request: FastAPI request object
            
        Returns:
            AuthContext for the authenticated subject
            
        Raises:
            AuthenticationError: If authentication fails
        """
        if not self._initialized:
            await self.initialize()
        
        # Extract authentication credentials
        auth_header = request.headers.get("Authorization")
        api_key_header = request.headers.get("X-API-Key")
        
        # Try different authentication methods
        try:
            # 1. Try JWT Authentication
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]  # Remove "Bearer " prefix
                return await self._authenticate_jwt(token)
            
            # 2. Try API Key Authentication
            if api_key_header:
                return await self._authenticate_api_key(api_key_header)
            
            # 3. Check for system token (internal operations)
            system_token = request.headers.get("X-System-Token")
            if system_token:
                return await self._authenticate_system_token(system_token)
            
            # No authentication provided
            raise AuthenticationError("No authentication credentials provided")
            
        except Exception as e:
            # Log authentication attempt
            client_ip = request.client.host if request.client else "unknown"
            logger.warning(f"Authentication failed from {client_ip}: {e}")
            
            # Track failed attempts for rate limiting
            await self._track_failed_attempt(client_ip)
            
            raise AuthenticationError(f"Authentication failed: {e}")
    
    async def authenticate_credentials(
        self,
        credentials: Dict[str, Any],
        auth_method: AuthMethod
    ) -> AuthContext:
        """
        Authenticate using provided credentials.
        
        Args:
            credentials: Authentication credentials
            auth_method: Method to use for authentication
            
        Returns:
            AuthContext for the authenticated subject
        """
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
                raise AuthenticationError(f"Unsupported authentication method: {auth_method}")
                
        except Exception as e:
            logger.error(f"Credential authentication failed: {e}")
            raise AuthenticationError(f"Authentication failed: {e}")
    
    async def authorize_operation(
        self,
        auth_context: AuthContext,
        operation: str,
        resource: str,
        resource_id: Optional[UUID] = None
    ) -> bool:
        """
        Authorize an operation for an authenticated subject.
        
        Args:
            auth_context: Authentication context
            operation: Operation to authorize (read, write, execute, etc.)
            resource: Resource type (digital_twin, service, replica, etc.)
            resource_id: Optional specific resource ID
            
        Returns:
            True if authorized, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Check if auth context is expired
            if auth_context.is_expired():
                logger.warning(f"Expired auth context for {auth_context.subject_id}")
                return False
            
            # Build permission string
            if resource_id:
                permission = f"{resource}:{resource_id}:{operation}"
                # Also check for general resource permission
                general_permission = f"{resource}:{operation}"
            else:
                permission = f"{resource}:{operation}"
                general_permission = permission
            
            # Check permissions
            if auth_context.has_permission(permission):
                return True
            
            if resource_id and auth_context.has_permission(general_permission):
                return True
            
            # Check for admin permissions
            if auth_context.has_permission("admin:*"):
                return True
            
            # Use permission manager if available
            if self.permission_manager:
                return await self.permission_manager.check_permission(
                    auth_context, operation, resource, resource_id
                )
            
            logger.warning(
                f"Authorization denied for {auth_context.subject_id}: "
                f"{operation} on {resource}:{resource_id}"
            )
            return False
            
        except Exception as e:
            logger.error(f"Authorization check failed: {e}")
            return False
    
    async def get_auth_context_from_cache(self, cache_key: str) -> Optional[AuthContext]:
        """Get authentication context from cache."""
        if cache_key in self._auth_cache:
            context = self._auth_cache[cache_key]
            if not context.is_expired():
                return context
            else:
                # Remove expired context
                del self._auth_cache[cache_key]
        return None
    
    def cache_auth_context(self, cache_key: str, context: AuthContext) -> None:
        """Cache authentication context for performance."""
        # Limit cache size
        if len(self._auth_cache) > 1000:
            # Remove oldest entries
            oldest_key = min(self._auth_cache.keys())
            del self._auth_cache[oldest_key]
        
        self._auth_cache[cache_key] = context
    
    async def invalidate_auth_cache(self, subject_id: Optional[UUID] = None) -> None:
        """Invalidate authentication cache."""
        if subject_id:
            # Remove specific subject from cache
            keys_to_remove = [
                key for key, context in self._auth_cache.items()
                if context.subject_id == subject_id
            ]
            for key in keys_to_remove:
                del self._auth_cache[key]
        else:
            # Clear entire cache
            self._auth_cache.clear()
    
    async def _authenticate_jwt(self, token: str) -> AuthContext:
        """Authenticate using JWT token."""
        # Check cache first
        cache_key = f"jwt:{token[:16]}"  # Use token prefix as cache key
        cached_context = await self.get_auth_context_from_cache(cache_key)
        if cached_context:
            return cached_context
        
        if self.jwt_provider:
            context = await self.jwt_provider.validate_token(token)
        else:
            context = await self._mock_jwt_validation(token)
        
        # Cache the context
        self.cache_auth_context(cache_key, context)
        return context
    
    async def _authenticate_api_key(self, api_key: str) -> AuthContext:
        """Authenticate using API key."""
        # Check cache first
        cache_key = f"api_key:{api_key[:16]}"
        cached_context = await self.get_auth_context_from_cache(cache_key)
        if cached_context:
            return cached_context
        
        if self.api_key_provider:
            context = await self.api_key_provider.validate_api_key(api_key)
        else:
            context = await self._mock_api_key_validation(api_key)
        
        # Cache the context
        self.cache_auth_context(cache_key, context)
        return context
    
    async def _authenticate_system_token(self, system_token: str) -> AuthContext:
        """Authenticate using system token for internal operations."""
        # Simple system token validation
        expected_token = self.config.get("system", {}).get("internal_token", "system-token-123")
        
        if system_token != expected_token:
            raise AuthenticationError("Invalid system token")
        
        # Return system context with all permissions
        return AuthContext(
            subject_type=AuthSubjectType.SYSTEM,
            subject_id=UUID("00000000-0000-0000-0000-000000000000"),
            auth_method=AuthMethod.SYSTEM_TOKEN,
            permissions=["admin:*"],
            metadata={"system": True}
        )
    
    async def _track_failed_attempt(self, identifier: str) -> None:
        """Track failed authentication attempts for rate limiting."""
        now = datetime.now(timezone.utc)
        
        if identifier not in self._failed_attempts:
            self._failed_attempts[identifier] = []
        
        # Add current attempt
        self._failed_attempts[identifier].append(now)
        
        # Remove old attempts (outside lockout window)
        cutoff = now.timestamp() - self.lockout_duration
        self._failed_attempts[identifier] = [
            attempt for attempt in self._failed_attempts[identifier]
            if attempt.timestamp() > cutoff
        ]
        
        # Check if lockout threshold exceeded
        if len(self._failed_attempts[identifier]) >= self.max_auth_attempts:
            logger.warning(f"Authentication lockout triggered for {identifier}")
            raise AuthenticationError(
                f"Too many failed attempts. Try again in {self.lockout_duration} seconds."
            )
    
    # Mock authentication methods for development (until providers are implemented)
    async def _mock_jwt_auth(self, credentials: Dict[str, Any]) -> AuthContext:
        """Mock JWT authentication for development."""
        username = credentials.get("username", "mock_user")
        return AuthContext(
            subject_type=AuthSubjectType.USER,
            subject_id=UUID("12345678-1234-1234-1234-123456789012"),
            auth_method=AuthMethod.JWT_TOKEN,
            permissions=["digital_twin:*", "service:*", "replica:*"],
            metadata={"username": username, "mock": True}
        )
    
    async def _mock_jwt_validation(self, token: str) -> AuthContext:
        """Mock JWT token validation for development."""
        if token == "mock-jwt-token":
            return AuthContext(
                subject_type=AuthSubjectType.USER,
                subject_id=UUID("12345678-1234-1234-1234-123456789012"),
                auth_method=AuthMethod.JWT_TOKEN,
                permissions=["digital_twin:*", "service:*", "replica:*"],
                metadata={"username": "mock_user", "mock": True}
            )
        raise AuthenticationError("Invalid JWT token")
    
    async def _mock_api_key_auth(self, credentials: Dict[str, Any]) -> AuthContext:
        """Mock API key authentication for development."""
        api_key = credentials.get("api_key", "mock-api-key")
        return AuthContext(
            subject_type=AuthSubjectType.APPLICATION,
            subject_id=UUID("87654321-4321-4321-4321-210987654321"),
            auth_method=AuthMethod.API_KEY,
            permissions=["digital_twin:read", "service:execute"],
            metadata={"application": "mock_app", "mock": True}
        )
    
    async def _mock_api_key_validation(self, api_key: str) -> AuthContext:
        """Mock API key validation for development."""
        if api_key == "mock-api-key-123":
            return AuthContext(
                subject_type=AuthSubjectType.APPLICATION,
                subject_id=UUID("87654321-4321-4321-4321-210987654321"),
                auth_method=AuthMethod.API_KEY,
                permissions=["digital_twin:read", "service:execute"],
                metadata={"application": "mock_app", "mock": True}
            )
        raise AuthenticationError("Invalid API key")
    
    def get_auth_status(self) -> Dict[str, Any]:
        """Get authentication system status."""
        return {
            "initialized": self._initialized,
            "providers": {
                "jwt_provider": self.jwt_provider is not None,
                "api_key_provider": self.api_key_provider is not None,
                "permission_manager": self.permission_manager is not None
            },
            "cache_size": len(self._auth_cache),
            "failed_attempts": len(self._failed_attempts),
            "security_settings": {
                "max_auth_attempts": self.max_auth_attempts,
                "lockout_duration": self.lockout_duration,
                "cache_timeout": self._cache_timeout
            }
        }


# Global authentication manager instance
_auth_manager: Optional[AuthenticationManager] = None


def get_auth_manager() -> AuthenticationManager:
    """Get the global authentication manager instance."""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthenticationManager()
    return _auth_manager


async def initialize_authentication() -> AuthenticationManager:
    """Initialize the authentication system."""
    global _auth_manager
    _auth_manager = AuthenticationManager()
    await _auth_manager.initialize()
    return _auth_manager


# FastAPI Dependencies
security = HTTPBearer(auto_error=False)


async def get_auth_context(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> AuthContext:
    """
    FastAPI dependency to get authentication context for requests.
    
    Usage in endpoints:
    ```python
    @app.get("/protected")
    async def protected_endpoint(auth: AuthContext = Depends(get_auth_context)):
        # auth contains the authenticated subject info
    ```
    """
    auth_manager = get_auth_manager()
    return await auth_manager.authenticate_request(request)


async def get_current_user(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
    """
    FastAPI dependency to ensure user authentication (not API key).
    
    Usage in endpoints that require user authentication:
    ```python
    @app.get("/user-only")
    async def user_only_endpoint(user: AuthContext = Depends(get_current_user)):
        # Only authenticated users can access this
    ```
    """
    if auth.subject_type != AuthSubjectType.USER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User authentication required"
        )
    return auth


async def get_current_application(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
    """
    FastAPI dependency to ensure application authentication (API key).
    
    Usage in endpoints that require application authentication:
    ```python
    @app.get("/app-only")
    async def app_only_endpoint(app: AuthContext = Depends(get_current_application)):
        # Only authenticated applications can access this
    ```
    """
    if auth.subject_type != AuthSubjectType.APPLICATION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Application authentication required"
        )
    return auth


def require_permission(permission: str):
    """
    Create a dependency that requires a specific permission.
    
    Usage:
    ```python
    @app.post("/digital-twins")
    async def create_twin(
        auth: AuthContext = Depends(require_permission("digital_twin:write"))
    ):
        # Only subjects with digital_twin:write permission can access
    ```
    """
    async def permission_checker(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if not auth.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: {permission}"
            )
        return auth
    
    return permission_checker


def require_any_permission(permissions: List[str]):
    """
    Create a dependency that requires any of the specified permissions.
    
    Usage:
    ```python
    @app.get("/digital-twins")
    async def list_twins(
        auth: AuthContext = Depends(require_any_permission(["digital_twin:read", "admin:*"]))
    ):
        # Subjects with either permission can access
    ```
    """
    async def permission_checker(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if not auth.has_any_permission(permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of these permissions required: {permissions}"
            )
        return auth
    
    return permission_checker


def require_all_permissions(permissions: List[str]):
    """
    Create a dependency that requires all of the specified permissions.
    """
    async def permission_checker(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if not auth.has_all_permissions(permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"All of these permissions required: {permissions}"
            )
        return auth
    
    return permission_checker


# Standard permission constants
class Permissions:
    """Standard permission constants for the platform."""
    
    # Digital Twin permissions
    DIGITAL_TWIN_READ = "digital_twin:read"
    DIGITAL_TWIN_WRITE = "digital_twin:write"
    DIGITAL_TWIN_DELETE = "digital_twin:delete"
    DIGITAL_TWIN_EXECUTE = "digital_twin:execute"
    
    # Service permissions
    SERVICE_READ = "service:read"
    SERVICE_WRITE = "service:write"
    SERVICE_DELETE = "service:delete"
    SERVICE_EXECUTE = "service:execute"
    
    # Digital Replica permissions
    REPLICA_READ = "replica:read"
    REPLICA_WRITE = "replica:write"
    REPLICA_DELETE = "replica:delete"
    REPLICA_MANAGE = "replica:manage"
    
    # Workflow permissions
    WORKFLOW_READ = "workflow:read"
    WORKFLOW_WRITE = "workflow:write"
    WORKFLOW_DELETE = "workflow:delete"
    WORKFLOW_EXECUTE = "workflow:execute"
    
    # Administrative permissions
    ADMIN_ALL = "admin:*"
    USER_MANAGE = "user:manage"
    API_KEY_MANAGE = "api_key:manage"
    
    # System permissions
    SYSTEM_MONITOR = "system:monitor"
    SYSTEM_CONFIG = "system:config"


# Convenience dependency combiners
require_digital_twin_read = require_permission(Permissions.DIGITAL_TWIN_READ)
require_digital_twin_write = require_permission(Permissions.DIGITAL_TWIN_WRITE)
require_service_execute = require_permission(Permissions.SERVICE_EXECUTE)
require_replica_manage = require_permission(Permissions.REPLICA_MANAGE)
require_workflow_execute = require_permission(Permissions.WORKFLOW_EXECUTE)
require_admin = require_permission(Permissions.ADMIN_ALL)


# Example usage demo
async def demo_authentication():
    """Demonstrate authentication system capabilities."""
    print("🔐 Digital Twin Platform - Authentication System Demo")
    print("=" * 60)
    
    # Initialize authentication
    auth_manager = await initialize_authentication()
    
    print(f"✅ Authentication Manager initialized")
    print(f"📊 Status: {auth_manager.get_auth_status()}")
    
    # Mock authentication examples
    print(f"\n🧪 Testing mock authentication...")
    
    try:
        # Test JWT mock authentication
        jwt_context = await auth_manager.authenticate_credentials(
            {"username": "admin_user"},
            AuthMethod.JWT_TOKEN
        )
        print(f"✅ JWT Auth: {jwt_context.subject_type.value} with {len(jwt_context.permissions)} permissions")
        
        # Test API key mock authentication
        api_context = await auth_manager.authenticate_credentials(
            {"api_key": "test-key"},
            AuthMethod.API_KEY
        )
        print(f"✅ API Key Auth: {api_context.subject_type.value} with {len(api_context.permissions)} permissions")
        
        # Test permission checking
        can_read_dt = jwt_context.has_permission(Permissions.DIGITAL_TWIN_READ)
        can_write_dt = api_context.has_permission(Permissions.DIGITAL_TWIN_WRITE)
        
        print(f"🔍 Permission checks:")
        print(f"   • JWT user can read DT: {can_read_dt}")
        print(f"   • API key can write DT: {can_write_dt}")
        
        print(f"\n✅ Authentication system ready for integration!")
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")


if __name__ == "__main__":
    asyncio.run(demo_authentication())