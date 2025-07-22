from fastapi import APIRouter, Depends, HTTPException, status
from src.layers.application.api_gateway import APIGateway
from src.layers.application.api import get_gateway
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/restore-associations", summary="Restore All System Associations")
async def restore_system_associations(
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Restore all associations after system restart."""
    try:
        result = await gateway.restore_all_associations()
        return result
    except Exception as e:
        logger.error(f"Failed to restore system associations: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Association restoration failed: {e}"
        )


@router.get("/health", summary="System Health Check")
async def system_health(
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    """Get comprehensive system health status."""
    try:
        health_status = await gateway.get_gateway_status()
        
        # Additional health checks
        health_status["associations"] = {
            "replica_count": 0,
            "device_associations": 0,
            "twin_replica_links": 0
        }
        
        # Count current associations
        if gateway.virtualization_orchestrator:
            registry = gateway.virtualization_orchestrator.registry
            replicas = await registry.list()
            health_status["associations"]["replica_count"] = len(replicas)
            health_status["associations"]["device_associations"] = len(registry.device_associations)
        
        if gateway.dt_orchestrator:
            twins = await gateway.dt_orchestrator.registry.list()
            health_status["associations"]["twin_count"] = len(twins)
        
        return health_status
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Health check failed: {e}"
        )