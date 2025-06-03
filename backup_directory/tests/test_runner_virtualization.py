import sys
import os
import asyncio
import argparse
import tempfile
import json
import shutil
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
script_dir = Path(__file__).parent
if script_dir.name == 'tests':
    project_root = script_dir.parent
else:
    project_root = script_dir
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
print(f'📍 Project root: {project_root}')
print(f'📍 Python path includes: {project_root}')

def check_imports():
    missing_modules = []
    try:
        from src.core.interfaces.base import BaseMetadata, EntityStatus
        from src.core.interfaces.replica import ReplicaType, DataAggregationMode, DeviceData, DataQuality
        print('✅ Core interfaces imported successfully')
    except ImportError as e:
        missing_modules.append(f'Core interfaces: {e}')
    try:
        from src.utils.exceptions import DigitalReplicaError, ConfigurationError
        from src.utils.config import get_config
        print('✅ Utils modules imported successfully')
    except ImportError as e:
        missing_modules.append(f'Utils modules: {e}')
    try:
        from tests.mocks.storage_adapter import InMemoryStorageAdapter
        print('✅ Test mocks imported successfully')
    except ImportError as e:
        missing_modules.append(f'Test mocks: {e}')
    virtualization_components = {'Factory': 'src.layers.virtualization.dr_factory', 'Registry': 'src.layers.virtualization.dr_registry', 'Management': 'src.layers.virtualization.dr_management', 'Container': 'src.layers.virtualization.dr_container', 'Ontology': 'src.layers.virtualization.ontology.manager'}
    available_components = {}
    for component_name, module_path in virtualization_components.items():
        try:
            __import__(module_path)
            available_components[component_name] = True
            print(f'✅ {component_name} component available')
        except ImportError as e:
            available_components[component_name] = False
            print(f'⚠️  {component_name} component not available: {e}')
    return (missing_modules, available_components)

async def test_factory_component():
    print('\n🏭 Testing Digital Replica Factory...')
    try:
        from src.layers.virtualization.dr_factory import DigitalReplicaFactory, StandardDataAggregator
        from src.core.interfaces.replica import ReplicaType, DataAggregationMode, DeviceData, DataQuality
        factory = DigitalReplicaFactory()
        print('✅ Factory created successfully')
        config = {'replica_type': 'sensor_aggregator', 'parent_digital_twin_id': str(uuid4()), 'device_ids': ['device-001', 'device-002'], 'aggregation_mode': 'batch', 'aggregation_config': {'batch_size': 5}, 'data_retention_policy': {'retention_days': 30}, 'quality_thresholds': {'min_quality': 0.7}}
        is_valid = factory.validate_config(config)
        assert is_valid, 'Configuration should be valid'
        print('✅ Configuration validation works')
        replica = await factory.create(config)
        assert replica is not None, 'Replica should be created'
        assert replica.replica_type == ReplicaType.SENSOR_AGGREGATOR
        print(f'✅ Replica created: {replica.id}')
        aggregator = StandardDataAggregator()
        await aggregator.configure({'method': 'average'})
        device_data = [DeviceData(device_id='device-001', timestamp=datetime.now(timezone.utc), data={'temperature': 25.0, 'humidity': 60.0}, data_type='sensor', quality=DataQuality.HIGH), DeviceData(device_id='device-001', timestamp=datetime.now(timezone.utc), data={'temperature': 27.0, 'humidity': 65.0}, data_type='sensor', quality=DataQuality.HIGH)]
        result = await aggregator.aggregate(device_data)
        assert result.aggregated_data['temperature'] == 26.0, f"Expected 26.0, got {result.aggregated_data['temperature']}"
        print(f"✅ Data aggregation works: temp={result.aggregated_data['temperature']}, humidity={result.aggregated_data['humidity']}")
        return True
    except Exception as e:
        print(f'❌ Factory test failed: {e}')
        import traceback
        traceback.print_exc()
        return False

async def test_registry_component():
    print('\n📋 Testing Digital Replica Registry...')
    try:
        from src.layers.virtualization.dr_registry import DigitalReplicaRegistry, DeviceAssociation
        from src.layers.virtualization.dr_factory import DigitalReplicaFactory
        from tests.mocks.storage_adapter import InMemoryStorageAdapter
        from src.core.interfaces.replica import DataQuality
        storage_adapter = InMemoryStorageAdapter()
        registry = DigitalReplicaRegistry(storage_adapter)
        await registry.connect()
        print('✅ Registry created and connected')
        factory = DigitalReplicaFactory()
        config = {'replica_type': 'sensor_aggregator', 'parent_digital_twin_id': str(uuid4()), 'device_ids': ['device-001'], 'aggregation_mode': 'batch', 'aggregation_config': {'batch_size': 5}, 'data_retention_policy': {'retention_days': 30}, 'quality_thresholds': {'min_quality': 0.7}}
        replica = await factory.create(config)
        await registry.register_digital_replica(replica)
        print(f'✅ Replica registered: {replica.id}')
        retrieved = await registry.get_digital_replica(replica.id)
        assert retrieved.id == replica.id, 'Retrieved replica should match original'
        print('✅ Replica retrieval works')
        association = DeviceAssociation(device_id='device-001', replica_id=replica.id, association_type='managed')
        await registry.associate_device(association)
        associations = await registry.get_device_associations('device-001')
        assert len(associations) == 1, f'Expected 1 association, got {len(associations)}'
        print('✅ Device associations work')
        await registry.record_device_data('device-001', replica.id, DataQuality.HIGH)
        await registry.record_aggregation(replica.id)
        stats = await registry.get_data_flow_statistics()
        assert stats['metrics']['total_data_points'] > 0, 'Should have recorded data points'
        print('✅ Data flow metrics work')
        return True
    except Exception as e:
        print(f'❌ Registry test failed: {e}')
        import traceback
        traceback.print_exc()
        return False

async def test_ontology_component():
    print('\n🧠 Testing Ontology & Template System...')
    try:
        from src.layers.virtualization.ontology.manager import OntologyManager, Template, TemplateType, JSONOntologyLoader
        temp_dir = Path(tempfile.mkdtemp())
        try:
            manager = OntologyManager(temp_dir)
            print('✅ Ontology manager created')
            template = Template(template_id='test_template', name='Test Template', template_type=TemplateType.DIGITAL_REPLICA, version='1.0.0', description='Test template', configuration={'replica_type': 'sensor_aggregator', 'aggregation_mode': 'batch', 'aggregation_config': {'batch_size': 10}}, metadata={'allowed_override_keys': ['aggregation_config.batch_size'], 'required_keys': ['replica_type']})
            manager.templates['test_template'] = template
            print('✅ Template created and stored')
            overrides = {'aggregation_config': {'batch_size': 20}}
            result = manager.apply_template('test_template', overrides)
            assert result['aggregation_config']['batch_size'] == 20, f'Override failed: {result}'
            print('✅ Template override works')
            ontology_data = {'name': 'Test_Ontology', 'version': '1.0.0', 'namespace': 'http://test.example/', 'classes': [{'name': 'TestDevice', 'uri': 'http://test.example/#TestDevice', 'properties': [{'name': 'deviceId', 'property_type': 'datatype', 'range_type': 'string', 'constraints': {'required': True}}]}]}
            ontologies_dir = temp_dir / 'ontologies'
            ontologies_dir.mkdir()
            ontology_file = ontologies_dir / 'test.json'
            with open(ontology_file, 'w') as f:
                json.dump(ontology_data, f)
            await manager.load_ontologies()
            assert len(manager.ontologies) == 1, f'Expected 1 ontology, got {len(manager.ontologies)}'
            print('✅ Ontology loading works')
            valid_config = {'deviceId': 'device-001'}
            errors = manager.validate_configuration(valid_config, 'Test_Ontology', 'TestDevice')
            assert len(errors) == 0, f'Valid config should have no errors: {errors}'
            invalid_config = {}
            errors = manager.validate_configuration(invalid_config, 'Test_Ontology', 'TestDevice')
            assert len(errors) > 0, 'Invalid config should have errors'
            print('✅ Configuration validation works')
            return True
        finally:
            shutil.rmtree(temp_dir)
    except Exception as e:
        print(f'❌ Ontology test failed: {e}')
        import traceback
        traceback.print_exc()
        return False

async def test_integration_workflow():
    print('\n🔄 Testing Integration Workflow...')
    try:
        from src.layers.virtualization.dr_factory import DigitalReplicaFactory
        from src.layers.virtualization.dr_registry import DigitalReplicaRegistry
        from src.layers.virtualization.dr_management import DigitalReplicaLifecycleManager
        from src.layers.virtualization.ontology.manager import OntologyManager, Template, TemplateType
        from tests.mocks.storage_adapter import InMemoryStorageAdapter
        from src.core.interfaces.base import EntityStatus
        print('✅ All components imported successfully')
        temp_dir = Path(tempfile.mkdtemp())
        try:
            ontology_manager = OntologyManager(temp_dir)
            template = Template(template_id='integration_test', name='Integration Test Template', template_type=TemplateType.DIGITAL_REPLICA, version='1.0.0', description='Template for integration testing', configuration={'replica_type': 'sensor_aggregator', 'aggregation_mode': 'batch', 'aggregation_config': {'batch_size': 5, 'method': 'average'}})
            ontology_manager.templates['integration_test'] = template
            print('✅ Template system ready')
            factory = DigitalReplicaFactory()
            storage_adapter = InMemoryStorageAdapter()
            registry = DigitalReplicaRegistry(storage_adapter)
            await registry.connect()
            lifecycle_manager = DigitalReplicaLifecycleManager(factory, registry)
            print('✅ All managers initialized')
            base_config = ontology_manager.apply_template('integration_test')
            complete_config = {**base_config, 'parent_digital_twin_id': str(uuid4()), 'device_ids': ['device-001', 'device-002'], 'data_retention_policy': {'retention_days': 30}, 'quality_thresholds': {'min_quality': 0.7}}
            replica = await lifecycle_manager.create_entity(complete_config)
            print(f'✅ Replica created via lifecycle manager: {replica.id}')
            retrieved = await registry.get_digital_replica(replica.id)
            assert retrieved.id == replica.id, 'Replica should be in registry'
            print('✅ Replica found in registry')
            await lifecycle_manager.start_entity(replica.id)
            status = await lifecycle_manager.get_entity_status(replica.id)
            assert status == EntityStatus.ACTIVE, f'Expected ACTIVE, got {status}'
            print('✅ Replica started successfully')
            monitoring_data = await lifecycle_manager.monitor_entity(replica.id)
            assert 'replica_id' in monitoring_data, 'Monitoring data should include replica_id'
            assert monitoring_data['status'] == 'active', f"Expected active status, got {monitoring_data.get('status')}"
            print('✅ Monitoring works')
            discovered = await registry.discover_replicas({'type': 'sensor_aggregator'})
            assert len(discovered) >= 1, 'Should discover at least one replica'
            print('✅ Discovery works')
            print('\n🎉 Integration workflow completed successfully!')
            return True
        finally:
            shutil.rmtree(temp_dir)
    except Exception as e:
        print(f'❌ Integration test failed: {e}')
        import traceback
        traceback.print_exc()
        return False

async def run_all_tests():
    print('🚀 Running All Virtualization Layer Tests')
    print('=' * 50)
    test_results = {}
    missing_modules, available_components = check_imports()
    if missing_modules:
        print('\n❌ Missing required modules:')
        for module in missing_modules:
            print(f'   • {module}')
        return False
    print(f'\n📊 Component Availability:')
    for component, available in available_components.items():
        status = '✅' if available else '❌'
        print(f'   {status} {component}')
    if available_components.get('Factory', False):
        test_results['Factory'] = await test_factory_component()
    else:
        print('\n⚠️  Skipping Factory tests - component not available')
        test_results['Factory'] = None
    if available_components.get('Registry', False):
        test_results['Registry'] = await test_registry_component()
    else:
        print('\n⚠️  Skipping Registry tests - component not available')
        test_results['Registry'] = None
    if available_components.get('Ontology', False):
        test_results['Ontology'] = await test_ontology_component()
    else:
        print('\n⚠️  Skipping Ontology tests - component not available')
        test_results['Ontology'] = None
    core_available = all([available_components.get('Factory', False), available_components.get('Registry', False), available_components.get('Management', False), available_components.get('Ontology', False)])
    if core_available:
        test_results['Integration'] = await test_integration_workflow()
    else:
        print('\n⚠️  Skipping Integration tests - not all core components available')
        test_results['Integration'] = None
    print('\n' + '=' * 50)
    print('📊 Test Results Summary:')
    passed = 0
    failed = 0
    skipped = 0
    for test_name, result in test_results.items():
        if result is True:
            print(f'   ✅ {test_name}: PASSED')
            passed += 1
        elif result is False:
            print(f'   ❌ {test_name}: FAILED')
            failed += 1
        else:
            print(f'   ⚠️  {test_name}: SKIPPED')
            skipped += 1
    print(f'\nResults: {passed} passed, {failed} failed, {skipped} skipped')
    if failed == 0 and passed > 0:
        print('🎉 All available tests passed!')
        return True
    else:
        print('❌ Some tests failed or no tests were run')
        return False

def main():
    parser = argparse.ArgumentParser(description='Test runner for Virtualization Layer')
    parser.add_argument('--component', choices=['factory', 'registry', 'ontology', 'integration'], help='Run tests for specific component only')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()
    if args.verbose:
        print('🔧 Verbose mode enabled')
    try:
        if args.component == 'factory':
            success = asyncio.run(test_factory_component())
        elif args.component == 'registry':
            success = asyncio.run(test_registry_component())
        elif args.component == 'ontology':
            success = asyncio.run(test_ontology_component())
        elif args.component == 'integration':
            success = asyncio.run(test_integration_workflow())
        else:
            success = asyncio.run(run_all_tests())
        return 0 if success else 1
    except KeyboardInterrupt:
        print('\n⏹️ Tests interrupted by user')
        return 1
    except Exception as e:
        print(f'\n💥 Unexpected error: {e}')
        import traceback
        traceback.print_exc()
        return 1
if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)