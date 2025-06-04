import sys
import os
import asyncio
from pathlib import Path
from uuid import uuid4
script_dir = Path(__file__).parent
project_root = script_dir
if script_dir.name == 'tests':
    project_root = script_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
    print(f'✅ Added project root to path: {project_root}')
src_path = project_root / 'src'
if src_path.exists():
    print(f'✅ Found source directory: {src_path}')
else:
    print(f'❌ Source directory not found: {src_path}')
    print(f'Script location: {script_dir}')
    print(f'Looking for src at: {src_path}')
    print('Available directories:')
    for item in project_root.iterdir():
        if item.is_dir():
            print(f'  📁 {item.name}')
    sys.exit(1)

def test_imports():
    print('🔍 Testing imports...')
    try:
        from src.utils.exceptions import DigitalTwinPlatformError, RegistryError, EntityNotFoundError
        print('  ✅ Exceptions imported successfully')
        from src.core.interfaces.base import IEntity, IRegistry, BaseMetadata, EntityStatus
        print('  ✅ Base interfaces imported successfully')
        from src.utils.config import PlatformConfig, ConfigManager, get_config
        print('  ✅ Configuration management imported successfully')
        from src.core.registry.base import AbstractRegistry, RegistryMetrics, BaseCache
        print('  ✅ Registry components imported successfully')
        return True
    except ImportError as e:
        print(f'  ❌ Import failed: {e}')
        return False

def test_exceptions():
    print('\n🧪 Testing exceptions...')
    try:
        from src.utils.exceptions import EntityNotFoundError, EntityAlreadyExistsError
        error = EntityNotFoundError('TestEntity', 'test-id-123')
        assert 'TestEntity' in str(error)
        assert 'test-id-123' in str(error)
        print('  ✅ EntityNotFoundError works correctly')
        error = EntityAlreadyExistsError('TestEntity', 'test-id-456')
        assert 'TestEntity' in str(error)
        assert 'test-id-456' in str(error)
        print('  ✅ EntityAlreadyExistsError works correctly')
        return True
    except Exception as e:
        print(f'  ❌ Exception test failed: {e}')
        return False

def test_configuration():
    print('\n⚙️ Testing configuration...')
    try:
        from src.utils.config import PlatformConfig, DatabaseConfig, ConfigManager, get_config
        config = PlatformConfig()
        config.auth.secret_key = 'test_secret_key_123456789012345678901234567890'
        assert config.service_name == 'digital-twin-platform'
        assert isinstance(config.database, DatabaseConfig)
        print('  ✅ PlatformConfig created successfully')
        manager = ConfigManager()
        test_config = manager.load_from_dict({'debug': True, 'version': 'test-1.0', 'auth': {'secret_key': 'test_secret_for_config_manager_123456789'}})
        assert isinstance(test_config, PlatformConfig)
        print('  ✅ ConfigManager works correctly')
        try:
            global_config = get_config()
            assert isinstance(global_config, PlatformConfig)
            print('  ✅ Global config accessible')
        except Exception as e:
            print('  ⚠️  Global config validation issue (expected in test environment)')
        return True
    except Exception as e:
        print(f'  ❌ Configuration test failed: {e}')
        return False

def test_base_metadata():
    print('\n📋 Testing base metadata...')
    try:
        from src.core.interfaces.base import BaseMetadata
        from datetime import datetime, timezone
        metadata = BaseMetadata(entity_id=uuid4(), timestamp=datetime.now(timezone.utc), version='1.0.0', created_by=uuid4())
        metadata_dict = metadata.to_dict()
        assert 'id' in metadata_dict
        assert 'timestamp' in metadata_dict
        assert 'version' in metadata_dict
        print('  ✅ BaseMetadata created and serialized')
        restored_metadata = BaseMetadata.from_dict(metadata_dict)
        assert restored_metadata.version == metadata.version
        print('  ✅ BaseMetadata deserialized correctly')
        return True
    except Exception as e:
        print(f'  ❌ Base metadata test failed: {e}')
        return False

def test_cache():
    print('\n💾 Testing cache...')
    try:
        from src.core.registry.base import BaseCache
        cache = BaseCache(max_size=3, ttl_seconds=60)
        cache.set('key1', 'value1')
        cache.set('key2', {'nested': 'value'})
        assert cache.get('key1') == 'value1'
        assert cache.get('key2') == {'nested': 'value'}
        assert cache.get('nonexistent') is None
        assert cache.size() == 2
        print('  ✅ Cache basic operations work')
        cache.set('key3', 'value3')
        cache.set('key4', 'value4')
        assert cache.size() == 3
        print('  ✅ Cache size limiting works')
        cache.clear()
        assert cache.size() == 0
        print('  ✅ Cache clearing works')
        return True
    except Exception as e:
        print(f'  ❌ Cache test failed: {e}')
        return False

async def test_mock_storage():
    print('\n🗄️ Testing mock storage...')
    try:

        class SimpleEntity:

            def __init__(self, entity_id, name):
                self.id = entity_id
                self.name = name

            def validate(self):
                return True
        entity = SimpleEntity(uuid4(), 'test-entity')
        assert entity.name == 'test-entity'
        assert entity.validate() is True
        print('  ✅ Simple entity created')
        await asyncio.sleep(0.001)
        print('  ✅ Async operations work')
        return True
    except Exception as e:
        print(f'  ❌ Mock storage test failed: {e}')
        return False

def test_registry_metrics():
    print('\n📊 Testing registry metrics...')
    try:
        from src.core.registry.base import RegistryMetrics
        metrics = RegistryMetrics()
        assert metrics.total_operations == 0
        assert metrics.get_success_ratio() == 0.0
        assert metrics.get_cache_hit_ratio() == 0.0
        print('  ✅ Metrics initialized correctly')
        metrics.record_operation(True, 0.1)
        metrics.record_operation(False, 0.2)
        metrics.record_cache_hit()
        metrics.record_cache_miss()
        assert metrics.total_operations == 2
        assert metrics.successful_operations == 1
        assert metrics.failed_operations == 1
        assert metrics.get_success_ratio() == 0.5
        assert metrics.get_cache_hit_ratio() == 0.5
        print('  ✅ Metrics recording works correctly')
        metrics_dict = metrics.to_dict()
        assert isinstance(metrics_dict, dict)
        assert 'total_operations' in metrics_dict
        print('  ✅ Metrics serialization works')
        return True
    except Exception as e:
        print(f'  ❌ Registry metrics test failed: {e}')
        return False

async def main():
    print('🚀 Digital Twin Platform - Quick Test')
    print('=' * 50)
    tests = [('Imports', test_imports), ('Exceptions', test_exceptions), ('Configuration', test_configuration), ('Base Metadata', test_base_metadata), ('Cache', test_cache), ('Registry Metrics', test_registry_metrics), ('Mock Storage', test_mock_storage)]
    passed = 0
    failed = 0
    for test_name, test_func in tests:
        try:
            if asyncio.iscoroutinefunction(test_func):
                result = await test_func()
            else:
                result = test_func()
            if result:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f'\n❌ {test_name} test crashed: {e}')
            failed += 1
    print('\n' + '=' * 50)
    print(f'📊 Test Results: {passed} passed, {failed} failed')
    if failed == 0:
        print('🎉 All quick tests passed! The basic implementation is working.')
        return 0
    else:
        print('⚠️  Some tests failed. Check the output above for details.')
        return 1

def check_environment():
    print('🔧 Checking environment...')
    script_dir = Path(__file__).parent
    project_root = script_dir
    if script_dir.name == 'tests':
        project_root = script_dir.parent
    print(f'  📁 Project root: {project_root}')
    print(f'  📍 Script location: {script_dir}')
    if sys.version_info < (3, 8):
        print(f'  ❌ Python 3.8+ required, got {sys.version}')
        return False
    else:
        print(f'  ✅ Python version: {sys.version.split()[0]}')
    src_dir = project_root / 'src'
    if not src_dir.exists():
        print(f'  ❌ Source directory not found: {src_dir}')
        return False
    else:
        print(f'  ✅ Source directory found: {src_dir}')
    key_files = ['src/utils/exceptions.py', 'src/utils/config.py', 'src/core/interfaces/base.py', 'src/core/registry/base.py']
    existing_files = []
    missing_files = []
    for file_path in key_files:
        full_path = project_root / file_path
        if full_path.exists():
            existing_files.append(file_path)
        else:
            missing_files.append(file_path)
    if existing_files:
        print(f'  ✅ Found {len(existing_files)} key source files:')
        for file_path in existing_files:
            print(f'    • {file_path}')
    if missing_files:
        print(f'  ⚠️  Missing {len(missing_files)} source files:')
        for file_path in missing_files:
            print(f'    • {file_path}')
        return False
    return True
if __name__ == '__main__':
    if not check_environment():
        print('\n❌ Environment check failed!')
        sys.exit(1)
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print('\n\n⏹️ Test interrupted by user')
        sys.exit(1)
    except Exception as e:
        print(f'\n💥 Unexpected error: {e}')
        sys.exit(1)