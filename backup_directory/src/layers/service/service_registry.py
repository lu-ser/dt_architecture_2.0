import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID
import logging
from src.core.registry.base import AbstractRegistry, RegistryMetrics
from src.core.interfaces.base import IStorageAdapter
from src.core.interfaces.service import IService, ServiceType, ServiceDefinition, ServiceState, ServiceExecutionMode, ServicePriority
from src.utils.exceptions import ServiceError, ServiceNotFoundError, EntityNotFoundError, RegistryError
logger = logging.getLogger(__name__)

class ServiceAssociation:

    def __init__(self, service_id: UUID, digital_twin_id: UUID, association_type: str='provides_capability', created_at: Optional[datetime]=None, metadata: Optional[Dict[str, Any]]=None):
        self.service_id = service_id
        self.digital_twin_id = digital_twin_id
        self.association_type = association_type
        self.created_at = created_at or datetime.now(timezone.utc)
        self.metadata = metadata or {}
        self.last_execution_timestamp: Optional[datetime] = None
        self.execution_count = 0
        self.total_execution_time = 0.0
        self.success_count = 0
        self.error_count = 0

    def update_execution_stats(self, success: bool, execution_time: float) -> None:
        self.last_execution_timestamp = datetime.now(timezone.utc)
        self.execution_count += 1
        self.total_execution_time += execution_time
        if success:
            self.success_count += 1
        else:
            self.error_count += 1

    def get_average_execution_time(self) -> float:
        if self.execution_count == 0:
            return 0.0
        return self.total_execution_time / self.execution_count

    def get_success_rate(self) -> float:
        if self.execution_count == 0:
            return 1.0
        return self.success_count / self.execution_count

    def to_dict(self) -> Dict[str, Any]:
        return {'service_id': str(self.service_id), 'digital_twin_id': str(self.digital_twin_id), 'association_type': self.association_type, 'created_at': self.created_at.isoformat(), 'last_execution_timestamp': self.last_execution_timestamp.isoformat() if self.last_execution_timestamp else None, 'execution_count': self.execution_count, 'average_execution_time': self.get_average_execution_time(), 'success_rate': self.get_success_rate(), 'total_execution_time': self.total_execution_time, 'metadata': self.metadata}

class ServicePerformanceMetrics:

    def __init__(self):
        self.total_executions = 0
        self.total_success = 0
        self.total_errors = 0
        self.total_execution_time = 0.0
        self.executions_by_service: Dict[UUID, int] = {}
        self.executions_by_type: Dict[ServiceType, int] = {}
        self.executions_by_priority: Dict[ServicePriority, int] = {}
        self.last_execution_timestamp: Optional[datetime] = None
        self.executions_per_minute = 0.0
        self._execution_timestamps: List[datetime] = []
        self._response_times: List[float] = []

    def record_execution(self, service_id: UUID, service_type: ServiceType, priority: ServicePriority, execution_time: float, success: bool) -> None:
        now = datetime.now(timezone.utc)
        self.total_executions += 1
        self.total_execution_time += execution_time
        self.last_execution_timestamp = now
        if success:
            self.total_success += 1
        else:
            self.total_errors += 1
        self.executions_by_service[service_id] = self.executions_by_service.get(service_id, 0) + 1
        self.executions_by_type[service_type] = self.executions_by_type.get(service_type, 0) + 1
        self.executions_by_priority[priority] = self.executions_by_priority.get(priority, 0) + 1
        self._execution_timestamps.append(now)
        self._response_times.append(execution_time)
        cutoff = now - timedelta(hours=1)
        self._execution_timestamps = [ts for ts in self._execution_timestamps if ts > cutoff]
        self._response_times = self._response_times[-len(self._execution_timestamps):]
        if len(self._execution_timestamps) > 1:
            time_span = (self._execution_timestamps[-1] - self._execution_timestamps[0]).total_seconds() / 60
            self.executions_per_minute = len(self._execution_timestamps) / max(time_span, 1)

    def get_average_execution_time(self) -> float:
        if self.total_executions == 0:
            return 0.0
        return self.total_execution_time / self.total_executions

    def get_success_rate(self) -> float:
        if self.total_executions == 0:
            return 1.0
        return self.total_success / self.total_executions

    def get_percentile_response_time(self, percentile: float) -> float:
        if not self._response_times:
            return 0.0
        sorted_times = sorted(self._response_times)
        index = int(len(sorted_times) * percentile / 100)
        return sorted_times[min(index, len(sorted_times) - 1)]

    def to_dict(self) -> Dict[str, Any]:
        return {'total_executions': self.total_executions, 'total_success': self.total_success, 'total_errors': self.total_errors, 'success_rate': self.get_success_rate(), 'average_execution_time': self.get_average_execution_time(), 'executions_per_minute': self.executions_per_minute, 'last_execution': self.last_execution_timestamp.isoformat() if self.last_execution_timestamp else None, 'executions_by_type': {stype.value: count for stype, count in self.executions_by_type.items()}, 'executions_by_priority': {priority.value: count for priority, count in self.executions_by_priority.items()}, 'response_time_percentiles': {'p50': self.get_percentile_response_time(50), 'p95': self.get_percentile_response_time(95), 'p99': self.get_percentile_response_time(99)}}

class ServiceMetrics(RegistryMetrics):

    def __init__(self):
        super().__init__()
        self.services_by_type: Dict[str, int] = {}
        self.services_by_state: Dict[str, int] = {}
        self.active_services = 0
        self.total_associations = 0
        self.total_executions = 0
        self.performance_metrics = ServicePerformanceMetrics()

    def update_service_statistics(self, service_type: ServiceType, service_state: ServiceState, is_active: bool) -> None:
        type_key = service_type.value
        self.services_by_type[type_key] = self.services_by_type.get(type_key, 0) + 1
        state_key = service_state.value
        self.services_by_state[state_key] = self.services_by_state.get(state_key, 0) + 1
        if is_active:
            self.active_services += 1

    def to_dict(self) -> Dict[str, Any]:
        base_metrics = super().to_dict()
        base_metrics.update({'services_by_type': self.services_by_type, 'services_by_state': self.services_by_state, 'active_services': self.active_services, 'total_associations': self.total_associations, 'total_executions': self.total_executions, 'performance_metrics': self.performance_metrics.to_dict()})
        return base_metrics

class ServiceRegistry(AbstractRegistry[IService]):

    def __init__(self, storage_adapter: IStorageAdapter[IService], cache_enabled: bool=True, cache_size: int=1000, cache_ttl: int=300):
        super().__init__(entity_type=IService, storage_adapter=storage_adapter, cache_enabled=cache_enabled, cache_size=cache_size, cache_ttl=cache_ttl)
        self.service_associations: Dict[str, ServiceAssociation] = {}
        self.service_definitions: Dict[str, ServiceDefinition] = {}
        self.digital_twin_services: Dict[UUID, Set[UUID]] = {}
        self.capability_services: Dict[str, Set[UUID]] = {}
        self.metrics = ServiceMetrics()
        self._association_lock = asyncio.Lock()
        self._performance_lock = asyncio.Lock()

    async def register_service(self, service: IService, associations: Optional[List[ServiceAssociation]]=None) -> None:
        await self.register(service)
        if associations:
            for association in associations:
                await self.associate_service(association)
        else:
            association = ServiceAssociation(service_id=service.id, digital_twin_id=service.digital_twin_id, association_type='provides_capability')
            await self.associate_service(association)
        await self._register_service_capabilities(service)

    async def get_service(self, service_id: UUID) -> IService:
        try:
            return await self.get(service_id)
        except EntityNotFoundError:
            raise ServiceNotFoundError(service_id=str(service_id))

    async def find_services_by_type(self, service_type: ServiceType) -> List[IService]:
        filters = {'service_type': service_type.value}
        return await self.list(filters=filters)

    async def find_services_by_digital_twin(self, digital_twin_id: UUID) -> List[IService]:
        service_ids = self.digital_twin_services.get(digital_twin_id, set())
        services = []
        for service_id in service_ids:
            try:
                service = await self.get_service(service_id)
                services.append(service)
            except ServiceNotFoundError:
                self.digital_twin_services[digital_twin_id].discard(service_id)
        return services

    async def find_services_by_capability(self, capability: str) -> List[IService]:
        service_ids = self.capability_services.get(capability, set())
        services = []
        for service_id in service_ids:
            try:
                service = await self.get_service(service_id)
                services.append(service)
            except ServiceNotFoundError:
                self.capability_services[capability].discard(service_id)
        return services

    async def find_services_by_state(self, state: ServiceState) -> List[IService]:
        all_services = await self.list()
        matching_services = []
        for service in all_services:
            if service.current_state == state:
                matching_services.append(service)
        return matching_services

    async def associate_service(self, association: ServiceAssociation) -> None:
        async with self._association_lock:
            await self.get_service(association.service_id)
            key = f'{association.service_id}:{association.digital_twin_id}'
            self.service_associations[key] = association
            dt_id = association.digital_twin_id
            if dt_id not in self.digital_twin_services:
                self.digital_twin_services[dt_id] = set()
            self.digital_twin_services[dt_id].add(association.service_id)
            self.metrics.total_associations += 1
            self.logger.info(f'Associated service {association.service_id} with Digital Twin {association.digital_twin_id}')

    async def disassociate_service(self, service_id: UUID, digital_twin_id: UUID) -> bool:
        async with self._association_lock:
            key = f'{service_id}:{digital_twin_id}'
            if key in self.service_associations:
                del self.service_associations[key]
                if digital_twin_id in self.digital_twin_services:
                    self.digital_twin_services[digital_twin_id].discard(service_id)
                    if not self.digital_twin_services[digital_twin_id]:
                        del self.digital_twin_services[digital_twin_id]
                self.metrics.total_associations -= 1
                self.logger.info(f'Disassociated service {service_id} from Digital Twin {digital_twin_id}')
                return True
            return False

    async def get_service_associations(self, service_id: UUID) -> List[ServiceAssociation]:
        associations = []
        for association in self.service_associations.values():
            if association.service_id == service_id:
                associations.append(association)
        return associations

    async def record_service_execution(self, service_id: UUID, execution_time: float, success: bool, priority: ServicePriority=ServicePriority.NORMAL) -> None:
        async with self._performance_lock:
            try:
                service = await self.get_service(service_id)
                service_type = service.service_type
            except ServiceNotFoundError:
                return
            self.metrics.performance_metrics.record_execution(service_id, service_type, priority, execution_time, success)
            for association in self.service_associations.values():
                if association.service_id == service_id:
                    association.update_execution_stats(success, execution_time)
            self.metrics.total_executions += 1

    async def get_service_performance(self, service_id: UUID) -> Dict[str, Any]:
        try:
            service = await self.get_service(service_id)
            service_metrics = await service.get_metrics()
            associations = await self.get_service_associations(service_id)
            total_executions = sum((assoc.execution_count for assoc in associations))
            avg_execution_time = sum((assoc.get_average_execution_time() for assoc in associations)) / len(associations) if associations else 0
            overall_success_rate = sum((assoc.get_success_rate() for assoc in associations)) / len(associations) if associations else 1.0
            return {'service_id': str(service_id), 'service_type': service.service_type.value, 'current_state': service.current_state.value, 'total_executions': total_executions, 'average_execution_time': avg_execution_time, 'overall_success_rate': overall_success_rate, 'associations_count': len(associations), 'service_metrics': service_metrics, 'associations': [assoc.to_dict() for assoc in associations]}
        except ServiceNotFoundError:
            return {'error': f'Service {service_id} not found'}

    async def discover_services(self, criteria: Dict[str, Any]) -> List[IService]:
        filters = {}
        if 'type' in criteria:
            filters['service_type'] = criteria['type']
        if 'digital_twin_id' in criteria:
            filters['digital_twin_id'] = criteria['digital_twin_id']
        services = await self.list(filters=filters)
        if 'capabilities' in criteria:
            required_capabilities = set(criteria['capabilities'])
            services = [s for s in services if required_capabilities.issubset(s.capabilities)]
        if 'state' in criteria:
            target_state = ServiceState(criteria['state'])
            services = [s for s in services if s.current_state == target_state]
        if 'min_success_rate' in criteria:
            threshold = criteria['min_success_rate']
            filtered_services = []
            for service in services:
                associations = await self.get_service_associations(service.id)
                if associations:
                    avg_success_rate = sum((assoc.get_success_rate() for assoc in associations)) / len(associations)
                    if avg_success_rate >= threshold:
                        filtered_services.append(service)
                else:
                    filtered_services.append(service)
            services = filtered_services
        if 'max_response_time' in criteria:
            threshold = criteria['max_response_time']
            filtered_services = []
            for service in services:
                associations = await self.get_service_associations(service.id)
                if associations:
                    avg_response_time = sum((assoc.get_average_execution_time() for assoc in associations)) / len(associations)
                    if avg_response_time <= threshold:
                        filtered_services.append(service)
                else:
                    filtered_services.append(service)
            services = filtered_services
        return services

    async def get_service_statistics(self) -> Dict[str, Any]:
        all_services = await self.list()
        stats = {'total_services': len(all_services), 'services_by_type': {}, 'services_by_state': {}, 'services_with_associations': len(set((assoc.service_id for assoc in self.service_associations.values()))), 'total_associations': len(self.service_associations), 'total_capabilities': len(self.capability_services), 'digital_twins_with_services': len(self.digital_twin_services)}
        for service in all_services:
            service_type = service.service_type.value
            service_state = service.current_state.value
            stats['services_by_type'][service_type] = stats['services_by_type'].get(service_type, 0) + 1
            stats['services_by_state'][service_state] = stats['services_by_state'].get(service_state, 0) + 1
        stats['performance'] = self.metrics.performance_metrics.to_dict()
        return stats

    async def register_service_definition(self, definition: ServiceDefinition) -> None:
        self.service_definitions[definition.definition_id] = definition
        logger.info(f'Registered service definition: {definition.definition_id}')

    async def get_service_definition(self, definition_id: str) -> ServiceDefinition:
        if definition_id not in self.service_definitions:
            raise ServiceError(f'Service definition {definition_id} not found')
        return self.service_definitions[definition_id]

    async def list_service_definitions(self, service_type: Optional[ServiceType]=None) -> List[ServiceDefinition]:
        definitions = list(self.service_definitions.values())
        if service_type:
            definitions = [d for d in definitions if d.service_type == service_type]
        return definitions

    async def _register_service_capabilities(self, service: IService) -> None:
        for capability in service.capabilities:
            if capability not in self.capability_services:
                self.capability_services[capability] = set()
            self.capability_services[capability].add(service.id)

    async def _unregister_service_capabilities(self, service: IService) -> None:
        for capability in service.capabilities:
            if capability in self.capability_services:
                self.capability_services[capability].discard(service.id)
                if not self.capability_services[capability]:
                    del self.capability_services[capability]

    async def _post_register_hook(self, entity: IService) -> None:
        from src.core.interfaces.base import EntityStatus
        self.metrics.update_service_statistics(service_type=entity.service_type, service_state=entity.current_state, is_active=entity.status == EntityStatus.ACTIVE)

    async def _pre_unregister_hook(self, entity: IService) -> None:
        service_id = entity.id
        associations_to_remove = await self.get_service_associations(service_id)
        for association in associations_to_remove:
            await self.disassociate_service(service_id, association.digital_twin_id)
        await self._unregister_service_capabilities(entity)