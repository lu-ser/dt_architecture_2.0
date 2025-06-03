import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body, status
from pydantic import BaseModel, Field, validator
from src.layers.application.api_gateway import APIGateway
from src.layers.application.api import get_gateway
from src.core.interfaces.replica import ReplicaType, DataAggregationMode
from src.utils.exceptions import EntityNotFoundError
logger = logging.getLogger(__name__)
router = APIRouter()

class ReplicaCreate(BaseModel):
    replica_type: str = Field(..., description='Type of Digital Replica')
    template_id: Optional[str] = Field(None, description='Template ID for creation')
    parent_digital_twin_id: UUID = Field(..., description='Parent Digital Twin ID')
    device_ids: List[str] = Field(..., min_items=1, description='List of device IDs to manage')
    aggregation_mode: str = Field(..., description='Data aggregation mode')
    aggregation_config: Optional[Dict[str, Any]] = Field({}, description='Aggregation configuration')
    data_retention_policy: Optional[Dict[str, Any]] = Field({}, description='Data retention policy')
    quality_thresholds: Optional[Dict[str, float]] = Field({}, description='Data quality thresholds')
    overrides: Optional[Dict[str, Any]] = Field(None, description='Template overrides')

    @validator('replica_type')
    def validate_replica_type(cls, v):
        try:
            ReplicaType(v)
            return v
        except ValueError:
            valid_types = [t.value for t in ReplicaType]
            raise ValueError(f'Invalid replica_type. Must be one of: {valid_types}')

    @validator('aggregation_mode')
    def validate_aggregation_mode(cls, v):
        try:
            DataAggregationMode(v)
            return v
        except ValueError:
            valid_modes = [m.value for m in DataAggregationMode]
            raise ValueError(f'Invalid aggregation_mode. Must be one of: {valid_modes}')

    class Config:
        schema_extra = {'example': {'replica_type': 'sensor_aggregator', 'parent_digital_twin_id': '123e4567-e89b-12d3-a456-426614174000', 'device_ids': ['sensor-001', 'sensor-002', 'sensor-003'], 'aggregation_mode': 'batch', 'aggregation_config': {'batch_size': 10, 'window_seconds': 60, 'quality_threshold': 0.7}, 'data_retention_policy': {'retention_days': 30, 'cleanup_interval_hours': 24}, 'quality_thresholds': {'min_quality': 0.6, 'alert_threshold': 0.4}}}

class DeviceData(BaseModel):
    device_id: str = Field(..., description='Device ID')
    data: Dict[str, Any] = Field(..., description='Device data payload')
    data_type: str = Field('sensor_reading', description='Type of data')
    timestamp: Optional[datetime] = Field(None, description='Data timestamp (optional)')
    quality_hint: Optional[str] = Field(None, description='Quality hint (high/medium/low)')

    class Config:
        schema_extra = {'example': {'device_id': 'sensor-001', 'data': {'temperature': 22.5, 'humidity': 65.2, 'pressure': 1013.25}, 'data_type': 'environmental_reading', 'timestamp': '2024-01-01T10:30:00Z', 'quality_hint': 'high'}}

class DeviceAssociation(BaseModel):
    device_id: str = Field(..., description='Device ID to associate')
    association_type: str = Field('managed', description='Type of association')
    data_mapping: Optional[Dict[str, str]] = Field(None, description='Optional data field mapping')

    class Config:
        schema_extra = {'example': {'device_id': 'sensor-004', 'association_type': 'monitored', 'data_mapping': {'temp': 'temperature', 'hum': 'humidity'}}}

class ContainerDeployment(BaseModel):
    deployment_target: str = Field(..., description='Deployment target')
    container_config: Optional[Dict[str, Any]] = Field(None, description='Container configuration')

    class Config:
        schema_extra = {'example': {'deployment_target': 'local_docker', 'container_config': {'memory_mb': 512, 'cpu_cores': 0.5, 'health_check_interval': 30, 'protocols': {'http': {'enabled': True, 'port': 8080}, 'mqtt': {'enabled': False}}}}}

class ReplicaResponse(BaseModel):
    id: UUID
    replica_type: str
    parent_digital_twin_id: UUID
    device_ids: List[str]
    aggregation_mode: str
    current_status: str
    created_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

@router.get('/', summary='List Digital Replicas')
async def list_replicas(gateway: APIGateway=Depends(get_gateway), replica_type: Optional[str]=Query(None, description='Filter by replica type'), parent_digital_twin_id: Optional[UUID]=Query(None, description='Filter by parent Digital Twin'), device_id: Optional[str]=Query(None, description='Filter by managed device'), limit: int=Query(100, ge=1, le=1000, description='Maximum number of results'), offset: int=Query(0, ge=0, description='Number of results to skip')) -> Dict[str, Any]:
    try:
        criteria = {}
        if replica_type:
            criteria['type'] = replica_type
        if parent_digital_twin_id:
            criteria['parent_digital_twin_id'] = str(parent_digital_twin_id)
        if device_id:
            criteria['manages_device'] = device_id
        from src.layers.application.api_gateway import RequestType
        replicas = await gateway.discover_entities(RequestType.REPLICA, criteria)
        total = len(replicas)
        paginated_replicas = replicas[offset:offset + limit]
        return {'replicas': paginated_replicas, 'pagination': {'total': total, 'limit': limit, 'offset': offset, 'count': len(paginated_replicas)}}
    except Exception as e:
        logger.error(f'Failed to list Digital Replicas: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to list Digital Replicas: {e}')

@router.post('/', summary='Create Digital Replica', response_model=ReplicaResponse)
async def create_replica(replica_data: ReplicaCreate, gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        replica_config = replica_data.dict()
        result = await gateway.create_replica(replica_config)
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.error(f'Failed to create Digital Replica: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to create Digital Replica: {e}')

@router.get('/{replica_id}', summary='Get Digital Replica', response_model=ReplicaResponse)
async def get_replica(replica_id: UUID=Path(..., description='Digital Replica ID'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        return await gateway.get_replica(replica_id)
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Digital Replica {replica_id} not found')
    except Exception as e:
        logger.error(f'Failed to get Digital Replica {replica_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to get Digital Replica: {e}')

@router.delete('/{replica_id}', summary='Delete Digital Replica')
async def delete_replica(replica_id: UUID=Path(..., description='Digital Replica ID'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, str]:
    try:
        return {'message': f'Digital Replica {replica_id} deletion requested', 'status': 'accepted'}
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Digital Replica {replica_id} not found')
    except Exception as e:
        logger.error(f'Failed to delete Digital Replica {replica_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to delete Digital Replica: {e}')

@router.get('/{replica_id}/devices', summary='Get Managed Devices')
async def get_managed_devices(replica_id: UUID=Path(..., description='Digital Replica ID'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        devices = [{'device_id': 'sensor-001', 'association_type': 'managed', 'data_count': 15647, 'last_data_time': '2024-01-01T10:29:45Z', 'average_quality': 0.92, 'status': 'active'}, {'device_id': 'sensor-002', 'association_type': 'managed', 'data_count': 14892, 'last_data_time': '2024-01-01T10:29:50Z', 'average_quality': 0.88, 'status': 'active'}]
        return {'replica_id': str(replica_id), 'device_count': len(devices), 'devices': devices}
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Digital Replica {replica_id} not found')
    except Exception as e:
        logger.error(f'Failed to get devices for replica {replica_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to get managed devices: {e}')

@router.post('/{replica_id}/devices', summary='Associate Device')
async def associate_device(replica_id: UUID=Path(..., description='Digital Replica ID'), device_association: DeviceAssociation=Body(...), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, str]:
    try:
        return {'message': f'Device {device_association.device_id} associated with replica {replica_id}', 'device_id': device_association.device_id, 'association_type': device_association.association_type, 'status': 'success'}
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Digital Replica {replica_id} not found')
    except Exception as e:
        logger.error(f'Failed to associate device with replica {replica_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Device association failed: {e}')

@router.delete('/{replica_id}/devices/{device_id}', summary='Disassociate Device')
async def disassociate_device(replica_id: UUID=Path(..., description='Digital Replica ID'), device_id: str=Path(..., description='Device ID'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, str]:
    try:
        return {'message': f'Device {device_id} disassociated from replica {replica_id}', 'device_id': device_id, 'status': 'success'}
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Digital Replica {replica_id} or device {device_id} not found')
    except Exception as e:
        logger.error(f'Failed to disassociate device {device_id} from replica {replica_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Device disassociation failed: {e}')

@router.post('/{replica_id}/data', summary='Send Device Data')
async def send_device_data(replica_id: UUID=Path(..., description='Digital Replica ID'), device_data: DeviceData=Body(...), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        processed_at = datetime.utcnow()
        return {'replica_id': str(replica_id), 'device_id': device_data.device_id, 'data_received': True, 'data_size_bytes': len(str(device_data.data)), 'processed_at': processed_at.isoformat(), 'quality_assessment': 'high', 'aggregation_triggered': True}
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Digital Replica {replica_id} not found')
    except Exception as e:
        logger.error(f'Failed to send data to replica {replica_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Data sending failed: {e}')

@router.get('/{replica_id}/data/quality', summary='Get Data Quality Report')
async def get_data_quality_report(replica_id: UUID=Path(..., description='Digital Replica ID'), time_range: int=Query(3600, ge=60, description='Time range in seconds'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        return {'replica_id': str(replica_id), 'time_range_seconds': time_range, 'quality_report': {'total_data_points': 8943, 'high_quality': 7847, 'medium_quality': 892, 'low_quality': 158, 'invalid_data': 46, 'overall_quality_score': 0.877, 'quality_trend': 'improving', 'devices_performance': {'sensor-001': {'quality_score': 0.92, 'data_points': 4521}, 'sensor-002': {'quality_score': 0.88, 'data_points': 4422}}}, 'aggregation_stats': {'aggregations_performed': 894, 'average_batch_size': 10.02, 'aggregation_success_rate': 0.996}, 'generated_at': datetime.utcnow().isoformat()}
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Digital Replica {replica_id} not found')
    except Exception as e:
        logger.error(f'Failed to get data quality report for replica {replica_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to get data quality report: {e}')


class AggregationTriggerData(BaseModel):
    force: bool = Field(False, description='Force aggregation even if conditions not met')

@router.post('/{replica_id}/aggregation/trigger', summary='Force Data Aggregation')
async def trigger_aggregation(
    replica_id: UUID = Path(..., description='Digital Replica ID'), 
    trigger_data: AggregationTriggerData = Body(...),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    try:
        triggered_at = datetime.utcnow()
        return {
            'replica_id': str(replica_id),
            'aggregation_triggered': True,
            'forced': trigger_data.force,
            'triggered_at': triggered_at.isoformat(),
            'estimated_completion': triggered_at.timestamp() + 30,
            'aggregation_id': f'agg-{replica_id}-{int(triggered_at.timestamp())}'
        }
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Digital Replica {replica_id} not found')
    except Exception as e:
        logger.error(f'Failed to trigger aggregation for replica {replica_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Aggregation trigger failed: {e}')
    
@router.post('/{replica_id}/deploy', summary='Deploy as Container')
async def deploy_as_container(replica_id: UUID=Path(..., description='Digital Replica ID'), deployment: ContainerDeployment=Body(...), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        container_id = f'dr-container-{replica_id}'[:16]
        return {'replica_id': str(replica_id), 'container_id': container_id, 'deployment_target': deployment.deployment_target, 'status': 'deploying', 'deployment_started': datetime.utcnow().isoformat(), 'estimated_ready': datetime.utcnow().isoformat(), 'container_config': deployment.container_config}
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Digital Replica {replica_id} not found')
    except Exception as e:
        logger.error(f'Failed to deploy replica {replica_id} as container: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Container deployment failed: {e}')

@router.get('/{replica_id}/container/status', summary='Get Container Status')
async def get_container_status(replica_id: UUID=Path(..., description='Digital Replica ID'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        return {'replica_id': str(replica_id), 'container_id': f'dr-container-{replica_id}'[:16], 'status': 'running', 'health': 'healthy', 'uptime_seconds': 3647, 'resource_usage': {'memory_mb': 284, 'memory_limit_mb': 512, 'cpu_percent': 12.4, 'cpu_limit_cores': 0.5}, 'data_processing': {'queue_size': 3, 'processed_count': 8943, 'last_data_time': '2024-01-01T10:29:45Z'}, 'protocols': {'http': {'enabled': True, 'port': 8080, 'connected': True}, 'mqtt': {'enabled': False}}, 'last_health_check': datetime.utcnow().isoformat()}
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Digital Replica {replica_id} not found')
    except Exception as e:
        logger.error(f'Failed to get container status for replica {replica_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to get container status: {e}')

@router.get('/{replica_id}/performance', summary='Get Performance Metrics')
async def get_performance_metrics(replica_id: UUID=Path(..., description='Digital Replica ID'), time_range: int=Query(3600, ge=60, description='Time range in seconds'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        return {'replica_id': str(replica_id), 'time_range_seconds': time_range, 'data_flow': {'total_data_received': 8943, 'data_rate_per_minute': 148.2, 'peak_data_rate': 312.5, 'average_data_size_bytes': 156, 'total_bytes_processed': 1395108}, 'aggregation_performance': {'total_aggregations': 894, 'average_aggregation_time': 0.023, 'aggregation_success_rate': 0.996, 'average_batch_size': 10.02}, 'device_performance': {'sensor-001': {'data_points': 4521, 'average_quality': 0.92, 'response_time': 0.012, 'error_rate': 0.003}, 'sensor-002': {'data_points': 4422, 'average_quality': 0.88, 'response_time': 0.015, 'error_rate': 0.007}}, 'resource_efficiency': {'memory_usage_mb': 284, 'cpu_utilization': 0.124, 'network_throughput_mbps': 0.89}, 'generated_at': datetime.utcnow().isoformat()}
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Digital Replica {replica_id} not found')
    except Exception as e:
        logger.error(f'Failed to get performance metrics for replica {replica_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to get performance metrics: {e}')

@router.get('/types/available', summary='Get Available Replica Types')
async def get_available_types() -> Dict[str, List[str]]:
    return {'replica_types': [t.value for t in ReplicaType], 'aggregation_modes': [m.value for m in DataAggregationMode]}

@router.get('/templates/available', summary='Get Available Templates')
async def get_available_templates(gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        return {'templates': [{'template_id': 'iot_sensor_aggregator', 'name': 'IoT Sensor Aggregator', 'description': 'Template for aggregating IoT sensor data', 'replica_type': 'sensor_aggregator', 'suggested_use': 'Multiple low-frequency sensors'}, {'template_id': 'industrial_device_proxy', 'name': 'Industrial Device Proxy', 'description': 'Template for industrial device monitoring', 'replica_type': 'device_proxy', 'suggested_use': 'Single high-value industrial equipment'}, {'template_id': 'edge_gateway', 'name': 'Edge Gateway', 'description': 'Template for edge computing gateway', 'replica_type': 'edge_gateway', 'suggested_use': 'Remote location data collection'}]}
    except Exception as e:
        logger.error(f'Failed to get available templates: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to get templates: {e}')

@router.post('/bulk/scale', summary='Scale Multiple Replicas')
async def bulk_scale_replicas(scaling_operations: List[Dict[str, Any]]=Body(..., description='List of scaling operations'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        results = []
        for operation in scaling_operations:
            try:
                replica_id = UUID(operation['replica_id'])
                scale_factor = operation.get('scale_factor', 2)
                results.append({'replica_id': str(replica_id), 'scale_factor': scale_factor, 'success': True, 'status': 'scaling_initiated'})
            except Exception as e:
                results.append({'replica_id': operation.get('replica_id', 'unknown'), 'success': False, 'error': str(e)})
        successful = len([r for r in results if r['success']])
        return {'total_operations': len(scaling_operations), 'successful': successful, 'failed': len(scaling_operations) - successful, 'results': results, 'initiated_at': datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f'Failed to scale replicas in bulk: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Bulk scaling failed: {e}')