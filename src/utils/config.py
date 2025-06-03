import os
from typing import Any, Dict, Optional


class SimpleConfig:
    """Simple configuration class without complex dependencies."""
    
    def __init__(self):
        self._config = self._load_default_config()
    
    def _load_default_config(self) -> Dict[str, Any]:
        """Load default configuration from environment variables."""
        return {
            'environment': os.getenv('DT_ENVIRONMENT', 'development'),
            'debug': os.getenv('DT_DEBUG', 'true').lower() == 'true',
            'version': '1.0.0',
            'service_name': 'digital-twin-platform',
            'logging': {
                'level': os.getenv('DT_LOG_LEVEL', 'INFO'),
                'file_path': os.getenv('DT_LOG_FILE', 'logs/platform.log')
            },
            'api': {
                'host': os.getenv('DT_API_HOST', '0.0.0.0'),
                'port': int(os.getenv('DT_API_PORT', '8000')),
                'cors_origins': ['*'],
                'allowed_hosts': ['*']
            },
            'auth': {
                'secret_key': os.getenv('DT_AUTH_SECRET', 'dev-secret-key-change-in-production'),
                'algorithm': 'HS256',
                'access_token_expire_minutes': 60,
                'refresh_token_expire_days': 7
            },
            'database': {
                'host': os.getenv('DT_DB_HOST', 'localhost'),
                'port': int(os.getenv('DT_DB_PORT', '5432')),
                'database': os.getenv('DT_DB_NAME', 'digital_twin_platform'),
                'username': os.getenv('DT_DB_USER', 'dt_user'),
                'password': os.getenv('DT_DB_PASSWORD', ''),
            },
            'redis': {
                'host': os.getenv('DT_REDIS_HOST', 'localhost'),
                'port': int(os.getenv('DT_REDIS_PORT', '6379')),
                'database': int(os.getenv('DT_REDIS_DB', '0')),
                'password': os.getenv('DT_REDIS_PASSWORD')
            },
            'jwt': {
                'secret_key': os.getenv('DT_AUTH_SECRET', 'dev-secret-key-change-in-production'),
                'algorithm': 'HS256'
            }
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value using dot notation."""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def __getitem__(self, key: str) -> Any:
        return self.get(key)
    
    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None


# Global configuration instance
_config = SimpleConfig()


def get_config() -> SimpleConfig:
    """Get the global configuration instance."""
    return _config


# Legacy compatibility - some modules might expect these
class PlatformConfig:
    """Legacy compatibility class."""
    def __init__(self, **kwargs):
        self.data = kwargs or _config._config
    
    def get(self, key: str, default: Any = None) -> Any:
        return _config.get(key, default)


def load_config_from_file(file_path: str) -> SimpleConfig:
    """Load configuration from file (stub implementation)."""
    return _config


def load_config_from_env(prefix: str = 'DT_') -> SimpleConfig:
    """Load configuration from environment (already implemented)."""
    return _config