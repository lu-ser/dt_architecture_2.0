import pytest
import json
import yaml
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from utils.config import PlatformConfig, DatabaseConfig, RedisConfig, AuthConfig, ProtocolConfig, StorageConfig, ContainerConfig, LoggingConfig, MonitoringConfig, SecurityConfig, ConfigFormat, ConfigEnvironment, JsonConfigLoader, YamlConfigLoader, EnvironmentConfigLoader, ConfigManager, ConfigValidator, get_config, load_config_from_file, load_config_from_env
from utils.exceptions import InvalidConfigurationError, MissingConfigurationError, ConfigurationError

class TestConfigurationClasses:

    def test_database_config_defaults(self):
        config = DatabaseConfig()
        assert config.host == 'localhost'
        assert config.port == 5432
        assert config.database == 'digital_twin_platform'
        assert config.username == 'dt_user'
        assert config.password == ''
        assert config.pool_size == 10
        assert config.max_overflow == 20
        assert config.echo is False
        assert config.ssl_mode == 'prefer'
        assert config.connection_timeout == 30
        assert config.custom_params == {}

    def test_redis_config_defaults(self):
        config = RedisConfig()
        assert config.host == 'localhost'
        assert config.port == 6379
        assert config.database == 0
        assert config.password is None
        assert config.max_connections == 50
        assert config.connection_timeout == 10
        assert config.socket_timeout == 10
        assert config.retry_on_timeout is True
        assert config.health_check_interval == 30

    def test_auth_config_defaults(self):
        config = AuthConfig()
        assert config.provider == 'jwt'
        assert config.secret_key == ''
        assert config.algorithm == 'HS256'
        assert config.access_token_expire_minutes == 30
        assert config.refresh_token_expire_days == 7
        assert config.issuer == 'digital-twin-platform'
        assert config.audience == 'digital-twin-users'
        assert config.oauth_providers == {}

    def test_platform_config_defaults(self):
        config = PlatformConfig()
        assert config.environment == ConfigEnvironment.DEVELOPMENT
        assert config.debug is False
        assert config.version == '1.0.0'
        assert config.service_name == 'digital-twin-platform'
        assert config.timezone == 'UTC'
        assert isinstance(config.database, DatabaseConfig)
        assert isinstance(config.redis, RedisConfig)
        assert isinstance(config.auth, AuthConfig)
        assert isinstance(config.protocols, ProtocolConfig)
        assert isinstance(config.storage, StorageConfig)
        assert isinstance(config.container, ContainerConfig)
        assert isinstance(config.logging, LoggingConfig)
        assert isinstance(config.monitoring, MonitoringConfig)
        assert isinstance(config.security, SecurityConfig)
        assert config.custom == {}

class TestConfigLoaders:

    def test_json_config_loader_from_string(self):
        loader = JsonConfigLoader()
        json_string = '{"database": {"host": "test-host", "port": 3306}}'
        result = loader.load(json_string)
        assert result['database']['host'] == 'test-host'
        assert result['database']['port'] == 3306
        assert loader.supports_format(ConfigFormat.JSON) is True
        assert loader.supports_format(ConfigFormat.YAML) is False

    def test_json_config_loader_from_file(self):
        loader = JsonConfigLoader()
        config_data = {'environment': 'testing', 'database': {'host': 'test-db', 'port': 5432}}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            temp_file = f.name
        try:
            result = loader.load(temp_file)
            assert result['environment'] == 'testing'
            assert result['database']['host'] == 'test-db'
            assert result['database']['port'] == 5432
        finally:
            os.unlink(temp_file)

    def test_json_config_loader_invalid_json(self):
        loader = JsonConfigLoader()
        invalid_json = '{"invalid": json}'
        with pytest.raises(InvalidConfigurationError):
            loader.load(invalid_json)

    def test_yaml_config_loader_from_string(self):
        loader = YamlConfigLoader()
        yaml_string = '\ndatabase:\n  host: test-host\n  port: 3306\nenvironment: development\n        '
        result = loader.load(yaml_string)
        assert result['database']['host'] == 'test-host'
        assert result['database']['port'] == 3306
        assert result['environment'] == 'development'
        assert loader.supports_format(ConfigFormat.YAML) is True
        assert loader.supports_format(ConfigFormat.JSON) is False

    def test_yaml_config_loader_from_file(self):
        loader = YamlConfigLoader()
        config_data = {'environment': 'testing', 'database': {'host': 'test-db', 'port': 5432}}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            temp_file = f.name
        try:
            result = loader.load(temp_file)
            assert result['environment'] == 'testing'
            assert result['database']['host'] == 'test-db'
            assert result['database']['port'] == 5432
        finally:
            os.unlink(temp_file)

    def test_environment_config_loader(self):
        loader = EnvironmentConfigLoader('TEST_')
        test_env = {'TEST_DATABASE_HOST': 'env-host', 'TEST_DATABASE_PORT': '3307', 'TEST_DEBUG': 'true', 'TEST_AUTH_SECRET_KEY': 'secret123', 'OTHER_VAR': 'ignored'}
        with patch.dict(os.environ, test_env, clear=True):
            result = loader.load()
        assert result['database']['host'] == 'env-host'
        assert result['database']['port'] == 3307
        assert result['debug'] is True
        assert result['auth']['secret']['key'] == 'secret123'
        assert 'other' not in result
        assert loader.supports_format(ConfigFormat.ENV) is True

    def test_environment_config_loader_parse_value(self):
        loader = EnvironmentConfigLoader()
        assert loader._parse_value('true') is True
        assert loader._parse_value('false') is False
        assert loader._parse_value('True') is True
        assert loader._parse_value('FALSE') is False
        assert loader._parse_value('42') == 42
        assert loader._parse_value('3.14') == 3.14
        assert loader._parse_value('{"key": "value"}') == {'key': 'value'}
        assert loader._parse_value('[1, 2, 3]') == [1, 2, 3]
        assert loader._parse_value('plain string') == 'plain string'

class TestConfigValidator:

    def test_validate_valid_config(self):
        validator = ConfigValidator()
        config = PlatformConfig()
        config.auth.secret_key = 'a' * 32
        errors = validator.validate(config)
        assert len(errors) == 0

    def test_validate_missing_secret_key(self):
        validator = ConfigValidator()
        config = PlatformConfig()
        config.auth.secret_key = ''
        errors = validator.validate(config)
        assert len(errors) > 0
        assert any(('secret_key is required' in error for error in errors))

    def test_validate_short_secret_key(self):
        validator = ConfigValidator()
        config = PlatformConfig()
        config.auth.secret_key = 'short'
        errors = validator.validate(config)
        assert len(errors) > 0
        assert any(('must be at least 32 characters' in error for error in errors))

    def test_validate_database_port_range(self):
        validator = ConfigValidator()
        config = PlatformConfig()
        config.auth.secret_key = 'a' * 32
        config.database.port = 70000
        errors = validator.validate(config)
        assert len(errors) > 0
        assert any(('port must be between 1 and 65535' in error for error in errors))

    def test_validate_ssl_configuration(self):
        validator = ConfigValidator()
        config = PlatformConfig()
        config.auth.secret_key = 'a' * 32
        config.security.ssl_enabled = True
        config.security.ssl_cert_path = ''
        config.security.ssl_key_path = ''
        errors = validator.validate(config)
        assert len(errors) >= 2
        assert any(('ssl_cert_path is required' in error for error in errors))
        assert any(('ssl_key_path is required' in error for error in errors))

class TestConfigManager:

    def test_config_manager_load_from_dict(self):
        manager = ConfigManager()
        config_data = {'environment': 'testing', 'debug': True, 'database': {'host': 'test-host', 'port': 3306}}
        config = manager.load_from_dict(config_data)
        assert config.environment == ConfigEnvironment.TESTING
        assert config.debug is True

    def test_config_manager_load_from_file_json(self):
        manager = ConfigManager()
        config_data = {'environment': 'development', 'database': {'host': 'file-host', 'port': 5433}, 'auth': {'secret_key': 'file_secret_key_123456789012345'}}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            temp_file = f.name
        try:
            config = manager.load_from_file(temp_file)
            assert isinstance(config, PlatformConfig)
        finally:
            os.unlink(temp_file)

    def test_config_manager_auto_detect_format(self):
        manager = ConfigManager()
        assert manager._detect_format(Path('config.json')) == ConfigFormat.JSON
        assert manager._detect_format(Path('config.yaml')) == ConfigFormat.YAML
        assert manager._detect_format(Path('config.yml')) == ConfigFormat.YAML
        with pytest.raises(InvalidConfigurationError):
            manager._detect_format(Path('config.xml'))

    def test_config_manager_missing_file(self):
        manager = ConfigManager()
        with pytest.raises(MissingConfigurationError):
            manager.load_from_file('nonexistent_file.json')

    def test_config_manager_get_config_default(self):
        manager = ConfigManager()
        manager._config = None
        with patch.object(manager, 'load_from_environment') as mock_load:
            mock_load.side_effect = Exception('No env config')
            config = manager.get_config()
            assert isinstance(config, PlatformConfig)
            assert config.environment == ConfigEnvironment.DEVELOPMENT

class TestGlobalConfigFunctions:

    def test_get_config(self):
        config = get_config()
        assert isinstance(config, PlatformConfig)

    @patch('utils.config.config_manager')
    def test_load_config_from_file(self, mock_manager):
        mock_config = PlatformConfig()
        mock_manager.load_from_file.return_value = mock_config
        result = load_config_from_file('test.json')
        mock_manager.load_from_file.assert_called_once_with('test.json')
        assert mock_manager._config == mock_config
        assert result == mock_config

    @patch('utils.config.config_manager')
    def test_load_config_from_env(self, mock_manager):
        mock_config = PlatformConfig()
        mock_manager.load_from_environment.return_value = mock_config
        result = load_config_from_env('TEST_')
        mock_manager.load_from_environment.assert_called_once_with('TEST_')
        assert mock_manager._config == mock_config
        assert result == mock_config

class TestConfigurationIntegration:

    def test_full_configuration_workflow(self):
        config_data = {'environment': 'testing', 'debug': True, 'service_name': 'test-platform', 'database': {'host': 'test-db', 'port': 5432, 'database': 'test_db', 'username': 'test_user'}, 'auth': {'secret_key': 'test_secret_key_12345678901234567890', 'access_token_expire_minutes': 60}, 'protocols': {'enabled_protocols': ['http', 'mqtt']}}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            temp_file = f.name
        try:
            manager = ConfigManager()
            config = manager.load_from_file(temp_file)
            assert isinstance(config, PlatformConfig)
            assert config.debug is True
            assert config.service_name == 'test-platform'
        finally:
            os.unlink(temp_file)
if __name__ == '__main__':
    pytest.main([__file__, '-v'])