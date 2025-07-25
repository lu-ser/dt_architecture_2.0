#!/usr/bin/env python3
"""
Digital Twin Platform - Main Application Entry Point

This is the main startup script for the Digital Twin Platform.
It initializes all layers in the correct order and starts the API server.
Enhanced with MongoDB + Redis storage support.
"""

import asyncio
import logging
import signal
import sys
import os
from pathlib import Path
from typing import Optional
import uvicorn
from src.layers.digital_twin.association_manager import get_association_manager

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


class SimpleConfig:
    """Simple configuration class without circular imports."""
    
    def __init__(self):
        self.data = {
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
            # NEW: MongoDB Configuration
            'mongodb': {
                'connection_string': os.getenv('DT_MONGO_URI', 'mongodb://localhost:27017'),
                'database_prefix': os.getenv('DT_MONGO_DB_PREFIX', 'dt_platform'),
                'global_database': os.getenv('DT_MONGO_GLOBAL_DB', 'dt_platform_global'),
                'pool_size': int(os.getenv('DT_MONGO_POOL_SIZE', '10')),
                'max_pool_size': int(os.getenv('DT_MONGO_MAX_POOL', '50')),
                'timeout_ms': int(os.getenv('DT_MONGO_TIMEOUT', '5000')),
                'username': os.getenv('DT_MONGO_USER'),
                'password': os.getenv('DT_MONGO_PASSWORD')
            },
            # NEW: Redis Configuration
            'redis': {
                'host': os.getenv('DT_REDIS_HOST', 'localhost'),
                'port': int(os.getenv('DT_REDIS_PORT', '6379')),
                'database': int(os.getenv('DT_REDIS_DB', '0')),
                'password': os.getenv('DT_REDIS_PASSWORD'),
                'max_connections': int(os.getenv('DT_REDIS_MAX_CONN', '20')),
                'connection_timeout': int(os.getenv('DT_REDIS_TIMEOUT', '5'))
            },
            # NEW: Storage Configuration
            'storage': {
                'primary_type': os.getenv('DT_STORAGE_PRIMARY', 'mongodb'),
                'cache_type': os.getenv('DT_STORAGE_CACHE', 'redis'),
                'separate_dbs_per_twin': os.getenv('DT_SEPARATE_DBS', 'true').lower() == 'true'
            },
            # Legacy database config (keep for compatibility)
            'database': {
                'host': os.getenv('DT_DB_HOST', 'localhost'),
                'port': int(os.getenv('DT_DB_PORT', '5432')),
                'database': os.getenv('DT_DB_NAME', 'digital_twin_platform'),
                'username': os.getenv('DT_DB_USER', 'dt_user'),
                'password': os.getenv('DT_DB_PASSWORD', ''),
            },
            # JWT config (for backwards compatibility)
            'jwt': {
                'secret_key': os.getenv('DT_AUTH_SECRET', 'dev-secret-key-change-in-production')
            },
            'protocols': {
                'http_defaults': {
                    'timeout': int(os.getenv('DT_PROTOCOL_HTTP_TIMEOUT', '30')),
                    'polling_interval': int(os.getenv('DT_PROTOCOL_HTTP_POLL', '60')),
                    'max_concurrent_requests': int(os.getenv('DT_PROTOCOL_HTTP_CONCURRENT', '10'))
                },
                'mqtt_defaults': {
                    'keepalive': int(os.getenv('DT_PROTOCOL_MQTT_KEEPALIVE', '60')),
                    'qos': int(os.getenv('DT_PROTOCOL_MQTT_QOS', '1')),
                    'retain': os.getenv('DT_PROTOCOL_MQTT_RETAIN', 'false').lower() == 'true',
                    'reconnect_attempts': int(os.getenv('DT_PROTOCOL_MQTT_RECONNECT', '5'))
                },
                'max_adapters': int(os.getenv('DT_PROTOCOL_MAX_ADAPTERS', '10')),
                'max_devices_per_adapter': int(os.getenv('DT_PROTOCOL_MAX_DEVICES', '100')),
                'message_queue_size': int(os.getenv('DT_PROTOCOL_QUEUE_SIZE', '1000'))
            },
            'device_storage': {
                'persistent': os.getenv('DT_DEVICE_STORAGE_PERSIST', 'true').lower() == 'true',
                'backend': os.getenv('DT_DEVICE_STORAGE_BACKEND', 'mongodb')  # mongodb, redis, memory
            }
        }
    def get(self, key, default=None):
        """Get configuration value using dot notation."""
        keys = key.split('.')
        value = self.data
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def __getitem__(self, key):
        return self.get(key)
    
    def __contains__(self, key):
        return self.get(key) is not None


class DigitalTwinPlatform:
    """Main platform class that coordinates all layers and components."""
    
    def __init__(self, config_file: Optional[Path] = None):
        self.config_file = config_file
        self.config = SimpleConfig()
        self.virtualization_orchestrator = None
        self.service_orchestrator = None
        self.digital_twin_orchestrator = None
        self.application_layer = None
        self.api_gateway = None
        self.running = False
        self._shutdown_event = asyncio.Event()
        
        # NEW: Storage status
        self._storage_initialized = False
        self._storage_status = {}

        self.device_service = None
        self.protocol_registry = None
        
    async def initialize(self) -> None:
        """Initialize the platform and all its components."""
        try:
            logger.info("Starting Digital Twin Platform initialization...")
            
            # 1. Setup enhanced logging
            self._setup_logging()
            
            # 2. Patch configuration for modules
            self._patch_module_configs()
            
            # NEW: 3. Initialize storage infrastructure first
            await self._initialize_storage()
            
            # 4. Initialize platform layers in dependency order
            await self._initialize_layers()
            
            # 5. Initialize API Gateway
            await self._initialize_api_gateway()
            await self._initialize_association_system()
            
            logger.info("Digital Twin Platform initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Digital Twin Platform: {e}")
            logger.exception("Full traceback:")
            raise RuntimeError(f"Platform initialization failed: {e}")
    
    async def _initialize_storage(self) -> None:
        """Initialize storage infrastructure."""
        try:
            logger.info("Initializing storage infrastructure...")
            
            # Import and initialize storage
            from src.storage import initialize_storage
            self._storage_status = await initialize_storage()
            self._storage_initialized = True
            
            # Log storage status
            primary = self._storage_status.get('primary_storage', 'unknown')
            cache = self._storage_status.get('cache_storage', 'none')
            separate_dbs = self._storage_status.get('separate_dbs_per_twin', False)
            
            logger.info(f"Storage initialized: {primary} + {cache}")
            if separate_dbs:
                logger.info("Using separate databases per Digital Twin (migration ready)")
            
            # Check connections
            connections = self._storage_status.get('connections', {})
            for conn_name, conn_info in connections.items():
                if isinstance(conn_info, dict) and conn_info.get('connected'):
                    logger.info(f"  ✓ {conn_name} connected")
                elif 'error' in str(conn_info):
                    logger.warning(f"  ✗ {conn_name} failed: {conn_info}")
            
        except ImportError as e:
            logger.warning(f"Storage modules not available: {e}")
            logger.info("Falling back to in-memory storage")
            self._storage_status = {
                'primary_storage': 'memory',
                'cache_storage': 'none',
                'fallback_reason': str(e)
            }
        except Exception as e:
            logger.error(f"Storage initialization failed: {e}")
            logger.info("Falling back to in-memory storage")
            self._storage_status = {
                'primary_storage': 'memory',
                'cache_storage': 'none',
                'fallback_reason': str(e)
            }
    
    async def start(self) -> None:
        """Start the platform and all its services."""
        if self.running:
            logger.warning("Platform is already running")
            return
            
        try:
            logger.info("Starting Digital Twin Platform services...")
            
            # Start all layer orchestrators
            await self._start_layer_orchestrators()
            
            # Start application services
            await self._start_application_services()
            
            self.running = True
            logger.info("Digital Twin Platform is now running and ready to accept requests")
            
            # Log platform overview
            await self._log_platform_status()
            
        except Exception as e:
            logger.error(f"Failed to start Digital Twin Platform: {e}")
            await self.stop()
            raise
    
    async def stop(self) -> None:
        """Stop the platform gracefully."""
        if not self.running:
            return
            
        logger.info("Stopping Digital Twin Platform...")
        if self.protocol_registry:
            try:
                logger.info("Stopping device protocol system...")
                # Disconnect all adapters
                for adapter_id in list(self.protocol_registry.adapters.keys()):
                    await self.protocol_registry.remove_adapter(adapter_id)
                logger.info("Device protocol system stopped")
            except Exception as e:
                logger.error(f"Error stopping device protocols: {e}")
        try:
            # Stop layers in reverse order
            if self.digital_twin_orchestrator:
                await self.digital_twin_orchestrator.stop()
                
            if self.service_orchestrator:
                await self.service_orchestrator.stop()
                
            if self.virtualization_orchestrator:
                await self.virtualization_orchestrator.stop()
                
            if self.application_layer:
                await self.application_layer.stop()
                
            self.running = False
            self._shutdown_event.set()
            
            logger.info("Digital Twin Platform stopped successfully")
            
        except Exception as e:
            logger.error(f"Error during platform shutdown: {e}")
    
    async def run_forever(self) -> None:
        """Run the platform until shutdown signal is received."""
        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()
        
        try:
            await self.initialize()
            await self.start()
            
            # Wait for shutdown signal
            await self._shutdown_event.wait()
            
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        finally:
            await self.stop()
    
    async def start_api_server(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        """Start the FastAPI server."""
        try:
            logger.info(f"Starting API server on {host}:{port}")
            
            # Get FastAPI app
            from src.layers.application.api import get_app
            app = get_app()
            
            # Configure uvicorn
            config = uvicorn.Config(
                app=app,
                host=host,
                port=port,
                log_config=None,  # We handle logging ourselves
                access_log=True,
                loop="asyncio"
            )
            
            server = uvicorn.Server(config)
            
            # Start server
            await server.serve()
            
        except Exception as e:
            logger.error(f"Failed to start API server: {e}")
            raise
    
    def _setup_logging(self) -> None:
        """Setup enhanced logging with platform configuration."""
        log_level = self.config.get('logging.level')
        log_file = self.config.get('logging.file_path')
        
        # Create logs directory if it doesn't exist
        if log_file:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        
        # Setup file handler if specified
        if log_file:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(getattr(logging, log_level))
            file_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            )
            logging.getLogger().addHandler(file_handler)
        
        # Set logging level
        logging.getLogger().setLevel(getattr(logging, log_level))
        
        logger.info(f"Logging configured - Level: {log_level}, File: {log_file or 'Console only'}")
    
    def _patch_module_configs(self) -> None:
        """Patch module configurations to work with our config."""
        # Patch get_config functions directly without imports
        import sys
        
        # Create a mock config module
        class MockConfigModule:
            def get_config(self):
                return self.config
            
            def __init__(self, config):
                self.config = config
        
        # If the config module exists, patch it
        if 'src.utils.config' in sys.modules:
            sys.modules['src.utils.config'].get_config = lambda: self.config
        
        logger.info("Configuration patched for all modules")
    
    async def _initialize_layers(self) -> None:
        """Initialize all platform layers in the correct order."""
        logger.info("Initializing platform layers...")
        
        try:
            # 1. Initialize Virtualization Layer (handles Digital Replicas)
            logger.info("Initializing Virtualization Layer...")
            from src.layers.virtualization import initialize_virtualization_layer
            self.virtualization_orchestrator = await initialize_virtualization_layer(Path("src/templates"))
            
            # 2. Initialize Service Layer (provides capabilities)
            logger.info("Initializing Service Layer...")
            from src.layers.service import initialize_service_layer
            self.service_orchestrator = await initialize_service_layer()
            
            # 3. Initialize Digital Twin Layer (main coordination layer)
            logger.info("Initializing Digital Twin Layer...")
            from src.layers.digital_twin import initialize_digital_twin_layer
            self.digital_twin_orchestrator = await initialize_digital_twin_layer()
            
            # 4. Initialize Application Layer (API and auth)
            logger.info("Initializing Application Layer...")
            from src.layers.application import initialize_application_layer
            self.application_layer = await initialize_application_layer()
            
            logger.info("All platform layers initialized")
            logger.info("Initializing Device Protocol System...")
            from src.core.services.device_configuration_service import get_device_configuration_service
            from src.core.protocols.protocol_registry import get_protocol_registry
            
            self.protocol_registry = await get_protocol_registry()
            self.device_service = await get_device_configuration_service()
            logger.info("Device Protocol System initialized")
            
            logger.info("All platform layers initialized")
        except Exception as e:
            logger.error(f"Failed to initialize layers: {e}")
            raise
    
    async def _initialize_api_gateway(self) -> None:
        """Initialize the API Gateway."""
        logger.info("Initializing API Gateway...")
        try:
            from src.layers.application.api_gateway import initialize_api_gateway
            self.api_gateway = await initialize_api_gateway()
            logger.info("API Gateway initialized")
        except Exception as e:
            logger.error(f"Failed to initialize API Gateway: {e}")
            raise
    
    
    async def _initialize_association_system(self) -> None:
        """Initialize persistent association system for twin-replica mapping."""
        try:
            logger.info("Initializing persistent association system...")
            
            # Initialize Association Manager
            association_manager = await get_association_manager()
            logger.info("✅ Association Manager initialized")
            
            # Get registries from orchestrators
            if hasattr(self, 'digital_twin_orchestrator') and self.digital_twin_orchestrator:
                dt_registry = self.digital_twin_orchestrator.registry
                if hasattr(dt_registry, 'initialize_associations'):
                    await dt_registry.initialize_associations()
                    logger.info("✅ DT Registry associations initialized")
            else:
                logger.warning("Digital Twin orchestrator not available for association sync")
                return
                
            if hasattr(self, 'virtualization_orchestrator') and self.virtualization_orchestrator:
                dr_registry = self.virtualization_orchestrator.registry
            else:
                logger.warning("Virtualization orchestrator not available for association sync")
                return
            
            # Sync registries with persistent storage
            await association_manager.sync_with_registries(dt_registry, dr_registry)
            
            # Check if we need to restore associations from replica metadata
            stats = await association_manager.get_statistics()
            if stats['total_associations'] == 0:
                logger.info("🔧 No associations found, attempting restore from replica metadata...")
                await self._restore_associations_from_metadata(association_manager, dr_registry)
            else:
                logger.info(f"✅ Found {stats['total_associations']} existing associations")
            
            # Cleanup orphaned associations
            cleaned = await association_manager.cleanup_orphaned_associations(dt_registry, dr_registry)
            if cleaned > 0:
                logger.info(f"🧹 Cleaned {cleaned} orphaned associations")
            
            # Final sync after cleanup
            await association_manager.sync_with_registries(dt_registry, dr_registry)
            
            logger.info("✅ Persistent association system initialized")
            # Final verification
            final_stats = await association_manager.get_statistics()
            dr_memory_count = len(dr_registry.digital_twin_replicas)
            
            logger.info(f"✅ Association system initialized:")
            logger.info(f"   📊 Persistent: {final_stats['total_associations']} associations")
            logger.info(f"   💾 Memory: {dr_memory_count} mappings")
            
            if final_stats['total_associations'] != dr_memory_count:
                logger.warning(f"⚠️ Mismatch detected: persistent={final_stats['total_associations']}, memory={dr_memory_count}")
                logger.info("🔧 This will be auto-corrected by the orchestrator")  
        except Exception as e:
            logger.error(f"❌ Failed to initialize association system: {e}")
            # Non-critical error - continue without persistent associations
            logger.warning("Continuing without persistent association system")

    async def _restore_associations_from_metadata(self, association_manager, dr_registry) -> None:
        """Restore associations from replica metadata (one-time migration)."""
        try:
            logger.info("🔄 Attempting to restore associations from replica metadata...")
            
            # Get all replicas
            replicas = await dr_registry.list()
            restored_count = 0
            
            for replica in replicas:
                try:
                    # Try to find parent twin ID from replica
                    twin_id = None
                    
                    if hasattr(replica, 'parent_digital_twin_id'):
                        twin_id = replica.parent_digital_twin_id
                    elif hasattr(replica, 'metadata') and replica.metadata:
                        try:
                            metadata_dict = replica.metadata.to_dict() if hasattr(replica.metadata, 'to_dict') else replica.metadata
                            custom_data = metadata_dict.get('custom', {}) if isinstance(metadata_dict, dict) else {}
                            parent_twin_str = custom_data.get('parent_twin_id')
                            if parent_twin_str:
                                from uuid import UUID
                                twin_id = UUID(parent_twin_str)
                        except Exception as e:
                            logger.debug(f"Failed to parse metadata for replica {replica.id}: {e}")
                    
                    if twin_id:
                        # Create persistent association
                        await association_manager.create_association(
                            twin_id=twin_id,
                            replica_id=replica.id,
                            association_type='data_source'
                        )
                        restored_count += 1
                        logger.info(f"✅ Restored association: {replica.id} -> {twin_id}")
                    else:
                        logger.debug(f"No parent twin found for replica {replica.id}")
                
                except Exception as e:
                    logger.warning(f"Failed to restore association for replica {replica.id}: {e}")
            
            logger.info(f"✅ Restored {restored_count} associations from replica metadata")
            
        except Exception as e:
            logger.error(f"❌ Failed to restore associations from metadata: {e}")
    
    async def _start_layer_orchestrators(self) -> None:
        """Start all layer orchestrators."""
        logger.info("Starting layer orchestrators...")
        
        try:
            # Start in dependency order
            await self.virtualization_orchestrator.start()
            logger.info("Virtualization Layer started")
            
            await self.service_orchestrator.start()
            logger.info("Service Layer started")
            
            await self.digital_twin_orchestrator.start()
            logger.info("Digital Twin Layer started")
            
            logger.info("All layer orchestrators started")
            
        except Exception as e:
            logger.error(f"Failed to start layer orchestrators: {e}")
            raise
    
    async def _start_application_services(self) -> None:
        """Start application services."""
        try:
            from src.layers.application import start_application_services
            await start_application_services()
            logger.info("Application services started")
        except Exception as e:
            logger.error(f"Failed to start application services: {e}")
            raise
    
    async def _log_platform_status(self) -> None:
        """Log current platform status."""
        try:
            if self.digital_twin_orchestrator:
                overview = await self.digital_twin_orchestrator.get_platform_overview()
                
                logger.info("Platform Status Overview:")
                dt_running = overview['digital_twin_layer']['running']
                logger.info(f"   Digital Twin Layer: {'Running' if dt_running else 'Stopped'}")
                logger.info(f"   Active Digital Twins: {overview['digital_twin_layer']['orchestration']['active_twins']}")
                
                if 'layer_statistics' in overview:
                    if 'virtualization' in overview['layer_statistics']:
                        virt_stats = overview['layer_statistics']['virtualization']['virtualization_layer']
                        virt_running = virt_stats['running']
                        logger.info(f"   Virtualization Layer: {'Running' if virt_running else 'Stopped'}")
                    
                    if 'service' in overview['layer_statistics']:
                        svc_stats = overview['layer_statistics']['service']['service_layer']
                        svc_running = svc_stats['running']
                        logger.info(f"   Service Layer: {'Running' if svc_running else 'Stopped'}")
                
                # NEW: Log storage status
                if 'storage_health' in overview:
                    storage = overview['storage_health']
                    primary_status = "Connected" if storage.get('twin_registry_connected') else "Failed"
                    logger.info(f"   Storage: {primary_status} ({storage.get('primary_storage', 'unknown')})")
                    
                    if storage.get('cache_connected'):
                        logger.info(f"   Cache: Connected ({storage.get('cache_storage', 'unknown')})")
                
                health = overview['platform_health']['all_layers_running']
                logger.info(f"   Platform Health: {'Healthy' if health else 'Degraded'}")
                
        except Exception as e:
            logger.warning(f"Could not retrieve platform status: {e}")
    
    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            self._shutdown_event.set()
        
        # Register signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """Main entry point for the Digital Twin Platform."""
    platform = DigitalTwinPlatform()
    
    try:
        # Initialize and start the platform
        await platform.initialize()
        await platform.start()
        
        # Get API configuration
        host = platform.config.get('api.host')
        port = platform.config.get('api.port')
        
        # Print startup information
        logger.info(f"Digital Twin Platform ready! API available at http://{host}:{port}")
        logger.info(f"API Documentation: http://{host}:{port}/docs")
        logger.info(f"Health Check: http://{host}:{port}/health")
        
        # NEW: Print storage information
        if platform._storage_status:
            primary = platform._storage_status.get('primary_storage', 'unknown')
            cache = platform._storage_status.get('cache_storage', 'none')
            logger.info(f"Storage: {primary} + {cache}")
        if platform.protocol_registry:
            status = platform.protocol_registry.get_registry_status()
            logger.info(f"Device Protocols: {len(status.get('available_protocols', []))} protocols available")
            logger.info(f"Device Management: http://{host}:{port}/api/v1/devices")
        # Start API server (this will block until shutdown)
        await platform.start_api_server(host=host, port=port)
        
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    except Exception as e:
        logger.error(f"Platform error: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)
    finally:
        await platform.stop()


def sync_main():
    """Synchronous wrapper for the main async function."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Create necessary directories
    Path("logs").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)
    Path("templates").mkdir(exist_ok=True)
    
    # Check Python version
    if sys.version_info < (3, 8):
        print("Python 3.8 or higher is required")
        sys.exit(1)
    
    print("Digital Twin Platform")
    print("=" * 50)
    print("Environment Variables:")
    print(f"   DT_ENVIRONMENT: {os.getenv('DT_ENVIRONMENT', 'development')}")
    print(f"   DT_API_HOST: {os.getenv('DT_API_HOST', '0.0.0.0')}")
    print(f"   DT_API_PORT: {os.getenv('DT_API_PORT', '8000')}")
    print(f"   DT_LOG_LEVEL: {os.getenv('DT_LOG_LEVEL', 'INFO')}")
    print(f"   DT_STORAGE_PRIMARY: {os.getenv('DT_STORAGE_PRIMARY', 'mongodb')}")
    print(f"   DT_STORAGE_CACHE: {os.getenv('DT_STORAGE_CACHE', 'redis')}")
    print("=" * 50)
    print("Device Protocol Settings:")
    print(f"   DT_PROTOCOL_HTTP_TIMEOUT: {os.getenv('DT_PROTOCOL_HTTP_TIMEOUT', '30')}")
    print(f"   DT_PROTOCOL_HTTP_POLL: {os.getenv('DT_PROTOCOL_HTTP_POLL', '60')}")
    print(f"   DT_PROTOCOL_MQTT_KEEPALIVE: {os.getenv('DT_PROTOCOL_MQTT_KEEPALIVE', '60')}")
    print(f"   DT_PROTOCOL_MAX_ADAPTERS: {os.getenv('DT_PROTOCOL_MAX_ADAPTERS', '10')}")
    print("=" * 50)
    
    # Run the platform
    sync_main()