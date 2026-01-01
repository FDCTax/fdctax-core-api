#!/usr/bin/env python3
"""
Infrastructure Integration Tests for FDC Core Backend
Tests deployment readiness for MyFDC and FDC Tax integration

This test suite verifies:
1. Health Check Endpoints
2. CORS Configuration
3. Authentication & Role Mapping
4. End-to-End Transaction Flow
5. Response Headers
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

import aiohttp
import asyncpg

# Test configuration
BASE_URL = "https://tax-sync-core.preview.emergentagent.com/api"

# Test credentials as specified in the review request
TEST_CREDENTIALS = {
    "admin": {"email": "admin@fdctax.com", "password": "admin123"},
    "staff": {"email": "staff@fdctax.com", "password": "staff123"},
    "tax_agent": {"email": "taxagent@fdctax.com", "password": "taxagent123"},
    "client": {"email": "client@fdctax.com", "password": "client123"}
}

# CORS origins to test
CORS_ORIGINS_TO_TEST = [
    "https://fdctax.com",
    "https://myfdc.com", 
    "http://localhost:3000"
]

class InfrastructureTester:
    def __init__(self):
        self.session = None
        self.test_results = []
        self.tokens = {}  # Store tokens for each role
        
        # Test data storage
        self.test_transaction_id = None
        self.test_client_id = "test-client-infra-001"
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def log_test(self, test_name: str, success: bool, details: str = "", response_data: Any = None):
        """Log test result"""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        if details:
            print(f"    {details}")
        if not success and response_data:
            print(f"    Response: {response_data}")
        
        self.test_results.append({
            "test": test_name,
            "success": success,
            "details": details,
            "response": response_data if not success else None
        })
    
    async def test_health_endpoints(self):
        """Test 1: Health Check Endpoints"""
        print("\n=== Testing Health Check Endpoints ===")
        
        # Test basic health endpoint
        try:
            async with self.session.get(f"{BASE_URL}/") as response:
                data = await response.json()
                success = (response.status == 200 and 
                          data.get("status") == "healthy")
                self.log_test(
                    "GET /api/ - Basic health",
                    success,
                    f"Status: {response.status}, Response: {data.get('status')}"
                )
        except Exception as e:
            self.log_test("GET /api/ - Basic health", False, f"Error: {str(e)}")
        
        # Test detailed health endpoint
        try:
            async with self.session.get(f"{BASE_URL}/health") as response:
                data = await response.json()
                db_connected = (data.get("checks", {}).get("database", {}).get("status") == "connected")
                success = (response.status == 200 and db_connected)
                self.log_test(
                    "GET /api/health - Detailed health",
                    success,
                    f"Status: {response.status}, DB: {data.get('checks', {}).get('database', {}).get('status')}"
                )
        except Exception as e:
            self.log_test("GET /api/health - Detailed health", False, f"Error: {str(e)}")
        
        # Test Kubernetes readiness probe
        try:
            async with self.session.get(f"{BASE_URL}/health/ready") as response:
                data = await response.json()
                success = (response.status == 200 and 
                          data.get("status") == "ready")
                self.log_test(
                    "GET /api/health/ready - K8s readiness",
                    success,
                    f"Status: {response.status}, Ready: {data.get('status')}"
                )
        except Exception as e:
            self.log_test("GET /api/health/ready - K8s readiness", False, f"Error: {str(e)}")
        
        # Test Kubernetes liveness probe
        try:
            async with self.session.get(f"{BASE_URL}/health/live") as response:
                data = await response.json()
                success = (response.status == 200 and 
                          data.get("status") == "alive")
                self.log_test(
                    "GET /api/health/live - K8s liveness",
                    success,
                    f"Status: {response.status}, Alive: {data.get('status')}"
                )
        except Exception as e:
            self.log_test("GET /api/health/live - K8s liveness", False, f"Error: {str(e)}")
        
        # Test configuration status
        try:
            async with self.session.get(f"{BASE_URL}/config/status") as response:
                data = await response.json()
                cors_count = data.get("cors_origins_count", 0)
                success = (response.status == 200 and cors_count >= 6)
                self.log_test(
                    "GET /api/config/status - Configuration",
                    success,
                    f"Status: {response.status}, CORS origins: {cors_count}/6+"
                )
        except Exception as e:
            self.log_test("GET /api/config/status - Configuration", False, f"Error: {str(e)}")
    
    async def test_cors_verification(self):
        """Test 2: CORS Verification"""
        print("\n=== Testing CORS Verification ===")
        
        for origin in CORS_ORIGINS_TO_TEST:
            try:
                # Test OPTIONS preflight request
                headers = {
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Authorization, Content-Type"
                }
                
                async with self.session.options(f"{BASE_URL}/", headers=headers) as response:
                    # Check response headers
                    allow_origin = response.headers.get("Access-Control-Allow-Origin")
                    allow_credentials = response.headers.get("Access-Control-Allow-Credentials")
                    allow_methods = response.headers.get("Access-Control-Allow-Methods", "")
                    
                    origin_allowed = allow_origin == origin or allow_origin == "*"
                    credentials_allowed = allow_credentials == "true"
                    methods_ok = all(method in allow_methods for method in ["GET", "POST", "PATCH", "DELETE"])
                    
                    success = origin_allowed and credentials_allowed and methods_ok
                    
                    self.log_test(
                        f"CORS preflight for {origin}",
                        success,
                        f"Origin: {allow_origin}, Credentials: {allow_credentials}, Methods: {methods_ok}"
                    )
            except Exception as e:
                self.log_test(f"CORS preflight for {origin}", False, f"Error: {str(e)}")
    
    async def authenticate_user(self, role: str, credentials: Dict[str, str]) -> Optional[str]:
        """Authenticate and return token"""
        try:
            async with self.session.post(
                f"{BASE_URL}/auth/login",
                json=credentials
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    token = data.get("access_token")
                    if token:
                        self.tokens[role] = token
                    return token
                else:
                    error_text = await response.text()
                    print(f"Authentication failed for {role}: {response.status} - {error_text}")
                    return None
        except Exception as e:
            print(f"Authentication error for {role}: {e}")
            return None
    
    async def test_authentication_role_mapping(self):
        """Test 3: Authentication & Role Mapping"""
        print("\n=== Testing Authentication & Role Mapping ===")
        
        for role, credentials in TEST_CREDENTIALS.items():
            # Test authentication
            token = await self.authenticate_user(role, credentials)
            auth_success = token is not None
            
            self.log_test(
                f"Authentication - {role}",
                auth_success,
                f"Token: {'✓' if token else '✗'}"
            )
            
            if token:
                # Verify JWT token contains role claim
                try:
                    # Decode JWT payload (without verification for testing)
                    import base64
                    import json
                    
                    # Split token and decode payload
                    parts = token.split('.')
                    if len(parts) >= 2:
                        # Add padding if needed
                        payload = parts[1]
                        payload += '=' * (4 - len(payload) % 4)
                        decoded = base64.b64decode(payload)
                        jwt_data = json.loads(decoded)
                        
                        token_role = jwt_data.get("role")
                        expected_role = role if role != "tax_agent" else "tax_agent"  # Map role names
                        
                        role_correct = token_role == expected_role
                        self.log_test(
                            f"JWT role claim - {role}",
                            role_correct,
                            f"Expected: {expected_role}, Got: {token_role}"
                        )
                except Exception as e:
                    self.log_test(f"JWT role claim - {role}", False, f"Error decoding JWT: {str(e)}")
    
    async def make_authenticated_request(
        self, 
        method: str, 
        endpoint: str, 
        role: str, 
        json_data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> tuple[int, Any, Dict]:
        """Make authenticated API request and return status, data, headers"""
        token = self.tokens.get(role)
        if not token:
            return 401, "No token available", {}
        
        headers = {"Authorization": f"Bearer {token}"}
        
        try:
            async with self.session.request(
                method,
                f"{BASE_URL}{endpoint}",
                headers=headers,
                json=json_data,
                params=params
            ) as response:
                try:
                    data = await response.json()
                except:
                    data = await response.text()
                return response.status, data, dict(response.headers)
        except Exception as e:
            return 500, str(e), {}
    
    async def test_end_to_end_transaction_flow(self):
        """Test 4: End-to-End Transaction Flow"""
        print("\n=== Testing End-to-End Transaction Flow ===")
        
        # Step 1: MyFDC (client) creates transaction
        transaction_data = {
            "amount": 500.00,
            "gst_amount": 50.00,
            "description": "Infrastructure test transaction",
            "date": "2024-01-15",
            "category": "office_supplies",
            "vendor": "Test Vendor Ltd",
            "receipt_url": "https://example.com/receipt.pdf"
        }
        
        status, data, headers = await self.make_authenticated_request(
            "POST", f"/myfdc/transactions?client_id={self.test_client_id}", "client", transaction_data
        )
        
        create_success = status in [200, 201]
        if create_success:
            self.test_transaction_id = data.get("transaction", {}).get("id")
        
        self.log_test(
            "MyFDC transaction creation",
            create_success,
            f"Status: {status}, Transaction ID: {self.test_transaction_id if create_success else 'Failed'}"
        )
        
        if not self.test_transaction_id:
            self.log_test("End-to-End Flow", False, "Cannot continue without transaction ID")
            return
        
        # Step 2: FDC Tax (staff) lists transactions
        status, data, headers = await self.make_authenticated_request(
            "GET", "/bookkeeper/transactions", "staff", 
            params={"client_id": self.test_client_id}
        )
        
        list_success = status == 200 and isinstance(data.get("items"), list)
        transaction_found = False
        if list_success:
            transaction_found = any(tx.get("id") == self.test_transaction_id for tx in data.get("items", []))
        
        self.log_test(
            "FDC Tax transaction listing",
            list_success and transaction_found,
            f"Status: {status}, Transactions: {len(data.get('items', [])) if list_success else 0}, Found: {'✓' if transaction_found else '✗'}"
        )
        
        # Step 3: FDC Tax (staff) updates transaction
        update_data = {
            "category": "professional_services",
            "notes_bookkeeper": "Updated by infrastructure test"
        }
        
        status, data, headers = await self.make_authenticated_request(
            "PATCH", f"/bookkeeper/transactions/{self.test_transaction_id}", "staff", update_data
        )
        
        update_success = status == 200
        self.log_test(
            "FDC Tax transaction update",
            update_success,
            f"Status: {status}, Category: {data.get('category_bookkeeper') if update_success else 'Failed'}"
        )
        
        # Step 3.5: Create a workpaper job for locking (staff creates job)
        job_data = {
            "client_id": self.test_client_id,
            "year": "2024-25",
            "notes": "Infrastructure test workpaper job",
            "auto_create_modules": True
        }
        
        status, data, headers = await self.make_authenticated_request(
            "POST", "/workpaper/jobs", "staff", job_data
        )
        
        job_create_success = status in [200, 201]
        workpaper_job_id = None
        if job_create_success:
            workpaper_job_id = data.get("id")
        
        self.log_test(
            "Workpaper job creation",
            job_create_success,
            f"Status: {status}, Job ID: {workpaper_job_id if job_create_success else 'Failed'}"
        )
        
        if not workpaper_job_id:
            self.log_test("Tax Agent transaction lock", False, "Cannot lock without workpaper job")
            return
        
        # Step 4: Tax Agent locks transaction for workpaper
        lock_data = {
            "transaction_ids": [self.test_transaction_id],
            "workpaper_id": workpaper_job_id,
            "module": "GENERAL",
            "period": "2024-25"
        }
        
        status, data, headers = await self.make_authenticated_request(
            "POST", "/workpapers/transactions-lock", "tax_agent", lock_data
        )
        
        lock_success = status == 200
        self.log_test(
            "Tax Agent transaction lock",
            lock_success,
            f"Status: {status}, Locked: {data.get('locked_count', 0) if lock_success else 'Failed'}"
        )
    
    async def test_response_headers(self):
        """Test 5: Response Headers"""
        print("\n=== Testing Response Headers ===")
        
        # Test with a simple authenticated request
        if "staff" in self.tokens:
            status, data, headers = await self.make_authenticated_request(
                "GET", "/", "staff"
            )
            
            # Check for required headers
            request_id = headers.get("X-Request-ID") or headers.get("x-request-id")
            process_time = headers.get("X-Process-Time") or headers.get("x-process-time")
            
            self.log_test(
                "X-Request-ID header",
                request_id is not None,
                f"Present: {'✓' if request_id else '✗'}, Value: {request_id}"
            )
            
            self.log_test(
                "X-Process-Time header",
                process_time is not None,
                f"Present: {'✓' if process_time else '✗'}, Value: {process_time}ms"
            )
        else:
            self.log_test("Response Headers", False, "No staff token available for testing")
    
    async def run_all_tests(self):
        """Run all infrastructure tests"""
        print("🚀 Starting Infrastructure Integration Tests")
        print(f"Base URL: {BASE_URL}")
        print(f"Test Client: {self.test_client_id}")
        
        # Run test suites in order
        await self.test_health_endpoints()
        await self.test_cors_verification()
        await self.test_authentication_role_mapping()
        await self.test_end_to_end_transaction_flow()
        await self.test_response_headers()
        
        # Summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("📊 INFRASTRUCTURE TEST SUMMARY")
        print("="*60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results if result["success"])
        failed_tests = total_tests - passed_tests
        
        print(f"Total Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests}")
        print(f"❌ Failed: {failed_tests}")
        print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        if failed_tests > 0:
            print(f"\n🔍 FAILED TESTS:")
            for result in self.test_results:
                if not result["success"]:
                    print(f"  ❌ {result['test']}")
                    if result["details"]:
                        print(f"     {result['details']}")
        
        print("\n" + "="*60)
        
        # Deployment readiness assessment
        critical_failures = []
        for result in self.test_results:
            if not result["success"]:
                test_name = result["test"]
                if any(keyword in test_name.lower() for keyword in ["health", "cors", "authentication"]):
                    critical_failures.append(test_name)
        
        if critical_failures:
            print("🚨 CRITICAL FAILURES - NOT READY FOR DEPLOYMENT:")
            for failure in critical_failures:
                print(f"   - {failure}")
        else:
            print("✅ DEPLOYMENT READY - All critical infrastructure tests passed")


async def main():
    """Main test runner"""
    async with InfrastructureTester() as tester:
        await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())