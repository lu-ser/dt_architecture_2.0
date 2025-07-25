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
from src.core.interfaces.digital_twin import TwinModelType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SecureDigitalTwinFactory(DigitalTwinFactory):
    """Enhanced factory with security and tenant awareness"""
    
    async def create_from_template_secure(self,
                                 template_name: str,
                                 owner_id: UUID, 
                                 tenant_id: UUID,
                                 customization: Optional[Dict[str, Any]] = None,
                                 metadata: Optional[BaseMetadata] = None,
                                 authorized_users: Optional[Dict[UUID, DTAccessLevel]] = None) -> SecureDigitalTwin:
        """Create secure twin from template with ownership"""
                
        template = self._get_twin_template_sync(template_name)
        if not template:
            available_templates = self.get_available_templates()
            raise ValidationError(f'Template {template_name} not found. Available: {available_templates}')
                
        logger.info(f"Found template: {template_name}")
        logger.info(f"Template type: {template.get('twin_type')}")
        logger.info(f"Template capabilities: {template.get('capabilities')}")
        
        # Apply customization if provided
        if customization:
            logger.info(f"Applying customization: {list(customization.keys())}")
            template = self._apply_template_customization(template, customization)
        
        try:
            # Convert twin_type
            twin_type = DigitalTwinType(template['twin_type'])
            logger.info(f"Twin type: {twin_type}")
            
            # Convert capabilities
            capabilities = set()
            for cap in template['capabilities']:
                try:
                    capabilities.add(TwinCapability(cap))
                except ValueError as e:
                    logger.warning(f"Invalid capability {cap}: {e}")
                    
            logger.info(f"Capabilities: {capabilities}")
            
            # Process model configurations
            model_configs = {}
            raw_model_configs = template.get('model_configurations', {})

            for model_key, config in raw_model_configs.items():                
                # Map string keys to TwinModelType enums
                if model_key == "physics_based":
                    model_configs[TwinModelType.PHYSICS_BASED] = config
                elif model_key == "data_driven":
                    model_configs[TwinModelType.DATA_DRIVEN] = config
                elif model_key == "hybrid":
                    model_configs[TwinModelType.HYBRID] = config
                else:
                    # Try to match enum values directly
                    try:
                        enum_key = TwinModelType(model_key)
                        model_configs[enum_key] = config
                    except ValueError:
                        logger.warning(f"Unknown model configuration key: {model_key}, skipping")

            logger.info(f"🔍 Final model configurations: {model_configs}")
            
            # Create configuration
            config = DigitalTwinConfiguration(
                twin_type=twin_type,
                name=template['name'],
                description=template['description'],
                capabilities=capabilities,
                model_configurations=model_configs,
                data_sources=template.get('data_sources', []),
                update_frequency=template.get('update_frequency', 60),
                retention_policy=template.get('retention_policy', {}),
                quality_requirements=template.get('quality_requirements', {}),
                custom_config=template.get('custom_config', {})
            )
            
            logger.info(f"🔍 Configuration created successfully")
            
            # Add template models
            models = []
            for model_template_id in template.get('model_templates', []):
                if hasattr(self, '_model_templates') and model_template_id in self._model_templates:
                    models.append(self._model_templates[model_template_id])
            
            # Create secure twin
            result = await self.create_secure_twin(
                twin_type=twin_type,
                config=config,
                owner_id=owner_id,
                tenant_id=tenant_id,
                models=models,
                metadata=metadata,
                initial_authorized_users=authorized_users  # ✅ FIX: correct parameter name
            )
            
            logger.info(f"🔍 Secure twin created successfully: {result.id}")
            return result
            
        except Exception as e:
            logger.error(f"🚨 Error in create_from_template_secure: {e}", exc_info=True)
            raise ValidationError(f'Failed to create secure twin from template: {e}')

    def _get_twin_template(self, template_name: str) -> Optional[Dict[str, Any]]:
        """Get a Digital Twin template by name."""
        templates = {
            "industrial_asset": {
                "twin_type": DigitalTwinType.ASSET.value,
                "name": "Industrial Asset Twin",
                "description": "Digital Twin for industrial assets with monitoring and prediction",
                "capabilities": [
                    TwinCapability.MONITORING.value,
                    TwinCapability.ANALYTICS.value,
                    TwinCapability.PREDICTION.value,
                    TwinCapability.MAINTENANCE_PLANNING.value
                ],
                "model_configurations": {
                    TwinModelType.PHYSICS_BASED.value: {"enabled": True},
                    TwinModelType.DATA_DRIVEN.value: {"enabled": True}
                },
                "data_sources": ["sensors", "maintenance_logs", "operational_data"],
                "update_frequency": 30,
                "model_templates": ["basic_physics", "basic_ml"]
            },
            "smart_building": {
                "twin_type": DigitalTwinType.INFRASTRUCTURE.value,
                "name": "Smart Building Twin",
                "description": "Digital Twin for smart building management",
                "capabilities": [
                    TwinCapability.MONITORING.value,
                    TwinCapability.OPTIMIZATION.value,
                    TwinCapability.CONTROL.value
                ],
                "model_configurations": {
                    TwinModelType.HYBRID.value: {"enabled": True}
                },
                "data_sources": ["hvac_sensors", "occupancy_sensors", "energy_meters"],
                "update_frequency": 60,
                "model_templates": ["basic_physics"]
            },
            "user_smartwatch": {
                "twin_type": DigitalTwinType.ASSET.value,
                "name": "User Smartwatch Twin",
                "description": "Digital Twin for user wearable devices with health monitoring",
                "capabilities": [
                    TwinCapability.MONITORING.value,
                    TwinCapability.ANALYTICS.value,
                    TwinCapability.PREDICTION.value,
                    TwinCapability.ANOMALY_DETECTION.value
                ],
                "model_configurations": {
                    TwinModelType.DATA_DRIVEN.value: {"enabled": True}
                },
                "data_sources": [
                    "heart_rate_sensor", "accelerometer", "gyroscope",
                    "gps_location", "sleep_sensor", "stress_sensor", "blood_oxygen_sensor"
                ],
                "update_frequency": 5,
                "quality_requirements": {
                    "min_quality": 0.85,
                    "alert_threshold": 0.7
                },
                "model_templates": ["basic_ml"]
            }
        }
        return templates.get(template_name)
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