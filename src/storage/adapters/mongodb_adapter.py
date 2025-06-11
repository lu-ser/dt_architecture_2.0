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
    def entity_to_document(entity: IEntity) -> Dict[str, Any]:
        """Convert entity to MongoDB document with proper type detection."""
        try:
            # Identificazione sicura del tipo di entità
            entity_class_name = entity.__class__.__name__
            
            # Gestione specifica per tipo di entità
            if entity_class_name == 'Tenant' or 'Tenant' in str(type(entity)):
                doc = EntitySerializer._serialize_tenant(entity)
            elif entity_class_name == 'EnhancedUser' or hasattr(entity, 'user_id'):
                doc = EntitySerializer._serialize_user(entity)
            elif hasattr(entity, 'to_dict'):
                # Fallback per altre entità che hanno to_dict
                doc = entity.to_dict()
            else:
                # Fallback generico
                doc = EntitySerializer._serialize_generic_entity(entity)
            
            # Campi comuni MongoDB
            doc['_id'] = str(entity.id)
            doc['entity_id'] = str(entity.id)
            doc['entity_type'] = entity_class_name
            doc['serialized_at'] = datetime.now(timezone.utc).isoformat()
            
            # Convert UUIDs to strings per MongoDB
            doc = EntitySerializer._convert_uuids_to_strings(doc)
            
            return doc
            
        except Exception as e:
            logger.error(f"Failed to serialize entity {entity.id} of type {type(entity)}: {e}")
            raise DataPersistenceError(f"Entity serialization failed: {e}")
    

    @staticmethod
    def _serialize_user(entity) -> Dict[str, Any]:
        """Serializza specificamente oggetti User/EnhancedUser"""
        try:
            # Se ha to_dict, usalo
            if hasattr(entity, 'to_dict'):
                return entity.to_dict()
            
            # Altrimenti serializza manualmente
            return {
                'user_id': str(entity.user_id),
                'username': entity.username,
                'email': entity.email,
                'password_hash': entity.password_hash,
                'role': entity.role,
                'tenant_id': str(entity.tenant_id),
                'first_name': entity.first_name,
                'last_name': entity.last_name,
                'is_active': entity.is_active,
                'created_at': entity.created_at.isoformat(),
                'last_login': entity.last_login.isoformat() if entity.last_login else None,
                'metadata': getattr(entity, 'custom_metadata', {})
            }
        except Exception as e:
            logger.error(f"Failed to serialize User: {e}")
            raise

    @staticmethod
    def _serialize_tenant(entity) -> Dict[str, Any]:
        """Serializza specificamente oggetti Tenant"""
        try:
            # Se ha to_dict, usalo
            if hasattr(entity, 'to_dict'):
                return entity.to_dict()
            
            # Altrimenti serializza manualmente
            return {
                'tenant_id': str(entity.tenant_id),
                'name': entity.name,
                'plan': entity.plan,
                'created_by': str(entity.created_by) if entity.created_by else None,
                'created_at': entity.created_at.isoformat(),
                'is_active': entity.is_active,
                'settings': getattr(entity, 'settings', {}),
                'metadata': getattr(entity, 'custom_metadata', {})
            }
        except Exception as e:
            logger.error(f"Failed to serialize Tenant: {e}")
            raise
    @staticmethod
    def _serialize_generic_entity(entity) -> Dict[str, Any]:
        """Serializza entità generiche"""
        return {
            'id': str(entity.id),
            'metadata': entity.metadata.to_dict() if hasattr(entity.metadata, 'to_dict') else {},
            'status': entity.status.value if hasattr(entity.status, 'value') else str(entity.status),
            'entity_type': entity.__class__.__name__
        }

    @staticmethod
    def document_to_entity_dict(doc: Dict[str, Any], entity_class: Type[T]) -> Dict[str, Any]:
        """Convert MongoDB document back to entity dict."""
        try:
            # Remove MongoDB _id field
            if '_id' in doc:
                del doc['_id']
            
            # Convert string UUIDs back to UUID objects where needed
            doc = EntitySerializer._convert_strings_to_uuids(doc)
            
            return doc
            
        except Exception as e:
            logger.error(f"Failed to deserialize document: {e}")
            raise StorageError(f"Document deserialization failed: {e}")
    
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


class MongoStorageAdapter(IStorageAdapter[T], Generic[T]):
    """MongoDB storage adapter with support for separate databases per Digital Twin."""
    
    def __init__(self, entity_type: Type[T], twin_id: Optional[UUID] = None):
        self.entity_type = entity_type
        self.twin_id = twin_id
        self.config = get_config()
        
        # MongoDB client and database
        self._client: Optional[AsyncIOMotorClient] = None
        self._database: Optional[AsyncIOMotorDatabase] = None
        self._collection: Optional[AsyncIOMotorCollection] = None
        self._connected = False
        
        # Database and collection names
        self._database_name = self._get_database_name()
        self._collection_name = self._get_collection_name()
        
        logger.info(f"MongoDB adapter initialized for {entity_type.__name__} (DB: {self._database_name})")
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
        """Establish connection to MongoDB."""
        if self._connected:
            return
        
        try:
            # Create MongoDB client
            connection_string = self._get_connection_string()
            
            self._client = AsyncIOMotorClient(
                connection_string,
                maxPoolSize=self.config.get('mongodb.max_pool_size', 50),
                minPoolSize=self.config.get('mongodb.pool_size', 10),
                serverSelectionTimeoutMS=self.config.get('mongodb.timeout_ms', 5000),
                retryWrites=self.config.get('mongodb.retry_writes', True)
            )
            
            # Get database and collection
            self._database = self._client[self._database_name]
            self._collection = self._database[self._collection_name]
            
            # Test connection
            await self._client.admin.command('ping')
            
            # Create indexes
            await self._ensure_indexes()
            
            self._connected = True
            logger.info(f"Connected to MongoDB: {self._database_name}.{self._collection_name}")
            
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
            # Primary index on entity_id
            await self._collection.create_index("entity_id", unique=True)
            
            # Index on entity type
            await self._collection.create_index("entity_type")
            
            # Index on created_at for time-based queries
            await self._collection.create_index("created_at")
            
            # Composite indexes based on entity type
            if 'replica' in self._collection_name:
                await self._collection.create_index([("parent_digital_twin_id", 1), ("replica_type", 1)])
            elif 'service' in self._collection_name:
                await self._collection.create_index([("digital_twin_id", 1), ("service_type", 1)])
            
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
        """Load entity from MongoDB and deserialize to proper object type"""
        if not self._connected:
            await self.connect()
        try:
            document = await self._collection.find_one({'entity_id': str(entity_id)})
            if not document:
                raise EntityNotFoundError(self.entity_type.__name__, str(entity_id))
            
            entity_dict = EntitySerializer.document_to_entity_dict(document, self.entity_type)
            
            entity = self._deserialize_entity(entity_dict)
            
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
                return self._deserialize_user(entity_dict)
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
        
        # Crea oggetto EnhancedUser
        user = EnhancedUser(
            user_id=user_id,
            username=user_dict['username'],
            email=user_dict['email'],
            password_hash=user_dict['password_hash'],  # ← QUESTO È CRUCIALE!
            role=user_dict['role'],
            tenant_id=tenant_id,
            first_name=user_dict['first_name'],
            last_name=user_dict['last_name'],
            is_active=user_dict.get('is_active', True),
            metadata=user_dict.get('metadata', {}),
            created_at=created_at,
            last_login=last_login
        )
        
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
    
    async def query(self, filters: Optional[Dict[str, Any]] = None) -> List[T]:
        """Query entities from MongoDB with proper deserialization"""
        if not self._connected:
            await self.connect()
        
        try:
            query_filter = filters or {}
            cursor = self._collection.find(query_filter)
            documents = await cursor.to_list(length=None)
            
            entities = []
            for doc in documents:
                entity_dict = EntitySerializer.document_to_entity_dict(doc, self.entity_type)
                # ✅ FIX: Usa il nuovo metodo di deserializzazione
                entity = self._deserialize_entity(entity_dict)
                entities.append(entity)
            
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
            
            # Ping the database
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
    
