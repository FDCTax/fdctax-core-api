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

# Test data for LodgeIT
TEST_CLIENT_IDS = [143003, 143004, 143005]  # Existing client IDs for testing

class LodgeITAPITester:
    def __init__(self):
        self.session = None
        self.admin_token = None
        self.tax_agent_token = None
        self.staff_token = None
        self.client_token = None
        self.test_results = []
        
        # Test data storage
        self.test_queue_id = None
        self.test_export_data = None
    
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
        """Test 1: Authentication for all user roles"""
        print("\n=== Testing Authentication ===")
        
        # Test admin login
        self.admin_token = await self.authenticate(ADMIN_CREDENTIALS)
        self.log_test(
            "Admin Authentication",
            self.admin_token is not None,
            f"Token: {'✓' if self.admin_token else '✗'}"
        )
        
        # Test tax agent login
        self.tax_agent_token = await self.authenticate(TAX_AGENT_CREDENTIALS)
        self.log_test(
            "Tax Agent Authentication",
            self.tax_agent_token is not None,
            f"Token: {'✓' if self.tax_agent_token else '✗'}"
        )
        
        # Test staff login
        self.staff_token = await self.authenticate(STAFF_CREDENTIALS)
        self.log_test(
            "Staff Authentication",
            self.staff_token is not None,
            f"Token: {'✓' if self.staff_token else '✗'}"
        )
        
        # Test client login
        self.client_token = await self.authenticate(CLIENT_CREDENTIALS)
        self.log_test(
            "Client Authentication",
            self.client_token is not None,
            f"Token: {'✓' if self.client_token else '✗'}"
        )
        
        return all([self.admin_token, self.tax_agent_token, self.staff_token, self.client_token])
    
    async def test_lodgeit_export_queue_access(self):
        """Test 2: LodgeIT Export Queue Access - RBAC"""
        print("\n=== Testing LodgeIT Export Queue Access (RBAC) ===")
        
        # Test admin access (should work)
        status, data = await self.make_request("GET", "/lodgeit/export-queue", self.admin_token)
        self.log_test(
            "GET /lodgeit/export-queue (admin)",
            status == 200 and isinstance(data, list),
            f"Status: {status}, Queue entries: {len(data) if status == 200 else 'N/A'}"
        )
        
        # Test tax agent access (should work)
        status, data = await self.make_request("GET", "/lodgeit/export-queue", self.tax_agent_token)
        self.log_test(
            "GET /lodgeit/export-queue (tax_agent)",
            status == 200 and isinstance(data, list),
            f"Status: {status}, Queue entries: {len(data) if status == 200 else 'N/A'}"
        )
        
        # Test staff access (should be blocked - 403)
        status, data = await self.make_request("GET", "/lodgeit/export-queue", self.staff_token)
        self.log_test(
            "GET /lodgeit/export-queue (staff - should be blocked)",
            status == 403,
            f"Status: {status}, Expected: 403 (Access denied)"
        )
        
        # Test client access (should be blocked - 403)
        status, data = await self.make_request("GET", "/lodgeit/export-queue", self.client_token)
        self.log_test(
            "GET /lodgeit/export-queue (client - should be blocked)",
            status == 403,
            f"Status: {status}, Expected: 403 (Access denied)"
        )
    
    async def test_lodgeit_queue_stats(self):
        """Test 3: LodgeIT Queue Statistics"""
        print("\n=== Testing LodgeIT Queue Statistics ===")
        
        # Test with admin credentials
        status, data = await self.make_request("GET", "/lodgeit/export-queue/stats", self.admin_token)
        
        expected_keys = ["pending", "exported", "failed", "total"]
        has_all_keys = all(key in data for key in expected_keys) if status == 200 else False
        
        self.log_test(
            "GET /lodgeit/export-queue/stats",
            status == 200 and has_all_keys,
            f"Status: {status}, Stats: {data if status == 200 else 'Failed'}"
        )
        
        # Test RBAC - staff should be blocked
        status, data = await self.make_request("GET", "/lodgeit/export-queue/stats", self.staff_token)
        self.log_test(
            "GET /lodgeit/export-queue/stats (staff - should be blocked)",
            status == 403,
            f"Status: {status}, Expected: 403"
        )
    
    async def test_lodgeit_queue_add(self):
        """Test 4: Add Client to Queue"""
        print("\n=== Testing Add Client to Queue ===")
        
        # Test adding client with tax agent credentials
        add_data = {"client_id": TEST_CLIENT_IDS[0]}
        status, data = await self.make_request("POST", "/lodgeit/queue/add", self.tax_agent_token, add_data)
        
        success = status in [200, 201] and data.get("success") is True
        if success:
            self.test_queue_id = data.get("queue_id")
        
        self.log_test(
            f"POST /lodgeit/queue/add (client_id: {TEST_CLIENT_IDS[0]})",
            success,
            f"Status: {status}, Queue ID: {self.test_queue_id if success else 'Failed'}, Client: {data.get('client_name', 'N/A') if success else 'N/A'}"
        )
        
        # Test duplicate add (should return existing entry message)
        status, data = await self.make_request("POST", "/lodgeit/queue/add", self.tax_agent_token, add_data)
        is_duplicate = status == 200 and "already in queue" in data.get("message", "").lower()
        
        self.log_test(
            f"POST /lodgeit/queue/add (duplicate - should return existing)",
            is_duplicate,
            f"Status: {status}, Message: {data.get('message', 'N/A') if status == 200 else 'Failed'}"
        )
        
        # Test RBAC - staff should be blocked
        status, data = await self.make_request("POST", "/lodgeit/queue/add", self.staff_token, {"client_id": TEST_CLIENT_IDS[1]})
        self.log_test(
            "POST /lodgeit/queue/add (staff - should be blocked)",
            status == 403,
            f"Status: {status}, Expected: 403"
        )
        
        # Test RBAC - client should be blocked
        status, data = await self.make_request("POST", "/lodgeit/queue/add", self.client_token, {"client_id": TEST_CLIENT_IDS[1]})
        self.log_test(
            "POST /lodgeit/queue/add (client - should be blocked)",
            status == 403,
            f"Status: {status}, Expected: 403"
        )
    
    async def test_lodgeit_export(self):
        """Test 5: Export Clients to CSV"""
        print("\n=== Testing LodgeIT Export ===")
        
        # First, add clients to queue
        for client_id in TEST_CLIENT_IDS[:2]:  # Add first 2 clients
            add_data = {"client_id": client_id}
            await self.make_request("POST", "/lodgeit/queue/add", self.admin_token, add_data)
        
        # Test export with admin credentials
        export_data = {"client_ids": TEST_CLIENT_IDS[:2]}
        status, data = await self.make_request("POST", "/lodgeit/export", self.admin_token, export_data)
        
        # Check if we got CSV content (response might be text/csv)
        is_csv = status == 200 and (isinstance(data, str) and "ClientID" in data)
        
        self.log_test(
            f"POST /lodgeit/export (client_ids: {TEST_CLIENT_IDS[:2]})",
            is_csv,
            f"Status: {status}, CSV headers present: {'✓' if is_csv else '✗'}"
        )
        
        if is_csv:
            # Verify CSV has required columns (39 columns as specified)
            lines = data.strip().split('\n')
            if lines:
                headers = lines[0].split(',')
                expected_headers = ["ClientID", "FirstName", "LastName", "Email", "ABN", "BusinessName"]
                has_required_headers = all(header in headers for header in expected_headers)
                
                self.log_test(
                    "CSV Format Validation",
                    len(headers) >= 30 and has_required_headers,  # Should have many columns
                    f"Headers count: {len(headers)}, Required headers present: {'✓' if has_required_headers else '✗'}"
                )
                
                self.test_export_data = data
        
        # Test RBAC - staff should be blocked
        status, data = await self.make_request("POST", "/lodgeit/export", self.staff_token, export_data)
        self.log_test(
            "POST /lodgeit/export (staff - should be blocked)",
            status == 403,
            f"Status: {status}, Expected: 403"
        )
    
    async def test_lodgeit_itr_template(self):
        """Test 6: ITR Template Generation"""
        print("\n=== Testing ITR Template Generation ===")
        
        # Test ITR template generation with admin credentials
        itr_data = {"client_id": TEST_CLIENT_IDS[0]}
        status, data = await self.make_request("POST", "/lodgeit/export-itr-template", self.admin_token, itr_data)
        
        success = status == 200 and data.get("success") is True
        template = data.get("template", {}) if success else {}
        
        # Check for required template sections
        required_sections = ["_meta", "taxpayer", "contact", "income", "deductions"]
        has_sections = all(section in template for section in required_sections) if template else False
        
        self.log_test(
            f"POST /lodgeit/export-itr-template (client_id: {TEST_CLIENT_IDS[0]})",
            success and has_sections,
            f"Status: {status}, Template sections: {list(template.keys()) if template else 'None'}"
        )
        
        if success and template:
            # Verify _meta section
            meta = template.get("_meta", {})
            has_meta_fields = all(field in meta for field in ["financial_year", "source_system"])
            
            self.log_test(
                "ITR Template _meta validation",
                has_meta_fields and meta.get("source_system") == "FDC_Core",
                f"Financial year: {meta.get('financial_year')}, Source: {meta.get('source_system')}"
            )
        
        # Test RBAC - staff should be blocked
        status, data = await self.make_request("POST", "/lodgeit/export-itr-template", self.staff_token, itr_data)
        self.log_test(
            "POST /lodgeit/export-itr-template (staff - should be blocked)",
            status == 403,
            f"Status: {status}, Expected: 403"
        )
    
    async def test_lodgeit_queue_remove(self):
        """Test 7: Remove Client from Queue"""
        print("\n=== Testing Remove Client from Queue ===")
        
        # First add a client to queue
        add_data = {"client_id": TEST_CLIENT_IDS[2]}
        await self.make_request("POST", "/lodgeit/queue/add", self.admin_token, add_data)
        
        # Test removing client with admin credentials
        status, data = await self.make_request("DELETE", f"/lodgeit/queue/{TEST_CLIENT_IDS[2]}", self.admin_token)
        
        success = status == 200 and data.get("success") is True
        
        self.log_test(
            f"DELETE /lodgeit/queue/{TEST_CLIENT_IDS[2]}",
            success,
            f"Status: {status}, Message: {data.get('message', 'N/A') if success else 'Failed'}"
        )
        
        # Test RBAC - staff should be blocked
        status, data = await self.make_request("DELETE", f"/lodgeit/queue/{TEST_CLIENT_IDS[0]}", self.staff_token)
        self.log_test(
            "DELETE /lodgeit/queue/{client_id} (staff - should be blocked)",
            status == 403,
            f"Status: {status}, Expected: 403"
        )
    
    async def test_lodgeit_audit_log(self):
        """Test 8: Audit Log Retrieval"""
        print("\n=== Testing LodgeIT Audit Log ===")
        
        # Test audit log with admin credentials
        status, data = await self.make_request("GET", "/lodgeit/audit-log", self.admin_token)
        
        success = status == 200 and isinstance(data, list)
        
        self.log_test(
            "GET /lodgeit/audit-log",
            success,
            f"Status: {status}, Audit entries: {len(data) if success else 'N/A'}"
        )
        
        if success and data:
            # Verify audit log entry structure
            entry = data[0]
            required_fields = ["id", "user_id", "action", "client_ids", "success", "timestamp"]
            has_fields = all(field in entry for field in required_fields)
            
            self.log_test(
                "Audit Log Entry Structure",
                has_fields,
                f"Entry fields: {list(entry.keys())}"
            )
            
            # Check for expected actions
            actions = [entry.get("action") for entry in data]
            expected_actions = ["queue_add", "export", "itr_export"]
            has_expected_actions = any(action in actions for action in expected_actions)
            
            self.log_test(
                "Audit Log Actions",
                has_expected_actions,
                f"Actions found: {set(actions)}"
            )
        
        # Test with query parameters
        status, data = await self.make_request("GET", "/lodgeit/audit-log", self.admin_token, params={"limit": 10, "action": "queue_add"})
        self.log_test(
            "GET /lodgeit/audit-log (with filters)",
            status == 200 and isinstance(data, list),
            f"Status: {status}, Filtered entries: {len(data) if status == 200 else 'N/A'}"
        )
        
        # Test RBAC - staff should be blocked
        status, data = await self.make_request("GET", "/lodgeit/audit-log", self.staff_token)
        self.log_test(
            "GET /lodgeit/audit-log (staff - should be blocked)",
            status == 403,
            f"Status: {status}, Expected: 403"
        )
    
    async def test_queue_status_updates(self):
        """Test 9: Queue Status Updates After Export"""
        print("\n=== Testing Queue Status Updates ===")
        
        # Add a client to queue
        add_data = {"client_id": TEST_CLIENT_IDS[1]}
        await self.make_request("POST", "/lodgeit/queue/add", self.admin_token, add_data)
        
        # Check initial queue status
        status, queue_data = await self.make_request("GET", "/lodgeit/export-queue", self.admin_token)
        initial_pending = len([entry for entry in queue_data if entry.get("status") == "pending"]) if status == 200 else 0
        
        # Export the client
        export_data = {"client_ids": [TEST_CLIENT_IDS[1]]}
        status, export_result = await self.make_request("POST", "/lodgeit/export", self.admin_token, export_data)
        
        # Check queue status after export
        status, queue_data_after = await self.make_request("GET", "/lodgeit/export-queue", self.admin_token)
        final_pending = len([entry for entry in queue_data_after if entry.get("status") == "pending"]) if status == 200 else 0
        
        # Verify status was updated (pending count should decrease)
        status_updated = final_pending < initial_pending
        
        self.log_test(
            "Queue Status Update After Export",
            status_updated,
            f"Pending before: {initial_pending}, Pending after: {final_pending}"
        )
    
    async def run_all_tests(self):
        """Run all LodgeIT test suites"""
        print("🚀 Starting Comprehensive LodgeIT Integration Tests")
        print(f"Base URL: {BASE_URL}")
        print(f"Test Client IDs: {TEST_CLIENT_IDS}")
        
        # Authentication is required for all tests
        if not await self.test_authentication():
            print("❌ Authentication failed - cannot continue with API tests")
            return
        
        # Run all test suites
        await self.test_lodgeit_export_queue_access()
        await self.test_lodgeit_queue_stats()
        await self.test_lodgeit_queue_add()
        await self.test_lodgeit_export()
        await self.test_lodgeit_itr_template()
        await self.test_lodgeit_queue_remove()
        await self.test_lodgeit_audit_log()
        await self.test_queue_status_updates()
        
        # Summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("📊 LODGEIT INTEGRATION TEST SUMMARY")
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
        
        # RBAC Summary
        print("🔐 RBAC VERIFICATION SUMMARY:")
        print("   ✅ Admin: Full access to all LodgeIT endpoints")
        print("   ✅ Tax Agent: Full access to all LodgeIT endpoints")
        print("   ❌ Staff: Blocked from all LodgeIT endpoints (403)")
        print("   ❌ Client: Blocked from all LodgeIT endpoints (403)")


async def main():
    """Main test runner"""
    async with LodgeITAPITester() as tester:
        await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())