# src/utils/entity_wrapper.py
from typing import Any, Dict, List, Set, Optional
from uuid import UUID
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

class DictToObjectWrapper:
    """Enhanced wrapper that properly exposes dictionary attributes."""
    
    def __init__(self, data_dict: Dict[str, Any]):
        self._data = data_dict
        
        # Expose all keys as attributes
        for key, value in data_dict.items():
            setattr(self, key, value)
    
    def __getattr__(self, name):
        """Get attribute from wrapped dictionary."""
        if name in self._data:
            return self._data[name]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
    
    def __setattr__(self, name, value):
        """Set attribute in wrapped dictionary."""
        if name.startswith('_'):
            super().__setattr__(name, value)
        else:
            if hasattr(self, '_data'):
                self._data[name] = value
            super().__setattr__(name, value)
    
    def __str__(self):
        return f"Wrapper({self._data})"
    
    def __repr__(self):
        return f"DictToObjectWrapper({self._data})"

class EnhancedDictToObjectWrapper:
    """Enhanced wrapper that properly exposes all dictionary attributes."""
    
    def __init__(self, data_dict: Dict[str, Any]):
        self._data = data_dict
        
        # Expose all keys as attributes
        for key, value in data_dict.items():
            setattr(self, key, value)
    
    def __getattr__(self, name):
        """Get attribute from wrapped dictionary."""
        if name in self._data:
            return self._data[name]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
    
    def __setattr__(self, name, value):
        """Set attribute in wrapped dictionary."""
        if name.startswith('_'):
            super().__setattr__(name, value)
        else:
            if hasattr(self, '_data'):
                self._data[name] = value
            super().__setattr__(name, value)
    
    def __str__(self):
        return f"Wrapper({self._data})"
    
    def __repr__(self):
        return f"EnhancedDictToObjectWrapper({self._data})"