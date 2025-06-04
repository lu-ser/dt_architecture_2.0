import os
from typing import Any, Dict, Optional

class SimpleConfig:

    def __init__(self):
        self._config = self._load_default_config()

    def _load_default_config(self) -> Dict[str, Any]:
        return {'environment': os.getenv('DT_ENVIRONMENT', 'development'), 'debug': os.getenv('DT_DEBUG', 'true').lower() == 'true', 'version': '1.0.0', 'service_name': 'digital-twin-platform', 'logging': {'level': os.getenv('DT_LOG_LEVEL', 'INFO'), 'file_path': os.getenv('DT_LOG_FILE', 'logs/platform.log')}, 'api': {'host': os.getenv('DT_API_HOST', '0.0.0.0'), 'port': int(os.getenv('DT_API_PORT', '8000')), 'cors_origins': ['*'], 'allowed_hosts': ['*']}, 'auth': {'secret_key': os.getenv('DT_AUTH_SECRET', 'dev-secret-key-change-in-production'), 'algorithm': 'HS256', 'access_token_expire_minutes': 60, 'refresh_token_expire_days': 7}, 'mongodb': {'connection_string': os.getenv('DT_MONGO_URI', 'mongodb://localhost:27017'), 'database_prefix': os.getenv('DT_MONGO_DB_PREFIX', 'dt_platform'), 'global_database': os.getenv('DT_MONGO_GLOBAL_DB', 'dt_platform_global'), 'pool_size': int(os.getenv('DT_MONGO_POOL_SIZE', '10')), 'max_pool_size': int(os.getenv('DT_MONGO_MAX_POOL', '50')), 'timeout_ms': int(os.getenv('DT_MONGO_TIMEOUT', '5000')), 'retry_writes': os.getenv('DT_MONGO_RETRY_WRITES', 'true').lower() == 'true', 'auth_source': os.getenv('DT_MONGO_AUTH_SOURCE', 'admin'), 'username': os.getenv('DT_MONGO_USER'), 'password': os.getenv('DT_MONGO_PASSWORD')}, 'redis': {'host': os.getenv('DT_REDIS_HOST', 'localhost'), 'port': int(os.getenv('DT_REDIS_PORT', '6379')), 'database': int(os.getenv('DT_REDIS_DB', '0')), 'password': os.getenv('DT_REDIS_PASSWORD'), 'max_connections': int(os.getenv('DT_REDIS_MAX_CONN', '20')), 'connection_timeout': int(os.getenv('DT_REDIS_TIMEOUT', '5')), 'decode_responses': True, 'retry_on_timeout': True, 'health_check_interval': 30}, 'storage': {'primary_type': os.getenv('DT_STORAGE_PRIMARY', 'mongodb'), 'cache_type': os.getenv('DT_STORAGE_CACHE', 'redis'), 'separate_dbs_per_twin': os.getenv('DT_SEPARATE_DBS', 'true').lower() == 'true', 'auto_migration': os.getenv('DT_AUTO_MIGRATION', 'false').lower() == 'true'}, 'database': {'host': os.getenv('DT_DB_HOST', 'localhost'), 'port': int(os.getenv('DT_DB_PORT', '5432')), 'database': os.getenv('DT_DB_NAME', 'digital_twin_platform'), 'username': os.getenv('DT_DB_USER', 'dt_user'), 'password': os.getenv('DT_DB_PASSWORD', '')}, 'jwt': {'secret_key': os.getenv('DT_AUTH_SECRET', 'dev-secret-key-change-in-production'), 'algorithm': 'HS256'}}

    def get(self, key: str, default: Any=None) -> Any:
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
_config = SimpleConfig()

def get_config() -> SimpleConfig:
    return _config

class PlatformConfig:

    def __init__(self, **kwargs):
        self.data = kwargs or _config._config

    def get(self, key: str, default: Any=None) -> Any:
        return _config.get(key, default)

def load_config_from_file(file_path: str) -> SimpleConfig:
    return _config

def load_config_from_env(prefix: str='DT_') -> SimpleConfig:
    return _config