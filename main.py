#!/usr/bin/env python3
"""
Main entry point for the Digital Twin Platform.

This module initializes and starts the complete Digital Twin Platform,
including all layers and the API server.
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Optional

# Import configuration and utilities
from src.utils.config import get_config, load_config_from_file, load_config_from_env
from src.utils.exceptions import ConfigurationError

# Setup logging - use basic logging if custom module not available
try:
    from src.utils.logging import setup_logging
except ImportError:
    def setup_logging():
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler()]
        )

# Import layer orchestrators
try:
    from src.layers.application import initialize_application_layer, stop_application_services
except ImportError:
    # Fallback if application layer init file has wrong name
    async def initialize_application_layer():
        from src.layers.application.api_gateway import initialize_api_gateway
        return await initialize_api_gateway()
    
    async def stop_application_services():
        pass

from src.layers.application.api import start_api_server

# Import layer orchestrators directly since they may not have __init__.py files
from src.layers.digital_twin import get_digital_twin_orchestrator
from src.layers.service import get_service_orchestrator  
from src.layers.virtualization import initialize_virtualization_layer

logger = logging.getLogger(__name__)


class DigitalTwinPlatform:
    """Main platform orchestrator."""
    
    def __init__(self):
        self.config = None
        self.running = False
        self.shutdown_event = asyncio.Event()
        
        # Layer references
        self.application_layer = None
        self.digital_twin_layer = None
        self.service_layer = None
        self.virtualization_layer = None
    
    async def initialize(self, config_file: Optional[str] = None) -> None:
        """Initialize the platform."""
        try:
            # Load configuration
            if config_file and Path(config_file).exists():
                logger.info(f"Loading configuration from {config_file}")
                self.config = load_config_from_file(config_file)
            else:
                logger.info("Loading configuration from environment variables")
                self.config = load_config_from_env()
            
            logger.info(f"Platform configuration loaded - Environment: {self.config.environment.value}")
            
            # Initialize layers in order of dependency
            logger.info("Initializing platform layers...")
            
            # 1. Virtualization Layer (base layer)
            logger.info("Initializing Virtualization Layer...")
            self.virtualization_layer = await initialize_virtualization_layer()
            
            # 2. Service Layer - get orchestrator and initialize
            logger.info("Initializing Service Layer...")
            self.service_layer = get_service_orchestrator()
            if not self.service_layer._initialized:
                await self.service_layer.initialize()
            
            # 3. Digital Twin Layer - get orchestrator and initialize
            logger.info("Initializing Digital Twin Layer...")
            self.digital_twin_layer = get_digital_twin_orchestrator()
            if not self.digital_twin_layer._initialized:
                await self.digital_twin_layer.initialize()
            
            # 4. Application Layer (API layer, depends on all others)
            logger.info("Initializing Application Layer...")
            self.application_layer = await initialize_application_layer()
            
            logger.info("All platform layers initialized successfully")
            
        except Exception as e:
            logger.error(f"Platform initialization failed: {e}")
            raise ConfigurationError(f"Failed to initialize platform: {e}")
    
    async def start(self) -> None:
        """Start the platform."""
        if self.running:
            logger.warning("Platform is already running")
            return
        
        try:
            logger.info("Starting Digital Twin Platform...")
            
            # Start layers
            if self.virtualization_layer:
                await self.virtualization_layer.start()
            
            if self.service_layer:
                await self.service_layer.start()
            
            if self.digital_twin_layer:
                await self.digital_twin_layer.start()
            
            # Application layer doesn't have a start method in the current implementation
            
            self.running = True
            logger.info("Digital Twin Platform started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start platform: {e}")
            await self.stop()
            raise
    
    async def stop(self) -> None:
        """Stop the platform gracefully."""
        if not self.running:
            return
        
        logger.info("Stopping Digital Twin Platform...")
        
        try:
            # Stop layers in reverse order
            await stop_application_services()
            
            if self.digital_twin_layer:
                await self.digital_twin_layer.stop()
            
            if self.service_layer:
                await self.service_layer.stop()
            
            if self.virtualization_layer:
                await self.virtualization_layer.stop()
            
            self.running = False
            self.shutdown_event.set()
            logger.info("Digital Twin Platform stopped successfully")
            
        except Exception as e:
            logger.error(f"Error during platform shutdown: {e}")
    
    async def run_api_server(self) -> None:
        """Run the API server."""
        if not self.running:
            raise RuntimeError("Platform must be started before running API server")
        
        # Get API configuration
        api_config = self.config.protocols.http_config
        host = api_config.get("host", "0.0.0.0")
        port = api_config.get("port", 8000)
        
        logger.info(f"Starting API server on {host}:{port}")
        
        # Start the API server
        await start_api_server(host=host, port=port, reload=self.config.debug)
    
    async def run_until_shutdown(self) -> None:
        """Run the platform until shutdown signal is received."""
        # Setup signal handlers
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown...")
            asyncio.create_task(self.stop())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Wait for shutdown
        await self.shutdown_event.wait()


async def main():
    """Main entry point."""
    platform = None
    
    try:
        # Setup basic logging first
        setup_logging()
        
        logger.info("=" * 60)
        logger.info("Digital Twin Platform Starting...")
        logger.info("=" * 60)
        
        # Parse command line arguments
        import argparse
        parser = argparse.ArgumentParser(description="Digital Twin Platform")
        parser.add_argument("--config", "-c", help="Configuration file path")
        parser.add_argument("--host", default="0.0.0.0", help="API server host")
        parser.add_argument("--port", type=int, default=8000, help="API server port")
        parser.add_argument("--debug", action="store_true", help="Enable debug mode")
        
        args = parser.parse_args()
        
        # Create and initialize platform
        platform = DigitalTwinPlatform()
        await platform.initialize(config_file=args.config)
        
        # Start platform
        await platform.start()
        
        # Override config with CLI args if provided
        if args.debug:
            platform.config.debug = True
        
        platform.config.protocols.http_config["host"] = args.host
        platform.config.protocols.http_config["port"] = args.port
        
        # Run API server and platform
        await asyncio.gather(
            platform.run_api_server(),
            platform.run_until_shutdown()
        )
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Platform error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if platform:
            await platform.stop()
        logger.info("Digital Twin Platform shutdown complete")


def run_sync():
    """Synchronous entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_sync()