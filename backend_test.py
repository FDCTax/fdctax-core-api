#!/usr/bin/env python3
"""
Comprehensive Backend Test Suite for LodgeIT Integration Module
Tests all LodgeIT endpoints with RBAC authentication
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
BASE_URL = "https://lodgeit-sync.preview.emergentagent.com/api"

# Test credentials for RBAC testing
ADMIN_CREDENTIALS = {"email": "admin@fdctax.com", "password": "admin123"}
TAX_AGENT_CREDENTIALS = {"email": "taxagent@fdctax.com", "password": "taxagent123"}
STAFF_CREDENTIALS = {"email": "staff@fdctax.com", "password": "staff123"}
CLIENT_CREDENTIALS = {"email": "client@fdctax.com", "password": "client123"}

# Test data
TEST_JOB_ID = "4fc51694-ebaf-40a0-a358-62da0d4fb9d7"
TEST_CLIENT_ID = "test-client-001"
TEST_YEAR = "2024-25"

# New test data for comprehensive testing
NEW_CLIENT_ID = "test-client-002"
NEW_YEAR = "2023-24"

class WorkpaperAPITester:
    def __init__(self):
        self.session = None
        self.staff_token = None
        self.admin_token = None
        self.test_results = []
        
        # Test data storage
        self.new_job_id = None
        self.new_module_id = None
        self.new_transaction_id = None
        self.new_query_id = None
        self.new_snapshot_id = None
    
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
    
    async def authenticate(self, credentials: Dict[str, str]) -> Optional[str]:
        """Authenticate and return token"""
        try:
            async with self.session.post(
                f"{BASE_URL}/auth/login",
                json=credentials
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("access_token")
                else:
                    error_text = await response.text()
                    print(f"Authentication failed: {response.status} - {error_text}")
                    return None
        except Exception as e:
            print(f"Authentication error: {e}")
            return None
    
    async def make_request(
        self, 
        method: str, 
        endpoint: str, 
        token: str, 
        json_data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> tuple[int, Any]:
        """Make authenticated API request"""
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
                return response.status, data
        except Exception as e:
            return 500, str(e)
    
    async def test_authentication(self):
        """Test 1: Authentication"""
        print("\n=== Testing Authentication ===")
        
        # Test staff login
        self.staff_token = await self.authenticate(STAFF_CREDENTIALS)
        self.log_test(
            "Staff Authentication",
            self.staff_token is not None,
            f"Token: {'✓' if self.staff_token else '✗'}"
        )
        
        # Test admin login
        self.admin_token = await self.authenticate(ADMIN_CREDENTIALS)
        self.log_test(
            "Admin Authentication",
            self.admin_token is not None,
            f"Token: {'✓' if self.admin_token else '✗'}"
        )
        
        return self.staff_token and self.admin_token
    
    async def test_reference_data(self):
        """Test 2-4: Reference Data (No auth required)"""
        print("\n=== Testing Reference Data ===")
        
        # Test module types
        status, data = await self.make_request("GET", "/workpaper/module-types", "")
        self.log_test(
            "GET /workpaper/module-types",
            status == 200 and "module_types" in data,
            f"Status: {status}, Types count: {len(data.get('module_types', []))}"
        )
        
        # Test transaction categories
        status, data = await self.make_request("GET", "/workpaper/transaction-categories", "")
        self.log_test(
            "GET /workpaper/transaction-categories",
            status == 200 and "categories" in data,
            f"Status: {status}, Categories count: {len(data.get('categories', []))}"
        )
        
        # Test job statuses
        status, data = await self.make_request("GET", "/workpaper/job-statuses", "")
        self.log_test(
            "GET /workpaper/job-statuses",
            status == 200 and "statuses" in data,
            f"Status: {status}, Statuses count: {len(data.get('statuses', []))}"
        )
    
    async def test_existing_job_operations(self):
        """Test 5-8: Existing Job Operations"""
        print("\n=== Testing Existing Job Operations ===")
        
        # Test get existing job
        status, data = await self.make_request("GET", f"/workpaper/jobs/{TEST_JOB_ID}", self.staff_token)
        self.log_test(
            f"GET /workpaper/jobs/{TEST_JOB_ID}",
            status == 200 and data.get("id") == TEST_JOB_ID,
            f"Status: {status}, Job ID: {data.get('id') if status == 200 else 'N/A'}"
        )
        
        # Test get job by client/year
        status, data = await self.make_request("GET", f"/workpaper/clients/{TEST_CLIENT_ID}/jobs/{TEST_YEAR}", self.staff_token)
        self.log_test(
            f"GET /workpaper/clients/{TEST_CLIENT_ID}/jobs/{TEST_YEAR}",
            status == 200 and data.get("client_id") == TEST_CLIENT_ID,
            f"Status: {status}, Client: {data.get('client_id') if status == 200 else 'N/A'}"
        )
        
        # Test list client jobs
        status, data = await self.make_request("GET", f"/workpaper/clients/{TEST_CLIENT_ID}/jobs", self.staff_token)
        self.log_test(
            f"GET /workpaper/clients/{TEST_CLIENT_ID}/jobs",
            status == 200 and isinstance(data, list),
            f"Status: {status}, Jobs count: {len(data) if status == 200 else 0}"
        )
        
        # Test update job
        update_data = {"notes": f"Updated at {datetime.now().isoformat()}"}
        status, data = await self.make_request("PATCH", f"/workpaper/jobs/{TEST_JOB_ID}", self.staff_token, update_data)
        self.log_test(
            f"PATCH /workpaper/jobs/{TEST_JOB_ID}",
            status == 200 and data.get("notes") == update_data["notes"],
            f"Status: {status}, Notes updated: {'✓' if status == 200 else '✗'}"
        )
    
    async def test_new_job_creation(self):
        """Test 9: Create New Job with Auto-modules"""
        print("\n=== Testing New Job Creation ===")
        
        job_data = {
            "client_id": NEW_CLIENT_ID,
            "year": NEW_YEAR,
            "notes": "Test job created by automated test",
            "auto_create_modules": True
        }
        
        status, data = await self.make_request("POST", "/workpaper/jobs", self.staff_token, job_data)
        success = status == 201 or status == 200
        
        if success:
            self.new_job_id = data.get("id")
        
        self.log_test(
            "POST /workpaper/jobs (with auto_create_modules=true)",
            success and self.new_job_id is not None,
            f"Status: {status}, Job ID: {self.new_job_id if success else 'Failed'}"
        )
        
        # Verify modules were auto-created
        if self.new_job_id:
            status, modules = await self.make_request("GET", f"/workpaper/clients/{NEW_CLIENT_ID}/jobs/{NEW_YEAR}/modules", self.staff_token)
            self.log_test(
                "Auto-created modules verification",
                status == 200 and len(modules) == 9,
                f"Status: {status}, Modules created: {len(modules) if status == 200 else 0}/9"
            )
            
            if status == 200 and modules:
                self.new_module_id = modules[0]["id"]  # Store first module for later tests
    
    async def test_module_operations(self):
        """Test 10-12: Module Operations"""
        print("\n=== Testing Module Operations ===")
        
        if not self.new_module_id:
            self.log_test("Module Operations", False, "No module ID available from previous tests")
            return
        
        # Test get module detail
        status, data = await self.make_request("GET", f"/workpaper/modules/{self.new_module_id}", self.staff_token)
        self.log_test(
            f"GET /workpaper/modules/{self.new_module_id}",
            status == 200 and data.get("module", {}).get("id") == self.new_module_id,
            f"Status: {status}, Module type: {data.get('module', {}).get('module_type') if status == 200 else 'N/A'}"
        )
        
        # Test update module
        update_data = {
            "config": {"test_setting": "automated_test_value"},
            "status": "in_progress"
        }
        status, data = await self.make_request("PATCH", f"/workpaper/modules/{self.new_module_id}", self.staff_token, update_data)
        self.log_test(
            f"PATCH /workpaper/modules/{self.new_module_id}",
            status == 200 and data.get("status") == "in_progress",
            f"Status: {status}, Updated status: {data.get('status') if status == 200 else 'N/A'}"
        )
        
        # Test get effective transactions (should be empty initially)
        status, data = await self.make_request("GET", f"/workpaper/modules/{self.new_module_id}/effective-transactions", self.staff_token)
        self.log_test(
            f"GET /workpaper/modules/{self.new_module_id}/effective-transactions",
            status == 200 and isinstance(data, list),
            f"Status: {status}, Transactions count: {len(data) if status == 200 else 0}"
        )
    
    async def test_transaction_operations(self):
        """Test 13-15: Transaction Operations"""
        print("\n=== Testing Transaction Operations ===")
        
        if not self.new_job_id or not self.new_module_id:
            self.log_test("Transaction Operations", False, "Missing job or module ID from previous tests")
            return
        
        # Create transaction
        transaction_data = {
            "client_id": NEW_CLIENT_ID,
            "job_id": self.new_job_id,
            "module_instance_id": self.new_module_id,
            "source": "manual",
            "date": "2024-01-15",
            "amount": 250.00,
            "gst_amount": 25.00,
            "category": "office_supplies",
            "description": "Test office supplies purchase",
            "vendor": "Test Vendor Pty Ltd"
        }
        
        status, data = await self.make_request("POST", "/workpaper/transactions", self.staff_token, transaction_data)
        success = status == 201 or status == 200
        
        if success:
            self.new_transaction_id = data.get("id")
        
        self.log_test(
            "POST /workpaper/transactions",
            success and self.new_transaction_id is not None,
            f"Status: {status}, Transaction ID: {self.new_transaction_id if success else 'Failed'}"
        )
        
        # List transactions by job
        status, data = await self.make_request("GET", "/workpaper/transactions", self.staff_token, params={"job_id": self.new_job_id})
        self.log_test(
            f"GET /workpaper/transactions?job_id={self.new_job_id}",
            status == 200 and isinstance(data, list) and len(data) > 0,
            f"Status: {status}, Transactions found: {len(data) if status == 200 else 0}"
        )
        
        # List transactions by module
        status, data = await self.make_request("GET", "/workpaper/transactions", self.staff_token, params={"module_instance_id": self.new_module_id})
        self.log_test(
            f"GET /workpaper/transactions?module_instance_id={self.new_module_id}",
            status == 200 and isinstance(data, list) and len(data) > 0,
            f"Status: {status}, Module transactions: {len(data) if status == 200 else 0}"
        )
    
    async def test_override_operations(self):
        """Test 16-17: Override Operations"""
        print("\n=== Testing Override Operations ===")
        
        if not self.new_transaction_id or not self.new_job_id or not self.new_module_id:
            self.log_test("Override Operations", False, "Missing required IDs from previous tests")
            return
        
        # Create transaction override
        override_data = {
            "transaction_id": self.new_transaction_id,
            "job_id": self.new_job_id,
            "overridden_business_pct": 50.0,
            "reason": "Only 50% business use for this expense"
        }
        
        status, data = await self.make_request("POST", "/workpaper/overrides/transaction", self.staff_token, override_data)
        success = status == 201 or status == 200
        
        self.log_test(
            "POST /workpaper/overrides/transaction",
            success,
            f"Status: {status}, Business %: {data.get('overridden_business_pct') if success else 'Failed'}"
        )
        
        # Create module override
        module_override_data = {
            "module_instance_id": self.new_module_id,
            "field_key": "effective_pct",
            "original_value": 100,
            "effective_value": 75,
            "reason": "Adjusted percentage based on usage analysis"
        }
        
        status, data = await self.make_request("POST", "/workpaper/overrides/module", self.staff_token, module_override_data)
        success = status == 201 or status == 200
        
        self.log_test(
            "POST /workpaper/overrides/module",
            success,
            f"Status: {status}, Field: {data.get('field_key') if success else 'Failed'}"
        )
        
        # Verify effective transactions now show override
        status, data = await self.make_request("GET", f"/workpaper/modules/{self.new_module_id}/effective-transactions", self.staff_token)
        has_override = False
        if status == 200 and data:
            for tx in data:
                if tx.get("has_override"):
                    has_override = True
                    break
        
        self.log_test(
            "Verify effective transactions with overrides",
            status == 200 and has_override,
            f"Status: {status}, Override applied: {'✓' if has_override else '✗'}"
        )
    
    async def test_query_operations(self):
        """Test 18-22: Query Operations"""
        print("\n=== Testing Query Operations ===")
        
        if not self.new_job_id:
            self.log_test("Query Operations", False, "Missing job ID from previous tests")
            return
        
        # Create query
        status, data = await self.make_request(
            "POST", 
            f"/workpaper/jobs/{self.new_job_id}/queries",
            self.staff_token,
            params={"title": "Test Query for Automated Testing", "initial_message": "This is a test query created by automation"}
        )
        success = status == 201 or status == 200
        
        if success:
            self.new_query_id = data.get("id")
        
        self.log_test(
            f"POST /workpaper/jobs/{self.new_job_id}/queries",
            success and self.new_query_id is not None,
            f"Status: {status}, Query ID: {self.new_query_id if success else 'Failed'}"
        )
        
        if not self.new_query_id:
            return
        
        # Send query to client
        status, data = await self.make_request("POST", f"/workpaper/queries/{self.new_query_id}/send", self.staff_token, {"message": "Additional message when sending"})
        self.log_test(
            f"POST /workpaper/queries/{self.new_query_id}/send",
            status == 200 and data.get("status") == "sent_to_client",
            f"Status: {status}, Query status: {data.get('status') if status == 200 else 'Failed'}"
        )
        
        # Add message to query
        message_data = {
            "message_text": "Follow-up message from staff",
            "attachment_url": "https://example.com/document.pdf",
            "attachment_name": "supporting_document.pdf"
        }
        status, data = await self.make_request("POST", f"/workpaper/queries/{self.new_query_id}/messages", self.staff_token, message_data)
        self.log_test(
            f"POST /workpaper/queries/{self.new_query_id}/messages",
            status == 201 or status == 200,
            f"Status: {status}, Message added: {'✓' if status in [200, 201] else '✗'}"
        )
        
        # Get query messages
        status, data = await self.make_request("GET", f"/workpaper/queries/{self.new_query_id}/messages", self.staff_token)
        self.log_test(
            f"GET /workpaper/queries/{self.new_query_id}/messages",
            status == 200 and isinstance(data, list) and len(data) >= 2,
            f"Status: {status}, Messages count: {len(data) if status == 200 else 0}"
        )
        
        # Resolve query
        status, data = await self.make_request("POST", f"/workpaper/queries/{self.new_query_id}/resolve", self.staff_token, {"resolution_message": "Query resolved by automated test"})
        self.log_test(
            f"POST /workpaper/queries/{self.new_query_id}/resolve",
            status == 200 and data.get("status") == "resolved",
            f"Status: {status}, Query status: {data.get('status') if status == 200 else 'Failed'}"
        )
        
        # List job queries
        status, data = await self.make_request("GET", f"/workpaper/jobs/{self.new_job_id}/queries", self.staff_token)
        self.log_test(
            f"GET /workpaper/jobs/{self.new_job_id}/queries",
            status == 200 and isinstance(data, list) and len(data) > 0,
            f"Status: {status}, Queries count: {len(data) if status == 200 else 0}"
        )
    
    async def test_dashboard_operations(self):
        """Test 23: Dashboard Operations"""
        print("\n=== Testing Dashboard Operations ===")
        
        if not self.new_job_id:
            self.log_test("Dashboard Operations", False, "Missing job ID from previous tests")
            return
        
        # Test full dashboard
        status, data = await self.make_request("GET", f"/workpaper/clients/{NEW_CLIENT_ID}/jobs/{NEW_YEAR}/dashboard", self.staff_token)
        
        success = (status == 200 and 
                  data.get("job", {}).get("id") == self.new_job_id and
                  "modules" in data and
                  "total_deduction" in data and
                  "total_income" in data)
        
        self.log_test(
            f"GET /workpaper/clients/{NEW_CLIENT_ID}/jobs/{NEW_YEAR}/dashboard",
            success,
            f"Status: {status}, Modules: {len(data.get('modules', [])) if status == 200 else 0}, Deduction: ${data.get('total_deduction', 0) if status == 200 else 0}"
        )
    
    async def test_freeze_operations(self):
        """Test 24-26: Freeze Operations"""
        print("\n=== Testing Freeze Operations ===")
        
        if not self.new_module_id or not self.new_job_id:
            self.log_test("Freeze Operations", False, "Missing module or job ID from previous tests")
            return
        
        # Freeze module
        status, data = await self.make_request("POST", f"/workpaper/modules/{self.new_module_id}/freeze", self.staff_token, {"reason": "Testing freeze functionality"})
        success = status == 201 or status == 200
        
        if success:
            self.new_snapshot_id = data.get("id")
        
        self.log_test(
            f"POST /workpaper/modules/{self.new_module_id}/freeze",
            success and self.new_snapshot_id is not None,
            f"Status: {status}, Snapshot ID: {self.new_snapshot_id if success else 'Failed'}"
        )
        
        # List job snapshots
        status, data = await self.make_request("GET", f"/workpaper/jobs/{self.new_job_id}/snapshots", self.staff_token)
        self.log_test(
            f"GET /workpaper/jobs/{self.new_job_id}/snapshots",
            status == 200 and isinstance(data, list) and len(data) > 0,
            f"Status: {status}, Snapshots count: {len(data) if status == 200 else 0}"
        )
        
        # Test reopen with admin credentials (requires admin role)
        status, data = await self.make_request("POST", f"/workpaper/modules/{self.new_module_id}/reopen", self.admin_token, params={"reason": "Testing reopen functionality for automated test"})
        self.log_test(
            f"POST /workpaper/modules/{self.new_module_id}/reopen (admin only)",
            status == 200 and data.get("status") != "frozen",
            f"Status: {status}, Module status: {data.get('status') if status == 200 else 'Failed'}"
        )
    
    async def test_database_integrity(self):
        """Test 27: Database Integrity Check"""
        print("\n=== Testing Database Integrity ===")
        
        try:
            # Connect to PostgreSQL to verify data integrity
            conn = await asyncpg.connect(
                host="fdctax-onboarding-sandbox-do-user-29847186-0.k.db.ondigitalocean.com",
                port=25060,
                database="defaultdb",
                user="myfdc_user",
                password="AVNS_p5zBjf0WxY2MrRcRh87",
                ssl="require"
            )
            
            # Check if all expected tables exist
            tables_query = """
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name LIKE 'workpaper_%'
                ORDER BY table_name
            """
            tables = await conn.fetch(tables_query)
            table_names = [row['table_name'] for row in tables]
            
            expected_tables = [
                'workpaper_jobs', 'workpaper_modules', 'workpaper_transactions',
                'workpaper_transaction_overrides', 'workpaper_override_records',
                'workpaper_queries', 'workpaper_query_messages', 'workpaper_tasks',
                'workpaper_freeze_snapshots', 'workpaper_audit_logs'
            ]
            
            missing_tables = [t for t in expected_tables if t not in table_names]
            
            self.log_test(
                "Database Tables Existence",
                len(missing_tables) == 0,
                f"Found: {len(table_names)}/10 tables, Missing: {missing_tables if missing_tables else 'None'}"
            )
            
            # Check data integrity for our test job
            if self.new_job_id:
                job_data = await conn.fetchrow("SELECT * FROM workpaper_jobs WHERE id = $1", self.new_job_id)
                modules_count = await conn.fetchval("SELECT COUNT(*) FROM workpaper_modules WHERE job_id = $1", self.new_job_id)
                
                self.log_test(
                    "Test Data Integrity",
                    job_data is not None and modules_count == 9,
                    f"Job exists: {'✓' if job_data else '✗'}, Modules: {modules_count}/9"
                )
            
            await conn.close()
            
        except Exception as e:
            self.log_test(
                "Database Connection",
                False,
                f"Failed to connect to database: {str(e)}"
            )
    
    async def run_all_tests(self):
        """Run all test suites"""
        print("🚀 Starting Comprehensive Workpaper API Tests")
        print(f"Base URL: {BASE_URL}")
        print(f"Test Job ID: {TEST_JOB_ID}")
        print(f"Test Client: {TEST_CLIENT_ID}")
        
        # Authentication is required for most tests
        if not await self.test_authentication():
            print("❌ Authentication failed - cannot continue with API tests")
            return
        
        # Run all test suites
        await self.test_reference_data()
        await self.test_existing_job_operations()
        await self.test_new_job_creation()
        await self.test_module_operations()
        await self.test_transaction_operations()
        await self.test_override_operations()
        await self.test_query_operations()
        await self.test_dashboard_operations()
        await self.test_freeze_operations()
        await self.test_database_integrity()
        
        # Summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("📊 TEST SUMMARY")
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
        if self.new_job_id:
            print(f"🆔 Test Data Created:")
            print(f"   Job ID: {self.new_job_id}")
            print(f"   Module ID: {self.new_module_id}")
            print(f"   Transaction ID: {self.new_transaction_id}")
            print(f"   Query ID: {self.new_query_id}")
            print(f"   Snapshot ID: {self.new_snapshot_id}")


async def main():
    """Main test runner"""
    async with WorkpaperAPITester() as tester:
        await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())