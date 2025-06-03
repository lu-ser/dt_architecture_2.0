# src/utils/config_helper.py
"""
Configuration Helper - Provides backward compatibility and nested access
"""
import logging
from typing import Any, Dict, Optional, Union
from src.utils.config import PlatformConfig, get_config as _get_config

logger = logging.getLogger(__name__)

class ConfigProxy:
    """Proxy class that provides dictionary-like access to PlatformConfig."""
    
    def __init__(self, config: PlatformConfig):
        self._config = config
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value with dot notation support."""
        return self.get_nested(key, default)
    
    def get_nested(self, key: str, default: Any = None) -> Any:
        """Get a nested configuration value using dot notation."""
        try:
            keys = key.split('.')
            value = self._config
            
            for k in keys:
                if hasattr(value, k):
                    value = getattr(value, k)
                else:
                    return default
            
            return value
        except Exception as e:
            logger.debug(f"Failed to get config key '{key}': {e}")
            return default
    
    def __getitem__(self, key: str) -> Any:
        """Support bracket notation."""
        value = self.get_nested(key)
        if value is None:
            raise KeyError(f"Configuration key '{key}' not found")
        return value
    
    def __contains__(self, key: str) -> bool:
        """Support 'in' operator."""
        return self.get_nested(key) is not None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'environment': self._config.environment.value,
            'debug': self._config.debug,
            'version': self._config.version,
            'service_name': self._config.service_name,
            'timezone': self._config.timezone,
            'database': {
                'host': self._config.database.host,
                'port': self._config.database.port,
                'database': self._config.database.database,
                'username': self._config.database.username,
                'password': self._config.database.password,
                'pool_size': self._config.database.pool_size,
                'max_overflow': self._config.database.max_overflow,
                'echo': self._config.database.echo,
                'ssl_mode': self._config.database.ssl_mode,
                'connection_timeout': self._config.database.connection_timeout,
                'custom_params': self._config.database.custom_params
            },
            'redis': {
                'host': self._config.redis.host,
                'port': self._config.redis.port,
                'database': self._config.redis.database,
                'password': self._config.redis.password,
                'max_connections': self._config.redis.max_connections,
                'connection_timeout': self._config.redis.connection_timeout,
                'socket_timeout': self._config.redis.socket_timeout,
                'retry_on_timeout': self._config.redis.retry_on_timeout,
                'health_check_interval': self._config.redis.health_check_interval
            },
            'auth': {
                'provider': self._config.auth.provider,
                'secret_key': self._config.auth.secret_key,
                'algorithm': self._config.auth.algorithm,
                'access_token_expire_minutes': self._config.auth.access_token_expire_minutes,
                'refresh_token_expire_days': self._config.auth.refresh_token_expire_days,
                'issuer': self._config.auth.issuer,
                'audience': self._config.auth.audience,
                'oauth_providers': self._config.auth.oauth_providers
            },
            'protocols': {
                'enabled_protocols': self._config.protocols.enabled_protocols,
                'http_config': self._config.protocols.http_config,
                'mqtt_config': self._config.protocols.mqtt_config,
                'custom_protocols': self._config.protocols.custom_protocols
            },
            'storage': {
                'primary_storage': self._config.storage.primary_storage,
                'cache_storage': self._config.storage.cache_storage,
                'file_storage_path': self._config.storage.file_storage_path,
                'backup_storage_path': self._config.storage.backup_storage_path,
                'retention_days': self._config.storage.retention_days,
                'compression_enabled': self._config.storage.compression_enabled,
                'encryption_enabled': self._config.storage.encryption_enabled,
                'storage_adapters': self._config.storage.storage_adapters
            },
            'container': {
                'container_runtime': self._config.container.container_runtime,
                'registry_url': self._config.container.registry_url,
                'base_image': self._config.container.base_image,
                'resource_limits': self._config.container.resource_limits,
                'kubernetes_namespace': self._config.container.kubernetes_namespace,
                'auto_scaling_enabled': self._config.container.auto_scaling_enabled,
                'health_check_enabled': self._config.container.health_check_enabled
            },
            'logging': {
                'level': self._config.logging.level,
                'format': self._config.logging.format,
                'handlers': self._config.logging.handlers,
                'file_path': self._config.logging.file_path,
                'max_file_size': self._config.logging.max_file_size,
                'backup_count': self._config.logging.backup_count,
                'json_logging': self._config.logging.json_logging,
                'structured_logging': self._config.logging.structured_logging
            },
            'monitoring': {
                'enabled': self._config.monitoring.enabled,
                'metrics_port': self._config.monitoring.metrics_port,
                'health_check_port': self._config.monitoring.health_check_port,
                'prometheus_enabled': self._config.monitoring.prometheus_enabled,
                'grafana_enabled': self._config.monitoring.grafana_enabled,
                'alert_manager_url': self._config.monitoring.alert_manager_url,
                'custom_metrics': self._config.monitoring.custom_metrics
            },
            'security': {
                'encryption_key': self._config.security.encryption_key,
                'api_rate_limiting': self._config.security.api_rate_limiting,
                'rate_limit_requests': self._config.security.rate_limit_requests,
                'rate_limit_window': self._config.security.rate_limit_window,
                'cors_enabled': self._config.security.cors_enabled,
                'cors_origins': self._config.security.cors_origins,
                'ssl_enabled': self._config.security.ssl_enabled,
                'ssl_cert_path': self._config.security.ssl_cert_path,
                'ssl_key_path': self._config.security.ssl_key_path
            },
            'api': {
                'host': self._config.protocols.http_config.get('host', '0.0.0.0'),
                'port': self._config.protocols.http_config.get('port', 8000),
                'cors_origins': self._config.security.cors_origins,
                'allowed_hosts': ['*']  # Default fallback
            },
            'jwt': {
                'secret_key': self._config.auth.secret_key,
                'algorithm': self._config.auth.algorithm,
                'access_token_expire_minutes': self._config.auth.access_token_expire_minutes,
                'refresh_token_expire_days': self._config.auth.refresh_token_expire_days
            },
            'custom': self._config.custom
        }

# Global config proxy instance
_config_proxy: Optional[ConfigProxy] = None

def get_config() -> ConfigProxy:
    """Get the configuration proxy instance."""
    global _config_proxy
    if _config_proxy is None:
        platform_config = _get_config()
        _config_proxy = ConfigProxy(platform_config)
    return _config_proxy

def refresh_config() -> ConfigProxy:
    """Refresh the configuration proxy."""
    global _config_proxy
    platform_config = _get_config()
    _config_proxy = ConfigProxy(platform_config)
    return _config_proxy