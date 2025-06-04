import logging
from typing import Any, Dict, List, Set, Union, Type, TypeVar
from enum import Enum
from src.core.interfaces.digital_twin import DigitalTwinType, TwinCapability
from src.core.interfaces.service import ServiceType, ServicePriority
from src.core.interfaces.replica import ReplicaType, DataAggregationMode
from src.utils.exceptions import ValidationError
logger = logging.getLogger(__name__)
T = TypeVar('T', bound=Enum)

class TypeConverter:

    @staticmethod
    def string_to_enum(value: str, enum_class: Type[T], field_name: str='value') -> T:
        if not isinstance(value, str):
            raise ValidationError(f'{field_name} must be a string, got {type(value)}')
        try:
            return enum_class(value)
        except ValueError:
            valid_values = [e.value for e in enum_class]
            raise ValidationError(f'Invalid {field_name} "{value}". Must be one of: {valid_values}')

    @staticmethod
    def strings_to_enum_set(values: List[str], enum_class: Type[T], field_name: str='values') -> Set[T]:
        if not isinstance(values, list):
            raise ValidationError(f'{field_name} must be a list, got {type(values)}')
        result = set()
        for value in values:
            enum_value = TypeConverter.string_to_enum(value, enum_class, field_name)
            result.add(enum_value)
        return result

    @staticmethod
    def convert_digital_twin_config(config: Dict[str, Any]) -> Dict[str, Any]:
        converted = config.copy()
        if 'twin_type' in converted:
            converted['twin_type'] = TypeConverter.string_to_enum(converted['twin_type'], DigitalTwinType, 'twin_type')
        if 'capabilities' in converted:
            converted['capabilities'] = TypeConverter.strings_to_enum_set(converted['capabilities'], TwinCapability, 'capabilities')
        logger.debug(f'Converted Digital Twin config: {config} -> {converted}')
        return converted

    @staticmethod
    def convert_service_config(config: Dict[str, Any]) -> Dict[str, Any]:
        converted = config.copy()
        if 'service_type' in converted:
            converted['service_type'] = TypeConverter.string_to_enum(converted['service_type'], ServiceType, 'service_type')
        if 'priority' in converted:
            converted['priority'] = TypeConverter.string_to_enum(converted['priority'], ServicePriority, 'priority')
        logger.debug(f'Converted Service config: {config} -> {converted}')
        return converted

    @staticmethod
    def convert_replica_config(config: Dict[str, Any]) -> Dict[str, Any]:
        converted = config.copy()
        if 'replica_type' in converted:
            converted['replica_type'] = TypeConverter.string_to_enum(converted['replica_type'], ReplicaType, 'replica_type')
        if 'aggregation_mode' in converted:
            converted['aggregation_mode'] = TypeConverter.string_to_enum(converted['aggregation_mode'], DataAggregationMode, 'aggregation_mode')
        logger.debug(f'Converted Replica config: {config} -> {converted}')
        return converted

    @staticmethod
    def convert_capability_string(capability: str) -> TwinCapability:
        return TypeConverter.string_to_enum(capability, TwinCapability, 'capability')

def to_digital_twin_type(value: str) -> DigitalTwinType:
    return TypeConverter.string_to_enum(value, DigitalTwinType, 'twin_type')

def to_twin_capabilities(values: List[str]) -> Set[TwinCapability]:
    return TypeConverter.strings_to_enum_set(values, TwinCapability, 'capabilities')

def to_service_type(value: str) -> ServiceType:
    return TypeConverter.string_to_enum(value, ServiceType, 'service_type')

def to_service_priority(value: str) -> ServicePriority:
    return TypeConverter.string_to_enum(value, ServicePriority, 'priority')

def to_replica_type(value: str) -> ReplicaType:
    return TypeConverter.string_to_enum(value, ReplicaType, 'replica_type')

def to_aggregation_mode(value: str) -> DataAggregationMode:
    return TypeConverter.string_to_enum(value, DataAggregationMode, 'aggregation_mode')

def to_twin_capability(value: str) -> TwinCapability:
    return TypeConverter.string_to_enum(value, TwinCapability, 'capability')