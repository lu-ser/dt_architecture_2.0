# src/layers/application/api/secure_digital_twins.py

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body, status
from pydantic import BaseModel, Field, validator

# Import per autenticazione
from src.layers.application.auth import (
    get_auth_context, AuthContext, require_permission, Permissions,
    require_digital_twin_read, require_digital_twin_write
)
from src.layers.application.api_gateway import APIGateway
from src.layers.application.api import get_gateway
from src.core.interfaces.digital_twin import TwinCapability, DigitalTwinType
from src.layers.digital_twin.dt_factory import DTAccessLevel
from src.utils.exceptions import EntityNotFoundError, ValidationError, AuthorizationError

logger = logging.getLogger(__name__)
router = APIRouter()

# === PYDANTIC MODELS ===

class SecureDigitalTwinCreate(BaseModel):
    twin_type: str = Field(..., description='Type of Digital Twin')
    name: str = Field(..., min_length=1, max_length=255, description='Human-readable name')
    description: str = Field('', max_length=1000, description='Description of the twin')
    capabilities: Optional[List[str]] = Field(None, description='List of capabilities (optional, defaults to ["monitoring"])')
    template_id: Optional[str] = Field(None, description='Template ID for creation')
    customization: Optional[Dict[str, Any]] = Field(None, description='Template customization')
    
    # Security-specific fields
    security_enabled: bool = Field(True, description='Enable security features')
    shared_with_tenant: bool = Field(True, description='Share with tenant users')
    authorized_users: Optional[List[Dict[str, str]]] = Field(
        None, 
        description='Initial authorized users [{"user_id": "uuid", "access_level": "read|write|execute|admin"}]'
    )
    metadata: Optional[Dict[str, Any]] = Field(None, description='Custom metadata')
    
    @validator('twin_type')
    @classmethod
    def validate_twin_type(cls, v):
        try:
            DigitalTwinType(v)
            return v
        except ValueError:
            valid_types = [t.value for t in DigitalTwinType]
            raise ValueError(f'Invalid twin_type. Must be one of: {valid_types}')

    @validator('capabilities', pre=True, always=True)
    @classmethod
    def validate_capabilities(cls, v):
        """Validate capabilities or assign defaults if not provided."""
        # Se None o lista vuota, il factory userà ["monitoring"] di default
        if v is None or v == []:
            return None
            
        if not isinstance(v, list):
            raise ValueError("capabilities must be a list")
        
        # Validazione con registry (copiata dall'endpoint legacy)
        try:
            from src.core.capabilities.capability_registry import get_capability_registry
            registry = get_capability_registry()
            
            invalid_capabilities = []
            valid_capabilities = []
            
            for cap in v:
                if not isinstance(cap, str):
                    raise ValueError(f"All capabilities must be strings, got {type(cap)}")
                
                if registry.has_capability(cap):
                    valid_capabilities.append(cap)
                else:
                    invalid_capabilities.append(cap)
            
            if invalid_capabilities:
                available = [cap.full_name for cap in registry.list_capabilities()]
                raise ValueError(f"Invalid capabilities: {invalid_capabilities}. Available: {available}")
            
            return valid_capabilities
            
        except ImportError:
            # Fallback senza registry
            return v
    
    @validator('authorized_users')
    @classmethod
    def validate_authorized_users(cls, v):
        if v is None:
            return v
        
        valid_levels = [level.value for level in DTAccessLevel]
        for user_data in v:
            if 'user_id' not in user_data or 'access_level' not in user_data:
                raise ValueError('Each authorized user must have user_id and access_level')
            
            try:
                UUID(user_data['user_id'])
            except ValueError:
                raise ValueError(f'Invalid user_id format: {user_data["user_id"]}')
            
            if user_data['access_level'] not in valid_levels:
                raise ValueError(f'Invalid access_level. Must be one of: {valid_levels}')
        
        return v

    class Config:
        schema_extra = {
            'example': {
                'twin_type': 'asset',
                'name': 'Turbina Eolica #001',
                'description': 'Digital Twin della turbina principale',
                'metadata': {
                    'location': 'Parco Eolico Sardegna',
                    'manufacturer': 'TecnoWind',
                    'model': 'TW-3000',
                    'installation_date': '2024-03-15'
                },
                'capabilities': ['monitoring', 'analytics'],  # Opzionale
                'security_enabled': True,
                'shared_with_tenant': True
            }
        }

class AccessManagement(BaseModel):
    target_user_id: UUID = Field(..., description='User ID to grant/revoke access')
    access_level: str = Field(..., description='Access level to grant')
    action: str = Field(..., description='Action: grant or revoke')
    
    @validator('access_level')
    @classmethod
    def validate_access_level(cls, v):
        valid_levels = [level.value for level in DTAccessLevel if level != DTAccessLevel.NONE]
        if v not in valid_levels:
            raise ValueError(f'Invalid access_level. Must be one of: {valid_levels}')
        return v
    
    @validator('action')
    @classmethod
    def validate_action(cls, v):
        if v not in ['grant', 'revoke']:
            raise ValueError('Action must be "grant" or "revoke"')
        return v

class SecureCapabilityExecution(BaseModel):
    capability: str = Field(..., description='Capability to execute')
    input_data: Dict[str, Any] = Field(..., description='Input data for execution')
    execution_config: Optional[Dict[str, Any]] = Field(None, description='Execution configuration')

    @validator('capability')
    @classmethod
    def validate_capability(cls, v):
        try:
            TwinCapability(v)
            return v
        except ValueError:
            valid_caps = [c.value for c in TwinCapability]
            raise ValueError(f'Invalid capability. Must be one of: {valid_caps}')

# === SECURE ENDPOINTS ===

@router.get('/', summary='🔒 List My Digital Twins (Secure)')
async def list_my_digital_twins(
    auth_context: AuthContext = Depends(get_auth_context),
    gateway: APIGateway = Depends(get_gateway),
    twin_type: Optional[str] = Query(None, description='Filter by twin type'),
    access_level: Optional[str] = Query(None, description='Filter by minimum access level'),
    limit: int = Query(100, ge=1, le=1000, description='Maximum number of results'),
    offset: int = Query(0, ge=0, description='Number of results to skip')
) -> Dict[str, Any]:
    """Get all Digital Twins accessible to the authenticated user"""
    try:
        # Get user's accessible twins
        user_twins = await gateway.get_user_twins(auth_context)
        
        # Apply filters
        all_twins = []
        for category, twins in user_twins['twins'].items():
            all_twins.extend(twins)
        
        if twin_type:
            all_twins = [t for t in all_twins if t.get('twin_type') == twin_type]
        
        # Apply pagination
        total = len(all_twins)
        paginated_twins = all_twins[offset:offset + limit]
        
        return {
            **user_twins,
            'filtered_twins': paginated_twins,
            'pagination': {
                'total': total,
                'limit': limit,
                'offset': offset,
                'count': len(paginated_twins)
            }
        }
        
    except Exception as e:
        logger.error(f'Failed to list user Digital Twins: {e}')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to list Digital Twins: {e}'
        )

@router.post('/', summary='🔒 Create Secure Digital Twin')
async def create_secure_digital_twin(
    twin_data: SecureDigitalTwinCreate,
    auth_context: AuthContext = Depends(require_digital_twin_write),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Create a new secure Digital Twin with ownership and access controls"""
    try:
        # AGGIUNTO: Debug per verificare auth_context
        logger.info(f"🔍 Auth context: {auth_context}")
        logger.info(f"🔍 Auth metadata: {auth_context.metadata if auth_context else 'None'}")
        
        # Convert to gateway format
        twin_config = twin_data.dict()
        logger.info(f"🔍 Twin config: {twin_config}")
        
        # SOLUZIONE 1: Usa il metodo corretto se gateway è SecureAPIGateway
        if hasattr(gateway, 'create_digital_twin_secure'):
            logger.info("🔍 Using SecureAPIGateway method")
            result = await gateway.create_digital_twin_secure(
                twin_config=twin_config, 
                auth_context=auth_context
            )
        else:
            # SOLUZIONE 2: Fallback al metodo normale con security_enabled=True
            logger.info("🔍 Using APIGateway method with security enabled")
            twin_config['security_enabled'] = True
            result = await gateway.create_digital_twin(
                twin_config=twin_config, 
                auth_context=auth_context
            )
        
        return {
            **result,
            'message': 'Secure Digital Twin created successfully',
            'owner_id': str(auth_context.subject_id),
            'security_enabled': twin_data.security_enabled
        }
        
    except AuthorizationError as e:
        logger.error(f"Authorization error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except ValidationError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, 
            detail=str(e)
        )
    except ValueError as e:
        logger.error(f"Value error: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, 
            detail=str(e)
        )
    except Exception as e:
        logger.error(f'Failed to create secure Digital Twin: {e}', exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to create Digital Twin: {str(e)}'
        )
@router.get('/{twin_id}', summary='🔒 Get Digital Twin (Secure)')
async def get_secure_digital_twin(
    twin_id: UUID = Path(..., description='Digital Twin ID'),
    auth_context: AuthContext = Depends(get_auth_context),
    gateway: APIGateway = Depends(get_gateway),
    include_security_details: bool = Query(False, description='Include detailed security info (admin only)')
) -> Dict[str, Any]:
    """Get Digital Twin with access control verification"""
    try:
        result = await gateway.get_digital_twin(
            twin_id=twin_id, 
            auth_context=auth_context
        )
        
        # Add access info
        result['accessed_by'] = str(auth_context.subject_id)
        result['accessed_at'] = datetime.utcnow().isoformat()
        
        return result
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Digital Twin {twin_id} not found or not accessible'
        )
    except Exception as e:
        logger.error(f'Failed to get Digital Twin {twin_id}: {e}')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to get Digital Twin: {e}'
        )

@router.post('/{twin_id}/execute', summary='🔒 Execute Capability (Secure)')
async def execute_secure_capability(
    twin_id: UUID = Path(..., description='Digital Twin ID'),
    execution_data: SecureCapabilityExecution = Body(...),
    auth_context: AuthContext = Depends(get_auth_context),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Execute Digital Twin capability with permission verification"""
    try:
        result = await gateway.execute_twin_capability(
            twin_id=twin_id,
            capability=execution_data.capability,
            input_data=execution_data.input_data,
            execution_config=execution_data.execution_config,
            auth_context=auth_context
        )
        
        return result
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Digital Twin {twin_id} not found'
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f'Failed to execute capability on twin {twin_id}: {e}')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Capability execution failed: {e}'
        )

@router.post('/{twin_id}/access', summary='🔒 Manage Access (Admin Only)')
async def manage_twin_access(
    twin_id: UUID = Path(..., description='Digital Twin ID'),
    access_data: AccessManagement = Body(...),
    auth_context: AuthContext = Depends(get_auth_context),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Manage access permissions for a Digital Twin (admin/owner only)"""
    try:
        result = await gateway.manage_twin_access(
            twin_id=twin_id,
            target_user_id=access_data.target_user_id,
            access_level=access_data.access_level,
            action=access_data.action,
            auth_context=auth_context
        )
        
        return result
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Digital Twin {twin_id} not found'
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f'Failed to manage access for twin {twin_id}: {e}')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Access management failed: {e}'
        )

@router.get('/{twin_id}/access', summary='🔒 Get Access Info (Admin Only)')
async def get_twin_access_info(
    twin_id: UUID = Path(..., description='Digital Twin ID'),
    auth_context: AuthContext = Depends(get_auth_context),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get access information for a Digital Twin (admin/owner only)"""
    try:
        # Get twin with security details
        result = await gateway.get_digital_twin(
            twin_id=twin_id, 
            auth_context=auth_context
        )
        
        # Extract only access-related info
        if result.get('security_enabled'):
            return {
                'twin_id': str(twin_id),
                'owner_id': result.get('owner_id'),
                'tenant_id': result.get('tenant_id'),
                'shared_with_tenant': result.get('shared_with_tenant'),
                'authorized_users': result.get('authorized_users', {}),
                'authorized_users_count': result.get('authorized_users_count', 0),
                'last_accessed_by': result.get('last_accessed_by'),
                'recent_access_log': result.get('recent_access_log', [])
            }
        else:
            return {
                'twin_id': str(twin_id),
                'security_enabled': False,
                'message': 'This twin does not have security features enabled'
            }
        
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Digital Twin {twin_id} not found'
        )
    except Exception as e:
        logger.error(f'Failed to get access info for twin {twin_id}: {e}')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to get access info: {e}'
        )

@router.get('/discover/secure', summary='🔒 Discover Accessible Twins')
async def discover_accessible_twins(
    auth_context: AuthContext = Depends(get_auth_context),
    gateway: APIGateway = Depends(get_gateway),
    twin_type: Optional[str] = Query(None, description='Filter by twin type'),
    has_capability: Optional[str] = Query(None, description='Filter by capability'),
    shared_only: bool = Query(False, description='Only shared twins'),
    limit: int = Query(50, ge=1, le=200, description='Maximum number of results'),
    offset: int = Query(0, ge=0, description='Number of results to skip')
) -> Dict[str, Any]:
    """Discover Digital Twins accessible to the user with advanced filtering"""
    try:
        # Build criteria
        criteria = {}
        if twin_type:
            criteria['type'] = twin_type
        if has_capability:
            criteria['has_capability'] = has_capability
        if shared_only:
            criteria['shared_with_tenant'] = True
        
        # Discover twins
        from src.layers.application.api_gateway import RequestType
        twins = await gateway.discover_entities(
            RequestType.DIGITAL_TWIN, 
            criteria, 
            auth_context
        )
        
        # Apply pagination
        total = len(twins)
        paginated_twins = twins[offset:offset + limit]
        
        return {
            'twins': paginated_twins,
            'pagination': {
                'total': total,
                'limit': limit,
                'offset': offset,
                'count': len(paginated_twins)
            },
            'discovery_criteria': criteria,
            'user_id': str(auth_context.subject_id)
        }
        
    except Exception as e:
        logger.error(f'Failed to discover twins: {e}')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Twin discovery failed: {e}'
        )

@router.get('/security/status', summary='🔒 Get Security Status')
async def get_security_status(
    auth_context: AuthContext = Depends(get_auth_context),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get overall security status and user's access summary"""
    try:
        # Get user twins summary
        user_twins = await gateway.get_user_twins(auth_context)
        
        return {
            'security_enabled': getattr(gateway, 'security_enabled', True),
            'tenant_isolation_enabled': getattr(gateway, 'enforce_tenant_isolation', True),
            'user_info': {
                'user_id': str(auth_context.subject_id),
                'tenant_id': auth_context.metadata.get('tenant_id'),
                'permissions': auth_context.permissions
            },
            'access_summary': user_twins['summary'],
            'security_features': {
                'tenant_isolation': True,
                'user_access_control': True, 
                'access_logging': True,
                'digital_twin_identity': True
            }
        }
        
    except Exception as e:
        logger.error(f'Failed to get security status: {e}')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to get security status: {e}'
        )