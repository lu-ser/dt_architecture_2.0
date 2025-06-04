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

    @staticmethod
    def entity_to_document(entity: IEntity) -> Dict[str, Any]:
        try:
            if hasattr(entity, 'to_dict'):
                doc = entity.to_dict()
            else:
                doc = {'id': str(entity.id), 'metadata': entity.metadata.to_dict() if entity.metadata else {}, 'status': entity.status.value if hasattr(entity.status, 'value') else str(entity.status), 'created_at': datetime.now(timezone.utc).isoformat(), 'entity_type': entity.__class__.__name__}
            doc['_id'] = str(entity.id)
            doc['entity_id'] = str(entity.id)
            doc = EntitySerializer._convert_uuids_to_strings(doc)
            return doc
        except Exception as e:
            logger.error(f'Failed to serialize entity {entity.id}: {e}')
            raise DataPersistenceError(f'Entity serialization failed: {e}')

    @staticmethod
    def document_to_entity_dict(doc: Dict[str, Any], entity_class: Type[T]) -> Dict[str, Any]:
        try:
            if '_id' in doc:
                del doc['_id']
            doc = EntitySerializer._convert_strings_to_uuids(doc)
            return doc
        except Exception as e:
            logger.error(f'Failed to deserialize document: {e}')
            raise StorageError(f'Document deserialization failed: {e}')

    @staticmethod
    def _convert_uuids_to_strings(obj: Any) -> Any:
        if isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, dict):
            return {key: EntitySerializer._convert_uuids_to_strings(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [EntitySerializer._convert_uuids_to_strings(item) for item in obj]
        return obj

    @staticmethod
    def _convert_strings_to_uuids(obj: Any) -> Any:
        if isinstance(obj, dict):
            converted = {}
            for key, value in obj.items():
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

    def __init__(self, entity_type: Type[T], twin_id: Optional[UUID]=None):
        self.entity_type = entity_type
        self.twin_id = twin_id
        self.config = get_config()
        self._client: Optional[AsyncIOMotorClient] = None
        self._database: Optional[AsyncIOMotorDatabase] = None
        self._collection: Optional[AsyncIOMotorCollection] = None
        self._connected = False
        self._database_name = self._get_database_name()
        self._collection_name = self._get_collection_name()
        logger.info(f'MongoDB adapter initialized for {entity_type.__name__} (DB: {self._database_name})')

    @property
    def storage_type(self) -> str:
        return 'mongodb'

    def _get_database_name(self) -> str:
        prefix = self.config.get('mongodb.database_prefix', 'dt_platform')
        if self.config.get('storage.separate_dbs_per_twin', True) and self.twin_id:
            return f"{prefix}_dt_{str(self.twin_id).replace('-', '_')}"
        else:
            return self.config.get('mongodb.global_database', 'dt_platform_global')

    def _get_collection_name(self) -> str:
        entity_name = self.entity_type.__name__.lower()
        collection_mapping = {'digitaltwin': 'digital_twins', 'digitalreplica': 'digital_replicas', 'standarddigitalreplica': 'digital_replicas', 'service': 'services', 'standardservice': 'services', 'user': 'users', 'apikey': 'api_keys'}
        return collection_mapping.get(entity_name, f'{entity_name}s')

    def _get_connection_string(self) -> str:
        base_uri = self.config.get('mongodb.connection_string', 'mongodb://localhost:27017')
        username = self.config.get('mongodb.username')
        password = self.config.get('mongodb.password')
        auth_source = self.config.get('mongodb.auth_source', 'admin')
        if username and password:
            if '://' in base_uri:
                protocol, rest = base_uri.split('://', 1)
                return f'{protocol}://{username}:{password}@{rest}?authSource={auth_source}'
        return base_uri

    async def connect(self) -> None:
        if self._connected:
            return
        try:
            connection_string = self._get_connection_string()
            self._client = AsyncIOMotorClient(connection_string, maxPoolSize=self.config.get('mongodb.max_pool_size', 50), minPoolSize=self.config.get('mongodb.pool_size', 10), serverSelectionTimeoutMS=self.config.get('mongodb.timeout_ms', 5000), retryWrites=self.config.get('mongodb.retry_writes', True))
            self._database = self._client[self._database_name]
            self._collection = self._database[self._collection_name]
            await self._client.admin.command('ping')
            await self._ensure_indexes()
            self._connected = True
            logger.info(f'Connected to MongoDB: {self._database_name}.{self._collection_name}')
        except (ServerSelectionTimeoutError, ConnectionFailure) as e:
            logger.error(f'Failed to connect to MongoDB: {e}')
            raise StorageConnectionError(f'MongoDB connection failed: {e}')
        except Exception as e:
            logger.error(f'Unexpected error connecting to MongoDB: {e}')
            raise StorageError(f'MongoDB connection error: {e}')

    async def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._connected = False
            logger.info('Disconnected from MongoDB')

    async def _ensure_indexes(self) -> None:
        try:
            await self._collection.create_index('entity_id', unique=True)
            await self._collection.create_index('entity_type')
            await self._collection.create_index('created_at')
            if 'replica' in self._collection_name:
                await self._collection.create_index([('parent_digital_twin_id', 1), ('replica_type', 1)])
            elif 'service' in self._collection_name:
                await self._collection.create_index([('digital_twin_id', 1), ('service_type', 1)])
            logger.debug(f'Indexes ensured for {self._collection_name}')
        except Exception as e:
            logger.warning(f'Failed to create indexes: {e}')

    async def save(self, entity: T) -> None:
        if not self._connected:
            await self.connect()
        try:
            document = EntitySerializer.entity_to_document(entity)
            result = await self._collection.replace_one({'entity_id': str(entity.id)}, document, upsert=True)
            if result.upserted_id:
                logger.debug(f'Inserted entity {entity.id} into {self._collection_name}')
            else:
                logger.debug(f'Updated entity {entity.id} in {self._collection_name}')
        except DuplicateKeyError as e:
            logger.error(f'Duplicate entity {entity.id}: {e}')
            raise DataPersistenceError(f'Entity {entity.id} already exists')
        except Exception as e:
            logger.error(f'Failed to save entity {entity.id}: {e}')
            raise DataPersistenceError(f'Save operation failed: {e}')

    async def load(self, entity_id: UUID) -> T:
        if not self._connected:
            await self.connect()
        try:
            document = await self._collection.find_one({'entity_id': str(entity_id)})
            if not document:
                raise EntityNotFoundError(self.entity_type.__name__, str(entity_id))
            entity_dict = EntitySerializer.document_to_entity_dict(document, self.entity_type)
            entity_wrapper = DictToObjectWrapper(entity_dict)
            logger.debug(f'Loaded entity {entity_id} from {self._collection_name}')
            return entity_wrapper
        except EntityNotFoundError:
            raise
        except Exception as e:
            logger.error(f'Failed to load entity {entity_id}: {e}')
            raise StorageError(f'Load operation failed: {e}')

    async def delete(self, entity_id: UUID) -> None:
        if not self._connected:
            await self.connect()
        try:
            result = await self._collection.delete_one({'entity_id': str(entity_id)})
            if result.deleted_count == 0:
                raise EntityNotFoundError(self.entity_type.__name__, str(entity_id))
            logger.debug(f'Deleted entity {entity_id} from {self._collection_name}')
        except EntityNotFoundError:
            raise
        except Exception as e:
            logger.error(f'Failed to delete entity {entity_id}: {e}')
            raise StorageError(f'Delete operation failed: {e}')

    async def query(self, filters: Dict[str, Any], limit: Optional[int]=None, offset: Optional[int]=None) -> List[T]:
        if not self._connected:
            await self.connect()
        try:
            mongo_filter = self._build_mongo_filter(filters)
            cursor = self._collection.find(mongo_filter)
            if offset:
                cursor = cursor.skip(offset)
            if limit:
                cursor = cursor.limit(limit)
            documents = await cursor.to_list(length=limit)
            entities = []
            for doc in documents:
                entity_dict = EntitySerializer.document_to_entity_dict(doc, self.entity_type)
                entity_wrapper = DictToObjectWrapper(entity_dict)
                entities.append(entity_wrapper)
            logger.debug(f'Queried {len(entities)} entities from {self._collection_name}')
            return entities
        except Exception as e:
            logger.error(f'Failed to query entities: {e}')
            raise StorageError(f'Query operation failed: {e}')

    def _build_mongo_filter(self, filters: Dict[str, Any]) -> Dict[str, Any]:
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
        try:
            if not self._connected:
                return False
            await self._client.admin.command('ping')
            return True
        except Exception as e:
            logger.error(f'MongoDB health check failed: {e}')
            return False

class MongoStorageAdapterFactory:

    @staticmethod
    def create_adapter(entity_type: Type[T], twin_id: Optional[UUID]=None) -> MongoStorageAdapter[T]:
        return MongoStorageAdapter(entity_type, twin_id)

    @staticmethod
    def create_global_adapter(entity_type: Type[T]) -> MongoStorageAdapter[T]:
        return MongoStorageAdapter(entity_type, twin_id=None)

    @staticmethod
    def create_twin_adapter(entity_type: Type[T], twin_id: UUID) -> MongoStorageAdapter[T]:
        return MongoStorageAdapter(entity_type, twin_id=twin_id)