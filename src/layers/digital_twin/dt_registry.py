"""
Digital Twin Registry implementation for the Digital Twin Platform.

This module provides the specialized registry for Digital Twins,
including twin relationships, model tracking, and performance monitoring.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID
import logging
from src.layers.digital_twin.association_manager import get_association_manager

from src.core.registry.dt_registry import DigitalTwinRegistry as BaseDigitalTwinRegistry
from src.core.interfaces.base import IStorageAdapter
from src.core.interfaces.digital_twin import (
    IDigitalTwin,
    DigitalTwinType,
    DigitalTwinState,
    TwinCapability,
    TwinSnapshot,
    TwinModel
)

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import UUID
import logging

from src.utils.exceptions import (
    DigitalTwinError,
    DigitalTwinNotFoundError,
    EntityNotFoundError,
    RegistryError
)
from src.core.registry.dt_registry import DigitalTwinRelationship
from src.core.registry.base import AbstractRegistry, RegistryMetrics
from src.core.interfaces.base import IStorageAdapter, BaseMetadata
from src.core.interfaces.digital_twin import IDigitalTwin, DigitalTwinType, DigitalTwinState, TwinCapability, TwinSnapshot
from src.utils.exceptions import DigitalTwinError, DigitalTwinNotFoundError, EntityNotFoundError, RegistryError
logger = logging.getLogger(__name__)


class DigitalTwinAssociation:
    """Represents associations between Digital Twins and other entities."""
    
    def __init__(
        self,
        twin_id: UUID,
        associated_entity_id: UUID,
        association_type: str,  # replica, service, parent_twin, child_twin
        entity_type: str,  # digital_replica, service, digital_twin
        created_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.twin_id = twin_id
        self.associated_entity_id = associated_entity_id
        self.association_type = association_type
        self.entity_type = entity_type
        self.created_at = created_at or datetime.now(timezone.utc)
        self.metadata = metadata or {}
        self.last_interaction: Optional[datetime] = None
        self.interaction_count = 0
    
    def update_interaction(self) -> None:
        """Update interaction statistics."""
        self.last_interaction = datetime.now(timezone.utc)
        self.interaction_count += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert association to dictionary representation."""
        return {
            "twin_id": str(self.twin_id),
            "associated_entity_id": str(self.associated_entity_id),
            "association_type": self.association_type,
            "entity_type": self.entity_type,
            "created_at": self.created_at.isoformat(),
            "last_interaction": self.last_interaction.isoformat() if self.last_interaction else None,
            "interaction_count": self.interaction_count,
            "metadata": self.metadata
        }


class DigitalTwinPerformanceMetrics:
    """Performance metrics for Digital Twins."""
    
    def __init__(self):
        self.total_twins = 0
        self.twins_by_type: Dict[DigitalTwinType, int] = {}
        self.twins_by_state: Dict[DigitalTwinState, int] = {}
        self.model_executions = 0
        self.predictions_made = 0
        self.simulations_run = 0
        self.data_updates = 0
        self.snapshots_created = 0
        self.last_activity: Optional[datetime] = None
        self.average_update_frequency = 0.0
        
        # Performance tracking
        self._activity_timestamps: List[datetime] = []
    
    def record_activity(
        self,
        activity_type: str,
        twin_id: UUID,
        twin_type: DigitalTwinType
    ) -> None:
        """Record Digital Twin activity."""
        now = datetime.now(timezone.utc)
        
        self.last_activity = now
        self._activity_timestamps.append(now)
        
        # Update counters based on activity type
        if activity_type == "model_execution":
            self.model_executions += 1
        elif activity_type == "prediction":
            self.predictions_made += 1
        elif activity_type == "simulation":
            self.simulations_run += 1
        elif activity_type == "data_update":
            self.data_updates += 1
        elif activity_type == "snapshot":
            self.snapshots_created += 1
        
        # Update twin type counters
        self.twins_by_type[twin_type] = self.twins_by_type.get(twin_type, 0) + 1
        
        # Keep only last hour of activities
        cutoff = now - timedelta(hours=1)
        self._activity_timestamps = [ts for ts in self._activity_timestamps if ts > cutoff]
        
        # Calculate activity rate
        if len(self._activity_timestamps) > 1:
            time_span = (self._activity_timestamps[-1] - self._activity_timestamps[0]).total_seconds() / 60
            self.average_update_frequency = len(self._activity_timestamps) / max(time_span, 1)
    
    def get_activity_rate_per_minute(self) -> float:
        """Get activity rate per minute."""
        return self.average_update_frequency
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary representation."""
        return {
            "total_twins": self.total_twins,
            "twins_by_type": {ttype.value: count for ttype, count in self.twins_by_type.items()},
            "twins_by_state": {state.value: count for state, count in self.twins_by_state.items()},
            "model_executions": self.model_executions,
            "predictions_made": self.predictions_made,
            "simulations_run": self.simulations_run,
            "data_updates": self.data_updates,
            "snapshots_created": self.snapshots_created,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
            "activity_rate_per_minute": self.get_activity_rate_per_minute()
        }


class EnhancedDigitalTwinRegistry(AbstractRegistry[IDigitalTwin]):
    """
    Registry avanzato per Digital Twins con supporto per associazioni,
    gerarchie e metriche di performance.
    """

    def __init__(self, storage_adapter: IStorageAdapter[IDigitalTwin], 
             cache_enabled: bool = True, cache_size: int = 1000, cache_ttl: int = 300):
        # Inizializza il registry base
        super().__init__(
            entity_type=IDigitalTwin, 
            storage_adapter=storage_adapter, 
            cache_enabled=cache_enabled, 
            cache_size=cache_size, 
            cache_ttl=cache_ttl
        )
        
        # Inizializza le strutture specifiche per Digital Twins
        self.twin_associations: Dict[str, DigitalTwinRelationship] = {}
        self.twin_hierarchies: Dict[UUID, Set[UUID]] = {}
        self.twin_performance_metrics = DigitalTwinPerformanceMetrics()
        self.model_registry: Dict[UUID, TwinSnapshot] = {}
        self.twin_snapshots: Dict[UUID, List[TwinSnapshot]] = {}
        self._associations: Dict[str, DigitalTwinAssociation] = {}   
        # Lock per operazioni concorrenti
        self._association_lock = asyncio.Lock()
        self._performance_lock = asyncio.Lock()
        self._hierarchy_lock = asyncio.Lock()
        
        # Flag per tracking inizializzazione
        self._associations_loaded = False
        
    async def initialize_associations(self) -> None:
        """Initialize associations after registry is connected."""
        if self._associations_loaded:
            return
        
        try:
            logger.info("🔄 Loading associations from MongoDB...")
            await self.load_associations_from_mongodb()
            self._associations_loaded = True
            logger.info("✅ Associations loaded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to load associations: {e}")

    async def connect(self) -> None:
        """Connect to storage and load associations."""
        await super().connect()  # Connect base registry
        
        # Load associations after connection
        await self.initialize_associations()

    async def register_digital_twin(self, twin: IDigitalTwin, 
                                   initial_relationships: Optional[List[DigitalTwinRelationship]] = None) -> None:
        """Registra un Digital Twin con eventuali relazioni iniziali"""
        await self.register(twin)  # Usa il metodo del parent
        
        if initial_relationships:
            for relationship in initial_relationships:
                await self.add_relationship(relationship)

    async def register_digital_twin_enhanced(self, twin: IDigitalTwin, 
                                           associations: Optional[List] = None, 
                                           parent_twin_id: Optional[UUID] = None) -> None:
        """Alias per compatibilità con il codice esistente"""
        await self.register_digital_twin(twin)
        
        if parent_twin_id:
            await self.add_twin_to_hierarchy(parent_twin_id, twin.id)
        
        # Aggiorna metriche
        async with self._performance_lock:
            self.twin_performance_metrics.total_twins += 1
    
    
    async def add_association(self, association: DigitalTwinAssociation) -> None:
        """Add an association between a Digital Twin and another entity - CON PERSISTENZA!"""
        try:
            # 1. Salva in memoria (per backward compatibility)
            association_key = f"{association.twin_id}:{association.associated_entity_id}:{association.association_type}"
            self._associations[association_key] = association
            
            # 2. NUOVO: Salva in storage persistente se è un'associazione replica
            if not self._association_manager:
                self._association_manager = await get_association_manager()
            
            if association.association_type == 'data_source' or 'replica' in str(association.associated_entity_id).lower():
                try:
                    await self._association_manager.create_association(
                        twin_id=association.twin_id,
                        replica_id=association.associated_entity_id,
                        association_type=association.association_type,
                        data_mapping=association.metadata if hasattr(association, 'metadata') else {}
                    )
                    logger.info(f"✅ Created persistent association: {association.twin_id} -> {association.associated_entity_id}")
                except Exception as e:
                    if "already exists" not in str(e):
                        logger.error(f"❌ Failed to create persistent association: {e}")
            
            # 3. Salva in MongoDB collection dedicata
            try:
                association_data = {
                    'twin_id': str(association.twin_id),
                    'associated_entity_id': str(association.associated_entity_id),
                    'association_type': association.association_type,
                    'entity_type': getattr(association, 'entity_type', 'unknown'),
                    'metadata': getattr(association, 'metadata', {}),
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'status': 'active'
                }
                
                # Usa storage adapter per salvare
                from src.storage.adapters.mongodb_adapter import MongoStorageAdapter
                from src.layers.digital_twin.association_manager import TwinReplicaAssociation
                
                if not hasattr(self, '_association_storage'):
                    self._association_storage = MongoStorageAdapter(TwinReplicaAssociation, twin_id=None)
                    await self._association_storage.connect()
                
                # Crea entity per storage
                from uuid import uuid4
                from src.core.interfaces.base import BaseMetadata
                
                association_entity = TwinReplicaAssociation(
                    entity_id=uuid4(),
                    metadata=BaseMetadata(
                        entity_id=uuid4(),
                        timestamp=datetime.now(timezone.utc),
                        version='1.0',
                        created_by=uuid4()
                    ),
                    twin_id=association.twin_id,
                    replica_id=association.associated_entity_id,
                    association_type=association.association_type,
                    data_mapping=association_data['metadata']
                )
                
                await self._association_storage.save(association_entity)
                logger.info(f"✅ Saved association to MongoDB: {association_key}")
                
            except Exception as e:
                logger.warning(f"Failed to save association to MongoDB: {e}")
            
        except Exception as e:
            logger.error(f"Failed to add association: {e}")
            raise

    async def get_twin_replicas(self, twin_id: UUID) -> Set[UUID]:
        """Ottieni repliche associate al twin (PERSISTENTE)"""
        if not self._association_manager:
            self._association_manager = await get_association_manager()
        
        return await self._association_manager.get_replicas_for_twin(twin_id)
    
    async def remove_association(
        self,
        twin_id: UUID,
        associated_entity_id: UUID,
        association_type: str
    ) -> bool:
        """Remove an association."""
        async with self._association_lock:
            key = f"{twin_id}:{associated_entity_id}:{association_type}"
            
            if key in self.twin_associations:
                del self.twin_associations[key]
                logger.info(f"Removed association: {key}")
                return True
            
            return False
    
    async def get_twin_associations(
        self, 
        twin_id: UUID, 
        association_type: Optional[str] = None,
        entity_type: Optional[str] = None
    ) -> List[DigitalTwinAssociation]:
        """Get associations for a specific Digital Twin."""
        try:
            associations = []
            for key, association in self._associations.items():
                if association.twin_id == twin_id:
                    if association_type and association.association_type != association_type:
                        continue
                    if entity_type and association.entity_type != entity_type:
                        continue
                    associations.append(association)
            return associations
        except Exception as e:
            logger.error(f"Failed to get twin associations: {e}")
            return []
    
    async def add_twin_to_hierarchy(self, parent_twin_id: UUID, child_twin_id: UUID) -> None:
        """Aggiunge un twin alla gerarchia"""
        async with self._hierarchy_lock:
            if parent_twin_id not in self.twin_hierarchies:
                self.twin_hierarchies[parent_twin_id] = set()
            self.twin_hierarchies[parent_twin_id].add(child_twin_id)
            logger.info(f"Added {child_twin_id} to hierarchy under {parent_twin_id}")

    
    async def get_twin_children(self, parent_twin_id: UUID) -> List[IDigitalTwin]:
        """Recupera i twins figli"""
        child_ids = self.twin_hierarchies.get(parent_twin_id, set())
        children = []
        for child_id in child_ids:
            try:
                child_twin = await self.get_digital_twin(child_id)
                children.append(child_twin)
            except DigitalTwinNotFoundError:
                self.twin_hierarchies[parent_twin_id].discard(child_id)
        return children
    
    async def load_associations_from_mongodb(self) -> None:
        """Load all associations from MongoDB at startup."""
        try:
            from src.core.entities.association import DigitalTwinAssociationEntity
            from src.storage import get_global_storage_adapter
            
            storage_adapter = get_global_storage_adapter(DigitalTwinAssociationEntity)
            
            # Load all associations from MongoDB
            association_entities = await storage_adapter.query({}, limit=10000)
            
            loaded_count = 0
            for entity in association_entities:
                # Convert back to DigitalTwinAssociation and store in memory
                association = DigitalTwinAssociation(
                    twin_id=entity.twin_id,
                    associated_entity_id=entity.associated_entity_id,
                    association_type=entity.association_type,
                    entity_type=entity.entity_type,
                    created_at=entity._metadata.timestamp,
                    metadata=entity.association_metadata
                )
                association.last_interaction = entity.last_interaction
                association.interaction_count = entity.interaction_count
                
                # Store in memory
                association_key = f"{association.twin_id}:{association.associated_entity_id}:{association.association_type}"
                self._associations[association_key] = association
                loaded_count += 1
            
            logger.info(f"🔄 Loaded {loaded_count} associations from MongoDB")
            
        except Exception as e:
            logger.error(f"Failed to load associations from MongoDB: {e}")

    async def get_twin_hierarchy_tree(self, root_twin_id: UUID) -> Dict[str, Any]:
        """Get complete hierarchy tree for a twin."""
        try:
            root_twin = await self.get_digital_twin(root_twin_id)
            
            async def build_tree(twin_id: UUID) -> Dict[str, Any]:
                twin = await self.get_digital_twin(twin_id)
                children = await self.get_twin_children(twin_id)
                
                tree = {
                    "twin_id": str(twin_id),
                    "name": twin.name,
                    "twin_type": twin.twin_type.value,
                    "current_state": twin.current_state.value,
                    "children": []
                }
                
                for child in children:
                    child_tree = await build_tree(child.id)
                    tree["children"].append(child_tree)
                
                return tree
            
            return await build_tree(root_twin_id)
            
        except DigitalTwinNotFoundError:
            return {"error": f"Twin {root_twin_id} not found"}
    
    async def register_model(self, model: TwinModel) -> None:
        """Register a model in the model registry."""
        self.model_registry[model.model_id] = model
        logger.info(f"Registered model {model.name} ({model.model_id})")
    
    async def get_model(self, model_id: UUID) -> TwinModel:
        """Get a model from the registry."""
        if model_id not in self.model_registry:
            raise DigitalTwinError(f"Model {model_id} not found")
        return self.model_registry[model_id]
    
    async def find_models_by_type(self, model_type: str) -> List[TwinModel]:
        """Find models by type."""
        return [
            model for model in self.model_registry.values()
            if model.model_type.value == model_type
        ]
    
    async def store_twin_snapshot(self, snapshot: TwinSnapshot) -> None:
        """Store a twin snapshot."""
        twin_id = snapshot.twin_id
        
        if twin_id not in self.twin_snapshots:
            self.twin_snapshots[twin_id] = []
        
        self.twin_snapshots[twin_id].append(snapshot)
        
        # Keep only last 10 snapshots per twin
        if len(self.twin_snapshots[twin_id]) > 10:
            self.twin_snapshots[twin_id] = self.twin_snapshots[twin_id][-10:]
        
        # Update performance metrics
        async with self._performance_lock:
            self.twin_performance_metrics.record_activity("snapshot", twin_id, snapshot.twin_id)
        
        logger.info(f"Stored snapshot for twin {twin_id}")
    
    async def get_twin_snapshots(
        self,
        twin_id: UUID,
        limit: Optional[int] = None
    ) -> List[TwinSnapshot]:
        """Get snapshots for a twin."""
        snapshots = self.twin_snapshots.get(twin_id, [])
        
        # Sort by snapshot time (most recent first)
        snapshots.sort(key=lambda s: s.snapshot_time, reverse=True)
        
        if limit:
            snapshots = snapshots[:limit]
        
        return snapshots
    
    async def record_twin_activity(
        self,
        twin_id: UUID,
        activity_type: str,
        activity_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record activity for a Digital Twin."""
        try:
            twin = await self.get_digital_twin(twin_id)
            
            async with self._performance_lock:
                self.twin_performance_metrics.record_activity(activity_type, twin_id, twin.twin_type)
            
            # Update association interactions if relevant
            if activity_data and "associated_entity_id" in activity_data:
                associated_id = UUID(activity_data["associated_entity_id"])
                for association in self.twin_associations.values():
                    if (association.twin_id == twin_id and 
                        association.associated_entity_id == associated_id):
                        association.update_interaction()
                        break
            
        except DigitalTwinNotFoundError:
            logger.warning(f"Activity recorded for non-existent twin {twin_id}")
    
    async def discover_twins_advanced(self, criteria: Dict[str, Any]) -> List[IDigitalTwin]:
        """Scopre Digital Twins basandosi su criteri avanzati"""
        try:
            filters = {}
            if 'type' in criteria:
                filters['twin_type'] = criteria['type']
            if 'digital_twin_id' in criteria:
                filters['id'] = criteria['digital_twin_id']

            twins = await self.list(filters=filters)
            
            # Applica filtri aggiuntivi
            if 'has_capability' in criteria:
                required_capability = TwinCapability(criteria['has_capability'])
                twins = [t for t in twins if hasattr(t, 'capabilities') and required_capability in t.capabilities]

            return twins

        except Exception as e:
            logger.error(f"Failed to discover twins: {e}")
            raise DigitalTwinError(f"Twin discovery failed: {e}")
        

    async def get_digital_twin(self, twin_id: UUID) -> IDigitalTwin:
        """Recupera un Digital Twin per ID"""
        try:
            return await self.get(twin_id)
        except EntityNotFoundError:
            raise DigitalTwinNotFoundError(twin_id=str(twin_id))

        
    async def find_twins_by_type(self, twin_type: 'DigitalTwinType') -> List[IDigitalTwin]:
        """Trova twins per tipo"""
        filters = {'twin_type': twin_type.value}
        return await self.list(filters=filters)
    
    async def find_twins_by_capability(self, capability: 'TwinCapability') -> List[IDigitalTwin]:
        """Trova twins per capability"""
        all_twins = await self.list()
        matching_twins = []
        for twin in all_twins:
            if hasattr(twin, 'capabilities') and capability in twin.capabilities:
                matching_twins.append(twin)
        return matching_twins

    async def find_twins_by_state(self, state: 'DigitalTwinState') -> List[IDigitalTwin]:
        """Trova twins per stato"""
        all_twins = await self.list()
        matching_twins = []
        for twin in all_twins:
            if hasattr(twin, 'current_state') and twin.current_state == state:
                matching_twins.append(twin)
        return matching_twins

    async def get_twin_performance_summary(self, twin_id: UUID) -> Dict[str, Any]:
        """Ottiene un riassunto delle performance di un twin"""
        try:
            twin = await self.get_digital_twin(twin_id)
            return {
                'twin_id': str(twin_id),
                'name': getattr(twin, 'name', 'Unknown'),
                'twin_type': getattr(twin, 'twin_type', 'unknown'),
                'current_state': getattr(twin, 'current_state', 'unknown'),
                'associations': {'total': 0},  # Semplificato
                'hierarchy': {'children_count': len(self.twin_hierarchies.get(twin_id, set()))},
                'snapshots': {'total': len(self.twin_snapshots.get(twin_id, []))}
            }
        except DigitalTwinNotFoundError:
            return {'error': f'Twin {twin_id} not found'}
    
    async def get_registry_analytics(self) -> Dict[str, Any]:
        """Ottiene analytics completi del registry"""
        all_twins = await self.list()
        analytics = {
            'total_twins': len(all_twins),
            'twins_by_type': {},
            'twins_by_state': {},
            'total_associations': len(self.twin_associations),
            'total_hierarchies': len(self.twin_hierarchies),
            'performance_metrics': self.twin_performance_metrics.to_dict() if hasattr(self.twin_performance_metrics, 'to_dict') else {}
        }
        
        # Analizza i twins
        for twin in all_twins:
            if hasattr(twin, 'twin_type'):
                twin_type = str(twin.twin_type)
                analytics['twins_by_type'][twin_type] = analytics['twins_by_type'].get(twin_type, 0) + 1
            
            if hasattr(twin, 'current_state'):
                twin_state = str(twin.current_state)
                analytics['twins_by_state'][twin_state] = analytics['twins_by_state'].get(twin_state, 0) + 1
        
        return analytics
    
    async def optimize_registry_performance(self) -> Dict[str, Any]:
        """Optimize registry performance and return optimization results."""
        optimization_results = {
            "cache_optimization": {},
            "data_cleanup": {},
            "performance_improvements": {}
        }
        
        # Clear cache if enabled
        if self.cache_enabled:
            cache_size_before = self.cache.size() if self.cache else 0
            await self.clear_cache()
            optimization_results["cache_optimization"]["cache_cleared"] = cache_size_before
        
        # Clean up old snapshots
        snapshots_cleaned = 0
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
        
        for twin_id, snapshots in self.twin_snapshots.items():
            original_count = len(snapshots)
            self.twin_snapshots[twin_id] = [
                s for s in snapshots 
                if s.snapshot_time > cutoff_date
            ]
            snapshots_cleaned += original_count - len(self.twin_snapshots[twin_id])
        
        optimization_results["data_cleanup"]["old_snapshots_removed"] = snapshots_cleaned
        
        # Clean up stale associations
        stale_associations = []
        for key, association in list(self.twin_associations.items()):
            try:
                await self.get_digital_twin(association.twin_id)
            except DigitalTwinNotFoundError:
                stale_associations.append(key)
        
        for key in stale_associations:
            del self.twin_associations[key]
        
        optimization_results["data_cleanup"]["stale_associations_removed"] = len(stale_associations)
        
        # Performance improvements
        optimization_results["performance_improvements"] = {
            "total_twins": len(await self.list()),
            "total_associations": len(self.twin_associations),
            "total_models": len(self.model_registry),
            "optimization_completed_at": datetime.now(timezone.utc).isoformat()
        }
        
        logger.info("Registry performance optimization completed")
        return optimization_results
    async def create_snapshot(self, twin_id: UUID) -> TwinSnapshot:
        """Crea uno snapshot di un twin"""
        twin = await self.get_digital_twin(twin_id)
        
        # Snapshot semplificato
        snapshot = TwinSnapshot(
            twin_id=twin_id,
            snapshot_time=datetime.now(timezone.utc),
            state=getattr(twin, '_twin_state', {}),
            model_states={},
            metrics={},
            metadata={'created_by': 'registry'}
        )
        
        if twin_id not in self.twin_snapshots:
            self.twin_snapshots[twin_id] = []
        self.twin_snapshots[twin_id].append(snapshot)
        
        return snapshot
    async def get_snapshots(self, twin_id: UUID, limit: Optional[int] = None) -> List[TwinSnapshot]:
        """Recupera gli snapshot di un twin"""
        snapshots = self.twin_snapshots.get(twin_id, [])
        snapshots.sort(key=lambda s: s.snapshot_time, reverse=True)
        if limit:
            snapshots = snapshots[:limit]
        return snapshots