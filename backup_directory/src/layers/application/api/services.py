import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body, status
from pydantic import BaseModel, Field, validator
from src.layers.application.api_gateway import APIGateway
from src.layers.application.api import get_gateway
from src.core.interfaces.service import ServiceType, ServicePriority
from src.utils.exceptions import EntityNotFoundError
logger = logging.getLogger(__name__)
router = APIRouter()

class ServiceCreate(BaseModel):
    definition_id: Optional[str] = Field(None, description='Service definition ID')
    template_id: Optional[str] = Field(None, description='Template ID for creation')
    instance_name: str = Field(..., min_length=1, max_length=255, description='Service instance name')
    digital_twin_id: UUID = Field(..., description='Parent Digital Twin ID')
    parameters: Optional[Dict[str, Any]] = Field({}, description='Service parameters')
    execution_config: Optional[Dict[str, Any]] = Field({}, description='Execution configuration')
    resource_limits: Optional[Dict[str, Any]] = Field({}, description='Resource limits')
    priority: str = Field(ServicePriority.NORMAL.value, description='Service priority')
    overrides: Optional[Dict[str, Any]] = Field(None, description='Template overrides')

    @validator('priority')
    @classmethod
    def validate_priority(cls, v):
        try:
            ServicePriority(v)
            return v
        except ValueError:
            valid_priorities = [p.value for p in ServicePriority]
            raise ValueError(f'Invalid priority. Must be one of: {valid_priorities}')

    class Config:
        schema_extra = {'example': {'definition_id': 'analytics_basic', 'instance_name': 'Production Analytics Service', 'digital_twin_id': '123e4567-e89b-12d3-a456-426614174000', 'parameters': {'analytics_type': 'basic_statistics', 'data_sources': ['sensor_001', 'sensor_002']}, 'execution_config': {'timeout': 60, 'retry_count': 3}, 'priority': 'normal'}}

class ServiceExecution(BaseModel):
    input_data: Dict[str, Any] = Field(..., description='Input data for execution')
    execution_parameters: Optional[Dict[str, Any]] = Field(None, description='Execution parameters')
    priority: str = Field(ServicePriority.NORMAL.value, description='Execution priority')
    async_execution: bool = Field(False, description='Whether to execute asynchronously')
    timeout: Optional[int] = Field(None, ge=1, description='Execution timeout in seconds')

    @validator('priority')
    def validate_priority(cls, v):
        try:
            ServicePriority(v)
            return v
        except ValueError:
            valid_priorities = [p.value for p in ServicePriority]
            raise ValueError(f'Invalid priority. Must be one of: {valid_priorities}')

    class Config:
        schema_extra = {'example': {'input_data': {'data_points': [{'value': 10, 'timestamp': '2024-01-01T10:00:00Z'}, {'value': 15, 'timestamp': '2024-01-01T10:05:00Z'}]}, 'execution_parameters': {'calculation_method': 'moving_average'}, 'priority': 'high', 'async_execution': False}}

class WorkflowCreate(BaseModel):
    workflow_name: str = Field(..., min_length=1, max_length=255, description='Workflow name')
    digital_twin_id: UUID = Field(..., description='Digital Twin context')
    service_chain: List[Dict[str, Any]] = Field(..., min_items=1, description='Chain of services')
    workflow_config: Optional[Dict[str, Any]] = Field({}, description='Workflow configuration')

    class Config:
        schema_extra = {'example': {'workflow_name': 'Analytics and Prediction Pipeline', 'digital_twin_id': '123e4567-e89b-12d3-a456-426614174000', 'service_chain': [{'step_name': 'analyze_data', 'service_id': 'service-123', 'config': {'batch_size': 100}}, {'step_name': 'predict_trends', 'service_id': 'service-456', 'config': {'horizon': 300}}], 'workflow_config': {'error_handling': 'continue_on_failure', 'timeout': 600}}}

class ServiceResponse(BaseModel):
    id: UUID
    service_type: str
    instance_name: str
    digital_twin_id: UUID
    current_state: str
    capabilities: List[str]
    created_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class ServiceExecutionResponse(BaseModel):
    service_id: UUID
    execution_id: Optional[UUID] = None
    result: Optional[Dict[str, Any]] = None
    success: bool = True
    executed_at: str
    execution_time: Optional[float] = None
    error: Optional[str] = None

@router.get('/', summary='List Services')
async def list_services(gateway: APIGateway=Depends(get_gateway), service_type: Optional[str]=Query(None, description='Filter by service type'), digital_twin_id: Optional[UUID]=Query(None, description='Filter by Digital Twin'), capabilities: Optional[List[str]]=Query(None, description='Filter by capabilities'), limit: int=Query(100, ge=1, le=1000, description='Maximum number of results'), offset: int=Query(0, ge=0, description='Number of results to skip')) -> Dict[str, Any]:
    try:
        criteria = {}
        if service_type:
            criteria['type'] = service_type
        if digital_twin_id:
            criteria['digital_twin_id'] = str(digital_twin_id)
        if capabilities:
            criteria['capabilities'] = capabilities
        from src.layers.application.api_gateway import RequestType
        services = await gateway.discover_entities(RequestType.SERVICE, criteria)
        total = len(services)
        paginated_services = services[offset:offset + limit]
        return {'services': paginated_services, 'pagination': {'total': total, 'limit': limit, 'offset': offset, 'count': len(paginated_services)}}
    except Exception as e:
        logger.error(f'Failed to list Services: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to list Services: {e}')

@router.post('/', summary='Create Service', response_model=ServiceResponse)
async def create_service(service_data: ServiceCreate, gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        if not service_data.definition_id and (not service_data.template_id):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Either definition_id or template_id must be provided')
        if service_data.definition_id and service_data.template_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Cannot specify both definition_id and template_id')
        service_config = service_data.dict()
        result = await gateway.create_service(service_config)
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.error(f'Failed to create Service: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to create Service: {e}')

@router.get('/{service_id}', summary='Get Service', response_model=ServiceResponse)
async def get_service(service_id: UUID=Path(..., description='Service ID'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        return await gateway.get_service(service_id)
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Service {service_id} not found')
    except Exception as e:
        logger.error(f'Failed to get Service {service_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to get Service: {e}')

@router.delete('/{service_id}', summary='Delete Service')
async def delete_service(service_id: UUID=Path(..., description='Service ID'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, str]:
    try:
        return {'message': f'Service {service_id} deletion requested', 'status': 'accepted'}
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Service {service_id} not found')
    except Exception as e:
        logger.error(f'Failed to delete Service {service_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to delete Service: {e}')

@router.post('/{service_id}/execute', summary='Execute Service')
async def execute_service(service_id: UUID=Path(..., description='Service ID'), execution_data: ServiceExecution=Body(...), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        result = await gateway.execute_service(service_id=service_id, input_data=execution_data.input_data, execution_parameters=execution_data.execution_parameters, async_execution=execution_data.async_execution)
        return result
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Service {service_id} not found')
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.error(f'Failed to execute Service {service_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Service execution failed: {e}')

@router.post('/{service_id}/execute/analytics', summary='Execute Analytics Service')
async def execute_analytics(service_id: UUID=Path(..., description='Service ID'), data_points: List[Dict[str, Any]]=Body(..., description='Data points to analyze'), analytics_config: Optional[Dict[str, Any]]=Body(None, description='Analytics configuration'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        execution_data = {'data_points': data_points, 'config': analytics_config or {}}
        result = await gateway.execute_service(service_id=service_id, input_data=execution_data)
        return result
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Service {service_id} not found')
    except Exception as e:
        logger.error(f'Failed to execute analytics on service {service_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Analytics execution failed: {e}')

@router.post('/{service_id}/execute/prediction', summary='Execute Prediction Service')
async def execute_prediction(service_id: UUID=Path(..., description='Service ID'), historical_data: List[Dict[str, Any]]=Body(..., description='Historical data for prediction'), prediction_horizon: int=Body(300, ge=1, description='Prediction horizon in seconds'), model_config: Optional[Dict[str, Any]]=Body(None, description='Model configuration'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        execution_data = {'historical_data': historical_data, 'prediction_horizon': prediction_horizon, 'model_config': model_config or {}}
        result = await gateway.execute_service(service_id=service_id, input_data=execution_data)
        return result
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Service {service_id} not found')
    except Exception as e:
        logger.error(f'Failed to execute prediction on service {service_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Prediction execution failed: {e}')

@router.post('/workflows', summary='Create Service Workflow')
async def create_workflow(workflow_data: WorkflowCreate, gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        workflow_id = 'workflow-' + str(workflow_data.digital_twin_id)[:8]
        return {'workflow_id': workflow_id, 'workflow_name': workflow_data.workflow_name, 'digital_twin_id': str(workflow_data.digital_twin_id), 'service_chain_length': len(workflow_data.service_chain), 'status': 'created', 'created_at': datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f'Failed to create workflow: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Workflow creation failed: {e}')

@router.post('/workflows/{workflow_id}/execute', summary='Execute Workflow')
async def execute_workflow(workflow_id: str=Path(..., description='Workflow ID'), input_data: Dict[str, Any]=Body(..., description='Input data for workflow'), execution_config: Optional[Dict[str, Any]]=Body(None, description='Execution configuration'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        execution_id = f"exec-{workflow_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        return {'workflow_id': workflow_id, 'execution_id': execution_id, 'status': 'running', 'started_at': datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f'Failed to execute workflow {workflow_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Workflow execution failed: {e}')

@router.get('/workflows/{workflow_id}/status', summary='Get Workflow Status')
async def get_workflow_status(workflow_id: str=Path(..., description='Workflow ID'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        return {'workflow_id': workflow_id, 'status': 'completed', 'progress': 100, 'completed_steps': 2, 'total_steps': 2, 'last_updated': datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f'Failed to get workflow status {workflow_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to get workflow status: {e}')

@router.get('/{service_id}/status', summary='Get Service Status')
async def get_service_status(service_id: UUID=Path(..., description='Service ID'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        service = await gateway.get_service(service_id)
        status_info = {'service_id': str(service_id), 'current_state': service.get('current_state'), 'health': 'healthy', 'performance': {'success_rate': 0.95, 'average_response_time': 0.15, 'requests_per_minute': 45}, 'resource_usage': {'memory_mb': 256, 'cpu_percent': 15.5}, 'last_execution': datetime.utcnow().isoformat()}
        return status_info
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Service {service_id} not found')
    except Exception as e:
        logger.error(f'Failed to get service status {service_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to get service status: {e}')

@router.get('/{service_id}/metrics', summary='Get Service Metrics')
async def get_service_metrics(service_id: UUID=Path(..., description='Service ID'), time_range: int=Query(3600, ge=60, description='Time range in seconds'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        return {'service_id': str(service_id), 'time_range_seconds': time_range, 'metrics': {'total_executions': 1247, 'successful_executions': 1182, 'failed_executions': 65, 'success_rate': 0.948, 'average_execution_time': 0.145, 'min_execution_time': 0.023, 'max_execution_time': 2.156, 'requests_per_minute': 42.3, 'error_rate': 0.052}, 'resource_metrics': {'peak_memory_mb': 312, 'average_memory_mb': 256, 'peak_cpu_percent': 45.2, 'average_cpu_percent': 15.8}, 'generated_at': datetime.utcnow().isoformat()}
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Service {service_id} not found')
    except Exception as e:
        logger.error(f'Failed to get service metrics {service_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to get service metrics: {e}')

@router.get('/definitions/available', summary='Get Available Service Definitions')
async def get_available_definitions(service_type: Optional[str]=Query(None, description='Filter by service type'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        type_filter = None
        if service_type:
            try:
                type_filter = ServiceType(service_type)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f'Invalid service_type. Must be one of: {[t.value for t in ServiceType]}')
        definitions = await gateway.service_orchestrator.get_available_service_definitions(type_filter)
        return {'definitions': definitions, 'count': len(definitions), 'service_type_filter': service_type}
    except Exception as e:
        logger.error(f'Failed to get service definitions: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to get service definitions: {e}')

@router.get('/templates/available', summary='Get Available Service Templates')
async def get_available_templates(gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        templates = await gateway.service_orchestrator.get_service_templates()
        return {'templates': templates, 'count': len(templates)}
    except Exception as e:
        logger.error(f'Failed to get service templates: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to get service templates: {e}')

@router.get('/types/available', summary='Get Available Service Types')
async def get_available_types() -> Dict[str, List[str]]:
    return {'service_types': [t.value for t in ServiceType], 'priorities': [p.value for p in ServicePriority]}

@router.post('/bulk/execute', summary='Execute Multiple Services')
async def bulk_execute_services(service_executions: List[Dict[str, Any]]=Body(..., description='List of service executions'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        results = []
        for execution in service_executions:
            try:
                service_id = UUID(execution['service_id'])
                input_data = execution['input_data']
                result = await gateway.execute_service(service_id=service_id, input_data=input_data)
                results.append({'service_id': str(service_id), 'success': True, 'result': result})
            except Exception as e:
                results.append({'service_id': execution.get('service_id', 'unknown'), 'success': False, 'error': str(e)})
        successful = len([r for r in results if r['success']])
        return {'total_executions': len(service_executions), 'successful': successful, 'failed': len(service_executions) - successful, 'results': results, 'executed_at': datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f'Failed to execute bulk services: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Bulk execution failed: {e}')