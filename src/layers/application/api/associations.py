# NUOVO FILE: src/layers/application/api/associations.py

from fastapi import APIRouter, Depends, HTTPException, status, Path, Query, Body
from typing import Dict, Any, List, Optional, UUID
from datetime import datetime, timezone
import logging

from src.layers.application.api_gateway import APIGateway, get_gateway
from src.layers.digital_twin.association_manager import get_association_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/associations", tags=["Association Management"])


@router.get("/status", summary="Association System Status")
async def get_association_status(
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """
    Mostra lo status del sistema di associazioni per diagnosticare problemi
    """
    try:
        # Get Association Manager status
        association_manager = await get_association_manager()
        manager_stats = await association_manager.get_statistics()
        
        # Get current registries status
        dt_registry = gateway.dt_orchestrator.registry
        dr_registry = gateway.virtualization_orchestrator.registry
        
        # Registry memory state
        registry_state = {
            'dr_registry_associations': len(dr_registry.digital_twin_replicas),
            'dt_registry_associations': len(getattr(dt_registry, '_associations', {})),
            'memory_mappings_sample': {
                str(k): len(v) for k, v in list(dr_registry.digital_twin_replicas.items())[:3]
            }
        }
        
        # Health check
        health_issues = []
        if manager_stats['total_associations'] == 0:
            health_issues.append("No associations found in persistent storage")
        if registry_state['dr_registry_associations'] == 0 and manager_stats['total_associations'] > 0:
            health_issues.append("DR registry not synced with persistent storage")
        
        return {
            'status': 'healthy' if not health_issues else 'issues_detected',
            'health_issues': health_issues,
            'association_manager': manager_stats,
            'registry_state': registry_state,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get association status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get status: {e}"
        )


@router.post("/repair", summary="Repair Association System")
async def repair_associations(
    force_full_sync: bool = Query(False, description="Force complete resync"),
    cleanup_orphaned: bool = Query(True, description="Remove orphaned associations"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """
    RIPARAZIONE COMPLETA del sistema di associazioni
    Risolve associazioni perse, registries non sincronizzati
    """
    try:
        logger.info(f"🔧 Starting association repair (force_sync={force_full_sync}, cleanup={cleanup_orphaned})")
        
        # Get managers
        association_manager = await get_association_manager()
        
        # Get registries
        dt_registry = gateway.dt_orchestrator.registry
        dr_registry = gateway.virtualization_orchestrator.registry
        
        repair_results = {
            'started_at': datetime.now(timezone.utc).isoformat(),
            'actions_performed': [],
            'before_stats': await association_manager.get_statistics(),
            'issues_found': [],
            'issues_fixed': []
        }
        
        # 1. Initialize Association Manager if needed
        if not association_manager._initialized:
            await association_manager.initialize()
            repair_results['actions_performed'].append('initialized_association_manager')
        
        # 2. Force full sync if requested or if discrepancies found
        stats = await association_manager.get_statistics()
        memory_count = len(dr_registry.digital_twin_replicas)
        
        if force_full_sync or stats['total_associations'] != memory_count:
            await association_manager.sync_with_registries(dt_registry, dr_registry)
            repair_results['actions_performed'].append('synced_registries')
            
            # Check if we need to restore from metadata
            updated_stats = await association_manager.get_statistics()
            if updated_stats['total_associations'] == 0:
                logger.info("🔧 No associations found, attempting restore from replica metadata...")
                restored_count = await _restore_associations_from_metadata(
                    association_manager, dr_registry
                )
                repair_results['actions_performed'].append('restored_from_metadata')
                repair_results['associations_restored'] = restored_count
        
        # 3. Cleanup orphaned associations
        if cleanup_orphaned:
            cleaned_count = await association_manager.cleanup_orphaned_associations(
                dt_registry, dr_registry
            )
            repair_results['actions_performed'].append('cleaned_orphaned_associations')
            repair_results['orphaned_cleaned'] = cleaned_count
        
        # 4. Final sync
        await association_manager.sync_with_registries(dt_registry, dr_registry)
        
        # 5. Final stats
        repair_results['after_stats'] = await association_manager.get_statistics()
        repair_results['completed_at'] = datetime.now(timezone.utc).isoformat()
        repair_results['status'] = 'success'
        
        logger.info(f"✅ Association repair completed: {len(repair_results['actions_performed'])} actions")
        return repair_results
        
    except Exception as e:
        logger.error(f"❌ Association repair failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Repair failed: {e}"
        )


async def _restore_associations_from_metadata(association_manager, dr_registry) -> int:
    """Helper per ripristinare associazioni dai metadata delle repliche"""
    try:
        replicas = await dr_registry.list()
        restored_count = 0
        
        for replica in replicas:
            try:
                twin_id = None
                
                if hasattr(replica, 'parent_digital_twin_id'):
                    twin_id = replica.parent_digital_twin_id
                elif hasattr(replica, 'metadata') and replica.metadata:
                    try:
                        metadata_dict = replica.metadata.to_dict() if hasattr(replica.metadata, 'to_dict') else replica.metadata
                        custom_data = metadata_dict.get('custom', {}) if isinstance(metadata_dict, dict) else {}
                        parent_twin_str = custom_data.get('parent_twin_id')
                        if parent_twin_str:
                            twin_id = UUID(parent_twin_str)
                    except Exception:
                        continue
                
                if twin_id:
                    await association_manager.create_association(
                        twin_id=twin_id,
                        replica_id=replica.id,
                        association_type='data_source'
                    )
                    restored_count += 1
                    logger.info(f"✅ Restored association: {replica.id} -> {twin_id}")
            
            except Exception as e:
                if "already exists" not in str(e):
                    logger.warning(f"Failed to restore association for replica {replica.id}: {e}")
        
        return restored_count
        
    except Exception as e:
        logger.error(f"Failed to restore associations from metadata: {e}")
        return 0


@router.get("/twin/{twin_id}/replicas", summary="Get Twin Replicas (Persistent)")
async def get_twin_replicas_persistent(
    twin_id: UUID = Path(..., description="Digital Twin ID"),
    include_details: bool = Query(False, description="Include replica details"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """
    Ottieni repliche associate a un twin usando storage persistente
    """
    try:
        # Use persistent Association Manager
        association_manager = await get_association_manager()
        replica_ids = await association_manager.get_replicas_for_twin(twin_id)
        
        result = {
            'twin_id': str(twin_id),
            'replica_count': len(replica_ids),
            'replica_ids': [str(rid) for rid in replica_ids],
        }
        
        # Include details if requested
        if include_details:
            dr_registry = gateway.virtualization_orchestrator.registry
            replica_details = []
            
            for replica_id in replica_ids:
                try:
                    replica = await dr_registry.get_digital_replica(replica_id)
                    replica_details.append({
                        'replica_id': str(replica_id),
                        'type': str(type(replica)),
                        'status': getattr(replica, 'status', 'unknown'),
                        'device_count': len(getattr(replica, 'device_ids', []))
                    })
                except Exception as e:
                    replica_details.append({
                        'replica_id': str(replica_id),
                        'error': str(e),
                        'status': 'not_found'
                    })
            
            result['replica_details'] = replica_details
        
        # Compare with memory state
        dr_registry = gateway.virtualization_orchestrator.registry
        memory_replicas = dr_registry.digital_twin_replicas.get(twin_id, set())
        
        result['consistency_check'] = {
            'persistent_count': len(replica_ids),
            'memory_count': len(memory_replicas),
            'consistent': replica_ids == memory_replicas,
            'memory_replica_ids': [str(rid) for rid in memory_replicas]
        }
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to get twin replicas: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get replicas: {e}"
        )


@router.get("/replica/{replica_id}/twin", summary="Find Twin for Replica")
async def find_twin_for_replica(
    replica_id: UUID = Path(..., description="Digital Replica ID"),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """
    Trova il Digital Twin associato a una replica usando storage persistente
    """
    try:
        # Use persistent Association Manager
        association_manager = await get_association_manager()
        twin_id = await association_manager.get_twin_for_replica(replica_id)
        
        if not twin_id:
            # Fallback: Try to find from replica metadata
            dr_registry = gateway.virtualization_orchestrator.registry
            try:
                replica = await dr_registry.get_digital_replica(replica_id)
                
                # Try parent_digital_twin_id property
                if hasattr(replica, 'parent_digital_twin_id'):
                    twin_id = replica.parent_digital_twin_id
                else:
                    # Try metadata custom
                    metadata_dict = replica.metadata.to_dict() if hasattr(replica.metadata, 'to_dict') else replica.metadata
                    custom_data = metadata_dict.get('custom', {})
                    parent_twin_str = custom_data.get('parent_twin_id')
                    if parent_twin_str:
                        twin_id = UUID(parent_twin_str)
                
                # If found via metadata, create persistent association
                if twin_id:
                    logger.info(f"Found twin via metadata, creating persistent association: {replica_id} -> {twin_id}")
                    await association_manager.create_association(
                        twin_id=twin_id,
                        replica_id=replica_id,
                        association_type='data_source'
                    )
                    
            except Exception as e:
                logger.warning(f"Failed metadata fallback for replica {replica_id}: {e}")
        
        if not twin_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No Digital Twin found for replica {replica_id}"
            )
        
        # Verify twin exists
        dt_registry = gateway.dt_orchestrator.registry
        try:
            twin = await dt_registry.get_digital_twin(twin_id)
            twin_info = {
                'exists': True,
                'type': str(type(twin)),
                'name': getattr(twin, 'name', 'unknown')
            }
        except Exception as e:
            twin_info = {
                'exists': False,
                'error': str(e)
            }
        
        return {
            'replica_id': str(replica_id),
            'twin_id': str(twin_id),
            'twin_info': twin_info,
            'found_via': 'persistent_storage',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to find twin for replica: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {e}"
        )


@router.get("/debug", summary="Debug All Associations")
async def debug_all_associations(
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """
    Debug completo di tutte le associazioni - mostra differenze tra storage e memoria
    """
    try:
        # Get Association Manager data
        association_manager = await get_association_manager()
        persistent_associations = await association_manager.get_all_associations()
        
        # Get Registry data
        dr_registry = gateway.virtualization_orchestrator.registry
        memory_associations = dr_registry.digital_twin_replicas
        
        # Compare and find discrepancies
        discrepancies = []
        all_twin_ids = set(persistent_associations.keys()) | set(memory_associations.keys())
        
        for twin_id in all_twin_ids:
            persistent_replicas = persistent_associations.get(twin_id, set())
            memory_replicas = memory_associations.get(twin_id, set())
            
            if persistent_replicas != memory_replicas:
                discrepancies.append({
                    'twin_id': str(twin_id),
                    'persistent_count': len(persistent_replicas),
                    'memory_count': len(memory_replicas),
                    'persistent_only': [str(r) for r in persistent_replicas - memory_replicas],
                    'memory_only': [str(r) for r in memory_replicas - persistent_replicas]
                })
        
        # Association Manager stats
        manager_stats = await association_manager.get_statistics()
        
        return {
            'total_persistent_associations': sum(len(replicas) for replicas in persistent_associations.values()),
            'total_memory_associations': sum(len(replicas) for replicas in memory_associations.values()),
            'twins_in_persistent': len(persistent_associations),
            'twins_in_memory': len(memory_associations),
            'discrepancies_count': len(discrepancies),
            'discrepancies': discrepancies,
            'manager_stats': manager_stats,
            'sample_persistent': {
                str(k): [str(r) for r in v] 
                for k, v in list(persistent_associations.items())[:3]
            },
            'sample_memory': {
                str(k): [str(r) for r in v] 
                for k, v in list(memory_associations.items())[:3]
            },
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Debug failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Debug failed: {e}"
        )