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
    """Registra tutti i router API con gestione errori migliorata"""
    
    # Lista dei router da registrare
    routers_to_register = [
        {
            'name': 'auth',
            'prefix': '/api/v1/auth',
            'tags': ['Authentication'],
            'module_path': 'src.layers.application.api.auth'
        },
        {
            'name': 'digital_twins',
            'prefix': '/api/v1/digital-twins',
            'tags': ['Digital Twins'],
            'module_path': 'src.layers.application.api.digital_twins'
        },
        {
            'name': 'services',
            'prefix': '/api/v1/services',
            'tags': ['Services'],
            'module_path': 'src.layers.application.api.services'
        },
        {
            'name': 'replicas',
            'prefix': '/api/v1/replicas',
            'tags': ['Digital Replicas'],
            'module_path': 'src.layers.application.api.replicas'
        },
        {
            'name': 'workflows',
            'prefix': '/api/v1/workflows',
            'tags': ['Workflows'],
            'module_path': 'src.layers.application.api.workflows'
        }
    ]
    
    successful_routers = []
    failed_routers = []
    
    for router_config in routers_to_register:
        try:
            logger.info(f"Registering {router_config['name']} router...")
            
            # Import dinamico del router
            module = __import__(router_config['module_path'], fromlist=['router'])
            router = getattr(module, 'router')
            
            # Registra il router
            app.include_router(
                router,
                prefix=router_config['prefix'],
                tags=router_config['tags']
            )
            
            successful_routers.append(router_config['name'])
            logger.info(f"✓ Successfully registered {router_config['name']} router")
            
        except ImportError as e:
            failed_routers.append({
                'name': router_config['name'],
                'error': f'Import error: {str(e)}'
            })
            logger.error(f"✗ Failed to import {router_config['name']} router: {e}")
            
        except AttributeError as e:
            failed_routers.append({
                'name': router_config['name'],
                'error': f'Router not found in module: {str(e)}'
            })
            logger.error(f"✗ Router not found in {router_config['name']} module: {e}")
            
        except Exception as e:
            failed_routers.append({
                'name': router_config['name'],
                'error': f'Unexpected error: {str(e)}'
            })
            logger.error(f"✗ Unexpected error registering {router_config['name']} router: {e}")
            logger.exception(f"Full traceback for {router_config['name']}:")
    
    # Report finale
    logger.info(f"Router registration completed:")
    logger.info(f"  ✓ Successful: {len(successful_routers)} - {successful_routers}")
    if failed_routers:
        logger.warning(f"  ✗ Failed: {len(failed_routers)}")
        for failed in failed_routers:
            logger.warning(f"    - {failed['name']}: {failed['error']}")

def setup_root_endpoints(app: FastAPI) -> None:
    """Setup degli endpoint root"""
    
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
    async def health_check(gateway=Depends(get_gateway)):
        try:
            status_info = await gateway.get_gateway_status()
            auth_manager = get_auth_manager()
            auth_status = auth_manager.get_auth_status()
            status_info['auth'] = auth_status
            
            return {
                'status': 'healthy' if gateway.is_ready() else 'degraded',
                'timestamp': status_info['gateway']['timestamp'],
                'details': status_info
            }
        except Exception as e:
            logger.error(f'Health check failed: {e}')
            return {
                'status': 'unhealthy',
                'error': str(e)
            }

    @app.get('/platform/overview', summary='Platform overview')
    async def platform_overview(gateway=Depends(get_gateway)):
        try:
            overview = await gateway.get_platform_overview()
            auth_manager = get_auth_manager()
            overview['auth_statistics'] = auth_manager.get_auth_status()
            return overview
        except Exception as e:
            logger.error(f'Platform overview failed: {e}')
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f'Failed to get platform overview: {e}'
            )

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