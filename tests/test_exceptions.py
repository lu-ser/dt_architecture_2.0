"""
Unit tests for custom exceptions in the Digital Twin Platform.

Tests the exception hierarchy, error messages, and custom functionality
of all platform-specific exceptions.
"""

import pytest
from uuid import uuid4

from utils.exceptions import (
    # Base exceptions
    DigitalTwinPlatformError,
    
    # Registry exceptions
    RegistryError,
    EntityNotFoundError,
    EntityAlreadyExistsError,
    RegistryConnectionError,
    
    # Digital Twin exceptions
    DigitalTwinError,
    DigitalTwinNotFoundError,
    DigitalTwinCreationError,
    DigitalTwinLifecycleError,
    
    # Service exceptions
    ServiceError,
    ServiceNotFoundError,
    ServiceExecutionError,
    ServiceConfigurationError,
    
    # Digital Replica exceptions
    DigitalReplicaError,
    DigitalReplicaNotFoundError,
    DataAggregationError,
    
    # Protocol exceptions
    ProtocolError,
    ProtocolNotSupportedError,
    ProtocolConnectionError,
    MessageRoutingError,
    
    # Authentication exceptions
    AuthenticationError,
    InvalidTokenError,
    UnauthorizedError,
    TokenExpiredError,
    
    # Storage exceptions
    StorageError,
    StorageConnectionError,
    DataValidationError,
    DataPersistenceError,
    
    # Factory exceptions
    FactoryError,
    FactoryConfigurationError,
    EntityCreationError,
    
    # Configuration exceptions
    ConfigurationError,
    InvalidConfigurationError,
    MissingConfigurationError,
    
    # Plugin exceptions
    PluginError,
    PluginNotFoundError,
    PluginLoadError,
    PluginConfigurationError
)


class TestBaseExceptions:
    """Test base exception functionality."""
    
    def test_digital_twin_platform_error_basic(self):
        """Test basic DigitalTwinPlatformError functionality."""
        message = "Test error message"
        error = DigitalTwinPlatformError(message)
        
        assert str(error) == message
        assert error.message == message
        assert error.details == {}
    
    def test_digital_twin_platform_error_with_details(self):
        """Test DigitalTwinPlatformError with details."""
        message = "Test error with details"
        details = {"key": "value", "number": 42}
        error = DigitalTwinPlatformError(message, details)
        
        assert str(error) == message
        assert error.message == message
        assert error.details == details


class TestRegistryExceptions:
    """Test registry-related exceptions."""
    
    def test_entity_not_found_error(self):
        """Test EntityNotFoundError functionality."""
        entity_type = "DigitalTwin"
        entity_id = str(uuid4())
        
        error = EntityNotFoundError(entity_type, entity_id)
        
        expected_message = f"{entity_type} with ID '{entity_id}' not found"
        assert str(error) == expected_message
        assert error.entity_type == entity_type
        assert error.entity_id == entity_id
        assert isinstance(error, RegistryError)
        assert isinstance(error, DigitalTwinPlatformError)
    
    def test_entity_already_exists_error(self):
        """Test EntityAlreadyExistsError functionality."""
        entity_type = "Service"
        entity_id = str(uuid4())
        
        error = EntityAlreadyExistsError(entity_type, entity_id)
        
        expected_message = f"{entity_type} with ID '{entity_id}' already exists"
        assert str(error) == expected_message
        assert error.entity_type == entity_type
        assert error.entity_id == entity_id
        assert isinstance(error, RegistryError)
    
    def test_registry_connection_error(self):
        """Test RegistryConnectionError functionality."""
        message = "Database connection failed"
        error = RegistryConnectionError(message)
        
        assert str(error) == message
        assert isinstance(error, RegistryError)


class TestDigitalTwinExceptions:
    """Test Digital Twin-related exceptions."""
    
    def test_digital_twin_not_found_error(self):
        """Test DigitalTwinNotFoundError functionality."""
        dt_id = str(uuid4())
        
        error = DigitalTwinNotFoundError(dt_id)
        
        expected_message = f"Digital Twin with ID '{dt_id}' not found"
        assert str(error) == expected_message
        assert error.dt_id == dt_id
        assert isinstance(error, DigitalTwinError)
    
    def test_digital_twin_creation_error(self):
        """Test DigitalTwinCreationError functionality."""
        message = "Failed to create Digital Twin"
        error = DigitalTwinCreationError(message)
        
        assert str(error) == message
        assert isinstance(error, DigitalTwinError)


class TestServiceExceptions:
    """Test Service-related exceptions."""
    
    def test_service_not_found_error(self):
        """Test ServiceNotFoundError functionality."""
        service_id = str(uuid4())
        
        error = ServiceNotFoundError(service_id)
        
        expected_message = f"Service with ID '{service_id}' not found"
        assert str(error) == expected_message
        assert error.service_id == service_id
        assert isinstance(error, ServiceError)
    
    def test_service_execution_error(self):
        """Test ServiceExecutionError functionality."""
        message = "Service execution failed"
        error = ServiceExecutionError(message)
        
        assert str(error) == message
        assert isinstance(error, ServiceError)


class TestDigitalReplicaExceptions:
    """Test Digital Replica-related exceptions."""
    
    def test_digital_replica_not_found_error(self):
        """Test DigitalReplicaNotFoundError functionality."""
        replica_id = str(uuid4())
        
        error = DigitalReplicaNotFoundError(replica_id)
        
        expected_message = f"Digital Replica with ID '{replica_id}' not found"
        assert str(error) == expected_message
        assert error.replica_id == replica_id
        assert isinstance(error, DigitalReplicaError)
    
    def test_data_aggregation_error(self):
        """Test DataAggregationError functionality."""
        message = "Data aggregation failed"
        error = DataAggregationError(message)
        
        assert str(error) == message
        assert isinstance(error, DigitalReplicaError)


class TestProtocolExceptions:
    """Test Protocol-related exceptions."""
    
    def test_protocol_not_supported_error(self):
        """Test ProtocolNotSupportedError functionality."""
        protocol_name = "UNKNOWN_PROTOCOL"
        
        error = ProtocolNotSupportedError(protocol_name)
        
        expected_message = f"Protocol '{protocol_name}' is not supported"
        assert str(error) == expected_message
        assert error.protocol_name == protocol_name
        assert isinstance(error, ProtocolError)
    
    def test_protocol_connection_error(self):
        """Test ProtocolConnectionError functionality."""
        message = "Failed to connect to MQTT broker"
        error = ProtocolConnectionError(message)
        
        assert str(error) == message
        assert isinstance(error, ProtocolError)


class TestAuthenticationExceptions:
    """Test Authentication-related exceptions."""
    
    def test_invalid_token_error(self):
        """Test InvalidTokenError functionality."""
        message = "JWT token is invalid"
        error = InvalidTokenError(message)
        
        assert str(error) == message
        assert isinstance(error, AuthenticationError)
    
    def test_unauthorized_error(self):
        """Test UnauthorizedError functionality."""
        message = "User not authorized for this operation"
        error = UnauthorizedError(message)
        
        assert str(error) == message
        assert isinstance(error, AuthenticationError)
    
    def test_token_expired_error(self):
        """Test TokenExpiredError functionality."""
        message = "Authentication token has expired"
        error = TokenExpiredError(message)
        
        assert str(error) == message
        assert isinstance(error, AuthenticationError)


class TestStorageExceptions:
    """Test Storage-related exceptions."""
    
    def test_storage_connection_error(self):
        """Test StorageConnectionError functionality."""
        message = "Failed to connect to database"
        error = StorageConnectionError(message)
        
        assert str(error) == message
        assert isinstance(error, StorageError)
    
    def test_data_validation_error(self):
        """Test DataValidationError functionality."""
        message = "Data validation failed"
        error = DataValidationError(message)
        
        assert str(error) == message
        assert isinstance(error, StorageError)
    
    def test_data_persistence_error(self):
        """Test DataPersistenceError functionality."""
        message = "Failed to persist data"
        error = DataPersistenceError(message)
        
        assert str(error) == message
        assert isinstance(error, StorageError)


class TestFactoryExceptions:
    """Test Factory-related exceptions."""
    
    def test_factory_configuration_error(self):
        """Test FactoryConfigurationError functionality."""
        message = "Invalid factory configuration"
        error = FactoryConfigurationError(message)
        
        assert str(error) == message
        assert isinstance(error, FactoryError)
    
    def test_entity_creation_error(self):
        """Test EntityCreationError functionality."""
        message = "Failed to create entity"
        error = EntityCreationError(message)
        
        assert str(error) == message
        assert isinstance(error, FactoryError)


class TestConfigurationExceptions:
    """Test Configuration-related exceptions."""
    
    def test_invalid_configuration_error(self):
        """Test InvalidConfigurationError functionality."""
        message = "Configuration is invalid"
        error = InvalidConfigurationError(message)
        
        assert str(error) == message
        assert isinstance(error, ConfigurationError)
    
    def test_missing_configuration_error(self):
        """Test MissingConfigurationError functionality."""
        config_key = "database.host"
        
        error = MissingConfigurationError(config_key)
        
        expected_message = f"Missing required configuration: '{config_key}'"
        assert str(error) == expected_message
        assert error.config_key == config_key
        assert isinstance(error, ConfigurationError)


class TestPluginExceptions:
    """Test Plugin-related exceptions."""
    
    def test_plugin_not_found_error(self):
        """Test PluginNotFoundError functionality."""
        plugin_name = "http_adapter"
        
        error = PluginNotFoundError(plugin_name)
        
        expected_message = f"Plugin '{plugin_name}' not found"
        assert str(error) == expected_message
        assert error.plugin_name == plugin_name
        assert isinstance(error, PluginError)
    
    def test_plugin_load_error(self):
        """Test PluginLoadError functionality."""
        message = "Failed to load plugin"
        error = PluginLoadError(message)
        
        assert str(error) == message
        assert isinstance(error, PluginError)
    
    def test_plugin_configuration_error(self):
        """Test PluginConfigurationError functionality."""
        message = "Plugin configuration is invalid"
        error = PluginConfigurationError(message)
        
        assert str(error) == message
        assert isinstance(error, PluginError)


class TestExceptionHierarchy:
    """Test exception inheritance hierarchy."""
    
    def test_all_exceptions_inherit_from_base(self):
        """Test that all custom exceptions inherit from DigitalTwinPlatformError."""
        exception_classes = [
            RegistryError,
            DigitalTwinError,
            ServiceError,
            DigitalReplicaError,
            ProtocolError,
            AuthenticationError,
            StorageError,
            FactoryError,
            ConfigurationError,
            PluginError
        ]
        
        for exception_class in exception_classes:
            assert issubclass(exception_class, DigitalTwinPlatformError)
    
    def test_specific_exceptions_inherit_from_category(self):
        """Test that specific exceptions inherit from their category."""
        test_cases = [
            (EntityNotFoundError, RegistryError),
            (EntityAlreadyExistsError, RegistryError),
            (DigitalTwinNotFoundError, DigitalTwinError),
            (ServiceNotFoundError, ServiceError),
            (DigitalReplicaNotFoundError, DigitalReplicaError),
            (ProtocolNotSupportedError, ProtocolError),
            (InvalidTokenError, AuthenticationError),
            (StorageConnectionError, StorageError),
            (FactoryConfigurationError, FactoryError),
            (InvalidConfigurationError, ConfigurationError),
            (PluginNotFoundError, PluginError)
        ]
        
        for specific_exception, category_exception in test_cases:
            assert issubclass(specific_exception, category_exception)
    
    def test_exceptions_are_catchable_as_base_exception(self):
        """Test that all exceptions can be caught as base exception."""
        try:
            raise DigitalTwinNotFoundError("test-id")
        except DigitalTwinPlatformError as e:
            assert isinstance(e, DigitalTwinNotFoundError)
            assert isinstance(e, DigitalTwinError)
            assert isinstance(e, DigitalTwinPlatformError)
        
        try:
            raise ServiceExecutionError("test error")
        except DigitalTwinPlatformError as e:
            assert isinstance(e, ServiceExecutionError)
            assert isinstance(e, ServiceError)
            assert isinstance(e, DigitalTwinPlatformError)


if __name__ == "__main__":
    pytest.main([__file__])