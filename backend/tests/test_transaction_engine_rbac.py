#!/usr/bin/env python3
"""
Comprehensive RBAC Test Suite for Transaction Engine
Tests role-based access control for all transaction endpoints

Test Credentials:
- Admin: admin@fdctax.com / admin123 (full access)
- Staff: staff@fdctax.com / staff123 (bookkeeper - edit until LOCKED)
- Tax Agent: taxagent@fdctax.com / taxagent123 (read-only in Bookkeeper Tab, can lock for workpapers)
- Client: client@fdctax.com / client123 (MyFDC only, no Bookkeeper access)

RBAC Permissions Matrix:
┌──────────────────────────────────────────────┬────────┬───────┬───────────┬───────┐
│ Endpoint                                     │ client │ staff │ tax_agent │ admin │
├──────────────────────────────────────────────┼────────┼───────┼───────────┼───────┤
│ GET /api/bookkeeper/transactions             │   ❌   │   ✔️   │   ✔️      │   ✔️   │
│ PATCH /api/bookkeeper/transactions/{id}      │   ❌   │   ✔️*  │   ❌      │   ✔️   │
│ POST /api/bookkeeper/transactions/bulk-update│   ❌   │   ✔️   │   ❌      │   ✔️   │
│ GET /api/bookkeeper/transactions/{id}/history│   ❌   │   ✔️   │   ✔️      │   ✔️   │
│ POST /api/workpapers/transactions-lock       │   ❌   │   ❌   │   ✔️      │   ✔️   │
│ POST /api/bookkeeper/transactions/{id}/unlock│   ❌   │   ❌   │   ❌      │   ✔️   │
│ POST /api/myfdc/transactions                 │   ✔️   │   ❌   │   ❌      │   ✔️   │
└──────────────────────────────────────────────┴────────┴───────┴───────────┴───────┘
* Staff can edit unless status=LOCKED (then only notes_bookkeeper)
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import uuid

import aiohttp

# Test configuration
BASE_URL = "https://fdctax-core.preview.emergentagent.com/api"

# Test credentials (4 roles)
ADMIN_CREDENTIALS = {"email": "admin@fdctax.com", "password": "admin123"}
STAFF_CREDENTIALS = {"email": "staff@fdctax.com", "password": "staff123"}
TAX_AGENT_CREDENTIALS = {"email": "taxagent@fdctax.com", "password": "taxagent123"}
CLIENT_CREDENTIALS = {"email": "client@fdctax.com", "password": "client123"}

# Test data
TEST_CLIENT_ID = "test-client-rbac-001"


class TransactionRBACTester:
    def __init__(self):
        self.session = None
        self.admin_token = None
        self.staff_token = None
        self.tax_agent_token = None
        self.client_token = None
        self.test_results = []
        
        # Test data storage
        self.test_transaction_ids = []
        self.locked_transaction_id = None
        self.workpaper_job_id = None
    
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
                    print(f"Authentication failed for {credentials['email']}: {response.status} - {error_text}")
                    return None
        except Exception as e:
            print(f"Authentication error for {credentials['email']}: {e}")
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
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        
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
        """Test authentication for all 4 roles"""
        print("\n=== Testing Authentication for All Roles ===")
        
        # Test admin login
        self.admin_token = await self.authenticate(ADMIN_CREDENTIALS)
        self.log_test(
            "Admin Authentication",
            self.admin_token is not None,
            f"admin@fdctax.com: {'✓' if self.admin_token else '✗'}"
        )
        
        # Test staff login
        self.staff_token = await self.authenticate(STAFF_CREDENTIALS)
        self.log_test(
            "Staff Authentication",
            self.staff_token is not None,
            f"staff@fdctax.com: {'✓' if self.staff_token else '✗'}"
        )
        
        # Test tax agent login
        self.tax_agent_token = await self.authenticate(TAX_AGENT_CREDENTIALS)
        self.log_test(
            "Tax Agent Authentication",
            self.tax_agent_token is not None,
            f"taxagent@fdctax.com: {'✓' if self.tax_agent_token else '✗'}"
        )
        
        # Test client login
        self.client_token = await self.authenticate(CLIENT_CREDENTIALS)
        self.log_test(
            "Client Authentication",
            self.client_token is not None,
            f"client@fdctax.com: {'✓' if self.client_token else '✗'}"
        )
        
        return all([self.admin_token, self.staff_token, self.tax_agent_token, self.client_token])
    
    async def setup_test_data(self):
        """Create test transactions for RBAC testing"""
        print("\n=== Setting Up Test Data ===")
        
        # Create test transactions via MyFDC (using admin token)
        for i in range(3):
            transaction_data = {
                "date": "2024-12-15",
                "amount": 100.00 + (i * 50),
                "gst_amount": 10.00 + (i * 5),
                "payee_raw": f"Test Vendor {i+1} Pty Ltd",
                "description_raw": f"Test expense {i+1} for RBAC testing",
                "attachment_url": f"https://example.com/receipt_{i+1}.pdf",
                "attachment_name": f"receipt_{i+1}.pdf"
            }
            
            status, data = await self.make_request(
                "POST", 
                f"/myfdc/transactions?client_id={TEST_CLIENT_ID}",
                self.admin_token,
                transaction_data
            )
            
            if status in [200, 201] and data.get("success"):
                transaction_id = data["transaction"]["id"]
                self.test_transaction_ids.append(transaction_id)
                print(f"    Created test transaction {i+1}: {transaction_id}")
        
        self.log_test(
            "Test Data Setup",
            len(self.test_transaction_ids) == 3,
            f"Created {len(self.test_transaction_ids)}/3 test transactions"
        )
        
        # Create a workpaper job for locking tests
        job_data = {
            "client_id": TEST_CLIENT_ID,
            "year": "2024-25",
            "notes": "Test workpaper job for RBAC testing",
            "auto_create_modules": True
        }
        
        status, data = await self.make_request(
            "POST", 
            "/workpaper/jobs",
            self.admin_token,
            job_data
        )
        
        if status in [200, 201]:
            self.workpaper_job_id = data.get("id")
            print(f"    Created test workpaper job: {self.workpaper_job_id}")
        
        return len(self.test_transaction_ids) >= 2 and self.workpaper_job_id
    
    async def test_client_role_restrictions(self):
        """Test 1: Client Role Tests - Should be blocked from Bookkeeper Tab"""
        print("\n=== Testing Client Role Restrictions ===")
        
        if not self.test_transaction_ids:
            self.log_test("Client Role Tests", False, "No test transactions available")
            return
        
        transaction_id = self.test_transaction_ids[0]
        
        # ❌ Client cannot GET /api/bookkeeper/transactions (403)
        status, data = await self.make_request(
            "GET", 
            "/bookkeeper/transactions",
            self.client_token
        )
        self.log_test(
            "Client BLOCKED from GET /bookkeeper/transactions",
            status == 403,
            f"Status: {status} (expected 403)"
        )
        
        # ❌ Client cannot PATCH transactions (403)
        update_data = {"notes_bookkeeper": "Client trying to edit"}
        status, data = await self.make_request(
            "PATCH", 
            f"/bookkeeper/transactions/{transaction_id}",
            self.client_token,
            update_data
        )
        self.log_test(
            "Client BLOCKED from PATCH /bookkeeper/transactions/{id}",
            status == 403,
            f"Status: {status} (expected 403)"
        )
        
        # ❌ Client cannot GET history (403)
        status, data = await self.make_request(
            "GET", 
            f"/bookkeeper/transactions/{transaction_id}/history",
            self.client_token
        )
        self.log_test(
            "Client BLOCKED from GET /bookkeeper/transactions/{id}/history",
            status == 403,
            f"Status: {status} (expected 403)"
        )
        
        # ❌ Client cannot call bulk-update (403)
        bulk_data = {
            "criteria": {"client_id": TEST_CLIENT_ID},
            "updates": {"category_bookkeeper": "office_supplies"}
        }
        status, data = await self.make_request(
            "POST", 
            "/bookkeeper/transactions/bulk-update",
            self.client_token,
            bulk_data
        )
        self.log_test(
            "Client BLOCKED from POST /bookkeeper/transactions/bulk-update",
            status == 403,
            f"Status: {status} (expected 403)"
        )
        
        # ❌ Client cannot lock transactions (403)
        lock_data = {
            "transaction_ids": [transaction_id],
            "workpaper_id": self.workpaper_job_id or "dummy-job-id",
            "module": "GENERAL",
            "period": "2024-25"
        }
        status, data = await self.make_request(
            "POST", 
            "/workpapers/transactions-lock",
            self.client_token,
            lock_data
        )
        self.log_test(
            "Client BLOCKED from POST /workpapers/transactions-lock",
            status == 403,
            f"Status: {status} (expected 403)"
        )
        
        # ❌ Client cannot unlock (403)
        status, data = await self.make_request(
            "POST", 
            f"/bookkeeper/transactions/{transaction_id}/unlock",
            self.client_token,
            params={"comment": "Client trying to unlock transaction"}
        )
        self.log_test(
            "Client BLOCKED from POST /bookkeeper/transactions/{id}/unlock",
            status == 403,
            f"Status: {status} (expected 403)"
        )
        
        # ✔️ Client CAN POST /api/myfdc/transactions
        myfdc_data = {
            "date": "2024-12-16",
            "amount": 75.00,
            "gst_amount": 7.50,
            "payee_raw": "Client Created Vendor",
            "description_raw": "Client-created transaction for RBAC test"
        }
        status, data = await self.make_request(
            "POST", 
            f"/myfdc/transactions?client_id={TEST_CLIENT_ID}",
            self.client_token,
            myfdc_data
        )
        self.log_test(
            "Client ALLOWED to POST /myfdc/transactions",
            status in [200, 201] and data.get("success"),
            f"Status: {status}, Success: {data.get('success') if status in [200, 201] else 'Failed'}"
        )
    
    async def test_staff_role_permissions(self):
        """Test 2: Staff (Bookkeeper) Role Tests"""
        print("\n=== Testing Staff (Bookkeeper) Role Permissions ===")
        
        if not self.test_transaction_ids:
            self.log_test("Staff Role Tests", False, "No test transactions available")
            return
        
        transaction_id = self.test_transaction_ids[0]
        
        # ✔️ Staff can GET /api/bookkeeper/transactions
        status, data = await self.make_request(
            "GET", 
            "/bookkeeper/transactions",
            self.staff_token,
            params={"client_id": TEST_CLIENT_ID}
        )
        self.log_test(
            "Staff ALLOWED to GET /bookkeeper/transactions",
            status == 200 and isinstance(data.get("items"), list),
            f"Status: {status}, Found {len(data.get('items', []))} transactions"
        )
        
        # ✔️ Staff can PATCH unlocked transactions
        update_data = {
            "notes_bookkeeper": "Updated by staff for RBAC test",
            "category_bookkeeper": "office_supplies"
        }
        status, data = await self.make_request(
            "PATCH", 
            f"/bookkeeper/transactions/{transaction_id}",
            self.staff_token,
            update_data
        )
        self.log_test(
            "Staff ALLOWED to PATCH unlocked transactions",
            status == 200,
            f"Status: {status}, Notes: {data.get('notes_bookkeeper') if status == 200 else 'Failed'}"
        )
        
        # ✔️ Staff can GET history
        status, data = await self.make_request(
            "GET", 
            f"/bookkeeper/transactions/{transaction_id}/history",
            self.staff_token
        )
        self.log_test(
            "Staff ALLOWED to GET /bookkeeper/transactions/{id}/history",
            status == 200 and isinstance(data, list),
            f"Status: {status}, History entries: {len(data) if status == 200 else 0}"
        )
        
        # ✔️ Staff can bulk-update
        bulk_data = {
            "criteria": {"transaction_ids": [self.test_transaction_ids[1]]},
            "updates": {"category_bookkeeper": "travel"}
        }
        status, data = await self.make_request(
            "POST", 
            "/bookkeeper/transactions/bulk-update",
            self.staff_token,
            bulk_data
        )
        self.log_test(
            "Staff ALLOWED to POST /bookkeeper/transactions/bulk-update",
            status == 200 and data.get("success"),
            f"Status: {status}, Updated: {data.get('updated_count', 0)} transactions"
        )
        
        # ❌ Staff cannot call workpaper lock endpoint (403)
        lock_data = {
            "transaction_ids": [transaction_id],
            "workpaper_id": self.workpaper_job_id or "dummy-job-id",
            "module": "GENERAL",
            "period": "2024-25"
        }
        status, data = await self.make_request(
            "POST", 
            "/workpapers/transactions-lock",
            self.staff_token,
            lock_data
        )
        self.log_test(
            "Staff BLOCKED from POST /workpapers/transactions-lock",
            status == 403,
            f"Status: {status} (expected 403)"
        )
        
        # ❌ Staff cannot unlock (403)
        status, data = await self.make_request(
            "POST", 
            f"/bookkeeper/transactions/{transaction_id}/unlock",
            self.staff_token,
            params={"comment": "Staff trying to unlock transaction"}
        )
        self.log_test(
            "Staff BLOCKED from POST /bookkeeper/transactions/{id}/unlock",
            status == 403,
            f"Status: {status} (expected 403)"
        )
        
        # ❌ Staff cannot POST /api/myfdc/transactions (403)
        myfdc_data = {
            "date": "2024-12-16",
            "amount": 85.00,
            "gst_amount": 8.50,
            "payee_raw": "Staff Created Vendor",
            "description_raw": "Staff-created transaction (should fail)"
        }
        status, data = await self.make_request(
            "POST", 
            f"/myfdc/transactions?client_id={TEST_CLIENT_ID}",
            self.staff_token,
            myfdc_data
        )
        self.log_test(
            "Staff BLOCKED from POST /myfdc/transactions",
            status == 403,
            f"Status: {status} (expected 403)"
        )
    
    async def test_tax_agent_role_permissions(self):
        """Test 3: Tax Agent Role Tests"""
        print("\n=== Testing Tax Agent Role Permissions ===")
        
        if not self.test_transaction_ids:
            self.log_test("Tax Agent Role Tests", False, "No test transactions available")
            return
        
        transaction_id = self.test_transaction_ids[0]
        
        # ✔️ Tax agent can GET /api/bookkeeper/transactions (read-only)
        status, data = await self.make_request(
            "GET", 
            "/bookkeeper/transactions",
            self.tax_agent_token,
            params={"client_id": TEST_CLIENT_ID}
        )
        self.log_test(
            "Tax Agent ALLOWED to GET /bookkeeper/transactions (read-only)",
            status == 200 and isinstance(data.get("items"), list),
            f"Status: {status}, Found {len(data.get('items', []))} transactions"
        )
        
        # ❌ Tax agent cannot PATCH transactions (403)
        update_data = {
            "notes_bookkeeper": "Tax agent trying to edit",
            "category_bookkeeper": "professional_services"
        }
        status, data = await self.make_request(
            "PATCH", 
            f"/bookkeeper/transactions/{transaction_id}",
            self.tax_agent_token,
            update_data
        )
        self.log_test(
            "Tax Agent BLOCKED from PATCH /bookkeeper/transactions/{id}",
            status == 403,
            f"Status: {status} (expected 403)"
        )
        
        # ✔️ Tax agent can GET history
        status, data = await self.make_request(
            "GET", 
            f"/bookkeeper/transactions/{transaction_id}/history",
            self.tax_agent_token
        )
        self.log_test(
            "Tax Agent ALLOWED to GET /bookkeeper/transactions/{id}/history",
            status == 200 and isinstance(data, list),
            f"Status: {status}, History entries: {len(data) if status == 200 else 0}"
        )
        
        # ❌ Tax agent cannot bulk-update (403)
        bulk_data = {
            "criteria": {"client_id": TEST_CLIENT_ID},
            "updates": {"category_bookkeeper": "utilities"}
        }
        status, data = await self.make_request(
            "POST", 
            "/bookkeeper/transactions/bulk-update",
            self.tax_agent_token,
            bulk_data
        )
        self.log_test(
            "Tax Agent BLOCKED from POST /bookkeeper/transactions/bulk-update",
            status == 403,
            f"Status: {status} (expected 403)"
        )
        
        # ✔️ Tax agent CAN call workpaper lock endpoint
        if self.workpaper_job_id and len(self.test_transaction_ids) >= 2:
            lock_data = {
                "transaction_ids": [self.test_transaction_ids[1]],
                "workpaper_id": self.workpaper_job_id,
                "module": "GENERAL",
                "period": "2024-25"
            }
            status, data = await self.make_request(
                "POST", 
                "/workpapers/transactions-lock",
                self.tax_agent_token,
                lock_data
            )
            
            if status == 200 and data.get("success"):
                self.locked_transaction_id = self.test_transaction_ids[1]
            
            self.log_test(
                "Tax Agent ALLOWED to POST /workpapers/transactions-lock",
                status == 200 and data.get("success"),
                f"Status: {status}, Locked: {data.get('locked_count', 0)} transactions"
            )
        
        # ❌ Tax agent cannot unlock (403)
        status, data = await self.make_request(
            "POST", 
            f"/bookkeeper/transactions/{transaction_id}/unlock",
            self.tax_agent_token,
            params={"comment": "Tax agent trying to unlock transaction"}
        )
        self.log_test(
            "Tax Agent BLOCKED from POST /bookkeeper/transactions/{id}/unlock",
            status == 403,
            f"Status: {status} (expected 403)"
        )
        
        # ❌ Tax agent cannot POST /api/myfdc/transactions (403)
        myfdc_data = {
            "date": "2024-12-16",
            "amount": 95.00,
            "gst_amount": 9.50,
            "payee_raw": "Tax Agent Created Vendor",
            "description_raw": "Tax agent-created transaction (should fail)"
        }
        status, data = await self.make_request(
            "POST", 
            f"/myfdc/transactions?client_id={TEST_CLIENT_ID}",
            self.tax_agent_token,
            myfdc_data
        )
        self.log_test(
            "Tax Agent BLOCKED from POST /myfdc/transactions",
            status == 403,
            f"Status: {status} (expected 403)"
        )
    
    async def test_admin_role_permissions(self):
        """Test 4: Admin Role Tests - Full access"""
        print("\n=== Testing Admin Role Permissions ===")
        
        if not self.test_transaction_ids:
            self.log_test("Admin Role Tests", False, "No test transactions available")
            return
        
        transaction_id = self.test_transaction_ids[0]
        
        # ✔️ Admin can do everything - GET transactions
        status, data = await self.make_request(
            "GET", 
            "/bookkeeper/transactions",
            self.admin_token,
            params={"client_id": TEST_CLIENT_ID}
        )
        self.log_test(
            "Admin ALLOWED to GET /bookkeeper/transactions",
            status == 200 and isinstance(data.get("items"), list),
            f"Status: {status}, Found {len(data.get('items', []))} transactions"
        )
        
        # ✔️ Admin can PATCH any transaction
        update_data = {
            "notes_bookkeeper": "Updated by admin for RBAC test",
            "status_bookkeeper": "REVIEWED"
        }
        status, data = await self.make_request(
            "PATCH", 
            f"/bookkeeper/transactions/{transaction_id}",
            self.admin_token,
            update_data
        )
        self.log_test(
            "Admin ALLOWED to PATCH /bookkeeper/transactions/{id}",
            status == 200,
            f"Status: {status}, Status: {data.get('status_bookkeeper') if status == 200 else 'Failed'}"
        )
        
        # ✔️ Admin can bulk-update
        if len(self.test_transaction_ids) >= 3:
            bulk_data = {
                "criteria": {"transaction_ids": [self.test_transaction_ids[2]]},
                "updates": {"category_bookkeeper": "admin_category"}
            }
            status, data = await self.make_request(
                "POST", 
                "/bookkeeper/transactions/bulk-update",
                self.admin_token,
                bulk_data
            )
            self.log_test(
                "Admin ALLOWED to POST /bookkeeper/transactions/bulk-update",
                status == 200 and data.get("success"),
                f"Status: {status}, Updated: {data.get('updated_count', 0)} transactions"
            )
        
        # ✔️ Admin can lock transactions
        if self.workpaper_job_id and len(self.test_transaction_ids) >= 3:
            lock_data = {
                "transaction_ids": [self.test_transaction_ids[2]],
                "workpaper_id": self.workpaper_job_id,
                "module": "GENERAL",
                "period": "2024-25"
            }
            status, data = await self.make_request(
                "POST", 
                "/workpapers/transactions-lock",
                self.admin_token,
                lock_data
            )
            self.log_test(
                "Admin ALLOWED to POST /workpapers/transactions-lock",
                status == 200 and data.get("success"),
                f"Status: {status}, Locked: {data.get('locked_count', 0)} transactions"
            )
        
        # ✔️ Admin can unlock with comment
        if self.locked_transaction_id:
            status, data = await self.make_request(
                "POST", 
                f"/bookkeeper/transactions/{self.locked_transaction_id}/unlock",
                self.admin_token,
                params={"comment": "Admin unlocking transaction for RBAC test - sufficient comment length"}
            )
            self.log_test(
                "Admin ALLOWED to POST /bookkeeper/transactions/{id}/unlock",
                status == 200,
                f"Status: {status}, Status: {data.get('status_bookkeeper') if status == 200 else 'Failed'}"
            )
        
        # ✔️ Admin can POST /api/myfdc/transactions (for client)
        myfdc_data = {
            "date": "2024-12-16",
            "amount": 125.00,
            "gst_amount": 12.50,
            "payee_raw": "Admin Created Vendor",
            "description_raw": "Admin-created transaction for client"
        }
        status, data = await self.make_request(
            "POST", 
            f"/myfdc/transactions?client_id={TEST_CLIENT_ID}",
            self.admin_token,
            myfdc_data
        )
        self.log_test(
            "Admin ALLOWED to POST /myfdc/transactions (for client)",
            status in [200, 201] and data.get("success"),
            f"Status: {status}, Success: {data.get('success') if status in [200, 201] else 'Failed'}"
        )
    
    async def test_locked_transaction_behavior(self):
        """Test 5: Locked Transaction Behaviour (with staff)"""
        print("\n=== Testing Locked Transaction Behavior ===")
        
        # First, create and lock a transaction for this test
        if not self.workpaper_job_id:
            self.log_test("Locked Transaction Tests", False, "No workpaper job available")
            return
        
        # Create a fresh transaction for locking test
        transaction_data = {
            "date": "2024-12-17",
            "amount": 200.00,
            "gst_amount": 20.00,
            "payee_raw": "Lock Test Vendor Pty Ltd",
            "description_raw": "Transaction for lock behavior testing"
        }
        
        status, data = await self.make_request(
            "POST", 
            f"/myfdc/transactions?client_id={TEST_CLIENT_ID}",
            self.admin_token,
            transaction_data
        )
        
        if not (status in [200, 201] and data.get("success")):
            self.log_test("Locked Transaction Tests", False, "Failed to create test transaction")
            return
        
        lock_test_transaction_id = data["transaction"]["id"]
        
        # Lock the transaction using tax agent
        lock_data = {
            "transaction_ids": [lock_test_transaction_id],
            "workpaper_id": self.workpaper_job_id,
            "module": "GENERAL",
            "period": "2024-25"
        }
        status, data = await self.make_request(
            "POST", 
            "/workpapers/transactions-lock",
            self.tax_agent_token,
            lock_data
        )
        
        if not (status == 200 and data.get("success")):
            self.log_test("Locked Transaction Tests", False, "Failed to lock test transaction")
            return
        
        print(f"    Locked transaction {lock_test_transaction_id} for testing")
        
        # ✔️ Staff can edit notes_bookkeeper on LOCKED transaction
        notes_update = {"notes_bookkeeper": "Staff can edit notes on locked transaction"}
        status, data = await self.make_request(
            "PATCH", 
            f"/bookkeeper/transactions/{lock_test_transaction_id}",
            self.staff_token,
            notes_update
        )
        self.log_test(
            "Staff CAN edit notes_bookkeeper on LOCKED transaction",
            status == 200,
            f"Status: {status}, Notes updated: {'✓' if status == 200 else '✗'}"
        )
        
        # ❌ Staff cannot edit other fields on LOCKED transaction (400 error, not 403)
        other_fields_update = {
            "amount": 250.00,
            "category_bookkeeper": "office_supplies"
        }
        status, data = await self.make_request(
            "PATCH", 
            f"/bookkeeper/transactions/{lock_test_transaction_id}",
            self.staff_token,
            other_fields_update
        )
        self.log_test(
            "Staff CANNOT edit other fields on LOCKED transaction (400 error)",
            status == 400,
            f"Status: {status} (expected 400, not 403)"
        )
        
        # Verify admin can still edit locked transaction
        admin_update = {
            "amount": 275.00,
            "notes_bookkeeper": "Admin can edit any field on locked transaction"
        }
        status, data = await self.make_request(
            "PATCH", 
            f"/bookkeeper/transactions/{lock_test_transaction_id}",
            self.admin_token,
            admin_update
        )
        self.log_test(
            "Admin CAN edit any field on LOCKED transaction",
            status == 200,
            f"Status: {status}, Amount: {data.get('amount') if status == 200 else 'Failed'}"
        )
    
    async def run_all_tests(self):
        """Run all RBAC test suites"""
        print("🚀 Starting Comprehensive Transaction Engine RBAC Tests")
        print(f"Base URL: {BASE_URL}")
        print(f"Test Client: {TEST_CLIENT_ID}")
        
        # Authentication is required for all tests
        if not await self.test_authentication():
            print("❌ Authentication failed - cannot continue with RBAC tests")
            return
        
        # Setup test data
        if not await self.setup_test_data():
            print("❌ Test data setup failed - cannot continue with RBAC tests")
            return
        
        # Run all RBAC test suites
        await self.test_client_role_restrictions()
        await self.test_staff_role_permissions()
        await self.test_tax_agent_role_permissions()
        await self.test_admin_role_permissions()
        await self.test_locked_transaction_behavior()
        
        # Summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*80)
        print("📊 TRANSACTION ENGINE RBAC TEST SUMMARY")
        print("="*80)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results if result["success"])
        failed_tests = total_tests - passed_tests
        
        print(f"Total Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests}")
        print(f"❌ Failed: {failed_tests}")
        print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        # Group results by test category
        categories = {
            "Authentication": [],
            "Client Role": [],
            "Staff Role": [],
            "Tax Agent Role": [],
            "Admin Role": [],
            "Locked Transaction": [],
            "Setup": []
        }
        
        for result in self.test_results:
            test_name = result["test"]
            if "Authentication" in test_name:
                categories["Authentication"].append(result)
            elif "Client" in test_name:
                categories["Client Role"].append(result)
            elif "Staff" in test_name:
                categories["Staff Role"].append(result)
            elif "Tax Agent" in test_name:
                categories["Tax Agent Role"].append(result)
            elif "Admin" in test_name:
                categories["Admin Role"].append(result)
            elif "Locked" in test_name or "LOCKED" in test_name:
                categories["Locked Transaction"].append(result)
            else:
                categories["Setup"].append(result)
        
        for category, results in categories.items():
            if results:
                passed = sum(1 for r in results if r["success"])
                total = len(results)
                print(f"\n{category}: {passed}/{total} passed")
                
                for result in results:
                    status = "✅" if result["success"] else "❌"
                    print(f"  {status} {result['test']}")
                    if not result["success"] and result["details"]:
                        print(f"     {result['details']}")
        
        if failed_tests > 0:
            print(f"\n🔍 FAILED TESTS DETAILS:")
            for result in self.test_results:
                if not result["success"]:
                    print(f"  ❌ {result['test']}")
                    if result["details"]:
                        print(f"     {result['details']}")
                    if result["response"]:
                        print(f"     Response: {result['response']}")
        
        print("\n" + "="*80)
        
        # Test data summary
        if self.test_transaction_ids:
            print(f"🆔 Test Data Created:")
            print(f"   Client ID: {TEST_CLIENT_ID}")
            print(f"   Workpaper Job: {self.workpaper_job_id}")
            print(f"   Test Transactions: {len(self.test_transaction_ids)}")
            for i, txn_id in enumerate(self.test_transaction_ids):
                print(f"     {i+1}. {txn_id}")
            if self.locked_transaction_id:
                print(f"   Locked Transaction: {self.locked_transaction_id}")


async def main():
    """Main test runner"""
    async with TransactionRBACTester() as tester:
        await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())