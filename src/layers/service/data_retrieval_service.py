# src/layers/service/data_retrieval_service.py
"""
Data Retrieval Service for Digital Twin Platform.

This service handles retrieval of device data from Digital Replicas
and provides various data access patterns (latest, historical, aggregated).
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Union
from uuid import UUID
from dataclasses import dataclass

from src.core.interfaces.service import IService, ServiceType, ServicePriority
from src.core.interfaces.base import BaseMetadata, EntityStatus
from src.utils.exceptions import ServiceError, EntityNotFoundError

logger = logging.getLogger(__name__)


@dataclass
class DataPoint:
    """Represents a single data point from a device."""
    device_id: str
    timestamp: datetime
    data: Dict[str, Any]
    data_type: str
    quality: float
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "data_type": self.data_type,
            "quality": self.quality,
            "metadata": self.metadata
        }


@dataclass
class DataRetrievalQuery:
    """Query parameters for data retrieval."""
    replica_id: UUID
    device_ids: Optional[List[str]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    limit: int = 100
    data_types: Optional[List[str]] = None
    min_quality: float = 0.0
    include_metadata: bool = True
    aggregation_type: Optional[str] = None  # latest, average, sum, etc.


class DataRetrievalService(IService):
    """Service for retrieving data from Digital Replicas."""
    
    def __init__(
        self,
        service_id: UUID,
        digital_twin_id: UUID,
        metadata: BaseMetadata,
        virtualization_orchestrator=None
    ):
        self._service_id = service_id
        self._digital_twin_id = digital_twin_id
        self._metadata = metadata
        self.virtualization_orchestrator = virtualization_orchestrator
        self._status = EntityStatus.CREATED
        self._service_type = ServiceType.DATA_PROCESSING
        self._priority = ServicePriority.NORMAL
        
        self._execution_count = 0
        self._last_execution = None
        self._error_count = 0
        self._instance_name = f"DataRetrieval-{service_id}"
        self._service_definition_id = "data_retrieval_v1"
        self._current_state = "ready"
        self._execution_mode = "synchronous"
        
        logger.info(f"DataRetrievalService {service_id} created for twin {digital_twin_id}")
    
    # =====================================
    # IService Interface Implementation
    # =====================================
    
    @property
    def id(self) -> UUID:
        return self._service_id
    
    @property
    def digital_twin_id(self) -> UUID:
        return self._digital_twin_id
    
    @property
    def service_type(self) -> ServiceType:
        return self._service_type
    
    @property
    def status(self) -> EntityStatus:
        return self._status
    
    @property
    def metadata(self) -> BaseMetadata:
        return self._metadata
    
    @property
    def instance_name(self) -> str:
        return self._instance_name
    
    @property
    def service_definition_id(self) -> str:
        return self._service_definition_id
    
    @property
    def current_state(self) -> str:
        return self._current_state
    
    @property
    def execution_mode(self) -> str:
        return self._execution_mode
    
    @property
    def capabilities(self) -> List[str]:
        return ["data_retrieval", "latest_data", "historical_data", "aggregated_data", "device_summary"]
    
    @property
    def configuration(self) -> Dict[str, Any]:
        return {
            "service_type": self._service_type.value,
            "priority": self._priority.value,
            "execution_mode": self._execution_mode,
            "capabilities": self.capabilities
        }
    
    async def initialize(self) -> None:
        """Initialize the service."""
        self._status = EntityStatus.INITIALIZING
        # No special initialization needed
        self._status = EntityStatus.ACTIVE
        logger.info(f"DataRetrievalService {self._service_id} initialized")
    
    async def start(self) -> None:
        """Start the data retrieval service."""
        if self._status == EntityStatus.CREATED:
            await self.initialize()
        self._status = EntityStatus.ACTIVE
        self._current_state = "running"
        logger.info(f"DataRetrievalService {self._service_id} started")
    
    async def stop(self) -> None:
        """Stop the data retrieval service."""
        self._status = EntityStatus.INACTIVE
        self._current_state = "stopped"
        logger.info(f"DataRetrievalService {self._service_id} stopped")
    
    async def pause(self) -> None:
        """Pause the service."""
        self._current_state = "paused"
        logger.info(f"DataRetrievalService {self._service_id} paused")
    
    async def resume(self) -> None:
        """Resume the service."""
        self._current_state = "running"
        logger.info(f"DataRetrievalService {self._service_id} resumed")
    
    async def terminate(self) -> None:
        """Terminate the service."""
        await self.stop()
        self._status = EntityStatus.TERMINATED
        self._current_state = "terminated"
        logger.info(f"DataRetrievalService {self._service_id} terminated")
    
    async def drain(self) -> None:
        """Drain the service (finish current work)."""
        # No ongoing work to drain for this service
        pass
    
    async def health_check(self) -> Dict[str, Any]:
        """Check service health."""
        is_healthy = (
            self._status == EntityStatus.ACTIVE and 
            self.virtualization_orchestrator is not None
        )
        
        return {
            "healthy": is_healthy,
            "status": self._status.value,
            "current_state": self._current_state,
            "execution_count": self._execution_count,
            "error_count": self._error_count,
            "last_execution": self._last_execution.isoformat() if self._last_execution else None
        }
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get service metrics."""
        return {
            "execution_count": self._execution_count,
            "error_count": self._error_count,
            "success_rate": (self._execution_count - self._error_count) / max(self._execution_count, 1),
            "last_execution": self._last_execution.isoformat() if self._last_execution else None,
            "uptime_seconds": (datetime.now(timezone.utc) - self._metadata.timestamp).total_seconds()
        }
    
    async def update_configuration(self, new_config: Dict[str, Any]) -> None:
        """Update service configuration."""
        # For this simple service, just log the update
        logger.info(f"Configuration update requested for {self._service_id}: {new_config}")
    
    async def validate(self) -> bool:
        """Validate service state."""
        return (
            self._service_id is not None and
            self._digital_twin_id is not None and
            self.virtualization_orchestrator is not None
        )
    
    async def execute_async(
        self,
        input_data: Dict[str, Any],
        execution_config: Optional[Dict[str, Any]] = None
    ) -> str:
        """Execute asynchronously (returns execution ID)."""
        execution_id = f"exec-{datetime.now(timezone.utc).timestamp()}"
        # For this simple implementation, we'll just do sync execution
        await self.execute(input_data, execution_config)
        return execution_id
    
    async def get_execution_status(self, execution_id: str) -> Dict[str, Any]:
        """Get execution status."""
        return {
            "execution_id": execution_id,
            "status": "completed",
            "started_at": self._last_execution.isoformat() if self._last_execution else None,
            "completed_at": self._last_execution.isoformat() if self._last_execution else None
        }
    
    async def cancel_execution(self, execution_id: str) -> bool:
        """Cancel execution."""
        # For this simple service, executions are short-lived
        logger.info(f"Cancel requested for execution {execution_id}")
        return True
    
    # =====================================
    # Data Retrieval Implementation
    # =====================================
    
    async def execute(
        self,
        input_data: Dict[str, Any],
        execution_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute data retrieval based on query parameters."""
        try:
            self._execution_count += 1
            self._last_execution = datetime.now(timezone.utc)
            
            # Parse query from input_data
            query = self._parse_query(input_data)
            
            # Retrieve data based on query type
            retrieval_type = input_data.get("retrieval_type", "latest")
            
            if retrieval_type == "latest":
                result = await self._get_latest_data(query)
            elif retrieval_type == "historical":
                result = await self._get_historical_data(query)
            elif retrieval_type == "aggregated":
                result = await self._get_aggregated_data(query)
            elif retrieval_type == "device_summary":
                result = await self._get_device_summary(query)
            else:
                raise ServiceError(f"Unknown retrieval_type: {retrieval_type}")
            
            return {
                "status": "success",
                "retrieval_type": retrieval_type,
                "query": self._query_to_dict(query),
                "data": result,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "service_id": str(self._service_id)
            }
            
        except Exception as e:
            self._error_count += 1
            logger.error(f"DataRetrievalService execution failed: {e}")
            raise ServiceError(f"Data retrieval failed: {e}")
    
    def _parse_query(self, input_data: Dict[str, Any]) -> DataRetrievalQuery:
        """Parse input data into DataRetrievalQuery."""
        replica_id = UUID(input_data["replica_id"])
        
        # Parse optional datetime strings
        start_time = None
        end_time = None
        if "start_time" in input_data:
            start_time = datetime.fromisoformat(input_data["start_time"].replace('Z', '+00:00'))
        if "end_time" in input_data:
            end_time = datetime.fromisoformat(input_data["end_time"].replace('Z', '+00:00'))
        
        return DataRetrievalQuery(
            replica_id=replica_id,
            device_ids=input_data.get("device_ids"),
            start_time=start_time,
            end_time=end_time,
            limit=input_data.get("limit", 100),
            data_types=input_data.get("data_types"),
            min_quality=input_data.get("min_quality", 0.0),
            include_metadata=input_data.get("include_metadata", True),
            aggregation_type=input_data.get("aggregation_type")
        )
    
    async def _get_latest_data(self, query: DataRetrievalQuery) -> List[Dict[str, Any]]:
        """Get latest data points from replica."""
        if not self.virtualization_orchestrator:
            raise ServiceError("Virtualization orchestrator not available")
        
        registry = self.virtualization_orchestrator.registry
        data_points = []
        
        # Access device associations directly from registry
        for key, association in registry.device_associations.items():
            if str(association.replica_id) == str(query.replica_id):
                
                # Filter by device_ids if specified
                if query.device_ids and association.device_id not in query.device_ids:
                    continue
                
                # Get quality score
                quality_score = association.get_average_quality_score()
                
                # Filter by quality
                if quality_score < query.min_quality:
                    continue
                
                # Create synthetic data point from association data
                data_point = {
                    "device_id": association.device_id,
                    "timestamp": association.last_data_timestamp.isoformat() if association.last_data_timestamp else None,
                    "data": self._generate_latest_data_from_association(association),
                    "data_type": "sensor_reading",
                    "quality": quality_score,
                    "metadata": {
                        "association_type": association.association_type,
                        "data_count": association.data_count,
                        "created_at": association.created_at.isoformat()
                    } if query.include_metadata else {}
                }
                
                data_points.append(data_point)
        
        # Apply limit
        return data_points[:query.limit]
    
    async def _get_historical_data(self, query: DataRetrievalQuery) -> List[Dict[str, Any]]:
        """Get historical data points within time range."""
        if not self.virtualization_orchestrator:
            raise ServiceError("Virtualization orchestrator not available")
        
        registry = self.virtualization_orchestrator.registry
        data_points = []
        
        for key, association in registry.device_associations.items():
            if str(association.replica_id) == str(query.replica_id):
                
                if query.device_ids and association.device_id not in query.device_ids:
                    continue
                
                # Generate historical data points (mock)
                historical_points = self._generate_historical_data(
                    association, query.start_time, query.end_time, query.limit
                )
                data_points.extend(historical_points)
        
        return sorted(data_points, key=lambda x: x["timestamp"], reverse=True)[:query.limit]
    
    async def _get_aggregated_data(self, query: DataRetrievalQuery) -> Dict[str, Any]:
        """Get aggregated data summary."""
        if not self.virtualization_orchestrator:
            raise ServiceError("Virtualization orchestrator not available")
        
        registry = self.virtualization_orchestrator.registry
        
        device_summaries = {}
        total_data_points = 0
        avg_quality = 0
        device_count = 0
        
        for key, association in registry.device_associations.items():
            if str(association.replica_id) == str(query.replica_id):
                
                if query.device_ids and association.device_id not in query.device_ids:
                    continue
                
                quality_score = association.get_average_quality_score()
                
                device_summaries[association.device_id] = {
                    "total_data_points": association.data_count,
                    "average_quality": quality_score,
                    "last_data_time": association.last_data_timestamp.isoformat() if association.last_data_timestamp else None,
                    "association_type": association.association_type,
                    "status": "active" if association.last_data_timestamp else "inactive"
                }
                
                total_data_points += association.data_count
                avg_quality += quality_score
                device_count += 1
        
        return {
            "summary": {
                "total_devices": device_count,
                "total_data_points": total_data_points,
                "average_quality": avg_quality / max(device_count, 1),
                "time_range": {
                    "start": query.start_time.isoformat() if query.start_time else None,
                    "end": query.end_time.isoformat() if query.end_time else None
                }
            },
            "devices": device_summaries
        }
    
    async def _get_device_summary(self, query: DataRetrievalQuery) -> Dict[str, Any]:
        """Get summary information for devices."""
        if not self.virtualization_orchestrator:
            raise ServiceError("Virtualization orchestrator not available")
        
        registry = self.virtualization_orchestrator.registry
        
        # Get replica devices
        replica_devices = registry.replica_to_devices.get(query.replica_id, set())
        
        device_info = {}
        for device_id in replica_devices:
            if query.device_ids and device_id not in query.device_ids:
                continue
            
            # Find association for this device
            association = None
            for key, assoc in registry.device_associations.items():
                if assoc.device_id == device_id and assoc.replica_id == query.replica_id:
                    association = assoc
                    break
            
            if association:
                device_info[device_id] = {
                    "device_id": device_id,
                    "data_count": association.data_count,
                    "quality_score": association.get_average_quality_score(),
                    "last_data": association.last_data_timestamp.isoformat() if association.last_data_timestamp else None,
                    "status": "active",
                    "association_type": association.association_type
                }
            else:
                device_info[device_id] = {
                    "device_id": device_id,
                    "data_count": 0,
                    "quality_score": 0,
                    "last_data": None,
                    "status": "inactive",
                    "association_type": "unknown"
                }
        
        return {
            "replica_id": str(query.replica_id),
            "device_count": len(device_info),
            "devices": device_info
        }
    
    def _generate_latest_data_from_association(self, association) -> Dict[str, Any]:
        """Generate synthetic latest data based on association info."""
        # This is where you'd normally fetch from actual storage
        # For now, return mock data based on device type
        
        if "smartwatch" in association.device_id.lower():
            return {
                "heart_rate": 72,
                "battery_level": 85,
                "activity_level": "moderate",
                "steps": 8500,
                "calories_burned": 245
            }
        else:
            return {
                "value": association.data_count * 10,  # Mock value
                "status": "active",
                "sensor_reading": association.get_average_quality_score() * 100
            }
    
    def _generate_historical_data(
        self, 
        association, 
        start_time: Optional[datetime], 
        end_time: Optional[datetime], 
        limit: int
    ) -> List[Dict[str, Any]]:
        """Generate mock historical data points."""
        if not end_time:
            end_time = datetime.now(timezone.utc)
        if not start_time:
            start_time = end_time - timedelta(hours=24)
        
        # Generate mock data points at 5-minute intervals
        data_points = []
        current_time = start_time
        interval = timedelta(minutes=5)
        
        base_value = 70 if "smartwatch" in association.device_id.lower() else 50
        
        while current_time <= end_time and len(data_points) < limit:
            # Add some variation to the data
            import random
            variation = random.uniform(-5, 5)
            
            if "smartwatch" in association.device_id.lower():
                data = {
                    "heart_rate": int(base_value + variation),
                    "activity_level": random.choice(["resting", "light", "moderate"]),
                    "battery_level": max(20, 100 - (len(data_points) * 2))
                }
            else:
                data = {
                    "value": base_value + variation,
                    "sensor_reading": association.get_average_quality_score() * 100
                }
            
            data_points.append({
                "device_id": association.device_id,
                "timestamp": current_time.isoformat(),
                "data": data,
                "data_type": "historical_reading",
                "quality": association.get_average_quality_score(),
                "metadata": {"generated": True}
            })
            
            current_time += interval
        
        return data_points
    
    def _query_to_dict(self, query: DataRetrievalQuery) -> Dict[str, Any]:
        """Convert query to dictionary for response."""
        return {
            "replica_id": str(query.replica_id),
            "device_ids": query.device_ids,
            "start_time": query.start_time.isoformat() if query.start_time else None,
            "end_time": query.end_time.isoformat() if query.end_time else None,
            "limit": query.limit,
            "data_types": query.data_types,
            "min_quality": query.min_quality,
            "aggregation_type": query.aggregation_type
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get service execution statistics."""
        return {
            "execution_count": self._execution_count,
            "last_execution": self._last_execution.isoformat() if self._last_execution else None,
            "error_count": self._error_count,
            "status": self._status.value,
            "service_type": self._service_type.value,
            "priority": self._priority.value
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize service to dictionary."""
        return {
            "id": str(self._service_id),
            "digital_twin_id": str(self._digital_twin_id),
            "service_type": self._service_type.value,
            "status": self._status.value,
            "priority": self._priority.value,
            "metadata": self._metadata.to_dict(),
            "statistics": self.get_statistics()
        }