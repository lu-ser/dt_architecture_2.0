# src/utils/type_converter.py (MODIFICATO)
# Helper utilities for string -> enum conversions + capability validation

import logging
from typing import Any, Dict, List, Set, Union, Type, TypeVar
from enum import Enum

from src.core.interfaces.digital_twin import DigitalTwinType
from src.core.interfaces.service import ServiceType, ServicePriority
from src.core.interfaces.replica import ReplicaType, DataAggregationMode
from src.utils.exceptions import ValidationError

from src.core.capabilities.capability_registry import get_capability_registry, CoreCapability

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

T = TypeVar('T', bound=Enum)

class TypeConverter:
    """
    Centralized type conversion utilities for the Digital Twin Platform.
    UPDATED: Now supports both enum-based and registry-based capability validation.
    """
    
    @staticmethod
    def string_to_enum(value: str, enum_class: Type[T], field_name: str = "value") -> T:
        """Convert a string value to the corresponding enum."""
        if not isinstance(value, str):
            raise ValidationError(f"{field_name} must be a string, got {type(value)}")
        
        try:
            return enum_class(value)
        except ValueError:
            valid_values = [e.value for e in enum_class]
            raise ValidationError(
                f'Invalid {field_name} "{value}". Must be one of: {valid_values}'
            )
    
    @staticmethod
    def strings_to_enum_set(values: List[str], enum_class: Type[T], field_name: str = "values") -> Set[T]:
        """Convert a list of strings to a set of enums."""
        if not isinstance(values, list):
            raise ValidationError(f"{field_name} must be a list, got {type(values)}")
        
        result = set()
        for value in values:
            enum_value = TypeConverter.string_to_enum(value, enum_class, field_name)
            result.add(enum_value)
        
        return result
    
    # ==========================================
    # NEW: CAPABILITY VALIDATION METHODS
    # ==========================================
    
    @staticmethod
    def validate_capability(capability_name: str, twin_type: str = None) -> bool:
        """
        Validate a capability name using the registry system.
        
        Args:
            capability_name: Name of the capability to validate
            twin_type: Optional twin type for additional validation
            
        Returns:
            True if capability is valid, False otherwise
        """
        registry = get_capability_registry()
        
        # Check if capability exists in registry
        if not registry.has_capability(capability_name):
            return False
        
        # If twin_type provided, check compatibility
        if twin_type:
            capability_def = registry.get_capability(capability_name)
            if capability_def and capability_def.required_twin_types:
                return twin_type in capability_def.required_twin_types
        
        return True
    
    @staticmethod
    def validate_capabilities(capability_names: List[str], twin_type: str = None) -> Dict[str, bool]:
        """
        Validate a list of capability names.
        
        Args:
            capability_names: List of capability names to validate
            twin_type: Optional twin type for additional validation
            
        Returns:
            Dictionary mapping capability names to validation results
        """
        results = {}
        for name in capability_names:
            results[name] = TypeConverter.validate_capability(name, twin_type)
        return results
    
    @staticmethod
    def get_available_capabilities(twin_type: str = None, namespace: str = None) -> List[str]:
        """
        Get list of available capabilities.
        
        Args:
            twin_type: Filter by twin type compatibility
            namespace: Filter by namespace (e.g., "core", "energy")
            
        Returns:
            List of available capability names
        """
        registry = get_capability_registry()
        capabilities = registry.list_capabilities(namespace=namespace, twin_type=twin_type)
        return [cap.full_name for cap in capabilities]
    
    @staticmethod
    def convert_digital_twin_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert Digital Twin configuration from API format to internal format.
        UPDATED: Now uses registry-based capability validation.
        """
        converted = config.copy()
        
        # Convert twin_type
        if 'twin_type' in converted:
            converted['twin_type'] = TypeConverter.string_to_enum(
                converted['twin_type'], DigitalTwinType, 'twin_type'
            )
        
        # NEW: Convert capabilities using registry validation
        if 'capabilities' in converted:
            capabilities = converted['capabilities']
            twin_type = config.get('twin_type', 'asset')  # Default to asset
            
            # Validate each capability
            invalid_capabilities = []
            valid_capabilities = []
            
            for cap in capabilities:
                if TypeConverter.validate_capability(cap, twin_type):
                    valid_capabilities.append(cap)
                else:
                    invalid_capabilities.append(cap)
            
            if invalid_capabilities:
                available = TypeConverter.get_available_capabilities(twin_type)
                raise ValidationError(
                    f'Invalid capabilities: {invalid_capabilities}. '
                    f'Available capabilities for {twin_type}: {available}'
                )
            
            converted['capabilities'] = valid_capabilities
        
        logger.debug(f"Converted Digital Twin config: {config} -> {converted}")
        return converted
    
    @staticmethod
    def convert_service_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Service configuration from API format to internal format."""
        converted = config.copy()
        
        # Convert service_type if present
        if 'service_type' in converted:
            converted['service_type'] = TypeConverter.string_to_enum(
                converted['service_type'], ServiceType, 'service_type'
            )
        
        # Convert priority if present
        if 'priority' in converted:
            converted['priority'] = TypeConverter.string_to_enum(
                converted['priority'], ServicePriority, 'priority'
            )
        
        logger.debug(f"Converted Service config: {config} -> {converted}")
        return converted
    
    @staticmethod
    def convert_replica_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Digital Replica configuration from API format to internal format."""
        converted = config.copy()
        
        # Convert replica_type
        if 'replica_type' in converted:
            converted['replica_type'] = TypeConverter.string_to_enum(
                converted['replica_type'], ReplicaType, 'replica_type'
            )
        
        # Convert aggregation_mode
        if 'aggregation_mode' in converted:
            converted['aggregation_mode'] = TypeConverter.string_to_enum(
                converted['aggregation_mode'], DataAggregationMode, 'aggregation_mode'
            )
        
        logger.debug(f"Converted Replica config: {config} -> {converted}")
        return converted
    
    # ==========================================
    # LEGACY SUPPORT (Backward Compatibility)
    # ==========================================
    
    @staticmethod
    def convert_capability_string(capability: str) -> Union[CoreCapability, str]:
        """
        Convert a capability string to CoreCapability enum OR return as string.
        This provides backward compatibility while supporting new registry system.
        """
        try:
            # Try core capability first
            return CoreCapability(capability)
        except ValueError:
            # If not core capability, validate with registry and return string
            if TypeConverter.validate_capability(capability):
                return capability
            else:
                raise ValidationError(f'Invalid capability: {capability}')

# ==========================================
# CONVENIENCE FUNCTIONS (Updated)
# ==========================================

def to_digital_twin_type(value: str) -> DigitalTwinType:
    """Convert string to DigitalTwinType enum."""
    return TypeConverter.string_to_enum(value, DigitalTwinType, 'twin_type')

def to_service_type(value: str) -> ServiceType:
    """Convert string to ServiceType enum."""
    return TypeConverter.string_to_enum(value, ServiceType, 'service_type')

def to_service_priority(value: str) -> ServicePriority:
    """Convert string to ServicePriority enum."""
    return TypeConverter.string_to_enum(value, ServicePriority, 'priority')

def to_replica_type(value: str) -> ReplicaType:
    """Convert string to ReplicaType enum."""
    return TypeConverter.string_to_enum(value, ReplicaType, 'replica_type')

def to_aggregation_mode(value: str) -> DataAggregationMode:
    """Convert string to DataAggregationMode enum."""
    return TypeConverter.string_to_enum(value, DataAggregationMode, 'aggregation_mode')

# NEW: Capability validation functions
def validate_capability(capability: str, twin_type: str = None) -> bool:
    """Validate a capability using the registry system."""
    return TypeConverter.validate_capability(capability, twin_type)

def get_available_capabilities(twin_type: str = None) -> List[str]:
    """Get available capabilities for a twin type."""
    return TypeConverter.get_available_capabilities(twin_type)