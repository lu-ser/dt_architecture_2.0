"""
API Module for the Digital Twin Platform Application Layer.

This module provides FastAPI-based REST endpoints for external applications
to interact with the Digital Twin Platform. It includes endpoints for all
major platform entities and operations.

LOCATION: src/layers/application/api/__init__.py
"""

import logging
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from typing import Dict, Any
import uvicorn

from src.layers.application.api_gateway import get_api_gateway, initialize_api_gateway
from src.utils.exceptions import (
    APIGatewayError,
    AuthenticationError,
    EntityNotFoundError,
    ValidationError
)
from src.utils.config import get_config

logger = logging.getLogger(__name__)


# Global FastAPI app instance
app: FastAPI = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI application."""
    # Startup
    logger.info("Starting Digital Twin Platform API...")
    
    try:
        # Initialize API Gateway
        gateway = await initialize_api_gateway()
        logger.info("API Gateway initialized")
        
        # Store gateway in app state for access in endpoints
        app.state.gateway = gateway
        
        yield
        
    except Exception as e:
        logger.error(f"Failed to start API: {e}")
        raise
    
    finally:
        # Shutdown
        logger.info("Shutting down Digital Twin Platform API...")


def create_fastapi_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = get_config()
    
    # Create FastAPI app with lifespan management
    fastapi_app = FastAPI(
        title="Digital Twin Platform API",
        description="Generic REST API for Digital Twin Platform external access",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan
    )
    
    # Configure CORS
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=config.get("api", {}).get("cors_origins", ["*"]),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Configure trusted hosts
    allowed_hosts = config.get("api", {}).get("allowed_hosts", ["*"])
    if allowed_hosts != ["*"]:
        fastapi_app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=allowed_hosts
        )
    
    # Global exception handlers
    setup_exception_handlers(fastapi_app)
    
    return fastapi_app


def setup_exception_handlers(app: FastAPI) -> None:
    """Setup global exception handlers for the API."""
    
    @app.exception_handler(APIGatewayError)
    async def api_gateway_exception_handler(request, exc: APIGatewayError):
        logger.error(f"API Gateway error: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "API Gateway Error",
                "message": str(exc),
                "type": "gateway_error"
            }
        )
    
    @app.exception_handler(AuthenticationError)
    async def authentication_exception_handler(request, exc: AuthenticationError):
        logger.warning(f"Authentication error: {exc}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": "Authentication Failed",
                "message": str(exc),
                "type": "auth_error"
            }
        )
    
    @app.exception_handler(EntityNotFoundError)
    async def not_found_exception_handler(request, exc: EntityNotFoundError):
        logger.warning(f"Entity not found: {exc}")
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "Entity Not Found",
                "message": str(exc),
                "type": "not_found_error"
            }
        )
    
    @app.exception_handler(ValidationError)
    async def validation_exception_handler(request, exc: ValidationError):
        logger.warning(f"Validation error: {exc}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "Validation Error",
                "message": str(exc),
                "type": "validation_error"
            }
        )
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "HTTP Error",
                "message": exc.detail,
                "type": "http_error"
            }
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal Server Error",
                "message": "An unexpected error occurred",
                "type": "internal_error"
            }
        )


def get_gateway_dependency():
    """Dependency to get the API Gateway instance."""
    async def _get_gateway():
        gateway = get_api_gateway()
        if not gateway.is_ready():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API Gateway not ready"
            )
        return gateway
    return _get_gateway


# Dependency for getting the gateway
get_gateway = get_gateway_dependency()


def register_routers(app: FastAPI) -> None:
    """Register all API routers with the FastAPI app."""
    
    # Import routers here to avoid circular imports
    # These will be implemented in the next files
    try:
        from src.layers.application.api.digital_twins import router as digital_twins_router
        from src.layers.application.api.services import router as services_router
        from src.layers.application.api.replicas import router as replicas_router
        from src.layers.application.api.workflows import router as workflows_router
        
        # Register routers with prefixes
        app.include_router(digital_twins_router, prefix="/api/v1/digital-twins", tags=["Digital Twins"])
        app.include_router(services_router, prefix="/api/v1/services", tags=["Services"])
        app.include_router(replicas_router, prefix="/api/v1/replicas", tags=["Digital Replicas"])
        app.include_router(workflows_router, prefix="/api/v1/workflows", tags=["Workflows"])
        
        logger.info("All API routers registered successfully")
        
    except ImportError as e:
        logger.warning(f"Some API routers not available yet: {e}")


# Root endpoints
def setup_root_endpoints(app: FastAPI) -> None:
    """Setup root-level endpoints."""
    
    @app.get("/", summary="Root endpoint")
    async def root():
        """Root endpoint with basic platform information."""
        return {
            "name": "Digital Twin Platform API",
            "version": "1.0.0",
            "status": "running",
            "documentation": "/docs"
        }
    
    @app.get("/health", summary="Health check")
    async def health_check(gateway = Depends(get_gateway)):
        """Health check endpoint."""
        try:
            status_info = await gateway.get_gateway_status()
            return {
                "status": "healthy" if gateway.is_ready() else "degraded",
                "timestamp": status_info["gateway"]["timestamp"],
                "details": status_info
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    @app.get("/platform/overview", summary="Platform overview")
    async def platform_overview(gateway = Depends(get_gateway)):
        """Get comprehensive platform overview."""
        try:
            return await gateway.get_platform_overview()
        except Exception as e:
            logger.error(f"Platform overview failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get platform overview: {e}"
            )


def get_app() -> FastAPI:
    """Get the configured FastAPI application."""
    global app
    
    if app is None:
        app = create_fastapi_app()
        setup_root_endpoints(app)
        register_routers(app)
    
    return app


async def start_api_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False
) -> None:
    """Start the API server."""
    config = get_config()
    
    # Get configuration
    api_config = config.get("api", {})
    host = api_config.get("host", host)
    port = api_config.get("port", port)
    
    logger.info(f"Starting API server on {host}:{port}")
    
    # Get the app
    fastapi_app = get_app()
    
    # Run the server
    uvicorn_config = uvicorn.Config(
        app=fastapi_app,
        host=host,
        port=port,
        reload=reload,
        log_config=None,  # Use our logging configuration
        access_log=True
    )
    
    server = uvicorn.Server(uvicorn_config)
    await server.serve()


# Convenience functions
def run_api_server_sync(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False
) -> None:
    """Run the API server synchronously."""
    import asyncio
    asyncio.run(start_api_server(host, port, reload))


if __name__ == "__main__":
    # Development server
    run_api_server_sync(reload=True)