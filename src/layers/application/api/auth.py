# === NEW FILE: src/layers/application/api/auth.py ===

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, validator, EmailStr
from src.layers.application.auth import get_auth_manager, AuthContext, get_auth_context
from src.layers.application.auth.user_registration import UserRegistrationRequest, UserRegistrationService
from src.layers.application.auth.jwt_auth import JWTProvider
from src.utils.exceptions import ValidationError, AuthenticationError

logger = logging.getLogger(__name__)
router = APIRouter()

# === PYDANTIC MODELS ===

class UserRegistration(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="Unique username")
    email: EmailStr = Field(..., description="Valid email address")
    password: str = Field(..., min_length=8, description="Strong password")
    first_name: str = Field(..., min_length=1, max_length=50, description="First name")
    last_name: str = Field(..., min_length=1, max_length=50, description="Last name")
    company_name: Optional[str] = Field(None, max_length=100, description="Company name (optional)")
    plan: str = Field("free", description="Subscription plan")
    
    @validator('plan')
    @classmethod
    def validate_plan(cls, v):
        if v not in ["free", "pro", "enterprise"]:
            raise ValueError("Plan must be 'free', 'pro', or 'enterprise'")
        return v
    
    class Config:
        schema_extra = {
            'example': {
                'username': 'john_doe',
                'email': 'john@example.com',
                'password': 'StrongPass123!',
                'first_name': 'John',
                'last_name': 'Doe',
                'company_name': 'Acme Corp',
                'plan': 'pro'
            }
        }

class UserLogin(BaseModel):
    username: str = Field(..., description="Username or email")
    password: str = Field(..., description="Password")
    
    class Config:
        schema_extra = {
            'example': {
                'username': 'john_doe',
                'password': 'StrongPass123!'
            }
        }

class InviteUser(BaseModel):
    email: EmailStr = Field(..., description="Email of user to invite")
    role: str = Field("viewer", description="Role for invited user")
    message: Optional[str] = Field(None, description="Optional invitation message")
    
    @validator('role')
    @classmethod
    def validate_role(cls, v):
        from src.layers.application.auth.jwt_auth import UserRole
        if v not in [UserRole.ADMIN, UserRole.OPERATOR, UserRole.VIEWER]:
            raise ValueError(f"Role must be one of: {UserRole.ADMIN}, {UserRole.OPERATOR}, {UserRole.VIEWER}")
        return v

class AcceptInvitation(BaseModel):
    invite_token: str = Field(..., description="Invitation token")
    registration: UserRegistration = Field(..., description="User registration data")

class PasswordReset(BaseModel):
    email: EmailStr = Field(..., description="Email address for password reset")

class PasswordResetConfirm(BaseModel):
    reset_token: str = Field(..., description="Password reset token")
    new_password: str = Field(..., min_length=8, description="New password")

# === RESPONSE MODELS ===

class RegistrationResponse(BaseModel):
    status: str
    message: str
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    verification_required: bool = False
    tokens: Optional[Dict[str, Any]] = None

class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: Dict[str, Any]
    tenant: Dict[str, Any]

class TenantResponse(BaseModel):
    tenant_id: str
    name: str
    plan: str
    usage: Dict[str, Any]
    limits: Dict[str, Any]

# === DEPENDENCY INJECTION ===

async def get_registration_service() -> UserRegistrationService:
    """Dependency per ottenere il servizio di registrazione"""
    auth_manager = get_auth_manager()
    await auth_manager.initialize()
    return UserRegistrationService(auth_manager.jwt_provider)

# === ENDPOINTS ===

@router.post("/register", summary="Register New User", response_model=RegistrationResponse)
async def register_user(
    registration_data: UserRegistration,
    request: Request,
    registration_service: UserRegistrationService = Depends(get_registration_service)
) -> Dict[str, Any]:
    """
    Registra nuovo utente e crea tenant
    
    - Crea nuovo tenant per l'utente
    - Configura l'utente come admin del tenant  
    - Genera token di accesso
    - Setup Digital Twin identity system
    """
    try:
        # Converti in oggetto di dominio
        registration_request = UserRegistrationRequest(
            username=registration_data.username,
            email=registration_data.email,
            password=registration_data.password,
            first_name=registration_data.first_name,
            last_name=registration_data.last_name,
            company_name=registration_data.company_name,
            plan=registration_data.plan
        )
        
        # Registra utente
        result = await registration_service.register_user(registration_request)
        
        # Log registration
        logger.info(f"User registration: {registration_data.email} -> {result.get('status')}")
        
        return result
        
    except ValidationError as e:
        logger.warning(f"Registration validation failed: {e}")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.error(f"Registration failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration failed")

@router.post("/login", summary="User Login", response_model=LoginResponse)
async def login_user(
    login_data: UserLogin,
    request: Request,
    registration_service: UserRegistrationService = Depends(get_registration_service)
) -> Dict[str, Any]:
    """
    Autentica utente e restituisce token
    
    - Valida credenziali
    - Genera JWT token pair
    - Restituisce informazioni utente e tenant
    """
    try:
        # Autentica con JWT Provider
        jwt_provider = registration_service.jwt_provider
        credentials = {
            'username': login_data.username,
            'password': login_data.password
        }
        
        # Prova autenticazione
        auth_context = await jwt_provider.authenticate(credentials)
        
        # Ottieni user completo
        user = await jwt_provider.get_user_by_username(login_data.username)
        if not user:
            raise AuthenticationError("User not found")
        
        # Genera token pair
        token_pair = await jwt_provider.generate_token_pair(user)
        
        # Ottieni informazioni tenant
        tenant_id = UUID(user.metadata.get('tenant_id'))
        tenant_info = await registration_service.get_tenant_info(tenant_id)
        
        # Log successful login
        logger.info(f"Successful login: {user.username} (tenant: {tenant_id})")
        
        return {
            'access_token': token_pair.access_token,
            'refresh_token': token_pair.refresh_token,
            'token_type': token_pair.token_type,
            'expires_in': token_pair.expires_in,
            'user': user.to_dict(),
            'tenant': tenant_info
        }
        
    except AuthenticationError as e:
        logger.warning(f"Login failed: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Login failed")

@router.post("/refresh", summary="Refresh Token")
async def refresh_token(
    refresh_token: str,
    registration_service: UserRegistrationService = Depends(get_registration_service)
) -> Dict[str, Any]:
    """Rinnova token di accesso usando refresh token"""
    try:
        jwt_provider = registration_service.jwt_provider
        
        # Rinnova token
        new_token_pair = await jwt_provider.refresh_token(refresh_token)
        
        return {
            'access_token': new_token_pair.access_token,
            'refresh_token': new_token_pair.refresh_token,
            'token_type': new_token_pair.token_type,
            'expires_in': new_token_pair.expires_in
        }
        
    except AuthenticationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

@router.post("/logout", summary="Logout User")
async def logout_user(
    auth_context: AuthContext = Depends(get_auth_context),
    registration_service: UserRegistrationService = Depends(get_registration_service)
) -> Dict[str, str]:
    """
    Logout utente e revoca token
    """
    try:
        jwt_provider = registration_service.jwt_provider
        
        # Revoca tutti i token dell'utente
        await jwt_provider.revoke_all_user_tokens(auth_context.subject_id)
        
        logger.info(f"User logged out: {auth_context.subject_id}")
        
        return {
            'status': 'success',
            'message': 'Successfully logged out'
        }
        
    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Logout failed")

@router.post("/invite", summary="Invite User to Tenant")
async def invite_user_to_tenant(
    invite_data: InviteUser,
    auth_context: AuthContext = Depends(get_auth_context),
    registration_service: UserRegistrationService = Depends(get_registration_service)
) -> Dict[str, Any]:
    """
    Invita utente a unirsi al tenant corrente
    
    - Solo admin possono invitare
    - Verifica limiti del piano
    - Invia email di invito
    """
    try:
        # Verifica che l'utente sia admin
        if not auth_context.has_permission('user:manage'):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can invite users")
        
        tenant_id = UUID(auth_context.metadata.get('tenant_id'))
        
        # Invia invito
        result = await registration_service.invite_user_to_tenant(
            tenant_id=tenant_id,
            inviter_id=auth_context.subject_id,
            email=invite_data.email,
            role=invite_data.role
        )
        
        logger.info(f"User invitation sent: {invite_data.email} to tenant {tenant_id}")
        
        return result
        
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.error(f"Invitation failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invitation failed")

@router.post("/accept-invitation", summary="Accept Invitation", response_model=RegistrationResponse)
async def accept_invitation(
    acceptance_data: AcceptInvitation,
    registration_service: UserRegistrationService = Depends(get_registration_service)
) -> Dict[str, Any]:
    """
    Accetta invito e completa registrazione in tenant esistente
    """
    try:
        # Converti registration data
        registration_request = UserRegistrationRequest(
            username=acceptance_data.registration.username,
            email=acceptance_data.registration.email,
            password=acceptance_data.registration.password,
            first_name=acceptance_data.registration.first_name,
            last_name=acceptance_data.registration.last_name,
            company_name=acceptance_data.registration.company_name,
            plan=acceptance_data.registration.plan
        )
        
        # Accetta invito
        result = await registration_service.accept_invitation(
            invite_token=acceptance_data.invite_token,
            registration=registration_request
        )
        
        logger.info(f"Invitation accepted: {acceptance_data.registration.email}")
        
        return result
        
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.error(f"Invitation acceptance failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invitation acceptance failed")

@router.get("/me", summary="Get Current User Info")
async def get_current_user(
    auth_context: AuthContext = Depends(get_auth_context),
    registration_service: UserRegistrationService = Depends(get_registration_service)
) -> Dict[str, Any]:
    """
    Restituisce informazioni sull'utente corrente e il suo tenant
    """
    try:
        # Ottieni user
        user = await registration_service.jwt_provider.get_user_by_id(auth_context.subject_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
        # Ottieni tenant info
        tenant_id = UUID(user.metadata.get('tenant_id'))
        tenant_info = await registration_service.get_tenant_info(tenant_id)
        
        return {
            'user': user.to_dict(),
            'tenant': tenant_info,
            'auth_context': auth_context.to_dict()
        }
        
    except Exception as e:
        logger.error(f"Get current user failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get user info")

@router.get("/tenant", summary="Get Tenant Info", response_model=TenantResponse)
async def get_tenant_info(
    auth_context: AuthContext = Depends(get_auth_context),
    registration_service: UserRegistrationService = Depends(get_registration_service)
) -> Dict[str, Any]:
    """
    Restituisce informazioni dettagliate sul tenant corrente
    """
    try:
        tenant_id = UUID(auth_context.metadata.get('tenant_id'))
        tenant_info = await registration_service.get_tenant_info(tenant_id)
        
        return tenant_info
        
    except Exception as e:
        logger.error(f"Get tenant info failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get tenant info")

@router.get("/tenant/users", summary="List Tenant Users")
async def list_tenant_users(
    auth_context: AuthContext = Depends(get_auth_context),
    registration_service: UserRegistrationService = Depends(get_registration_service)
) -> Dict[str, Any]:
    """
    Lista tutti gli utenti del tenant corrente
    
    - Solo admin possono vedere tutti gli utenti
    - Altri utenti vedono solo se stessi
    """
    try:
        if not auth_context.has_permission('user:manage'):
            # Non admin - restituisce solo info proprie
            user = await registration_service.jwt_provider.get_user_by_id(auth_context.subject_id)
            return {
                'users': [user.to_dict()] if user else [],
                'total': 1 if user else 0,
                'can_manage': False
            }
        
        # Admin - lista tutti gli utenti del tenant
        tenant_id = auth_context.metadata.get('tenant_id')
        all_users = await registration_service.jwt_provider.list_users(include_inactive=False)
        
        # Filtra per tenant
        tenant_users = [
            user for user in all_users 
            if user.get('metadata', {}).get('tenant_id') == tenant_id
        ]
        
        return {
            'users': tenant_users,
            'total': len(tenant_users),
            'can_manage': True
        }
        
    except Exception as e:
        logger.error(f"List tenant users failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list users")

@router.post("/password-reset", summary="Request Password Reset")
async def request_password_reset(
    reset_data: PasswordReset,
    registration_service: UserRegistrationService = Depends(get_registration_service)
) -> Dict[str, str]:
    """
    Richiede reset password via email
    """
    try:
        # In produzione, invieremmo email con token
        # Per ora, log e conferma ricezione
        logger.info(f"Password reset requested for: {reset_data.email}")
        
        return {
            'status': 'success',
            'message': 'If the email exists, you will receive reset instructions'
        }
        
    except Exception as e:
        logger.error(f"Password reset request failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Password reset request failed")

@router.post("/password-reset/confirm", summary="Confirm Password Reset")
async def confirm_password_reset(
    reset_data: PasswordResetConfirm,
    registration_service: UserRegistrationService = Depends(get_registration_service)
) -> Dict[str, str]:
    """
    Conferma reset password con token
    """
    try:
        # In produzione, valideremmo il token e cambierebbero la password
        logger.info(f"Password reset confirmed with token: {reset_data.reset_token}")
        
        return {
            'status': 'success',
            'message': 'Password has been reset successfully'
        }
        
    except Exception as e:
        logger.error(f"Password reset confirmation failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Password reset failed")

@router.get("/statistics", summary="Get Auth Statistics")
async def get_auth_statistics(
    auth_context: AuthContext = Depends(get_auth_context),
    registration_service: UserRegistrationService = Depends(get_registration_service)
) -> Dict[str, Any]:
    """
    Statistiche del sistema di autenticazione
    
    - Solo admin possono vedere le statistiche
    """
    try:
        if not auth_context.has_permission('admin:*'):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
        
        # Statistiche JWT Provider
        jwt_stats = registration_service.jwt_provider.get_provider_status()
        
        # Statistiche tenant
        tenant_count = len(registration_service.tenants)
        active_tenants = len([t for t in registration_service.tenants.values() if t.is_active])
        
        return {
            'jwt_provider': jwt_stats,
            'tenants': {
                'total': tenant_count,
                'active': active_tenants,
                'by_plan': {
                    'free': len([t for t in registration_service.tenants.values() if t.plan == 'free']),
                    'pro': len([t for t in registration_service.tenants.values() if t.plan == 'pro']),
                    'enterprise': len([t for t in registration_service.tenants.values() if t.plan == 'enterprise'])
                }
            },
            'pending_invitations': len(registration_service.pending_registrations)
        }
        
    except Exception as e:
        logger.error(f"Get auth statistics failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get statistics")