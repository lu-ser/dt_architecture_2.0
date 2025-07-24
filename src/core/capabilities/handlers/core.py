# src/core/capabilities/handlers/core.py
"""
Core capability handlers that every Digital Twin should support.
These replace the hardcoded enum values with flexible implementations.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List
from ..capability_registry import ICapabilityHandler, CapabilityDefinition, ExecutionContext

logger = logging.getLogger(__name__)

# ==========================================
# CORE HANDLERS
# ==========================================

class MonitoringHandler(ICapabilityHandler):
    """Handler for real-time monitoring capability."""
    
    async def execute(self, input_data: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        """Execute monitoring logic."""
        metrics = input_data.get('metrics', [])
        duration = input_data.get('duration', 60)  # seconds
        
        # Simulate data collection (replace with real monitoring logic)
        monitoring_data = {
            "twin_id": context.twin_id,
            "status": "active",
            "metrics_collected": len(metrics),
            "monitoring_duration": duration,
            "data_points": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "quality_score": 0.95
        }
        
        # Simulate collecting metric data
        for metric in metrics:
            monitoring_data["data_points"].append({
                "metric": metric,
                "value": 42.0,  # Replace with real data source
                "unit": "units",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        
        logger.info(f"Monitoring executed for twin {context.twin_id}, collected {len(metrics)} metrics")
        return monitoring_data
    
    def validate_input(self, input_data: Dict[str, Any]) -> bool:
        """Validate monitoring input data."""
        if not isinstance(input_data, dict):
            return False
        
        metrics = input_data.get('metrics', [])
        if not isinstance(metrics, list):
            return False
        
        duration = input_data.get('duration', 60)
        if not isinstance(duration, (int, float)) or duration <= 0:
            return False
        
        return True
    
    def get_capability_definition(self) -> CapabilityDefinition:
        """Return the monitoring capability definition."""
        return CapabilityDefinition(
            name="monitoring",
            namespace="core",
            description="Real-time data monitoring and collection",
            category="observability",
            input_schema={
                "type": "object",
                "properties": {
                    "metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of metrics to monitor"
                    },
                    "duration": {
                        "type": "number",
                        "minimum": 1,
                        "description": "Monitoring duration in seconds"
                    }
                },
                "required": ["metrics"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "twin_id": {"type": "string"},
                    "status": {"type": "string"},
                    "metrics_collected": {"type": "integer"},
                    "data_points": {"type": "array"},
                    "timestamp": {"type": "string"},
                    "quality_score": {"type": "number"}
                }
            },
            required_permissions=["read:data", "monitor:twin"]
        )


class HealthCheckHandler(ICapabilityHandler):
    """Handler for system health verification."""
    
    async def execute(self, input_data: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        """Execute health check logic."""
        check_type = input_data.get('check_type', 'basic')
        include_details = input_data.get('include_details', False)
        
        # Simulate health check (replace with real health monitoring)
        health_status = {
            "twin_id": context.twin_id,
            "status": "healthy",
            "overall_score": 0.98,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "check_type": check_type
        }
        
        if include_details:
            health_status["details"] = {
                "cpu_usage": 0.15,
                "memory_usage": 0.32,
                "storage_usage": 0.45,
                "network_latency": 12.5,
                "error_rate": 0.001,
                "uptime": "7d 14h 32m"
            }
            
            # Check for specific twin type health metrics
            if context.twin_type == "asset":
                health_status["details"]["asset_specific"] = {
                    "operational_status": "running",
                    "maintenance_due": False,
                    "performance_index": 0.94
                }
        
        logger.info(f"Health check executed for twin {context.twin_id}, status: {health_status['status']}")
        return health_status
    
    def validate_input(self, input_data: Dict[str, Any]) -> bool:
        """Validate health check input data."""
        if not isinstance(input_data, dict):
            return False
        
        check_type = input_data.get('check_type', 'basic')
        if check_type not in ['basic', 'detailed', 'full']:
            return False
        
        include_details = input_data.get('include_details', False)
        if not isinstance(include_details, bool):
            return False
        
        return True
    
    def get_capability_definition(self) -> CapabilityDefinition:
        """Return the health check capability definition."""
        return CapabilityDefinition(
            name="health_check",
            namespace="core",
            description="System health verification and status reporting",
            category="diagnostics",
            input_schema={
                "type": "object",
                "properties": {
                    "check_type": {
                        "type": "string",
                        "enum": ["basic", "detailed", "full"],
                        "description": "Type of health check to perform"
                    },
                    "include_details": {
                        "type": "boolean",
                        "description": "Include detailed metrics in response"
                    }
                }
            },
            output_schema={
                "type": "object",
                "properties": {
                    "twin_id": {"type": "string"},
                    "status": {"type": "string"},
                    "overall_score": {"type": "number"},
                    "timestamp": {"type": "string"},
                    "details": {"type": "object"}
                }
            },
            required_permissions=["read:status", "health:check"]
        )


class DataSyncHandler(ICapabilityHandler):
    """Handler for data synchronization capability."""
    
    async def execute(self, input_data: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        """Execute data synchronization logic."""
        sync_type = input_data.get('sync_type', 'incremental')
        force_full_sync = input_data.get('force_full_sync', False)
        target_sources = input_data.get('target_sources', [])
        
        # Simulate data sync (replace with real sync logic)
        sync_result = {
            "twin_id": context.twin_id,
            "sync_type": sync_type,
            "status": "completed",
            "records_synced": 1247,
            "records_updated": 89,
            "records_created": 23,
            "errors": 0,
            "sync_duration_ms": 1250,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        if target_sources:
            sync_result["sources_synced"] = target_sources
            sync_result["source_status"] = {
                source: "success" for source in target_sources
            }
        else:
            sync_result["sources_synced"] = ["default_replica", "external_api"]
            sync_result["source_status"] = {
                "default_replica": "success",
                "external_api": "success"
            }
        
        if force_full_sync:
            sync_result["sync_type"] = "full"
            sync_result["records_synced"] *= 3  # Simulate more data for full sync
        
        logger.info(f"Data sync executed for twin {context.twin_id}, synced {sync_result['records_synced']} records")
        return sync_result
    
    def validate_input(self, input_data: Dict[str, Any]) -> bool:
        """Validate data sync input data."""
        if not isinstance(input_data, dict):
            return False
        
        sync_type = input_data.get('sync_type', 'incremental')
        if sync_type not in ['incremental', 'full', 'differential']:
            return False
        
        force_full_sync = input_data.get('force_full_sync', False)
        if not isinstance(force_full_sync, bool):
            return False
        
        target_sources = input_data.get('target_sources', [])
        if not isinstance(target_sources, list):
            return False
        
        return True
    
    def get_capability_definition(self) -> CapabilityDefinition:
        """Return the data sync capability definition."""
        return CapabilityDefinition(
            name="data_sync",
            namespace="core",
            description="Data synchronization between twin and data sources",
            category="data_management",
            input_schema={
                "type": "object",
                "properties": {
                    "sync_type": {
                        "type": "string",
                        "enum": ["incremental", "full", "differential"],
                        "description": "Type of synchronization to perform"
                    },
                    "force_full_sync": {
                        "type": "boolean",
                        "description": "Force full synchronization regardless of sync_type"
                    },
                    "target_sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific data sources to sync (empty = all)"
                    }
                }
            },
            output_schema={
                "type": "object",
                "properties": {
                    "twin_id": {"type": "string"},
                    "sync_type": {"type": "string"},
                    "status": {"type": "string"},
                    "records_synced": {"type": "integer"},
                    "sync_duration_ms": {"type": "integer"},
                    "timestamp": {"type": "string"}
                }
            },
            required_permissions=["write:data", "sync:sources"]
        )