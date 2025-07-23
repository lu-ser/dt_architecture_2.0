# src/layers/digital_twin/association_manager.py
"""
Association Manager - Gestione Persistente delle Associazioni
Risolve il problema delle associazioni perse in memoria
"""

import asyncio
from typing import Dict, Set, List, Optional, Any
from uuid import UUID
from datetime import datetime, timezone
import logging
from dataclasses import dataclass

from src.core.interfaces.base import IEntity, BaseMetadata, EntityStatus
from src.storage.adapters.mongodb_adapter import MongoStorageAdapter

logger = logging.getLogger(__name__)


@dataclass
class TwinReplicaAssociation(IEntity):
    """Entity per persistere le associazioni Twin-Replica in MongoDB"""
    
    def __init__(
        self,
        entity_id: UUID,
        metadata: BaseMetadata,
        twin_id: UUID,
        replica_id: UUID,
        association_type: str = 'data_source',
        data_mapping: Optional[Dict[str, Any]] = None,
        status: str = 'active'
    ):
        self._id = entity_id
        self._metadata = metadata
        self._status = EntityStatus.ACTIVE
        
        self.twin_id = twin_id
        self.replica_id = replica_id
        self.association_type = association_type
        self.data_mapping = data_mapping or {}
        self.association_status = status
        self.created_at = datetime.now(timezone.utc)
        self.last_updated = datetime.now(timezone.utc)
    
    @property
    def id(self) -> UUID:
        return self._id
    
    @property
    def metadata(self) -> BaseMetadata:
        return self._metadata
    
    @property
    def status(self) -> EntityStatus:
        return self._status
    
    async def initialize(self) -> None:
        self._status = EntityStatus.ACTIVE
    
    async def start(self) -> None:
        self._status = EntityStatus.ACTIVE
    
    async def stop(self) -> None:
        self._status = EntityStatus.INACTIVE
    
    async def terminate(self) -> None:
        self._status = EntityStatus.TERMINATED
    
    async def validate(self) -> bool:
        return self.twin_id is not None and self.replica_id is not None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'entity_id': str(self.id),
            'twin_id': str(self.twin_id),
            'replica_id': str(self.replica_id),
            'association_type': self.association_type,
            'data_mapping': self.data_mapping,
            'association_status': self.association_status,
            'created_at': self.created_at.isoformat(),
            'last_updated': self.last_updated.isoformat(),
            'metadata': self.metadata.to_dict() if hasattr(self.metadata, 'to_dict') else str(self.metadata)
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TwinReplicaAssociation':
        from uuid import uuid4
        
        # Create minimal metadata if not present
        metadata = BaseMetadata(
            entity_id=UUID(data['entity_id']),
            timestamp=datetime.fromisoformat(data.get('created_at', datetime.now(timezone.utc).isoformat())),
            version='1.0',
            created_by=uuid4()
        )
        
        return cls(
            entity_id=UUID(data['entity_id']),
            metadata=metadata,
            twin_id=UUID(data['twin_id']),
            replica_id=UUID(data['replica_id']),
            association_type=data.get('association_type', 'data_source'),
            data_mapping=data.get('data_mapping', {}),
            status=data.get('association_status', 'active')
        )


class PersistentAssociationManager:
    """
    Manager per gestire le associazioni Twin-Replica con persistenza MongoDB
    RISOLVE: Il problema delle associazioni perse in memoria
    """
    
    def __init__(self):
        self._storage_adapter: Optional[MongoStorageAdapter] = None
        self._memory_cache: Dict[UUID, Set[UUID]] = {}  # twin_id -> set(replica_ids)
        self._reverse_cache: Dict[UUID, UUID] = {}      # replica_id -> twin_id
        self._cache_lock = asyncio.Lock()
        self._initialized = False
        
    async def initialize(self) -> None:
        """Inizializza il manager con storage MongoDB"""
        if self._initialized:
            return
            
        try:
            # Setup MongoDB storage per associazioni (global DB)
            self._storage_adapter = MongoStorageAdapter(TwinReplicaAssociation, twin_id=None)
            await self._storage_adapter.connect()
            
            # Carica tutte le associazioni esistenti in cache
            await self._load_associations_from_storage()
            
            self._initialized = True
            logger.info("✅ Persistent Association Manager initialized")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Association Manager: {e}")
            raise
    
    async def _fallback_load_from_registry(self) -> None:
        """Fallback: carica associazioni dalle strutture legacy del registry"""
        try:
            logger.info("🔄 Attempting fallback load from registry structures...")
            
            # Se ci sono associazioni nei registries esistenti, caricale
            loaded_count = 0
            
            # Questo è il metodo per sincronizzare con i registries esistenti
            # se necessario implementare
            
            logger.info(f"✅ Fallback loaded {loaded_count} associations")
            
        except Exception as e:
            logger.error(f"❌ Fallback load failed: {e}")

    async def _load_associations_from_storage(self) -> None:
        """Carica tutte le associazioni da MongoDB in cache"""
        try:
            async with self._cache_lock:
                self._memory_cache.clear()
                self._reverse_cache.clear()
                
                # Query tutte le associazioni attive
                filters = {'association_status': 'active'}
                associations = await self._storage_adapter.query(filters)
                
                loaded_count = 0
                for association in associations:
                    twin_id = association.twin_id
                    replica_id = association.replica_id
                    
                    # Aggiorna cache
                    if twin_id not in self._memory_cache:
                        self._memory_cache[twin_id] = set()
                    self._memory_cache[twin_id].add(replica_id)
                    self._reverse_cache[replica_id] = twin_id
                    loaded_count += 1
                
                logger.info(f"✅ Loaded {loaded_count} associations from MongoDB into cache")
                
        except Exception as e:
            logger.error(f"❌ Failed to load associations from storage: {e}")
            # Prova con il fallback delle associazioni legacy
            await self._fallback_load_from_registry()

    async def create_association(
        self,
        twin_id: UUID,
        replica_id: UUID,
        association_type: str = 'data_source',
        data_mapping: Optional[Dict[str, Any]] = None
    ) -> TwinReplicaAssociation:
        """Crea una nuova associazione Twin-Replica con persistenza"""
        
        if not self._initialized:
            await self.initialize()
        
        try:
            from uuid import uuid4
            
            # 1. Verifica che l'associazione non esista già
            if await self.association_exists(twin_id, replica_id):
                raise ValueError(f"Association between {twin_id} and {replica_id} already exists")
            
            # 2. Crea entity di associazione
            association = TwinReplicaAssociation(
                entity_id=uuid4(),
                metadata=BaseMetadata(
                    entity_id=uuid4(),
                    timestamp=datetime.now(timezone.utc),
                    version='1.0',
                    created_by=uuid4(),
                    custom={'association_manager': 'persistent'}
                ),
                twin_id=twin_id,
                replica_id=replica_id,
                association_type=association_type,
                data_mapping=data_mapping
            )
            
            # 3. PERSISTI in MongoDB
            await self._storage_adapter.save(association)
            
            # 4. Aggiorna cache in memoria
            async with self._cache_lock:
                if twin_id not in self._memory_cache:
                    self._memory_cache[twin_id] = set()
                self._memory_cache[twin_id].add(replica_id)
                self._reverse_cache[replica_id] = twin_id
            
            logger.info(f"✅ Created persistent association: {twin_id} -> {replica_id}")
            return association
            
        except Exception as e:
            logger.error(f"❌ Failed to create association {twin_id} -> {replica_id}: {e}")
            raise
    
    async def remove_association(self, twin_id: UUID, replica_id: UUID) -> bool:
        """Rimuove un'associazione Twin-Replica"""
        
        if not self._initialized:
            await self.initialize()
        
        try:
            # 1. Trova l'associazione in MongoDB
            filters = {
                'twin_id': str(twin_id),
                'replica_id': str(replica_id),
                'association_status': 'active'
            }
            associations = await self._storage_adapter.query(filters, limit=1)
            
            if not associations:
                logger.warning(f"Association {twin_id} -> {replica_id} not found")
                return False
            
            association = associations[0]
            
            # 2. Marca come inattiva invece di eliminare (audit trail)
            association.association_status = 'inactive'
            association.last_updated = datetime.now(timezone.utc)
            await self._storage_adapter.update(association.id, association)
            
            # 3. Rimuovi dalla cache
            async with self._cache_lock:
                if twin_id in self._memory_cache:
                    self._memory_cache[twin_id].discard(replica_id)
                    if not self._memory_cache[twin_id]:
                        del self._memory_cache[twin_id]
                
                if replica_id in self._reverse_cache:
                    del self._reverse_cache[replica_id]
            
            logger.info(f"✅ Removed association: {twin_id} -> {replica_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to remove association {twin_id} -> {replica_id}: {e}")
            return False
    
    async def get_replicas_for_twin(self, twin_id: UUID) -> Set[UUID]:
        """Ottieni tutte le repliche associate a un Digital Twin"""
        
        if not self._initialized:
            await self.initialize()
        
        async with self._cache_lock:
            return self._memory_cache.get(twin_id, set()).copy()
    
    async def get_twin_for_replica(self, replica_id: UUID) -> Optional[UUID]:
        """Ottieni il Digital Twin associato a una replica"""
        
        if not self._initialized:
            await self.initialize()
        
        async with self._cache_lock:
            return self._reverse_cache.get(replica_id)
    
    async def association_exists(self, twin_id: UUID, replica_id: UUID) -> bool:
        """Verifica se esiste un'associazione tra Twin e Replica"""
        
        if not self._initialized:
            await self.initialize()
        
        async with self._cache_lock:
            return (twin_id in self._memory_cache and 
                    replica_id in self._memory_cache[twin_id])
    
    async def get_all_associations(self) -> Dict[UUID, Set[UUID]]:
        """Ottieni tutte le associazioni attive"""
        
        if not self._initialized:
            await self.initialize()
        
        async with self._cache_lock:
            return {twin_id: replicas.copy() 
                    for twin_id, replicas in self._memory_cache.items()}
    
    async def sync_with_registries(self, dt_registry, dr_registry) -> None:
        """Sincronizza le associazioni con i registries esistenti"""
        
        if not self._initialized:
            await self.initialize()
        
        try:
            logger.info("🔄 Syncing associations with registries...")
            
            # Sync DR registry mapping
            async with self._cache_lock:
                dr_registry.digital_twin_replicas.clear()
                dr_registry.digital_twin_replicas.update(self._memory_cache)
            
            # Sync DT registry associations (se supportato)
            if hasattr(dt_registry, '_associations'):
                dt_registry._associations.clear()
                for twin_id, replica_ids in self._memory_cache.items():
                    for replica_id in replica_ids:
                        key = f"{twin_id}:{replica_id}:data_source"
                        # Crea associazione semplice per backward compatibility
                        dt_registry._associations[key] = {
                            'twin_id': twin_id,
                            'replica_id': replica_id,
                            'type': 'data_source'
                        }
            
            synced_associations = sum(len(replicas) for replicas in self._memory_cache.values())
            logger.info(f"✅ Synced {synced_associations} associations with registries")
            
        except Exception as e:
            logger.error(f"❌ Failed to sync with registries: {e}")
            raise
    
    async def cleanup_orphaned_associations(self, dt_registry, dr_registry) -> int:
        """Pulisce associazioni orfane (entità non più esistenti)"""
        
        if not self._initialized:
            await self.initialize()
        
        try:
            cleaned_count = 0
            
            for twin_id, replica_ids in list(self._memory_cache.items()):
                # Verifica che il twin esista ancora
                try:
                    await dt_registry.get_digital_twin(twin_id)
                except:
                    logger.warning(f"Twin {twin_id} no longer exists, cleaning associations")
                    for replica_id in replica_ids:
                        await self.remove_association(twin_id, replica_id)
                        cleaned_count += 1
                    continue
                
                # Verifica che le repliche esistano ancora
                for replica_id in list(replica_ids):
                    try:
                        await dr_registry.get_digital_replica(replica_id)
                    except:
                        logger.warning(f"Replica {replica_id} no longer exists, cleaning association")
                        await self.remove_association(twin_id, replica_id)
                        cleaned_count += 1
            
            logger.info(f"✅ Cleaned {cleaned_count} orphaned associations")
            return cleaned_count
            
        except Exception as e:
            logger.error(f"❌ Failed to cleanup orphaned associations: {e}")
            return 0
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Ottieni statistiche sulle associazioni"""
        
        if not self._initialized:
            await self.initialize()
        
        async with self._cache_lock:
            total_twins = len(self._memory_cache)
            total_replicas = sum(len(replicas) for replicas in self._memory_cache.values())
            
            return {
                'total_twins_with_replicas': total_twins,
                'total_associations': total_replicas,
                'average_replicas_per_twin': total_replicas / total_twins if total_twins > 0 else 0,
                'cache_size': len(self._reverse_cache),
                'initialized': self._initialized
            }


# Singleton instance
_association_manager: Optional[PersistentAssociationManager] = None

async def get_association_manager() -> PersistentAssociationManager:
    """Ottieni l'istanza singleton del Association Manager"""
    global _association_manager
    
    if _association_manager is None:
        _association_manager = PersistentAssociationManager()
        await _association_manager.initialize()
    
    return _association_manager