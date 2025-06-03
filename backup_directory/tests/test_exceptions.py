import pytest
from uuid import uuid4
from utils.exceptions import DigitalTwinPlatformError, RegistryError, EntityNotFoundError, EntityAlreadyExistsError, RegistryConnectionError, DigitalTwinError, DigitalTwinNotFoundError, DigitalTwinCreationError, DigitalTwinLifecycleError, ServiceError, ServiceNotFoundError, ServiceExecutionError, ServiceConfigurationError, DigitalReplicaError, DigitalReplicaNotFoundError, DataAggregationError, ProtocolError, ProtocolNotSupportedError, ProtocolConnectionError, MessageRoutingError, AuthenticationError, InvalidTokenError, UnauthorizedError, TokenExpiredError, StorageError, StorageConnectionError, DataValidationError, DataPersistenceError, FactoryError, FactoryConfigurationError, EntityCreationError, ConfigurationError, InvalidConfigurationError, MissingConfigurationError, PluginError, PluginNotFoundError, PluginLoadError, PluginConfigurationError

class TestBaseExceptions:

    def test_digital_twin_platform_error_basic(self):
        message = 'Test error message'
        error = DigitalTwinPlatformError(message)
        assert str(error) == message
        assert error.message == message
        assert error.details == {}

    def test_digital_twin_platform_error_with_details(self):
        message = 'Test error with details'
        details = {'key': 'value', 'number': 42}
        error = DigitalTwinPlatformError(message, details)
        assert str(error) == message
        assert error.message == message
        assert error.details == details

class TestRegistryExceptions:

    def test_entity_not_found_error(self):
        entity_type = 'DigitalTwin'
        entity_id = str(uuid4())
        error = EntityNotFoundError(entity_type, entity_id)
        expected_message = f"{entity_type} with ID '{entity_id}' not found"
        assert str(error) == expected_message
        assert error.entity_type == entity_type
        assert error.entity_id == entity_id
        assert isinstance(error, RegistryError)
        assert isinstance(error, DigitalTwinPlatformError)

    def test_entity_already_exists_error(self):
        entity_type = 'Service'
        entity_id = str(uuid4())
        error = EntityAlreadyExistsError(entity_type, entity_id)
        expected_message = f"{entity_type} with ID '{entity_id}' already exists"
        assert str(error) == expected_message
        assert error.entity_type == entity_type
        assert error.entity_id == entity_id
        assert isinstance(error, RegistryError)

    def test_registry_connection_error(self):
        message = 'Database connection failed'
        error = RegistryConnectionError(message)
        assert str(error) == message
        assert isinstance(error, RegistryError)

class TestDigitalTwinExceptions:

    def test_digital_twin_not_found_error(self):
        dt_id = str(uuid4())
        error = DigitalTwinNotFoundError(dt_id)
        expected_message = f"Digital Twin with ID '{dt_id}' not found"
        assert str(error) == expected_message
        assert error.dt_id == dt_id
        assert isinstance(error, DigitalTwinError)

    def test_digital_twin_creation_error(self):
        message = 'Failed to create Digital Twin'
        error = DigitalTwinCreationError(message)
        assert str(error) == message
        assert isinstance(error, DigitalTwinError)

class TestServiceExceptions:

    def test_service_not_found_error(self):
        service_id = str(uuid4())
        error = ServiceNotFoundError(service_id)
        expected_message = f"Service with ID '{service_id}' not found"
        assert str(error) == expected_message
        assert error.service_id == service_id
        assert isinstance(error, ServiceError)

    def test_service_execution_error(self):
        message = 'Service execution failed'
        error = ServiceExecutionError(message)
        assert str(error) == message
        assert isinstance(error, ServiceError)

class TestDigitalReplicaExceptions:

    def test_digital_replica_not_found_error(self):
        replica_id = str(uuid4())
        error = DigitalReplicaNotFoundError(replica_id)
        expected_message = f"Digital Replica with ID '{replica_id}' not found"
        assert str(error) == expected_message
        assert error.replica_id == replica_id
        assert isinstance(error, DigitalReplicaError)

    def test_data_aggregation_error(self):
        message = 'Data aggregation failed'
        error = DataAggregationError(message)
        assert str(error) == message
        assert isinstance(error, DigitalReplicaError)

class TestProtocolExceptions:

    def test_protocol_not_supported_error(self):
        protocol_name = 'UNKNOWN_PROTOCOL'
        error = ProtocolNotSupportedError(protocol_name)
        expected_message = f"Protocol '{protocol_name}' is not supported"
        assert str(error) == expected_message
        assert error.protocol_name == protocol_name
        assert isinstance(error, ProtocolError)

    def test_protocol_connection_error(self):
        message = 'Failed to connect to MQTT broker'
        error = ProtocolConnectionError(message)
        assert str(error) == message
        assert isinstance(error, ProtocolError)

class TestAuthenticationExceptions:

    def test_invalid_token_error(self):
        message = 'JWT token is invalid'
        error = InvalidTokenError(message)
        assert str(error) == message
        assert isinstance(error, AuthenticationError)

    def test_unauthorized_error(self):
        message = 'User not authorized for this operation'
        error = UnauthorizedError(message)
        assert str(error) == message
        assert isinstance(error, AuthenticationError)

    def test_token_expired_error(self):
        message = 'Authentication token has expired'
        error = TokenExpiredError(message)
        assert str(error) == message
        assert isinstance(error, AuthenticationError)

class TestStorageExceptions:

    def test_storage_connection_error(self):
        message = 'Failed to connect to database'
        error = StorageConnectionError(message)
        assert str(error) == message
        assert isinstance(error, StorageError)

    def test_data_validation_error(self):
        message = 'Data validation failed'
        error = DataValidationError(message)
        assert str(error) == message
        assert isinstance(error, StorageError)

    def test_data_persistence_error(self):
        message = 'Failed to persist data'
        error = DataPersistenceError(message)
        assert str(error) == message
        assert isinstance(error, StorageError)

class TestFactoryExceptions:

    def test_factory_configuration_error(self):
        message = 'Invalid factory configuration'
        error = FactoryConfigurationError(message)
        assert str(error) == message
        assert isinstance(error, FactoryError)

    def test_entity_creation_error(self):
        message = 'Failed to create entity'
        error = EntityCreationError(message)
        assert str(error) == message
        assert isinstance(error, FactoryError)

class TestConfigurationExceptions:

    def test_invalid_configuration_error(self):
        message = 'Configuration is invalid'
        error = InvalidConfigurationError(message)
        assert str(error) == message
        assert isinstance(error, ConfigurationError)

    def test_missing_configuration_error(self):
        config_key = 'database.host'
        error = MissingConfigurationError(config_key)
        expected_message = f"Missing required configuration: '{config_key}'"
        assert str(error) == expected_message
        assert error.config_key == config_key
        assert isinstance(error, ConfigurationError)

class TestPluginExceptions:

    def test_plugin_not_found_error(self):
        plugin_name = 'http_adapter'
        error = PluginNotFoundError(plugin_name)
        expected_message = f"Plugin '{plugin_name}' not found"
        assert str(error) == expected_message
        assert error.plugin_name == plugin_name
        assert isinstance(error, PluginError)

    def test_plugin_load_error(self):
        message = 'Failed to load plugin'
        error = PluginLoadError(message)
        assert str(error) == message
        assert isinstance(error, PluginError)

    def test_plugin_configuration_error(self):
        message = 'Plugin configuration is invalid'
        error = PluginConfigurationError(message)
        assert str(error) == message
        assert isinstance(error, PluginError)

class TestExceptionHierarchy:

    def test_all_exceptions_inherit_from_base(self):
        exception_classes = [RegistryError, DigitalTwinError, ServiceError, DigitalReplicaError, ProtocolError, AuthenticationError, StorageError, FactoryError, ConfigurationError, PluginError]
        for exception_class in exception_classes:
            assert issubclass(exception_class, DigitalTwinPlatformError)

    def test_specific_exceptions_inherit_from_category(self):
        test_cases = [(EntityNotFoundError, RegistryError), (EntityAlreadyExistsError, RegistryError), (DigitalTwinNotFoundError, DigitalTwinError), (ServiceNotFoundError, ServiceError), (DigitalReplicaNotFoundError, DigitalReplicaError), (ProtocolNotSupportedError, ProtocolError), (InvalidTokenError, AuthenticationError), (StorageConnectionError, StorageError), (FactoryConfigurationError, FactoryError), (InvalidConfigurationError, ConfigurationError), (PluginNotFoundError, PluginError)]
        for specific_exception, category_exception in test_cases:
            assert issubclass(specific_exception, category_exception)

    def test_exceptions_are_catchable_as_base_exception(self):
        try:
            raise DigitalTwinNotFoundError('test-id')
        except DigitalTwinPlatformError as e:
            assert isinstance(e, DigitalTwinNotFoundError)
            assert isinstance(e, DigitalTwinError)
            assert isinstance(e, DigitalTwinPlatformError)
        try:
            raise ServiceExecutionError('test error')
        except DigitalTwinPlatformError as e:
            assert isinstance(e, ServiceExecutionError)
            assert isinstance(e, ServiceError)
            assert isinstance(e, DigitalTwinPlatformError)
if __name__ == '__main__':
    pytest.main([__file__])