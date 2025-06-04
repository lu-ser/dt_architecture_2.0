import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Union
from uuid import UUID
from redis import asyncio as aioredis
from redis.asyncio import *

from src.utils.exceptions import StorageError, StorageConnectionError
from src.utils.config import get_config

logger = logging.getLogger(__name__)

class RedisCache:
    """Redis-based caching system for Digital Twin Platform."""
    
    def __init__(self, key_prefix: str = "dt_platform"):
        self.config = get_config()
        self.key_prefix = key_prefix
        self._redis: Optional[aioredis.Redis] = None
        self._connected = False
        
        # Cache configuration
        self.default_ttl = 300  # 5 minutes
        self.registry_ttl = 600  # 10 minutes for registry cache
        self.session_ttl = 3600  # 1 hour for sessions
        
        logger.info(f"Redis cache initialized with prefix: {key_prefix}")
    
    async def connect(self) -> None:
        """Establish connection to Redis."""
        if self._connected:
            return
        
        try:
            redis_config = {
                'host': self.config.get('redis.host', 'localhost'),
                'port': self.config.get('redis.port', 6379),
                'db': self.config.get('redis.database', 0),
                'password': self.config.get('redis.password'),
                'socket_timeout': self.config.get('redis.connection_timeout', 5),
                'socket_connect_timeout': 5,
                'retry_on_timeout': self.config.get('redis.retry_on_timeout', True),
                'decode_responses': True,
                'max_connections': self.config.get('redis.max_connections', 20)
            }
            
            # Remove None values
            redis_config = {k: v for k, v in redis_config.items() if v is not None}
            
            # Create Redis connection
            self._redis = aioredis.from_url(
                f"redis://{redis_config['host']}:{redis_config['port']}/{redis_config['db']}",
                **{k: v for k, v in redis_config.items() if k not in ['host', 'port', 'db']}
            )
            
            # Test connection
            await self._redis.ping()
            
            self._connected = True
            logger.info("Connected to Redis cache")
            
        except (ConnectionError) as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise StorageConnectionError(f"Redis connection failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error connecting to Redis: {e}")
            raise StorageError(f"Redis connection error: {e}")
    
    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._connected = False
            logger.info("Disconnected from Redis")
    
    def _make_key(self, key: str, namespace: str = "default") -> str:
        """Create a namespaced Redis key."""
        return f"{self.key_prefix}:{namespace}:{key}"
    
    async def get(self, key: str, namespace: str = "default") -> Optional[Any]:
        """Get value from cache."""
        if not self._connected:
            await self.connect()
        
        try:
            cache_key = self._make_key(key, namespace)
            value = await self._redis.get(cache_key)
            
            if value is None:
                return None
            
            # Try to deserialize JSON
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
                
        except Exception as e:
            logger.warning(f"Failed to get cache key {key}: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None, namespace: str = "default") -> bool:
        """Set value in cache with optional TTL."""
        if not self._connected:
            await self.connect()
        
        try:
            cache_key = self._make_key(key, namespace)
            
            # Serialize value
            if isinstance(value, (dict, list)):
                serialized_value = json.dumps(value, default=self._json_serializer)
            else:
                serialized_value = str(value)
            
            # Set with TTL
            ttl = ttl or self.default_ttl
            result = await self._redis.setex(cache_key, ttl, serialized_value)
            
            return result
            
        except Exception as e:
            logger.warning(f"Failed to set cache key {key}: {e}")
            return False
    
    async def delete(self, key: str, namespace: str = "default") -> bool:
        """Delete value from cache."""
        if not self._connected:
            await self.connect()
        
        try:
            cache_key = self._make_key(key, namespace)
            result = await self._redis.delete(cache_key)
            return result > 0
            
        except Exception as e:
            logger.warning(f"Failed to delete cache key {key}: {e}")
            return False
    
    async def exists(self, key: str, namespace: str = "default") -> bool:
        """Check if key exists in cache."""
        if not self._connected:
            await self.connect()
        
        try:
            cache_key = self._make_key(key, namespace)
            result = await self._redis.exists(cache_key)
            return result > 0
            
        except Exception as e:
            logger.warning(f"Failed to check existence of cache key {key}: {e}")
            return False
    
    async def expire(self, key: str, ttl: int, namespace: str = "default") -> bool:
        """Set expiration time for a key."""
        if not self._connected:
            await self.connect()
        
        try:
            cache_key = self._make_key(key, namespace)
            result = await self._redis.expire(cache_key, ttl)
            return result
            
        except Exception as e:
            logger.warning(f"Failed to set expiration for cache key {key}: {e}")
            return False
    
    async def clear_namespace(self, namespace: str) -> int:
        """Clear all keys in a namespace."""
        if not self._connected:
            await self.connect()
        
        try:
            pattern = self._make_key("*", namespace)
            keys = await self._redis.keys(pattern)
            
            if keys:
                result = await self._redis.delete(*keys)
                logger.info(f"Cleared {result} keys from namespace {namespace}")
                return result
            
            return 0
            
        except Exception as e:
            logger.warning(f"Failed to clear namespace {namespace}: {e}")
            return 0
    
    async def health_check(self) -> bool:
        """Check Redis connection health."""
        try:
            if not self._connected:
                return False
            
            await self._redis.ping()
            return True
            
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False
    
    def _json_serializer(self, obj: Any) -> str:
        """Custom JSON serializer for special types."""
        if isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, datetime):
            return obj.isoformat()
        elif hasattr(obj, 'value'):  # Enum
            return obj.value
        
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class RegistryCache:
    """Specialized cache for registry operations."""
    
    def __init__(self, redis_cache: RedisCache):
        self.cache = redis_cache
        self.namespace = "registry"
    
    async def cache_entity(self, entity_id: UUID, entity_data: Dict[str, Any], entity_type: str) -> bool:
        """Cache entity data."""
        key = f"{entity_type}:{entity_id}"
        return await self.cache.set(key, entity_data, ttl=self.cache.registry_ttl, namespace=self.namespace)
    
    async def get_entity(self, entity_id: UUID, entity_type: str) -> Optional[Dict[str, Any]]:
        """Get cached entity data."""
        key = f"{entity_type}:{entity_id}"
        return await self.cache.get(key, namespace=self.namespace)
    
    async def invalidate_entity(self, entity_id: UUID, entity_type: str) -> bool:
        """Remove entity from cache."""
        key = f"{entity_type}:{entity_id}"
        return await self.cache.delete(key, namespace=self.namespace)
    
    async def cache_query_result(self, query_hash: str, results: List[Dict[str, Any]], ttl: int = 300) -> bool:
        """Cache query results."""
        key = f"query:{query_hash}"
        return await self.cache.set(key, results, ttl=ttl, namespace=self.namespace)
    
    async def get_query_result(self, query_hash: str) -> Optional[List[Dict[str, Any]]]:
        """Get cached query results."""
        key = f"query:{query_hash}"
        return await self.cache.get(key, namespace=self.namespace)


class SessionCache:
    """Specialized cache for user sessions."""
    
    def __init__(self, redis_cache: RedisCache):
        self.cache = redis_cache
        self.namespace = "sessions"
    
    async def store_session(self, session_id: str, session_data: Dict[str, Any]) -> bool:
        """Store session data."""
        return await self.cache.set(session_id, session_data, ttl=self.cache.session_ttl, namespace=self.namespace)
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data."""
        return await self.cache.get(session_id, namespace=self.namespace)
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete session."""
        return await self.cache.delete(session_id, namespace=self.namespace)
    
    async def extend_session(self, session_id: str, ttl: Optional[int] = None) -> bool:
        """Extend session TTL."""
        ttl = ttl or self.cache.session_ttl
        return await self.cache.expire(session_id, ttl, namespace=self.namespace)


class RateLimitCache:
    """Rate limiting using Redis."""
    
    def __init__(self, redis_cache: RedisCache):
        self.cache = redis_cache
        self.namespace = "rate_limit"
    
    async def check_rate_limit(self, identifier: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """
        Check if identifier is within rate limit.
        Returns (is_allowed, remaining_requests).
        """
        if not self.cache._connected:
            await self.cache.connect()
        
        try:
            key = self.cache._make_key(identifier, self.namespace)
            
            # Use Redis pipeline for atomic operations
            pipe = self.cache._redis.pipeline()
            
            # Get current count
            pipe.get(key)
            # Increment counter
            pipe.incr(key)
            # Set expiration if key is new
            pipe.expire(key, window_seconds)
            
            results = await pipe.execute()
            
            current_count = int(results[1])  # Result of incr
            
            if current_count <= limit:
                remaining = limit - current_count
                return True, remaining
            else:
                return False, 0
                
        except Exception as e:
            logger.warning(f"Rate limit check failed for {identifier}: {e}")
            # On error, allow the request (fail open)
            return True, limit


# Global cache instances
_redis_cache: Optional[RedisCache] = None
_registry_cache: Optional[RegistryCache] = None
_session_cache: Optional[SessionCache] = None
_rate_limit_cache: Optional[RateLimitCache] = None

async def get_redis_cache() -> RedisCache:
    """Get global Redis cache instance."""
    global _redis_cache
    if _redis_cache is None:
        _redis_cache = RedisCache()
        await _redis_cache.connect()
    return _redis_cache

async def get_registry_cache() -> RegistryCache:
    """Get registry cache instance."""
    global _registry_cache
    if _registry_cache is None:
        redis_cache = await get_redis_cache()
        _registry_cache = RegistryCache(redis_cache)
    return _registry_cache

async def get_session_cache() -> SessionCache:
    """Get session cache instance."""
    global _session_cache
    if _session_cache is None:
        redis_cache = await get_redis_cache()
        _session_cache = SessionCache(redis_cache)
    return _session_cache

async def get_rate_limit_cache() -> RateLimitCache:
    """Get rate limit cache instance."""
    global _rate_limit_cache
    if _rate_limit_cache is None:
        redis_cache = await get_redis_cache()
        _rate_limit_cache = RateLimitCache(redis_cache)
    return _rate_limit_cache