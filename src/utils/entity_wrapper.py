# src/utils/entity_wrapper.py
from typing import Any, Dict, List, Set, Optional
from uuid import UUID
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

class DictToObjectWrapper:
    """
    Wrapper che converte un dizionario in un oggetto con attributi.
    Soluzione temporanea per il problema di deserializzazione.
    """
    
    def __init__(self, data: Dict[str, Any]):
        self._data = data
        self._setup_attributes()
    
    def _setup_attributes(self):
        """Configura gli attributi in base al tipo di entità"""
        # Attributi comuni
        self.id = self._get_uuid('id')
        
        # Determina il tipo di entità e configura di conseguenza
        if self._is_digital_twin():
            self._setup_digital_twin_attributes()
        elif self._is_service():
            self._setup_service_attributes()
        elif self._is_replica():
            self._setup_replica_attributes()
    
    def _is_digital_twin(self) -> bool:
        return ('twin_type' in self._data or 
                'capabilities' in self._data or
                'integrated_models' in self._data)
    
    def _is_service(self) -> bool:
        return ('service_type' in self._data or
                'service_definition_id' in self._data or
                'instance_name' in self._data)
    
    def _is_replica(self) -> bool:
        return ('replica_type' in self._data or
                'parent_digital_twin_id' in self._data or
                'device_ids' in self._data)
    
    def _setup_digital_twin_attributes(self):
        """Configura attributi per Digital Twin"""
        from src.core.interfaces.digital_twin import DigitalTwinType, DigitalTwinState, TwinCapability
        
        # Attributi base
        self.name = self._data.get('name', 'Unknown Twin')
        self.description = self._data.get('description', '')
        
        # Twin type
        try:
            self.twin_type = DigitalTwinType(self._data.get('twin_type', 'asset'))
        except ValueError:
            self.twin_type = DigitalTwinType.ASSET
        
        # Current state  
        try:
            self.current_state = DigitalTwinState(self._data.get('current_state', 'learning'))
        except ValueError:
            self.current_state = DigitalTwinState.LEARNING
        
        # Capabilities
        capabilities_data = self._data.get('capabilities', [])
        self.capabilities = set()
        for cap in capabilities_data:
            try:
                self.capabilities.add(TwinCapability(cap))
            except ValueError:
                pass
        
        # Altri attributi
        self.associated_replicas = self._data.get('associated_replicas', [])
        self.integrated_models = self._data.get('integrated_models', [])
        
        # Configuration
        config_data = self._data.get('configuration', {})
        self.configuration = type('Config', (), config_data)()
    
    def _setup_service_attributes(self):
        """Configura attributi per Service"""
        from src.core.interfaces.service import ServiceType, ServiceState
        
        self.instance_name = self._data.get('instance_name', 'Unknown Service')
        self.service_definition_id = self._data.get('service_definition_id', 'unknown')
        self.digital_twin_id = self._get_uuid('digital_twin_id')
        
        # Service type
        try:
            self.service_type = ServiceType(self._data.get('service_type', 'analytics'))
        except ValueError:
            self.service_type = ServiceType.ANALYTICS
        
        # Current state
        try:
            self.current_state = ServiceState(self._data.get('current_state', 'ready'))
        except ValueError:
            self.current_state = ServiceState.READY
        
        # Capabilities
        self.capabilities = set(self._data.get('capabilities', []))
        
        # Configuration
        self.configuration = type('Config', (), self._data.get('configuration', {}))()
    
    def _setup_replica_attributes(self):
        """Configura attributi per Digital Replica"""
        from src.core.interfaces.replica import ReplicaType, DataAggregationMode
        
        self.parent_digital_twin_id = self._get_uuid('parent_digital_twin_id')
        self.device_ids = self._data.get('device_ids', [])
        
        # Replica type
        try:
            self.replica_type = ReplicaType(self._data.get('replica_type', 'sensor_aggregator'))
        except ValueError:
            self.replica_type = ReplicaType.SENSOR_AGGREGATOR
        
        # Aggregation mode
        try:
            self.aggregation_mode = DataAggregationMode(self._data.get('aggregation_mode', 'batch'))
        except ValueError:
            self.aggregation_mode = DataAggregationMode.BATCH
        
        # Configuration
        self.configuration = type('Config', (), self._data.get('configuration', {}))()
    
    def _get_uuid(self, key: str) -> Optional[UUID]:
        """Converte un valore in UUID se possibile"""
        value = self._data.get(key)
        if not value:
            return None
        
        if isinstance(value, UUID):
            return value
        
        if isinstance(value, str):
            try:
                return UUID(value)
            except ValueError:
                return None
        
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Restituisce i dati originali"""
        return self._data.copy()
    
    def __getattr__(self, name: str) -> Any:
        """Fallback per attributi non definiti"""
        if name in self._data:
            return self._data[name]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")