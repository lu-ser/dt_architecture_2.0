# src/core/capabilities/capability_registry.py
"""
Plugin-based Capability Registry for Digital Twin Platform.
Replaces rigid enum system with flexible plugin architecture.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set, Type, Callable
from uuid import UUID
from enum import Enum
import importlib
import inspect
from pathlib import Path

logger = logging.getLogger(__name__)

# ==========================================
# CORE CAPABILITY TYPES (Keep minimal enum for stability)
# ==========================================

class CoreCapability(Enum):
    """Core capabilities that every Digital Twin should support."""
    MONITORING = "monitoring"
    HEALTH_CHECK = "health_check"
    DATA_SYNC = "data_sync"
    # Only universal capabilities here

# ==========================================
# CAPABILITY DEFINITION SYSTEM
# ==========================================

@dataclass
class CapabilityDefinition:
    """Definition of a Digital Twin capability."""
    name: str
    namespace: str  # e.g., "core", "energy", "automotive"
    description: str
    category: str  # "monitoring", "control", "analytics", etc.
    version: str = "1.0.0"
    
    # Schema definitions
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    
    # Permission and access control
    required_permissions: List[str] = field(default_factory=list)
    required_twin_types: List[str] = field(default_factory=list)  # Restrict to specific twin types
    
    # Dependencies and metadata
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def full_name(self) -> str:
        """Get the full namespaced name."""
        if self.namespace == "core":
            return self.name
        return f"{self.namespace}.{self.name}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "namespace": self.namespace,
            "full_name": self.full_name,
            "description": self.description,
            "category": self.category,
            "version": self.version,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "required_permissions": self.required_permissions,
            "required_twin_types": self.required_twin_types,
            "dependencies": self.dependencies,
            "metadata": self.metadata
        }

# ==========================================
# CAPABILITY HANDLER INTERFACE
# ==========================================

@dataclass
class ExecutionContext:
    """Context provided to capability handlers during execution."""
    twin_id: str
    twin_type: str
    user_id: str
    permissions: Set[str]
    twin_metadata: Dict[str, Any]
    execution_config: Dict[str, Any] = field(default_factory=dict)

class ICapabilityHandler(ABC):
    """Interface for capability handlers."""
    
    @abstractmethod
    async def execute(self, input_data: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        """Execute the capability logic."""
        pass
    
    @abstractmethod
    def validate_input(self, input_data: Dict[str, Any]) -> bool:
        """Validate input data against capability requirements."""
        pass
    
    @abstractmethod
    def get_capability_definition(self) -> CapabilityDefinition:
        """Return the capability definition this handler implements."""
        pass

# ==========================================
# CAPABILITY REGISTRY
# ==========================================

class CapabilityRegistry:
    """Central registry for Digital Twin capabilities."""
    
    def __init__(self):
        self._capabilities: Dict[str, CapabilityDefinition] = {}
        self._handlers: Dict[str, ICapabilityHandler] = {}
        self._namespaces: Set[str] = set()
        
        # Load core capabilities
        self._load_core_capabilities()
    
    def register_capability(self, handler: ICapabilityHandler) -> bool:
        """Register a new capability handler."""
        try:
            capability_def = handler.get_capability_definition()
            full_name = capability_def.full_name
            
            # Check for conflicts
            if full_name in self._capabilities:
                logger.warning(f"Capability '{full_name}' already registered, skipping")
                return False
            
            # Validate dependencies
            if not self._validate_dependencies(capability_def):
                logger.error(f"Capability '{full_name}' has unmet dependencies")
                return False
            
            # Register
            self._capabilities[full_name] = capability_def
            self._handlers[full_name] = handler
            self._namespaces.add(capability_def.namespace)
            
            logger.info(f"✅ Registered capability: {full_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register capability: {e}")
            return False
    
    def get_capability(self, name: str) -> Optional[CapabilityDefinition]:
        """Get capability definition by name."""
        return self._capabilities.get(name)
    
    def get_handler(self, name: str) -> Optional[ICapabilityHandler]:
        """Get capability handler by name."""
        return self._handlers.get(name)
    
    def has_capability(self, name: str) -> bool:
        """Check if a capability is registered."""
        return name in self._capabilities
    
    def list_capabilities(self, 
                         namespace: Optional[str] = None,
                         category: Optional[str] = None,
                         twin_type: Optional[str] = None) -> List[CapabilityDefinition]:
        """List capabilities with optional filtering."""
        caps = list(self._capabilities.values())
        
        if namespace:
            caps = [c for c in caps if c.namespace == namespace]
        
        if category:
            caps = [c for c in caps if c.category == category]
        
        if twin_type:
            caps = [c for c in caps if not c.required_twin_types or twin_type in c.required_twin_types]
        
        return caps
    
    def get_namespaces(self) -> List[str]:
        """Get all registered namespaces."""
        return sorted(list(self._namespaces))
    
    def validate_capability_list(self, capability_names: List[str]) -> Dict[str, bool]:
        """Validate a list of capability names."""
        results = {}
        for name in capability_names:
            results[name] = self.has_capability(name)
        return results
    
    def _load_core_capabilities(self) -> None:
        """Load core capabilities."""
        try:
            from .handlers.core import MonitoringHandler, HealthCheckHandler, DataSyncHandler
            
            # Register core handlers
            core_handlers = [
                MonitoringHandler(),
                HealthCheckHandler(), 
                DataSyncHandler()
            ]
            
            for handler in core_handlers:
                self.register_capability(handler)
        except ImportError as e:
            logger.warning(f"Could not load core capability handlers: {e}")
    
    def _validate_dependencies(self, capability_def: CapabilityDefinition) -> bool:
        """Validate that all dependencies are satisfied."""
        for dep in capability_def.dependencies:
            if not self.has_capability(dep):
                logger.error(f"Dependency '{dep}' not found for capability '{capability_def.full_name}'")
                return False
        return True

# ==========================================
# GLOBAL REGISTRY INSTANCE
# ==========================================

_global_registry: Optional[CapabilityRegistry] = None

def get_capability_registry() -> CapabilityRegistry:
    """Get the global capability registry instance."""
    global _global_registry
    if _global_registry is None:
        _global_registry = CapabilityRegistry()
    return _global_registry

def register_capability(handler: ICapabilityHandler) -> bool:
    """Convenience function to register a capability globally."""
    return get_capability_registry().register_capability(handler)