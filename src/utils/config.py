"""
Configuration management for the Digital Twin Platform.

This module provides centralized configuration management with support for
multiple formats, environments, validation, and dynamic updates.
"""

import os
import json
import yaml
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Type, Set
from dataclasses import dataclass, field
from enum import Enum

from src.utils.exceptions import (
    ConfigurationError, 
    InvalidConfigurationError, 
    MissingConfigurationError
)


class ConfigFormat(Enum):
    """Supported configuration formats."""
    JSON = "json"
    YAML = "yaml"
    TOML = "toml"
    ENV = "env"
    DICT = "dict"


class ConfigEnvironment(Enum):
    """Configuration environments."""
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"
    LOCAL = "local"


@dataclass
class DatabaseConfig:
    """Database configuration."""
    host: str = "localhost"
    port: int = 5432
    database: str = "digital_twin_platform"
    username: str = "dt_user"
    password: str = ""
    pool_size: int = 10
    max_overflow: int = 20
    echo: bool = False
    ssl_mode: str = "prefer"
    connection_timeout: int = 30
    custom_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RedisConfig:
    """Redis configuration."""
    host: str = "localhost"
    port: int = 6379
    database: int = 0
    password: Optional[str] = None
    max_connections: int = 50
    connection_timeout: int = 10
    socket_timeout: int = 10
    retry_on_timeout: bool = True
    health_check_interval: int = 30


@dataclass
class AuthConfig:
    """Authentication configuration."""
    provider: str = "jwt"
    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    issuer: str = "digital-twin-platform"
    audience: str = "digital-twin-users"
    oauth_providers: Dict[str, Dict[str, str]] = field(default_factory=dict)


@dataclass
class ProtocolConfig:
    """Protocol configuration."""
    enabled_protocols: List[str] = field(default_factory=lambda: ["http"])
    http_config: Dict[str, Any] = field(default_factory=lambda: {
        "host": "0.0.0.0",
        "port": 8000,
        "max_connections": 1000,
        "timeout": 60
    })
    mqtt_config: Dict[str, Any] = field(default_factory=lambda: {
        "broker_host": "localhost",
        "broker_port": 1883,
        "keepalive": 60,
        "qos": 1
    })
    custom_protocols: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class StorageConfig:
    """Storage configuration."""
    primary_storage: str = "postgresql"
    cache_storage: str = "redis"
    file_storage_path: str = "/data/files"
    backup_storage_path: str = "/data/backups"
    retention_days: int = 90
    compression_enabled: bool = True
    encryption_enabled: bool = False
    storage_adapters: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class ContainerConfig:
    """Container and deployment configuration."""
    container_runtime: str = "docker"
    registry_url: str = "localhost:5000"
    base_image: str = "python:3.11-slim"
    resource_limits: Dict[str, str] = field(default_factory=lambda: {
        "memory": "512Mi",
        "cpu": "500m"
    })
    kubernetes_namespace: str = "digital-twin-platform"
    auto_scaling_enabled: bool = False
    health_check_enabled: bool = True


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    handlers: List[str] = field(default_factory=lambda: ["console", "file"])
    file_path: str = "/logs/platform.log"
    max_file_size: str = "100MB"
    backup_count: int = 5
    json_logging: bool = False
    structured_logging: bool = True


@dataclass
class MonitoringConfig:
    """Monitoring and metrics configuration."""
    enabled: bool = True
    metrics_port: int = 9090
    health_check_port: int = 8080
    prometheus_enabled: bool = True
    grafana_enabled: bool = False
    alert_manager_url: str = ""
    custom_metrics: List[str] = field(default_factory=list)


@dataclass
class SecurityConfig:
    """Security configuration."""
    encryption_key: str = ""
    api_rate_limiting: bool = True
    rate_limit_requests: int = 100
    rate_limit_window: int = 60  # seconds
    cors_enabled: bool = True
    cors_origins: List[str] = field(default_factory=lambda: ["*"])
    ssl_enabled: bool = False
    ssl_cert_path: str = ""
    ssl_key_path: str = ""


@dataclass
class PlatformConfig:
    """Main platform configuration."""
    environment: ConfigEnvironment = ConfigEnvironment.DEVELOPMENT
    debug: bool = False
    version: str = "1.0.0"
    service_name: str = "digital-twin-platform"
    timezone: str = "UTC"
    
    # Component configurations
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    protocols: ProtocolConfig = field(default_factory=ProtocolConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    container: ContainerConfig = field(default_factory=ContainerConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    
    # Custom configurations
    custom: Dict[str, Any] = field(default_factory=dict)


class IConfigLoader(ABC):
    """Interface for configuration loaders."""
    
    @abstractmethod
    def load(self, source: str) -> Dict[str, Any]:
        """Load configuration from source."""
        pass
    
    @abstractmethod
    def supports_format(self, format_type: ConfigFormat) -> bool:
        """Check if loader supports the format."""
        pass


class JsonConfigLoader(IConfigLoader):
    """JSON configuration loader."""
    
    def load(self, source: str) -> Dict[str, Any]:
        """Load configuration from JSON file or string."""
        try:
            if os.path.isfile(source):
                with open(source, 'r') as f:
                    return json.load(f)
            else:
                return json.loads(source)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            raise InvalidConfigurationError(f"Invalid JSON configuration: {e}")
    
    def supports_format(self, format_type: ConfigFormat) -> bool:
        """Check if loader supports JSON format."""
        return format_type == ConfigFormat.JSON


class YamlConfigLoader(IConfigLoader):
    """YAML configuration loader."""
    
    def load(self, source: str) -> Dict[str, Any]:
        """Load configuration from YAML file or string."""
        try:
            if os.path.isfile(source):
                with open(source, 'r') as f:
                    return yaml.safe_load(f)
            else:
                return yaml.safe_load(source)
        except (yaml.YAMLError, FileNotFoundError) as e:
            raise InvalidConfigurationError(f"Invalid YAML configuration: {e}")
    
    def supports_format(self, format_type: ConfigFormat) -> bool:
        """Check if loader supports YAML format."""
        return format_type == ConfigFormat.YAML


class EnvironmentConfigLoader(IConfigLoader):
    """Environment variables configuration loader."""
    
    def __init__(self, prefix: str = "DT_"):
        self.prefix = prefix
    
    def load(self, source: str = "") -> Dict[str, Any]:
        """Load configuration from environment variables."""
        config = {}
        for key, value in os.environ.items():
            if key.startswith(self.prefix):
                # Remove prefix and convert to nested dict
                config_key = key[len(self.prefix):].lower()
                self._set_nested_value(config, config_key, self._parse_value(value))
        return config
    
    def _set_nested_value(self, config: Dict[str, Any], key: str, value: Any) -> None:
        """Set nested dictionary value from dot-separated key."""
        keys = key.split('_')
        current = config
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]
        current[keys[-1]] = value
    
    def _parse_value(self, value: str) -> Any:
        """Parse environment variable value to appropriate type."""
        # Try to parse as JSON first
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
        
        # Parse boolean values
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true'
        
        # Parse numeric values
        try:
            if '.' in value:
                return float(value)
            return int(value)
        except ValueError:
            pass
        
        # Return as string
        return value
    
    def supports_format(self, format_type: ConfigFormat) -> bool:
        """Check if loader supports environment format."""
        return format_type == ConfigFormat.ENV


class ConfigValidator:
    """Configuration validator."""
    
    def __init__(self):
        self.required_keys: Set[str] = {
            "database.host",
            "database.database",
            "auth.secret_key"
        }
    
    def validate(self, config: PlatformConfig) -> List[str]:
        """
        Validate platform configuration.
        
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        # Check required configuration values
        errors.extend(self._check_required_values(config))
        
        # Validate specific components
        errors.extend(self._validate_database_config(config.database))
        errors.extend(self._validate_auth_config(config.auth))
        errors.extend(self._validate_protocol_config(config.protocols))
        errors.extend(self._validate_security_config(config.security))
        
        return errors
    
    def _check_required_values(self, config: PlatformConfig) -> List[str]:
        """Check for required configuration values."""
        errors = []
        
        if not config.auth.secret_key:
            errors.append("auth.secret_key is required")
        
        if not config.database.password and config.environment == ConfigEnvironment.PRODUCTION:
            errors.append("database.password is required in production")
        
        return errors
    
    def _validate_database_config(self, db_config: DatabaseConfig) -> List[str]:
        """Validate database configuration."""
        errors = []
        
        if db_config.port < 1 or db_config.port > 65535:
            errors.append("database.port must be between 1 and 65535")
        
        if db_config.pool_size < 1:
            errors.append("database.pool_size must be greater than 0")
        
        return errors
    
    def _validate_auth_config(self, auth_config: AuthConfig) -> List[str]:
        """Validate authentication configuration."""
        errors = []
        
        if len(auth_config.secret_key) < 32:
            errors.append("auth.secret_key must be at least 32 characters")
        
        if auth_config.access_token_expire_minutes < 1:
            errors.append("auth.access_token_expire_minutes must be greater than 0")
        
        return errors
    
    def _validate_protocol_config(self, protocol_config: ProtocolConfig) -> List[str]:
        """Validate protocol configuration."""
        errors = []
        
        if not protocol_config.enabled_protocols:
            errors.append("protocols.enabled_protocols cannot be empty")
        
        return errors
    
    def _validate_security_config(self, security_config: SecurityConfig) -> List[str]:
        """Validate security configuration."""
        errors = []
        
        if security_config.ssl_enabled:
            if not security_config.ssl_cert_path:
                errors.append("security.ssl_cert_path is required when SSL is enabled")
            if not security_config.ssl_key_path:
                errors.append("security.ssl_key_path is required when SSL is enabled")
        
        return errors


class ConfigManager:
    """Central configuration manager for the platform."""
    
    def __init__(self):
        self.loaders: Dict[ConfigFormat, IConfigLoader] = {
            ConfigFormat.JSON: JsonConfigLoader(),
            ConfigFormat.YAML: YamlConfigLoader(),
            ConfigFormat.ENV: EnvironmentConfigLoader()
        }
        self.validator = ConfigValidator()
        self._config: Optional[PlatformConfig] = None
        self._config_sources: List[str] = []
    
    def add_loader(self, format_type: ConfigFormat, loader: IConfigLoader) -> None:
        """Add a custom configuration loader."""
        self.loaders[format_type] = loader
    
    def load_from_file(
        self, 
        file_path: Union[str, Path], 
        format_type: Optional[ConfigFormat] = None
    ) -> PlatformConfig:
        """
        Load configuration from file.
        
        Args:
            file_path: Path to configuration file
            format_type: Format type (auto-detected if None)
            
        Returns:
            Loaded platform configuration
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise MissingConfigurationError(f"Configuration file not found: {file_path}")
        
        # Auto-detect format if not specified
        if format_type is None:
            format_type = self._detect_format(file_path)
        
        # Load configuration
        loader = self.loaders.get(format_type)
        if not loader:
            raise InvalidConfigurationError(f"No loader available for format: {format_type}")
        
        config_data = loader.load(str(file_path))
        self._config_sources.append(str(file_path))
        
        return self._build_config(config_data)
    
    def load_from_dict(self, config_data: Dict[str, Any]) -> PlatformConfig:
        """
        Load configuration from dictionary.
        
        Args:
            config_data: Configuration dictionary
            
        Returns:
            Loaded platform configuration
        """
        self._config_sources.append("dict")
        return self._build_config(config_data)
    
    def load_from_environment(self, prefix: str = "DT_") -> PlatformConfig:
        """
        Load configuration from environment variables.
        
        Args:
            prefix: Environment variable prefix
            
        Returns:
            Loaded platform configuration
        """
        loader = EnvironmentConfigLoader(prefix)
        config_data = loader.load()
        self._config_sources.append("environment")
        
        return self._build_config(config_data)
    
    def merge_configs(self, *configs: PlatformConfig) -> PlatformConfig:
        """
        Merge multiple configurations (later configs override earlier ones).
        
        Args:
            configs: Configuration objects to merge
            
        Returns:
            Merged configuration
        """
        if not configs:
            raise InvalidConfigurationError("At least one configuration must be provided")
        
        # Start with the first config
        merged_dict = self._config_to_dict(configs[0])
        
        # Merge subsequent configs
        for config in configs[1:]:
            config_dict = self._config_to_dict(config)
            merged_dict = self._deep_merge(merged_dict, config_dict)
        
        return self._build_config(merged_dict)
    
    def get_config(self) -> PlatformConfig:
        """Get the current configuration."""
        if self._config is None:
            # Load default configuration from environment if available
            try:
                self._config = self.load_from_environment()
            except:
                # Use default configuration
                self._config = PlatformConfig()
        
        return self._config
    
    def validate_config(self, config: Optional[PlatformConfig] = None) -> None:
        """
        Validate configuration.
        
        Args:
            config: Configuration to validate (uses current if None)
            
        Raises:
            InvalidConfigurationError: If configuration is invalid
        """
        if config is None:
            config = self.get_config()
        
        errors = self.validator.validate(config)
        if errors:
            raise InvalidConfigurationError(f"Configuration validation failed: {'; '.join(errors)}")
    
    def reload_config(self) -> PlatformConfig:
        """
        Reload configuration from the same sources.
        
        Returns:
            Reloaded configuration
        """
        if not self._config_sources:
            raise ConfigurationError("No configuration sources to reload from")
        
        # For now, just return the current config
        # In a full implementation, this would re-read from sources
        return self.get_config()
    
    def _detect_format(self, file_path: Path) -> ConfigFormat:
        """Auto-detect configuration format from file extension."""
        suffix = file_path.suffix.lower()
        
        format_map = {
            '.json': ConfigFormat.JSON,
            '.yaml': ConfigFormat.YAML,
            '.yml': ConfigFormat.YAML,
            '.toml': ConfigFormat.TOML
        }
        
        format_type = format_map.get(suffix)
        if not format_type:
            raise InvalidConfigurationError(f"Unsupported configuration format: {suffix}")
        
        return format_type
    
    def _build_config(self, config_data: Dict[str, Any]) -> PlatformConfig:
        """Build PlatformConfig from dictionary data."""
        try:
            # Convert nested dictionaries to dataclass instances
            config = PlatformConfig()
            
            # Update fields from config_data
            self._update_dataclass_from_dict(config, config_data)
            
            # Store and validate
            self._config = config
            self.validate_config(config)
            
            return config
        
        except Exception as e:
            raise InvalidConfigurationError(f"Failed to build configuration: {e}")
    
    def _update_dataclass_from_dict(self, obj: Any, data: Dict[str, Any]) -> None:
        """Update dataclass instance from dictionary."""
        for key, value in data.items():
            if hasattr(obj, key):
                attr = getattr(obj, key)
                if hasattr(attr, '__dataclass_fields__'):
                    # Nested dataclass
                    if isinstance(value, dict):
                        self._update_dataclass_from_dict(attr, value)
                else:
                    # Simple field
                    setattr(obj, key, value)
    
    def _config_to_dict(self, config: PlatformConfig) -> Dict[str, Any]:
        """Convert PlatformConfig to dictionary."""
        # This is a simplified version - full implementation would use
        # proper dataclass serialization
        return {
            "environment": config.environment.value,
            "debug": config.debug,
            "version": config.version,
            "service_name": config.service_name,
            "timezone": config.timezone,
            "custom": config.custom
            # Add other fields as needed
        }
    
    def _deep_merge(self, dict1: Dict[str, Any], dict2: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries."""
        result = dict1.copy()
        
        for key, value in dict2.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        
        return result


# Global configuration manager instance
config_manager = ConfigManager()


def get_config() -> PlatformConfig:
    """Get the global platform configuration."""
    return config_manager.get_config()


def load_config_from_file(file_path: Union[str, Path]) -> PlatformConfig:
    """Load configuration from file and set as global config."""
    config = config_manager.load_from_file(file_path)
    config_manager._config = config
    return config


def load_config_from_env(prefix: str = "DT_") -> PlatformConfig:
    """Load configuration from environment variables and set as global config."""
    config = config_manager.load_from_environment(prefix)
    config_manager._config = config
    return config