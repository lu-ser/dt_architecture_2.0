# src/setup_capabilities.py
"""
Setup script for initializing the plugin-based capability system.
Run this during application startup to load all capabilities.
"""

import asyncio
import logging
from pathlib import Path
from typing import List
import sys
import os
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.capabilities.capability_registry import get_capability_registry
from src.utils.config import get_config

logger = logging.getLogger(__name__)

async def setup_capability_system():
    """Initialize the capability system with all plugins."""
    logger.info("🚀 Initializing plugin-based capability system...")
    
    registry = get_capability_registry()
    
    # Core capabilities are already loaded during registry initialization
    core_count = len([cap for cap in registry.list_capabilities() if cap.namespace == "core"])
    logger.info(f"✅ Core capabilities loaded: {core_count}")
    
    # Display summary
    all_capabilities = registry.list_capabilities()
    namespaces = registry.get_namespaces()
    
    logger.info(f"🎯 Capability system initialized:")
    logger.info(f"   • Total capabilities: {len(all_capabilities)}")
    logger.info(f"   • Namespaces: {namespaces}")
    
    # Display capabilities by namespace
    for namespace in namespaces:
        caps_in_ns = [cap for cap in all_capabilities if cap.namespace == namespace]
        cap_names = [cap.name for cap in caps_in_ns]
        logger.info(f"   • {namespace}: {cap_names}")
    
    return registry

def validate_system_setup():
    """Validate that the capability system is properly set up."""
    logger.info("🔍 Validating capability system setup...")
    
    registry = get_capability_registry()
    
    # Check core capabilities
    core_capabilities = ['monitoring', 'health_check', 'data_sync']
    missing_core = []
    
    for cap in core_capabilities:
        if not registry.has_capability(cap):
            missing_core.append(cap)
    
    if missing_core:
        logger.error(f"❌ Missing core capabilities: {missing_core}")
        return False
    
    # Check that each capability has a handler
    missing_handlers = []
    for cap_def in registry.list_capabilities():
        if not registry.get_handler(cap_def.full_name):
            missing_handlers.append(cap_def.full_name)
    
    if missing_handlers:
        logger.error(f"❌ Missing handlers for capabilities: {missing_handlers}")
        return False
    
    logger.info("✅ Capability system validation passed")
    return True

async def main():
    """Main setup function."""
    print("=" * 60)
    print("🔧 Digital Twin Platform - Capability System Setup")
    print("=" * 60)
    
    try:
        # Setup the capability system
        registry = await setup_capability_system()
        
        # Validate setup
        if not validate_system_setup():
            logger.error("❌ Capability system setup validation failed")
            return False
        
        print("\n" + "=" * 60)
        print("✅ Capability system setup completed successfully!")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to setup capability system: {e}")
        print(f"\n❌ Setup failed: {e}")
        return False

if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run setup
    success = asyncio.run(main())
    exit(0 if success else 1)