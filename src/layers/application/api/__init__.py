import logging
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from typing import Dict, Any
import uvicorn
from src.layers.application.api_gateway import get_api_gateway, initialize_api_gateway
from src.utils.exceptions import APIGatewayError, AuthenticationError, EntityNotFoundError, ValidationError
from src.utils.config import get_config
from src.layers.application.auth import get_auth_manager
from datetime import datetime
import asyncio
logger = logging.getLogger(__name__)
app: FastAPI = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info('Starting Digital Twin Platform API...')
    try:
        # Inizializza l'API Gateway
        gateway = await initialize_api_gateway()
        logger.info('API Gateway initialized')
        app.state.gateway = gateway
        
        # Inizializza il sistema di autenticazione
        auth_manager = get_auth_manager()
        await auth_manager.initialize()
        logger.info('Authentication system initialized')
        
        yield
    except Exception as e:
        logger.error(f'Failed to start API: {e}')
        raise
    finally:
        logger.info('Shutting down Digital Twin Platform API...')

def create_fastapi_app() -> FastAPI:
    config = get_config()
    
    fastapi_app = FastAPI(
        title='Digital Twin Platform API',
        description='REST API for Digital Twin Platform',
        version='1.0.0',
        docs_url='/docs',
        redoc_url='/redoc',
        openapi_url='/openapi.json',
        lifespan=lifespan
    )
    
    # CORS middleware
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=config.get('api', {}).get('cors_origins', ['*']),
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*']
    )
    
    # Trusted hosts middleware
    allowed_hosts = config.get('api', {}).get('allowed_hosts', ['*'])
    if allowed_hosts != ['*']:
        fastapi_app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    
    setup_exception_handlers(fastapi_app)
    return fastapi_app

def setup_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIGatewayError)
    async def api_gateway_exception_handler(request, exc: APIGatewayError):
        logger.error(f'API Gateway error: {exc}')
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                'error': 'API Gateway Error',
                'message': str(exc),
                'type': 'gateway_error'
            }
        )

    @app.exception_handler(AuthenticationError)
    async def authentication_exception_handler(request, exc: AuthenticationError):
        logger.warning(f'Authentication error: {exc}')
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                'error': 'Authentication Failed',
                'message': str(exc),
                'type': 'auth_error'
            }
        )

    @app.exception_handler(EntityNotFoundError)
    async def not_found_exception_handler(request, exc: EntityNotFoundError):
        logger.warning(f'Entity not found: {exc}')
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                'error': 'Entity Not Found',
                'message': str(exc),
                'type': 'not_found_error'
            }
        )

    @app.exception_handler(ValidationError)
    async def validation_exception_handler(request, exc: ValidationError):
        logger.warning(f'Validation error: {exc}')
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                'error': 'Validation Error',
                'message': str(exc),
                'type': 'validation_error'
            }
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                'error': 'HTTP Error',
                'message': exc.detail,
                'type': 'http_error'
            }
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request, exc: Exception):
        logger.error(f'Unhandled exception: {exc}', exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                'error': 'Internal Server Error',
                'message': 'An unexpected error occurred',
                'type': 'internal_error'
            }
        )

def get_gateway_dependency():
    async def _get_gateway():
        gateway = get_api_gateway()
        if not gateway.is_ready():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail='API Gateway not ready'
            )
        return gateway
    return _get_gateway

get_gateway = get_gateway_dependency()

def register_routers(app: FastAPI) -> None:
    routers_to_register = [
        # === AUTHENTICATION ===
        {
            'name': 'auth', 
            'prefix': '/api/v1/auth', 
            'tags': ['🔐 Authentication'], 
            'module_path': 'src.layers.application.api.auth'
        },
        
        # === DIGITAL TWINS (Legacy + Secure) ===
        {
            'name': 'digital_twins', 
            'prefix': '/api/v1/digital-twins', 
            'tags': ['🔷 Digital Twins (Legacy)'], 
            'module_path': 'src.layers.application.api.digital_twins'
        },
        
        # 🆕 NUOVE ROUTE SICURE
        {
            'name': 'secure_digital_twins', 
            'prefix': '/api/v1/secure/digital-twins', 
            'tags': ['🔒 Secure Digital Twins'], 
            'module_path': 'src.layers.application.api.secure_digital_twins'
        },
        # NEW: Device Configuration Routes
        {
            'name': 'device_config', 
            'prefix': '/api/v1/devices', 
            'tags': ['🔌 Device Configuration'], 
            'module_path': 'src.layers.application.api.device_config'
        },
        
        # === OTHER SERVICES ===
        {
            'name': 'services', 
            'prefix': '/api/v1/services', 
            'tags': ['⚙️ Services'], 
            'module_path': 'src.layers.application.api.services'
        },
        {
            'name': 'replicas', 
            'prefix': '/api/v1/replicas', 
            'tags': ['📱 Digital Replicas'], 
            'module_path': 'src.layers.application.api.replicas'
        },
        {
            'name': 'workflows', 
            'prefix': '/api/v1/workflows', 
            'tags': ['🔄 Workflows'], 
            'module_path': 'src.layers.application.api.workflows'
        }
    ]
    
    successful_routers = []
    failed_routers = []
    
    for router_config in routers_to_register:
        try:
            logger.info(f"🔌 Registering {router_config['name']} router...")
            
            # Try to import the module
            try:
                module = __import__(router_config['module_path'], fromlist=['router'])
                router = getattr(module, 'router')
                
                # Register the router
                app.include_router(
                    router, 
                    prefix=router_config['prefix'], 
                    tags=router_config['tags']
                )
                
                successful_routers.append(router_config['name'])
                logger.info(f"✅ Successfully registered {router_config['name']} router")
                
            except ImportError as e:
                failed_routers.append({
                    'name': router_config['name'], 
                    'error': f'Import error: {str(e)}',
                    'critical': router_config['name'] in ['auth', 'digital_twins']  # Critical routers
                })
                logger.error(f"❌ Failed to import {router_config['name']} router: {e}")
                
            except AttributeError as e:
                failed_routers.append({
                    'name': router_config['name'], 
                    'error': f'Router not found in module: {str(e)}',
                    'critical': router_config['name'] in ['auth', 'digital_twins']
                })
                logger.error(f"❌ Router not found in {router_config['name']} module: {e}")
                
        except Exception as e:
            failed_routers.append({
                'name': router_config['name'], 
                'error': f'Unexpected error: {str(e)}',
                'critical': router_config['name'] in ['auth', 'digital_twins']
            })
            logger.error(f"❌ Unexpected error registering {router_config['name']} router: {e}")
    
    # Summary
    logger.info(f'📊 Router registration completed:')
    logger.info(f'  ✅ Successful: {len(successful_routers)} - {successful_routers}')
    
    if failed_routers:
        critical_failures = [r for r in failed_routers if r.get('critical')]
        non_critical_failures = [r for r in failed_routers if not r.get('critical')]
        
        if critical_failures:
            logger.error(f'  🚨 CRITICAL failures: {len(critical_failures)}')
            for failed in critical_failures:
                logger.error(f"    - {failed['name']}: {failed['error']}")
        
        if non_critical_failures:
            logger.warning(f'  ⚠️  Non-critical failures: {len(non_critical_failures)}')
            for failed in non_critical_failures:
                logger.warning(f"    - {failed['name']}: {failed['error']}")
    
    # Add a debug endpoint to show registered routes
    @app.get('/debug/routes', summary='🔍 Debug: List all registered routes')
    async def debug_routes():
        """Debug endpoint to see all registered routes"""
        routes_info = []
        for route in app.routes:
            if hasattr(route, 'path') and hasattr(route, 'methods'):
                routes_info.append({
                    'path': route.path,
                    'methods': list(route.methods) if route.methods else [],
                    'name': getattr(route, 'name', 'unnamed')
                })
        
        return {
            'total_routes': len(routes_info),
            'successful_routers': successful_routers,
            'failed_routers': [f['name'] for f in failed_routers],
            'routes': sorted(routes_info, key=lambda x: x['path'])
        }

def setup_root_endpoints(app: FastAPI) -> None:

    @app.get('/', summary='Root endpoint')
    async def root():
        return {
            'name': 'Digital Twin Platform API', 
            'version': '1.0.0', 
            'status': 'running',
            'documentation': '/docs',
            'endpoints': {
                'auth': '/api/v1/auth',
                'digital_twins': '/api/v1/digital-twins',
                'secure_digital_twins': '/api/v1/secure/digital-twins',  # NEW!
                'services': '/api/v1/services',
                'replicas': '/api/v1/replicas',
                'workflows': '/api/v1/workflows'
            },
            'auth': {
                'registration': '/api/v1/auth/register',
                'login': '/api/v1/auth/login',
                'docs': '/docs#/Authentication'
            }
        }

    @app.get('/health', summary='Health check')
    async def health_check():
        """Fixed health check endpoint that never crashes"""
        try:
            current_time = datetime.now().isoformat()
            
            # Basic status sempre funzionante
            basic_status = {
                'status': 'healthy',
                'timestamp': current_time,
                'version': '1.0.0',
                'service': 'Digital Twin Platform API'
            }
            
            # Try to get gateway status (safe)
            try:
                gateway = get_api_gateway()
                
                if gateway:
                    # Check if gateway is ready (handle both sync and async)
                    gateway_ready = gateway.is_ready()
                    if asyncio.iscoroutine(gateway_ready):
                        gateway_ready = await gateway_ready
                    
                    basic_status['gateway_ready'] = bool(gateway_ready)
                    basic_status['status'] = 'healthy' if gateway_ready else 'degraded'
                    
                    # Get detailed status safely
                    if gateway_ready:
                        try:
                            gateway_status = await gateway.get_gateway_status()
                            if isinstance(gateway_status, dict):
                                # Extract only serializable data
                                safe_gateway = {}
                                for key, value in gateway_status.items():
                                    try:
                                        if isinstance(value, (str, int, float, bool, type(None))):
                                            safe_gateway[key] = value
                                        elif isinstance(value, (list, dict)):
                                            # Only include if JSON serializable
                                            import json
                                            json.dumps(value)  # Test serialization
                                            safe_gateway[key] = value
                                        else:
                                            safe_gateway[key] = str(value)
                                    except:
                                        safe_gateway[key] = str(value)
                                
                                basic_status['gateway'] = safe_gateway
                        except Exception as gw_err:
                            basic_status['gateway_error'] = str(gw_err)
                else:
                    basic_status['gateway_ready'] = False
                    basic_status['status'] = 'degraded'
                    basic_status['gateway_error'] = 'Gateway not initialized'
                    
            except Exception as e:
                basic_status['gateway_ready'] = False
                basic_status['status'] = 'degraded'
                basic_status['gateway_error'] = str(e)
            
            # Try to get auth status (safe)
            try:
                auth_manager = get_auth_manager()
                
                if auth_manager:
                    auth_status = auth_manager.get_auth_status()
                    if asyncio.iscoroutine(auth_status):
                        auth_status = await auth_status
                    
                    # Make auth status serializable
                    if isinstance(auth_status, dict):
                        safe_auth = {}
                        for key, value in auth_status.items():
                            try:
                                if isinstance(value, (str, int, float, bool, type(None))):
                                    safe_auth[key] = value
                                elif isinstance(value, (list, dict)):
                                    import json
                                    json.dumps(value)  # Test serialization
                                    safe_auth[key] = value
                                else:
                                    safe_auth[key] = str(value)
                            except:
                                safe_auth[key] = str(value)
                        
                        basic_status['auth'] = safe_auth
                    else:
                        basic_status['auth'] = {'status': 'unknown', 'data_type': str(type(auth_status))}
                else:
                    basic_status['auth'] = {'status': 'not_initialized'}
                    
            except Exception as e:
                basic_status['auth'] = {'status': 'error', 'error': str(e)}
            
            return basic_status
            
        except Exception as e:
            logger.error(f'Health check completely failed: {e}')
            return {
                'status': 'unhealthy', 
                'error': str(e),
                'timestamp': datetime.now().isoformat(),
                'service': 'Digital Twin Platform API',
                'message': 'Critical health check failure'
            }

    @app.get('/health/simple', summary='Simple Health Check')
    async def simple_health_check():
        """Super simple health check that always works"""
        return {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'service': 'Digital Twin Platform API',
            'message': 'Service is running properly'
        }

    @app.get('/platform/overview', summary='Platform overview')
    async def platform_overview():
        """Safe platform overview"""
        try:
            gateway = get_api_gateway()
            if gateway and gateway.is_ready():
                overview = await gateway.get_platform_overview()
                
                # Make sure it's serializable
                if isinstance(overview, dict):
                    safe_overview = {}
                    for key, value in overview.items():
                        try:
                            import json
                            json.dumps(value)  # Test if serializable
                            safe_overview[key] = value
                        except:
                            safe_overview[key] = str(value)
                    return safe_overview
                else:
                    return {'error': 'Invalid overview format', 'type': str(type(overview))}
            else:
                return {
                    'status': 'degraded',
                    'message': 'Gateway not ready',
                    'timestamp': datetime.now().isoformat()
                }
        except Exception as e:
            logger.error(f'Platform overview failed: {e}')
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

def get_app() -> FastAPI:
    """Crea e configura l'applicazione FastAPI"""
    global app
    if app is None:
        logger.info("Creating FastAPI application...")
        app = create_fastapi_app()
        
        # Setup endpoints root
        setup_root_endpoints(app)
        
        # Registra tutti i router
        register_routers(app)
        
        logger.info("FastAPI application created and configured")
    
    return app

async def start_api_server(host: str = '0.0.0.0', port: int = 8000, reload: bool = False) -> None:
    """Avvia il server API"""
    config = get_config()
    api_config = config.get('api', {})
    
    host = api_config.get('host', host)
    port = api_config.get('port', port)
    
    logger.info(f'Starting API server on {host}:{port}')
    
    fastapi_app = get_app()
    
    uvicorn_config = uvicorn.Config(
        app=fastapi_app,
        host=host,
        port=port,
        reload=reload,
        log_config=None,
        access_log=True
    )
    
    server = uvicorn.Server(uvicorn_config)
    await server.serve()