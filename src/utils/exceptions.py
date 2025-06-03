"""
Custom exceptions for the Digital Twin Platform.

This module defines all custom exceptions used throughout the platform,
providing specific error handling for different layers and components.
"""

from typing import Any, Dict, Optional


class DigitalTwinPlatformError(Exception):
    """Base exception for all Digital Twin Platform errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


# Registry Exceptions
class RegistryError(DigitalTwinPlatformError):
    """Base exception for registry-related errors."""
    pass


class EntityNotFoundError(RegistryError):
    """Raised when an entity is not found in the registry."""
    
    def __init__(self, entity_type: str, entity_id: str, details: Optional[Dict[str, Any]] = None):
        message = f"{entity_type} with ID '{entity_id}' not found"
        super().__init__(message, details)
        self.entity_type = entity_type
        self.entity_id = entity_id


class EntityAlreadyExistsError(RegistryError):
    """Raised when trying to create an entity that already exists."""
    
    def __init__(self, entity_type: str, entity_id: str, details: Optional[Dict[str, Any]] = None):
        message = f"{entity_type} with ID '{entity_id}' already exists"
        super().__init__(message, details)
        self.entity_type = entity_type
        self.entity_id = entity_id


class RegistryConnectionError(RegistryError):
    """Raised when registry cannot connect to storage backend."""
    pass


# Digital Twin Exceptions
class DigitalTwinError(DigitalTwinPlatformError):
    """Base exception for Digital Twin-related errors."""
    pass


class DigitalTwinNotFoundError(DigitalTwinError):
    """Raised when a Digital Twin is not found."""
    
    def __init__(self, dt_id: str, details: Optional[Dict[str, Any]] = None):
        message = f"Digital Twin with ID '{dt_id}' not found"
        super().__init__(message, details)
        self.dt_id = dt_id


class DigitalTwinCreationError(DigitalTwinError):
    """Raised when Digital Twin creation fails."""
    pass


class DigitalTwinLifecycleError(DigitalTwinError):
    """Raised when Digital Twin lifecycle operation fails."""
    pass


# Service Exceptions
class ServiceError(DigitalTwinPlatformError):
    """Base exception for Service-related errors."""
    pass


class ServiceNotFoundError(ServiceError):
    """Raised when a service is not found."""
    
    def __init__(self, service_id: str, details: Optional[Dict[str, Any]] = None):
        message = f"Service with ID '{service_id}' not found"
        super().__init__(message, details)
        self.service_id = service_id


class ServiceExecutionError(ServiceError):
    """Raised when service execution fails."""
    pass


class ServiceConfigurationError(ServiceError):
    """Raised when service configuration is invalid."""
    pass


# Digital Replica Exceptions
class DigitalReplicaError(DigitalTwinPlatformError):
    """Base exception for Digital Replica-related errors."""
    pass


class DigitalReplicaNotFoundError(DigitalReplicaError):
    """Raised when a Digital Replica is not found."""
    
    def __init__(self, replica_id: str, details: Optional[Dict[str, Any]] = None):
        message = f"Digital Replica with ID '{replica_id}' not found"
        super().__init__(message, details)
        self.replica_id = replica_id


class DataAggregationError(DigitalReplicaError):
    """Raised when data aggregation fails."""
    pass


# Protocol Exceptions
class ProtocolError(DigitalTwinPlatformError):
    """Base exception for protocol-related errors."""
    pass


class ProtocolNotSupportedError(ProtocolError):
    """Raised when a protocol is not supported."""
    
    def __init__(self, protocol_name: str, details: Optional[Dict[str, Any]] = None):
        message = f"Protocol '{protocol_name}' is not supported"
        super().__init__(message, details)
        self.protocol_name = protocol_name


class ProtocolConnectionError(ProtocolError):
    """Raised when protocol connection fails."""
    pass


class MessageRoutingError(ProtocolError):
    """Raised when message routing fails."""
    pass


# Authentication Exceptions
class AuthenticationError(DigitalTwinPlatformError):
    """Base exception for authentication-related errors."""
    pass


class InvalidTokenError(AuthenticationError):
    """Raised when authentication token is invalid."""
    pass


class UnauthorizedError(AuthenticationError):
    """Raised when user is not authorized for the operation."""
    pass


class TokenExpiredError(AuthenticationError):
    """Raised when authentication token has expired."""
    pass


# Storage Exceptions
class StorageError(DigitalTwinPlatformError):
    """Base exception for storage-related errors."""
    pass


class StorageConnectionError(StorageError):
    """Raised when storage connection fails."""
    pass


class DataValidationError(StorageError):
    """Raised when data validation fails."""
    pass


class DataPersistenceError(StorageError):
    """Raised when data persistence operation fails."""
    pass


# Factory Exceptions
class FactoryError(DigitalTwinPlatformError):
    """Base exception for factory-related errors."""
    pass


class FactoryConfigurationError(FactoryError):
    """Raised when factory configuration is invalid."""
    pass


class EntityCreationError(FactoryError):
    """Raised when entity creation through factory fails."""
    pass


# Configuration Exceptions
class ConfigurationError(DigitalTwinPlatformError):
    """Base exception for configuration-related errors."""
    pass


class InvalidConfigurationError(ConfigurationError):
    """Raised when configuration is invalid."""
    pass


class MissingConfigurationError(ConfigurationError):
    """Raised when required configuration is missing."""
    
    def __init__(self, config_key: str, details: Optional[Dict[str, Any]] = None):
        message = f"Missing required configuration: '{config_key}'"
        super().__init__(message, details)
        self.config_key = config_key


# Plugin Exceptions
class PluginError(DigitalTwinPlatformError):
    """Base exception for plugin-related errors."""
    pass


class PluginNotFoundError(PluginError):
    """Raised when a plugin is not found."""
    
    def __init__(self, plugin_name: str, details: Optional[Dict[str, Any]] = None):
        message = f"Plugin '{plugin_name}' not found"
        super().__init__(message, details)
        self.plugin_name = plugin_name


class PluginLoadError(PluginError):
    """Raised when plugin loading fails."""
    pass


class PluginConfigurationError(PluginError):
    """Raised when plugin configuration is invalid."""
    pass


class AuthorizationError(AuthenticationError):
    """Raised when authorization check fails."""
    pass





class RateLimitError(AuthenticationError):
    """Raised when API rate limit is exceeded."""
    
    def __init__(self, message: str, retry_after: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.retry_after = retry_after  # Seconds until retry allowed


# Validation Exceptions
class ValidationError(DigitalTwinPlatformError):
    """Base exception for validation-related errors."""
    
    def __init__(self, message: str, field: Optional[str] = None, value: Any = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.field = field
        self.value = value


class SchemaValidationError(ValidationError):
    """Raised when data doesn't match expected schema."""
    pass


class PermissionValidationError(ValidationError):
    """Raised when permission format is invalid."""
    pass


class APIGatewayError(DigitalTwinPlatformError):
    """Base exception for API Gateway-related errors."""
    pass