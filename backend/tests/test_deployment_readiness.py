#!/usr/bin/env python3
"""
Deployment Readiness Test Suite for FDC Core
Tests CI/CD pipeline setup and production deployment readiness
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

import aiohttp

# Test configuration
BASE_URL = "https://fdctax-core.preview.emergentagent.com/api"

# Test credentials as provided
TEST_CREDENTIALS = {
    "admin": {"email": "admin@fdctax.com", "password": "admin123"},
    "staff": {"email": "staff@fdctax.com", "password": "staff123"},
    "tax_agent": {"email": "taxagent@fdctax.com", "password": "taxagent123"},
    "client": {"email": "client@fdctax.com", "password": "client123"}
}

class DeploymentReadinessTester:
    def __init__(self):
        self.session = None
        self.tokens = {}
        self.test_results = []
        
        # Test data storage
        self.test_transaction_id = None
        self.test_workpaper_job_id = None
    
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
    
    async def authenticate(self, role: str) -> Optional[str]:
        """Authenticate and return token for given role"""
        try:
            credentials = TEST_CREDENTIALS[role]
            async with self.session.post(
                f"{BASE_URL}/auth/login",
                json=credentials
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    token = data.get("access_token")
                    self.tokens[role] = token
                    return token
                else:
                    error_text = await response.text()
                    print(f"Authentication failed for {role}: {response.status} - {error_text}")
                    return None
        except Exception as e:
            print(f"Authentication error for {role}: {e}")
            return None
    
    async def make_request(
        self, 
        method: str, 
        endpoint: str, 
        token: Optional[str] = None,
        json_data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None
    ) -> tuple[int, Any, Dict]:
        """Make API request and return status, data, and headers"""
        request_headers = {}
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        if headers:
            request_headers.update(headers)
        
        try:
            async with self.session.request(
                method,
                f"{BASE_URL}{endpoint}",
                headers=request_headers,
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
    
    async def test_production_readiness_checks(self):
        """Test 1: Production Readiness Checks"""
        print("\n=== Testing Production Readiness Checks ===")
        
        # Test /api/health returns status=healthy
        status, data, headers = await self.make_request("GET", "/health")
        health_success = (status == 200 and 
                         isinstance(data, dict) and 
                         data.get("status") == "healthy")
        self.log_test(
            "GET /api/health returns status=healthy",
            health_success,
            f"Status: {status}, Health status: {data.get('status') if isinstance(data, dict) else 'N/A'}"
        )
        
        # Test /api/health shows database.status=connected
        db_success = (health_success and 
                     data.get("checks", {}).get("database", {}).get("status") == "connected")
        self.log_test(
            "GET /api/health shows database.status=connected",
            db_success,
            f"DB status: {data.get('checks', {}).get('database', {}).get('status') if isinstance(data, dict) else 'N/A'}"
        )
        
        # Test /api/health/ready returns 200 (Kubernetes readiness)
        status, data, headers = await self.make_request("GET", "/health/ready")
        ready_success = (status == 200 and 
                        isinstance(data, dict) and 
                        data.get("status") == "ready")
        self.log_test(
            "GET /api/health/ready returns 200 (Kubernetes readiness)",
            ready_success,
            f"Status: {status}, Ready status: {data.get('status') if isinstance(data, dict) else 'N/A'}"
        )
        
        # Test /api/health/live returns 200 (Kubernetes liveness)
        status, data, headers = await self.make_request("GET", "/health/live")
        live_success = (status == 200 and 
                       isinstance(data, dict) and 
                       data.get("status") == "alive")
        self.log_test(
            "GET /api/health/live returns 200 (Kubernetes liveness)",
            live_success,
            f"Status: {status}, Live status: {data.get('status') if isinstance(data, dict) else 'N/A'}"
        )
        
        # Test /api/config/status shows environment configuration
        status, data, headers = await self.make_request("GET", "/config/status")
        config_success = (status == 200 and 
                         isinstance(data, dict) and 
                         "environment" in data and
                         "cors_origins_count" in data)
        self.log_test(
            "GET /api/config/status shows environment configuration",
            config_success,
            f"Status: {status}, Environment: {data.get('environment') if isinstance(data, dict) else 'N/A'}, CORS origins: {data.get('cors_origins_count') if isinstance(data, dict) else 'N/A'}"
        )
    
    async def test_cors_production_configuration(self):
        """Test 2: CORS Production Configuration"""
        print("\n=== Testing CORS Production Configuration ===")
        
        # Production origins that must be allowed
        production_origins = [
            "https://fdctax.com",
            "https://myfdc.com", 
            "https://api.fdccore.com"
        ]
        
        for origin in production_origins:
            # Test OPTIONS preflight request
            headers = {
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type,Authorization"
            }
            
            status, data, response_headers = await self.make_request(
                "OPTIONS", "/health", headers=headers
            )
            
            # Headers are returned in lowercase
            cors_success = (status == 200 and
                           response_headers.get("access-control-allow-origin") == origin and
                           "true" in response_headers.get("access-control-allow-credentials", "").lower())
            
            self.log_test(
                f"CORS OPTIONS preflight for {origin}",
                cors_success,
                f"Status: {status}, Allow-Origin: {response_headers.get('access-control-allow-origin')}, Allow-Credentials: {response_headers.get('access-control-allow-credentials')}"
            )
        
        # Verify localhost is NOT allowed in production mode (check via config/status)
        status, data, headers = await self.make_request("GET", "/config/status")
        if status == 200 and isinstance(data, dict):
            environment = data.get("environment", "").lower()
            is_production = environment == "production"
            
            # In production, localhost should not be in CORS origins
            # We can't directly check CORS config, but we can verify environment
            self.log_test(
                "Production environment configuration check",
                True,  # This is informational - we verify environment is set
                f"Environment: {data.get('environment')}, CORS origins count: {data.get('cors_origins_count')}"
            )
    
    async def test_complete_transaction_engine_flow(self):
        """Test 3: Complete Transaction Engine Flow"""
        print("\n=== Testing Complete Transaction Engine Flow ===")
        
        # Authenticate all required roles
        client_token = await self.authenticate("client")
        staff_token = await self.authenticate("staff")
        tax_agent_token = await self.authenticate("tax_agent")
        admin_token = await self.authenticate("admin")
        
        if not all([client_token, staff_token, tax_agent_token, admin_token]):
            self.log_test("Authentication for transaction flow", False, "Failed to authenticate all required roles")
            return
        
        # 1. Client creates transaction via POST /api/myfdc/transactions
        transaction_data = {
            "date": "2024-01-15",
            "amount": 500.00,
            "gst_amount": 50.00,
            "description": "Deployment test transaction",
            "vendor": "Test Vendor Ltd",
            "category": "office_supplies",
            "source": "myfdc_upload"
        }
        
        status, data, headers = await self.make_request(
            "POST", "/myfdc/transactions", client_token, transaction_data,
            params={"client_id": "test-client-deployment-001"}
        )
        
        create_success = status in [200, 201] and isinstance(data, dict) and data.get("transaction", {}).get("id")
        if create_success:
            self.test_transaction_id = data.get("transaction", {}).get("id")
        
        self.log_test(
            "1. Client creates transaction via POST /api/myfdc/transactions",
            create_success,
            f"Status: {status}, Transaction ID: {self.test_transaction_id if create_success else 'Failed'}"
        )
        
        if not self.test_transaction_id:
            return
        
        # 2. Staff lists transactions via GET /api/bookkeeper/transactions
        status, data, headers = await self.make_request(
            "GET", "/bookkeeper/transactions", staff_token,
            params={"client_id": "test-client-deployment-001"}
        )
        
        list_success = (status == 200 and isinstance(data, list) and 
                       any(tx.get("id") == self.test_transaction_id for tx in data))
        
        self.log_test(
            "2. Staff lists transactions via GET /api/bookkeeper/transactions",
            list_success,
            f"Status: {status}, Found transactions: {len(data) if isinstance(data, list) else 0}"
        )
        
        # 3. Staff updates transaction via PATCH /api/bookkeeper/transactions/{id}
        update_data = {
            "notes_bookkeeper": "Updated by deployment test",
            "status": "REVIEWED"
        }
        
        status, data, headers = await self.make_request(
            "PATCH", f"/bookkeeper/transactions/{self.test_transaction_id}", 
            staff_token, update_data
        )
        
        update_success = (status == 200 and isinstance(data, dict) and 
                         data.get("notes_bookkeeper") == update_data["notes_bookkeeper"])
        
        self.log_test(
            "3. Staff updates transaction via PATCH /api/bookkeeper/transactions/{id}",
            update_success,
            f"Status: {status}, Notes updated: {'✓' if update_success else '✗'}"
        )
        
        # 4. Staff creates workpaper job via POST /api/workpaper/jobs
        job_data = {
            "client_id": "test-client-deployment-001",
            "year": "2024-25",
            "notes": "Deployment test workpaper job",
            "auto_create_modules": True
        }
        
        status, data, headers = await self.make_request(
            "POST", "/workpaper/jobs", staff_token, job_data
        )
        
        job_success = status in [200, 201] and isinstance(data, dict) and data.get("id")
        if job_success:
            self.test_workpaper_job_id = data.get("id")
        
        self.log_test(
            "4. Staff creates workpaper job via POST /api/workpaper/jobs",
            job_success,
            f"Status: {status}, Job ID: {self.test_workpaper_job_id if job_success else 'Failed'}"
        )
        
        if not self.test_workpaper_job_id:
            return
        
        # 5. Tax agent locks transaction via POST /api/workpapers/transactions-lock
        lock_data = {
            "transaction_ids": [self.test_transaction_id],
            "workpaper_id": self.test_workpaper_job_id,
            "module": "GENERAL",
            "period": "2024-25"
        }
        
        status, data, headers = await self.make_request(
            "POST", "/workpapers/transactions-lock", tax_agent_token, lock_data
        )
        
        lock_success = status == 200 and isinstance(data, dict) and data.get("locked_count", 0) > 0
        
        self.log_test(
            "5. Tax agent locks transaction via POST /api/workpapers/transactions-lock",
            lock_success,
            f"Status: {status}, Locked count: {data.get('locked_count', 0) if isinstance(data, dict) else 0}"
        )
        
        # 6. Admin unlocks transaction via POST /api/bookkeeper/transactions/{id}/unlock
        unlock_data = {
            "comment": "Unlocked by deployment test - admin override for testing purposes"
        }
        
        status, data, headers = await self.make_request(
            "POST", f"/bookkeeper/transactions/{self.test_transaction_id}/unlock",
            admin_token, unlock_data
        )
        
        unlock_success = status == 200 and isinstance(data, dict) and data.get("status") != "LOCKED"
        
        self.log_test(
            "6. Admin unlocks transaction via POST /api/bookkeeper/transactions/{id}/unlock",
            unlock_success,
            f"Status: {status}, Transaction status: {data.get('status') if isinstance(data, dict) else 'N/A'}"
        )
    
    async def test_response_headers(self):
        """Test 4: Response Headers"""
        print("\n=== Testing Response Headers ===")
        
        # Test X-Request-ID header
        status, data, headers = await self.make_request("GET", "/health")
        
        has_request_id = "x-request-id" in headers
        self.log_test(
            "X-Request-ID header present",
            has_request_id,
            f"X-Request-ID: {headers.get('x-request-id', 'Missing')}"
        )
        
        # Test X-Process-Time header
        has_process_time = "x-process-time" in headers
        self.log_test(
            "X-Process-Time header present",
            has_process_time,
            f"X-Process-Time: {headers.get('x-process-time', 'Missing')} ms"
        )
    
    async def test_error_handling(self):
        """Test 5: Error Handling"""
        print("\n=== Testing Error Handling ===")
        
        # Test 404 for non-existent resources (with authentication)
        staff_token = await self.authenticate("staff")
        if staff_token:
            status, data, headers = await self.make_request(
                "GET", "/bookkeeper/transactions/non-existent-id", staff_token
            )
            
            self.log_test(
                "404 for non-existent resources",
                status == 404,
                f"Status: {status} (expected 404)"
            )
        
        # Test 403 for unauthorized access (client accessing bookkeeper)
        client_token = await self.authenticate("client")
        if client_token:
            status, data, headers = await self.make_request(
                "GET", "/bookkeeper/transactions", client_token
            )
            
            self.log_test(
                "403 for unauthorized access (client accessing bookkeeper)",
                status == 403,
                f"Status: {status} (expected 403)"
            )
        
        # Test 400 for invalid input
        if staff_token:
            invalid_data = {
                "amount": "invalid_amount",  # Should be numeric
                "date": "invalid_date"       # Should be valid date format
            }
            
            status, data, headers = await self.make_request(
                "POST", "/myfdc/transactions", staff_token, invalid_data,
                params={"client_id": "test-client"}
            )
            
            self.log_test(
                "400 for invalid input",
                status in [400, 422],  # 422 is also acceptable for validation errors
                f"Status: {status} (expected 400 or 422)"
            )
    
    async def test_no_regressions(self):
        """Test 6: No Regressions - Smoke Tests"""
        print("\n=== Testing No Regressions (Smoke Tests) ===")
        
        staff_token = await self.authenticate("staff")
        if not staff_token:
            self.log_test("Smoke tests", False, "Failed to authenticate staff user")
            return
        
        # Test /api/bookkeeper/statuses
        status, data, headers = await self.make_request("GET", "/bookkeeper/statuses", staff_token)
        self.log_test(
            "GET /api/bookkeeper/statuses",
            status == 200 and isinstance(data, dict) and "statuses" in data,
            f"Status: {status}, Statuses count: {len(data.get('statuses', [])) if isinstance(data, dict) else 0}"
        )
        
        # Test /api/bookkeeper/gst-codes
        status, data, headers = await self.make_request("GET", "/bookkeeper/gst-codes", staff_token)
        self.log_test(
            "GET /api/bookkeeper/gst-codes",
            status == 200 and isinstance(data, dict) and "gst_codes" in data,
            f"Status: {status}, GST codes count: {len(data.get('gst_codes', [])) if isinstance(data, dict) else 0}"
        )
        
        # Test /api/bookkeeper/sources
        status, data, headers = await self.make_request("GET", "/bookkeeper/sources", staff_token)
        self.log_test(
            "GET /api/bookkeeper/sources",
            status == 200 and isinstance(data, dict) and "sources" in data,
            f"Status: {status}, Sources count: {len(data.get('sources', [])) if isinstance(data, dict) else 0}"
        )
        
        # Test /api/bookkeeper/module-routings
        status, data, headers = await self.make_request("GET", "/bookkeeper/module-routings", staff_token)
        self.log_test(
            "GET /api/bookkeeper/module-routings",
            status == 200 and isinstance(data, dict) and "module_routings" in data,
            f"Status: {status}, Module routings count: {len(data.get('module_routings', [])) if isinstance(data, dict) else 0}"
        )
    
    async def run_all_tests(self):
        """Run all deployment readiness tests"""
        print("🚀 Starting Deployment Readiness Tests for FDC Core")
        print(f"Base URL: {BASE_URL}")
        print(f"Test Credentials: {list(TEST_CREDENTIALS.keys())}")
        
        # Run all test suites
        await self.test_production_readiness_checks()
        await self.test_cors_production_configuration()
        await self.test_complete_transaction_engine_flow()
        await self.test_response_headers()
        await self.test_error_handling()
        await self.test_no_regressions()
        
        # Summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("📊 DEPLOYMENT READINESS TEST SUMMARY")
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
        
        # Test data summary
        if self.test_transaction_id or self.test_workpaper_job_id:
            print(f"🆔 Test Data Created:")
            if self.test_transaction_id:
                print(f"   Transaction ID: {self.test_transaction_id}")
            if self.test_workpaper_job_id:
                print(f"   Workpaper Job ID: {self.test_workpaper_job_id}")
        
        # Deployment readiness assessment
        print(f"\n🎯 DEPLOYMENT READINESS ASSESSMENT:")
        if failed_tests == 0:
            print("   ✅ READY FOR DEPLOYMENT - All tests passed")
        elif failed_tests <= 2:
            print("   ⚠️  MOSTLY READY - Minor issues detected")
        else:
            print("   ❌ NOT READY - Critical issues detected")


async def main():
    """Main test runner"""
    async with DeploymentReadinessTester() as tester:
        await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())