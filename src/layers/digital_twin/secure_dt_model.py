
from typing import Set, Dict, List, Optional, Any
from uuid import UUID
from datetime import datetime, timezone
from enum import Enum
from src.core.interfaces.base import BaseMetadata
from src.layers.digital_twin import StandardDigitalTwin
from src.core.interfaces.digital_twin import DigitalTwinConfiguration, TwinModel
from src.layers.application.auth.user_registration import DigitalTwinIdentity
class DTAccessLevel(Enum):
    NONE = "none"
    READ = "read" 
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"

class SecureDigitalTwin(StandardDigitalTwin):
    """Security-enhanced Digital Twin with ownership and access controls"""
    
    def __init__(self, twin_id: UUID, configuration: DigitalTwinConfiguration, 
                 metadata: BaseMetadata, owner_id: UUID, tenant_id: UUID,
                 models: Optional[List[TwinModel]] = None):
        super().__init__(twin_id, configuration, metadata, models)
        
        # Security fields
        self.owner_id = owner_id
        self.tenant_id = tenant_id
        self.authorized_users: Dict[UUID, DTAccessLevel] = {owner_id: DTAccessLevel.ADMIN}
        self.access_permissions: Dict[UUID, Set[str]] = {
            owner_id: {"read", "write", "execute", "admin", "manage_access"}
        }
        
        # Access tracking
        self.created_by = owner_id
        self.last_accessed_by: Optional[UUID] = None
        self.access_log: List[Dict[str, Any]] = []
        self.is_public = False
        self.shared_with_tenant = True
        
        # Digital Twin Identity (for device communication)
        self.dt_identity: Optional[DigitalTwinIdentity] = None
        
    async def initialize(self) -> None:
        """Enhanced initialization with identity creation"""
        await super().initialize()
        
        # Create Digital Twin identity for secure device communication
        from src.layers.application.auth.user_registration import DigitalTwinIdentityService
        identity_service = DigitalTwinIdentityService()
        self.dt_identity = await identity_service.create_identity(
            twin_id=self._id,
            owner_id=self.owner_id, 
            tenant_id=self.tenant_id
        )
        
    def check_access(self, user_id: UUID, required_access: DTAccessLevel) -> bool:
        """Check if user has required access level"""
        if user_id == self.owner_id:
            return True
            
        user_access = self.authorized_users.get(user_id, DTAccessLevel.NONE)
        
        # Access hierarchy: ADMIN > EXECUTE > WRITE > READ > NONE
        access_hierarchy = {
            DTAccessLevel.ADMIN: 4,
            DTAccessLevel.EXECUTE: 3, 
            DTAccessLevel.WRITE: 2,
            DTAccessLevel.READ: 1,
            DTAccessLevel.NONE: 0
        }
        
        return access_hierarchy[user_access] >= access_hierarchy[required_access]
    
    def grant_access(self, user_id: UUID, access_level: DTAccessLevel, 
                    granted_by: UUID) -> None:
        """Grant access to user (only owner or admin can grant)"""
        if not (granted_by == self.owner_id or 
                self.authorized_users.get(granted_by) == DTAccessLevel.ADMIN):
            raise PermissionError("Only owner or admin can grant access")
            
        self.authorized_users[user_id] = access_level
        
        # Set permissions based on access level
        permissions = set()
        if access_level in [DTAccessLevel.READ, DTAccessLevel.WRITE, 
                           DTAccessLevel.EXECUTE, DTAccessLevel.ADMIN]:
            permissions.add("read")
        if access_level in [DTAccessLevel.WRITE, DTAccessLevel.EXECUTE, DTAccessLevel.ADMIN]:
            permissions.add("write") 
        if access_level in [DTAccessLevel.EXECUTE, DTAccessLevel.ADMIN]:
            permissions.add("execute")
        if access_level == DTAccessLevel.ADMIN:
            permissions.update({"admin", "manage_access"})
            
        self.access_permissions[user_id] = permissions
        
        self._log_access_change("grant", user_id, access_level, granted_by)
    
    def revoke_access(self, user_id: UUID, revoked_by: UUID) -> None:
        """Revoke user access (only owner or admin)"""
        if user_id == self.owner_id:
            raise PermissionError("Cannot revoke owner access")
            
        if not (revoked_by == self.owner_id or 
                self.authorized_users.get(revoked_by) == DTAccessLevel.ADMIN):
            raise PermissionError("Only owner or admin can revoke access")
            
        self.authorized_users.pop(user_id, None)
        self.access_permissions.pop(user_id, None)
        
        self._log_access_change("revoke", user_id, DTAccessLevel.NONE, revoked_by)
    
    def log_access(self, user_id: UUID, operation: str, success: bool = True) -> None:
        """Log access attempt"""
        self.last_accessed_by = user_id
        
        log_entry = {
            "user_id": str(user_id),
            "operation": operation, 
            "success": success,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_access_level": self.authorized_users.get(user_id, DTAccessLevel.NONE).value
        }
        
        self.access_log.append(log_entry)
        
        # Keep only last 100 entries
        if len(self.access_log) > 100:
            self.access_log = self.access_log[-100:]
    
    def _log_access_change(self, action: str, target_user: UUID, 
                          access_level: DTAccessLevel, changed_by: UUID) -> None:
        """Log access permission changes"""
        log_entry = {
            "action": action,
            "target_user": str(target_user),
            "access_level": access_level.value,
            "changed_by": str(changed_by),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self.access_log.append(log_entry)
        
    def get_tenant_isolation_key(self) -> str:
        """Get key for tenant-based storage isolation"""
        return f"tenant_{self.tenant_id}_twin_{self._id}"
    
    def is_accessible_by_tenant_user(self, user_id: UUID, user_tenant_id: UUID) -> bool:
        """Check if user from same tenant can access this twin"""
        if user_tenant_id != self.tenant_id:
            return False
            
        # Check if explicitly authorized
        if user_id in self.authorized_users:
            return True
            
        # Check tenant-wide sharing settings
        return self.shared_with_tenant
    
    def to_dict(self, include_security_details: bool = False) -> Dict[str, Any]:
        """Enhanced to_dict with security information"""
        base_dict = super().to_dict()
        
        # Always include basic security info
        base_dict.update({
            "owner_id": str(self.owner_id),
            "tenant_id": str(self.tenant_id), 
            "is_public": self.is_public,
            "shared_with_tenant": self.shared_with_tenant,
            "authorized_users_count": len(self.authorized_users),
            "last_accessed_by": str(self.last_accessed_by) if self.last_accessed_by else None
        })
        
        # Include detailed security info if requested
        if include_security_details:
            base_dict.update({
                "authorized_users": {
                    str(uid): level.value for uid, level in self.authorized_users.items()
                },
                "access_permissions": {
                    str(uid): list(perms) for uid, perms in self.access_permissions.items()
                },
                "recent_access_log": self.access_log[-10:],  # Last 10 entries
                "dt_identity": self.dt_identity.to_dict() if self.dt_identity else None
            })
            
        return base_dict