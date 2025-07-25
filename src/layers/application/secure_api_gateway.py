from typing import Dict, Any, List, Optional
from uuid import UUID
import logging
from datetime import datetime, timezone
from src.layers.application.api_gateway import APIGateway
from src.layers.application.auth import AuthContext, AuthSubjectType
from src.layers.digital_twin.secure_dt_model import SecureDigitalTwin, DTAccessLevel
from src.layers.digital_twin.secure_dt_factory import SecureDigitalTwinFactory
from src.utils.exceptions import AuthorizationError, EntityNotFoundError, ValidationError
from src.core.interfaces.digital_twin import DigitalTwinType, TwinCapability
from src.layers.digital_twin import DigitalTwinLayerOrchestrator
from src.utils.type_converter import TypeConverter
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SecureAPIGateway(APIGateway):
    """Security-enhanced API Gateway with ownership and tenant controls"""
    
    def __init__(self):
        super().__init__()
        self.secure_dt_factory = None
    
    async def initialize(self) -> None:
        """Enhanced initialization with security components"""
        await super().initialize()
        self.secure_dt_factory = SecureDigitalTwinFactory()
        logger.info('Secure API Gateway initialized')
    
    async def create_digital_twin_secure(self, 
                                        twin_config: Dict[str, Any], 
                                        auth_context: AuthContext,
                                        share_with_tenant: bool = True) -> Dict[str, Any]:
        """Create Digital Twin with ownership and security controls"""
        
        # Validate user authentication
        if auth_context.subject_type != AuthSubjectType.USER:
            raise AuthorizationError("Only authenticated users can create Digital Twins")
        
        owner_id = auth_context.subject_id
        tenant_id = UUID(auth_context.metadata.get('tenant_id'))
        
        if not tenant_id:
            raise ValidationError("User must belong to a tenant to create Digital Twins")
        
        try:
            # Convert config to proper types
            converted_config = TypeConverter.convert_digital_twin_config(twin_config)
            twin_type = converted_config['twin_type']
            capabilities = converted_config['capabilities']
            
            # Create configuration
            from src.core.interfaces.digital_twin import DigitalTwinConfiguration
            dt_config = DigitalTwinConfiguration(
                twin_type=twin_type,
                name=twin_config['name'],
                description=twin_config.get('description', ''),
                capabilities=capabilities,
                model_configurations=twin_config.get('model_configurations', {}),
                data_sources=twin_config.get('data_sources', []),
                update_frequency=twin_config.get('update_frequency', 60),
                retention_policy=twin_config.get('retention_policy', {}),
                quality_requirements=twin_config.get('quality_requirements', {}),
                custom_config=twin_config.get('custom_config', {})
            )
            
            # Parse initial authorized users if provided
            initial_users = {}
            if 'authorized_users' in twin_config:
                for user_data in twin_config['authorized_users']:
                    user_id = UUID(user_data['user_id'])
                    access_level = DTAccessLevel(user_data['access_level'])
                    initial_users[user_id] = access_level
            
            # Create secure twin
            if twin_config.get('template_id'):
                twin = await self.secure_dt_factory.create_from_template_secure(
                    template_name=twin_config['template_id'],
                    owner_id=owner_id,
                    tenant_id=tenant_id,
                    customization=twin_config.get('customization'),
                    authorized_users=initial_users
                )
            else:
                twin = await self.secure_dt_factory.create_shared_twin(
                    twin_type=twin_type,
                    config=dt_config,
                    owner_id=owner_id,
                    tenant_id=tenant_id,
                    share_with_tenant=share_with_tenant,
                    authorized_users=initial_users
                )
            
            # Register with orchestrator
            await self._setup_twin_storage(twin.id)
            associations = []
            await self.dt_orchestrator.registry.register_digital_twin_enhanced(
                twin, associations, twin_config.get('parent_twin_id')
            )
            
            # Setup integrations
            await self._setup_twin_integrations(twin)
            
            # Cache and activate
            if self._registry_cache:
                await self._registry_cache.cache_entity(twin.id, twin.to_dict(), 'DigitalTwin')
            
            self.dt_orchestrator.active_twins[twin.id] = twin
            await twin.initialize()
            await twin.start()
            
            # Log creation
            twin.log_access(owner_id, "create", True)
            
            logger.info(f'Created secure Digital Twin {twin.id} for user {owner_id} in tenant {tenant_id}')
            return twin.to_dict()
            
        except Exception as e:
            logger.error(f'Failed to create secure Digital Twin: {e}')
            raise EntityCreationError(f'Secure Digital Twin creation failed: {e}')
    
    async def get_digital_twin_secure(self, 
                                     twin_id: UUID, 
                                     auth_context: AuthContext,
                                     include_security_details: bool = False) -> Dict[str, Any]:
        """Get Digital Twin with ownership verification"""
        
        # Get twin from registry
        twin = await self.dt_orchestrator.registry.get_digital_twin(twin_id)
        
        # Check if this is a secure twin
        if not isinstance(twin, SecureDigitalTwin):
            # Handle legacy twins - convert or restrict access
            return await self._handle_legacy_twin_access(twin, auth_context)
        
        # Verify access
        user_id = auth_context.subject_id
        user_tenant_id = UUID(auth_context.metadata.get('tenant_id', ''))
        
        # Check tenant isolation
        if not twin.is_accessible_by_tenant_user(user_id, user_tenant_id):
            raise AuthorizationError(f"Digital Twin {twin_id} not accessible from tenant {user_tenant_id}")
        
        # Check user access level
        if not twin.check_access(user_id, DTAccessLevel.READ):
            raise AuthorizationError(f"User {user_id} does not have read access to Digital Twin {twin_id}")
        
        # Log access
        twin.log_access(user_id, "read", True)
        
        # Return twin data (security details only for admins/owners)
        include_details = include_security_details and twin.check_access(user_id, DTAccessLevel.ADMIN)
        return twin.to_dict(include_security_details=include_details)
    
    async def execute_twin_capability_secure(self, 
                                           twin_id: UUID, 
                                           capability: str, 
                                           input_data: Dict[str, Any], 
                                           auth_context: AuthContext,
                                           execution_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute capability with access control"""
        
        # Get and verify twin access
        twin = await self.dt_orchestrator.registry.get_digital_twin(twin_id)
        
        if isinstance(twin, SecureDigitalTwin):
            user_id = auth_context.subject_id
            user_tenant_id = UUID(auth_context.metadata.get('tenant_id', ''))
            
            # Check tenant and user access
            if not twin.is_accessible_by_tenant_user(user_id, user_tenant_id):
                raise AuthorizationError("Twin not accessible from your tenant")
            
            # Check execution permission
            if not twin.check_access(user_id, DTAccessLevel.EXECUTE):
                raise AuthorizationError("User does not have execute permission")
            
            # Log execution attempt
            twin.log_access(user_id, f"execute_{capability}", True)
        
        # Execute capability through parent method
        try:
            capability_enum = TwinCapability(capability)
            result = await self.dt_orchestrator.execute_twin_capability(
                twin_id=twin_id,
                capability=capability_enum,
                input_data=input_data,
                execution_config=execution_config
            )
            
            return {
                'twin_id': str(twin_id),
                'capability': capability,
                'result': result,
                'executed_at': datetime.now(timezone.utc).isoformat(),
                'executed_by': str(auth_context.subject_id)
            }
        except Exception as e:
            # Log failed execution
            if isinstance(twin, SecureDigitalTwin):
                twin.log_access(auth_context.subject_id, f"execute_{capability}", False)
            raise
    
    async def discover_twins_secure(self, 
                                  auth_context: AuthContext, 
                                  criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Discover twins with tenant isolation and access filtering"""
        
        user_id = auth_context.subject_id
        user_tenant_id = UUID(auth_context.metadata.get('tenant_id', ''))
        
        # Add tenant filter to criteria
        criteria['tenant_id'] = str(user_tenant_id)
        
        # Get all twins matching criteria
        all_twins = await self.dt_orchestrator.registry.discover_twins_advanced(criteria)
        
        # Filter by access permissions
        accessible_twins = []
        for twin in all_twins:
            if isinstance(twin, SecureDigitalTwin):
                if twin.is_accessible_by_tenant_user(user_id, user_tenant_id) and \
                   twin.check_access(user_id, DTAccessLevel.READ):
                    accessible_twins.append(twin.to_dict())
            else:
                # Handle legacy twins
                accessible_twins.append(twin.to_dict())
        
        return accessible_twins
    
    async def manage_twin_access(self, 
                                twin_id: UUID, 
                                target_user_id: UUID,
                                access_level: str,
                                action: str,  # 'grant' or 'revoke'
                                auth_context: AuthContext) -> Dict[str, Any]:
        """Manage access permissions for a Digital Twin"""
        
        # Get twin and verify admin access
        twin = await self.dt_orchestrator.registry.get_digital_twin(twin_id)
        
        if not isinstance(twin, SecureDigitalTwin):
            raise ValidationError("Access management only available for secure twins")
        
        user_id = auth_context.subject_id
        
        # Check if user can manage access
        if not twin.check_access(user_id, DTAccessLevel.ADMIN):
            raise AuthorizationError("Admin access required to manage permissions")
        
        # Perform action
        try:
            if action == 'grant':
                access_level_enum = DTAccessLevel(access_level)
                twin.grant_access(target_user_id, access_level_enum, user_id)
                message = f"Granted {access_level} access to user {target_user_id}"
            elif action == 'revoke':
                twin.revoke_access(target_user_id, user_id)
                message = f"Revoked access for user {target_user_id}"
            else:
                raise ValidationError("Action must be 'grant' or 'revoke'")
            
            # Update in registry/cache
            if self._registry_cache:
                await self._registry_cache.invalidate_entity(twin_id, 'DigitalTwin')
            
            return {
                'twin_id': str(twin_id),
                'action': action,
                'target_user': str(target_user_id),
                'access_level': access_level if action == 'grant' else None,
                'message': message,
                'performed_by': str(user_id),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f'Failed to {action} access for user {target_user_id} on twin {twin_id}: {e}')
            raise ValidationError(f'Access management failed: {e}')
    
    async def _handle_legacy_twin_access(self, twin, auth_context: AuthContext) -> Dict[str, Any]:
        """Handle access to non-secure legacy twins"""
        
        # For legacy twins, apply basic tenant filtering if possible
        # This is a migration strategy
        
        logger.warning(f'Accessing legacy twin {twin.id} - consider upgrading to secure model')
        
        # Basic access - could be restricted based on policy
        return twin.to_dict()
    
    async def get_user_twins(self, auth_context: AuthContext) -> Dict[str, Any]:
        """Get all twins accessible to the user"""
        
        user_id = auth_context.subject_id
        user_tenant_id = UUID(auth_context.metadata.get('tenant_id', ''))
        
        # Get all twins for the tenant
        criteria = {'tenant_id': str(user_tenant_id)}
        all_twins = await self.discover_twins_secure(auth_context, criteria)
        
        # Categorize by access level
        owned_twins = []
        admin_twins = []
        write_twins = []
        read_twins = []
        
        for twin_data in all_twins:
            twin_id = UUID(twin_data['id'])
            twin = await self.dt_orchestrator.registry.get_digital_twin(twin_id)
            
            if isinstance(twin, SecureDigitalTwin):
                if twin.owner_id == user_id:
                    owned_twins.append(twin_data)
                elif twin.check_access(user_id, DTAccessLevel.ADMIN):
                    admin_twins.append(twin_data)
                elif twin.check_access(user_id, DTAccessLevel.WRITE):
                    write_twins.append(twin_data)
                else:
                    read_twins.append(twin_data)
            else:
                # Legacy twin - assume read access
                read_twins.append(twin_data)
        
        return {
            'user_id': str(user_id),
            'tenant_id': str(user_tenant_id),
            'twins': {
                'owned': owned_twins,
                'admin_access': admin_twins,
                'write_access': write_twins,
                'read_access': read_twins
            },
            'summary': {
                'total_accessible': len(all_twins),
                'owned_count': len(owned_twins),
                'admin_count': len(admin_twins),
                'write_count': len(write_twins),
                'read_count': len(read_twins)
            }
        }