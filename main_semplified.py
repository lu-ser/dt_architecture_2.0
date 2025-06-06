# quick_test.py - TEST VELOCE DEL PLATFORM

import asyncio
import httpx
import json
from datetime import datetime

async def quick_test():
    """Test veloce per verificare che il platform funzioni"""
    base_url = "http://localhost:8000"
    
    print("🚀 Quick Digital Twin Platform Test")
    print("=" * 50)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # 1. Test Health Check
            print("🏥 Testing Health Check...")
            response = await client.get(f"{base_url}/health/simple")
            
            if response.status_code == 200:
                health = response.json()
                print(f"   ✅ Health: {health['status']} - {health['message']}")
            else:
                print(f"   ❌ Health check failed: {response.status_code}")
                return
            
            # 2. Test Main Health
            print("🔍 Testing Main Health...")
            response = await client.get(f"{base_url}/health")
            
            if response.status_code == 200:
                health = response.json()
                print(f"   ✅ Main Health: {health['status']}")
                print(f"   🌐 Gateway Ready: {health.get('gateway_ready', 'unknown')}")
                print(f"   🔐 Auth Status: {health.get('auth', {}).get('status', 'unknown')}")
            else:
                print(f"   ⚠️  Main health failed: {response.status_code}")
            
            # 3. Test Root Endpoint
            print("🏠 Testing Root Endpoint...")
            response = await client.get(f"{base_url}/")
            
            if response.status_code == 200:
                root = response.json()
                print(f"   ✅ Platform: {root['name']} v{root['version']}")
                print(f"   📚 Docs: {base_url}{root['documentation']}")
                print(f"   🔒 Secure Twins: {root['endpoints'].get('secure_digital_twins', 'Not available')}")
            else:
                print(f"   ❌ Root endpoint failed: {response.status_code}")
            
            # 4. Test Route Discovery
            print("🔍 Testing Route Discovery...")
            response = await client.get(f"{base_url}/debug/routes")
            
            if response.status_code == 200:
                routes = response.json()
                print(f"   ✅ Total routes: {routes['total_routes']}")
                print(f"   ✅ Successful routers: {routes['successful_routers']}")
                
                if routes['failed_routers']:
                    print(f"   ⚠️  Failed routers: {routes['failed_routers']}")
                
                # Find secure routes
                secure_routes = [r for r in routes['routes'] if 'secure' in r['path']]
                if secure_routes:
                    print(f"   🔒 Secure routes found: {len(secure_routes)}")
                    for route in secure_routes[:3]:  # Show first 3
                        print(f"      - {route['methods']} {route['path']}")
                else:
                    print(f"   ⚠️  No secure routes found")
            else:
                print(f"   ⚠️  Route discovery failed: {response.status_code}")
            
            # 5. Test User Registration (if auth available)
            print("👤 Testing User Registration...")
            user_data = {
                "username": f"test_user_{int(datetime.utcnow().timestamp())}",
                "email": f"test_{int(datetime.utcnow().timestamp())}@example.com",
                "password": "TestPass123!",
                "first_name": "Test",
                "last_name": "User",
                "plan": "free"
            }
            
            response = await client.post(f"{base_url}/api/v1/auth/register", json=user_data)
            
            if response.status_code == 200:
                reg_data = response.json()
                print(f"   ✅ User registered: {reg_data.get('status', 'unknown')}")
                
                # Test login if registration successful
                if reg_data.get('status') == 'registration_complete' and 'tokens' in reg_data:
                    token = reg_data['tokens']['access_token']
                    print(f"   🔑 Got access token: ...{token[-10:]}")
                    
                    # Test secure endpoint access
                    print("🔒 Testing Secure Endpoint Access...")
                    headers = {"Authorization": f"Bearer {token}"}
                    
                    response = await client.get(
                        f"{base_url}/api/v1/secure/digital-twins/security/status",
                        headers=headers
                    )
                    
                    if response.status_code == 200:
                        security = response.json()
                        print(f"   ✅ Security status: {security.get('security_enabled', 'unknown')}")
                        print(f"   🏢 Tenant isolation: {security.get('tenant_isolation_enabled', 'unknown')}")
                    else:
                        print(f"   ⚠️  Security status failed: {response.status_code}")
                        # Don't fail the test, might be permission issue
                
            elif response.status_code == 422:
                print(f"   ⚠️  Registration failed (validation): {response.text}")
            else:
                print(f"   ⚠️  Registration failed: {response.status_code}")
            
            # 6. Test Legacy Digital Twins Endpoint
            print("🔷 Testing Legacy Digital Twins...")
            response = await client.get(f"{base_url}/api/v1/digital-twins/types/available")
            
            if response.status_code == 200:
                types = response.json()
                print(f"   ✅ Available twin types: {len(types.get('twin_types', []))}")
                print(f"   ✅ Available capabilities: {len(types.get('capabilities', []))}")
            else:
                print(f"   ⚠️  Legacy twins endpoint failed: {response.status_code}")
            
            print("\n" + "=" * 50)
            print("✨ Quick test completed!")
            print("🎯 Platform is running and accessible")
            print(f"📚 Visit {base_url}/docs for API documentation")
            print(f"🔒 Secure endpoints: {base_url}/api/v1/secure/digital-twins/")
            
        except httpx.ConnectError:
            print("❌ Connection failed - is the server running?")
            print("   Start with: python main.py")
        except Exception as e:
            print(f"❌ Test failed: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(quick_test())