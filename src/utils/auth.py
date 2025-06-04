from uuid import UUID
from typing import Union

def safe_uuid_conversion(value: Union[str, UUID, None], field_name: str) -> UUID:
    """Safely convert a value to UUID with proper error handling"""
    if value is None:
        raise ValueError(f'{field_name} cannot be None')
    
    if isinstance(value, UUID):
        return value
    
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            raise ValueError(f'Invalid UUID format for {field_name}: {value}')
    
    raise ValueError(f'{field_name} must be UUID or string, got {type(value)}')