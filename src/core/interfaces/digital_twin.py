"""
Digital Twin interfaces for the Digital Twin Platform.

This module defines interfaces specific to Digital Twins, which represent
the digital counterparts of physical assets and orchestrate the overall
digital twin behavior through services and replicas.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Union, Callable
from uuid import UUID
from enum import Enum

from .base import IEntity, IFactory, ILifecycleManager, BaseMetadata
from .replica import AggregatedData, IDigitalReplica


class DigitalTwinType(Enum):
    """Types of Digital Twins based on their domain and purpose."""
    ASSET = "asset"                     # Physical asset (machine, building, etc.)
    PROCESS = "process"                 # Business or industrial process
    SYSTEM = "system"                   # System of systems
    ENVIRONMENT = "environment"         # Environmental monitoring
    HUMAN = "human"                     # Human digital twin
    PRODUCT = "product"                 # Product lifecycle twin
    INFRASTRUCTURE = "infrastructure"   # Infrastructure monitoring
    COMPOSITE = "composite"  
    USER = "user"           # Combination of multiple types


class DigitalTwinState(Enum):
    """Operational states specific to Digital Twins."""
    LEARNING = "learning"               # Learning from historical data
    OPERATIONAL = "operational"         # Normal operation mode
    SIMULATION = "simulation"           # Running simulations
    PREDICTION = "prediction"           # Generating predictions
    OPTIMIZATION = "optimization"       # Optimizing operations
    MAINTENANCE = "maintenance"         # Maintenance mode
    DEGRADED = "degraded"              # Operating with limited capability


class TwinModelType(Enum):
    """Types of models that can be integrated into Digital Twins."""
    PHYSICS_BASED = "physics_based"     # Physics simulation models
    DATA_DRIVEN = "data_driven"         # Machine learning models
    HYBRID = "hybrid"                   # Combination of physics and data-driven
    STATISTICAL = "statistical"         # Statistical models
    RULE_BASED = "rule_based"          # Rule-based models
    BEHAVIORAL = "behavioral"           # Behavioral models


class TwinCapability(Enum):
    """Capabilities that a Digital Twin can provide."""
    MONITORING = "monitoring"           # Real-time monitoring
    ANALYTICS = "analytics"             # Data analytics
    PREDICTION = "prediction"           # Predictive analytics
    SIMULATION = "simulation"           # What-if simulations
    OPTIMIZATION = "optimization"       # Operation optimization
    ANOMALY_DETECTION = "anomaly_detection"  # Anomaly detection
    MAINTENANCE_PLANNING = "maintenance_planning"  # Predictive maintenance
    CONTROL = "control"                 # Direct control capabilities


class DigitalTwinConfiguration:
    """Configuration for Digital Twin instances."""
    
    def __init__(
        self,
        twin_type: DigitalTwinType,
        name: str,
        description: str,
        capabilities: Set[TwinCapability],
        model_configurations: Dict[TwinModelType, Dict[str, Any]],
        data_sources: List[str],
        update_frequency: int,  # in seconds
        retention_policy: Dict[str, Any],
        quality_requirements: Dict[str, float],
        custom_config: Optional[Dict[str, Any]] = None
    ):
        self.twin_type = twin_type
        self.name = name
        self.description = description
        self.capabilities = capabilities
        self.model_configurations = model_configurations
        self.data_sources = data_sources
        self.update_frequency = update_frequency
        self.retention_policy = retention_policy
        self.quality_requirements = quality_requirements
        self.custom_config = custom_config or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary representation."""
        return {
            "twin_type": self.twin_type.value,
            "name": self.name,
            "description": self.description,
            "capabilities": [
                        cap.value if hasattr(cap, 'value') else cap 
                    for cap in self.capabilities
                ],
            "model_configurations": {
                model_type.value: config 
                for model_type, config in self.model_configurations.items()
            },
            "data_sources": self.data_sources,
            "update_frequency": self.update_frequency,
            "retention_policy": self.retention_policy,
            "quality_requirements": self.quality_requirements,
            "custom_config": self.custom_config
        }


class TwinModel:
    """Represents a model integrated into a Digital Twin."""
    
    def __init__(
        self,
        model_id: UUID,
        model_type: TwinModelType,
        name: str,
        version: str,
        parameters: Dict[str, Any],
        inputs: List[str],
        outputs: List[str],
        accuracy_metrics: Optional[Dict[str, float]] = None
    ):
        self.model_id = model_id
        self.model_type = model_type
        self.name = name
        self.version = version
        self.parameters = parameters
        self.inputs = inputs
        self.outputs = outputs
        self.accuracy_metrics = accuracy_metrics or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary representation."""
        return {
            "model_id": str(self.model_id),
            "model_type": self.model_type.value,
            "name": self.name,
            "version": self.version,
            "parameters": self.parameters,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "accuracy_metrics": self.accuracy_metrics
        }


class TwinSnapshot:
    """Represents a snapshot of Digital Twin state at a specific time."""
    
    def __init__(
        self,
        twin_id: UUID,
        snapshot_time: datetime,
        state: Dict[str, Any],
        model_states: Dict[UUID, Dict[str, Any]],
        metrics: Dict[str, float],
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.twin_id = twin_id
        self.snapshot_time = snapshot_time
        self.state = state
        self.model_states = model_states
        self.metrics = metrics
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary representation."""
        return {
            "twin_id": str(self.twin_id),
            "snapshot_time": self.snapshot_time.isoformat(),
            "state": self.state,
            "model_states": {str(k): v for k, v in self.model_states.items()},
            "metrics": self.metrics,
            "metadata": self.metadata
        }


class IDigitalTwin(IEntity):
    """
    Interface for Digital Twin entities.
    
    Digital Twins represent the digital counterparts of physical assets,
    processes, or systems. They orchestrate data from replicas, execute
    models, and provide insights and predictions.
    """
    
    @property
    @abstractmethod
    def twin_type(self) -> DigitalTwinType:
        """Get the type of this Digital Twin."""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Get the human-readable name of the Digital Twin."""
        pass
    
    @property
    @abstractmethod
    def configuration(self) -> DigitalTwinConfiguration:
        """Get the current configuration of the Digital Twin."""
        pass
    
    @property
    @abstractmethod
    def current_state(self) -> DigitalTwinState:
        """Get the current operational state of the Digital Twin."""
        pass
    
    @property
    @abstractmethod
    def capabilities(self) -> Set[TwinCapability]:
        """Get the capabilities provided by this Digital Twin."""
        pass
    
    @property
    @abstractmethod
    def associated_replicas(self) -> List[UUID]:
        """Get the list of Digital Replica IDs associated with this twin."""
        pass
    
    @property
    @abstractmethod
    def integrated_models(self) -> List[TwinModel]:
        """Get the list of models integrated into this Digital Twin."""
        pass
    
    @abstractmethod
    async def receive_aggregated_data(self, data: AggregatedData) -> None:
        """
        Receive aggregated data from a Digital Replica.
        
        Args:
            data: Aggregated data from a replica
        """
        pass
    
    @abstractmethod
    async def update_state(self, new_data: Dict[str, Any]) -> None:
        """
        Update the Digital Twin's internal state with new data.
        
        Args:
            new_data: New data to incorporate into the state
        """
        pass
    
    @abstractmethod
    async def execute_models(
        self,
        model_ids: Optional[List[UUID]] = None,
        input_data: Optional[Dict[str, Any]] = None
    ) -> Dict[UUID, Dict[str, Any]]:
        """
        Execute specified models or all available models.
        
        Args:
            model_ids: Specific model IDs to execute (None for all)
            input_data: Optional input data for model execution
            
        Returns:
            Dictionary mapping model IDs to their execution results
        """
        pass
    
    @abstractmethod
    async def add_model(self, model: TwinModel) -> None:
        """
        Add a new model to the Digital Twin.
        
        Args:
            model: Model to add
        """
        pass
    
    @abstractmethod
    async def remove_model(self, model_id: UUID) -> None:
        """
        Remove a model from the Digital Twin.
        
        Args:
            model_id: ID of the model to remove
        """
        pass
    
    @abstractmethod
    async def update_model(self, model: TwinModel) -> None:
        """
        Update an existing model in the Digital Twin.
        
        Args:
            model: Updated model configuration
        """
        pass
    
    @abstractmethod
    async def associate_replica(self, replica_id: UUID) -> None:
        """
        Associate a Digital Replica with this Digital Twin.
        
        Args:
            replica_id: ID of the replica to associate
        """
        pass
    
    @abstractmethod
    async def disassociate_replica(self, replica_id: UUID) -> None:
        """
        Disassociate a Digital Replica from this Digital Twin.
        
        Args:
            replica_id: ID of the replica to disassociate
        """
        pass
    
    @abstractmethod
    async def create_snapshot(self) -> TwinSnapshot:
        """
        Create a snapshot of the current Digital Twin state.
        
        Returns:
            Snapshot of the current state
        """
        pass
    
    @abstractmethod
    async def restore_from_snapshot(self, snapshot: TwinSnapshot) -> None:
        """
        Restore the Digital Twin state from a snapshot.
        
        Args:
            snapshot: Snapshot to restore from
        """
        pass
    
    @abstractmethod
    async def get_performance_metrics(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Get performance metrics for the specified time range.
        
        Args:
            start_time: Start of the time range (None for all-time)
            end_time: End of the time range (None for current time)
            
        Returns:
            Performance metrics dictionary
        """
        pass
    
    @abstractmethod
    async def predict(
        self,
        prediction_horizon: int,
        scenario: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate predictions for the specified time horizon.
        
        Args:
            prediction_horizon: Time horizon for predictions (in seconds)
            scenario: Optional scenario parameters for prediction
            
        Returns:
            Prediction results
        """
        pass
    
    @abstractmethod
    async def simulate(
        self,
        simulation_config: Dict[str, Any],
        duration: int
    ) -> Dict[str, Any]:
        """
        Run a simulation with the specified configuration.
        
        Args:
            simulation_config: Configuration for the simulation
            duration: Simulation duration (in seconds)
            
        Returns:
            Simulation results
        """
        pass
    
    @abstractmethod
    async def optimize(
        self,
        optimization_target: str,
        constraints: Dict[str, Any],
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Perform optimization for the specified target.
        
        Args:
            optimization_target: Target to optimize
            constraints: Optimization constraints
            parameters: Optimization parameters
            
        Returns:
            Optimization results
        """
        pass


class IDigitalTwinFactory(IFactory[IDigitalTwin]):
    """
    Factory interface for creating Digital Twin instances.
    
    Handles the creation and configuration of Digital Twins
    based on provided specifications and templates.
    """
    
    @abstractmethod
    async def create_twin(
        self,
        twin_type: DigitalTwinType,
        config: DigitalTwinConfiguration,
        models: Optional[List[TwinModel]] = None,
        metadata: Optional[BaseMetadata] = None
    ) -> IDigitalTwin:
        """
        Create a new Digital Twin instance.
        
        Args:
            twin_type: Type of Digital Twin to create
            config: Digital Twin configuration
            models: Optional list of models to integrate
            metadata: Optional metadata for the twin
            
        Returns:
            Created Digital Twin instance
        """
        pass
    
    @abstractmethod
    async def create_from_template(
        self,
        template_name: str,
        customization: Optional[Dict[str, Any]] = None,
        metadata: Optional[BaseMetadata] = None
    ) -> IDigitalTwin:
        """
        Create a Digital Twin from a predefined template.
        
        Args:
            template_name: Name of the template to use
            customization: Optional customization parameters
            metadata: Optional metadata for the twin
            
        Returns:
            Created Digital Twin instance
        """
        pass
    
    @abstractmethod
    def get_supported_twin_types(self) -> List[DigitalTwinType]:
        """Get the list of Digital Twin types this factory can create."""
        pass
    
    @abstractmethod
    def get_available_templates(self) -> List[str]:
        """Get the list of available Digital Twin templates."""
        pass
    
    @abstractmethod
    def get_template_schema(self, template_name: str) -> Dict[str, Any]:
        """Get the schema for a specific template."""
        pass
    
    @abstractmethod
    def validate_twin_config(
        self,
        twin_type: DigitalTwinType,
        config: DigitalTwinConfiguration
    ) -> bool:
        """Validate a Digital Twin configuration for the specified type."""
        pass


class IDigitalTwinLifecycleManager(ILifecycleManager[IDigitalTwin]):
    """
    Lifecycle manager interface for Digital Twins.
    
    Manages the complete lifecycle of Digital Twins including
    creation, composition, evolution, and retirement.
    """
    
    @abstractmethod
    async def compose_twin(
        self,
        base_twin_id: UUID,
        component_twin_ids: List[UUID],
        composition_rules: Dict[str, Any]
    ) -> UUID:
        """
        Compose a new Digital Twin from existing twins.
        
        Args:
            base_twin_id: ID of the base Digital Twin
            component_twin_ids: IDs of component Digital Twins
            composition_rules: Rules for composition
            
        Returns:
            ID of the composed Digital Twin
        """
        pass
    
    @abstractmethod
    async def decompose_twin(
        self,
        composite_twin_id: UUID,
        decomposition_strategy: str
    ) -> List[UUID]:
        """
        Decompose a composite Digital Twin into components.
        
        Args:
            composite_twin_id: ID of the composite twin to decompose
            decomposition_strategy: Strategy for decomposition
            
        Returns:
            List of component Digital Twin IDs
        """
        pass
    
    @abstractmethod
    async def evolve_twin(
        self,
        twin_id: UUID,
        evolution_config: Dict[str, Any]
    ) -> None:
        """
        Evolve a Digital Twin based on learned patterns and feedback.
        
        Args:
            twin_id: ID of the twin to evolve
            evolution_config: Configuration for evolution
        """
        pass
    
    @abstractmethod
    async def clone_twin(
        self,
        source_twin_id: UUID,
        customization: Optional[Dict[str, Any]] = None
    ) -> UUID:
        """
        Clone a Digital Twin with optional customization.
        
        Args:
            source_twin_id: ID of the twin to clone
            customization: Optional customization for the clone
            
        Returns:
            ID of the cloned Digital Twin
        """
        pass
    
    @abstractmethod
    async def export_twin(
        self,
        twin_id: UUID,
        export_format: str,
        include_dependencies: bool = True
    ) -> str:
        """
        Export a Digital Twin with all its dependencies.
        
        Args:
            twin_id: ID of the twin to export
            export_format: Format for export (e.g., 'json', 'yaml')
            include_dependencies: Whether to include dependencies
            
        Returns:
            Export reference or path
        """
        pass
    
    @abstractmethod
    async def import_twin(
        self,
        import_reference: str,
        import_format: str,
        conflict_resolution: str = "error"
    ) -> UUID:
        """
        Import a Digital Twin from an export.
        
        Args:
            import_reference: Reference to the import data
            import_format: Format of the import data
            conflict_resolution: How to handle conflicts ("error", "skip", "overwrite")
            
        Returns:
            ID of the imported Digital Twin
        """
        pass


# Type alias for Digital Twin event handlers
DigitalTwinEventHandler = Callable[[UUID, str, Dict[str, Any]], None]


class IDigitalTwinOrchestrator(ABC):
    """
    Interface for Digital Twin orchestration and coordination.
    
    Handles coordination between multiple Digital Twins and manages
    cross-twin operations and interactions.
    """
    
    @abstractmethod
    async def register_twin(self, twin: IDigitalTwin) -> None:
        """
        Register a Digital Twin with the orchestrator.
        
        Args:
            twin: Digital Twin to register
        """
        pass
    
    @abstractmethod
    async def unregister_twin(self, twin_id: UUID) -> None:
        """
        Unregister a Digital Twin from the orchestrator.
        
        Args:
            twin_id: ID of the twin to unregister
        """
        pass
    
    @abstractmethod
    async def coordinate_twins(
        self,
        twin_ids: List[UUID],
        coordination_type: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Coordinate operations across multiple Digital Twins.
        
        Args:
            twin_ids: IDs of twins to coordinate
            coordination_type: Type of coordination to perform
            parameters: Coordination parameters
            
        Returns:
            Coordination results
        """
        pass
    
    @abstractmethod
    async def synchronize_twins(
        self,
        twin_ids: List[UUID],
        sync_strategy: str
    ) -> None:
        """
        Synchronize state across multiple Digital Twins.
        
        Args:
            twin_ids: IDs of twins to synchronize
            sync_strategy: Strategy for synchronization
        """
        pass
    
    @abstractmethod
    async def global_optimization(
        self,
        objective: str,
        constraints: Dict[str, Any],
        twin_scope: Optional[List[UUID]] = None
    ) -> Dict[str, Any]:
        """
        Perform global optimization across multiple Digital Twins.
        
        Args:
            objective: Optimization objective
            constraints: Global constraints
            twin_scope: Scope of twins to include (None for all)
            
        Returns:
            Global optimization results
        """
        pass