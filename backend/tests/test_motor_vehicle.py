#!/usr/bin/env python3
"""
Comprehensive Motor Vehicle Module API Test Suite
Tests all MV endpoints and calculation methods as specified in the review request
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

import aiohttp

# Test configuration
BASE_URL = "https://taxcrm-bridge.preview.emergentagent.com/api"

# Test credentials
STAFF_CREDENTIALS = {"email": "staff@fdctax.com", "password": "staff123"}
ADMIN_CREDENTIALS = {"email": "admin@fdctax.com", "password": "admin123"}

# Test data
TEST_CLIENT_ID = "mv-test-client"
TEST_YEAR = "2024-25"

class MotorVehicleAPITester:
    def __init__(self):
        self.session = None
        self.staff_token = None
        self.admin_token = None
        self.test_results = []
        
        # Test data storage
        self.test_job_id = None
        self.test_module_id = None
        self.km_entry_id = None
        self.logbook_period_id = None
        self.fuel_estimate_id = None
    
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
        token: Optional[str] = None, 
        json_data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> tuple[int, Any]:
        """Make API request"""
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
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
        
        # Test calculation methods
        status, data = await self.make_request("GET", "/workpaper/mv/methods")
        self.log_test(
            "GET /workpaper/mv/methods",
            status == 200 and "methods" in data,
            f"Status: {status}, Methods count: {len(data.get('methods', []))}"
        )
        
        # Test ATO rates
        status, data = await self.make_request("GET", "/workpaper/mv/ato-rates")
        self.log_test(
            "GET /workpaper/mv/ato-rates",
            status == 200 and "cents_per_km_rate" in data,
            f"Status: {status}, Cents/km rate: {data.get('cents_per_km_rate', 'N/A')}"
        )
        
        # Test GST rules
        status, data = await self.make_request("GET", "/workpaper/mv/gst-rules")
        self.log_test(
            "GET /workpaper/mv/gst-rules",
            status == 200 and isinstance(data, dict),
            f"Status: {status}, GST rules count: {len(data) if isinstance(data, dict) else 0}"
        )
    
    async def setup_test_job(self):
        """Setup: Create test job with motor vehicle module"""
        print("\n=== Setting Up Test Job ===")
        
        # Create job
        job_data = {
            "client_id": TEST_CLIENT_ID,
            "year": TEST_YEAR,
            "notes": "Motor Vehicle API test job",
            "auto_create_modules": True
        }
        
        status, data = await self.make_request("POST", "/workpaper/jobs", self.staff_token, job_data)
        success = status in [200, 201]
        
        if success:
            self.test_job_id = data.get("id")
        
        self.log_test(
            "Create Test Job",
            success and self.test_job_id is not None,
            f"Status: {status}, Job ID: {self.test_job_id if success else 'Failed'}"
        )
        
        # Get motor vehicle module
        if self.test_job_id:
            status, modules = await self.make_request("GET", f"/workpaper/clients/{TEST_CLIENT_ID}/jobs/{TEST_YEAR}/modules", self.staff_token)
            if status == 200:
                for module in modules:
                    if module.get("module_type") == "motor_vehicle":
                        self.test_module_id = module["id"]
                        break
        
        self.log_test(
            "Find Motor Vehicle Module",
            self.test_module_id is not None,
            f"Module ID: {self.test_module_id if self.test_module_id else 'Not found'}"
        )
        
        return self.test_module_id is not None
    
    async def test_module_detail_and_config(self):
        """Test 5-6: Module Detail & Config"""
        print("\n=== Testing Module Detail & Config ===")
        
        if not self.test_module_id:
            self.log_test("Module Detail & Config", False, "No module ID available")
            return
        
        # Test get module detail
        status, data = await self.make_request("GET", f"/workpaper/mv/modules/{self.test_module_id}", self.staff_token)
        self.log_test(
            f"GET /workpaper/mv/modules/{self.test_module_id}",
            status == 200 and data.get("module_id") == self.test_module_id,
            f"Status: {status}, Module type: {data.get('module_type') if status == 200 else 'N/A'}"
        )
        
        # Test update config
        config_data = {
            "method": "cents_per_km",
            "business_km": 3000,
            "total_km": 12000,
            "private_km": 9000
        }
        status, data = await self.make_request("PATCH", f"/workpaper/mv/modules/{self.test_module_id}/config", self.staff_token, config_data)
        self.log_test(
            f"PATCH /workpaper/mv/modules/{self.test_module_id}/config",
            status == 200 and data.get("success") == True,
            f"Status: {status}, Config updated: {'✓' if status == 200 else '✗'}"
        )
    
    async def test_km_tracking(self):
        """Test 7-10: KM Tracking"""
        print("\n=== Testing KM Tracking ===")
        
        if not self.test_module_id:
            self.log_test("KM Tracking", False, "No module ID available")
            return
        
        # Create KM summary entry
        km_data = {
            "entry_type": "summary",
            "date_from": "2024-07-01",
            "date_to": "2025-06-30",
            "total_km": 12000,
            "business_km": 3000,
            "private_km": 9000,
            "source": "manual",
            "notes": "Annual summary for testing"
        }
        
        status, data = await self.make_request("POST", f"/workpaper/mv/modules/{self.test_module_id}/km", self.staff_token, km_data)
        success = status in [200, 201]
        
        if success:
            self.km_entry_id = data.get("id")
        
        self.log_test(
            f"POST /workpaper/mv/modules/{self.test_module_id}/km",
            success and self.km_entry_id is not None,
            f"Status: {status}, KM Entry ID: {self.km_entry_id if success else 'Failed'}"
        )
        
        # List KM entries
        status, data = await self.make_request("GET", f"/workpaper/mv/modules/{self.test_module_id}/km", self.staff_token)
        self.log_test(
            f"GET /workpaper/mv/modules/{self.test_module_id}/km",
            status == 200 and isinstance(data, list) and len(data) > 0,
            f"Status: {status}, KM entries count: {len(data) if status == 200 else 0}"
        )
        
        # Get KM summary
        status, data = await self.make_request("GET", f"/workpaper/mv/modules/{self.test_module_id}/km/summary", self.staff_token)
        self.log_test(
            f"GET /workpaper/mv/modules/{self.test_module_id}/km/summary",
            status == 200 and "total_km" in data,
            f"Status: {status}, Total KM: {data.get('total_km', 0) if status == 200 else 'N/A'}"
        )
        
        # Delete KM entry (test later to keep data for calculations)
        # We'll test this after calculations are done
    
    async def test_asset_management(self):
        """Test 11-13: Asset Management"""
        print("\n=== Testing Asset Management ===")
        
        if not self.test_module_id:
            self.log_test("Asset Management", False, "No module ID available")
            return
        
        # Create vehicle purchase
        purchase_data = {
            "make": "Toyota",
            "model": "Camry",
            "year": 2023,
            "registration": "ABC123",
            "purchase_date": "2023-01-15",
            "purchase_price": 35000.00,
            "purchase_gst": 3181.82,
            "gst_registered_at_purchase": True,
            "depreciation_method": "diminishing_value",
            "effective_life_years": 8.0,
            "notes": "Test vehicle for MV calculations"
        }
        
        status, data = await self.make_request("POST", f"/workpaper/mv/modules/{self.test_module_id}/purchase", self.staff_token, purchase_data)
        success = status in [200, 201]
        
        self.log_test(
            f"POST /workpaper/mv/modules/{self.test_module_id}/purchase",
            success,
            f"Status: {status}, Purchase price: ${data.get('purchase_price', 0) if success else 'Failed'}"
        )
        
        # Get asset details
        status, data = await self.make_request("GET", f"/workpaper/mv/modules/{self.test_module_id}/asset", self.staff_token)
        self.log_test(
            f"GET /workpaper/mv/modules/{self.test_module_id}/asset",
            status == 200 and data is not None,
            f"Status: {status}, Asset: {data.get('make', '') + ' ' + data.get('model', '') if status == 200 and data else 'N/A'}"
        )
        
        # Record vehicle sale (for balancing adjustment test)
        sale_data = {
            "sale_date": "2025-01-31",
            "sale_price": 28000.00,
            "sale_gst": 2545.45
        }
        
        status, data = await self.make_request("POST", f"/workpaper/mv/modules/{self.test_module_id}/sale", self.staff_token, sale_data)
        self.log_test(
            f"POST /workpaper/mv/modules/{self.test_module_id}/sale",
            status == 200,
            f"Status: {status}, Sale price: ${data.get('sale_price', 0) if status == 200 else 'Failed'}"
        )
    
    async def test_logbook_period(self):
        """Test 14-15: Logbook Period"""
        print("\n=== Testing Logbook Period ===")
        
        if not self.test_module_id:
            self.log_test("Logbook Period", False, "No module ID available")
            return
        
        # Create logbook period (12+ weeks = 84+ days)
        logbook_data = {
            "period_start": "2024-07-01",
            "period_end": "2024-09-23",  # 84 days
            "total_km": 7000,
            "business_km": 2800,
            "private_km": 4200,
            "notes": "Representative 12-week logbook period"
        }
        
        status, data = await self.make_request("POST", f"/workpaper/mv/modules/{self.test_module_id}/logbook-period", self.staff_token, logbook_data)
        success = status in [200, 201]
        
        if success:
            self.logbook_period_id = data.get("id")
        
        self.log_test(
            f"POST /workpaper/mv/modules/{self.test_module_id}/logbook-period",
            success and self.logbook_period_id is not None,
            f"Status: {status}, Business %: {data.get('business_percentage', 0) if success else 'Failed'}%"
        )
        
        # Approve logbook period (admin only)
        if self.logbook_period_id:
            status, data = await self.make_request("POST", f"/workpaper/mv/modules/{self.test_module_id}/logbook-period/{self.logbook_period_id}/approve", self.admin_token)
            self.log_test(
                f"POST /workpaper/mv/modules/{self.test_module_id}/logbook-period/{self.logbook_period_id}/approve",
                status == 200,
                f"Status: {status}, Approved: {'✓' if status == 200 else '✗'}"
            )
    
    async def test_fuel_estimate(self):
        """Test 16: Fuel Estimate"""
        print("\n=== Testing Fuel Estimate ===")
        
        if not self.test_module_id:
            self.log_test("Fuel Estimate", False, "No module ID available")
            return
        
        # Create fuel estimate
        fuel_data = {
            "fuel_type": "petrol",
            "engine_size_litres": 2.0,
            "consumption_rate": 9.0,  # L/100km
            "fuel_price_per_litre": 1.85,
            "business_km": 4000,
            "notes": "Estimated fuel for testing"
        }
        
        status, data = await self.make_request("POST", f"/workpaper/mv/modules/{self.test_module_id}/fuel-estimate", self.staff_token, fuel_data)
        success = status in [200, 201]
        
        if success:
            self.fuel_estimate_id = data.get("id")
        
        self.log_test(
            f"POST /workpaper/mv/modules/{self.test_module_id}/fuel-estimate",
            success and self.fuel_estimate_id is not None,
            f"Status: {status}, Estimated cost: ${data.get('estimated_fuel_cost', 0) if success else 'Failed'}"
        )
    
    async def add_test_transactions(self):
        """Add test transactions for logbook method"""
        print("\n=== Adding Test Transactions ===")
        
        if not self.test_job_id or not self.test_module_id:
            self.log_test("Add Test Transactions", False, "Missing job or module ID")
            return
        
        transactions = [
            {
                "client_id": TEST_CLIENT_ID,
                "job_id": self.test_job_id,
                "module_instance_id": self.test_module_id,
                "source": "manual",
                "date": "2024-08-15",
                "amount": 1500.00,
                "gst_amount": 136.36,
                "category": "vehicle_fuel",
                "description": "Fuel expenses for business vehicle",
                "vendor": "Shell Service Station"
            },
            {
                "client_id": TEST_CLIENT_ID,
                "job_id": self.test_job_id,
                "module_instance_id": self.test_module_id,
                "source": "manual",
                "date": "2024-09-01",
                "amount": 600.00,
                "gst_amount": 30.00,
                "category": "vehicle_registration",
                "description": "Vehicle registration renewal",
                "vendor": "VicRoads"
            },
            {
                "client_id": TEST_CLIENT_ID,
                "job_id": self.test_job_id,
                "module_instance_id": self.test_module_id,
                "source": "manual",
                "date": "2024-10-15",
                "amount": 800.00,
                "gst_amount": 60.00,
                "category": "vehicle_insurance",
                "description": "Comprehensive vehicle insurance",
                "vendor": "RACV Insurance"
            },
            {
                "client_id": TEST_CLIENT_ID,
                "job_id": self.test_job_id,
                "module_instance_id": self.test_module_id,
                "source": "manual",
                "date": "2024-11-20",
                "amount": 400.00,
                "gst_amount": 36.36,
                "category": "vehicle_repairs",
                "description": "Vehicle service and repairs",
                "vendor": "Toyota Service Centre"
            }
        ]
        
        transaction_count = 0
        for txn_data in transactions:
            status, data = await self.make_request("POST", "/workpaper/transactions", self.staff_token, txn_data)
            if status in [200, 201]:
                transaction_count += 1
        
        self.log_test(
            "Add Test Transactions",
            transaction_count == len(transactions),
            f"Added {transaction_count}/{len(transactions)} transactions"
        )
    
    async def test_calculation_methods(self):
        """Test 17-20: All Calculation Methods"""
        print("\n=== Testing Calculation Methods ===")
        
        if not self.test_module_id:
            self.log_test("Calculation Methods", False, "No module ID available")
            return
        
        # Test Case 1: Cents per KM Method
        print("\n--- Test Case 1: Cents per KM Method ---")
        
        # Update config for cents per km
        config_data = {
            "method": "cents_per_km",
            "business_km": 3000,
            "total_km": 12000
        }
        status, data = await self.make_request("PATCH", f"/workpaper/mv/modules/{self.test_module_id}/config", self.staff_token, config_data)
        
        # Calculate
        status, data = await self.make_request("POST", f"/workpaper/mv/modules/{self.test_module_id}/calculate", self.staff_token)
        
        expected_deduction = 3000 * 0.85  # $2550
        expected_gst = round(expected_deduction / 11, 2)  # $231.82
        
        actual_deduction = data.get("result", {}).get("deduction", 0) if status == 200 else 0
        actual_gst = data.get("result", {}).get("gst_claimable", 0) if status == 200 else 0
        
        self.log_test(
            "Cents per KM Calculation",
            status == 200 and abs(actual_deduction - expected_deduction) < 0.01,
            f"Status: {status}, Deduction: ${actual_deduction} (expected ${expected_deduction}), GST: ${actual_gst} (expected ${expected_gst})"
        )
        
        # Test Case 2: Logbook Method with Depreciation
        print("\n--- Test Case 2: Logbook Method with Depreciation ---")
        
        # Update config for logbook method
        config_data = {
            "method": "logbook",
            "logbook_pct": 40.0  # 40% business use from logbook
        }
        status, data = await self.make_request("PATCH", f"/workpaper/mv/modules/{self.test_module_id}/config", self.staff_token, config_data)
        
        # Calculate
        status, data = await self.make_request("POST", f"/workpaper/mv/modules/{self.test_module_id}/calculate", self.staff_token)
        
        self.log_test(
            "Logbook Method Calculation",
            status == 200 and data.get("result", {}).get("method") == "logbook",
            f"Status: {status}, Method: {data.get('result', {}).get('method') if status == 200 else 'N/A'}, Business %: {data.get('result', {}).get('business_percentage', 0) if status == 200 else 0}%"
        )
        
        # Check depreciation was calculated
        depreciation = data.get("result", {}).get("depreciation") if status == 200 else None
        self.log_test(
            "Depreciation Calculation",
            depreciation is not None and depreciation.get("depreciation_amount", 0) > 0,
            f"Depreciation amount: ${depreciation.get('depreciation_amount', 0) if depreciation else 0}"
        )
        
        # Check balancing adjustment (vehicle was sold)
        balancing = data.get("result", {}).get("balancing_adjustment") if status == 200 else None
        self.log_test(
            "Balancing Adjustment",
            balancing is not None,
            f"Balancing adjustment: ${balancing if balancing else 0} ({'profit' if data.get('result', {}).get('is_balancing_profit') else 'loss'})"
        )
        
        # Test Case 3: Estimated Fuel Method
        print("\n--- Test Case 3: Estimated Fuel Method ---")
        
        # Update config for estimated fuel
        config_data = {
            "method": "estimated_fuel",
            "business_km": 4000
        }
        status, data = await self.make_request("PATCH", f"/workpaper/mv/modules/{self.test_module_id}/config", self.staff_token, config_data)
        
        # Calculate
        status, data = await self.make_request("POST", f"/workpaper/mv/modules/{self.test_module_id}/calculate", self.staff_token)
        
        # Expected: 4000km / 100 * 9L/100km * $1.85/L = 360L * $1.85 = $666
        expected_litres = 360
        expected_cost = 666
        expected_gst = round(expected_cost / 11, 2)
        
        fuel_estimate = data.get("result", {}).get("fuel_estimate") if status == 200 else None
        actual_cost = data.get("result", {}).get("deduction", 0) if status == 200 else 0
        
        self.log_test(
            "Estimated Fuel Calculation",
            status == 200 and fuel_estimate is not None,
            f"Status: {status}, Estimated cost: ${actual_cost}, Litres: {fuel_estimate.get('estimated_litres', 0) if fuel_estimate else 0}"
        )
        
        # Test Case 4: Actual Expenses Method
        print("\n--- Test Case 4: Actual Expenses Method ---")
        
        # Update config for actual expenses
        config_data = {
            "method": "actual_expenses"
        }
        status, data = await self.make_request("PATCH", f"/workpaper/mv/modules/{self.test_module_id}/config", self.staff_token, config_data)
        
        # Calculate
        status, data = await self.make_request("POST", f"/workpaper/mv/modules/{self.test_module_id}/calculate", self.staff_token)
        
        self.log_test(
            "Actual Expenses Calculation",
            status == 200 and data.get("result", {}).get("method") == "actual_expenses",
            f"Status: {status}, Method: {data.get('result', {}).get('method') if status == 200 else 'N/A'}, Business %: {data.get('result', {}).get('business_percentage', 0) if status == 200 else 0}%"
        )
    
    async def test_freeze_and_reopen(self):
        """Test 21-22: Freeze and Reopen Module"""
        print("\n=== Testing Freeze and Reopen ===")
        
        if not self.test_module_id:
            self.log_test("Freeze and Reopen", False, "No module ID available")
            return
        
        # Test Case 5: Freeze Module
        freeze_data = {"reason": "Testing freeze functionality with comprehensive snapshot"}
        status, data = await self.make_request("POST", f"/workpaper/mv/modules/{self.test_module_id}/freeze", self.staff_token, freeze_data)
        
        snapshot_id = data.get("snapshot_id") if status == 200 else None
        
        self.log_test(
            f"POST /workpaper/mv/modules/{self.test_module_id}/freeze",
            status == 200 and snapshot_id is not None,
            f"Status: {status}, Snapshot ID: {snapshot_id if snapshot_id else 'Failed'}"
        )
        
        # Verify module is frozen (try to update config - should fail)
        config_data = {"method": "cents_per_km"}
        status, data = await self.make_request("PATCH", f"/workpaper/mv/modules/{self.test_module_id}/config", self.staff_token, config_data)
        
        self.log_test(
            "Verify Module Frozen (Config Update Should Fail)",
            status == 400,
            f"Status: {status} (expected 400), Message: {data if isinstance(data, str) else data.get('detail', 'N/A')}"
        )
        
        # Test Case 6: Reopen Module (Admin)
        reopen_params = {"reason": "Testing reopen functionality"}
        status, data = await self.make_request("POST", f"/workpaper/modules/{self.test_module_id}/reopen", self.admin_token, params=reopen_params)
        
        self.log_test(
            f"POST /workpaper/modules/{self.test_module_id}/reopen (admin only)",
            status == 200,
            f"Status: {status}, Module status: {data.get('status') if status == 200 else 'Failed'}"
        )
        
        # Verify module can be updated again
        config_data = {"method": "logbook"}
        status, data = await self.make_request("PATCH", f"/workpaper/mv/modules/{self.test_module_id}/config", self.staff_token, config_data)
        
        self.log_test(
            "Verify Module Reopened (Config Update Should Work)",
            status == 200,
            f"Status: {status}, Config updated: {'✓' if status == 200 else '✗'}"
        )
    
    async def test_km_entry_deletion(self):
        """Test KM Entry Deletion (deferred from earlier)"""
        print("\n=== Testing KM Entry Deletion ===")
        
        if not self.test_module_id or not self.km_entry_id:
            self.log_test("KM Entry Deletion", False, "Missing module or KM entry ID")
            return
        
        # Delete KM entry
        status, data = await self.make_request("DELETE", f"/workpaper/mv/modules/{self.test_module_id}/km/{self.km_entry_id}", self.staff_token)
        
        self.log_test(
            f"DELETE /workpaper/mv/modules/{self.test_module_id}/km/{self.km_entry_id}",
            status == 200 and data.get("success") == True,
            f"Status: {status}, Deleted: {'✓' if status == 200 else '✗'}"
        )
    
    async def run_all_tests(self):
        """Run all test suites"""
        print("🚀 Starting Comprehensive Motor Vehicle API Tests")
        print(f"Base URL: {BASE_URL}")
        print(f"Test Client: {TEST_CLIENT_ID}")
        print(f"Test Year: {TEST_YEAR}")
        
        # Authentication is required for most tests
        if not await self.test_authentication():
            print("❌ Authentication failed - cannot continue with API tests")
            return
        
        # Run all test suites
        await self.test_reference_data()
        
        if not await self.setup_test_job():
            print("❌ Failed to setup test job - cannot continue")
            return
        
        await self.test_module_detail_and_config()
        await self.test_km_tracking()
        await self.test_asset_management()
        await self.test_logbook_period()
        await self.test_fuel_estimate()
        await self.add_test_transactions()
        await self.test_calculation_methods()
        await self.test_freeze_and_reopen()
        await self.test_km_entry_deletion()
        
        # Summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("📊 MOTOR VEHICLE API TEST SUMMARY")
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
        if self.test_job_id:
            print(f"🆔 Test Data Created:")
            print(f"   Job ID: {self.test_job_id}")
            print(f"   Module ID: {self.test_module_id}")
            print(f"   KM Entry ID: {self.km_entry_id}")
            print(f"   Logbook Period ID: {self.logbook_period_id}")
            print(f"   Fuel Estimate ID: {self.fuel_estimate_id}")


async def main():
    """Main test runner"""
    async with MotorVehicleAPITester() as tester:
        await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())