#!/usr/bin/env python3
"""
Comprehensive Backend Test Suite for Unified Transaction Engine
Tests all transaction endpoints with authentication and business logic
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
BASE_URL = "https://taxcore-crm.preview.emergentagent.com/api"

# Test credentials
STAFF_CREDENTIALS = {"email": "staff@fdctax.com", "password": "staff123"}
ADMIN_CREDENTIALS = {"email": "admin@fdctax.com", "password": "admin123"}

# Test data
TEST_CLIENT_ID = "test-client-txengine-001"
TEST_WORKPAPER_ID = "wp-test-001"


class TransactionEngineAPITester:
    def __init__(self):
        self.session = None
        self.staff_token = None
        self.admin_token = None
        self.test_results = []
        
        # Test data storage
        self.test_transaction_ids = []
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
            "Staff Authentication (Bookkeeper)",
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
    
    async def test_reference_data_endpoints(self):
        """Test 2-5: Reference Data Endpoints"""
        print("\n=== Testing Reference Data Endpoints ===")
        
        # Test transaction statuses
        status, data = await self.make_request("GET", "/bookkeeper/statuses", self.staff_token)
        self.log_test(
            "GET /bookkeeper/statuses",
            status == 200 and "statuses" in data,
            f"Status: {status}, Statuses count: {len(data.get('statuses', []))}"
        )
        
        # Test GST codes
        status, data = await self.make_request("GET", "/bookkeeper/gst-codes", self.staff_token)
        self.log_test(
            "GET /bookkeeper/gst-codes",
            status == 200 and "gst_codes" in data,
            f"Status: {status}, GST codes count: {len(data.get('gst_codes', []))}"
        )
        
        # Test transaction sources
        status, data = await self.make_request("GET", "/bookkeeper/sources", self.staff_token)
        self.log_test(
            "GET /bookkeeper/sources",
            status == 200 and "sources" in data,
            f"Status: {status}, Sources count: {len(data.get('sources', []))}"
        )
        
        # Test module routings
        status, data = await self.make_request("GET", "/bookkeeper/module-routings", self.staff_token)
        self.log_test(
            "GET /bookkeeper/module-routings",
            status == 200 and "module_routings" in data,
            f"Status: {status}, Module routings count: {len(data.get('module_routings', []))}"
        )
    
    async def test_myfdc_transaction_creation(self):
        """Test 6-8: MyFDC Transaction Creation"""
        print("\n=== Testing MyFDC Transaction Creation ===")
        
        # Create transactions via MyFDC endpoint
        test_transactions = [
            {
                "date": "2024-01-15",
                "amount": 250.50,
                "payee": "Office Supplies Co",
                "description": "Stationery and office materials",
                "category": "office_supplies",
                "module_hint": "GENERAL",
                "notes": "Monthly office supplies purchase"
            },
            {
                "date": "2024-01-20",
                "amount": 1200.00,
                "payee": "Fuel Station",
                "description": "Fuel for business vehicle",
                "category": "vehicle_expenses",
                "module_hint": "MOTOR_VEHICLE",
                "notes": "Business travel fuel"
            },
            {
                "date": "2024-01-25",
                "amount": 85.00,
                "payee": "Internet Provider",
                "description": "Monthly internet service",
                "category": "utilities",
                "module_hint": "INTERNET",
                "notes": "Home office internet"
            }
        ]
        
        for i, txn_data in enumerate(test_transactions):
            status, data = await self.make_request(
                "POST", 
                f"/myfdc/transactions?client_id={TEST_CLIENT_ID}",
                self.staff_token,
                txn_data
            )
            
            success = status in [200, 201] and data.get("success") and "transaction" in data
            if success:
                self.test_transaction_ids.append(data["transaction"]["id"])
            
            self.log_test(
                f"POST /myfdc/transactions (Transaction {i+1})",
                success,
                f"Status: {status}, Amount: ${txn_data['amount']}, ID: {data.get('transaction', {}).get('id', 'N/A') if success else 'Failed'}"
            )
    
    async def test_transaction_listing_and_filters(self):
        """Test 9-12: Transaction Listing with Filters"""
        print("\n=== Testing Transaction Listing and Filters ===")
        
        # Test basic listing
        status, data = await self.make_request(
            "GET", 
            "/bookkeeper/transactions",
            self.staff_token,
            params={"client_id": TEST_CLIENT_ID}
        )
        self.log_test(
            "GET /bookkeeper/transactions (basic listing)",
            status == 200 and "items" in data,
            f"Status: {status}, Transactions found: {len(data.get('items', []))}"
        )
        
        # Test status filter
        status, data = await self.make_request(
            "GET", 
            "/bookkeeper/transactions",
            self.staff_token,
            params={"client_id": TEST_CLIENT_ID, "status": "NEW"}
        )
        self.log_test(
            "GET /bookkeeper/transactions (status=NEW filter)",
            status == 200 and "items" in data,
            f"Status: {status}, NEW transactions: {len(data.get('items', []))}"
        )
        
        # Test date range filter
        status, data = await self.make_request(
            "GET", 
            "/bookkeeper/transactions",
            self.staff_token,
            params={
                "client_id": TEST_CLIENT_ID,
                "date_from": "2024-01-01",
                "date_to": "2024-01-31"
            }
        )
        self.log_test(
            "GET /bookkeeper/transactions (date range filter)",
            status == 200 and "items" in data,
            f"Status: {status}, January transactions: {len(data.get('items', []))}"
        )
        
        # Test search filter
        status, data = await self.make_request(
            "GET", 
            "/bookkeeper/transactions",
            self.staff_token,
            params={"client_id": TEST_CLIENT_ID, "search": "office"}
        )
        self.log_test(
            "GET /bookkeeper/transactions (search filter)",
            status == 200 and "items" in data,
            f"Status: {status}, Search results: {len(data.get('items', []))}"
        )
    
    async def test_single_transaction_operations(self):
        """Test 13-15: Single Transaction Operations"""
        print("\n=== Testing Single Transaction Operations ===")
        
        if not self.test_transaction_ids:
            self.log_test("Single Transaction Operations", False, "No transaction IDs available from previous tests")
            return
        
        transaction_id = self.test_transaction_ids[0]
        
        # Test get single transaction
        status, data = await self.make_request(
            "GET", 
            f"/bookkeeper/transactions/{transaction_id}",
            self.staff_token
        )
        self.log_test(
            f"GET /bookkeeper/transactions/{transaction_id}",
            status == 200 and data.get("id") == transaction_id,
            f"Status: {status}, Amount: ${data.get('amount', 0) if status == 200 else 'N/A'}"
        )
        
        # Test update transaction (bookkeeper edit)
        update_data = {
            "category_bookkeeper": "office_expenses",
            "gst_code_bookkeeper": "GST",
            "notes_bookkeeper": "Updated by bookkeeper - office supplies",
            "status_bookkeeper": "REVIEWED",
            "module_routing": "GENERAL"
        }
        
        status, data = await self.make_request(
            "PATCH", 
            f"/bookkeeper/transactions/{transaction_id}",
            self.staff_token,
            update_data
        )
        self.log_test(
            f"PATCH /bookkeeper/transactions/{transaction_id} (bookkeeper edit)",
            status == 200 and data.get("status_bookkeeper") == "REVIEWED",
            f"Status: {status}, New status: {data.get('status_bookkeeper') if status == 200 else 'Failed'}"
        )
        
        # Test get transaction history
        status, data = await self.make_request(
            "GET", 
            f"/bookkeeper/transactions/{transaction_id}/history",
            self.staff_token
        )
        self.log_test(
            f"GET /bookkeeper/transactions/{transaction_id}/history",
            status == 200 and isinstance(data, list) and len(data) >= 2,
            f"Status: {status}, History entries: {len(data) if status == 200 else 0}"
        )
    
    async def test_bulk_update_operations(self):
        """Test 16: Bulk Update Operations"""
        print("\n=== Testing Bulk Update Operations ===")
        
        if len(self.test_transaction_ids) < 2:
            self.log_test("Bulk Update Operations", False, "Need at least 2 transactions for bulk update test")
            return
        
        # Bulk update by client_id
        bulk_request = {
            "criteria": {
                "client_id": TEST_CLIENT_ID,
                "status": "NEW"
            },
            "updates": {
                "category_bookkeeper": "business_expenses",
                "status_bookkeeper": "PENDING"
            }
        }
        
        status, data = await self.make_request(
            "POST", 
            "/bookkeeper/transactions/bulk-update",
            self.staff_token,
            bulk_request
        )
        self.log_test(
            "POST /bookkeeper/transactions/bulk-update",
            status == 200 and data.get("success") and data.get("updated_count", 0) > 0,
            f"Status: {status}, Updated count: {data.get('updated_count', 0) if status == 200 else 'Failed'}"
        )
    
    async def test_workpaper_locking_system(self):
        """Test 17-19: Workpaper Locking System"""
        print("\n=== Testing Workpaper Locking System ===")
        
        if not self.test_transaction_ids:
            self.log_test("Workpaper Locking System", False, "No transaction IDs available")
            return
        
        # First create a workpaper job for testing
        job_data = {
            "client_id": TEST_CLIENT_ID,
            "year": "2024-25",
            "notes": "Test job for transaction locking",
            "auto_create_modules": True
        }
        
        status, data = await self.make_request("POST", "/workpaper/jobs", self.staff_token, job_data)
        if status in [200, 201]:
            self.test_workpaper_job_id = data.get("id")
        
        if not self.test_workpaper_job_id:
            self.log_test("Workpaper Job Creation", False, "Failed to create test workpaper job")
            return
        
        self.log_test(
            "Workpaper Job Creation for Locking Test",
            True,
            f"Created job: {self.test_workpaper_job_id}"
        )
        
        # Test transaction locking
        lock_request = {
            "transaction_ids": self.test_transaction_ids[:2],  # Lock first 2 transactions
            "workpaper_id": self.test_workpaper_job_id,
            "module": "GENERAL",
            "period": "2024-25"
        }
        
        status, data = await self.make_request(
            "POST", 
            "/workpapers/transactions-lock",
            self.staff_token,
            lock_request
        )
        self.log_test(
            "POST /workpapers/transactions-lock",
            status == 200 and data.get("success") and data.get("locked_count", 0) > 0,
            f"Status: {status}, Locked count: {data.get('locked_count', 0)}/{len(lock_request['transaction_ids'])}"
        )
        
        # Test that locked transaction can only have notes edited
        if self.test_transaction_ids:
            locked_txn_id = self.test_transaction_ids[0]
            
            # Try to edit a non-notes field (should fail)
            invalid_update = {
                "category_bookkeeper": "should_fail",
                "status_bookkeeper": "READY_FOR_WORKPAPER"
            }
            
            status, data = await self.make_request(
                "PATCH", 
                f"/bookkeeper/transactions/{locked_txn_id}",
                self.staff_token,
                invalid_update
            )
            self.log_test(
                "PATCH locked transaction (non-notes field - should fail)",
                status == 400,  # Should fail with 400 error
                f"Status: {status}, Expected 400 (locked transaction protection)"
            )
            
            # Try to edit notes only (should succeed)
            notes_update = {
                "notes_bookkeeper": "Updated notes on locked transaction"
            }
            
            status, data = await self.make_request(
                "PATCH", 
                f"/bookkeeper/transactions/{locked_txn_id}",
                self.staff_token,
                notes_update
            )
            self.log_test(
                "PATCH locked transaction (notes only - should succeed)",
                status == 200,
                f"Status: {status}, Notes update on locked transaction"
            )
    
    async def test_admin_unlock_functionality(self):
        """Test 20: Admin Unlock Functionality"""
        print("\n=== Testing Admin Unlock Functionality ===")
        
        if not self.test_transaction_ids:
            self.log_test("Admin Unlock Functionality", False, "No locked transactions available")
            return
        
        locked_txn_id = self.test_transaction_ids[0]
        
        # Test admin unlock with comment
        unlock_comment = "Unlocking for corrections - client provided additional documentation"
        
        status, data = await self.make_request(
            "POST", 
            f"/bookkeeper/transactions/{locked_txn_id}/unlock",
            self.admin_token,
            params={"comment": unlock_comment}
        )
        self.log_test(
            f"POST /bookkeeper/transactions/{locked_txn_id}/unlock (admin)",
            status == 200 and data.get("status_bookkeeper") != "LOCKED",
            f"Status: {status}, New status: {data.get('status_bookkeeper') if status == 200 else 'Failed'}"
        )
        
        # Test that staff cannot unlock (should fail)
        if len(self.test_transaction_ids) > 1:
            another_locked_id = self.test_transaction_ids[1]
            
            status, data = await self.make_request(
                "POST", 
                f"/bookkeeper/transactions/{another_locked_id}/unlock",
                self.staff_token,
                params={"comment": "Staff trying to unlock"}
            )
            self.log_test(
                "POST unlock with staff credentials (should fail)",
                status == 403,  # Should fail with 403 Forbidden
                f"Status: {status}, Expected 403 (staff cannot unlock)"
            )
    
    async def test_myfdc_sync_rules(self):
        """Test 21-22: MyFDC Sync Rules"""
        print("\n=== Testing MyFDC Sync Rules ===")
        
        # Create a new transaction via MyFDC
        new_txn_data = {
            "date": "2024-02-01",
            "amount": 150.00,
            "payee": "Test Vendor",
            "description": "Test sync rules",
            "category": "test_category",
            "notes": "Initial submission"
        }
        
        status, data = await self.make_request(
            "POST", 
            f"/myfdc/transactions?client_id={TEST_CLIENT_ID}",
            self.staff_token,
            new_txn_data
        )
        
        if status not in [200, 201] or not data.get("success"):
            self.log_test("MyFDC Sync Rules", False, "Failed to create test transaction")
            return
        
        sync_txn_id = data["transaction"]["id"]
        
        # Test update when status=NEW (should succeed)
        update_data = {
            "amount": 175.00,
            "description": "Updated description",
            "notes": "Updated notes"
        }
        
        status, data = await self.make_request(
            "PATCH", 
            f"/myfdc/transactions/{sync_txn_id}",
            self.staff_token,
            update_data
        )
        self.log_test(
            "PATCH /myfdc/transactions (status=NEW - should succeed)",
            status == 200 and data.get("was_updated") == True,
            f"Status: {status}, Was updated: {data.get('was_updated') if status == 200 else 'Failed'}"
        )
        
        # Update transaction to REVIEWED status via bookkeeper
        bookkeeper_update = {
            "status_bookkeeper": "REVIEWED",
            "category_bookkeeper": "reviewed_category"
        }
        
        await self.make_request(
            "PATCH", 
            f"/bookkeeper/transactions/{sync_txn_id}",
            self.staff_token,
            bookkeeper_update
        )
        
        # Test update when status>=REVIEWED (should be rejected)
        rejected_update = {
            "amount": 200.00,
            "description": "This should be rejected"
        }
        
        status, data = await self.make_request(
            "PATCH", 
            f"/myfdc/transactions/{sync_txn_id}",
            self.staff_token,
            rejected_update
        )
        self.log_test(
            "PATCH /myfdc/transactions (status>=REVIEWED - should be rejected)",
            status == 200 and data.get("was_updated") == False,
            f"Status: {status}, Was updated: {data.get('was_updated')}, Message: {data.get('message', '') if status == 200 else 'Failed'}"
        )
    
    async def test_permission_enforcement(self):
        """Test 23: Permission Enforcement"""
        print("\n=== Testing Permission Enforcement ===")
        
        if not self.test_transaction_ids:
            self.log_test("Permission Enforcement", False, "No transactions available for permission testing")
            return
        
        transaction_id = self.test_transaction_ids[0]
        
        # Test admin can edit any field
        admin_update = {
            "category_bookkeeper": "admin_category",
            "status_bookkeeper": "READY_FOR_WORKPAPER",
            "notes_bookkeeper": "Admin can edit anything"
        }
        
        status, data = await self.make_request(
            "PATCH", 
            f"/bookkeeper/transactions/{transaction_id}",
            self.admin_token,
            admin_update
        )
        self.log_test(
            "Admin can edit any field",
            status == 200,
            f"Status: {status}, Admin edit successful"
        )
        
        # Test staff (bookkeeper) can edit until LOCKED
        staff_update = {
            "notes_bookkeeper": "Staff bookkeeper edit",
            "gst_code_bookkeeper": "GST_FREE"
        }
        
        status, data = await self.make_request(
            "PATCH", 
            f"/bookkeeper/transactions/{transaction_id}",
            self.staff_token,
            staff_update
        )
        self.log_test(
            "Staff (bookkeeper) can edit unlocked transaction",
            status == 200,
            f"Status: {status}, Staff edit successful"
        )
    
    async def test_history_tracking_comprehensive(self):
        """Test 24: Comprehensive History Tracking"""
        print("\n=== Testing Comprehensive History Tracking ===")
        
        if not self.test_transaction_ids:
            self.log_test("History Tracking", False, "No transactions available for history testing")
            return
        
        transaction_id = self.test_transaction_ids[0]
        
        # Get current history
        status, history_data = await self.make_request(
            "GET", 
            f"/bookkeeper/transactions/{transaction_id}/history",
            self.staff_token
        )
        
        if status != 200:
            self.log_test("History Tracking", False, "Failed to get transaction history")
            return
        
        initial_count = len(history_data)
        
        # Make an update to generate new history
        update_data = {
            "notes_bookkeeper": f"History test update at {datetime.now().isoformat()}"
        }
        
        await self.make_request(
            "PATCH", 
            f"/bookkeeper/transactions/{transaction_id}",
            self.staff_token,
            update_data
        )
        
        # Get updated history
        status, new_history_data = await self.make_request(
            "GET", 
            f"/bookkeeper/transactions/{transaction_id}/history",
            self.staff_token
        )
        
        new_count = len(new_history_data) if status == 200 else 0
        
        self.log_test(
            "History entry created on update",
            status == 200 and new_count > initial_count,
            f"Status: {status}, History entries: {initial_count} → {new_count}"
        )
        
        # Verify history entry structure
        if status == 200 and new_history_data:
            latest_entry = new_history_data[0]  # Most recent first
            required_fields = ["id", "action_type", "role", "timestamp", "before", "after"]
            has_required_fields = all(field in latest_entry for field in required_fields)
            
            self.log_test(
                "History entry has required fields",
                has_required_fields,
                f"Required fields present: {has_required_fields}, Action type: {latest_entry.get('action_type', 'N/A')}"
            )
    
    async def run_all_tests(self):
        """Run all test suites"""
        print("🚀 Starting Comprehensive Transaction Engine API Tests")
        print(f"Base URL: {BASE_URL}")
        print(f"Test Client: {TEST_CLIENT_ID}")
        
        # Authentication is required for all tests
        if not await self.test_authentication():
            print("❌ Authentication failed - cannot continue with API tests")
            return
        
        # Run all test suites
        await self.test_reference_data_endpoints()
        await self.test_myfdc_transaction_creation()
        await self.test_transaction_listing_and_filters()
        await self.test_single_transaction_operations()
        await self.test_bulk_update_operations()
        await self.test_workpaper_locking_system()
        await self.test_admin_unlock_functionality()
        await self.test_myfdc_sync_rules()
        await self.test_permission_enforcement()
        await self.test_history_tracking_comprehensive()
        
        # Summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("📊 TRANSACTION ENGINE TEST SUMMARY")
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
        if self.test_transaction_ids:
            print(f"🆔 Test Data Created:")
            print(f"   Transaction IDs: {len(self.test_transaction_ids)} transactions")
            print(f"   Workpaper Job ID: {self.test_workpaper_job_id}")
            print(f"   Client ID: {TEST_CLIENT_ID}")


async def main():
    """Main test runner"""
    async with TransactionEngineAPITester() as tester:
        await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())