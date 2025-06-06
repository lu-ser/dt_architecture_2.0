
import asyncio
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
import bcrypt
from . import AuthContext, AuthSubject, AuthSubjectType, AuthMethod
from .jwt_auth import User, UserRole, JWTProvider
from .permissions import PermissionManager
from src.utils.exceptions import ValidationError, AuthenticationError
from src.utils.config import get_config

logger = logging.getLogger(__name__)

class Tenant:
    """Rappresenta un tenant nel sistema"""
    
    def __init__(self, tenant_id: UUID, name: str, plan: str = "free", 
                 created_by: UUID = None, metadata: Optional[Dict[str, Any]] = None):
        self.tenant_id = tenant_id
        self.name = name
        self.plan = plan  # free, pro, enterprise
        self.created_by = created_by
        self.created_at = datetime.now(timezone.utc)
        self.is_active = True
        self.metadata = metadata or {}
        self.settings = {
            "max_digital_twins": self._get_plan_limits(plan)["max_twins"],
            "max_users": self._get_plan_limits(plan)["max_users"],
            "storage_gb": self._get_plan_limits(plan)["storage_gb"]
        }
    
    def _get_plan_limits(self, plan: str) -> Dict[str, int]:
        """Limiti per piano di abbonamento"""
        limits = {
            "free": {"max_twins": 5, "max_users": 3, "storage_gb": 1},
            "pro": {"max_twins": 50, "max_users": 25, "storage_gb": 100},
            "enterprise": {"max_twins": -1, "max_users": -1, "storage_gb": -1}  # unlimited
        }
        return limits.get(plan, limits["free"])
    
    def can_create_digital_twin(self, current_count: int) -> bool:
        """Verifica se può creare altri Digital Twin"""
        max_twins = self.settings["max_digital_twins"]
        return max_twins == -1 or current_count < max_twins
    
    def can_add_user(self, current_count: int) -> bool:
        """Verifica se può aggiungere altri utenti"""
        max_users = self.settings["max_users"]
        return max_users == -1 or current_count < max_users
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'tenant_id': str(self.tenant_id),
            'name': self.name,
            'plan': self.plan,
            'created_by': str(self.created_by) if self.created_by else None,
            'created_at': self.created_at.isoformat(),
            'is_active': self.is_active,
            'settings': self.settings,
            'metadata': self.metadata
        }

class UserRegistrationRequest:
    """Richiesta di registrazione utente"""
    
    def __init__(self, username: str, email: str, password: str,
                 first_name: str, last_name: str,
                 company_name: Optional[str] = None,
                 plan: str = "free"):
        self.username = username.lower().strip()
        self.email = email.lower().strip()
        self.password = password
        self.first_name = first_name.strip()
        self.last_name = last_name.strip()
        self.company_name = company_name.strip() if company_name else None
        self.plan = plan
        
    def validate(self) -> List[str]:
        """Valida la richiesta di registrazione"""
        errors = []
        
        # Username
        if len(self.username) < 3:
            errors.append("Username must be at least 3 characters")
        if not self.username.replace('_', '').replace('-', '').isalnum():
            errors.append("Username can only contain letters, numbers, hyphens and underscores")
        
        # Email
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, self.email):
            errors.append("Invalid email format")
        
        # Password
        if len(self.password) < 8:
            errors.append("Password must be at least 8 characters")
        if not any(c.isupper() for c in self.password):
            errors.append("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in self.password):
            errors.append("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in self.password):
            errors.append("Password must contain at least one number")
        
        # Name
        if len(self.first_name) < 1:
            errors.append("First name is required")
        if len(self.last_name) < 1:
            errors.append("Last name is required")
        
        # Plan
        if self.plan not in ["free", "pro", "enterprise"]:
            errors.append("Invalid plan selected")
        
        return errors

class EnhancedUser(User):
    """User esteso con tenant e metadata aggiuntivi"""
    
    def __init__(self, user_id: UUID, username: str, email: str, password_hash: str,
                 role: str, tenant_id: UUID, first_name: str, last_name: str,
                 is_active: bool = True, metadata: Optional[Dict[str, Any]] = None,
                 created_at: Optional[datetime] = None, last_login: Optional[datetime] = None):
        
        # Estendi metadata con informazioni aggiuntive
        enhanced_metadata = metadata or {}
        enhanced_metadata.update({
            'first_name': first_name,
            'last_name': last_name,
            'tenant_id': str(tenant_id),
            'full_name': f"{first_name} {last_name}",
            'registration_completed': True
        })
        
        super().__init__(user_id, username, email, password_hash, role, 
                        is_active, enhanced_metadata, created_at, last_login)
        
        self.tenant_id = tenant_id
        self.first_name = first_name
        self.last_name = last_name
    
    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        """Override per includere informazioni tenant"""
        user_dict = super().to_dict(include_sensitive)
        user_dict.update({
            'tenant_id': str(self.tenant_id),
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': f"{self.first_name} {self.last_name}"
        })
        return user_dict

class UserRegistrationService:
    """Servizio per gestione registrazione e tenant"""
    
    def __init__(self, jwt_provider: JWTProvider):
        self.jwt_provider = jwt_provider
        self.config = get_config()
        self.tenants: Dict[UUID, Tenant] = {}
        self.pending_registrations: Dict[str, Dict[str, Any]] = {}  # email -> registration_data
        self.email_verification_enabled = self.config.get('auth.require_email_verification', False)
        
    async def register_user(self, registration: UserRegistrationRequest) -> Dict[str, Any]:
        """Registra nuovo utente e crea tenant"""
        
        # Validazione
        validation_errors = registration.validate()
        if validation_errors:
            raise ValidationError(f"Registration validation failed: {'; '.join(validation_errors)}")
        
        # Controlla se username/email già esistono
        if await self._username_exists(registration.username):
            raise ValidationError(f"Username '{registration.username}' already exists")
        
        if await self._email_exists(registration.email):
            raise ValidationError(f"Email '{registration.email}' already registered")
        
        # Crea tenant
        tenant = await self._create_tenant(registration)
        
        # Crea utente come admin del tenant
        user = await self._create_user_with_tenant(registration, tenant)
        
        # Setup permessi speciali per owner del tenant
        await self._setup_tenant_owner_permissions(user, tenant)
        
        if self.email_verification_enabled:
            # In produzione, invia email di verifica
            verification_token = await self._create_verification_token(user)
            return {
                'status': 'pending_verification',
                'message': 'Please check your email to verify your account',
                'user_id': str(user.user_id),
                'tenant_id': str(tenant.tenant_id),
                'verification_required': True
            }
        else:
            # Attiva immediatamente
            return await self._complete_registration(user, tenant)
    
    async def verify_email(self, verification_token: str) -> Dict[str, Any]:
        """Verifica email con token"""
        # In una implementazione reale, verificheremmo il token
        # Per ora simuliamo che il token sia valido
        
        user_id = await self._get_user_from_verification_token(verification_token)
        if not user_id:
            raise ValidationError("Invalid or expired verification token")
        
        user = await self.jwt_provider.get_user_by_id(user_id)
        if not user:
            raise ValidationError("User not found")
        
        tenant = self.tenants.get(UUID(user.metadata['tenant_id']))
        if not tenant:
            raise ValidationError("Tenant not found")
        
        return await self._complete_registration(user, tenant)
    
    async def invite_user_to_tenant(self, tenant_id: UUID, inviter_id: UUID,
                                   email: str, role: str = UserRole.VIEWER) -> Dict[str, Any]:
        """Invita utente a unirsi a tenant esistente"""
        
        # Verifica che l'inviter sia admin del tenant
        inviter = await self.jwt_provider.get_user_by_id(inviter_id)
        if not inviter or UUID(inviter.metadata['tenant_id']) != tenant_id:
            raise ValidationError("Only tenant members can invite users")
        
        if inviter.role not in [UserRole.ADMIN, 'tenant_admin']:
            raise ValidationError("Only admins can invite users")
        
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            raise ValidationError("Tenant not found")
        
        # Controlla limiti piano
        current_users = await self._count_tenant_users(tenant_id)
        if not tenant.can_add_user(current_users):
            raise ValidationError(f"Tenant has reached maximum user limit ({tenant.settings['max_users']})")
        
        # Crea invito
        invite_token = secrets.token_urlsafe(32)
        invite_data = {
            'tenant_id': str(tenant_id),
            'inviter_id': str(inviter_id),
            'email': email,
            'role': role,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'expires_at': (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        }
        
        self.pending_registrations[invite_token] = invite_data
        
        # In produzione, invia email di invito
        logger.info(f"User invitation sent to {email} for tenant {tenant_id}")
        
        return {
            'status': 'invitation_sent',
            'message': f'Invitation sent to {email}',
            'invite_token': invite_token,
            'expires_in_days': 7
        }
    
    async def accept_invitation(self, invite_token: str, 
                               registration: UserRegistrationRequest) -> Dict[str, Any]:
        """Accetta invito e completa registrazione"""
        
        if invite_token not in self.pending_registrations:
            raise ValidationError("Invalid or expired invitation")
        
        invite_data = self.pending_registrations[invite_token]
        
        # Verifica scadenza
        expires_at = datetime.fromisoformat(invite_data['expires_at'])
        if datetime.now(timezone.utc) > expires_at:
            del self.pending_registrations[invite_token]
            raise ValidationError("Invitation has expired")
        
        # Verifica che l'email corrisponda
        if registration.email != invite_data['email']:
            raise ValidationError("Email must match the invitation")
        
        tenant_id = UUID(invite_data['tenant_id'])
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            raise ValidationError("Tenant not found")
        
        # Crea utente nel tenant esistente
        user = await self._create_user_with_existing_tenant(registration, tenant, invite_data['role'])
        
        # Rimuovi invito utilizzato
        del self.pending_registrations[invite_token]
        
        return await self._complete_registration(user, tenant)
    
    async def get_tenant_info(self, tenant_id: UUID) -> Dict[str, Any]:
        """Ottieni informazioni tenant"""
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            raise ValidationError("Tenant not found")
        
        # Statistiche usage
        user_count = await self._count_tenant_users(tenant_id)
        twin_count = await self._count_tenant_digital_twins(tenant_id)
        
        return {
            **tenant.to_dict(),
            'usage': {
                'users': user_count,
                'digital_twins': twin_count,
                'storage_used_gb': 0  # TODO: implementare calcolo storage
            },
            'limits': {
                'users_remaining': tenant.settings['max_users'] - user_count if tenant.settings['max_users'] != -1 else -1,
                'twins_remaining': tenant.settings['max_digital_twins'] - twin_count if tenant.settings['max_digital_twins'] != -1 else -1
            }
        }
    
    # === PRIVATE METHODS ===
    
    async def _username_exists(self, username: str) -> bool:
        """Verifica se username esiste"""
        existing_user = await self.jwt_provider.get_user_by_username(username)
        return existing_user is not None
    
    async def _email_exists(self, email: str) -> bool:
        """Verifica se email esiste"""
        users = await self.jwt_provider.list_users(include_inactive=True)
        return any(user['email'] == email for user in users)
    
    async def _create_tenant(self, registration: UserRegistrationRequest) -> Tenant:
        """Crea nuovo tenant"""
        tenant_id = uuid4()
        tenant_name = registration.company_name or f"{registration.first_name} {registration.last_name}"
        
        tenant = Tenant(
            tenant_id=tenant_id,
            name=tenant_name,
            plan=registration.plan,
            metadata={
                'created_by_email': registration.email,
                'registration_ip': 'unknown',  # TODO: catturare IP
                'onboarding_completed': False
            }
        )
        
        self.tenants[tenant_id] = tenant
        logger.info(f"Created tenant {tenant_id} for {registration.email}")
        
        return tenant
    
    async def _create_user_with_tenant(self, registration: UserRegistrationRequest, 
                                     tenant: Tenant) -> EnhancedUser:
        """Crea utente come owner del tenant"""
        user_id = uuid4()
        password_hash = bcrypt.hashpw(registration.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Owner del tenant è sempre admin
        role = UserRole.ADMIN
        
        user = EnhancedUser(
            user_id=user_id,
            username=registration.username,
            email=registration.email,
            password_hash=password_hash,
            role=role,
            tenant_id=tenant.tenant_id,
            first_name=registration.first_name,
            last_name=registration.last_name,
            metadata={
                'is_tenant_owner': True,
                'registration_source': 'direct',
                'onboarding_completed': False
            }
        )
        
        # Aggiungi al sistema JWT
        self.jwt_provider.users[registration.username] = user
        self.jwt_provider.users_by_id[user_id] = user
        
        # Aggiorna tenant con owner
        tenant.created_by = user_id
        
        logger.info(f"Created tenant owner {user_id} for tenant {tenant.tenant_id}")
        
        return user
    
    async def _create_user_with_existing_tenant(self, registration: UserRegistrationRequest,
                                              tenant: Tenant, role: str) -> EnhancedUser:
        """Crea utente in tenant esistente"""
        user_id = uuid4()
        password_hash = bcrypt.hashpw(registration.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        user = EnhancedUser(
            user_id=user_id,
            username=registration.username,
            email=registration.email,
            password_hash=password_hash,
            role=role,
            tenant_id=tenant.tenant_id,
            first_name=registration.first_name,
            last_name=registration.last_name,
            metadata={
                'is_tenant_owner': False,
                'registration_source': 'invitation',
                'invited_by': tenant.created_by
            }
        )
        
        # Aggiungi al sistema JWT
        self.jwt_provider.users[registration.username] = user
        self.jwt_provider.users_by_id[user_id] = user
        
        logger.info(f"Created invited user {user_id} for tenant {tenant.tenant_id}")
        
        return user
    
    async def _setup_tenant_owner_permissions(self, user: EnhancedUser, tenant: Tenant) -> None:
        """Setup permessi speciali per owner del tenant"""
        # Owner ha tutti i permessi nel suo tenant
        user.metadata['tenant_permissions'] = [
            'tenant:admin',
            'digital_twin:*',
            'service:*',
            'replica:*',
            'user:manage',
            'billing:manage'
        ]
    
    async def _complete_registration(self, user: EnhancedUser, tenant: Tenant) -> Dict[str, Any]:
        """Completa registrazione e restituisce token"""
        
        # Genera token di accesso
        token_pair = await self.jwt_provider.generate_token_pair(user)
        
        return {
            'status': 'registration_complete',
            'message': 'Welcome to Digital Twin Platform!',
            'user': user.to_dict(),
            'tenant': tenant.to_dict(),
            'tokens': token_pair.to_dict(),
            'next_steps': [
                'Complete your profile',
                'Create your first Digital Twin',
                'Explore platform features'
            ]
        }
    
    async def _create_verification_token(self, user: EnhancedUser) -> str:
        """Crea token di verifica email"""
        token = secrets.token_urlsafe(32)
        # In produzione, salvare in database con scadenza
        return token
    
    async def _get_user_from_verification_token(self, token: str) -> Optional[UUID]:
        """Ottiene user_id da token di verifica"""
        # In produzione, cercare nel database
        return uuid4()  # Mock
    
    async def _count_tenant_users(self, tenant_id: UUID) -> int:
        """Conta utenti del tenant"""
        users = await self.jwt_provider.list_users(include_inactive=False)
        return len([u for u in users if u.get('metadata', {}).get('tenant_id') == str(tenant_id)])
    
    async def _count_tenant_digital_twins(self, tenant_id: UUID) -> int:
        """Conta Digital Twin del tenant"""
        # TODO: implementare quando avremo il registry con tenant
        return 0


import secrets
import jwt
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from uuid import UUID, uuid4
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography import x509
from src.utils.config import get_config

logger = logging.getLogger(__name__)

class DigitalTwinIdentity:
    """Identità crittografica per Digital Twin"""
    
    def __init__(self, twin_id: UUID, owner_id: UUID, tenant_id: UUID):
        self.twin_id = twin_id
        self.owner_id = owner_id
        self.tenant_id = tenant_id
        self.created_at = datetime.now(timezone.utc)
        self.last_rotation = self.created_at
        
        # Genera credenziali
        self.api_token = self._generate_api_token()
        self.private_key, self.certificate = self._generate_certificate()
        
        # Metadata di sicurezza
        self.token_version = 1
        self.certificate_serial = self.certificate.serial_number
        self.is_revoked = False
    
    def _generate_api_token(self) -> str:
        """Genera token API JWT per il Digital Twin"""
        config = get_config()
        secret_key = config.get('jwt.secret_key', 'default-secret')
        
        payload = {
            'sub': str(self.twin_id),  # Subject = Digital Twin ID
            'iss': 'digital-twin-platform',  # Issuer
            'aud': 'external-systems',  # Audience = sistemi esterni
            'iat': self.created_at.timestamp(),
            'exp': (self.created_at + timedelta(days=365)).timestamp(),
            'type': 'digital_twin_api',
            'owner_id': str(self.owner_id),
            'tenant_id': str(self.tenant_id),
            'version': self.token_version,
            'permissions': [
                'device:communicate',
                'data:send',
                'data:receive', 
                'twin:authenticate'
            ]
        }
        
        return jwt.encode(payload, secret_key, algorithm='HS256')
    
    def _generate_certificate(self) -> tuple:
        """Genera certificato X.509 per comunicazioni sicure"""
        
        # Genera chiave privata RSA
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        
        # Subject e Issuer del certificato
        subject = issuer = x509.Name([
            x509.NameAttribute(x509.NameOID.COUNTRY_NAME, "IT"),
            x509.NameAttribute(x509.NameOID.STATE_OR_PROVINCE_NAME, "Sardinia"),
            x509.NameAttribute(x509.NameOID.LOCALITY_NAME, "Cagliari"),
            x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, "Digital Twin Platform"),
            x509.NameAttribute(x509.NameOID.ORGANIZATIONAL_UNIT_NAME, "Digital Twins"),
            x509.NameAttribute(x509.NameOID.COMMON_NAME, f"dt-{self.twin_id}"),
        ])
        
        # Crea certificato
        certificate = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            self.created_at
        ).not_valid_after(
            self.created_at + timedelta(days=365)
        ).add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(f"twin-{self.twin_id}.dt-platform.local"),
                x509.DNSName(f"dt-{self.twin_id}.internal"),
                x509.IPAddress('127.0.0.1'),  # Per testing locale
            ]),
            critical=False,
        ).add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        ).add_extension(
            x509.ExtendedKeyUsage([
                x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
            ]),
            critical=True,
        ).sign(private_key, hashes.SHA256())
        
        return private_key, certificate
    
    async def rotate_credentials(self) -> None:
        """Ruota tutte le credenziali per sicurezza"""
        logger.info(f"Rotating credentials for Digital Twin {self.twin_id}")
        
        # Incrementa versione
        self.token_version += 1
        
        # Genera nuovo token
        self.api_token = self._generate_api_token()
        
        # Genera nuovo certificato
        self.private_key, self.certificate = self._generate_certificate()
        
        # Aggiorna timestamp
        self.last_rotation = datetime.now(timezone.utc)
        
        logger.info(f"Credentials rotated for Digital Twin {self.twin_id}, new version: {self.token_version}")
    
    def get_public_certificate_pem(self) -> str:
        """Restituisce certificato pubblico in formato PEM"""
        return self.certificate.public_bytes(serialization.Encoding.PEM).decode()
    
    def get_private_key_pem(self) -> str:
        """Restituisce chiave privata in formato PEM (ATTENZIONE: sensibile!)"""
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode()
    
    def validate_token(self) -> bool:
        """Valida se il token è ancora valido"""
        if self.is_revoked:
            return False
        
        try:
            config = get_config()
            secret_key = config.get('jwt.secret_key', 'default-secret')
            
            payload = jwt.decode(self.api_token, secret_key, algorithms=['HS256'])
            
            # Verifica scadenza
            exp = payload.get('exp', 0)
            if datetime.now(timezone.utc).timestamp() > exp:
                return False
            
            # Verifica versione
            if payload.get('version', 0) != self.token_version:
                return False
            
            return True
            
        except jwt.InvalidTokenError:
            return False
    
    def revoke(self) -> None:
        """Revoca l'identità"""
        self.is_revoked = True
        logger.warning(f"Digital Twin identity {self.twin_id} has been revoked")
    
    def to_dict(self, include_private_key: bool = False) -> Dict[str, Any]:
        """Serializza identità"""
        data = {
            'twin_id': str(self.twin_id),
            'owner_id': str(self.owner_id),
            'tenant_id': str(self.tenant_id),
            'api_token': self.api_token,
            'certificate_pem': self.get_public_certificate_pem(),
            'certificate_serial': str(self.certificate_serial),
            'token_version': self.token_version,
            'created_at': self.created_at.isoformat(),
            'last_rotation': self.last_rotation.isoformat(),
            'is_revoked': self.is_revoked,
            'is_valid': self.validate_token()
        }
        
        if include_private_key:
            data['private_key_pem'] = self.get_private_key_pem()
        
        return data

class DigitalTwinIdentityService:
    """Servizio per gestione identità Digital Twin"""
    
    def __init__(self):
        self.config = get_config()
        self.identities: Dict[UUID, DigitalTwinIdentity] = {}
        self.token_to_twin: Dict[str, UUID] = {}  # Cache token -> twin_id
        
    async def create_identity(self, twin_id: UUID, owner_id: UUID, tenant_id: UUID) -> DigitalTwinIdentity:
        """Crea nuova identità per Digital Twin"""
        
        if twin_id in self.identities:
            raise ValueError(f"Identity already exists for Digital Twin {twin_id}")
        
        identity = DigitalTwinIdentity(twin_id, owner_id, tenant_id)
        
        # Salva in memoria (in produzione: database)
        self.identities[twin_id] = identity
        self.token_to_twin[identity.api_token] = twin_id
        
        logger.info(f"Created identity for Digital Twin {twin_id}")
        
        return identity
    
    async def get_identity(self, twin_id: UUID) -> Optional[DigitalTwinIdentity]:
        """Ottieni identità di un Digital Twin"""
        return self.identities.get(twin_id)
    
    async def validate_twin_token(self, token: str) -> Optional[UUID]:
        """Valida token Digital Twin e restituisce twin_id"""
        
        # Check cache first
        if token in self.token_to_twin:
            twin_id = self.token_to_twin[token]
            identity = self.identities.get(twin_id)
            
            if identity and identity.validate_token():
                return twin_id
            else:
                # Rimuovi da cache se non valido
                del self.token_to_twin[token]
        
        # Verifica token manualmente
        try:
            config = get_config()
            secret_key = config.get('jwt.secret_key', 'default-secret')
            
            payload = jwt.decode(token, secret_key, algorithms=['HS256'])
            
            if payload.get('type') != 'digital_twin_api':
                return None
            
            twin_id = UUID(payload['sub'])
            identity = self.identities.get(twin_id)
            
            if identity and identity.api_token == token and identity.validate_token():
                # Aggiorna cache
                self.token_to_twin[token] = twin_id
                return twin_id
            
        except (jwt.InvalidTokenError, ValueError, KeyError):
            pass
        
        return None
    
    async def rotate_identity(self, twin_id: UUID) -> DigitalTwinIdentity:
        """Ruota credenziali di un Digital Twin"""
        
        identity = self.identities.get(twin_id)
        if not identity:
            raise ValueError(f"Identity not found for Digital Twin {twin_id}")
        
        # Rimuovi vecchio token da cache
        old_token = identity.api_token
        if old_token in self.token_to_twin:
            del self.token_to_twin[old_token]
        
        # Ruota credenziali
        await identity.rotate_credentials()
        
        # Aggiorna cache con nuovo token
        self.token_to_twin[identity.api_token] = twin_id
        
        return identity
    
    async def revoke_identity(self, twin_id: UUID) -> bool:
        """Revoca identità di un Digital Twin"""
        
        identity = self.identities.get(twin_id)
        if not identity:
            return False
        
        # Revoca
        identity.revoke()
        
        # Rimuovi da cache
        if identity.api_token in self.token_to_twin:
            del self.token_to_twin[identity.api_token]
        
        logger.warning(f"Revoked identity for Digital Twin {twin_id}")
        
        return True
    
    async def cleanup_expired_identities(self) -> int:
        """Pulisce identità scadute"""
        
        expired_count = 0
        to_remove = []
        
        for twin_id, identity in self.identities.items():
            if not identity.validate_token():
                to_remove.append(twin_id)
                expired_count += 1
        
        for twin_id in to_remove:
            identity = self.identities[twin_id]
            
            # Rimuovi da cache
            if identity.api_token in self.token_to_twin:
                del self.token_to_twin[identity.api_token]
            
            # Rimuovi identità
            del self.identities[twin_id]
        
        if expired_count > 0:
            logger.info(f"Cleaned up {expired_count} expired Digital Twin identities")
        
        return expired_count
    
    def get_statistics(self) -> Dict[str, Any]:
        """Statistiche del servizio identità"""
        
        total_identities = len(self.identities)
        valid_identities = len([i for i in self.identities.values() if i.validate_token()])
        revoked_identities = len([i for i in self.identities.values() if i.is_revoked])
        
        return {
            'total_identities': total_identities,
            'valid_identities': valid_identities,
            'revoked_identities': revoked_identities,
            'cache_size': len(self.token_to_twin),
            'validation_rate': valid_identities / max(total_identities, 1)
        }