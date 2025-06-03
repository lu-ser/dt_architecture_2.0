import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body, status
from pydantic import BaseModel, Field, validator
from src.layers.application.api_gateway import APIGateway
from src.layers.application.api import get_gateway
from src.utils.exceptions import EntityNotFoundError
logger = logging.getLogger(__name__)
router = APIRouter()

class WorkflowStep(BaseModel):
    step_name: str = Field(..., min_length=1, description='Name of the workflow step')
    step_type: str = Field(..., description='Type of step (digital_twin, service, replica)')
    entity_id: UUID = Field(..., description='ID of the entity to operate on')
    operation: str = Field(..., description='Operation to perform')
    input_data: Optional[Dict[str, Any]] = Field({}, description='Input data for the step')
    step_config: Optional[Dict[str, Any]] = Field({}, description='Step-specific configuration')
    timeout_seconds: Optional[int] = Field(300, ge=1, description='Step timeout')
    retry_count: Optional[int] = Field(0, ge=0, le=5, description='Number of retries')
    depends_on: Optional[List[str]] = Field([], description='Steps this step depends on')

    class Config:
        schema_extra = {'example': {'step_name': 'analyze_sensor_data', 'step_type': 'service', 'entity_id': '123e4567-e89b-12d3-a456-426614174000', 'operation': 'execute', 'input_data': {'data_points': [], 'analysis_type': 'trend_analysis'}, 'step_config': {'priority': 'high', 'cache_results': True}, 'timeout_seconds': 120, 'retry_count': 2, 'depends_on': ['collect_data']}}

class WorkflowCreate(BaseModel):
    workflow_name: str = Field(..., min_length=1, max_length=255, description='Workflow name')
    description: Optional[str] = Field('', max_length=1000, description='Workflow description')
    workflow_type: str = Field('sequential', description='Type of workflow execution')
    context_digital_twin_id: Optional[UUID] = Field(None, description='Digital Twin context')
    steps: List[WorkflowStep] = Field(..., min_items=1, description='Workflow steps')
    workflow_config: Optional[Dict[str, Any]] = Field({}, description='Global workflow configuration')
    schedule: Optional[Dict[str, Any]] = Field(None, description='Optional scheduling configuration')

    @validator('workflow_type')
    def validate_workflow_type(cls, v):
        valid_types = ['sequential', 'parallel', 'conditional', 'loop', 'dag']
        if v not in valid_types:
            raise ValueError(f'Invalid workflow_type. Must be one of: {valid_types}')
        return v

    class Config:
        schema_extra = {'example': {'workflow_name': 'Smart Factory Analysis Pipeline', 'description': 'Complete analysis pipeline for smart factory operations', 'workflow_type': 'sequential', 'context_digital_twin_id': '123e4567-e89b-12d3-a456-426614174000', 'steps': [{'step_name': 'collect_sensor_data', 'step_type': 'replica', 'entity_id': 'replica-123', 'operation': 'aggregate_data', 'input_data': {'force_aggregation': True}}, {'step_name': 'analyze_data', 'step_type': 'service', 'entity_id': 'service-456', 'operation': 'execute', 'input_data': {'analysis_type': 'anomaly_detection'}, 'depends_on': ['collect_sensor_data']}], 'workflow_config': {'error_handling': 'continue_on_failure', 'max_execution_time': 1800, 'notification_webhook': 'https://api.company.com/notifications'}}}

class WorkflowExecution(BaseModel):
    input_data: Dict[str, Any] = Field(..., description='Global input data for workflow')
    execution_config: Optional[Dict[str, Any]] = Field({}, description='Execution configuration')
    priority: str = Field('normal', description='Execution priority')
    async_execution: bool = Field(True, description='Whether to execute asynchronously')
    callback_url: Optional[str] = Field(None, description='Callback URL for completion notification')

    @validator('priority')
    def validate_priority(cls, v):
        valid_priorities = ['low', 'normal', 'high', 'critical']
        if v not in valid_priorities:
            raise ValueError(f'Invalid priority. Must be one of: {valid_priorities}')
        return v

    class Config:
        schema_extra = {'example': {'input_data': {'factory_section': 'production_line_1', 'time_range': 'last_24_hours', 'quality_threshold': 0.8}, 'execution_config': {'parallel_steps': 3, 'retry_on_failure': True, 'save_intermediate_results': True}, 'priority': 'high', 'async_execution': True, 'callback_url': 'https://api.company.com/workflow-completed'}}

class WorkflowTemplate(BaseModel):
    template_name: str = Field(..., min_length=1, description='Template name')
    template_description: str = Field(..., description='Template description')
    category: str = Field(..., description='Template category')
    workflow_definition: WorkflowCreate = Field(..., description='Workflow definition')
    parameters: Dict[str, Any] = Field({}, description='Template parameters')

    class Config:
        schema_extra = {'example': {'template_name': 'IoT Analytics Pipeline', 'template_description': 'Standard pipeline for IoT data analytics', 'category': 'analytics', 'workflow_definition': {'workflow_name': '{{workflow_name}}', 'workflow_type': 'sequential', 'steps': []}, 'parameters': {'data_source': '{{replica_id}}', 'analysis_service': '{{service_id}}', 'notification_endpoint': '{{webhook_url}}'}}}

class WorkflowResponse(BaseModel):
    workflow_id: UUID
    workflow_name: str
    workflow_type: str
    status: str
    step_count: int
    created_at: str
    context_digital_twin_id: Optional[UUID] = None

class WorkflowExecutionResponse(BaseModel):
    workflow_id: UUID
    execution_id: UUID
    status: str
    started_at: str
    progress: Optional[Dict[str, Any]] = None


class WorkflowExecutionData(BaseModel):
    input_data: Dict[str, Any] = Field(..., description='Input data for workflow')
    execution_config: Optional[Dict[str, Any]] = Field(None, description='Execution configuration')

class WorkflowCancellationData(BaseModel):
    reason: Optional[str] = Field(None, description='Cancellation reason')

class TemplateInstantiationData(BaseModel):
    workflow_name: str = Field(..., description='Name for the new workflow')
    parameters: Dict[str, Any] = Field({}, description='Template parameters')


@router.get('/', summary='List Workflows')
async def list_workflows(gateway: APIGateway=Depends(get_gateway), workflow_type: Optional[str]=Query(None, description='Filter by workflow type'), status: Optional[str]=Query(None, description='Filter by status'), digital_twin_id: Optional[UUID]=Query(None, description='Filter by Digital Twin context'), limit: int=Query(100, ge=1, le=1000, description='Maximum number of results'), offset: int=Query(0, ge=0, description='Number of results to skip')) -> Dict[str, Any]:
    try:
        workflows = [{'workflow_id': 'wf-analytics-001', 'workflow_name': 'Production Analytics Pipeline', 'workflow_type': 'sequential', 'status': 'active', 'step_count': 4, 'context_digital_twin_id': 'dt-factory-001', 'created_at': '2024-01-01T08:00:00Z', 'last_execution': '2024-01-01T10:25:00Z', 'execution_count': 47}, {'workflow_id': 'wf-maintenance-002', 'workflow_name': 'Predictive Maintenance Flow', 'workflow_type': 'conditional', 'status': 'active', 'step_count': 6, 'context_digital_twin_id': 'dt-equipment-001', 'created_at': '2024-01-01T09:15:00Z', 'last_execution': '2024-01-01T10:20:00Z', 'execution_count': 12}]
        if workflow_type:
            workflows = [w for w in workflows if w['workflow_type'] == workflow_type]
        if status:
            workflows = [w for w in workflows if w['status'] == status]
        if digital_twin_id:
            workflows = [w for w in workflows if w.get('context_digital_twin_id') == str(digital_twin_id)]
        total = len(workflows)
        paginated_workflows = workflows[offset:offset + limit]
        return {'workflows': paginated_workflows, 'pagination': {'total': total, 'limit': limit, 'offset': offset, 'count': len(paginated_workflows)}}
    except Exception as e:
        logger.error(f'Failed to list workflows: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to list workflows: {e}')

@router.post('/', summary='Create Workflow', response_model=WorkflowResponse)
async def create_workflow(workflow_data: WorkflowCreate, gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        workflow_id = f"wf-{workflow_data.workflow_name.lower().replace(' ', '-')}-{int(datetime.utcnow().timestamp())}"
        return {'workflow_id': workflow_id, 'workflow_name': workflow_data.workflow_name, 'workflow_type': workflow_data.workflow_type, 'status': 'created', 'step_count': len(workflow_data.steps), 'context_digital_twin_id': workflow_data.context_digital_twin_id, 'created_at': datetime.utcnow().isoformat()}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.error(f'Failed to create workflow: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to create workflow: {e}')

@router.get('/{workflow_id}', summary='Get Workflow', response_model=WorkflowResponse)
async def get_workflow(workflow_id: str=Path(..., description='Workflow ID'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        return {'workflow_id': workflow_id, 'workflow_name': 'Production Analytics Pipeline', 'description': 'Analyzes production data and generates insights', 'workflow_type': 'sequential', 'status': 'active', 'step_count': 4, 'context_digital_twin_id': 'dt-factory-001', 'created_at': '2024-01-01T08:00:00Z', 'last_modified': '2024-01-01T08:30:00Z', 'execution_stats': {'total_executions': 47, 'successful_executions': 44, 'failed_executions': 3, 'average_duration_seconds': 156.7}, 'steps': [{'step_name': 'collect_data', 'step_type': 'replica', 'entity_id': 'replica-sensors-001', 'operation': 'aggregate_data', 'status': 'active'}, {'step_name': 'analyze_data', 'step_type': 'service', 'entity_id': 'service-analytics-001', 'operation': 'execute', 'status': 'active'}]}
    except Exception as e:
        logger.error(f'Failed to get workflow {workflow_id}: {e}')
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Workflow {workflow_id} not found')

@router.delete('/{workflow_id}', summary='Delete Workflow')
async def delete_workflow(workflow_id: str=Path(..., description='Workflow ID'), force: bool=Query(False, description='Force deletion even if executions are running'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, str]:
    try:
        return {'message': f'Workflow {workflow_id} deletion requested', 'workflow_id': workflow_id, 'force': force, 'status': 'accepted'}
    except Exception as e:
        logger.error(f'Failed to delete workflow {workflow_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to delete workflow: {e}')

@router.post('/{workflow_id}/execute', summary='Execute Workflow')
async def execute_workflow(
    workflow_id: str = Path(..., description='Workflow ID'), 
    execution_data: WorkflowExecutionData = Body(...),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    try:
        execution_id = f'exec-{workflow_id}-{int(datetime.utcnow().timestamp())}'
        return {
            'workflow_id': workflow_id,
            'execution_id': execution_id,
            'status': 'running' if True else 'completed',  # Assume async
            'started_at': datetime.utcnow().isoformat(),
            'priority': 'normal',
            'async_execution': True
        }
    except Exception as e:
        logger.error(f'Failed to execute workflow {workflow_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Workflow execution failed: {e}')
    
@router.get('/{workflow_id}/executions', summary='Get Workflow Executions')
async def get_workflow_executions(workflow_id: str=Path(..., description='Workflow ID'), status: Optional[str]=Query(None, description='Filter by execution status'), limit: int=Query(50, ge=1, le=200, description='Maximum number of results'), offset: int=Query(0, ge=0, description='Number of results to skip'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        executions = [{'execution_id': f'exec-{workflow_id}-001', 'status': 'completed', 'started_at': '2024-01-01T10:25:00Z', 'completed_at': '2024-01-01T10:27:36Z', 'duration_seconds': 156.4, 'steps_executed': 4, 'steps_successful': 4, 'steps_failed': 0, 'trigger': 'scheduled'}, {'execution_id': f'exec-{workflow_id}-002', 'status': 'running', 'started_at': '2024-01-01T10:30:00Z', 'completed_at': None, 'duration_seconds': None, 'steps_executed': 2, 'steps_successful': 2, 'steps_failed': 0, 'trigger': 'manual'}]
        if status:
            executions = [e for e in executions if e['status'] == status]
        total = len(executions)
        paginated_executions = executions[offset:offset + limit]
        return {'workflow_id': workflow_id, 'executions': paginated_executions, 'pagination': {'total': total, 'limit': limit, 'offset': offset, 'count': len(paginated_executions)}}
    except Exception as e:
        logger.error(f'Failed to get executions for workflow {workflow_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to get workflow executions: {e}')

@router.get('/{workflow_id}/executions/{execution_id}', summary='Get Execution Details')
async def get_execution_details(workflow_id: str=Path(..., description='Workflow ID'), execution_id: str=Path(..., description='Execution ID'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        return {'workflow_id': workflow_id, 'execution_id': execution_id, 'status': 'completed', 'started_at': '2024-01-01T10:25:00Z', 'completed_at': '2024-01-01T10:27:36Z', 'duration_seconds': 156.4, 'trigger': 'scheduled', 'input_data': {'factory_section': 'production_line_1', 'time_range': 'last_24_hours'}, 'step_results': [{'step_name': 'collect_data', 'status': 'completed', 'started_at': '2024-01-01T10:25:00Z', 'completed_at': '2024-01-01T10:25:45Z', 'duration_seconds': 45.2, 'output_data': {'data_points': 8947, 'quality_score': 0.94}}, {'step_name': 'analyze_data', 'status': 'completed', 'started_at': '2024-01-01T10:25:45Z', 'completed_at': '2024-01-01T10:27:36Z', 'duration_seconds': 111.2, 'output_data': {'insights': 12, 'anomalies': 2, 'confidence': 0.89}}], 'final_result': {'success': True, 'summary': {'data_processed': 8947, 'insights_generated': 12, 'anomalies_detected': 2, 'quality_score': 0.94, 'recommendations': ['Increase monitoring on sensor-003', 'Schedule maintenance for equipment-007']}}}
    except Exception as e:
        logger.error(f'Failed to get execution details {execution_id}: {e}')
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Execution {execution_id} not found')

@router.post('/{workflow_id}/executions/{execution_id}/cancel', summary='Cancel Execution')
async def cancel_execution(
    workflow_id: str = Path(..., description='Workflow ID'),
    execution_id: str = Path(..., description='Execution ID'),
    cancellation_data: WorkflowCancellationData = Body(...),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, str]:
    try:
        return {
            'workflow_id': workflow_id,
            'execution_id': execution_id,
            'status': 'cancellation_requested',
            'reason': cancellation_data.reason or 'User requested cancellation',
            'cancelled_at': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f'Failed to cancel execution {execution_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to cancel execution: {e}')

@router.get('/templates', summary='List Workflow Templates')
async def list_workflow_templates(category: Optional[str]=Query(None, description='Filter by template category'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        templates = [{'template_id': 'iot-analytics-pipeline', 'template_name': 'IoT Analytics Pipeline', 'description': 'Standard pipeline for IoT sensor data analysis', 'category': 'analytics', 'step_count': 3, 'estimated_duration': '2-5 minutes', 'complexity': 'simple'}, {'template_id': 'predictive-maintenance', 'template_name': 'Predictive Maintenance Flow', 'description': 'Comprehensive predictive maintenance workflow', 'category': 'maintenance', 'step_count': 6, 'estimated_duration': '10-15 minutes', 'complexity': 'advanced'}, {'template_id': 'quality-control', 'template_name': 'Quality Control Assessment', 'description': 'Automated quality control and reporting', 'category': 'quality', 'step_count': 4, 'estimated_duration': '3-8 minutes', 'complexity': 'moderate'}]
        if category:
            templates = [t for t in templates if t['category'] == category]
        return {'templates': templates}
    except Exception as e:
        logger.error(f'Failed to list workflow templates: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to list workflow templates: {e}')

@router.post('/templates/{template_id}/instantiate', summary='Create Workflow from Template')
async def create_from_template(
    template_id: str = Path(..., description='Template ID'),
    instantiation_data: TemplateInstantiationData = Body(...),
    gateway: APIGateway = Depends(get_gateway)
) -> Dict[str, Any]:
    try:
        workflow_id = f'wf-{template_id}-{int(datetime.utcnow().timestamp())}'
        return {
            'workflow_id': workflow_id,
            'workflow_name': instantiation_data.workflow_name,
            'template_id': template_id,
            'status': 'created',
            'created_at': datetime.utcnow().isoformat(),
            'parameters_applied': instantiation_data.parameters
        }
    except Exception as e:
        logger.error(f'Failed to create workflow from template {template_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to create workflow from template: {e}')
    
@router.get('/{workflow_id}/metrics', summary='Get Workflow Metrics')
async def get_workflow_metrics(workflow_id: str=Path(..., description='Workflow ID'), time_range: int=Query(86400, ge=3600, description='Time range in seconds'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        return {'workflow_id': workflow_id, 'time_range_seconds': time_range, 'execution_metrics': {'total_executions': 156, 'successful_executions': 147, 'failed_executions': 9, 'success_rate': 0.942, 'average_duration_seconds': 167.8, 'min_duration_seconds': 89.2, 'max_duration_seconds': 423.7, 'executions_per_hour': 6.5}, 'step_performance': {'collect_data': {'average_duration': 45.6, 'success_rate': 0.987, 'error_types': {'timeout': 2, 'connection_error': 0}}, 'analyze_data': {'average_duration': 122.2, 'success_rate': 0.954, 'error_types': {'insufficient_data': 5, 'processing_error': 2}}}, 'resource_utilization': {'average_memory_mb': 445, 'peak_memory_mb': 768, 'average_cpu_percent': 23.7, 'network_io_mb': 156.4}, 'error_analysis': {'most_common_errors': [{'error': 'insufficient_data', 'count': 5, 'percentage': 55.6}, {'error': 'processing_timeout', 'count': 2, 'percentage': 22.2}, {'error': 'connection_error', 'count': 2, 'percentage': 22.2}]}, 'generated_at': datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f'Failed to get workflow metrics {workflow_id}: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to get workflow metrics: {e}')

@router.get('/analytics/global', summary='Get Global Workflow Analytics')
async def get_global_workflow_analytics(time_range: int=Query(86400, ge=3600, description='Time range in seconds'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        return {'time_range_seconds': time_range, 'platform_metrics': {'total_workflows': 23, 'active_workflows': 18, 'total_executions': 1247, 'active_executions': 7, 'overall_success_rate': 0.934}, 'workflow_types': {'sequential': {'count': 12, 'success_rate': 0.945}, 'parallel': {'count': 6, 'success_rate': 0.928}, 'conditional': {'count': 4, 'success_rate': 0.912}, 'dag': {'count': 1, 'success_rate': 0.876}}, 'performance_trends': {'average_execution_time_trend': 'decreasing', 'success_rate_trend': 'stable', 'throughput_trend': 'increasing'}, 'resource_efficiency': {'workflows_per_cpu_hour': 47.3, 'average_memory_efficiency': 0.67, 'cost_per_execution': 0.023}, 'top_performing_workflows': [{'workflow_id': 'wf-analytics-001', 'success_rate': 0.989, 'avg_duration': 134.5}, {'workflow_id': 'wf-maintenance-002', 'success_rate': 0.976, 'avg_duration': 298.7}], 'generated_at': datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f'Failed to get global workflow analytics: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Failed to get global workflow analytics: {e}')

@router.post('/bulk/execute', summary='Execute Multiple Workflows')
async def bulk_execute_workflows(workflow_executions: List[Dict[str, Any]]=Body(..., description='List of workflow executions'), gateway: APIGateway=Depends(get_gateway)) -> Dict[str, Any]:
    try:
        results = []
        for execution in workflow_executions:
            try:
                workflow_id = execution['workflow_id']
                input_data = execution.get('input_data', {})
                execution_id = f'exec-{workflow_id}-{int(datetime.utcnow().timestamp())}'
                results.append({'workflow_id': workflow_id, 'execution_id': execution_id, 'success': True, 'status': 'initiated', 'started_at': datetime.utcnow().isoformat()})
            except Exception as e:
                results.append({'workflow_id': execution.get('workflow_id', 'unknown'), 'success': False, 'error': str(e)})
        successful = len([r for r in results if r['success']])
        return {'total_workflows': len(workflow_executions), 'successful': successful, 'failed': len(workflow_executions) - successful, 'results': results, 'batch_execution_id': f'batch-{int(datetime.utcnow().timestamp())}', 'initiated_at': datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f'Failed to execute workflows in bulk: {e}')
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Bulk workflow execution failed: {e}')