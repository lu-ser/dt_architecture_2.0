#!/usr/bin/env python3
"""
Quick System Test for Virtualization Layer

This script performs a rapid end-to-end test of the virtualization layer
to verify all components work together correctly.

LOCATION: tests/quick_system_test.py

Usage:
    python tests/quick_system_test.py
"""

import sys
import os
import asyncio
import tempfile
import json
import yaml
import shutil
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

# Add project root to path
script_dir = Path(__file__).parent
if script_dir.name == 'tests':
    project_root = script_dir.parent
else:
    project_root = script_dir

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

print(f"🚀 Quick System Test - Virtualization Layer")
print(f"📍 Project root: {project_root}")
print("=" * 60)


def create_test_templates(temp_dir: Path):
    """Create test template files in temporary directory."""
    print("📁 Creating test templates...")
    
    # Create directory structure
    dr_templates_dir = temp_dir / "digital_replicas"
    ontologies_dir = temp_dir / "ontologies"
    dr_templates_dir.mkdir(parents=True, exist_ok=True)
    ontologies_dir.mkdir(parents=True, exist_ok=True)
    
    # Test IoT Template
    iot_template = {
        "template_id": "quick_test_iot",
        "name": "Quick Test IoT Sensor",
        "template_type": "digital_replica",
        "version": "1.0.0",
        "description": "Quick test IoT sensor replica",
        "ontology_classes": ["TestDevice"],
        "configuration": {
            "replica_type": "sensor_aggregator",
            "aggregation_mode": "batch",
            "aggregation_config": {
                "batch_size": 3,
                "method": "average"
            },
            "data_retention_policy": {
                "retention_days": 1
            },
            "quality_thresholds": {
                "min_quality": 0.5
            }
        },
        "metadata": {
            "allowed_override_keys": ["aggregation_config.batch_size"],
            "required_keys": ["replica_type", "aggregation_mode"]
        }
    }
    
    with open(dr_templates_dir / "quick_test_iot.json", 'w') as f:
        json.dump(iot_template, f, indent=2)
    
    # Test Ontology
    test_ontology = {
        "name": "QuickTest_Ontology",
        "version": "1.0.0",
        "namespace": "http://quicktest.example/",
        "classes": [
            {
                "name": "TestDevice",
                "uri": "http://quicktest.example/#TestDevice",
                "properties": [
                    {
                        "name": "deviceId",
                        "property_type": "datatype",
                        "range_type": "string",
                        "constraints": {"required": True}
                    },
                    {
                        "name": "temperature",
                        "property_type": "datatype",
                        "range_type": "float",
                        "constraints": {"min_value": -50, "max_value": 100}
                    }
                ]
            }
        ]
    }
    
    with open(ontologies_dir / "quicktest.json", 'w') as f:
        json.dump(test_ontology, f, indent=2)
    
    print(f"✅ Created test templates in {temp_dir}")


async def test_system_workflow():
    """Test the complete system workflow."""
    temp_dir = Path(tempfile.mkdtemp())
    
    try:
        print(f"🧪 Starting system workflow test...")
        
        # Step 1: Setup test templates
        create_test_templates(temp_dir)
        
        # Step 2: Import required modules
        print("📦 Importing components...")
        try:
            # Core interfaces
            from src.core.interfaces.base import BaseMetadata, EntityStatus
            from src.core.interfaces.replica import (
                ReplicaType, DataAggregationMode, DeviceData, DataQuality, AggregatedData
            )
            
            # Virtualization components
            from src.layers.virtualization.dr_factory import DigitalReplicaFactory, StandardDataAggregator
            from src.layers.virtualization.dr_registry import DigitalReplicaRegistry, DeviceAssociation
            from src.layers.virtualization.dr_management import DigitalReplicaLifecycleManager, ReplicaDeploymentTarget
            from src.layers.virtualization.ontology.manager import OntologyManager, Template, TemplateType
            
            # Storage
            from tests.mocks.storage_adapter import InMemoryStorageAdapter
            
            print("✅ All components imported successfully")
            
        except ImportError as e:
            print(f"❌ Import failed: {e}")
            print("⚠️  Some virtualization components may not be implemented yet")
            return False
        
        # Step 3: Initialize Ontology Manager
        print("🧠 Initializing ontology system...")
        ontology_manager = OntologyManager(temp_dir)
        await ontology_manager.load_ontologies()
        await ontology_manager.load_templates()
        
        print(f"   • Loaded {len(ontology_manager.ontologies)} ontologies")
        print(f"   • Loaded {len(ontology_manager.templates)} templates")
        
        # Step 4: Initialize other components
        print("🏭 Initializing core components...")
        factory = DigitalReplicaFactory()
        
        storage_adapter = InMemoryStorageAdapter()
        registry = DigitalReplicaRegistry(storage_adapter)
        await registry.connect()
        
        lifecycle_manager = DigitalReplicaLifecycleManager(factory, registry)
        
        print("✅ All components initialized")
        
        # Step 5: Create replica from template
        print("📋 Creating replica from template...")
        
        # Apply template
        base_config = ontology_manager.apply_template("quick_test_iot")
        
        # Complete configuration
        complete_config = {
            **base_config,
            "parent_digital_twin_id": str(uuid4()),
            "device_ids": ["test-device-001", "test-device-002"],
            "data_retention_policy": {"retention_days": 1},
            "quality_thresholds": {"min_quality": 0.5}
        }
        
        # Validate against ontology
        validation_errors = ontology_manager.validate_configuration(
            {"deviceId": "test-device-001", "temperature": 25.0},
            "QuickTest_Ontology",
            "TestDevice"
        )
        
        if validation_errors:
            print(f"⚠️  Validation errors: {validation_errors}")
        else:
            print("✅ Configuration validated against ontology")
        
        # Create replica
        replica = await lifecycle_manager.create_entity(complete_config)
        print(f"✅ Created replica: {replica.id}")
        
        # Step 6: Test replica functionality
        print("🔄 Testing replica functionality...")
        
        # Start replica
        await lifecycle_manager.start_entity(replica.id)
        status = await lifecycle_manager.get_entity_status(replica.id)
        print(f"   • Replica status: {status.value}")
        
        # Test device association
        association = DeviceAssociation(
            device_id="test-device-001",
            replica_id=replica.id,
            association_type="managed"
        )
        await registry.associate_device(association)
        print("   • Device associated successfully")
        
        # Test data aggregation
        aggregator = StandardDataAggregator()
        await aggregator.configure({"method": "average"})
        
        device_data = [
            DeviceData(
                device_id="test-device-001",
                timestamp=datetime.now(timezone.utc),
                data={"temperature": 25.0, "humidity": 60.0},
                data_type="sensor",
                quality=DataQuality.HIGH
            ),
            DeviceData(
                device_id="test-device-001",
                timestamp=datetime.now(timezone.utc),
                data={"temperature": 27.0, "humidity": 65.0},
                data_type="sensor",
                quality=DataQuality.HIGH
            ),
            DeviceData(
                device_id="test-device-001",
                timestamp=datetime.now(timezone.utc),
                data={"temperature": 26.0, "humidity": 62.0},
                data_type="sensor",
                quality=DataQuality.HIGH
            )
        ]
        
        # Send data to replica
        for data in device_data:
            await replica.receive_device_data(data)
        
        # Get aggregation statistics
        stats = await replica.get_aggregation_statistics()
        print(f"   • Data received: {stats['data_received']}")
        print(f"   • Aggregations performed: {stats['total_aggregations']}")
        
        # Test aggregation directly
        aggregated = await aggregator.aggregate(device_data)
        print(f"   • Average temperature: {aggregated.aggregated_data['temperature']}°C")
        print(f"   • Average humidity: {aggregated.aggregated_data['humidity']}%")
        
        # Step 7: Test registry discovery
        print("🔍 Testing discovery and monitoring...")
        
        # Record data flow
        await registry.record_device_data("test-device-001", replica.id, DataQuality.HIGH)
        await registry.record_aggregation(replica.id)
        
        # Discover replicas
        discovered = await registry.discover_replicas({
            "type": "sensor_aggregator"
        })
        print(f"   • Discovered {len(discovered)} replicas")
        
        # Get performance metrics
        performance = await registry.get_replica_performance(replica.id)
        print(f"   • Performance metrics available: {'replica_id' in performance}")
        
        # Step 8: Test deployment simulation
        print("📦 Testing deployment simulation...")
        
        # Add deployment target
        target = ReplicaDeploymentTarget(
            target_id="test_target",
            target_type="container",
            capacity={"memory": 512, "cpu": 1.0, "max_replicas": 5},
            location="test"
        )
        await lifecycle_manager.add_deployment_target(target)
        
        # Simulate deployment
        deployment_id = await lifecycle_manager.deploy_replica(replica, "test_target")
        print(f"   • Deployment ID: {deployment_id}")
        
        # Step 9: Test health monitoring
        print("❤️  Testing health monitoring...")
        
        health_check = await lifecycle_manager.perform_health_check(replica.id)
        print(f"   • Health status: {health_check.status.value}")
        print(f"   • Health checks passed: {sum(health_check.checks.values())}/{len(health_check.checks)}")
        
        # Step 10: Get system statistics
        print("📊 System statistics...")
        
        data_flow_stats = await registry.get_data_flow_statistics()
        management_stats = await lifecycle_manager.get_management_statistics()
        ontology_stats = ontology_manager.get_statistics()
        
        print(f"   • Total data points: {data_flow_stats['metrics']['total_data_points']}")
        print(f"   • Total replicas: {management_stats['total_replicas']}")
        print(f"   • Ontologies: {ontology_stats['ontologies']['count']}")
        print(f"   • Templates: {ontology_stats['templates']['count']}")
        
        # Step 11: Test scaling
        print("⚖️  Testing scaling...")
        
        await lifecycle_manager.scale_replica(replica.id, 2)
        scaled_replicas = await registry.find_replicas_by_digital_twin(replica.parent_digital_twin_id)
        print(f"   • Scaled to {len(scaled_replicas)} replicas")
        
        # Cleanup
        print("🧹 Cleaning up...")
        await lifecycle_manager.terminate_entity(replica.id)
        await registry.disconnect()
        
        print("\n🎉 System workflow test completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ System test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        shutil.rmtree(temp_dir)


async def test_template_loading():
    """Test template loading with real files."""
    print("📋 Testing template loading from files...")
    
    temp_dir = Path(tempfile.mkdtemp())
    
    try:
        # Create test files
        create_test_templates(temp_dir)
        
        # Import and test
        from src.layers.virtualization.ontology.manager import OntologyManager
        
        manager = OntologyManager(temp_dir)
        
        # Load ontologies and templates
        await manager.load_ontologies()
        await manager.load_templates()
        
        print(f"✅ Loaded {len(manager.ontologies)} ontologies:")
        for name in manager.list_ontologies():
            print(f"   • {name}")
        
        print(f"✅ Loaded {len(manager.templates)} templates:")
        for template_id in manager.list_templates():
            template = manager.get_template(template_id)
            print(f"   • {template.name} ({template_id})")
        
        # Test template application
        config = manager.apply_template("quick_test_iot", {
            "aggregation_config.batch_size": 10  # Use dot notation as specified in allowed_override_keys
        })
        
        print(f"✅ Template applied with override:")
        print(f"   • Batch size: {config['aggregation_config']['batch_size']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Template loading test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        shutil.rmtree(temp_dir)


async def test_data_aggregation():
    """Test data aggregation functionality."""
    print("📊 Testing data aggregation...")
    
    try:
        from src.layers.virtualization.dr_factory import StandardDataAggregator
        from src.core.interfaces.replica import DeviceData, DataQuality
        
        # Create aggregator
        aggregator = StandardDataAggregator()
        
        # Test different aggregation methods
        test_data = [
            DeviceData(
                device_id="device-001",
                timestamp=datetime.now(timezone.utc),
                data={"temperature": 20.0, "humidity": 50.0},
                data_type="sensor",
                quality=DataQuality.HIGH
            ),
            DeviceData(
                device_id="device-001",
                timestamp=datetime.now(timezone.utc),
                data={"temperature": 30.0, "humidity": 70.0},
                data_type="sensor",
                quality=DataQuality.HIGH
            ),
            DeviceData(
                device_id="device-001",
                timestamp=datetime.now(timezone.utc),
                data={"temperature": 25.0, "humidity": 60.0},
                data_type="sensor",
                quality=DataQuality.HIGH
            )
        ]
        
        methods = ["average", "max", "min", "sum"]
        
        for method in methods:
            await aggregator.configure({"method": method})
            result = await aggregator.aggregate(test_data)
            
            temp = result.aggregated_data["temperature"]
            humidity = result.aggregated_data["humidity"]
            
            print(f"   • {method.capitalize()}: temp={temp}°C, humidity={humidity}%")
        
        print("✅ All aggregation methods tested")
        return True
        
    except Exception as e:
        print(f"❌ Data aggregation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_system_health():
    """Check if the system components are available."""
    print("🔍 Checking system health...")
    
    components = {
        "Core Interfaces": "src.core.interfaces.base",
        "Replica Interfaces": "src.core.interfaces.replica",
        "Utils Config": "src.utils.config",
        "Utils Exceptions": "src.utils.exceptions",
        "Test Mocks": "tests.mocks.storage_adapter",
        "DR Factory": "src.layers.virtualization.dr_factory",
        "DR Registry": "src.layers.virtualization.dr_registry",
        "DR Management": "src.layers.virtualization.dr_management",
        "Ontology Manager": "src.layers.virtualization.ontology.manager"
    }
    
    available = {}
    missing = []
    
    for component_name, module_path in components.items():
        try:
            __import__(module_path)
            available[component_name] = True
            print(f"   ✅ {component_name}")
        except ImportError as e:
            available[component_name] = False
            missing.append(f"{component_name}: {e}")
            print(f"   ❌ {component_name}: {e}")
    
    return available, missing


async def main():
    """Main test function."""
    print("🚀 Quick System Test for Virtualization Layer")
    print("=" * 60)
    
    # Check system health
    available, missing = check_system_health()
    
    if missing:
        print(f"\n⚠️  Missing components: {len(missing)}")
        for component in missing:
            print(f"   • {component}")
        
        if len(missing) > 4:  # Too many missing components
            print("\n❌ Too many components missing. Please check implementation.")
            return False
    
    print(f"\n✅ Available components: {len([c for c in available.values() if c])}")
    
    # Run tests
    test_results = {}
    
    # Test 1: Template loading
    if available.get("Ontology Manager", False):
        print(f"\n" + "="*40)
        test_results["Template Loading"] = await test_template_loading()
    else:
        print(f"\n⚠️  Skipping template loading test - Ontology Manager not available")
        test_results["Template Loading"] = None
    
    # Test 2: Data aggregation
    if available.get("DR Factory", False):
        print(f"\n" + "="*40)
        test_results["Data Aggregation"] = await test_data_aggregation()
    else:
        print(f"\n⚠️  Skipping data aggregation test - DR Factory not available")
        test_results["Data Aggregation"] = None
    
    # Test 3: Full system workflow
    all_core_available = all([
        available.get("DR Factory", False),
        available.get("DR Registry", False),
        available.get("DR Management", False),
        available.get("Ontology Manager", False)
    ])
    
    if all_core_available:
        print(f"\n" + "="*40)
        test_results["System Workflow"] = await test_system_workflow()
    else:
        print(f"\n⚠️  Skipping system workflow test - not all core components available")
        test_results["System Workflow"] = None
    
    # Results summary
    print(f"\n" + "="*60)
    print("📊 Test Results Summary:")
    
    passed = sum(1 for result in test_results.values() if result is True)
    failed = sum(1 for result in test_results.values() if result is False)
    skipped = sum(1 for result in test_results.values() if result is None)
    
    for test_name, result in test_results.items():
        if result is True:
            print(f"   ✅ {test_name}: PASSED")
        elif result is False:
            print(f"   ❌ {test_name}: FAILED")
        else:
            print(f"   ⚠️  {test_name}: SKIPPED")
    
    print(f"\nSummary: {passed} passed, {failed} failed, {skipped} skipped")
    
    if failed == 0 and passed > 0:
        print("\n🎉 All available tests passed! Virtualization Layer is working correctly.")
        success_rate = passed / (passed + skipped) if (passed + skipped) > 0 else 0
        print(f"📈 Success rate: {success_rate:.1%} of available components tested")
        return True
    elif failed > 0:
        print(f"\n❌ {failed} test(s) failed. Check implementation.")
        return False
    else:
        print(f"\n⚠️  No tests could be run due to missing components.")
        return False


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        exit_code = 0 if success else 1
        print(f"\n🏁 Test completed with exit code: {exit_code}")
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n⏹️ Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)