# src/core/protocols/http_adapter.py

import aiohttp
import asyncio
from datetime import datetime
from typing import Dict, Any
import logging

from .base_adapter import BaseProtocolAdapter, ProtocolStatus, ProtocolMessage

logger = logging.getLogger(__name__)

class HTTPProtocolAdapter(BaseProtocolAdapter):
    """HTTP Protocol Adapter for device communication."""
    
    @property
    def protocol_name(self) -> str:
        return "http"
    
    async def initialize(self) -> None:
        """Initialize HTTP adapter."""
        self.session_timeout = aiohttp.ClientTimeout(total=self.config.get("timeout", 30))
        self.polling_interval = self.config.get("polling_interval", 30)
        self.polling_tasks: Dict[str, asyncio.Task] = {}
        
        logger.info(f"HTTP adapter {self.adapter_id} initialized")
    
    async def connect(self) -> None:
        """Establish HTTP connection (create session)."""
        try:
            self.status = ProtocolStatus.CONNECTING
            
            # Create aiohttp session
            self.session = aiohttp.ClientSession(timeout=self.session_timeout)
            
            # Test connection if base URL provided
            base_url = self.config.get("base_url")
            if base_url:
                try:
                    async with self.session.get(f"{base_url}/health") as response:
                        if response.status == 200:
                            logger.info(f"HTTP adapter {self.adapter_id} health check passed")
                except:
                    logger.warning(f"HTTP adapter {self.adapter_id} health check failed, but continuing")
            
            self.status = ProtocolStatus.CONNECTED
            self.connection_time = datetime.utcnow()
            logger.info(f"HTTP adapter {self.adapter_id} connected")
            
        except Exception as e:
            self.status = ProtocolStatus.ERROR
            self.error_count += 1
            logger.error(f"HTTP adapter {self.adapter_id} connection failed: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Close HTTP connections."""
        self.status = ProtocolStatus.DISCONNECTED
        
        # Cancel all polling tasks
        for device_id, task in self.polling_tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.polling_tasks.clear()
        
        # Close aiohttp session
        if hasattr(self, 'session'):
            await self.session.close()
        
        logger.info(f"HTTP adapter {self.adapter_id} disconnected")
    
    async def add_device(self, device_id: str, device_config: Dict[str, Any]) -> None:
        """Add HTTP device with polling."""
        self.connected_devices[device_id] = device_config
        
        # Start polling task if enabled
        if device_config.get("enable_polling", True):
            self.polling_tasks[device_id] = asyncio.create_task(
                self._poll_device(device_id, device_config)
            )
        
        logger.info(f"Added HTTP device {device_id} to adapter {self.adapter_id}")
    
    async def remove_device(self, device_id: str) -> None:
        """Remove HTTP device."""
        if device_id in self.polling_tasks:
            self.polling_tasks[device_id].cancel()
            del self.polling_tasks[device_id]
        
        if device_id in self.connected_devices:
            del self.connected_devices[device_id]
        
        logger.info(f"Removed HTTP device {device_id} from adapter {self.adapter_id}")
    
    async def send_message(self, device_id: str, message: ProtocolMessage) -> None:
        """Send HTTP message to device."""
        if not self.is_connected:
            raise ConnectionError("HTTP adapter not connected")
        
        device_config = self.connected_devices.get(device_id)
        if not device_config:
            raise ValueError(f"Device {device_id} not found in HTTP adapter")
        
        url = f"http://{device_config['host']}:{device_config['port']}{device_config.get('endpoint', '/data')}"
        
        try:
            async with self.session.post(url, json=message.to_dict()) as response:
                if response.status == 200:
                    logger.debug(f"Message sent to HTTP device {device_id}")
                else:
                    logger.warning(f"HTTP device {device_id} responded with status {response.status}")
        except Exception as e:
            self.error_count += 1
            logger.error(f"Failed to send message to HTTP device {device_id}: {e}")
            raise
    
    async def _poll_device(self, device_id: str, device_config: Dict[str, Any]) -> None:
        """Poll HTTP device for data."""
        url = f"http://{device_config['host']}:{device_config['port']}{device_config.get('endpoint', '/data')}"
        poll_interval = device_config.get("polling_interval", self.polling_interval)
        
        while self.is_connected and device_id in self.connected_devices:
            try:
                async with self.session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        message = ProtocolMessage(
                            device_id=device_id,
                            data=data,
                            message_type="polled_data",
                            metadata={"source": "http_polling", "url": url}
                        )
                        await self._handle_incoming_message(message)
                    else:
                        logger.warning(f"HTTP polling device {device_id} returned status {response.status}")
                
                await asyncio.sleep(poll_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error polling HTTP device {device_id}: {e}")
                await asyncio.sleep(poll_interval)