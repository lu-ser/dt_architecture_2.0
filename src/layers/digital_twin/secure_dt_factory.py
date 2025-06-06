from typing import Optional, Dict, Any, Set, List
from datetime import datetime, timezone
from uuid import uuid4
import logging
from uuid import UUID
from src.layers.digital_twin.dt_factory import DigitalTwinFactory
from src.layers.digital_twin.secure_dt_model import SecureDigitalTwin, DTAccessLevel
from src.core.interfaces.digital_twin import DigitalTwinType, DigitalTwinConfiguration, TwinCapability, TwinModel
from src.core.interfaces.base import BaseMetadata
from src.utils.exceptions import EntityCreationError, AuthorizationError, ValidationError
from src.layers.application.auth.user_registration import Tenant
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SecureDigitalTwinFactory(DigitalTwinFactory):
    """Enhanced factory with security and tenant awareness"""
    
    async def create_secure_twin(self, 
                                twin_type: DigitalTwinType,
                                config: DigitalTwinConfiguration, 
                                owner_id: UUID,
                                tenant_id: UUID,
                                models: Optional[List[TwinModel]] = None,
                                metadata: Optional[BaseMetadata] = None,
                                initial_authorized_users: Optional[Dict[UUID, DTAccessLevel]] = None) -> SecureDigitalTwin:
        """Create a security-enhanced Digital Twin"""
        
        try:
            # Validate inputs
            if not self.validate_twin_config(twin_type, config):
                raise ValidationError('Invalid Digital Twin configuration')
            
            # Check tenant limits
            await self._check_tenant_limits(tenant_id)
            
            if metadata is None:
                metadata = BaseMetadata(
                    entity_id=uuid4(),
                    timestamp=datetime.now(timezone.utc),
                    version='1.0.0',
                    created_by=owner_id,
                    custom={'tenant_id': str(tenant_id), 'security_enabled': True}
                )
            
            # Create secure twin
            twin = SecureDigitalTwin(
                twin_id=metadata.id,
                configuration=config,
                metadata=metadata,
                owner_id=owner_id,
                tenant_id=tenant_id,
                models=models
            )
            
            # Add initial authorized users if provided
            if initial_authorized_users:
                for user_id, access_level in initial_authorized_users.items():
                    twin.grant_access(user_id, access_level, owner_id)
            
            logger.info(f'Created secure Digital Twin {twin.id} for owner {owner_id} in tenant {tenant_id}')
            return twin
            
        except Exception as e:
            logger.error(f'Failed to create secure Digital Twin: {e}')
            raise EntityCreationError(f'Secure Digital Twin creation failed: {e}')
    
    async def create_from_template_secure(self,
                                         template_name: str,
                                         owner_id: UUID, 
                                         tenant_id: UUID,
                                         customization: Optional[Dict[str, Any]] = None,
                                         metadata: Optional[BaseMetadata] = None,
                                         authorized_users: Optional[Dict[UUID, DTAccessLevel]] = None) -> SecureDigitalTwin:
        """Create secure twin from template with ownership"""
        
        # Get template and apply customization
        template = self._get_twin_template(template_name)
        if not template:
            raise ValidationError(f'Template {template_name} not found')
        
        if customization:
            template = self._apply_template_customization(template, customization)
        
        # Create configuration
        twin_type = DigitalTwinType(template['twin_type'])
        config = DigitalTwinConfiguration(
            twin_type=twin_type,
            name=template['name'],
            description=template['description'],
            capabilities=set(TwinCapability(cap) for cap in template['capabilities']),
            model_configurations=template.get('model_configurations', {}),
            data_sources=template.get('data_sources', []),
            update_frequency=template.get('update_frequency', 60),
            retention_policy=template.get('retention_policy', {}),
            quality_requirements=template.get('quality_requirements', {}),
            custom_config=template.get('custom_config', {})
        )
        
        # Add template models
        models = []
        for model_template_id in template.get('model_templates', []):
            if model_template_id in self._model_templates:
                models.append(self._model_templates[model_template_id])
        
        return await self.create_secure_twin(
            twin_type=twin_type,
            config=config,
            owner_id=owner_id,
            tenant_id=tenant_id,
            models=models,
            metadata=metadata,
            initial_authorized_users=authorized_users
        )
    
    async def create_shared_twin(self,
                                twin_type: DigitalTwinType,
                                config: DigitalTwinConfiguration,
                                owner_id: UUID,
                                tenant_id: UUID,
                                share_with_tenant: bool = True,
                                authorized_users: Optional[Dict[UUID, DTAccessLevel]] = None) -> SecureDigitalTwin:
        """Create a twin with specific sharing settings"""
        
        twin = await self.create_secure_twin(
            twin_type=twin_type,
            config=config,
            owner_id=owner_id,
            tenant_id=tenant_id,
            initial_authorized_users=authorized_users
        )
        
        twin.shared_with_tenant = share_with_tenant
        
        # If sharing with tenant, add default access for tenant users
        if share_with_tenant:
            twin.access_permissions[tenant_id] = {"read"}  # Default tenant access
        
        return twin
    
    async def clone_twin_for_user(self,
                                 source_twin_id: UUID,
                                 new_owner_id: UUID,
                                 new_tenant_id: UUID,
                                 requesting_user_id: UUID) -> SecureDigitalTwin:
        """Clone an existing twin for a new user/tenant"""
        
        # This would need registry access to get the source twin
        # For now, this is a placeholder showing the concept
        
        # 1. Check if requesting user has access to source twin
        # 2. Get source twin configuration
        # 3. Create new twin with same config but new ownership
        # 4. Copy models and data (if permissions allow)
        
        raise NotImplementedError("Twin cloning requires registry integration")
    
    async def _check_tenant_limits(self, tenant_id: UUID) -> None:
        """Check if tenant can create more twins"""
        
        # This would integrate with the registration service
        # to check tenant limits
        from src.layers.application.auth.user_registration import UserRegistrationService
        
        # For now, assume we have access to tenant info
        # In practice, this would be injected or retrieved from registry
        
        # Example limit check:
        # tenant = await registration_service.get_tenant_info(tenant_id)
        # current_count = await twin_registry.count_tenant_twins(tenant_id)
        # if not tenant.can_create_digital_twin(current_count):
        #     raise ValidationError(f"Tenant has reached maximum Digital Twin limit")
        
        pass  # Placeholder for now
    
    def get_supported_security_features(self) -> Dict[str, bool]:
        """Return supported security features"""
        return {
            "tenant_isolation": True,
            "user_access_control": True,
            "digital_twin_identity": True,
            "access_logging": True,
            "sharing_controls": True,
            "ownership_transfer": False,  # Not implemented yet
            "twin_cloning": False         # Not implemented yet
        }