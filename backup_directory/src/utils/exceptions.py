from typing import Any, Dict, Optional

class DigitalTwinPlatformError(Exception):

    def __init__(self, message: str, details: Optional[Dict[str, Any]]=None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

class RegistryError(DigitalTwinPlatformError):
    pass

class EntityNotFoundError(RegistryError):

    def __init__(self, entity_type: str, entity_id: str, details: Optional[Dict[str, Any]]=None):
        message = f"{entity_type} with ID '{entity_id}' not found"
        super().__init__(message, details)
        self.entity_type = entity_type
        self.entity_id = entity_id

class EntityAlreadyExistsError(RegistryError):

    def __init__(self, entity_type: str, entity_id: str, details: Optional[Dict[str, Any]]=None):
        message = f"{entity_type} with ID '{entity_id}' already exists"
        super().__init__(message, details)
        self.entity_type = entity_type
        self.entity_id = entity_id

class RegistryConnectionError(RegistryError):
    pass

class DigitalTwinError(DigitalTwinPlatformError):
    pass

class DigitalTwinNotFoundError(DigitalTwinError):

    def __init__(self, dt_id: str, details: Optional[Dict[str, Any]]=None):
        message = f"Digital Twin with ID '{dt_id}' not found"
        super().__init__(message, details)
        self.dt_id = dt_id

class DigitalTwinCreationError(DigitalTwinError):
    pass

class DigitalTwinLifecycleError(DigitalTwinError):
    pass

class ServiceError(DigitalTwinPlatformError):
    pass

class ServiceNotFoundError(ServiceError):

    def __init__(self, service_id: str, details: Optional[Dict[str, Any]]=None):
        message = f"Service with ID '{service_id}' not found"
        super().__init__(message, details)
        self.service_id = service_id

class ServiceExecutionError(ServiceError):
    pass

class ServiceConfigurationError(ServiceError):
    pass

class DigitalReplicaError(DigitalTwinPlatformError):
    pass

class DigitalReplicaNotFoundError(DigitalReplicaError):

    def __init__(self, replica_id: str, details: Optional[Dict[str, Any]]=None):
        message = f"Digital Replica with ID '{replica_id}' not found"
        super().__init__(message, details)
        self.replica_id = replica_id

class DataAggregationError(DigitalReplicaError):
    pass

class ProtocolError(DigitalTwinPlatformError):
    pass

class ProtocolNotSupportedError(ProtocolError):

    def __init__(self, protocol_name: str, details: Optional[Dict[str, Any]]=None):
        message = f"Protocol '{protocol_name}' is not supported"
        super().__init__(message, details)
        self.protocol_name = protocol_name

class ProtocolConnectionError(ProtocolError):
    pass

class MessageRoutingError(ProtocolError):
    pass

class AuthenticationError(DigitalTwinPlatformError):
    pass

class InvalidTokenError(AuthenticationError):
    pass

class UnauthorizedError(AuthenticationError):
    pass

class TokenExpiredError(AuthenticationError):
    pass

class StorageError(DigitalTwinPlatformError):
    pass

class StorageConnectionError(StorageError):
    pass

class DataValidationError(StorageError):
    pass

class DataPersistenceError(StorageError):
    pass

class FactoryError(DigitalTwinPlatformError):
    pass

class FactoryConfigurationError(FactoryError):
    pass

class EntityCreationError(FactoryError):
    pass

class ConfigurationError(DigitalTwinPlatformError):
    pass

class InvalidConfigurationError(ConfigurationError):
    pass

class MissingConfigurationError(ConfigurationError):

    def __init__(self, config_key: str, details: Optional[Dict[str, Any]]=None):
        message = f"Missing required configuration: '{config_key}'"
        super().__init__(message, details)
        self.config_key = config_key

class PluginError(DigitalTwinPlatformError):
    pass

class PluginNotFoundError(PluginError):

    def __init__(self, plugin_name: str, details: Optional[Dict[str, Any]]=None):
        message = f"Plugin '{plugin_name}' not found"
        super().__init__(message, details)
        self.plugin_name = plugin_name

class PluginLoadError(PluginError):
    pass

class PluginConfigurationError(PluginError):
    pass

class AuthorizationError(AuthenticationError):
    pass

class RateLimitError(AuthenticationError):

    def __init__(self, message: str, retry_after: Optional[int]=None, details: Optional[Dict[str, Any]]=None):
        super().__init__(message, details)
        self.retry_after = retry_after

class ValidationError(DigitalTwinPlatformError):

    def __init__(self, message: str, field: Optional[str]=None, value: Any=None, details: Optional[Dict[str, Any]]=None):
        super().__init__(message, details)
        self.field = field
        self.value = value

class SchemaValidationError(ValidationError):
    pass

class PermissionValidationError(ValidationError):
    pass

class APIGatewayError(DigitalTwinPlatformError):
    pass

class DeserializationError(Exception):
    pass