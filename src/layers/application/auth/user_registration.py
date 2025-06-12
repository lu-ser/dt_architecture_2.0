
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
from src.storage.adapters.mongodb_adapter import MongoStorageAdapter
from src.core.interfaces.base import BaseMetadata, EntityStatus, IEntity

logger = logging.getLogger(__name__)

class Tenant(IEntity):
    """Classe Tenant modificata per supportare MongoDB"""
    
    def __init__(self, tenant_id: UUID, name: str, plan: str = 'free', 
                 created_by: UUID = None, metadata: Optional[Dict[str, Any]] = None):
        self.tenant_id = tenant_id
        self.name = name
        self.plan = plan
        self.created_by = created_by
        self.created_at = datetime.now(timezone.utc)
        self.is_active = True
        self.custom_metadata = metadata or {}
        self.settings = self._get_plan_limits(plan)
        
        # Implementazione IEntity
        self._entity_type = 'tenant'
        self._metadata = BaseMetadata(
            entity_id=tenant_id,
            timestamp=self.created_at,
            version='1.0.0',
            created_by=created_by or tenant_id,
            custom={
                'name': name,
                'plan': plan,
                'created_by': str(created_by) if created_by else None,
                'is_active': True,
                'settings': self.settings,
                'metadata': metadata or {}
            }
        )
        self._status = EntityStatus.ACTIVE

    @property
    def id(self) -> UUID:
        return self.tenant_id

    @property
    def metadata(self) -> BaseMetadata:
        return self._metadata

    @property
    def status(self) -> EntityStatus:
        return self._status

    @property
    def entity_type(self) -> str:
        return self._entity_type

    async def initialize(self) -> None:
        self._status = EntityStatus.ACTIVE

    async def start(self) -> None:
        self.is_active = True

    async def stop(self) -> None:
        self.is_active = False

    async def terminate(self) -> None:
        self.is_active = False
        self._status = EntityStatus.INACTIVE

    def validate(self) -> bool:
        import re
        if len(self.username) < 3:
            return False
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(email_pattern, self.email))
    

    def _get_plan_limits(self, plan: str) -> Dict[str, Any]:
        """Get limits based on plan"""
        limits = {
            'free': {
                'max_users': 5,
                'max_digital_twins': 3,
                'max_storage_gb': 1,
                'api_calls_per_month': 10000
            },
            'pro': {
                'max_users': 50,
                'max_digital_twins': 25,
                'max_storage_gb': 100,
                'api_calls_per_month': 100000
            },
            'enterprise': {
                'max_users': -1,  # unlimited
                'max_digital_twins': -1,
                'max_storage_gb': -1,
                'api_calls_per_month': -1
            }
        }
        return limits.get(plan, limits['free'])

    def can_create_digital_twin(self, current_count: int) -> bool:
        max_twins = self.settings['max_twins']
        return max_twins == -1 or current_count < max_twins

    def can_add_user(self, current_count: int) -> bool:
        max_users = self.settings['max_users']
        return max_users == -1 or current_count < max_users

    def to_dict(self) -> Dict[str, Any]:
        """Metodo to_dict corretto per Tenant"""
        return {
            'tenant_id': str(self.tenant_id),
            'name': self.name,
            'plan': self.plan,
            'created_by': str(self.created_by) if self.created_by else None,
            'created_at': self.created_at.isoformat(),
            'is_active': self.is_active,
            'settings': self.settings,
            'metadata': self.custom_metadata
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

class EnhancedUser(User, IEntity):
    """Classe EnhancedUser modificata per supportare MongoDB"""
    
    def __init__(self, user_id: UUID, username: str, email: str, password_hash: str, role: str, 
                 tenant_id: UUID, first_name: str, last_name: str, is_active: bool = True, 
                 metadata: Optional[Dict[str, Any]] = None, created_at: Optional[datetime] = None, 
                 last_login: Optional[datetime] = None):
        
        enhanced_metadata = metadata or {}
        enhanced_metadata.update({
            'first_name': first_name,
            'last_name': last_name,
            'tenant_id': str(tenant_id),
            'full_name': f'{first_name} {last_name}',
            'registration_completed': True
        })
        
        # Inizializza tutti gli attributi dell'utente
        self.user_id = user_id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.role = role
        self.is_active = is_active
        self.created_at = created_at or datetime.now(timezone.utc)
        self.last_login = last_login
        self.tenant_id = tenant_id
        self.first_name = first_name
        self.last_name = last_name
        self.custom_metadata = enhanced_metadata  # ← Questo è il dizionario modificabile
        
        # Implementazione IEntity
        self._entity_type = 'user'
        self._metadata = BaseMetadata(
            entity_id=user_id,
            timestamp=self.created_at,
            version='1.0.0',
            created_by=user_id,
            custom=enhanced_metadata
        )
        self._status = EntityStatus.ACTIVE if is_active else EntityStatus.INACTIVE

    def update_metadata(self, key: str, value: Any) -> None:
        """Aggiorna metadata in modo sicuro"""
        # Aggiorna il dizionario locale
        self.custom_metadata[key] = value
        
        # Ricrea BaseMetadata con i nuovi dati
        updated_custom = self.custom_metadata.copy()
        self._metadata = BaseMetadata(
            entity_id=self.user_id,
            timestamp=self.created_at,
            version='1.0.0',
            created_by=self.user_id,
            custom=updated_custom
        )

    @property
    def id(self) -> UUID:
        return self.user_id

    @property
    def metadata(self) -> BaseMetadata:
        return self._metadata

    @property
    def status(self) -> EntityStatus:
        return self._status
    
    @property 
    def metadata_dict(self) -> Dict[str, Any]:
        """Restituisce metadata come dizionario modificabile"""
        return self.custom_metadata
    
    @property
    def entity_type(self) -> str:
        return self._entity_type

    async def initialize(self) -> None:
        self._status = EntityStatus.ACTIVE if self.is_active else EntityStatus.INACTIVE

    async def start(self) -> None:
        self.is_active = True

    async def stop(self) -> None:
        self.is_active = False

    async def terminate(self) -> None:
        """Terminate the user"""
        self.is_active = False
        self._status = EntityStatus.INACTIVE

    def validate(self) -> bool:
        import re
        if len(self.username) < 3:
            return False
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        user_dict = {
            'user_id': str(self.user_id),
            'username': self.username,
            'password_hash': self.password_hash,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': f'{self.first_name} {self.last_name}',
            'role': self.role,
            'tenant_id': str(self.tenant_id),
            'is_active': self.is_active,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'created_at': self.created_at.isoformat(),
            'metadata': self.custom_metadata
        }
        
        if include_sensitive:
            user_dict['password_hash'] = self.password_hash
            
        return user_dict


class UserRegistrationService:
    """Classe UserRegistrationService corretta"""

    def __init__(self, jwt_provider: JWTProvider):
        self.jwt_provider = jwt_provider
        self.config = get_config()
        
        # MongoDB adapters invece di dizionari in memoria
        self.tenant_adapter = MongoStorageAdapter(Tenant, twin_id=None)
        self.user_adapter = MongoStorageAdapter(EnhancedUser, twin_id=None)
        
        # Cache in memoria per performance
        self.tenants: Dict[UUID, Tenant] = {}
        
        self.pending_registrations: Dict[str, Dict[str, Any]] = {}
        self.email_verification_enabled = self.config.get('auth.require_email_verification', False)
        self._initialized = False

    async def initialize(self):
        """Inizializza connessioni MongoDB - VERSIONE CORRETTA"""
        if self._initialized:
            return
            
        # Connetti agli adapter MongoDB
        await self.tenant_adapter.connect()
        await self.user_adapter.connect()
        
        # Carica dati esistenti in memoria
        await self._load_from_database()
        
        # Marca come inizializzato
        self._initialized = True
        logger.info("UserRegistrationService initialized with MongoDB")

    async def _load_from_database(self):
        """Carica tenant e user da MongoDB in memoria"""
        try:
            # Carica tenants
            tenant_entities = await self.tenant_adapter.query({})
            self.tenants.clear()
            for tenant in tenant_entities:
                self.tenants[tenant.tenant_id] = tenant
            
            # Carica users
            user_entities = await self.user_adapter.query({})
            self.jwt_provider.users.clear()
            self.jwt_provider.users_by_id.clear()
            for user in user_entities:
                self.jwt_provider.users[user.username] = user
                self.jwt_provider.users_by_id[user.user_id] = user
            
            logger.info(f"Loaded {len(self.tenants)} tenants and {len(self.jwt_provider.users)} users")
            
        except Exception as e:
            logger.error(f"Error loading from database: {e}")

    async def register_user(self, registration: UserRegistrationRequest) -> Dict[str, Any]:
        """Registra user con persistenza MongoDB"""
        if not self._initialized:
            await self.initialize()
            
        validation_errors = registration.validate()
        if validation_errors:
            raise ValidationError(f"Registration validation failed: {'; '.join(validation_errors)}")
        
        if await self._username_exists(registration.username):
            raise ValidationError(f"Username '{registration.username}' already exists")
        
        if await self._email_exists(registration.email):
            raise ValidationError(f"Email '{registration.email}' already registered")

        tenant = await self._create_tenant(registration)
        user = await self._create_user_with_tenant(registration, tenant)
        await self._setup_tenant_owner_permissions(user, tenant)

        if self.email_verification_enabled:
            verification_token = await self._create_verification_token(user)
            return {
                'status': 'pending_verification',
                'message': 'Please check your email to verify your account',
                'user_id': str(user.user_id),
                'tenant_id': str(tenant.tenant_id),
                'verification_required': True
            }
        else:
            return await self._complete_registration(user, tenant)

    async def _setup_tenant_owner_permissions(self, user: EnhancedUser, tenant: Tenant) -> None:
        """VERSIONE CORRETTA - usa custom_metadata invece di metadata"""
        
        # ✅ FIX: Usa custom_metadata invece di metadata
        user.custom_metadata['tenant_permissions'] = [
            'tenant:admin', 'digital_twin:*', 'service:*', 
            'replica:*', 'user:manage', 'billing:manage'
        ]
        
        # Aggiungi altre informazioni
        user.custom_metadata['is_tenant_owner'] = True
        user.custom_metadata['permissions_setup_completed'] = True
        user.custom_metadata['permissions_setup_at'] = datetime.now(timezone.utc).isoformat()
        
        # Salva le modifiche
        await self.user_adapter.save(user)

    async def _create_tenant(self, registration: UserRegistrationRequest) -> Tenant:
        """Crea tenant e salva su MongoDB"""
        tenant_id = uuid4()
        tenant_name = registration.company_name or f'{registration.first_name} {registration.last_name}'
        
        tenant = Tenant(
            tenant_id=tenant_id,
            name=tenant_name,
            plan=registration.plan,
            metadata={
                'created_by_email': registration.email,
                'registration_ip': 'unknown',
                'onboarding_completed': False
            }
        )
        
        # Salva su MongoDB
        await self.tenant_adapter.save(tenant)
        
        # Metti in cache
        self.tenants[tenant_id] = tenant
        
        logger.info(f'Created tenant {tenant_id} for {registration.email}')
        return tenant

    async def _create_user_with_tenant(self, registration: UserRegistrationRequest, tenant: Tenant) -> EnhancedUser:
        """Crea user e salva su MongoDB"""
        user_id = uuid4()
        password_hash = bcrypt.hashpw(registration.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        user = EnhancedUser(
            user_id=user_id,
            username=registration.username,
            email=registration.email,
            password_hash=password_hash,
            role=UserRole.ADMIN,
            tenant_id=tenant.tenant_id,
            first_name=registration.first_name,
            last_name=registration.last_name,
            metadata={
                'is_tenant_owner': True,
                'registration_source': 'direct',
                'onboarding_completed': False
            }
        )
        
        # Salva su MongoDB
        await self.user_adapter.save(user)
        
        # Metti in cache JWT provider
        self.jwt_provider.users[user.username] = user
        self.jwt_provider.users_by_id[user.user_id] = user
        
        # Aggiorna tenant
        tenant.created_by = user_id
        await self.tenant_adapter.save(tenant)
        
        logger.info(f'Created user {user_id} for tenant {tenant.tenant_id}')
        return user

    async def _complete_registration(self, user: EnhancedUser, tenant: Tenant) -> Dict[str, Any]:
        """Completa registrazione"""
        
        # Aggiorna metadata di completamento usando custom_metadata
        user.custom_metadata['registration_completed_at'] = datetime.now(timezone.utc).isoformat()
        user.custom_metadata['onboarding_completed'] = False
        
        # Salva l'utente aggiornato
        await self.user_adapter.save(user)
        
        # Genera token
        token_pair = await self.jwt_provider.generate_token_pair(user)
        
        return {
            'status': 'registration_complete',
            'message': 'Welcome to Digital Twin Platform!',
            'user_id': str(user.user_id),
            'tenant_id': str(tenant.tenant_id),
            'verification_required': False,
            'user': user.to_dict(),
            'tenant': tenant.to_dict(),
            'tokens': token_pair.to_dict()
        }

    async def get_tenant_info(self, tenant_id: UUID) -> Dict[str, Any]:
        """Get tenant con fallback al database"""
        if not self._initialized:
            await self.initialize()
            
        # Prima cerca in memoria
        tenant = self.tenants.get(tenant_id)
        
        # Se non trovato, cerca nel database
        if not tenant:
            try:
                tenant_entities = await self.tenant_adapter.query({'entity_id': str(tenant_id)})
                if tenant_entities:
                    tenant = tenant_entities[0]
                    self.tenants[tenant_id] = tenant  # Metti in cache
                else:
                    raise ValidationError('Tenant not found')
            except Exception as e:
                logger.error(f"Error getting tenant: {e}")
                raise ValidationError('Tenant not found')
        
        user_count = await self._count_tenant_users(tenant_id)
        twin_count = await self._count_tenant_digital_twins(tenant_id)
        
        return {
            **tenant.to_dict(),
            'usage': {
                'users': user_count,
                'digital_twins': twin_count,
                'storage_used_gb': 0
            },
            'limits': {
                'users_remaining': tenant.settings['max_users'] - user_count if tenant.settings['max_users'] != -1 else -1,
                'twins_remaining': tenant.settings['max_digital_twins'] - twin_count if tenant.settings['max_digital_twins'] != -1 else -1
            }
        }

    async def _username_exists(self, username: str) -> bool:
        """Check username in database"""
        try:
            user_entities = await self.user_adapter.query({'username': username.lower().strip()})
            return len(user_entities) > 0
        except:
            return username.lower().strip() in self.jwt_provider.users

    async def _email_exists(self, email: str) -> bool:
        """Check email in database"""
        try:
            user_entities = await self.user_adapter.query({'email': email.lower().strip()})
            return len(user_entities) > 0
        except:
            return any(user.email == email.lower().strip() for user in self.jwt_provider.users.values())

    async def _create_verification_token(self, user: EnhancedUser) -> str:
        return secrets.token_urlsafe(32)

    async def _get_user_from_verification_token(self, token: str) -> Optional[UUID]:
        return uuid4()

    async def _count_tenant_users(self, tenant_id: UUID) -> int:
        try:
            user_entities = await self.user_adapter.query({'tenant_id': str(tenant_id)})
            return len(user_entities)
        except:
            return len([u for u in self.jwt_provider.users.values() 
                       if hasattr(u, 'tenant_id') and u.tenant_id == tenant_id])

    async def _count_tenant_digital_twins(self, tenant_id: UUID) -> int:
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
    
class TenantWrapper(IEntity):
    """Wrapper for existing Tenant class to work with MongoDB"""
    
    def __init__(self, tenant_data: 'Tenant' = None, **kwargs):
        if tenant_data:
            # Initialize from existing Tenant object
            self._id = tenant_data.tenant_id
            self.tenant_data = tenant_data
            self._metadata = BaseMetadata(
                entity_id=tenant_data.tenant_id,
                timestamp=tenant_data.created_at,
                version='1.0.0',
                created_by=tenant_data.created_by or tenant_data.tenant_id,
                custom={
                    'name': tenant_data.name,
                    'plan': tenant_data.plan,
                    'created_by': str(tenant_data.created_by) if tenant_data.created_by else None,
                    'created_at': tenant_data.created_at.isoformat(),
                    'is_active': tenant_data.is_active,
                    'settings': tenant_data.settings,
                    'metadata': tenant_data.metadata
                }
            )
        else:
            # Initialize from kwargs (loading from MongoDB)
            self._id = kwargs.get('entity_id') or kwargs.get('tenant_id')
            custom_data = kwargs.get('custom', kwargs)
            self._metadata = BaseMetadata(
                entity_id=self._id,
                timestamp=datetime.fromisoformat(custom_data.get('created_at', datetime.now(timezone.utc).isoformat())),
                version=kwargs.get('version', '1.0.0'),
                created_by=UUID(custom_data.get('created_by')) if custom_data.get('created_by') else self._id,
                custom=custom_data
            )
            # Recreate Tenant object from stored data
            self.tenant_data = Tenant(
                tenant_id=self._id,
                name=custom_data.get('name', 'Unknown'),
                plan=custom_data.get('plan', 'free'),
                created_by=UUID(custom_data.get('created_by')) if custom_data.get('created_by') else None,
                metadata=custom_data.get('metadata', {})
            )
            self.tenant_data.created_at = datetime.fromisoformat(custom_data.get('created_at', datetime.now(timezone.utc).isoformat()))
            self.tenant_data.is_active = custom_data.get('is_active', True)
            self.tenant_data.settings = custom_data.get('settings', {})
        
        self._status = EntityStatus.ACTIVE
        self._entity_type = 'tenant'

    @property
    def id(self) -> UUID:
        return self._id

    @property
    def metadata(self) -> BaseMetadata:
        return self._metadata

    @property
    def status(self) -> EntityStatus:
        return self._status

    @property
    def entity_type(self) -> str:
        return self._entity_type

    def get_tenant(self) -> 'Tenant':
        """Get the wrapped Tenant object"""
        return self.tenant_data

    async def initialize(self) -> None:
        self._status = EntityStatus.ACTIVE

    async def start(self) -> None:
        self.is_active = True

    async def stop(self) -> None:
        self.is_active = False

    def validate(self) -> bool:
        return bool(self.tenant_data.name and self.tenant_data.name.strip() and 
                   self.tenant_data.plan in ['free', 'pro', 'enterprise'])

class UserWrapper(IEntity):
    """Wrapper for existing EnhancedUser class to work with MongoDB"""
    
    def __init__(self, user_data: 'EnhancedUser' = None, **kwargs):
        if user_data:
            # Initialize from existing EnhancedUser object
            self._id = user_data.user_id
            self.user_data = user_data
            self._metadata = BaseMetadata(
                entity_id=user_data.user_id,
                timestamp=user_data.created_at or datetime.now(timezone.utc),
                version='1.0.0',
                created_by=user_data.user_id,
                custom={
                    'username': user_data.username,
                    'email': user_data.email,
                    'password_hash': user_data.password_hash,
                    'role': user_data.role,
                    'tenant_id': str(user_data.tenant_id),
                    'first_name': user_data.first_name,
                    'last_name': user_data.last_name,
                    'is_active': user_data.is_active,
                    'created_at': (user_data.created_at or datetime.now(timezone.utc)).isoformat(),
                    'last_login': user_data.last_login.isoformat() if user_data.last_login else None,
                    'metadata': user_data.metadata
                }
            )
        else:
            # Initialize from kwargs (loading from MongoDB)
            self._id = kwargs.get('entity_id') or kwargs.get('user_id')
            custom_data = kwargs.get('custom', kwargs)
            self._metadata = BaseMetadata(
                entity_id=self._id,
                timestamp=datetime.fromisoformat(custom_data.get('created_at', datetime.now(timezone.utc).isoformat())),
                version=kwargs.get('version', '1.0.0'),
                created_by=self._id,
                custom=custom_data
            )
            # Recreate EnhancedUser object from stored data
            self.user_data = EnhancedUser(
                user_id=self._id,
                username=custom_data.get('username'),
                email=custom_data.get('email'),
                password_hash=custom_data.get('password_hash'),
                role=custom_data.get('role'),
                tenant_id=UUID(custom_data.get('tenant_id')),
                first_name=custom_data.get('first_name'),
                last_name=custom_data.get('last_name'),
                is_active=custom_data.get('is_active', True),
                metadata=custom_data.get('metadata', {}),
                created_at=datetime.fromisoformat(custom_data.get('created_at', datetime.now(timezone.utc).isoformat())),
                last_login=datetime.fromisoformat(custom_data.get('last_login')) if custom_data.get('last_login') else None
            )
        
        self._status = EntityStatus.ACTIVE if self.user_data.is_active else EntityStatus.INACTIVE
        self._entity_type = 'user'

    @property
    def id(self) -> UUID:
        return self._id

    @property
    def metadata(self) -> BaseMetadata:
        return self._metadata

    @property
    def status(self) -> EntityStatus:
        return self._status

    @property
    def entity_type(self) -> str:
        return self._entity_type

    def get_user(self) -> 'EnhancedUser':
        """Get the wrapped EnhancedUser object"""
        return self.user_data

    async def initialize(self) -> None:
        self._status = EntityStatus.ACTIVE if self.user_data.is_active else EntityStatus.INACTIVE

    async def start(self) -> None:
        self.user_data.is_active = True
        self._status = EntityStatus.ACTIVE

    async def stop(self) -> None:
        self.user_data.is_active = False
        self._status = EntityStatus.INACTIVE

    def validate(self) -> bool:
        import re
        if len(self.user_data.username) < 3:
            return False
        if not self.user_data.username.replace('_', '').replace('-', '').isalnum():
            return False
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, self.user_data.email):
            return False
        if not self.user_data.first_name or not self.user_data.last_name:
            return False
        return True