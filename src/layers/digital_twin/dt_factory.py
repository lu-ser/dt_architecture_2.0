"""
Digital Twin Factory implementation for the Digital Twin Platform.

This module provides the factory for creating Digital Twin instances
based on type and configuration, integrating services and replicas.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Type
from uuid import UUID, uuid4
from pathlib import Path
from src.core.interfaces.base import BaseMetadata, EntityStatus
from src.core.interfaces.digital_twin import (
    IDigitalTwin,
    IDigitalTwinFactory,
    DigitalTwinType,
    DigitalTwinState,
    DigitalTwinConfiguration,
    TwinModelType,
    TwinModel,
    TwinSnapshot,
    TwinCapability
)
from src.core.interfaces.replica import AggregatedData
from src.utils.exceptions import (
    FactoryError,
    FactoryConfigurationError,
    EntityCreationError,
    DigitalTwinError
)
from src.utils.config import get_config
from enum import Enum
logger = logging.getLogger(__name__)

class DTAccessLevel(Enum):
    NONE = "none"
    READ = "read" 
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"
class StandardDigitalTwin(IDigitalTwin):
    def __init__(self, twin_id: UUID, configuration: DigitalTwinConfiguration, 
                    metadata: BaseMetadata, models: Optional[List[TwinModel]] = None,
                    owner_id: Optional[UUID] = None, tenant_id: Optional[UUID] = None,
                    security_enabled: bool = False):
            self._id = twin_id
            self._configuration = configuration
            self._metadata = metadata
            self._current_state = DigitalTwinState.LEARNING
            self._status = EntityStatus.CREATED
            
            # Model management
            self._integrated_models: Dict[UUID, TwinModel] = {}
            if models:
                for model in models:
                    self._integrated_models[model.model_id] = model
            
            # Replica associations
            self._associated_replicas: Set[UUID] = set()
            
            # Internal state
            self._twin_state: Dict[str, Any] = {}
            self._last_update: Optional[datetime] = None
            
            # Performance tracking
            self._model_executions = 0
            self._data_updates = 0
            self._predictions_made = 0
            self._last_prediction: Optional[datetime] = None
            
            # Data processing
            self._data_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
            self._processing_task: Optional[asyncio.Task] = None
            self.security_enabled = security_enabled
            
            if security_enabled:
                # Sicurezza abilitata
                self.owner_id = owner_id or uuid4()  # Fallback se non specificato
                self.tenant_id = tenant_id or uuid4()  # Fallback se non specificato
                self.authorized_users: Dict[UUID, DTAccessLevel] = {self.owner_id: DTAccessLevel.ADMIN}
                self.access_permissions: Dict[UUID, Set[str]] = {
                    self.owner_id: {"read", "write", "execute", "admin", "manage_access"}
                }
                self.access_log: List[Dict[str, Any]] = []
                self.last_accessed_by: Optional[UUID] = None
                self.is_public = False
                self.shared_with_tenant = True
                self.dt_identity: Optional[Any] = None  # Will be set during initialization
            else:
                # Modalità legacy - nessun controllo di sicurezza
                self.owner_id = owner_id
                self.tenant_id = tenant_id
                self.authorized_users = {}
                self.access_permissions = {}
                self.access_log = []
                self.last_accessed_by = None
                self.is_public = True
                self.shared_with_tenant = True
                self.dt_identity = None


    
    @property
    def id(self) -> UUID:
        return self._id
    
    @property
    def metadata(self) -> BaseMetadata:
        return self._metadata
    
    @property
    def status(self) -> EntityStatus:
        return self._status
    
    @property
    def twin_type(self) -> DigitalTwinType:
        return self._configuration.twin_type
    
    @property
    def name(self) -> str:
        return self._configuration.name
    
    @property
    def configuration(self) -> DigitalTwinConfiguration:
        return self._configuration
    
    @property
    def current_state(self) -> DigitalTwinState:
        return self._current_state
    
    @property
    def capabilities(self) -> Set[TwinCapability]:
        return self._configuration.capabilities
    
    @property
    def associated_replicas(self) -> List[UUID]:
        return list(self._associated_replicas)
    
    @property
    def integrated_models(self) -> List[TwinModel]:
        return list(self._integrated_models.values())
    
    def check_access(self, user_id: UUID, required_access: DTAccessLevel) -> bool:
        """Check if user has required access level"""
        if not self.security_enabled:
            return True  # Legacy mode - accesso libero
            
        if user_id == self.owner_id:
            return True
            
        user_access = self.authorized_users.get(user_id, DTAccessLevel.NONE)
        
        # Access hierarchy: ADMIN > EXECUTE > WRITE > READ > NONE
        access_hierarchy = {
            DTAccessLevel.ADMIN: 4,
            DTAccessLevel.EXECUTE: 3, 
            DTAccessLevel.WRITE: 2,
            DTAccessLevel.READ: 1,
            DTAccessLevel.NONE: 0
        }
        
        return access_hierarchy[user_access] >= access_hierarchy[required_access]
    
    def grant_access(self, user_id: UUID, access_level: DTAccessLevel, granted_by: UUID) -> None:
        """Grant access to user (only if security enabled)"""
        if not self.security_enabled:
            logger.warning(f"Attempted to grant access on non-secure twin {self._id}")
            return
            
        if not (granted_by == self.owner_id or 
                self.authorized_users.get(granted_by) == DTAccessLevel.ADMIN):
            raise PermissionError("Only owner or admin can grant access")
            
        self.authorized_users[user_id] = access_level
        
        # Set permissions based on access level
        permissions = set()
        if access_level in [DTAccessLevel.READ, DTAccessLevel.WRITE, 
                           DTAccessLevel.EXECUTE, DTAccessLevel.ADMIN]:
            permissions.add("read")
        if access_level in [DTAccessLevel.WRITE, DTAccessLevel.EXECUTE, DTAccessLevel.ADMIN]:
            permissions.add("write") 
        if access_level in [DTAccessLevel.EXECUTE, DTAccessLevel.ADMIN]:
            permissions.add("execute")
        if access_level == DTAccessLevel.ADMIN:
            permissions.update({"admin", "manage_access"})
            
        self.access_permissions[user_id] = permissions
        self._log_access_change("grant", user_id, access_level, granted_by)
    
    def revoke_access(self, user_id: UUID, revoked_by: UUID) -> None:
        """Revoke user access"""
        if not self.security_enabled:
            return
            
        if user_id == self.owner_id:
            raise PermissionError("Cannot revoke owner access")
            
        if not (revoked_by == self.owner_id or 
                self.authorized_users.get(revoked_by) == DTAccessLevel.ADMIN):
            raise PermissionError("Only owner or admin can revoke access")
            
        self.authorized_users.pop(user_id, None)
        self.access_permissions.pop(user_id, None)
        self._log_access_change("revoke", user_id, DTAccessLevel.NONE, revoked_by)
    
    def log_access(self, user_id: UUID, operation: str, success: bool = True) -> None:
        """Log access attempt"""
        if not self.security_enabled:
            return
            
        self.last_accessed_by = user_id
        
        log_entry = {
            "user_id": str(user_id),
            "operation": operation, 
            "success": success,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_access_level": self.authorized_users.get(user_id, DTAccessLevel.NONE).value
        }
        
        self.access_log.append(log_entry)
        
        # Keep only last 100 entries
        if len(self.access_log) > 100:
            self.access_log = self.access_log[-100:]
    
    def is_accessible_by_tenant_user(self, user_id: UUID, user_tenant_id: UUID) -> bool:
        """Check if user from tenant can access this twin"""
        if not self.security_enabled:
            return True
            
        if not self.tenant_id or user_tenant_id != self.tenant_id:
            return False
            
        # Check if explicitly authorized
        if user_id in self.authorized_users:
            return True
            
        # Check tenant-wide sharing settings
        return self.shared_with_tenant
    
    def _log_access_change(self, action: str, target_user: UUID, 
                          access_level: DTAccessLevel, changed_by: UUID) -> None:
        """Log access permission changes"""
        if not self.security_enabled:
            return
            
        log_entry = {
            "action": action,
            "target_user": str(target_user),
            "access_level": access_level.value,
            "changed_by": str(changed_by),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self.access_log.append(log_entry)
    async def initialize(self) -> None:
        """Initialize the Digital Twin."""
        self._status = EntityStatus.INITIALIZING
        self._current_state = DigitalTwinState.LEARNING
        
        for model in self._integrated_models.values():
            await self._initialize_model(model)
        
        # Create Digital Twin identity if security enabled
        if self.security_enabled and self.owner_id and self.tenant_id:
            try:
                from src.layers.application.auth.user_registration import DigitalTwinIdentityService
                identity_service = DigitalTwinIdentityService()
                self.dt_identity = await identity_service.create_identity(
                    twin_id=self._id,
                    owner_id=self.owner_id, 
                    tenant_id=self.tenant_id
                )
                logger.info(f'Created Digital Twin identity for {self._id}')
            except Exception as e:
                logger.warning(f'Failed to create DT identity: {e}')
        
        await self._start_data_processing()
        self._status = EntityStatus.ACTIVE
        self._current_state = DigitalTwinState.OPERATIONAL
        
        logger.info(f'Digital Twin {self._id} ({self.twin_type.value}) initialized (security: {self.security_enabled})')
    
    async def start(self) -> None:
        """Start the Digital Twin operations."""
        if self._current_state not in [DigitalTwinState.OPERATIONAL, DigitalTwinState.MAINTENANCE]:
            await self.initialize()
        
        self._status = EntityStatus.ACTIVE
        self._current_state = DigitalTwinState.OPERATIONAL
        
        # Start data processing if not already running
        if not self._processing_task or self._processing_task.done():
            await self._start_data_processing()
        
        logger.info(f"Digital Twin {self._id} started")
    
    async def stop(self) -> None:
        """Stop the Digital Twin operations."""
        self._status = EntityStatus.INACTIVE
        self._current_state = DigitalTwinState.MAINTENANCE
        
        # Stop data processing
        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass
        
        logger.info(f"Digital Twin {self._id} stopped")
    
    async def terminate(self) -> None:
        """Terminate the Digital Twin."""
        await self.stop()
        
        # Clear all data
        self._twin_state.clear()
        self._integrated_models.clear()
        self._associated_replicas.clear()
        
        self._status = EntityStatus.TERMINATED
        self._current_state = DigitalTwinState.OPERATIONAL  # Reset state
        
        logger.info(f"Digital Twin {self._id} terminated")
    
    async def receive_aggregated_data(self, data: AggregatedData) -> None:
        """Receive aggregated data from a Digital Replica."""
        try:
            # Add to processing queue
            await self._data_queue.put(data)
            logger.debug(f"Received aggregated data from replica {data.source_replica_id}")
        except asyncio.QueueFull:
            logger.warning(f"Data queue full, dropping data from replica {data.source_replica_id}")
    
    async def update_state(self, new_data: Dict[str, Any]) -> None:
        """Update the Digital Twin's internal state with new data."""
        # Merge new data with existing state
        self._twin_state.update(new_data)
        self._last_update = datetime.now(timezone.utc)
        self._data_updates += 1
        
        # Trigger model updates based on configuration
        update_frequency = self._configuration.update_frequency
        if self._data_updates % max(update_frequency, 1) == 0:
            await self._trigger_model_updates()
        
        logger.debug(f"Updated Digital Twin {self._id} state with {len(new_data)} data points")
    
    async def execute_models(
        self,
        model_ids: Optional[List[UUID]] = None,
        input_data: Optional[Dict[str, Any]] = None
    ) -> Dict[UUID, Dict[str, Any]]:
        """Execute specified models or all available models."""
        if model_ids is None:
            model_ids = list(self._integrated_models.keys())
        
        execution_data = input_data or self._twin_state
        results = {}
        
        for model_id in model_ids:
            if model_id in self._integrated_models:
                model = self._integrated_models[model_id]
                try:
                    result = await self._execute_model(model, execution_data)
                    results[model_id] = result
                    self._model_executions += 1
                    logger.debug(f"Executed model {model.name} for Digital Twin {self._id}")
                except Exception as e:
                    logger.error(f"Model execution failed for {model.name}: {e}")
                    results[model_id] = {"error": str(e)}
        
        return results
    
    async def add_model(self, model: TwinModel) -> None:
        """Add a new model to the Digital Twin."""
        self._integrated_models[model.model_id] = model
        await self._initialize_model(model)
        logger.info(f"Added model {model.name} to Digital Twin {self._id}")
    
    async def remove_model(self, model_id: UUID) -> None:
        """Remove a model from the Digital Twin."""
        if model_id in self._integrated_models:
            model_name = self._integrated_models[model_id].name
            del self._integrated_models[model_id]
            logger.info(f"Removed model {model_name} from Digital Twin {self._id}")
    
    async def update_model(self, model: TwinModel) -> None:
        """Update an existing model in the Digital Twin."""
        if model.model_id in self._integrated_models:
            self._integrated_models[model.model_id] = model
            await self._initialize_model(model)
            logger.info(f"Updated model {model.name} in Digital Twin {self._id}")
    
    async def associate_replica(self, replica_id: UUID) -> None:
        """Associate a Digital Replica with this Digital Twin."""
        self._associated_replicas.add(replica_id)
        logger.info(f"Associated replica {replica_id} with Digital Twin {self._id}")
    
    async def disassociate_replica(self, replica_id: UUID) -> None:
        """Disassociate a Digital Replica from this Digital Twin."""
        self._associated_replicas.discard(replica_id)
        logger.info(f"Disassociated replica {replica_id} from Digital Twin {self._id}")
    
    async def create_snapshot(self) -> TwinSnapshot:
        """Create a snapshot of the current Digital Twin state."""
        # Capture model states
        model_states = {}
        for model_id, model in self._integrated_models.items():
            model_states[model_id] = {
                "parameters": model.parameters,
                "accuracy_metrics": model.accuracy_metrics,
                "last_trained": datetime.now(timezone.utc).isoformat()
            }
        
        # Calculate current metrics
        metrics = {
            "model_executions": self._model_executions,
            "data_updates": self._data_updates,
            "predictions_made": self._predictions_made,
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "state_size": len(self._twin_state),
            "associated_replicas_count": len(self._associated_replicas)
        }
        
        snapshot = TwinSnapshot(
            twin_id=self._id,
            snapshot_time=datetime.now(timezone.utc),
            state=self._twin_state.copy(),
            model_states=model_states,
            metrics=metrics,
            metadata={
                "twin_type": self.twin_type.value,
                "current_state": self._current_state.value,
                "capabilities": [cap.value for cap in self.capabilities]
            }
        )
        
        logger.info(f"Created snapshot for Digital Twin {self._id}")
        return snapshot
    
    async def restore_from_snapshot(self, snapshot: TwinSnapshot) -> None:
        """Restore the Digital Twin state from a snapshot."""
        if snapshot.twin_id != self._id:
            raise DigitalTwinError(f"Snapshot twin ID {snapshot.twin_id} does not match current twin {self._id}")
        
        # Restore state
        self._twin_state = snapshot.state.copy()
        
        # Restore model states
        for model_id, model_state in snapshot.model_states.items():
            if model_id in self._integrated_models:
                model = self._integrated_models[model_id]
                model.parameters.update(model_state.get("parameters", {}))
                model.accuracy_metrics.update(model_state.get("accuracy_metrics", {}))
        
        # Restore metrics
        metrics = snapshot.metrics
        self._model_executions = metrics.get("model_executions", 0)
        self._data_updates = metrics.get("data_updates", 0)
        self._predictions_made = metrics.get("predictions_made", 0)
        
        self._last_update = datetime.now(timezone.utc)
        
        logger.info(f"Restored Digital Twin {self._id} from snapshot")
    
    async def get_performance_metrics(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get performance metrics for the specified time range."""
        return {
            "twin_id": str(self._id),
            "twin_type": self.twin_type.value,
            "current_state": self._current_state.value,
            "model_executions": self._model_executions,
            "data_updates": self._data_updates,
            "predictions_made": self._predictions_made,
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "last_prediction": self._last_prediction.isoformat() if self._last_prediction else None,
            "state_size": len(self._twin_state),
            "integrated_models_count": len(self._integrated_models),
            "associated_replicas_count": len(self._associated_replicas),
            "queue_size": self._data_queue.qsize() if self._data_queue else 0,
            "capabilities": [cap.value for cap in self.capabilities]
        }
    
    async def predict(
        self,
        prediction_horizon: int,
        scenario: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Generate predictions for the specified time horizon."""
        prediction_models = [
            model for model in self._integrated_models.values()
            if model.model_type in [TwinModelType.DATA_DRIVEN, TwinModelType.HYBRID]
        ]
        
        if not prediction_models:
            return {"error": "No prediction models available"}
        
        predictions = {}
        
        for model in prediction_models:
            try:
                # Prepare input data
                input_data = self._twin_state.copy()
                if scenario:
                    input_data.update(scenario)
                
                # Execute prediction model
                result = await self._execute_prediction_model(model, input_data, prediction_horizon)
                predictions[model.name] = result
                
            except Exception as e:
                logger.error(f"Prediction failed for model {model.name}: {e}")
                predictions[model.name] = {"error": str(e)}
        
        self._predictions_made += 1
        self._last_prediction = datetime.now(timezone.utc)
        
        return {
            "prediction_horizon_seconds": prediction_horizon,
            "predicted_at": self._last_prediction.isoformat(),
            "scenario": scenario,
            "predictions": predictions,
            "confidence": self._calculate_prediction_confidence(predictions)
        }
    
    async def simulate(
        self,
        simulation_config: Dict[str, Any],
        duration: int
    ) -> Dict[str, Any]:
        """Run a simulation with the specified configuration."""
        simulation_models = [
            model for model in self._integrated_models.values()
            if model.model_type in [TwinModelType.PHYSICS_BASED, TwinModelType.HYBRID]
        ]
        
        if not simulation_models:
            return {"error": "No simulation models available"}
        
        simulation_results = {}
        
        for model in simulation_models:
            try:
                # Execute simulation
                result = await self._execute_simulation_model(model, simulation_config, duration)
                simulation_results[model.name] = result
                
            except Exception as e:
                logger.error(f"Simulation failed for model {model.name}: {e}")
                simulation_results[model.name] = {"error": str(e)}
        
        return {
            "simulation_duration_seconds": duration,
            "simulation_config": simulation_config,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "results": simulation_results
        }
    
    async def optimize(
        self,
        optimization_target: str,
        constraints: Dict[str, Any],
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Perform optimization for the specified target."""
        # This would integrate with optimization services
        # For now, return a mock optimization result
        
        return {
            "optimization_target": optimization_target,
            "constraints": constraints,
            "parameters": parameters,
            "optimized_values": {
                "target_value": 0.85,  # Mock optimized value
                "optimal_parameters": parameters,
                "improvement": 0.15
            },
            "optimization_time_seconds": 5.0,
            "iterations": 100,
            "converged": True,
            "executed_at": datetime.now(timezone.utc).isoformat()
        }
    
    def to_dict(self, include_security_details: bool = False) -> Dict[str, Any]:
        """Enhanced to_dict with optional security information"""
        base_dict = {
            'id': str(self._id),
            'twin_type': self.twin_type.value,
            'name': self.name,
            'description': self._configuration.description,
            'current_state': self._current_state.value,
            'status': self._status.value,
            'capabilities': [cap.value for cap in self.capabilities],
            'configuration': self._configuration.to_dict(),
            'metadata': self._metadata.to_dict(),
            'integrated_models': [model.to_dict() for model in self._integrated_models.values()],
            'associated_replicas': [str(rid) for rid in self._associated_replicas],
            'statistics': {
                'model_executions': self._model_executions,
                'data_updates': self._data_updates,
                'predictions_made': self._predictions_made,
                'last_update': self._last_update.isoformat() if self._last_update else None
            }
        }
        # Add security info if enabled
        if self.security_enabled:
            base_dict.update({
                "security_enabled": True,
                "owner_id": str(self.owner_id) if self.owner_id else None,
                "tenant_id": str(self.tenant_id) if self.tenant_id else None,
                "is_public": self.is_public,
                "shared_with_tenant": self.shared_with_tenant,
                "authorized_users_count": len(self.authorized_users),
                "last_accessed_by": str(self.last_accessed_by) if self.last_accessed_by else None
            })
            
            # Include detailed security info if requested
            if include_security_details:
                base_dict.update({
                    "authorized_users": {
                        str(uid): level.value for uid, level in self.authorized_users.items()
                    },
                    "access_permissions": {
                        str(uid): list(perms) for uid, perms in self.access_permissions.items()
                    },
                    "recent_access_log": self.access_log[-10:] if self.access_log else [],
                    "dt_identity": self.dt_identity.to_dict() if self.dt_identity else None
                })
        else:
            base_dict["security_enabled"] = False
            
        return base_dict
        
    def validate(self) -> bool:
        """Validate the Digital Twin configuration and state."""
        try:
            # Validate required fields
            if not self._configuration.name:
                return False
            if not self._configuration.capabilities:
                return False
            if self._configuration.update_frequency <= 0:
                return False
            
            return True
        except Exception:
            return False
    
    # Private helper methods
    async def _start_data_processing(self) -> None:
        """Start background data processing task."""
        async def process_data():
            while True:
                try:
                    # Get data from queue
                    data = await asyncio.wait_for(self._data_queue.get(), timeout=1.0)
                    
                    # Process aggregated data
                    await self._process_aggregated_data(data)
                    self._data_queue.task_done()
                    
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Data processing error in Digital Twin {self._id}: {e}")
        
        self._processing_task = asyncio.create_task(process_data())
    
    async def _process_aggregated_data(self, data: AggregatedData) -> None:
        """Process aggregated data from replicas."""
        # Extract relevant data
        new_state_data = {}
        
        for key, value in data.aggregated_data.items():
            # Apply data quality considerations
            if data.quality_score >= 0.7:  # Only use high-quality data
                new_state_data[f"replica_{data.source_replica_id}_{key}"] = value
        
        # Update state
        if new_state_data:
            await self.update_state(new_state_data)
    
    async def _trigger_model_updates(self) -> None:
        """Trigger model updates based on new data."""
        # Execute models that need regular updates
        auto_update_models = [
            model for model in self._integrated_models.values()
            if model.model_type == TwinModelType.DATA_DRIVEN
        ]
        
        if auto_update_models:
            model_ids = [model.model_id for model in auto_update_models]
            await self.execute_models(model_ids)
    
    async def _initialize_model(self, model: TwinModel) -> None:
        """Initialize a model."""
        # Model-specific initialization logic
        logger.debug(f"Initialized model {model.name} ({model.model_type.value})")
    
    async def _execute_model(self, model: TwinModel, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a specific model."""
        # Simulate model execution based on type
        if model.model_type == TwinModelType.PHYSICS_BASED:
            return await self._execute_physics_model(model, input_data)
        elif model.model_type == TwinModelType.DATA_DRIVEN:
            return await self._execute_ml_model(model, input_data)
        elif model.model_type == TwinModelType.HYBRID:
            physics_result = await self._execute_physics_model(model, input_data)
            ml_result = await self._execute_ml_model(model, input_data)
            return {"physics": physics_result, "ml": ml_result}
        else:
            return {"result": "Model executed", "model_type": model.model_type.value}
    
    async def _execute_physics_model(self, model: TwinModel, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a physics-based model."""
        # Simulate physics calculation
        await asyncio.sleep(0.1)  # Simulate computation time
        
        return {
            "model_type": "physics_based",
            "calculated_values": {
                "temperature": 25.5,
                "pressure": 101.3,
                "efficiency": 0.87
            },
            "computation_time": 0.1
        }
    
    async def _execute_ml_model(self, model: TwinModel, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a machine learning model."""
        # Simulate ML inference
        await asyncio.sleep(0.05)  # Simulate inference time
        
        return {
            "model_type": "data_driven",
            "predictions": {
                "next_value": 42.0,
                "confidence": 0.85,
                "trend": "increasing"
            },
            "inference_time": 0.05
        }
    
    async def _execute_prediction_model(
        self,
        model: TwinModel,
        input_data: Dict[str, Any],
        horizon: int
    ) -> Dict[str, Any]:
        """Execute a prediction model."""
        # Simulate prediction
        await asyncio.sleep(0.2)
        
        return {
            "predicted_value": 50.0 + (horizon / 100),  # Simple trend
            "confidence": 0.8,
            "prediction_interval": [45.0, 55.0],
            "horizon_seconds": horizon
        }
    
    async def _execute_simulation_model(
        self,
        model: TwinModel,
        config: Dict[str, Any],
        duration: int
    ) -> Dict[str, Any]:
        """Execute a simulation model."""
        # Simulate simulation
        await asyncio.sleep(0.5)
        
        return {
            "simulation_steps": duration // 10,
            "final_state": {"value": 100.0, "status": "stable"},
            "trajectory": [i * 10 for i in range(duration // 10)],
            "duration_seconds": duration
        }
    
    def _calculate_prediction_confidence(self, predictions: Dict[str, Any]) -> float:
        """Calculate overall prediction confidence."""
        confidences = []
        for prediction in predictions.values():
            if isinstance(prediction, dict) and "confidence" in prediction:
                confidences.append(prediction["confidence"])
        
        return sum(confidences) / len(confidences) if confidences else 0.5


class DigitalTwinFactory(IDigitalTwinFactory):
    """Factory for creating Digital Twin instances."""
    
    def __init__(self):
        self.config = get_config()
        self._supported_types = [
            DigitalTwinType.ASSET,
            DigitalTwinType.PROCESS,
            DigitalTwinType.SYSTEM,
            DigitalTwinType.INFRASTRUCTURE,
            DigitalTwinType.USER
        ]
        # Template cache
        self._template_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_loaded = False

        self._model_templates: Dict[str, TwinModel] = {}
        self._load_default_model_templates()
        # Template directory
        self._template_base_path = Path("src/templates/digital_replicas")
    
    async def create_twin(self, twin_type: DigitalTwinType, config: DigitalTwinConfiguration, 
                         models: Optional[List[TwinModel]] = None, metadata: Optional[BaseMetadata] = None,
                         owner_id: Optional[UUID] = None, tenant_id: Optional[UUID] = None,
                         security_enabled: bool = False) -> IDigitalTwin:
        """Create a new Digital Twin instance."""
        try:
            if not self.validate_twin_config(twin_type, config):
                raise FactoryConfigurationError('Invalid Digital Twin configuration')

            if metadata is None:
                creator_id = owner_id or uuid4()
                custom_metadata = {'security_enabled': security_enabled}
                if tenant_id:
                    custom_metadata['tenant_id'] = str(tenant_id)
                
                metadata = BaseMetadata(
                    entity_id=uuid4(),
                    timestamp=datetime.now(timezone.utc),
                    version='1.0.0',
                    created_by=creator_id,
                    custom=custom_metadata
                )

            # Create with security features
            twin = StandardDigitalTwin(
                twin_id=metadata.id,
                configuration=config,
                metadata=metadata,
                models=models,
                owner_id=owner_id,
                tenant_id=tenant_id,
                security_enabled=security_enabled
            )

            logger.info(f'Created Digital Twin {metadata.id} (security: {security_enabled})')
            return twin
            
        except Exception as e:
            logger.error(f'Failed to create Digital Twin: {e}')
            raise EntityCreationError(f'Digital Twin creation failed: {e}')
    

    def _load_templates_from_files_sync(self) -> Dict[str, Dict[str, Any]]:
        """Load templates synchronously from files."""
        templates = {}
        
        try:
            # Method 1: Try OntologyManager
            try:
                from src.layers.virtualization.ontology.manager import get_ontology_manager
                ontology_manager = get_ontology_manager()
                
                for template_id, template_obj in ontology_manager.templates.items():
                    if hasattr(template_obj, 'configuration') and template_obj.configuration:
                        config = template_obj.configuration
                        templates[template_id] = {
                            "twin_type": config.get("twin_type", "asset"),
                            "name": template_obj.name,
                            "description": template_obj.description,
                            "capabilities": config.get("capabilities", ["monitoring"]),
                            "model_configurations": config.get("model_configurations", {}),
                            "data_sources": config.get("data_sources", []),
                            "update_frequency": config.get("update_frequency", 60),
                            "retention_policy": config.get("data_retention_policy", {}),
                            "quality_requirements": config.get("quality_requirements", {}),
                            "model_templates": config.get("model_templates", [])
                        }
                logger.debug(f"Loaded {len(templates)} templates from OntologyManager")
            except Exception as e:
                logger.debug(f"OntologyManager not available: {e}")
            
            # Method 2: Scan files directly
            if not templates and self._template_base_path.exists():
                for template_file in self._template_base_path.glob("*.json"):
                    try:
                        with open(template_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        
                        template_id = data.get("template_id", template_file.stem)
                        
                        if "configuration" in data:
                            # Ontology manager format
                            config = data["configuration"]
                            templates[template_id] = {
                                "twin_type": config.get("twin_type", "asset"),
                                "name": data.get("name", template_id),
                                "description": data.get("description", ""),
                                "capabilities": config.get("capabilities", ["monitoring"]),
                                "model_configurations": config.get("model_configurations", {}),
                                "data_sources": config.get("data_sources", []),
                                "update_frequency": config.get("update_frequency", 60),
                                "retention_policy": config.get("data_retention_policy", {}),
                                "quality_requirements": config.get("quality_requirements", {}),
                                "model_templates": config.get("model_templates", [])
                            }
                        else:
                            # Direct format
                            templates[template_id] = data
                        
                        logger.debug(f"Loaded template from file: {template_id}")
                    except Exception as e:
                        logger.warning(f"Could not load template {template_file}: {e}")
            
            # Method 3: Hardcoded fallback
            if not templates:
                templates = self._get_hardcoded_templates()
                logger.info("Using hardcoded templates as fallback")
            
        except Exception as e:
            logger.error(f"Error loading templates: {e}")
            templates = self._get_hardcoded_templates()
        
        return templates

    async def _load_from_ontology_manager(self) -> None:
        """Load templates from OntologyManager."""
        try:
            ontology_manager = get_ontology_manager()
            
            # Ensure templates are loaded
            if not ontology_manager.templates:
                await ontology_manager.load_templates()
            
            # Convert ontology manager templates to our format
            for template_id, template_obj in ontology_manager.templates.items():
                if hasattr(template_obj, 'configuration') and template_obj.configuration:
                    # Convert ontology template to DT factory format
                    config = template_obj.configuration
                    
                    dt_template = {
                        "template_id": template_id,
                        "name": template_obj.name,
                        "description": template_obj.description,
                        "twin_type": config.get("twin_type", "asset"),
                        "capabilities": config.get("capabilities", ["monitoring"]),
                        "data_sources": config.get("data_sources", []),
                        "update_frequency": config.get("update_frequency", 60),
                        "model_configurations": config.get("model_configurations", {}),
                        "quality_requirements": config.get("quality_requirements", {}),
                        "retention_policy": config.get("data_retention_policy", {}),
                        "custom_config": config.get("custom_config", {}),
                        "model_templates": config.get("model_templates", []),
                        "metadata": template_obj.metadata
                    }
                    
                    self._template_cache[template_id] = dt_template
                    logger.debug(f"Loaded template from OntologyManager: {template_id}")
            
        except Exception as e:
            logger.warning(f"Could not load from OntologyManager: {e}")

    async def _load_from_filesystem(self) -> None:
        """Load templates directly from filesystem."""
        if not self._template_base_path.exists():
            logger.warning(f"Template directory not found: {self._template_base_path}")
            return
        
        # Load JSON templates
        for template_file in self._template_base_path.glob("*.json"):
            try:
                with open(template_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                template_id = data.get("template_id", template_file.stem)
                
                # Convert to DT factory format if needed
                if "configuration" in data:
                    # It's an ontology manager format
                    config = data["configuration"]
                    dt_template = {
                        "template_id": template_id,
                        "name": data.get("name", template_id),
                        "description": data.get("description", ""),
                        "twin_type": config.get("twin_type", "asset"),
                        "capabilities": config.get("capabilities", ["monitoring"]),
                        "data_sources": config.get("data_sources", []),
                        "update_frequency": config.get("update_frequency", 60),
                        "model_configurations": config.get("model_configurations", {}),
                        "quality_requirements": config.get("quality_requirements", {}),
                        "retention_policy": config.get("data_retention_policy", {}),
                        "model_templates": config.get("model_templates", [])
                    }
                else:
                    # It's already in DT factory format
                    dt_template = data
                
                self._template_cache[template_id] = dt_template
                logger.debug(f"Loaded template from file: {template_id}")
                
            except Exception as e:
                logger.error(f"Failed to load template from {template_file}: {e}")
    
    def _load_hardcoded_templates(self) -> None:
        """Load hardcoded templates as fallback."""
        hardcoded_templates = {
            "industrial_asset": {
                "twin_type": DigitalTwinType.ASSET.value,
                "name": "Industrial Asset Twin",
                "description": "Digital Twin for industrial assets with monitoring and prediction",
                "capabilities": [
                    TwinCapability.MONITORING.value,
                    TwinCapability.ANALYTICS.value,
                    TwinCapability.PREDICTION.value,
                    TwinCapability.MAINTENANCE_PLANNING.value
                ],
                "model_configurations": {
                    TwinModelType.PHYSICS_BASED.value: {"enabled": True},
                    TwinModelType.DATA_DRIVEN.value: {"enabled": True}
                },
                "data_sources": ["sensors", "maintenance_logs", "operational_data"],
                "update_frequency": 30,
                "model_templates": ["basic_physics", "basic_ml"]
            },
            "smart_building": {
                "twin_type": DigitalTwinType.INFRASTRUCTURE.value,
                "name": "Smart Building Twin",
                "description": "Digital Twin for smart building management",
                "capabilities": [
                    TwinCapability.MONITORING.value,
                    TwinCapability.OPTIMIZATION.value,
                    TwinCapability.CONTROL.value
                ],
                "model_configurations": {
                    TwinModelType.HYBRID.value: {"enabled": True}
                },
                "data_sources": ["hvac_sensors", "occupancy_sensors", "energy_meters"],
                "update_frequency": 60,
                "model_templates": ["basic_physics"]
            },
            "iot_device_system": {
                "twin_type": DigitalTwinType.SYSTEM.value,
                "name": "IoT Device System Twin",
                "description": "Digital Twin for IoT device systems",
                "capabilities": [
                    TwinCapability.MONITORING.value,
                    TwinCapability.ANALYTICS.value
                ],
                "data_sources": ["iot_sensors", "device_telemetry"],
                "update_frequency": 15,
                "model_templates": ["basic_ml"]
            },
            "production_line": {
                "twin_type": DigitalTwinType.PROCESS.value,
                "name": "Production Line Twin",
                "description": "Digital Twin for manufacturing production lines",
                "capabilities": [
                    TwinCapability.MONITORING.value,
                    TwinCapability.OPTIMIZATION.value,
                    TwinCapability.PREDICTION.value
                ],
                "data_sources": ["production_sensors", "quality_metrics"],
                "update_frequency": 20,
                "model_templates": ["basic_physics", "basic_ml"]
            },
            "energy_system": {
                "twin_type": DigitalTwinType.INFRASTRUCTURE.value,
                "name": "Energy System Twin",
                "description": "Digital Twin for energy management systems",
                "capabilities": [
                    TwinCapability.MONITORING.value,
                    TwinCapability.OPTIMIZATION.value,
                    TwinCapability.CONTROL.value
                ],
                "data_sources": ["energy_meters", "grid_sensors"],
                "update_frequency": 10,
                "model_templates": ["basic_physics"]
            }
        }
        
        for template_id, template_data in hardcoded_templates.items():
            if template_id not in self._template_cache:
                self._template_cache[template_id] = template_data
        
        logger.info(f"Loaded {len(hardcoded_templates)} hardcoded templates as fallback")

    async def _ensure_templates_loaded(self) -> None:
        """Ensure templates are loaded from files and ontology manager."""
        if self._cache_loaded:
            return
            
        try:
            # Method 1: Load from OntologyManager (preferred)
            await self._load_from_ontology_manager()
            
            # Method 2: Direct file system fallback
            if not self._template_cache:
                await self._load_from_filesystem()
            
            # Method 3: Hardcoded fallback for compatibility
            if not self._template_cache:
                self._load_hardcoded_templates()
            
            self._cache_loaded = True
            logger.info(f"Loaded {len(self._template_cache)} Digital Twin templates")
            
        except Exception as e:
            logger.error(f"Failed to load templates: {e}")
            # Load hardcoded as last resort
            self._load_hardcoded_templates()
            self._cache_loaded = True

    async def create_secure_twin(self, twin_type: DigitalTwinType, config: DigitalTwinConfiguration,
                                owner_id: UUID, tenant_id: UUID,
                                models: Optional[List[TwinModel]] = None, 
                                metadata: Optional[BaseMetadata] = None,
                                authorized_users: Optional[Dict[UUID, DTAccessLevel]] = None) -> StandardDigitalTwin:
        """Create a security-enabled Digital Twin"""
        
        # Create with security enabled
        twin = await self.create_twin(
            twin_type=twin_type,
            config=config,
            models=models,
            metadata=metadata,
            owner_id=owner_id,
            tenant_id=tenant_id,
            security_enabled=True
        )
        
        # Add additional authorized users
        if authorized_users:
            for user_id, access_level in authorized_users.items():
                twin.grant_access(user_id, access_level, owner_id)
        
        return twin

    async def create_from_template(
        self,
        template_name: str,
        customization: Optional[Dict[str, Any]] = None,
        metadata: Optional[BaseMetadata] = None
    ) -> IDigitalTwin:
        """Create a Digital Twin from a predefined template."""
        template = self._get_twin_template(template_name)
        if not template:
            raise FactoryConfigurationError(f"Digital Twin template {template_name} not found")
        
        # Apply customization
        if customization:
            template = self._apply_template_customization(template, customization)
        
        # Extract configuration from template
        twin_type = DigitalTwinType(template["twin_type"])
        config = DigitalTwinConfiguration(
            twin_type=twin_type,
            name=template["name"],
            description=template["description"],
            capabilities=set(TwinCapability(cap) for cap in template["capabilities"]),
            model_configurations=template.get("model_configurations", {}),
            data_sources=template.get("data_sources", []),
            update_frequency=template.get("update_frequency", 60),
            retention_policy=template.get("retention_policy", {}),
            quality_requirements=template.get("quality_requirements", {}),
            custom_config=template.get("custom_config", {})
        )
        
        # Create models from template
        models = []
        for model_template_id in template.get("model_templates", []):
            if model_template_id in self._model_templates:
                models.append(self._model_templates[model_template_id])
        
        return await self.create_twin(twin_type, config, models, metadata)
    
    def get_supported_twin_types(self) -> List[DigitalTwinType]:
        """Get the list of Digital Twin types this factory can create."""
        return self._supported_types.copy()
    
    def _ensure_templates_cached(self) -> None:
        """Ensure templates are loaded in cache (synchronous)."""
        if self._template_cache is None:
            self._template_cache = self._load_templates_from_files_sync()
            logger.info(f"Cached {len(self._template_cache)} templates")

    async def get_available_templates(self) -> List[str]:
        """Get the list of available Digital Twin templates (dynamically loaded)."""
        await self._ensure_templates_loaded()
        templates = list(self._template_cache.keys())
        logger.debug(f"Available templates: {templates}")
        return templates
    
    async def get_template_info(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a template."""
        await self._ensure_templates_loaded()
        template = self._template_cache.get(template_id)
        
        if template:
            return {
                "template_id": template_id,
                "name": template.get("name", template_id),
                "description": template.get("description", ""),
                "twin_type": template.get("twin_type"),
                "capabilities": template.get("capabilities", []),
                "data_sources": template.get("data_sources", []),
                "update_frequency": template.get("update_frequency", 60),
                "metadata": template.get("metadata", {})
            }
        
        return None

    def get_template_schema(self, template_name: str) -> Dict[str, Any]:
        """Get the schema for a specific template."""
        return {
            "type": "object",
            "properties": {
                "twin_type": {"type": "string", "enum": [t.value for t in DigitalTwinType]},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "capabilities": {"type": "array", "items": {"type": "string"}},
                "model_configurations": {"type": "object"},
                "data_sources": {"type": "array", "items": {"type": "string"}},
                "update_frequency": {"type": "integer", "minimum": 1},
                "retention_policy": {"type": "object"},
                "quality_requirements": {"type": "object"}
            },
            "required": ["twin_type", "name", "capabilities"]
        }
    
    def validate_twin_config(
        self,
        twin_type: DigitalTwinType,
        config: DigitalTwinConfiguration
    ) -> bool:
        """Validate a Digital Twin configuration for the specified type."""
        try:
            # Basic validation
            if config.twin_type != twin_type:
                return False
            
            if not config.name:
                return False
            
            if not config.capabilities:
                return False
            
            if config.update_frequency <= 0:
                return False
            
            # Type-specific validation
            if twin_type == DigitalTwinType.ASSET:
                # Asset twins should have monitoring capability
                if TwinCapability.MONITORING not in config.capabilities:
                    return False
            
            return True
            
        except Exception:
            return False
    
    # Implementation of IFactory interface methods
    async def create(
        self, 
        config: Dict[str, Any], 
        metadata: Optional[BaseMetadata] = None
    ) -> IDigitalTwin:
        """Create a new Digital Twin based on configuration."""
        try:
            if not self.validate_config(config):
                raise FactoryConfigurationError("Invalid Digital Twin configuration")
            
            # Extract configuration
            twin_type = DigitalTwinType(config["twin_type"])
            
            # Create Digital Twin configuration
            dt_config = DigitalTwinConfiguration(
                twin_type=twin_type,
                name=config["name"],
                description=config.get("description", ""),
                capabilities=set(TwinCapability(cap) for cap in config.get("capabilities", [])),
                model_configurations=config.get("model_configurations", {}),
                data_sources=config.get("data_sources", []),
                update_frequency=config.get("update_frequency", 60),
                retention_policy=config.get("retention_policy", {}),
                quality_requirements=config.get("quality_requirements", {}),
                custom_config=config.get("custom_config", {})
            )
            
            # Create models if specified
            models = []
            for model_config in config.get("models", []):
                model = TwinModel(
                    model_id=uuid4(),
                    model_type=TwinModelType(model_config["model_type"]),
                    name=model_config["name"],
                    version=model_config.get("version", "1.0.0"),
                    parameters=model_config.get("parameters", {}),
                    inputs=model_config.get("inputs", []),
                    outputs=model_config.get("outputs", []),
                    accuracy_metrics=model_config.get("accuracy_metrics", {})
                )
                models.append(model)
            
            return await self.create_twin(twin_type, dt_config, models, metadata)
            
        except Exception as e:
            logger.error(f"Failed to create Digital Twin: {e}")
            raise EntityCreationError(f"Digital Twin creation failed: {e}")
    
    async def create_from_template_v2(
        self, 
        template_id: str, 
        config_overrides: Optional[Dict[str, Any]] = None,
        metadata: Optional[BaseMetadata] = None
    ) -> IDigitalTwin:
        """Create a Digital Twin from a predefined template."""
        return await self.create_from_template(template_id, config_overrides, metadata)
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate the configuration before entity creation."""
        required_fields = ["twin_type", "name", "capabilities"]
        
        for field in required_fields:
            if field not in config:
                return False
        
        try:
            DigitalTwinType(config["twin_type"])
            
            # Validate capabilities
            for cap in config["capabilities"]:
                TwinCapability(cap)
            
            return True
            
        except (ValueError, TypeError):
            return False
    
    def get_supported_types(self) -> List[str]:
        """Get the list of entity types this factory can create."""
        return [dt.value for dt in self._supported_types]
    
    def get_config_schema(self, entity_type: str) -> Dict[str, Any]:
        """Get the configuration schema for a specific entity type."""
        return {
            "type": "object",
            "properties": {
                "twin_type": {"type": "string", "enum": [t.value for t in DigitalTwinType]},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "capabilities": {"type": "array", "items": {"type": "string"}},
                "model_configurations": {"type": "object"},
                "data_sources": {"type": "array", "items": {"type": "string"}},
                "update_frequency": {"type": "integer", "minimum": 1},
                "retention_policy": {"type": "object"},
                "quality_requirements": {"type": "object"},
                "models": {"type": "array"}
            },
            "required": ["twin_type", "name", "capabilities"]
        }
    
    def _load_default_model_templates(self) -> None:
        """Load default model templates."""
        # Physics model template
        physics_model = TwinModel(
            model_id=uuid4(),
            model_type=TwinModelType.PHYSICS_BASED,
            name="Basic Physics Model",
            version="1.0.0",
            parameters={"gravity": 9.81, "friction": 0.1},
            inputs=["force", "mass"],
            outputs=["acceleration", "velocity"],
            accuracy_metrics={"rmse": 0.05}
        )
        self._model_templates["basic_physics"] = physics_model
        
        # ML model template
        ml_model = TwinModel(
            model_id=uuid4(),
            model_type=TwinModelType.DATA_DRIVEN,
            name="Basic ML Model",
            version="1.0.0",
            parameters={"learning_rate": 0.01, "epochs": 100},
            inputs=["sensor_data", "historical_data"],
            outputs=["prediction", "confidence"],
            accuracy_metrics={"accuracy": 0.92, "f1_score": 0.89}
        )
        self._model_templates["basic_ml"] = ml_model
        
        logger.info(f"Loaded {len(self._model_templates)} model templates")
    

    
    def _apply_template_customization(
        self,
        template: Dict[str, Any],
        customization: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply customization to a template."""
        customized = template.copy()
        
        # Apply customizations
        for key, value in customization.items():
            if key in customized:
                if isinstance(customized[key], dict) and isinstance(value, dict):
                    customized[key].update(value)
                else:
                    customized[key] = value
        
        return customized
    
    def _get_twin_template_sync(self, template_name: str) -> Optional[Dict[str, Any]]:
        """Synchronous version for backward compatibility."""
        # Try cache first
        if self._cache_loaded and template_name in self._template_cache:
            return self._template_cache[template_name]
        
        # Load hardcoded as immediate fallback
        self._load_hardcoded_templates()
        return self._template_cache.get(template_name)
    
    async def reload_templates(self) -> None:
        """Reload all templates from source."""
        self._template_cache.clear()
        self._cache_loaded = False
        await self._ensure_templates_loaded()
        logger.info(f"Reloaded {len(self._template_cache)} templates")
    
    async def create_from_template(
        self,
        template_name: str,
        customization: Optional[Dict[str, Any]] = None,
        metadata: Optional[BaseMetadata] = None
    ) -> IDigitalTwin:
        """Create a Digital Twin from a predefined template."""
        
        template = await self._get_twin_template(template_name)
        if not template:
            available = await self.get_available_templates()
            raise FactoryConfigurationError(
                f"Digital Twin template '{template_name}' not found. "
                f"Available templates: {available}"
            )
        
        # Apply customization
        if customization:
            template = self._apply_template_customization(template, customization)
        
        # Extract configuration from template
        twin_type = DigitalTwinType(template["twin_type"])
        config = DigitalTwinConfiguration(
            twin_type=twin_type,
            name=template["name"],
            description=template["description"],
            capabilities=set(TwinCapability(cap) for cap in template["capabilities"]),
            model_configurations=template.get("model_configurations", {}),
            data_sources=template.get("data_sources", []),
            update_frequency=template.get("update_frequency", 60),
            retention_policy=template.get("retention_policy", {}),
            quality_requirements=template.get("quality_requirements", {}),
            custom_config=template.get("custom_config", {})
        )
        
        # Create models from template
        models = []
        for model_template_id in template.get("model_templates", []):
            if model_template_id in self._model_templates:
                models.append(self._model_templates[model_template_id])
        
        return await self.create_twin(twin_type, config, models, metadata)
    
    # Keep backward compatibility
    def get_available_templates_sync(self) -> List[str]:
        """Synchronous version for backward compatibility."""
        if not self._cache_loaded:
            self._load_hardcoded_templates()
        return list(self._template_cache.keys())
    
    # Update the old method to maintain compatibility
    def get_available_templates_old(self) -> List[str]:
        """DEPRECATED: Use async get_available_templates() instead."""
        logger.warning("Using deprecated get_available_templates_old(). Use async version.")
        return self.get_available_templates_sync()
    
    async def get_available_templates_async(self) -> List[str]:
        """Async version of get_available_templates."""
        # For now, just call sync version
        return self.get_available_templates()
        
    def refresh_templates(self) -> None:
        """Refresh template cache."""
        self._template_cache = None
        self._ensure_templates_cached()
        logger.info("Template cache refreshed")