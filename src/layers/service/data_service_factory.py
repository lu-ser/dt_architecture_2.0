# src/layers/service/data_service_factory.py
"""
Factory for creating data retrieval services.
"""

from typing import Dict, Any, Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone

from src.core.interfaces.service import IService, IServiceFactory, ServiceType
from src.core.interfaces.base import BaseMetadata
from src.layers.service.data_retrieval_service import DataRetrievalService
from src.utils.exceptions import FactoryConfigurationError


class DataServiceFactory(IServiceFactory):
    """Factory for creating data-related services."""
    
    def __init__(self, virtualization_orchestrator=None):
        self.virtualization_orchestrator = virtualization_orchestrator
        self._supported_types = [ServiceType.DATA_PROCESSING]
    
    async def create(
        self, 
        config: Dict[str, Any], 
        metadata: Optional[BaseMetadata] = None
    ) -> IService:
        """Create a data service instance."""
        try:
            service_type = config.get("service_type", "data_retrieval")
            
            if service_type == "data_retrieval":
                return await self._create_data_retrieval_service(config, metadata)
            else:
                raise FactoryConfigurationError(f"Unsupported service type: {service_type}")
                
        except Exception as e:
            raise FactoryConfigurationError(f"Failed to create data service: {e}")
    
    async def _create_data_retrieval_service(
        self, 
        config: Dict[str, Any], 
        metadata: Optional[BaseMetadata] = None
    ) -> DataRetrievalService:
        """Create a data retrieval service."""
        
        service_id = config.get("service_id", uuid4())
        if isinstance(service_id, str):
            service_id = UUID(service_id)
        
        digital_twin_id = config["digital_twin_id"]
        if isinstance(digital_twin_id, str):
            digital_twin_id = UUID(digital_twin_id)
        
        if metadata is None:
            metadata = BaseMetadata(
                entity_id=service_id,
                timestamp=datetime.now(timezone.utc),
                version="1.0.0",
                created_by=config.get("created_by", uuid4())
            )
        
        service = DataRetrievalService(
            service_id=service_id,
            digital_twin_id=digital_twin_id,
            metadata=metadata,
            virtualization_orchestrator=self.virtualization_orchestrator
        )
        
        return service
    
    def get_supported_types(self) -> list:
        """Get supported service types."""
        return [st.value for st in self._supported_types]
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate service configuration."""
        required_fields = ["digital_twin_id"]
        
        for field in required_fields:
            if field not in config:
                return False
        
        try:
            UUID(config["digital_twin_id"])
            return True
        except (ValueError, TypeError):
            return False


def register_data_services(service_orchestrator):
    """Register data services with the service orchestrator."""
    
    # Register the data service factory
    data_factory = DataServiceFactory(
        virtualization_orchestrator=service_orchestrator.virtualization_orchestrator
    )
    
    # Register factory with orchestrator
    service_orchestrator.register_service_factory("data_retrieval", data_factory)
    
    return data_factory