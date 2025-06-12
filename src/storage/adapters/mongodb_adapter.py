import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypeVar, Generic, Type
from uuid import UUID
import json

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure, DuplicateKeyError
from bson import ObjectId
from src.utils.entity_wrapper import DictToObjectWrapper

from src.core.interfaces.base import IStorageAdapter, IEntity, BaseMetadata
from src.utils.exceptions import StorageError, StorageConnectionError, DataPersistenceError, EntityNotFoundError
from src.utils.config import get_config

T = TypeVar('T', bound=IEntity)
logger = logging.getLogger(__name__)

class EntitySerializer:
    """Serializes/deserializes entities to/from MongoDB documents."""
    
    @staticmethod
    def entity_to_document(entity) -> Dict[str, Any]:
        """Convert entity to MongoDB document with type-specific handling."""
        try:
            # Handle User/EnhancedUser specifically
            if hasattr(entity, 'password_hash') and hasattr(entity, 'username'):
                return EntitySerializer._serialize_user(entity)
            
            # Handle Tenant specifically
            if hasattr(entity, 'tenant_id') and hasattr(entity, 'plan'):
                return EntitySerializer._serialize_tenant(entity)
            
            # Handle generic entities
            if hasattr(entity, 'to_dict'):
                doc = entity.to_dict()
            else:
                doc = EntitySerializer._serialize_generic_entity(entity)
            
            # Ensure entity_id and entity_type are set
            doc['entity_id'] = str(entity.id)
            doc['entity_type'] = entity.__class__.__name__
            
            return doc
            
        except Exception as e:
            logger.error(f"Entity serialization failed: {e}")
            raise DataPersistenceError(f"Entity serialization failed: {e}")
    

    @staticmethod
    def _serialize_user(entity) -> Dict[str, Any]:
        """Serialize User/EnhancedUser objects."""
        try:
            return {
                'entity_id': str(entity.user_id),
                'entity_type': 'EnhancedUser',
                'user_id': str(entity.user_id),
                'username': entity.username,
                'email': entity.email,
                'password_hash': entity.password_hash,  # CRUCIALE!
                'role': entity.role,
                'tenant_id': str(getattr(entity, 'tenant_id', '')),
                'first_name': getattr(entity, 'first_name', ''),
                'last_name': getattr(entity, 'last_name', ''),
                'is_active': entity.is_active,
                'created_at': entity.created_at.isoformat() if entity.created_at else None,
                'last_login': entity.last_login.isoformat() if entity.last_login else None,
                'metadata': getattr(entity, 'custom_metadata', getattr(entity, 'metadata', {}))
            }
        except Exception as e:
            logger.error(f"Failed to serialize User: {e}")
            raise
    @staticmethod
    def _serialize_tenant(entity) -> Dict[str, Any]:
        """Serialize Tenant objects."""
        try:
            return {
                'entity_id': str(entity.tenant_id),
                'entity_type': 'Tenant',
                'tenant_id': str(entity.tenant_id),
                'name': entity.name,
                'plan': entity.plan,
                'created_by': str(entity.created_by) if entity.created_by else None,
                'created_at': entity.created_at.isoformat() if entity.created_at else None,
                'is_active': entity.is_active,
                'settings': getattr(entity, 'settings', {}),
                'metadata': getattr(entity, 'custom_metadata', {})
            }
        except Exception as e:
            logger.error(f"Failed to serialize Tenant: {e}")
            raise
    
    @staticmethod
    def _serialize_generic_entity(entity) -> Dict[str, Any]:
        """Serialize generic entities."""
        return {
            'entity_id': str(entity.id),
            'entity_type': entity.__class__.__name__,
            'metadata': entity.metadata.to_dict() if hasattr(entity.metadata, 'to_dict') else {},
            'status': entity.status.value if hasattr(entity.status, 'value') else str(entity.status)
        }

    @staticmethod
    def document_to_entity_dict(doc: Dict[str, Any], entity_class: Type[T]) -> Dict[str, Any]:
        """Convert MongoDB document back to entity dict."""
        try:
            # Remove MongoDB internal fields
            entity_dict = {k: v for k, v in doc.items() if not k.startswith('_')}
            
            # Ensure required fields
            if 'entity_id' not in entity_dict and 'id' in entity_dict:
                entity_dict['entity_id'] = entity_dict['id']
            elif 'id' not in entity_dict and 'entity_id' in entity_dict:
                entity_dict['id'] = entity_dict['entity_id']
            
            return entity_dict
            
        except Exception as e:
            logger.error(f"Failed to convert document to entity dict: {e}")
            raise DataPersistenceError(f"Document conversion failed: {e}")


    @staticmethod
    def _convert_uuids_to_strings(obj: Any) -> Any:
        """Recursively convert UUID objects to strings."""
        if isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, dict):
            return {key: EntitySerializer._convert_uuids_to_strings(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [EntitySerializer._convert_uuids_to_strings(item) for item in obj]
        return obj
    
    @staticmethod
    def _convert_strings_to_uuids(obj: Any) -> Any:
        """Recursively convert string UUIDs back to UUID objects where appropriate."""
        if isinstance(obj, dict):
            converted = {}
            for key, value in obj.items():
                # Convert known UUID fields
                if key in ['id', 'entity_id', 'parent_digital_twin_id', 'digital_twin_id', 'service_id', 'replica_id'] and isinstance(value, str):
                    try:
                        converted[key] = UUID(value)
                    except ValueError:
                        converted[key] = value
                else:
                    converted[key] = EntitySerializer._convert_strings_to_uuids(value)
            return converted
        elif isinstance(obj, list):
            return [EntitySerializer._convert_strings_to_uuids(item) for item in obj]
        return obj
    @staticmethod
    def deserialize_entity(doc: Dict[str, Any], entity_class: Type[T]) -> T:
        """
        Deserialize MongoDB document to proper entity object.
        This is the KEY method that fixes the wrapper issue.
        """
        try:
            entity_type = doc.get('entity_type', entity_class.__name__)
            
            # SPECIFIC DESERIALIZATION FOR USER TYPES
            if entity_type in ['EnhancedUser', 'User'] or 'password_hash' in doc:
                return EntitySerializer._deserialize_user(doc, entity_class)
            
            # SPECIFIC DESERIALIZATION FOR TENANT
            if entity_type == 'Tenant' or 'tenant_id' in doc:
                return EntitySerializer._deserialize_tenant(doc, entity_class)
            
            # GENERIC DESERIALIZATION
            return EntitySerializer._deserialize_generic(doc, entity_class)
            
        except Exception as e:
            logger.error(f"Failed to deserialize entity: {e}")
            # Fallback to wrapper
            entity_dict = EntitySerializer.document_to_entity_dict(doc, entity_class)
            return DictToObjectWrapper(entity_dict)

    @staticmethod
    def _deserialize_user(doc: Dict[str, Any], entity_class: Type[T]) -> T:
        """Deserialize user document to EnhancedUser object."""
        try:
            from src.layers.application.auth.user_registration import EnhancedUser
            from datetime import datetime, timezone
            from uuid import UUID
            
            # Extract and convert data
            user_id = UUID(doc['user_id']) if isinstance(doc['user_id'], str) else doc['user_id']
            tenant_id = UUID(doc.get('tenant_id', '00000000-0000-0000-0000-000000000000'))
            
            # Parse dates safely
            created_at = None
            if doc.get('created_at'):
                try:
                    created_at = datetime.fromisoformat(doc['created_at'].replace('Z', '+00:00'))
                except:
                    created_at = datetime.now(timezone.utc)
            
            last_login = None
            if doc.get('last_login'):
                try:
                    last_login = datetime.fromisoformat(doc['last_login'].replace('Z', '+00:00'))
                except:
                    last_login = None
            
            # Create real EnhancedUser object
            user = EnhancedUser(
                user_id=user_id,
                username=doc['username'],
                email=doc['email'],
                password_hash=doc['password_hash'],  # THIS IS THE KEY FIX!
                role=doc.get('role', 'viewer'),
                tenant_id=tenant_id,
                first_name=doc.get('first_name', ''),
                last_name=doc.get('last_name', ''),
                is_active=doc.get('is_active', True),
                metadata=doc.get('metadata', {}),
                created_at=created_at,
                last_login=last_login
            )
            
            logger.debug(f"Successfully deserialized user: {user.username}")
            return user
            
        except Exception as e:
            logger.error(f"Failed to deserialize user: {e}")
            # Fallback to wrapper
            entity_dict = EntitySerializer.document_to_entity_dict(doc, entity_class)
            return DictToObjectWrapper(entity_dict)

    @staticmethod
    def _deserialize_tenant(doc: Dict[str, Any], entity_class: Type[T]) -> T:
        """Deserialize tenant document to Tenant object."""
        try:
            from src.layers.application.auth.user_registration import Tenant
            from datetime import datetime, timezone
            from uuid import UUID
            
            tenant_id = UUID(doc['tenant_id']) if isinstance(doc['tenant_id'], str) else doc['tenant_id']
            created_by = UUID(doc['created_by']) if doc.get('created_by') else None
            
            created_at = None
            if doc.get('created_at'):
                try:
                    created_at = datetime.fromisoformat(doc['created_at'].replace('Z', '+00:00'))
                except:
                    created_at = datetime.now(timezone.utc)
            
            tenant = Tenant(
                tenant_id=tenant_id,
                name=doc['name'],
                plan=doc.get('plan', 'free'),
                created_by=created_by,
                created_at=created_at,
                is_active=doc.get('is_active', True),
                settings=doc.get('settings', {}),
                metadata=doc.get('metadata', {})
            )
            
            return tenant
            
        except Exception as e:
            logger.error(f"Failed to deserialize tenant: {e}")
            entity_dict = EntitySerializer.document_to_entity_dict(doc, entity_class)
            return DictToObjectWrapper(entity_dict)

    @staticmethod
    def _deserialize_generic(doc: Dict[str, Any], entity_class: Type[T]) -> T:
        """Deserialize generic entity."""
        try:
            # Try to use from_dict if available
            if hasattr(entity_class, 'from_dict'):
                entity_dict = EntitySerializer.document_to_entity_dict(doc, entity_class)
                return entity_class.from_dict(entity_dict)
            
            # Fallback to wrapper
            entity_dict = EntitySerializer.document_to_entity_dict(doc, entity_class)
            return DictToObjectWrapper(entity_dict)
            
        except Exception as e:
            logger.error(f"Failed to deserialize generic entity: {e}")
            entity_dict = EntitySerializer.document_to_entity_dict(doc, entity_class)
            return DictToObjectWrapper(entity_dict)

class MongoStorageAdapter(IStorageAdapter[T], Generic[T]):
    """MongoDB storage adapter with support for separate databases per Digital Twin."""
    
    def __init__(self, entity_type: Type[T], twin_id: Optional[UUID] = None):
        self.entity_type = entity_type
        self.twin_id = twin_id
        self.config = get_config()
        
        # MongoDB connection details
        self._client: Optional[AsyncIOMotorClient] = None
        self._database: Optional[AsyncIOMotorDatabase] = None
        self._collection: Optional[AsyncIOMotorCollection] = None
        self._connected = False
        
        # Determine database and collection names
        self._db_name = self._get_database_name()
        self._collection_name = self._get_collection_name()
        
        logger.info(f"MongoDB adapter initialized for {entity_type.__name__} (DB: {self._db_name})")

    def _get_database_name(self) -> str:
        """Get database name based on configuration."""
        if self.config.get('storage.separate_dbs_per_twin', False) and self.twin_id:
            return f"dt_twin_{str(self.twin_id).replace('-', '_')}"
        return self.config.get('storage.mongodb.database', 'dt_platform_global')
    
    @property
    def storage_type(self) -> str:
        """Return the storage type identifier"""
        return "mongodb"
    def _get_database_name(self) -> str:
        """Get database name based on entity type and twin_id."""
        prefix = self.config.get('mongodb.database_prefix', 'dt_platform')
        
        if self.config.get('storage.separate_dbs_per_twin', True) and self.twin_id:
            # Separate database per Digital Twin for migration support
            return f"{prefix}_dt_{str(self.twin_id).replace('-', '_')}"
        else:
            # Global database for system entities
            return self.config.get('mongodb.global_database', 'dt_platform_global')
    
    def _get_collection_name(self) -> str:
        """Get collection name based on entity type."""
        entity_name = self.entity_type.__name__.lower()
        
        # Map entity types to collection names
        collection_mapping = {
            'digitaltwin': 'digital_twins',
            'digitalreplica': 'digital_replicas', 
            'standarddigitalreplica': 'digital_replicas',
            'service': 'services',
            'standardservice': 'services',
            'user': 'users',
            'apikey': 'api_keys'
        }
        
        return collection_mapping.get(entity_name, f"{entity_name}s")
    
    def _get_connection_string(self) -> str:
        """Build MongoDB connection string."""
        base_uri = self.config.get('mongodb.connection_string', 'mongodb://localhost:27017')
        username = self.config.get('mongodb.username')
        password = self.config.get('mongodb.password')
        auth_source = self.config.get('mongodb.auth_source', 'admin')
        
        if username and password:
            # Insert credentials into URI
            if '://' in base_uri:
                protocol, rest = base_uri.split('://', 1)
                return f"{protocol}://{username}:{password}@{rest}?authSource={auth_source}"
        
        return base_uri
    
    async def connect(self) -> None:
        """Connect to MongoDB."""
        if self._connected:
            return
            
        try:
            # MongoDB connection
            connection_string = self.config.get(
                'storage.mongodb.connection_string',
                'mongodb://localhost:27017'
            )
            
            self._client = AsyncIOMotorClient(connection_string)
            self._database = self._client[self._db_name]
            self._collection = self._database[self._collection_name]
            
            # Test connection
            await self._client.admin.command('ping')
            await self._ensure_indexes()
            
            self._connected = True
            logger.info(f"Connected to MongoDB: {self._db_name}.{self._collection_name}")
            
        except (ServerSelectionTimeoutError, ConnectionFailure) as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise StorageConnectionError(f"MongoDB connection failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error connecting to MongoDB: {e}")
            raise StorageError(f"MongoDB connection error: {e}")

    async def disconnect(self) -> None:
        """Close MongoDB connection."""
        if self._client:
            self._client.close()
            self._connected = False
            logger.info("Disconnected from MongoDB")
    
    async def _ensure_indexes(self) -> None:
        """Create necessary indexes for performance."""
        try:
            await self._collection.create_index("entity_id", unique=True)
            await self._collection.create_index("entity_type")
            await self._collection.create_index("created_at")
            
            # User-specific indexes
            if 'user' in self._collection_name:
                await self._collection.create_index("username", unique=True)
                await self._collection.create_index("email", unique=True)
                await self._collection.create_index("tenant_id")
            
            logger.debug(f"Indexes ensured for {self._collection_name}")
            
        except Exception as e:
            logger.warning(f"Failed to create indexes: {e}")


    
    async def save(self, entity: T) -> None:
        """Save entity to MongoDB."""
        if not self._connected:
            await self.connect()
        
        try:
            document = EntitySerializer.entity_to_document(entity)
            
            # Use upsert to handle both insert and update
            result = await self._collection.replace_one(
                {"entity_id": str(entity.id)},
                document,
                upsert=True
            )
            
            if result.upserted_id:
                logger.debug(f"Inserted entity {entity.id} into {self._collection_name}")
            else:
                logger.debug(f"Updated entity {entity.id} in {self._collection_name}")
                
        except DuplicateKeyError as e:
            logger.error(f"Duplicate entity {entity.id}: {e}")
            raise DataPersistenceError(f"Entity {entity.id} already exists")
        except Exception as e:
            logger.error(f"Failed to save entity {entity.id}: {e}")
            raise DataPersistenceError(f"Save operation failed: {e}")

    async def load(self, entity_id: UUID) -> T:
        """Load entity from MongoDB with proper deserialization."""
        if not self._connected:
            await self.connect()
        
        try:
            document = await self._collection.find_one({'entity_id': str(entity_id)})
            if not document:
                raise EntityNotFoundError(self.entity_type.__name__, str(entity_id))
            
            # USE THE NEW DESERIALIZER - THIS IS THE KEY FIX!
            entity = EntitySerializer.deserialize_entity(document, self.entity_type)
            
            logger.debug(f'Loaded entity {entity_id} from {self._collection_name}')
            return entity
            
        except EntityNotFoundError:
            raise
        except Exception as e:
            logger.error(f'Failed to load entity {entity_id}: {e}')
            raise StorageError(f'Load operation failed: {e}')


    def _deserialize_entity(self, entity_dict: Dict[str, Any]) -> T:
        """Deserialize entity dict to proper object type"""
        entity_type_name = self.entity_type.__name__
        
        try:
            if entity_type_name == 'EnhancedUser' or 'user_id' in entity_dict:
                return self._deserialize_user(entity_dict)  # ← Questo crea un vero EnhancedUser!
            elif entity_type_name == 'Tenant' or 'tenant_id' in entity_dict:
                return self._deserialize_tenant(entity_dict)
            else:
                from src.utils.entity_wrapper import DictToObjectWrapper
                return DictToObjectWrapper(entity_dict)
                
        except Exception as e:
            logger.error(f"Failed to deserialize {entity_type_name}: {e}")
            # Fallback a wrapper generico
            from src.utils.entity_wrapper import DictToObjectWrapper
            return DictToObjectWrapper(entity_dict)
    
    
    def _deserialize_user(self, user_dict: Dict[str, Any]) -> 'EnhancedUser':
        """Deserialize user data to EnhancedUser object"""
        from src.layers.application.auth.user_registration import EnhancedUser
        from datetime import datetime, timezone
        from uuid import UUID
        
        # Estrai i dati necessari
        user_id = UUID(user_dict['user_id']) if isinstance(user_dict['user_id'], str) else user_dict['user_id']
        tenant_id = UUID(user_dict['tenant_id']) if isinstance(user_dict['tenant_id'], str) else user_dict['tenant_id']
        
        # Parse date strings
        created_at = None
        if user_dict.get('created_at'):
            try:
                created_at = datetime.fromisoformat(user_dict['created_at'].replace('Z', '+00:00'))
            except:
                created_at = datetime.now(timezone.utc)
        
        last_login = None
        if user_dict.get('last_login'):
            try:
                last_login = datetime.fromisoformat(user_dict['last_login'].replace('Z', '+00:00'))
            except:
                last_login = None
        
        # Crea oggetto EnhancedUser REALE con password_hash!
        user = EnhancedUser(
            user_id=user_id,
            username=user_dict['username'],
            email=user_dict['email'],
            password_hash=user_dict['password_hash'],  # ← QUESTO È CRUCIALE e funziona già!
            role=user_dict.get('role', 'viewer'),
            tenant_id=tenant_id,
            first_name=user_dict.get('first_name', ''),
            last_name=user_dict.get('last_name', ''),
            is_active=user_dict.get('is_active', True),
            metadata=user_dict.get('metadata', {}),
            created_at=created_at,
            last_login=last_login
        )
        
        logger.debug(f"Successfully deserialized user: {user.username}")
        return user

    def _deserialize_tenant(self, tenant_dict: Dict[str, Any]) -> 'Tenant':
        """Deserialize tenant data to Tenant object"""
        from src.layers.application.auth.user_registration import Tenant
        from datetime import datetime, timezone
        from uuid import UUID
        
        tenant_id = UUID(tenant_dict['tenant_id']) if isinstance(tenant_dict['tenant_id'], str) else tenant_dict['tenant_id']
        
        # Parse created_by UUID
        created_by = None
        if tenant_dict.get('created_by'):
            try:
                created_by = UUID(tenant_dict['created_by'])
            except:
                created_by = None
        
        # Parse created_at
        created_at = datetime.now(timezone.utc)
        if tenant_dict.get('created_at'):
            try:
                created_at = datetime.fromisoformat(tenant_dict['created_at'].replace('Z', '+00:00'))
            except:
                pass
        
        # Crea oggetto Tenant
        tenant = Tenant(
            tenant_id=tenant_id,
            name=tenant_dict['name'],
            plan=tenant_dict.get('plan', 'free'),
            created_by=created_by,
            metadata=tenant_dict.get('metadata', {})
        )
        
        tenant.created_at = created_at
        tenant.is_active = tenant_dict.get('is_active', True)
        tenant.settings = tenant_dict.get('settings', tenant._get_plan_limits(tenant.plan))
        
        return tenant
    
    async def delete(self, entity_id: UUID) -> None:
        """Delete entity from MongoDB."""
        if not self._connected:
            await self.connect()
        
        try:
            result = await self._collection.delete_one({"entity_id": str(entity_id)})
            
            if result.deleted_count == 0:
                raise EntityNotFoundError(self.entity_type.__name__, str(entity_id))
            
            logger.debug(f"Deleted entity {entity_id} from {self._collection_name}")
            
        except EntityNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to delete entity {entity_id}: {e}")
            raise StorageError(f"Delete operation failed: {e}")


    async def query(self, filters: Dict[str, Any], **kwargs) -> List[T]:
        """Query entities from MongoDB with proper deserialization"""
        if not self._connected:
            await self.connect()
        
        try:
            mongo_filter = self._build_mongo_filter(filters)
            cursor = self._collection.find(mongo_filter)
            
            # Handle pagination safely
            limit_param = kwargs.get('limit')
            offset_param = kwargs.get('offset')
            
            offset_value = 0
            if offset_param is not None:
                try:
                    offset_value = max(0, int(offset_param))
                except (ValueError, TypeError):
                    offset_value = 0
            
            limit_value = None
            if limit_param is not None:
                try:
                    limit_int = int(limit_param)
                    limit_value = limit_int if limit_int > 0 else None
                except (ValueError, TypeError):
                    limit_value = None
            
            if offset_value > 0:
                cursor = cursor.skip(offset_value)
            
            if limit_value is not None:
                cursor = cursor.limit(limit_value)
            
            documents = await cursor.to_list(length=limit_value)
            
            entities = []
            for doc in documents:
                try:
                    entity_dict = EntitySerializer.document_to_entity_dict(doc, self.entity_type)
                    
                    # *** QUESTA È LA RIGA CRUCIALE CHE DEVE CAMBIARE ***
                    entity = self._deserialize_entity(entity_dict)  # NON DictToObjectWrapper!
                    entities.append(entity)
                    
                except Exception as e:
                    logger.warning(f"Failed to deserialize entity: {e}")
                    continue
                    
            logger.debug(f'Queried {len(entities)} entities from {self._collection_name}')
            return entities
            
        except Exception as e:
            logger.error(f'Failed to query entities: {e}')
            raise StorageError(f'Query operation failed: {e}')
    
    def _build_mongo_filter(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Convert generic filters to MongoDB query."""
        mongo_filter = {}
        
        for key, value in filters.items():
            if key == 'id':
                mongo_filter['entity_id'] = str(value)
            elif isinstance(value, UUID):
                mongo_filter[key] = str(value)
            else:
                mongo_filter[key] = value
        
        return mongo_filter

    async def health_check(self) -> bool:
        """Check MongoDB connection health."""
        try:
            if not self._connected:
                return False
            
            await self._client.admin.command('ping')
            return True
            
        except Exception as e:
            logger.error(f"MongoDB health check failed: {e}")
            return False

class MongoStorageAdapterFactory:
    """Factory for creating MongoDB storage adapters."""
    
    @staticmethod
    def create_adapter(entity_type: Type[T], twin_id: Optional[UUID] = None) -> MongoStorageAdapter[T]:
        """Create MongoDB storage adapter for given entity type."""
        return MongoStorageAdapter(entity_type, twin_id)
    
    @staticmethod
    def create_global_adapter(entity_type: Type[T]) -> MongoStorageAdapter[T]:
        """Create adapter for global entities (users, api keys, etc.)."""
        return MongoStorageAdapter(entity_type, twin_id=None)
    
    @staticmethod
    def create_twin_adapter(entity_type: Type[T], twin_id: UUID) -> MongoStorageAdapter[T]:
        """Create adapter for twin-specific entities (replicas, services)."""
        return MongoStorageAdapter(entity_type, twin_id=twin_id)
    
