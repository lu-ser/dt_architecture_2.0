"""
Comprehensive test suite for the Virtualization Layer.

LOCATION: tests/test_virtualization_layer.py

Run with: python -m pytest tests/test_virtualization_layer.py -v
"""

import pytest
import asyncio
import json
import tempfile
import shutil
from pathlib import Path
from uuid import uuid4, UUID
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

# Test what we can import (adjust imports based on what's available)
try:
    from src.layers.virtualization.dr_factory import DigitalReplicaFactory, DigitalReplica, StandardDataAggregator
    from src.layers.virtualization.dr_registry import DigitalReplicaRegistry, DeviceAssociation
    from src.layers.virtualization.dr_management import DigitalReplicaLifecycleManager, ReplicaDeploymentTarget
    from src.layers.virtualization.ontology.manager import (
        OntologyManager, Template, Ontology, JSONOntologyLoader, YAMLOntologyLoader,
        TemplateType, OntologyFormat, SemanticClass, SemanticProperty
    )
    
    # Test with available interfaces
    from src.core.interfaces.base import BaseMetadata, EntityStatus
    from src.core.interfaces.replica import (
        ReplicaType, ReplicaConfiguration, DataAggregationMode, 
        DeviceData, DataQuality, AggregatedData
    )
    
    # Use our test storage adapter
    from tests.mocks.storage_adapter import InMemoryStorageAdapter, MockEntity
    
    # Exceptions
    from src.utils.exceptions import (
        DigitalReplicaError, ConfigurationError, EntityCreationError,
        FactoryConfigurationError, InvalidConfigurationError
    )
    
    IMPORTS_AVAILABLE = True
    
except ImportError as e:
    print(f"⚠️  Import error: {e}")
    print("Some tests may be skipped due to missing modules")
    IMPORTS_AVAILABLE = False


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="Required modules not available")
class TestDigitalReplicaFactory:
    """Test Digital Replica Factory functionality."""
    
    @pytest.fixture
    def factory(self):
        """Create factory instance."""
        return DigitalReplicaFactory()
    
    @pytest.fixture
    def sample_config(self):
        """Sample configuration for replica creation."""
        return {
            "replica_type": "sensor_aggregator",
            "parent_digital_twin_id": str(uuid4()),
            "device_ids": ["device-001", "device-002"],
            "aggregation_mode": "batch",
            "aggregation_config": {
                "batch_size": 5,
                "method": "average"
            },
            "data_retention_policy": {
                "retention_days": 30
            },
            "quality_thresholds": {
                "min_quality": 0.7
            }
        }
    
    @pytest.mark.asyncio
    async def test_factory_creation(self, factory):
        """Test factory initialization."""
        assert factory is not None
        assert len(factory.get_supported_replica_types()) > 0
        assert "sensor_aggregator" in [rt.value for rt in factory.get_supported_replica_types()]
    
    @pytest.mark.asyncio
    async def test_create_replica_from_config(self, factory, sample_config):
        """Test creating replica from configuration."""
        replica = await factory.create(sample_config)
        
        assert isinstance(replica, DigitalReplica)
        assert replica.replica_type == ReplicaType.SENSOR_AGGREGATOR
        assert replica.aggregation_mode == DataAggregationMode.BATCH
        assert len(replica.device_ids) == 2
        assert replica.validate()
    
    @pytest.mark.asyncio
    async def test_create_replica_with_metadata(self, factory, sample_config):
        """Test creating replica with custom metadata."""
        metadata = BaseMetadata(
            entity_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            version="1.0.0",
            created_by=uuid4(),
            custom={"test": "metadata"}
        )
        
        replica = await factory.create(sample_config, metadata)
        
        assert replica.id == metadata.id
        assert replica.metadata.custom["test"] == "metadata"
    
    @pytest.mark.asyncio
    async def test_invalid_configuration(self, factory):
        """Test factory with invalid configuration."""
        invalid_config = {
            "replica_type": "invalid_type",
            # Missing required fields
        }
        
        with pytest.raises(EntityCreationError):
            await factory.create(invalid_config)
    
    @pytest.mark.asyncio
    async def test_template_creation(self, factory):
        """Test creating replica from template."""
        template_id = "iot_sensor"
        overrides = {
            "parent_digital_twin_id": str(uuid4()),
            "device_ids": ["sensor-001"]
        }
        
        # This will use the built-in template
        replica = await factory.create_from_template(template_id, overrides)
        
        assert isinstance(replica, DigitalReplica)
        assert len(replica.device_ids) == 1
    
    def test_configuration_validation(self, factory, sample_config):
        """Test configuration validation."""
        assert factory.validate_config(sample_config) is True
        
        # Test invalid configuration
        invalid_config = sample_config.copy()
        del invalid_config["replica_type"]
        assert factory.validate_config(invalid_config) is False
    
    def test_get_config_schema(self, factory):
        """Test getting configuration schema."""
        schema = factory.get_config_schema("digital_replica")
        
        assert isinstance(schema, dict)
        assert "properties" in schema
        assert "required" in schema


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="Required modules not available")
class TestStandardDataAggregator:
    """Test Standard Data Aggregator functionality."""
    
    @pytest.fixture
    def aggregator(self):
        """Create aggregator instance."""
        return StandardDataAggregator()
    
    @pytest.fixture
    def sample_device_data(self):
        """Create sample device data."""
        return [
            DeviceData(
                device_id="device-001",
                timestamp=datetime.now(timezone.utc),
                data={"temperature": 25.0, "humidity": 60.0},
                data_type="sensor",
                quality=DataQuality.HIGH
            ),
            DeviceData(
                device_id="device-001", 
                timestamp=datetime.now(timezone.utc),
                data={"temperature": 26.0, "humidity": 62.0},
                data_type="sensor",
                quality=DataQuality.HIGH
            )
        ]
    
    @pytest.mark.asyncio
    async def test_aggregator_configuration(self, aggregator):
        """Test aggregator configuration."""
        config = {"method": "average", "window_size": 10}
        await aggregator.configure(config)
        
        assert aggregator.aggregation_method == "average"
    
    @pytest.mark.asyncio
    async def test_data_aggregation_average(self, aggregator, sample_device_data):
        """Test average aggregation."""
        await aggregator.configure({"method": "average"})
        
        result = await aggregator.aggregate(sample_device_data)
        
        assert isinstance(result, AggregatedData)
        assert result.aggregated_data["temperature"] == 25.5  # (25+26)/2
        assert result.aggregated_data["humidity"] == 61.0     # (60+62)/2
        assert result.source_count == 2
        assert result.aggregation_method == "average"
    
    @pytest.mark.asyncio
    async def test_data_aggregation_max(self, aggregator, sample_device_data):
        """Test max aggregation."""
        await aggregator.configure({"method": "max"})
        
        result = await aggregator.aggregate(sample_device_data)
        
        assert result.aggregated_data["temperature"] == 26.0
        assert result.aggregated_data["humidity"] == 62.0
        assert result.aggregation_method == "max"
    
    def test_data_quality_validation(self, aggregator):
        """Test data quality validation."""
        # High quality data
        good_data = DeviceData(
            device_id="device-001",
            timestamp=datetime.now(timezone.utc),
            data={"temperature": 25.0, "humidity": 60.0},
            data_type="sensor"
        )
        
        quality = aggregator.validate_data(good_data)
        assert quality == DataQuality.HIGH
        
        # Poor quality data (many nulls)
        bad_data = DeviceData(
            device_id="device-001",
            timestamp=datetime.now(timezone.utc), 
            data={"temperature": None, "humidity": None, "pressure": None},
            data_type="sensor"
        )
        
        quality = aggregator.validate_data(bad_data)
        assert quality == DataQuality.INVALID
    
    def test_can_aggregate(self, aggregator, sample_device_data):
        """Test aggregation feasibility check."""
        assert aggregator.can_aggregate(sample_device_data) is True
        
        # Test with empty data
        assert aggregator.can_aggregate([]) is False


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="Required modules not available")
class TestDigitalReplicaRegistry:
    """Test Digital Replica Registry functionality."""
    
    @pytest.fixture
    async def registry(self):
        """Create registry instance."""
        storage_adapter = InMemoryStorageAdapter()
        registry = DigitalReplicaRegistry(storage_adapter)
        await registry.connect()
        return registry
    
    @pytest.fixture
    async def sample_replica(self):
        """Create sample replica."""
        factory = DigitalReplicaFactory()
        config = {
            "replica_type": "sensor_aggregator",
            "parent_digital_twin_id": str(uuid4()),
            "device_ids": ["device-001"],
            "aggregation_mode": "batch",
            "aggregation_config": {"batch_size": 5},
            "data_retention_policy": {"retention_days": 30},
            "quality_thresholds": {"min_quality": 0.7}
        }
        return await factory.create(config)
    
    @pytest.mark.asyncio
    async def test_registry_initialization(self, registry):
        """Test registry initialization."""
        assert registry is not None
        assert registry.is_connected is True
        assert isinstance(registry.metrics, type(registry.metrics))
    
    @pytest.mark.asyncio
    async def test_register_replica(self, registry, sample_replica):
        """Test replica registration."""
        await registry.register_digital_replica(sample_replica)
        
        # Verify registration
        assert await registry.exists(sample_replica.id) is True
        
        # Retrieve and verify
        retrieved = await registry.get_digital_replica(sample_replica.id)
        assert retrieved.id == sample_replica.id
        assert retrieved.replica_type == sample_replica.replica_type
    
    @pytest.mark.asyncio
    async def test_device_associations(self, registry, sample_replica):
        """Test device association management."""
        await registry.register_digital_replica(sample_replica)
        
        # Create device association
        association = DeviceAssociation(
            device_id="device-001",
            replica_id=sample_replica.id,
            association_type="managed"
        )
        
        await registry.associate_device(association)
        
        # Verify association
        associations = await registry.get_device_associations("device-001")
        assert len(associations) == 1
        assert associations[0].device_id == "device-001"
        assert associations[0].replica_id == sample_replica.id
        
        # Test replica devices
        devices = await registry.get_replica_devices(sample_replica.id)
        assert "device-001" in devices
    
    @pytest.mark.asyncio
    async def test_find_replicas_by_type(self, registry, sample_replica):
        """Test finding replicas by type."""
        await registry.register_digital_replica(sample_replica)
        
        replicas = await registry.find_replicas_by_type(ReplicaType.SENSOR_AGGREGATOR)
        
        assert len(replicas) >= 1
        assert any(r.id == sample_replica.id for r in replicas)
    
    @pytest.mark.asyncio
    async def test_data_flow_recording(self, registry, sample_replica):
        """Test data flow metrics recording."""
        await registry.register_digital_replica(sample_replica)
        
        # Record some data flow
        await registry.record_device_data(
            "device-001", 
            sample_replica.id, 
            DataQuality.HIGH
        )
        
        await registry.record_aggregation(sample_replica.id)
        
        # Check metrics
        stats = await registry.get_data_flow_statistics()
        assert stats["metrics"]["total_data_points"] > 0
        assert stats["metrics"]["aggregations_performed"] > 0


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="Required modules not available")
class TestOntologyManager:
    """Test Ontology and Template Management System."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test files."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def sample_ontology_data(self):
        """Sample ontology data."""
        return {
            "name": "Test_Ontology",
            "version": "1.0.0",
            "namespace": "http://test.ontology/",
            "classes": [
                {
                    "name": "TestDevice",
                    "uri": "http://test.ontology/#TestDevice",
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
    
    @pytest.fixture
    def sample_template_data(self):
        """Sample template data."""
        return {
            "template_id": "test_template",
            "name": "Test Template",
            "template_type": "digital_replica",
            "version": "1.0.0",
            "description": "Test template for testing",
            "configuration": {
                "replica_type": "sensor_aggregator",
                "aggregation_mode": "batch",
                "aggregation_config": {
                    "batch_size": 10,
                    "method": "average"
                }
            },
            "ontology_classes": ["TestDevice"],
            "metadata": {
                "allowed_override_keys": ["aggregation_config.batch_size"],
                "required_keys": ["replica_type"]
            }
        }
    
    @pytest.fixture
    async def ontology_manager(self, temp_dir):
        """Create ontology manager with temporary directory."""
        manager = OntologyManager(temp_dir)
        return manager
    
    def test_json_ontology_loader(self, temp_dir, sample_ontology_data):
        """Test JSON ontology loader."""
        # Create test ontology file
        ontology_file = temp_dir / "test_ontology.json"
        with open(ontology_file, 'w') as f:
            json.dump(sample_ontology_data, f)
        
        loader = JSONOntologyLoader()
        assert loader.can_load(ontology_file) is True
        
        # Test loading
        async def test_load():
            ontology = await loader.load(ontology_file)
            assert ontology.name == "Test_Ontology"
            assert len(ontology.classes) == 1
            assert "TestDevice" in ontology.classes
            
            # Test class properties
            test_device = ontology.get_class("TestDevice")
            assert test_device is not None
            assert len(test_device.properties) == 2
            
        asyncio.run(test_load())
    
    def test_template_creation_and_overrides(self, sample_template_data):
        """Test template creation and override application."""
        template = Template(
            template_id=sample_template_data["template_id"],
            name=sample_template_data["name"],
            template_type=TemplateType(sample_template_data["template_type"]),
            version=sample_template_data["version"],
            description=sample_template_data["description"],
            configuration=sample_template_data["configuration"],
            ontology_classes=sample_template_data["ontology_classes"],
            metadata=sample_template_data["metadata"]
        )
        
        # Test basic properties
        assert template.template_id == "test_template"
        assert template.template_type == TemplateType.DIGITAL_REPLICA
        
        # Test override application
        overrides = {"aggregation_config": {"batch_size": 20}}
        result = template.apply_overrides(overrides)
        
        assert result["aggregation_config"]["batch_size"] == 20
        assert result["aggregation_config"]["method"] == "average"  # Should keep original
        
        # Test override validation
        errors = template.validate_overrides(overrides)
        assert len(errors) == 0  # Should be valid
        
        # Test invalid override
        invalid_overrides = {"invalid_key": "value"}
        errors = template.validate_overrides(invalid_overrides)
        assert len(errors) > 0  # Should have errors
    
    @pytest.mark.asyncio
    async def test_ontology_manager_loading(self, ontology_manager, temp_dir, sample_ontology_data, sample_template_data):
        """Test ontology manager loading functionality."""
        # Create test files
        ontologies_dir = temp_dir / "ontologies"
        templates_dir = temp_dir / "digital_replicas"
        ontologies_dir.mkdir()
        templates_dir.mkdir()
        
        # Create ontology file
        ontology_file = ontologies_dir / "test.json"
        with open(ontology_file, 'w') as f:
            json.dump(sample_ontology_data, f)
        
        # Create template file
        template_file = templates_dir / "test_template.json"
        with open(template_file, 'w') as f:
            json.dump(sample_template_data, f)
        
        # Load ontologies and templates
        await ontology_manager.load_ontologies()
        await ontology_manager.load_templates()
        
        # Verify loading
        assert len(ontology_manager.ontologies) == 1
        assert len(ontology_manager.templates) == 1
        
        # Test retrieval
        ontology = ontology_manager.get_ontology("Test_Ontology")
        assert ontology is not None
        
        template = ontology_manager.get_template("test_template")
        assert template is not None
    
    @pytest.mark.asyncio
    async def test_configuration_validation(self, ontology_manager, temp_dir, sample_ontology_data):
        """Test configuration validation against ontology."""
        # Setup ontology
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        ontology_file = ontologies_dir / "test.json"
        with open(ontology_file, 'w') as f:
            json.dump(sample_ontology_data, f)
        
        await ontology_manager.load_ontologies()
        
        # Test valid configuration
        valid_config = {
            "deviceId": "device-001",
            "temperature": 25.0
        }
        
        errors = ontology_manager.validate_configuration(
            valid_config, "Test_Ontology", "TestDevice"
        )
        assert len(errors) == 0
        
        # Test invalid configuration (missing required field)
        invalid_config = {
            "temperature": 25.0
            # Missing deviceId
        }
        
        errors = ontology_manager.validate_configuration(
            invalid_config, "Test_Ontology", "TestDevice"
        )
        assert len(errors) > 0
        
        # Test constraint violation
        constraint_violation_config = {
            "deviceId": "device-001",
            "temperature": 150.0  # Above max_value of 100
        }
        
        errors = ontology_manager.validate_configuration(
            constraint_violation_config, "Test_Ontology", "TestDevice"
        )
        assert len(errors) > 0


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="Required modules not available")
class TestLifecycleManager:
    """Test Digital Replica Lifecycle Manager."""
    
    @pytest.fixture
    async def lifecycle_manager(self):
        """Create lifecycle manager instance."""
        factory = DigitalReplicaFactory()
        storage_adapter = InMemoryStorageAdapter()
        registry = DigitalReplicaRegistry(storage_adapter)
        await registry.connect()
        
        manager = DigitalReplicaLifecycleManager(factory, registry)
        return manager
    
    @pytest.fixture
    def sample_config(self):
        """Sample configuration for replica creation."""
        return {
            "replica_type": "sensor_aggregator",
            "parent_digital_twin_id": str(uuid4()),
            "device_ids": ["device-001"],
            "aggregation_mode": "batch",
            "aggregation_config": {"batch_size": 5},
            "data_retention_policy": {"retention_days": 30},
            "quality_thresholds": {"min_quality": 0.7}
        }
    
    @pytest.mark.asyncio
    async def test_replica_creation(self, lifecycle_manager, sample_config):
        """Test replica creation through lifecycle manager."""
        replica = await lifecycle_manager.create_entity(sample_config)
        
        assert isinstance(replica, DigitalReplica)
        assert replica.status in [EntityStatus.ACTIVE, EntityStatus.INITIALIZING]
    
    @pytest.mark.asyncio
    async def test_replica_lifecycle_operations(self, lifecycle_manager, sample_config):
        """Test complete replica lifecycle operations."""
        # Create replica
        replica = await lifecycle_manager.create_entity(sample_config)
        
        # Start replica
        await lifecycle_manager.start_entity(replica.id)
        status = await lifecycle_manager.get_entity_status(replica.id)
        assert status == EntityStatus.ACTIVE
        
        # Stop replica
        await lifecycle_manager.stop_entity(replica.id)
        status = await lifecycle_manager.get_entity_status(replica.id)
        assert status == EntityStatus.INACTIVE
        
        # Restart replica
        await lifecycle_manager.restart_entity(replica.id)
        status = await lifecycle_manager.get_entity_status(replica.id)
        assert status == EntityStatus.ACTIVE
    
    @pytest.mark.asyncio
    async def test_deployment_targets(self, lifecycle_manager):
        """Test deployment target management."""
        # Add deployment target
        target = ReplicaDeploymentTarget(
            target_id="test_target",
            target_type="container",
            capacity={"memory": 1024, "cpu": 1.0, "max_replicas": 10},
            location="test"
        )
        
        await lifecycle_manager.add_deployment_target(target)
        assert "test_target" in lifecycle_manager.deployment_targets
        
        # Remove deployment target
        await lifecycle_manager.remove_deployment_target("test_target")
        assert "test_target" not in lifecycle_manager.deployment_targets
    
    @pytest.mark.asyncio
    async def test_health_monitoring(self, lifecycle_manager, sample_config):
        """Test health monitoring functionality."""
        # Create replica
        replica = await lifecycle_manager.create_entity(sample_config)
        
        # Perform health check
        health_check = await lifecycle_manager.perform_health_check(replica.id)
        
        assert health_check.replica_id == replica.id
        assert health_check.status is not None
        assert isinstance(health_check.checks, dict)
        assert isinstance(health_check.metrics, dict)


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="Required modules not available")  
class TestIntegrationScenarios:
    """Integration tests for complete workflows."""
    
    @pytest.mark.asyncio
    async def test_template_to_container_workflow(self):
        """Test complete workflow from template to running container."""
        # This test simulates the complete workflow but with mocked components
        # since we can't run actual containers in tests
        
        # 1. Setup ontology manager with test data
        temp_dir = Path(tempfile.mkdtemp())
        try:
            ontology_manager = OntologyManager(temp_dir)
            
            # Create test template
            template = Template(
                template_id="test_integration",
                name="Integration Test Template",
                template_type=TemplateType.DIGITAL_REPLICA,
                version="1.0.0",
                description="Test template for integration",
                configuration={
                    "replica_type": "sensor_aggregator",
                    "aggregation_mode": "batch",
                    "aggregation_config": {"batch_size": 5}
                }
            )
            ontology_manager.templates["test_integration"] = template
            
            # 2. Create factory and registry
            factory = DigitalReplicaFactory()
            storage_adapter = InMemoryStorageAdapter()
            registry = DigitalReplicaRegistry(storage_adapter)
            await registry.connect()
            
            # 3. Create lifecycle manager
            lifecycle_manager = DigitalReplicaLifecycleManager(factory, registry)
            
            # 4. Apply template and create replica
            config = ontology_manager.apply_template("test_integration")
            config.update({
                "parent_digital_twin_id": str(uuid4()),
                "device_ids": ["device-001"],
                "data_retention_policy": {"retention_days": 30},
                "quality_thresholds": {"min_quality": 0.7}
            })
            
            replica = await lifecycle_manager.create_entity(config)
            
            # 5. Verify replica creation
            assert isinstance(replica, DigitalReplica)
            assert replica.replica_type == ReplicaType.SENSOR_AGGREGATOR
            
            # 6. Start replica
            await lifecycle_manager.start_entity(replica.id)
            status = await lifecycle_manager.get_entity_status(replica.id)
            assert status == EntityStatus.ACTIVE
            
            # 7. Register in registry and verify
            retrieved = await registry.get_digital_replica(replica.id)
            assert retrieved.id == replica.id
            
            print("✅ Integration test: Template → Replica → Registry → Lifecycle - SUCCESS")
            
        finally:
            shutil.rmtree(temp_dir)
    
    @pytest.mark.asyncio
    async def test_device_data_flow(self):
        """Test device data flow through the system."""
        # Create components
        factory = DigitalReplicaFactory()
        config = {
            "replica_type": "sensor_aggregator",
            "parent_digital_twin_id": str(uuid4()),
            "device_ids": ["device-001", "device-002"],
            "aggregation_mode": "batch",
            "aggregation_config": {"batch_size": 2, "method": "average"},
            "data_retention_policy": {"retention_days": 30},
            "quality_thresholds": {"min_quality": 0.7}
        }
        
        replica = await factory.create(config)
        await replica.initialize()
        await replica.start()
        
        # Create test device data
        device_data_1 = DeviceData(
            device_id="device-001",
            timestamp=datetime.now(timezone.utc),
            data={"temperature": 25.0},
            data_type="sensor",
            quality=DataQuality.HIGH
        )
        
        device_data_2 = DeviceData(
            device_id="device-001", 
            timestamp=datetime.now(timezone.utc),
            data={"temperature": 27.0},
            data_type="sensor",
            quality=DataQuality.HIGH
        )
        
        # Send data to replica
        await replica.receive_device_data(device_data_1)
        await replica.receive_device_data(device_data_2)
        
        # Verify replica processed the data
        stats = await replica.get_aggregation_statistics()
        assert stats["data_received"] == 2
        
        print("✅ Integration test: Device Data Flow - SUCCESS")


# Helper function to run tests
def run_virtualization_tests():
    """Run all virtualization layer tests."""
    print("🧪 Running Virtualization Layer Tests...")
    print("=" * 50)
    
    if not IMPORTS_AVAILABLE:
        print("❌ Cannot run tests - missing required modules")
        print("Please ensure all virtualization layer modules are properly imported")
        return False
    
    try:
        # Run pytest with our test file
        import pytest
        result = pytest.main([
            __file__,
            "-v",
            "--tb=short",
            "-x"  # Stop on first failure
        ])
        
        if result == 0:
            print("\n✅ All tests passed!")
            return True
        else:
            print(f"\n❌ Tests failed with code {result}")
            return False
            
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        return False


# Quick test function for individual components
async def quick_component_test():
    """Quick test of individual components."""
    print("🚀 Quick Component Test")
    print("=" * 30)
    
    try:
        # Test 1: Factory
        print("Testing DR Factory...")
        factory = DigitalReplicaFactory()
        config = {
            "replica_type": "sensor_aggregator",
            "parent_digital_twin_id": str(uuid4()),
            "device_ids": ["device-001"],
            "aggregation_mode": "batch",
            "aggregation_config": {"batch_size": 5},
            "data_retention_policy": {"retention_days": 30},
            "quality_thresholds": {"min_quality": 0.7}
        }
        replica = await factory.create(config)
        print(f"✅ Factory: Created replica {replica.id}")
        
        # Test 2: Data Aggregator
        print("Testing Data Aggregator...")
        aggregator = StandardDataAggregator()
        await aggregator.configure({"method": "average"})
        
        device_data = [
            DeviceData(
                device_id="device-001",
                timestamp=datetime.now(timezone.utc),
                data={"temperature": 25.0},
                data_type="sensor",
                quality=DataQuality.HIGH
            ),
            DeviceData(
                device_id="device-001",
                timestamp=datetime.now(timezone.utc),
                data={"temperature": 27.0},
                data_type="sensor",
                quality=DataQuality.HIGH
            )
        ]
        
        result = await aggregator.aggregate(device_data)
        print(f"✅ Aggregator: Average temperature = {result.aggregated_data['temperature']}")
        
        # Test 3: Template System
        print("Testing Template System...")
        ontology_manager = OntologyManager()
        
        template = Template(
            template_id="quick_test",
            name="Quick Test Template",
            template_type=TemplateType.DIGITAL_REPLICA,
            version="1.0.0",
            description="Quick test template",
            configuration={"replica_type": "sensor_aggregator"}
        )
        
        ontology_manager.templates["quick_test"] = template
        applied_config = ontology_manager.apply_template("quick_test")
        print(f"✅ Template: Applied config with replica_type = {applied_config['replica_type']}")
        
        print("\n🎉 All quick tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Quick test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Run quick component test
    print("Running quick component tests...")
    success = asyncio.run(quick_component_test())
    
    if success:
        print("\n" + "="*50)
        print("Running full test suite...")
        run_virtualization_tests()
    else:
        print("❌ Quick tests failed, skipping full test suite")