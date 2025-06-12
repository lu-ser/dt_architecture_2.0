# src/utils/entity_wrapper.py - VERSIONE CORRETTA
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
    """Enhanced wrapper that properly exposes dictionary attributes with to_dict support."""
    
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
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert wrapper back to dictionary - METODO MANCANTE!"""
        # Crea una copia pulita del dizionario
        result = {}
        for key, value in self._data.items():
            if hasattr(value, 'to_dict'):
                result[key] = value.to_dict()
            elif isinstance(value, (list, tuple)):
                result[key] = [
                    item.to_dict() if hasattr(item, 'to_dict') else item 
                    for item in value
                ]
            elif isinstance(value, dict):
                result[key] = {
                    k: v.to_dict() if hasattr(v, 'to_dict') else v 
                    for k, v in value.items()
                }
            else:
                result[key] = value
        return result
    
    def __str__(self):
        return f"Wrapper({self._data})"
    
    def __repr__(self):
        return f"DictToObjectWrapper({self._data})"

class EnhancedDictToObjectWrapper(DictToObjectWrapper):
    """Enhanced wrapper with additional utility methods."""
    
    def __init__(self, data_dict: Dict[str, Any]):
        super().__init__(data_dict)
    
    def get_raw_data(self) -> Dict[str, Any]:
        """Get the raw dictionary data."""
        return self._data.copy()
    
    def update_data(self, updates: Dict[str, Any]) -> None:
        """Update the wrapped data."""
        self._data.update(updates)
        for key, value in updates.items():
            setattr(self, key, value)
    
    def has_attribute(self, attr_name: str) -> bool:
        """Check if attribute exists."""
        return attr_name in self._data
    
    def __repr__(self):
        return f"EnhancedDictToObjectWrapper({self._data})"