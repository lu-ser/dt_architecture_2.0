import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4
from src.core.interfaces.base import BaseMetadata, EntityStatus
from src.core.interfaces.replica import IDigitalReplica, ReplicaType, ReplicaConfiguration, DataAggregationMode, DeviceData, AggregatedData, DataQuality
from src.utils.exceptions import DigitalReplicaError, ConfigurationError, ProtocolConnectionError
from src.utils.config import get_config, PlatformConfig
logger = logging.getLogger(__name__)

class ContainerEnvironment:

    def __init__(self, container_id: str):
        self.container_id = container_id
        self.start_time = datetime.now(timezone.utc)
        self.environment_vars = dict(os.environ) if 'os' in globals() else {}
        self.resource_limits = self._detect_resource_limits()
        self.health_status = 'starting'
        self.metadata = {'container_runtime': self._detect_container_runtime(), 'platform': self._detect_platform(), 'python_version': sys.version}

    def _detect_container_runtime(self) -> str:
        if Path('/.dockerenv').exists():
            return 'docker'
        elif Path('/proc/1/cgroup').exists():
            try:
                with open('/proc/1/cgroup', 'r') as f:
                    content = f.read()
                    if 'docker' in content:
                        return 'docker'
                    elif 'kubepods' in content:
                        return 'kubernetes'
            except Exception:
                pass
        return 'unknown'

    def _detect_platform(self) -> str:
        import platform
        return f'{platform.system()}-{platform.machine()}'

    def _detect_resource_limits(self) -> Dict[str, Any]:
        limits = {}
        try:
            with open('/sys/fs/cgroup/memory/memory.limit_in_bytes', 'r') as f:
                memory_limit = int(f.read().strip())
                if memory_limit < 1 << 62:
                    limits['memory_bytes'] = memory_limit
                    limits['memory_mb'] = memory_limit // (1024 * 1024)
        except Exception:
            pass
        try:
            with open('/sys/fs/cgroup/cpu/cpu.cfs_quota_us', 'r') as f:
                quota = int(f.read().strip())
            with open('/sys/fs/cgroup/cpu/cpu.cfs_period_us', 'r') as f:
                period = int(f.read().strip())
            if quota > 0 and period > 0:
                limits['cpu_cores'] = quota / period
        except Exception:
            pass
        return limits

    def get_uptime(self) -> float:
        return (datetime.now(timezone.utc) - self.start_time).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        return {'container_id': self.container_id, 'start_time': self.start_time.isoformat(), 'uptime_seconds': self.get_uptime(), 'resource_limits': self.resource_limits, 'health_status': self.health_status, 'metadata': self.metadata}

class ProtocolConnection:

    def __init__(self, protocol_type: str, config: Dict[str, Any]):
        self.protocol_type = protocol_type
        self.config = config
        self.connected = False
        self.connection_time: Optional[datetime] = None
        self.last_activity: Optional[datetime] = None
        self.message_count = 0
        self.error_count = 0

    async def connect(self) -> None:
        try:
            if self.protocol_type == 'http':
                await self._connect_http()
            elif self.protocol_type == 'mqtt':
                await self._connect_mqtt()
            else:
                raise ProtocolConnectionError(f'Unsupported protocol: {self.protocol_type}')
            self.connected = True
            self.connection_time = datetime.now(timezone.utc)
            logger.info(f'Connected to {self.protocol_type} protocol')
        except Exception as e:
            self.error_count += 1
            logger.error(f'Failed to connect to {self.protocol_type}: {e}')
            raise ProtocolConnectionError(f'Connection failed: {e}')

    async def disconnect(self) -> None:
        self.connected = False
        self.connection_time = None
        logger.info(f'Disconnected from {self.protocol_type} protocol')

    async def send_message(self, message: Dict[str, Any]) -> None:
        if not self.connected:
            raise ProtocolConnectionError('Not connected')
        self.message_count += 1
        self.last_activity = datetime.now(timezone.utc)
        logger.debug(f'Sent message via {self.protocol_type}: {len(json.dumps(message))} bytes')

    async def _connect_http(self) -> None:
        host = self.config.get('host', 'localhost')
        port = self.config.get('port', 8000)
        await asyncio.sleep(0.1)
        logger.debug(f'HTTP connection established to {host}:{port}')

    async def _connect_mqtt(self) -> None:
        broker = self.config.get('broker', 'localhost')
        port = self.config.get('port', 1883)
        await asyncio.sleep(0.2)
        logger.debug(f'MQTT connection established to {broker}:{port}')

    def get_connection_info(self) -> Dict[str, Any]:
        return {'protocol_type': self.protocol_type, 'connected': self.connected, 'connection_time': self.connection_time.isoformat() if self.connection_time else None, 'last_activity': self.last_activity.isoformat() if self.last_activity else None, 'message_count': self.message_count, 'error_count': self.error_count, 'config': {k: v for k, v in self.config.items() if k not in ['password', 'token']}}

class DigitalReplicaContainer:

    def __init__(self, replica: IDigitalReplica, container_config: Dict[str, Any], container_id: Optional[str]=None):
        self.replica = replica
        self.container_config = container_config
        self.container_id = container_id or f'dr-container-{replica.id}'
        self.environment = ContainerEnvironment(self.container_id)
        self.connections: Dict[str, ProtocolConnection] = {}
        self.running = False
        self.shutdown_requested = False
        self.tasks: Set[asyncio.Task] = set()
        self.data_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.processed_data_count = 0
        self.last_data_time: Optional[datetime] = None
        self.health_check_interval = container_config.get('health_check_interval', 30)
        self.last_health_check: Optional[datetime] = None
        self.health_issues: List[str] = []
        self._setup_signal_handlers()

    def _setup_signal_handlers(self) -> None:

        def signal_handler(signum, frame):
            logger.info(f'Received signal {signum}, initiating graceful shutdown')
            self.shutdown_requested = True
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, signal_handler)
        if hasattr(signal, 'SIGINT'):
            signal.signal(signal.SIGINT, signal_handler)

    async def initialize(self) -> None:
        try:
            logger.info(f'Initializing Digital Replica container {self.container_id}')
            await self.replica.initialize()
            await self._setup_protocol_connections()
            self.environment.health_status = 'healthy'
            logger.info(f'Container {self.container_id} initialized successfully')
        except Exception as e:
            self.environment.health_status = 'failed'
            logger.error(f'Container initialization failed: {e}')
            raise DigitalReplicaError(f'Container initialization failed: {e}')

    async def start(self) -> None:
        if self.running:
            logger.warning(f'Container {self.container_id} is already running')
            return
        try:
            logger.info(f'Starting Digital Replica container {self.container_id}')
            await self.replica.start()
            await self._start_background_tasks()
            self.running = True
            self.environment.health_status = 'running'
            logger.info(f'Container {self.container_id} started successfully')
        except Exception as e:
            self.environment.health_status = 'failed'
            logger.error(f'Container start failed: {e}')
            raise DigitalReplicaError(f'Container start failed: {e}')

    async def stop(self) -> None:
        if not self.running:
            logger.warning(f'Container {self.container_id} is not running')
            return
        try:
            logger.info(f'Stopping Digital Replica container {self.container_id}')
            self.running = False
            self.environment.health_status = 'stopping'
            await self._stop_background_tasks()
            await self.replica.stop()
            await self._disconnect_protocols()
            self.environment.health_status = 'stopped'
            logger.info(f'Container {self.container_id} stopped successfully')
        except Exception as e:
            self.environment.health_status = 'failed'
            logger.error(f'Container stop failed: {e}')
            raise DigitalReplicaError(f'Container stop failed: {e}')

    async def run(self) -> None:
        try:
            await self.initialize()
            await self.start()
            while self.running and (not self.shutdown_requested):
                await asyncio.sleep(1)
                await self._process_data_queue()
                if self.shutdown_requested:
                    logger.info('Shutdown requested, stopping container')
                    break
        except Exception as e:
            logger.error(f'Container run error: {e}')
            self.environment.health_status = 'failed'
            raise
        finally:
            await self.stop()

    async def _setup_protocol_connections(self) -> None:
        protocol_configs = self.container_config.get('protocols', {})
        for protocol_name, protocol_config in protocol_configs.items():
            if protocol_config.get('enabled', False):
                connection = ProtocolConnection(protocol_name, protocol_config)
                await connection.connect()
                self.connections[protocol_name] = connection
                logger.info(f'Setup {protocol_name} protocol connection')

    async def _disconnect_protocols(self) -> None:
        for protocol_name, connection in self.connections.items():
            try:
                await connection.disconnect()
                logger.info(f'Disconnected {protocol_name} protocol')
            except Exception as e:
                logger.error(f'Error disconnecting {protocol_name}: {e}')
        self.connections.clear()

    async def _start_background_tasks(self) -> None:
        health_task = asyncio.create_task(self._health_monitor())
        self.tasks.add(health_task)
        data_task = asyncio.create_task(self._data_processor())
        self.tasks.add(data_task)
        heartbeat_task = asyncio.create_task(self._protocol_heartbeat())
        self.tasks.add(heartbeat_task)
        logger.info(f'Started {len(self.tasks)} background tasks')

    async def _stop_background_tasks(self) -> None:
        for task in self.tasks:
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        logger.info('Stopped all background tasks')

    async def _health_monitor(self) -> None:
        while self.running:
            try:
                await self._perform_health_check()
                await asyncio.sleep(self.health_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f'Health monitor error: {e}')
                await asyncio.sleep(self.health_check_interval)

    async def _data_processor(self) -> None:
        while self.running:
            try:
                try:
                    data = await asyncio.wait_for(self.data_queue.get(), timeout=1.0)
                    await self._process_device_data(data)
                    self.data_queue.task_done()
                except asyncio.TimeoutError:
                    continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f'Data processor error: {e}')
                await asyncio.sleep(1)

    async def _protocol_heartbeat(self) -> None:
        while self.running:
            try:
                for protocol_name, connection in self.connections.items():
                    if connection.connected:
                        heartbeat = {'type': 'heartbeat', 'container_id': self.container_id, 'replica_id': str(self.replica.id), 'timestamp': datetime.now(timezone.utc).isoformat()}
                        await connection.send_message(heartbeat)
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f'Protocol heartbeat error: {e}')
                await asyncio.sleep(60)

    async def _perform_health_check(self) -> None:
        self.last_health_check = datetime.now(timezone.utc)
        self.health_issues.clear()
        if self.replica.status not in [EntityStatus.ACTIVE, EntityStatus.INACTIVE]:
            self.health_issues.append(f'Replica status: {self.replica.status.value}')
        for protocol_name, connection in self.connections.items():
            if not connection.connected:
                self.health_issues.append(f'Protocol {protocol_name} disconnected')
        queue_size = self.data_queue.qsize()
        if queue_size > 800:
            self.health_issues.append(f'Data queue near capacity: {queue_size}/1000')
        uptime = self.environment.get_uptime()
        if uptime > 3600 and self.processed_data_count == 0:
            self.health_issues.append('No data processed in last hour')
        if not self.health_issues:
            self.environment.health_status = 'healthy'
        elif len(self.health_issues) <= 2:
            self.environment.health_status = 'warning'
        else:
            self.environment.health_status = 'critical'

    async def receive_device_data(self, device_data: DeviceData) -> None:
        try:
            await self.data_queue.put(device_data)
            logger.debug(f'Queued device data from {device_data.device_id}')
        except asyncio.QueueFull:
            logger.warning(f'Data queue full, dropping data from {device_data.device_id}')

    async def _process_device_data(self, device_data: DeviceData) -> None:
        try:
            await self.replica.receive_device_data(device_data)
            self.processed_data_count += 1
            self.last_data_time = datetime.now(timezone.utc)
            for connection in self.connections.values():
                if connection.connected:
                    ack_message = {'type': 'data_ack', 'device_id': device_data.device_id, 'timestamp': device_data.timestamp.isoformat(), 'container_id': self.container_id, 'replica_id': str(self.replica.id)}
                    await connection.send_message(ack_message)
        except Exception as e:
            logger.error(f'Error processing device data: {e}')

    async def send_aggregated_data(self, aggregated_data: AggregatedData) -> None:
        try:
            message = {'type': 'aggregated_data', 'data': aggregated_data.to_dict(), 'container_id': self.container_id, 'timestamp': datetime.now(timezone.utc).isoformat()}
            for connection in self.connections.values():
                if connection.connected:
                    await connection.send_message(message)
            logger.debug(f'Sent aggregated data from replica {aggregated_data.source_replica_id}')
        except Exception as e:
            logger.error(f'Error sending aggregated data: {e}')

    def get_container_status(self) -> Dict[str, Any]:
        return {'container_id': self.container_id, 'replica_id': str(self.replica.id), 'running': self.running, 'environment': self.environment.to_dict(), 'connections': {name: conn.get_connection_info() for name, conn in self.connections.items()}, 'data_processing': {'queue_size': self.data_queue.qsize(), 'processed_count': self.processed_data_count, 'last_data_time': self.last_data_time.isoformat() if self.last_data_time else None}, 'health': {'last_check': self.last_health_check.isoformat() if self.last_health_check else None, 'issues': self.health_issues, 'status': self.environment.health_status}, 'tasks': {'active_tasks': len([t for t in self.tasks if not t.done()]), 'total_tasks': len(self.tasks)}}

    def get_metrics(self) -> Dict[str, Any]:
        return {'container_id': self.container_id, 'uptime_seconds': self.environment.get_uptime(), 'processed_data_count': self.processed_data_count, 'queue_size': self.data_queue.qsize(), 'protocol_connections': len([c for c in self.connections.values() if c.connected]), 'total_connections': len(self.connections), 'health_status': self.environment.health_status, 'resource_usage': self.environment.resource_limits, 'memory_usage_estimate': self.processed_data_count * 0.001, 'message_count': sum((c.message_count for c in self.connections.values())), 'error_count': sum((c.error_count for c in self.connections.values()))}

class DigitalReplicaContainerFactory:

    @staticmethod
    def create_container(replica: IDigitalReplica, container_config: Optional[Dict[str, Any]]=None) -> DigitalReplicaContainer:
        if container_config is None:
            container_config = DigitalReplicaContainerFactory.get_default_config()
        return DigitalReplicaContainer(replica=replica, container_config=container_config)

    @staticmethod
    def get_default_config() -> Dict[str, Any]:
        return {'health_check_interval': 30, 'protocols': {'http': {'enabled': True, 'host': '0.0.0.0', 'port': 8080, 'timeout': 30}, 'mqtt': {'enabled': False, 'broker': 'localhost', 'port': 1883, 'keepalive': 60}}, 'resource_limits': {'memory_mb': 512, 'cpu_cores': 0.5}, 'logging': {'level': 'INFO', 'format': 'json'}}

    @staticmethod
    def create_from_config_file(replica: IDigitalReplica, config_file_path: str) -> DigitalReplicaContainer:
        import json
        with open(config_file_path, 'r') as f:
            container_config = json.load(f)
        return DigitalReplicaContainerFactory.create_container(replica, container_config)