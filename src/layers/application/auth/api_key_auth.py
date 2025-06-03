"""
API Key Authentication Provider for the Digital Twin Platform.

This module handles API key-based authentication for external applications,
including key generation, validation, rate limiting, and usage tracking.

LOCATION: src/layers/application/auth/api_key_auth.py
"""

import asyncio
import hashlib
import logging
import secrets
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

from . import AuthContext, AuthSubject, AuthSubjectType, AuthMethod
from src.utils.exceptions import (
    AuthenticationError,
    ValidationError,
    RateLimitError
)
from src.utils.config import get_config

logger = logging.getLogger(__name__)


class ApplicationType:
    """Application types with different permission levels."""
    
    INTERNAL = "internal"           # Internal company applications
    PARTNER = "partner"             # Partner applications
    EXTERNAL = "external"           # External third-party applications
    TESTING = "testing"             # Testing and development
    
    # Type-based permission mappings
    TYPE_PERMISSIONS = {
        INTERNAL: [
            "digital_twin:read", "digital_twin:write", "digital_twin:execute",
            "service:read", "service:write", "service:execute",
            "replica:read", "replica:write", "replica:manage",
            "workflow:read", "workflow:write", "workflow:execute",
            "system:monitor"
        ],
        PARTNER: [
            "digital_twin:read", "digital_twin:execute",
            "service:read", "service:execute",
            "replica:read",
            "workflow:read", "workflow:execute"
        ],
        EXTERNAL: [
            "digital_twin:read",
            "service:read",
            "replica:read",
            "workflow:read"
        ],
        TESTING: [
            "digital_twin:read", "digital_twin:write",
            "service:read", "service:execute",
            "replica:read"
        ]
    }
    
    @classmethod
    def get_permissions(cls, app_type: str) -> List[str]:
        """Get permissions for a specific application type."""
        return cls.TYPE_PERMISSIONS.get(app_type, cls.TYPE_PERMISSIONS[cls.EXTERNAL])
    
    @classmethod
    def is_valid_type(cls, app_type: str) -> bool:
        """Check if an application type is valid."""
        return app_type in cls.TYPE_PERMISSIONS


class RateLimit:
    """Rate limiting configuration for API keys."""
    
    def __init__(
        self,
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000,
        requests_per_day: int = 10000,
        burst_limit: int = 10
    ):
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        self.requests_per_day = requests_per_day
        self.burst_limit = burst_limit
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert rate limit to dictionary representation."""
        return {
            "requests_per_minute": self.requests_per_minute,
            "requests_per_hour": self.requests_per_hour,
            "requests_per_day": self.requests_per_day,
            "burst_limit": self.burst_limit
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RateLimit':
        """Create rate limit from dictionary representation."""
        return cls(
            requests_per_minute=data.get("requests_per_minute", 60),
            requests_per_hour=data.get("requests_per_hour", 1000),
            requests_per_day=data.get("requests_per_day", 10000),
            burst_limit=data.get("burst_limit", 10)
        )


class APIKeyUsage:
    """API key usage tracking."""
    
    def __init__(self, api_key_id: UUID):
        self.api_key_id = api_key_id
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.last_used = None
        self.first_used = None
        
        # Time-based request tracking
        self.requests_by_minute: Dict[int, int] = {}  # minute_timestamp -> count
        self.requests_by_hour: Dict[int, int] = {}    # hour_timestamp -> count
        self.requests_by_day: Dict[int, int] = {}     # day_timestamp -> count
        
        # Recent request tracking for burst limiting
        self.recent_requests: List[float] = []  # timestamps of recent requests
    
    def record_request(self, success: bool = True) -> None:
        """Record an API request."""
        now = datetime.now(timezone.utc)
        timestamp = now.timestamp()
        
        # Update counters
        self.total_requests += 1
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
        
        # Update timestamps
        self.last_used = now
        if not self.first_used:
            self.first_used = now
        
        # Update time-based tracking
        minute_key = int(timestamp // 60)
        hour_key = int(timestamp // 3600)
        day_key = int(timestamp // 86400)
        
        self.requests_by_minute[minute_key] = self.requests_by_minute.get(minute_key, 0) + 1
        self.requests_by_hour[hour_key] = self.requests_by_hour.get(hour_key, 0) + 1
        self.requests_by_day[day_key] = self.requests_by_day.get(day_key, 0) + 1
        
        # Track for burst limiting
        self.recent_requests.append(timestamp)
        
        # Clean up old tracking data
        self._cleanup_old_data(timestamp)
    
    def check_rate_limit(self, rate_limit: RateLimit) -> Tuple[bool, str]:
        """
        Check if request would exceed rate limits.
        
        Returns:
            (allowed, reason) tuple
        """
        now = time.time()
        
        # Check burst limit (last 60 seconds)
        recent_cutoff = now - 60
        recent_count = len([req for req in self.recent_requests if req > recent_cutoff])
        if recent_count >= rate_limit.burst_limit:
            return False, f"Burst limit exceeded ({recent_count}/{rate_limit.burst_limit} in last minute)"
        
        # Check per-minute limit
        minute_key = int(now // 60)
        minute_count = self.requests_by_minute.get(minute_key, 0)
        if minute_count >= rate_limit.requests_per_minute:
            return False, f"Per-minute limit exceeded ({minute_count}/{rate_limit.requests_per_minute})"
        
        # Check per-hour limit
        hour_key = int(now // 3600)
        hour_count = self.requests_by_hour.get(hour_key, 0)
        if hour_count >= rate_limit.requests_per_hour:
            return False, f"Per-hour limit exceeded ({hour_count}/{rate_limit.requests_per_hour})"
        
        # Check per-day limit
        day_key = int(now // 86400)
        day_count = self.requests_by_day.get(day_key, 0)
        if day_count >= rate_limit.requests_per_day:
            return False, f"Per-day limit exceeded ({day_count}/{rate_limit.requests_per_day})"
        
        return True, "OK"
    
    def get_current_usage(self) -> Dict[str, Any]:
        """Get current usage statistics."""
        now = time.time()
        minute_key = int(now // 60)
        hour_key = int(now // 3600)
        day_key = int(now // 86400)
        
        # Count recent requests for burst tracking
        recent_cutoff = now - 60
        recent_count = len([req for req in self.recent_requests if req > recent_cutoff])
        
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": self.successful_requests / max(self.total_requests, 1),
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "first_used": self.first_used.isoformat() if self.first_used else None,
            "current_usage": {
                "this_minute": self.requests_by_minute.get(minute_key, 0),
                "this_hour": self.requests_by_hour.get(hour_key, 0),
                "this_day": self.requests_by_day.get(day_key, 0),
                "recent_burst": recent_count
            }
        }
    
    def _cleanup_old_data(self, current_timestamp: float) -> None:
        """Clean up old tracking data to prevent memory leaks."""
        current_minute = int(current_timestamp // 60)
        current_hour = int(current_timestamp // 3600)
        current_day = int(current_timestamp // 86400)
        
        # Keep last 5 minutes
        self.requests_by_minute = {
            k: v for k, v in self.requests_by_minute.items()
            if k >= current_minute - 5
        }
        
        # Keep last 25 hours
        self.requests_by_hour = {
            k: v for k, v in self.requests_by_hour.items()
            if k >= current_hour - 25
        }
        
        # Keep last 8 days
        self.requests_by_day = {
            k: v for k, v in self.requests_by_day.items()
            if k >= current_day - 8
        }
        
        # Keep only last 2 minutes of recent requests
        cutoff = current_timestamp - 120
        self.recent_requests = [req for req in self.recent_requests if req > cutoff]


class APIKey:
    """API Key entity for external application authentication."""
    
    def __init__(
        self,
        key_id: UUID,
        application_id: UUID,
        name: str,
        key_hash: str,
        permissions: List[str],
        rate_limit: RateLimit,
        is_active: bool = True,
        expires_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None
    ):
        self.key_id = key_id
        self.application_id = application_id
        self.name = name
        self.key_hash = key_hash
        self.permissions = permissions
        self.rate_limit = rate_limit
        self.is_active = is_active
        self.expires_at = expires_at
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.now(timezone.utc)
        
        # Usage tracking
        self.usage = APIKeyUsage(key_id)
    
    def is_expired(self) -> bool:
        """Check if API key is expired."""
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) > self.expires_at
    
    def is_valid(self) -> bool:
        """Check if API key is valid (active and not expired)."""
        return self.is_active and not self.is_expired()
    
    def check_rate_limit(self) -> Tuple[bool, str]:
        """Check if request would exceed rate limits."""
        return self.usage.check_rate_limit(self.rate_limit)
    
    def record_request(self, success: bool = True) -> None:
        """Record an API request."""
        self.usage.record_request(success)
    
    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        """Convert API key to dictionary representation."""
        key_dict = {
            "key_id": str(self.key_id),
            "application_id": str(self.application_id),
            "name": self.name,
            "permissions": self.permissions,
            "rate_limit": self.rate_limit.to_dict(),
            "is_active": self.is_active,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "usage": self.usage.get_current_usage()
        }
        
        if include_sensitive:
            key_dict["key_hash"] = self.key_hash
        
        return key_dict


class Application:
    """Application entity for external systems."""
    
    def __init__(
        self,
        application_id: UUID,
        name: str,
        application_type: str,
        description: str,
        contact_email: str,
        permissions: List[str],
        default_rate_limit: RateLimit,
        is_active: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None
    ):
        self.application_id = application_id
        self.name = name
        self.application_type = application_type
        self.description = description
        self.contact_email = contact_email
        self.permissions = permissions
        self.default_rate_limit = default_rate_limit
        self.is_active = is_active
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.now(timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert application to dictionary representation."""
        return {
            "application_id": str(self.application_id),
            "name": self.name,
            "application_type": self.application_type,
            "description": self.description,
            "contact_email": self.contact_email,
            "permissions": self.permissions,
            "default_rate_limit": self.default_rate_limit.to_dict(),
            "is_active": self.is_active,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat()
        }


class APIKeyProvider:
    """
    API Key Authentication Provider for the Digital Twin Platform.
    
    Handles API key generation, validation, rate limiting, and usage tracking
    for external applications accessing the platform.
    """
    
    def __init__(self):
        self.config = get_config()
        
        # In-memory storage for development (replace with database in production)
        self.applications: Dict[UUID, Application] = {}
        self.api_keys: Dict[str, APIKey] = {}  # key_hash -> APIKey
        self.keys_by_app: Dict[UUID, List[UUID]] = {}  # app_id -> list of key_ids
        
        # Rate limiting tracking
        self.rate_limit_violations: Dict[str, List[datetime]] = {}
        
        # Default rate limits by application type
        self.default_rate_limits = {
            ApplicationType.INTERNAL: RateLimit(120, 5000, 50000, 20),
            ApplicationType.PARTNER: RateLimit(60, 2000, 20000, 15),
            ApplicationType.EXTERNAL: RateLimit(30, 1000, 10000, 10),
            ApplicationType.TESTING: RateLimit(10, 100, 1000, 5)
        }
        
        self._initialized = False
        
        logger.info("API Key Provider initialized")
    
    async def initialize(self) -> None:
        """Initialize API Key provider with default applications."""
        if self._initialized:
            return
        
        try:
            # Create default applications for development
            await self._create_default_applications()
            
            self._initialized = True
            logger.info(f"API Key Provider initialized with {len(self.applications)} applications")
            
        except Exception as e:
            logger.error(f"Failed to initialize API Key Provider: {e}")
            raise AuthenticationError(f"API Key Provider initialization failed: {e}")
    
    async def authenticate(self, credentials: Dict[str, Any]) -> AuthContext:
        """
        Authenticate using API key credentials.
        
        Args:
            credentials: Dictionary with 'api_key'
            
        Returns:
            AuthContext for the authenticated application
        """
        api_key = credentials.get("api_key")
        if not api_key:
            raise AuthenticationError("API key required")
        
        return await self.validate_api_key(api_key)
    
    async def validate_api_key(self, api_key: str) -> AuthContext:
        """
        Validate API key and return auth context.
        
        Args:
            api_key: API key string
            
        Returns:
            AuthContext for the API key
        """
        # Hash the API key
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        # Find API key
        api_key_entity = self.api_keys.get(key_hash)
        if not api_key_entity:
            logger.warning(f"Invalid API key attempted")
            raise AuthenticationError("Invalid API key")
        
        # Check if key is valid
        if not api_key_entity.is_valid():
            logger.warning(f"Expired or inactive API key used: {api_key_entity.name}")
            raise AuthenticationError("API key is expired or inactive")
        
        # Check rate limits
        allowed, reason = api_key_entity.check_rate_limit()
        if not allowed:
            logger.warning(f"Rate limit exceeded for API key {api_key_entity.name}: {reason}")
            
            # Track rate limit violation
            self._track_rate_limit_violation(key_hash)
            
            raise RateLimitError(f"Rate limit exceeded: {reason}")
        
        # Get application
        application = self.applications.get(api_key_entity.application_id)
        if not application or not application.is_active:
            logger.warning(f"API key belongs to inactive application: {api_key_entity.application_id}")
            raise AuthenticationError("Application is inactive")
        
        # Record successful request
        api_key_entity.record_request(success=True)
        
        # Create auth context
        context = AuthContext(
            subject_type=AuthSubjectType.APPLICATION,
            subject_id=api_key_entity.application_id,
            auth_method=AuthMethod.API_KEY,
            permissions=api_key_entity.permissions,
            metadata={
                "application_name": application.name,
                "application_type": application.application_type,
                "api_key_name": api_key_entity.name,
                "api_key_id": str(api_key_entity.key_id),
                "contact_email": application.contact_email
            },
            expires_at=api_key_entity.expires_at
        )
        
        return context
    
    async def create_application(
        self,
        name: str,
        application_type: str,
        description: str,
        contact_email: str,
        custom_permissions: Optional[List[str]] = None,
        custom_rate_limit: Optional[RateLimit] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Application:
        """Create a new application."""
        # Validate input
        if not name or not contact_email:
            raise ValidationError("Name and contact email are required")
        
        if not ApplicationType.is_valid_type(application_type):
            raise ValidationError(f"Invalid application type: {application_type}")
        
        # Check for existing application name
        for app in self.applications.values():
            if app.name.lower() == name.lower():
                raise ValidationError(f"Application name already exists: {name}")
        
        # Determine permissions
        permissions = custom_permissions or ApplicationType.get_permissions(application_type)
        
        # Determine rate limit
        rate_limit = custom_rate_limit or self.default_rate_limits.get(
            application_type, 
            self.default_rate_limits[ApplicationType.EXTERNAL]
        )
        
        # Create application
        application = Application(
            application_id=uuid4(),
            name=name,
            application_type=application_type,
            description=description,
            contact_email=contact_email,
            permissions=permissions,
            default_rate_limit=rate_limit,
            metadata=metadata or {}
        )
        
        # Store application
        self.applications[application.application_id] = application
        self.keys_by_app[application.application_id] = []
        
        logger.info(f"Application created: {name} ({application_type})")
        return application
    
    async def create_api_key(
        self,
        application_id: UUID,
        name: str,
        permissions: Optional[List[str]] = None,
        rate_limit: Optional[RateLimit] = None,
        expires_days: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, APIKey]:
        """
        Create a new API key for an application.
        
        Returns:
            Tuple of (api_key_string, api_key_entity)
        """
        # Get application
        application = self.applications.get(application_id)
        if not application:
            raise ValidationError(f"Application not found: {application_id}")
        
        # Validate permissions
        if permissions:
            # Check that requested permissions are subset of application permissions
            invalid_permissions = set(permissions) - set(application.permissions)
            if invalid_permissions:
                raise ValidationError(f"Invalid permissions for application: {invalid_permissions}")
        else:
            permissions = application.permissions.copy()
        
        # Determine rate limit
        if not rate_limit:
            rate_limit = application.default_rate_limit
        
        # Determine expiration
        expires_at = None
        if expires_days:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)
        
        # Generate API key
        api_key_string = self._generate_api_key()
        key_hash = hashlib.sha256(api_key_string.encode()).hexdigest()
        
        # Create API key entity
        api_key_entity = APIKey(
            key_id=uuid4(),
            application_id=application_id,
            name=name,
            key_hash=key_hash,
            permissions=permissions,
            rate_limit=rate_limit,
            expires_at=expires_at,
            metadata=metadata or {}
        )
        
        # Store API key
        self.api_keys[key_hash] = api_key_entity
        self.keys_by_app[application_id].append(api_key_entity.key_id)
        
        logger.info(f"API key created: {name} for application {application.name}")
        return api_key_string, api_key_entity
    
    async def revoke_api_key(self, api_key: str) -> None:
        """Revoke an API key."""
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        api_key_entity = self.api_keys.get(key_hash)
        if api_key_entity:
            api_key_entity.is_active = False
            logger.info(f"API key revoked: {api_key_entity.name}")
    
    async def revoke_all_application_keys(self, application_id: UUID) -> int:
        """Revoke all API keys for an application."""
        revoked_count = 0
        
        key_ids = self.keys_by_app.get(application_id, [])
        for key_hash, api_key in self.api_keys.items():
            if api_key.application_id == application_id and api_key.is_active:
                api_key.is_active = False
                revoked_count += 1
        
        logger.info(f"Revoked {revoked_count} API keys for application {application_id}")
        return revoked_count
    
    async def rotate_api_key(
        self,
        old_api_key: str,
        name: Optional[str] = None
    ) -> Tuple[str, APIKey]:
        """
        Rotate an API key (create new one, optionally deactivate old one).
        
        Returns:
            Tuple of (new_api_key_string, new_api_key_entity)
        """
        # Get old key
        old_key_hash = hashlib.sha256(old_api_key.encode()).hexdigest()
        old_key_entity = self.api_keys.get(old_key_hash)
        
        if not old_key_entity:
            raise ValidationError("Original API key not found")
        
        # Create new key with same settings
        new_name = name or f"{old_key_entity.name} (rotated)"
        
        new_api_key, new_key_entity = await self.create_api_key(
            application_id=old_key_entity.application_id,
            name=new_name,
            permissions=old_key_entity.permissions,
            rate_limit=old_key_entity.rate_limit,
            metadata={**old_key_entity.metadata, "rotated_from": str(old_key_entity.key_id)}
        )
        
        # Mark old key as inactive
        old_key_entity.is_active = False
        old_key_entity.metadata["rotated_to"] = str(new_key_entity.key_id)
        
        logger.info(f"API key rotated: {old_key_entity.name} -> {new_key_entity.name}")
        return new_api_key, new_key_entity
    
    async def get_application_api_keys(self, application_id: UUID) -> List[APIKey]:
        """Get all API keys for an application."""
        return [
            api_key for api_key in self.api_keys.values()
            if api_key.application_id == application_id
        ]
    
    async def get_api_key_usage(self, api_key: str) -> Dict[str, Any]:
        """Get usage statistics for an API key."""
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        api_key_entity = self.api_keys.get(key_hash)
        
        if not api_key_entity:
            raise ValidationError("API key not found")
        
        return api_key_entity.usage.get_current_usage()
    
    def get_api_key_permissions(self, api_key: str) -> List[str]:
        """Get permissions for an API key."""
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        api_key_entity = self.api_keys.get(key_hash)
        
        if api_key_entity:
            return api_key_entity.permissions
        return []
    
    async def list_applications(
        self,
        include_inactive: bool = False
    ) -> List[Dict[str, Any]]:
        """List all applications."""
        applications = []
        for app in self.applications.values():
            if include_inactive or app.is_active:
                app_dict = app.to_dict()
                # Add API key count
                app_dict["api_key_count"] = len(self.keys_by_app.get(app.application_id, []))
                applications.append(app_dict)
        return applications
    
    async def _create_default_applications(self) -> None:
        """Create default applications for development and testing."""
        default_applications = [
            {
                "name": "Internal Dashboard",
                "application_type": ApplicationType.INTERNAL,
                "description": "Internal company dashboard application",
                "contact_email": "admin@company.com",
                "metadata": {"default_app": True}
            },
            {
                "name": "Partner Integration",
                "application_type": ApplicationType.PARTNER,
                "description": "Partner system integration",
                "contact_email": "partner@external.com",
                "metadata": {"default_app": True}
            },
            {
                "name": "Mobile App",
                "application_type": ApplicationType.EXTERNAL,
                "description": "Mobile application for external users",
                "contact_email": "mobile@company.com",
                "metadata": {"default_app": True}
            },
            {
                "name": "Testing Suite",
                "application_type": ApplicationType.TESTING,
                "description": "Automated testing and development",
                "contact_email": "dev@company.com",
                "metadata": {"default_app": True}
            }
        ]
        
        for app_data in default_applications:
            try:
                app = await self.create_application(**app_data)
                
                # Create default API key for each application
                api_key, key_entity = await self.create_api_key(
                    application_id=app.application_id,
                    name=f"{app.name} Default Key",
                    expires_days=365,  # 1 year expiry
                    metadata={"default_key": True}
                )
                
                # Store the API key in metadata for easy access during development
                app.metadata["default_api_key"] = api_key
                
                logger.info(f"Created default application: {app.name} with API key")
                
            except ValidationError as e:
                logger.debug(f"Default application already exists: {app_data['name']}")
    
    def _generate_api_key(self) -> str:
        """Generate a secure API key."""
        # Format: dtp_<random_32_chars>_<timestamp>
        random_part = secrets.token_urlsafe(24)  # 32 chars when base64 encoded
        timestamp_part = hex(int(time.time()))[2:]  # Remove '0x' prefix
        
        return f"dtp_{random_part}_{timestamp_part}"
    
    def _track_rate_limit_violation(self, key_hash: str) -> None:
        """Track rate limit violations for monitoring."""
        now = datetime.now(timezone.utc)
        
        if key_hash not in self.rate_limit_violations:
            self.rate_limit_violations[key_hash] = []
        
        self.rate_limit_violations[key_hash].append(now)
        
        # Keep only last 24 hours of violations
        cutoff = now - timedelta(hours=24)
        self.rate_limit_violations[key_hash] = [
            violation for violation in self.rate_limit_violations[key_hash]
            if violation > cutoff
        ]
    
    def get_provider_status(self) -> Dict[str, Any]:
        """Get API Key provider status and statistics."""
        total_keys = len(self.api_keys)
        active_keys = len([key for key in self.api_keys.values() if key.is_valid()])
        
        # Usage statistics
        total_requests = sum(key.usage.total_requests for key in self.api_keys.values())
        total_violations = sum(len(violations) for violations in self.rate_limit_violations.values())
        
        # Application type distribution
        app_type_dist = {}
        for app in self.applications.values():
            app_type_dist[app.application_type] = app_type_dist.get(app.application_type, 0) + 1
        
        return {
            "initialized": self._initialized,
            "total_applications": len(self.applications),
            "active_applications": len([app for app in self.applications.values() if app.is_active]),
            "total_api_keys": total_keys,
            "active_api_keys": active_keys,
            "total_requests": total_requests,
            "rate_limit_violations_24h": total_violations,
            "application_types": app_type_dist,
            "default_rate_limits": {
                app_type: limit.to_dict()
                for app_type, limit in self.default_rate_limits.items()
            }
        }