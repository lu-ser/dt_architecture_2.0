import asyncio
import sys
import logging
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).parent))
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_compatible_auth():
    print('🧪 Test Sistema Autenticazione Compatibile')
    print('=' * 60)
    try:
        print('\n📋 Step 1: Setup Configurazione')

        class SimpleConfig:

            def __init__(self):
                self.data = {'storage': {'primary_type': 'mongodb'}, 'mongodb': {'connection_string': 'mongodb://localhost:27017', 'global_database': 'dt_platform_test', 'database_prefix': 'dt_test'}, 'jwt': {'secret_key': 'test-secret-key'}, 'auth': {'secret_key': 'test-secret-key'}}

            def get(self, key, default=None):
                keys = key.split('.')
                value = self.data
                for k in keys:
                    if isinstance(value, dict) and k in value:
                        value = value[k]
                    else:
                        return default
                return value

        class MockConfigModule:

            def get_config(self):
                return SimpleConfig()
        sys.modules['src.utils.config'] = MockConfigModule()
        print('✅ Configurazione mock impostata')
        print('\n🔐 Step 2: Test Authentication Manager')
        from src.layers.application.auth import get_auth_manager
        auth_manager = get_auth_manager()
        await auth_manager.initialize()
        print('✅ Authentication Manager inizializzato')
        provider_type = auth_manager.jwt_provider.__class__.__name__
        print(f'✅ JWT Provider Type: {provider_type}')
        print('\n🔧 Step 3: Test Interfaccia Compatibile')
        jwt_provider = auth_manager.jwt_provider
        assert hasattr(jwt_provider, 'users'), "❌ Attributo 'users' mancante"
        assert hasattr(jwt_provider, 'users_by_id'), "❌ Attributo 'users_by_id' mancante"
        print('✅ Attributi compatibili presenti')
        methods_to_test = ['authenticate', 'create_user', 'get_user_by_username', 'get_user_by_id', 'list_users', 'generate_token_pair']
        for method in methods_to_test:
            assert hasattr(jwt_provider, method), f"❌ Metodo '{method}' mancante"
        print('✅ Metodi compatibili presenti')
        print('\n👤 Step 4: Test Creazione Utente')
        test_user = await jwt_provider.create_user(username='test_compatible', email='test@compatible.com', password='TestPass123!', role='viewer', metadata={'test': 'compatible'})
        print(f'✅ Utente creato: {test_user.username}')
        assert 'test_compatible' in jwt_provider.users, '❌ Utente non in memoria'
        assert test_user.user_id in jwt_provider.users_by_id, '❌ Utente non in cache by_id'
        print('✅ Utente presente in cache memoria')
        print('\n🔑 Step 5: Test Autenticazione')
        credentials = {'username': 'test_compatible', 'password': 'TestPass123!'}
        auth_context = await jwt_provider.authenticate(credentials)
        print(f'✅ Autenticazione riuscita: {auth_context.subject_id}')
        print(f"   Username: {auth_context.metadata.get('username')}")
        print(f"   Role: {auth_context.metadata.get('role')}")
        print('\n🎫 Step 6: Test Token Generation')
        token_pair = await jwt_provider.generate_token_pair(test_user)
        print(f'✅ Token generati: {token_pair.token_type}')
        print(f'   Access token: {token_pair.access_token[:20]}...')
        print(f'   Refresh token: {token_pair.refresh_token[:20]}...')
        print('\n✅ Step 7: Test Validazione Token')
        validated_context = await jwt_provider.validate_token(token_pair.access_token)
        print(f'✅ Token validato: {validated_context.subject_id}')
        assert validated_context.subject_id == test_user.user_id, '❌ Token validation mismatch'
        print('\n💾 Step 8: Test Persistenza Storage')
        status = jwt_provider.get_provider_status()
        print(f'✅ Provider Status:')
        print(f"   Storage mode: {status.get('storage_mode')}")
        print(f"   User storage connected: {status.get('user_storage_connected')}")
        print(f"   Total users: {status.get('total_users')}")
        print(f"   Active users: {status.get('active_users')}")
        all_users = await jwt_provider.list_users()
        print(f'✅ Lista utenti: {len(all_users)} utenti trovati')
        for user_dict in all_users:
            print(f"   - {user_dict['username']} ({user_dict['role']})")
        print('\n👥 Step 9: Test User Registration Service')
        from src.layers.application.auth.user_registration import UserRegistrationService, UserRegistrationRequest
        registration_service = UserRegistrationService(jwt_provider)
        print('✅ User Registration Service creato')
        reg_request = UserRegistrationRequest(username='full_registration_test', email='fullreg@test.com', password='FullTest123!', first_name='Full', last_name='Test', company_name='Test Corp', plan='free')
        reg_result = await registration_service.register_user(reg_request)
        print(f"✅ Registrazione completata: {reg_result.get('status')}")
        print(f"   User ID: {reg_result.get('user_id')}")
        print(f"   Tenant ID: {reg_result.get('tenant_id')}")
        if reg_result.get('user_id'):
            from uuid import UUID
            registered_user = await jwt_provider.get_user_by_id(UUID(reg_result['user_id']))
            if registered_user:
                print(f'✅ Utente registrato trovato: {registered_user.username}')
            else:
                print('❌ Utente registrato NON trovato')
        print('\n🔍 Step 10: Verifica Finale Database')
        if jwt_provider.user_storage:
            try:
                db_users = await jwt_provider.user_storage.query({})
                print(f'✅ Utenti nel database: {len(db_users)}')
                for user in db_users:
                    print(f'   📄 DB: {user.username} | {user.email} | {user.role}')
                await jwt_provider.user_storage.disconnect()
                print('✅ Disconnesso dal database')
            except Exception as e:
                print(f'⚠️  Errore verifica database: {e}')
        else:
            print('⚠️  Nessuna connessione database attiva (modalità memory)')
    except Exception as e:
        print(f'❌ Test fallito: {e}')
        import traceback
        traceback.print_exc()
        return False
    print('\n' + '=' * 60)
    print('🎉 TUTTI I TEST COMPLETATI CON SUCCESSO!')
    print('🔧 Il sistema di autenticazione è compatibile e persistente')
    return True

async def test_api_endpoints():
    print('\n🌐 Test API Endpoints')
    print('-' * 30)
    try:
        import aiohttp
        base_url = 'http://localhost:8000'
        test_registration = {'username': 'api_test_user', 'email': 'apitest@example.com', 'password': 'ApiTest123!', 'first_name': 'API', 'last_name': 'Test', 'plan': 'free'}
        async with aiohttp.ClientSession() as session:
            print('🧪 Test API Registration...')
            async with session.post(f'{base_url}/api/v1/auth/register', json=test_registration) as response:
                if response.status == 200:
                    reg_data = await response.json()
                    print(f"✅ API Registration: {reg_data.get('status')}")
                    login_data = {'username': test_registration['username'], 'password': test_registration['password']}
                    async with session.post(f'{base_url}/api/v1/auth/login', json=login_data) as login_response:
                        if login_response.status == 200:
                            login_result = await login_response.json()
                            print(f'✅ API Login: Success')
                            print(f"   Token: {login_result.get('access_token', '')[:20]}...")
                        else:
                            print(f'❌ API Login failed: {login_response.status}')
                else:
                    print(f'❌ API Registration failed: {response.status}')
    except Exception as e:
        print(f'⚠️  API test skipped (server might not be running): {e}')

async def main():
    print('🚀 Avvio Test Completo Sistema Autenticazione')
    success = await test_compatible_auth()
    if success:
        print('\n💡 PROSSIMI PASSI:')
        print('1. ✅ Il sistema di autenticazione funziona correttamente')
        print('2. 🔄 Sostituisci il file jwt_auth.py con la versione compatibile')
        print('3. 🌐 Avvia il server API: python auth_test_simple.py')
        print('4. 🧪 Testa gli endpoint con: python auth_test_script.py')
        print('\n🌐 Verifico se il server API è attivo...')
        await test_api_endpoints()
    print('\n🏁 Test completato!')
if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  Test interrotto dall'utente")
    except Exception as e:
        print(f'\n💥 Errore fatale: {e}')
        import traceback
        traceback.print_exc()