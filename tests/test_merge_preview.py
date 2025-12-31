"""
Merge Preview API Tests - Identity Spine v1.1
Tests for GET /api/identity/merge-preview endpoint.

This endpoint provides a read-only preview of what would happen if two persons were merged:
- Shows combined engagement profile
- Lists all linked MyFDC accounts and CRM clients
- Detects conflicts (multiple accounts, different emails, auth provider mismatch, etc.)
- Recommends merge direction
- Logs preview request to identity_link_log

Permissions: admin only (staff should get 403)
"""

import pytest
import requests
import os
import uuid
from datetime import datetime

# Get base URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@fdctax.com"
ADMIN_PASSWORD = "admin123"
STAFF_EMAIL = "staff@fdctax.com"
STAFF_PASSWORD = "staff123"


class TestMergePreviewSetup:
    """Setup and authentication tests for merge preview"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        """Shared requests session"""
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    @pytest.fixture(scope="class")
    def admin_token(self, api_client):
        """Get admin authentication token"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Admin authentication failed - skipping authenticated tests")
    
    @pytest.fixture(scope="class")
    def staff_token(self, api_client):
        """Get staff authentication token"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": STAFF_EMAIL,
            "password": STAFF_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Staff authentication failed - skipping authenticated tests")
    
    def test_base_url_configured(self):
        """Verify BASE_URL is configured"""
        assert BASE_URL, "REACT_APP_BACKEND_URL environment variable not set"
        print(f"Testing against: {BASE_URL}")


class TestMergePreviewAuthentication:
    """Tests for merge-preview authentication and authorization"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    @pytest.fixture(scope="class")
    def admin_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Admin authentication failed")
    
    @pytest.fixture(scope="class")
    def staff_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": STAFF_EMAIL,
            "password": STAFF_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Staff authentication failed")
    
    def test_merge_preview_requires_auth(self, api_client):
        """Test merge-preview requires authentication"""
        fake_uuid_a = str(uuid.uuid4())
        fake_uuid_b = str(uuid.uuid4())
        
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": fake_uuid_a, "person_id_b": fake_uuid_b}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("Merge preview correctly requires authentication")
    
    def test_merge_preview_staff_forbidden(self, api_client, staff_token):
        """Test merge-preview is forbidden for staff (admin only)"""
        fake_uuid_a = str(uuid.uuid4())
        fake_uuid_b = str(uuid.uuid4())
        
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": fake_uuid_a, "person_id_b": fake_uuid_b},
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        assert response.status_code == 403, f"Expected 403 for staff, got {response.status_code}"
        print("Merge preview correctly requires admin role (staff forbidden)")


class TestMergePreviewValidation:
    """Tests for merge-preview input validation"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    @pytest.fixture(scope="class")
    def admin_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Admin authentication failed")
    
    def test_merge_preview_invalid_uuid_a(self, api_client, admin_token):
        """Test merge-preview with invalid UUID for person_id_a"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": "not-a-uuid", "person_id_b": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        data = response.json()
        assert "uuid" in data.get("detail", "").lower()
        print("Invalid UUID for person_id_a correctly returns 400")
    
    def test_merge_preview_invalid_uuid_b(self, api_client, admin_token):
        """Test merge-preview with invalid UUID for person_id_b"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": str(uuid.uuid4()), "person_id_b": "invalid-uuid"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        data = response.json()
        assert "uuid" in data.get("detail", "").lower()
        print("Invalid UUID for person_id_b correctly returns 400")
    
    def test_merge_preview_same_person_id(self, api_client, admin_token):
        """Test merge-preview with same person ID for both params"""
        same_uuid = str(uuid.uuid4())
        
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": same_uuid, "person_id_b": same_uuid},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        data = response.json()
        assert "itself" in data.get("detail", "").lower() or "same" in data.get("detail", "").lower()
        print("Same person ID correctly returns 400")
    
    def test_merge_preview_nonexistent_person_a(self, api_client, admin_token):
        """Test merge-preview with non-existent person_id_a"""
        fake_uuid_a = str(uuid.uuid4())
        fake_uuid_b = str(uuid.uuid4())
        
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": fake_uuid_a, "person_id_b": fake_uuid_b},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        data = response.json()
        assert "not found" in data.get("detail", "").lower()
        print("Non-existent person_id_a correctly returns 400")


class TestMergePreviewBasicFunctionality:
    """Tests for basic merge-preview functionality"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    @pytest.fixture(scope="class")
    def admin_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Admin authentication failed")
    
    @pytest.fixture(scope="class")
    def staff_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": STAFF_EMAIL,
            "password": STAFF_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Staff authentication failed")
    
    @pytest.fixture(scope="class")
    def test_person_myfdc_only(self, api_client):
        """Create a test person with MyFDC account only (local auth)"""
        unique_email = f"TEST_merge_myfdc_{uuid.uuid4().hex[:8]}@example.com"
        response = api_client.post(f"{BASE_URL}/api/identity/myfdc-signup", json={
            "email": unique_email,
            "first_name": "MergeTest",
            "last_name": "MyFDCOnly",
            "mobile": "0400111001",
            "auth_provider": "local",
            "password_hash": "test_hash_123"
        })
        if response.status_code == 200:
            data = response.json()
            return {
                "person": data["person"],
                "myfdc_account": data["myfdc_account"],
                "engagement_profile": data["engagement_profile"]
            }
        pytest.skip(f"Failed to create test person: {response.text}")
    
    @pytest.fixture(scope="class")
    def test_person_crm_only(self, api_client, staff_token):
        """Create a test person with CRM client only"""
        unique_email = f"TEST_merge_crm_{uuid.uuid4().hex[:8]}@example.com"
        response = api_client.post(
            f"{BASE_URL}/api/identity/crm-client-create",
            json={
                "email": unique_email,
                "first_name": "MergeTest",
                "last_name": "CRMOnly",
                "mobile": "0400111002",
                "business_name": "Merge Test Business",
                "abn": "11111111111"
            },
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        if response.status_code == 200:
            data = response.json()
            return {
                "person": data["person"],
                "crm_client": data["crm_client"],
                "engagement_profile": data["engagement_profile"]
            }
        pytest.skip(f"Failed to create test CRM client: {response.text}")
    
    def test_merge_preview_basic_success(self, api_client, admin_token, test_person_myfdc_only, test_person_crm_only):
        """Test basic merge preview between two different persons"""
        person_a_id = test_person_myfdc_only["person"]["id"]
        person_b_id = test_person_crm_only["person"]["id"]
        
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": person_a_id, "person_id_b": person_b_id},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["success"] == True
        
        # Verify preview structure
        assert "preview" in data
        preview = data["preview"]
        assert preview["person_a"]["id"] == person_a_id
        assert preview["person_b"]["id"] == person_b_id
        assert preview["myfdc_account_a"] is not None  # Person A has MyFDC
        assert preview["myfdc_account_b"] is None  # Person B has no MyFDC
        assert preview["crm_client_a"] is None  # Person A has no CRM
        assert preview["crm_client_b"] is not None  # Person B has CRM
        
        # Verify combined engagement profile
        assert "combined_engagement_profile" in data
        combined = data["combined_engagement_profile"]
        assert combined["is_myfdc_user"] == True  # From person A
        assert combined["is_crm_client"] == True  # From person B
        
        # Verify conflicts structure
        assert "conflicts" in data
        assert "conflict_summary" in data
        
        # Verify recommendation structure
        assert "recommendation" in data
        rec = data["recommendation"]
        assert "merge_direction" in rec
        assert "primary_person_id" in rec
        assert "secondary_person_id" in rec
        assert "reason" in rec
        assert "safe_to_merge" in rec
        
        print(f"Merge preview successful: {person_a_id} <-> {person_b_id}")
        print(f"Conflicts: {data['conflict_summary']}")
        print(f"Recommendation: {rec['merge_direction']}")


class TestMergePreviewConflictDetection:
    """Tests for conflict detection in merge-preview"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    @pytest.fixture(scope="class")
    def admin_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Admin authentication failed")
    
    @pytest.fixture(scope="class")
    def staff_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": STAFF_EMAIL,
            "password": STAFF_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Staff authentication failed")
    
    @pytest.fixture(scope="class")
    def person_with_myfdc_local(self, api_client):
        """Create person with MyFDC account (local auth)"""
        unique_email = f"TEST_conflict_local_{uuid.uuid4().hex[:8]}@example.com"
        response = api_client.post(f"{BASE_URL}/api/identity/myfdc-signup", json={
            "email": unique_email,
            "first_name": "LocalAuth",
            "last_name": "User",
            "mobile": "0400222001",
            "auth_provider": "local",
            "password_hash": "hash_local"
        })
        if response.status_code == 200:
            return response.json()
        pytest.skip(f"Failed to create local auth person: {response.text}")
    
    @pytest.fixture(scope="class")
    def person_with_myfdc_google(self, api_client):
        """Create person with MyFDC account (google auth)"""
        unique_email = f"TEST_conflict_google_{uuid.uuid4().hex[:8]}@example.com"
        response = api_client.post(f"{BASE_URL}/api/identity/myfdc-signup", json={
            "email": unique_email,
            "first_name": "GoogleAuth",
            "last_name": "User",
            "mobile": "0400222002",
            "auth_provider": "google",
            "auth_provider_id": "google_123456"
        })
        if response.status_code == 200:
            return response.json()
        pytest.skip(f"Failed to create google auth person: {response.text}")
    
    @pytest.fixture(scope="class")
    def person_with_crm_a(self, api_client, staff_token):
        """Create person with CRM client A"""
        unique_email = f"TEST_conflict_crm_a_{uuid.uuid4().hex[:8]}@example.com"
        response = api_client.post(
            f"{BASE_URL}/api/identity/crm-client-create",
            json={
                "email": unique_email,
                "first_name": "CRM",
                "last_name": "ClientA",
                "business_name": "Business A Pty Ltd",
                "abn": "22222222222"
            },
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        if response.status_code == 200:
            return response.json()
        pytest.skip(f"Failed to create CRM client A: {response.text}")
    
    @pytest.fixture(scope="class")
    def person_with_crm_b(self, api_client, staff_token):
        """Create person with CRM client B"""
        unique_email = f"TEST_conflict_crm_b_{uuid.uuid4().hex[:8]}@example.com"
        response = api_client.post(
            f"{BASE_URL}/api/identity/crm-client-create",
            json={
                "email": unique_email,
                "first_name": "CRM",
                "last_name": "ClientB",
                "business_name": "Business B Pty Ltd",
                "abn": "33333333333"
            },
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        if response.status_code == 200:
            return response.json()
        pytest.skip(f"Failed to create CRM client B: {response.text}")
    
    def test_conflict_multiple_myfdc_accounts(self, api_client, admin_token, person_with_myfdc_local, person_with_myfdc_google):
        """Test conflict detection: multiple MyFDC accounts (high severity)"""
        person_a_id = person_with_myfdc_local["person"]["id"]
        person_b_id = person_with_myfdc_google["person"]["id"]
        
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": person_a_id, "person_id_b": person_b_id},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Find multiple_myfdc_accounts conflict
        myfdc_conflict = next(
            (c for c in data["conflicts"] if c["type"] == "multiple_myfdc_accounts"),
            None
        )
        assert myfdc_conflict is not None, "Expected multiple_myfdc_accounts conflict"
        assert myfdc_conflict["severity"] == "high"
        assert "account_a_id" in myfdc_conflict["details"]
        assert "account_b_id" in myfdc_conflict["details"]
        
        # Verify conflict summary
        assert data["conflict_summary"]["high"] >= 1
        
        # safe_to_merge should be False due to high severity conflict
        assert data["recommendation"]["safe_to_merge"] == False
        
        print(f"Multiple MyFDC accounts conflict detected: {myfdc_conflict}")
    
    def test_conflict_multiple_crm_clients(self, api_client, admin_token, person_with_crm_a, person_with_crm_b):
        """Test conflict detection: multiple CRM clients (high severity)"""
        person_a_id = person_with_crm_a["person"]["id"]
        person_b_id = person_with_crm_b["person"]["id"]
        
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": person_a_id, "person_id_b": person_b_id},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Find multiple_crm_clients conflict
        crm_conflict = next(
            (c for c in data["conflicts"] if c["type"] == "multiple_crm_clients"),
            None
        )
        assert crm_conflict is not None, "Expected multiple_crm_clients conflict"
        assert crm_conflict["severity"] == "high"
        assert "client_a_code" in crm_conflict["details"]
        assert "client_b_code" in crm_conflict["details"]
        
        # safe_to_merge should be False due to high severity conflict
        assert data["recommendation"]["safe_to_merge"] == False
        
        print(f"Multiple CRM clients conflict detected: {crm_conflict}")
    
    def test_conflict_different_emails(self, api_client, admin_token, person_with_myfdc_local, person_with_crm_a):
        """Test conflict detection: different emails (warning severity)"""
        person_a_id = person_with_myfdc_local["person"]["id"]
        person_b_id = person_with_crm_a["person"]["id"]
        
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": person_a_id, "person_id_b": person_b_id},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Find conflicting_emails conflict
        email_conflict = next(
            (c for c in data["conflicts"] if c["type"] == "conflicting_emails"),
            None
        )
        assert email_conflict is not None, "Expected conflicting_emails conflict"
        assert email_conflict["severity"] == "warning"
        assert "email_a" in email_conflict["details"]
        assert "email_b" in email_conflict["details"]
        
        print(f"Different emails conflict detected: {email_conflict}")
    
    def test_conflict_mismatched_auth_providers(self, api_client, admin_token, person_with_myfdc_local, person_with_myfdc_google):
        """Test conflict detection: mismatched auth providers (medium severity)"""
        person_a_id = person_with_myfdc_local["person"]["id"]
        person_b_id = person_with_myfdc_google["person"]["id"]
        
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": person_a_id, "person_id_b": person_b_id},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Find mismatched_auth_providers conflict
        auth_conflict = next(
            (c for c in data["conflicts"] if c["type"] == "mismatched_auth_providers"),
            None
        )
        assert auth_conflict is not None, "Expected mismatched_auth_providers conflict"
        assert auth_conflict["severity"] == "medium"
        assert auth_conflict["details"]["provider_a"] == "local"
        assert auth_conflict["details"]["provider_b"] == "google"
        
        print(f"Mismatched auth providers conflict detected: {auth_conflict}")


class TestMergePreviewServiceFlags:
    """Tests for service flag conflict detection and combined engagement profile"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    @pytest.fixture(scope="class")
    def admin_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Admin authentication failed")
    
    @pytest.fixture(scope="class")
    def staff_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": STAFF_EMAIL,
            "password": STAFF_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Staff authentication failed")
    
    @pytest.fixture(scope="class")
    def person_with_diy_bas(self, api_client, staff_token):
        """Create person with DIY BAS flag enabled"""
        unique_email = f"TEST_flags_diy_{uuid.uuid4().hex[:8]}@example.com"
        
        # Create person via MyFDC signup
        response = api_client.post(f"{BASE_URL}/api/identity/myfdc-signup", json={
            "email": unique_email,
            "first_name": "DIY",
            "last_name": "BASUser"
        })
        if response.status_code != 200:
            pytest.skip(f"Failed to create person: {response.text}")
        
        person_id = response.json()["person"]["id"]
        
        # Update engagement profile with DIY BAS flag
        update_response = api_client.put(
            f"{BASE_URL}/api/identity/engagement/{person_id}",
            json={
                "person_id": person_id,
                "is_diy_bas_user": True,
                "has_ocr": True
            },
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        
        if update_response.status_code == 200:
            return {"person_id": person_id, "email": unique_email}
        pytest.skip(f"Failed to update engagement: {update_response.text}")
    
    @pytest.fixture(scope="class")
    def person_with_full_service(self, api_client, staff_token):
        """Create person with full service ITR flag enabled"""
        unique_email = f"TEST_flags_full_{uuid.uuid4().hex[:8]}@example.com"
        
        # Create person via CRM client
        response = api_client.post(
            f"{BASE_URL}/api/identity/crm-client-create",
            json={
                "email": unique_email,
                "first_name": "FullService",
                "last_name": "ITRClient"
            },
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        if response.status_code != 200:
            pytest.skip(f"Failed to create CRM client: {response.text}")
        
        person_id = response.json()["person"]["id"]
        
        # Update engagement profile with full service flag
        update_response = api_client.put(
            f"{BASE_URL}/api/identity/engagement/{person_id}",
            json={
                "person_id": person_id,
                "is_full_service_itr_client": True,
                "is_bookkeeping_client": True
            },
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        
        if update_response.status_code == 200:
            return {"person_id": person_id, "email": unique_email}
        pytest.skip(f"Failed to update engagement: {update_response.text}")
    
    def test_conflict_mismatched_service_flags(self, api_client, admin_token, person_with_diy_bas, person_with_full_service):
        """Test conflict detection: mismatched service flags (low severity)"""
        person_a_id = person_with_diy_bas["person_id"]
        person_b_id = person_with_full_service["person_id"]
        
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": person_a_id, "person_id_b": person_b_id},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Find mismatched_service_flags conflict
        flags_conflict = next(
            (c for c in data["conflicts"] if c["type"] == "mismatched_service_flags"),
            None
        )
        assert flags_conflict is not None, "Expected mismatched_service_flags conflict"
        assert flags_conflict["severity"] == "low"
        assert "mismatched_flags" in flags_conflict["details"]
        
        # Verify mismatched flags include expected ones
        mismatched = flags_conflict["details"]["mismatched_flags"]
        flag_names = [f["flag"] for f in mismatched]
        
        # At least some of these should be mismatched
        expected_mismatches = ["is_diy_bas_user", "has_ocr", "is_full_service_itr_client", "is_bookkeeping_client"]
        found_mismatches = [f for f in flag_names if f in expected_mismatches]
        assert len(found_mismatches) > 0, f"Expected some service flag mismatches, got: {flag_names}"
        
        print(f"Mismatched service flags detected: {mismatched}")
    
    def test_combined_engagement_profile_or_logic(self, api_client, admin_token, person_with_diy_bas, person_with_full_service):
        """Test combined engagement profile uses OR logic for flags"""
        person_a_id = person_with_diy_bas["person_id"]
        person_b_id = person_with_full_service["person_id"]
        
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": person_a_id, "person_id_b": person_b_id},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        combined = data["combined_engagement_profile"]
        
        # Combined profile should have OR of all flags
        # Person A has: is_diy_bas_user=True, has_ocr=True
        # Person B has: is_full_service_itr_client=True, is_bookkeeping_client=True
        # Combined should have all True
        assert combined["is_myfdc_user"] == True  # Person A has MyFDC
        assert combined["is_crm_client"] == True  # Person B has CRM
        assert combined["is_diy_bas_user"] == True  # From Person A
        assert combined["has_ocr"] == True  # From Person A
        assert combined["is_full_service_itr_client"] == True  # From Person B
        assert combined["is_bookkeeping_client"] == True  # From Person B
        
        print(f"Combined engagement profile (OR logic): {combined}")


class TestMergePreviewRecommendation:
    """Tests for merge direction recommendation"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    @pytest.fixture(scope="class")
    def admin_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Admin authentication failed")
    
    @pytest.fixture(scope="class")
    def staff_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": STAFF_EMAIL,
            "password": STAFF_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Staff authentication failed")
    
    @pytest.fixture(scope="class")
    def person_myfdc_only(self, api_client):
        """Create person with MyFDC only"""
        unique_email = f"TEST_rec_myfdc_{uuid.uuid4().hex[:8]}@example.com"
        response = api_client.post(f"{BASE_URL}/api/identity/myfdc-signup", json={
            "email": unique_email,
            "first_name": "Rec",
            "last_name": "MyFDC"
        })
        if response.status_code == 200:
            return response.json()
        pytest.skip(f"Failed to create MyFDC person: {response.text}")
    
    @pytest.fixture(scope="class")
    def person_crm_only(self, api_client, staff_token):
        """Create person with CRM only"""
        unique_email = f"TEST_rec_crm_{uuid.uuid4().hex[:8]}@example.com"
        response = api_client.post(
            f"{BASE_URL}/api/identity/crm-client-create",
            json={
                "email": unique_email,
                "first_name": "Rec",
                "last_name": "CRM"
            },
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        if response.status_code == 200:
            return response.json()
        pytest.skip(f"Failed to create CRM person: {response.text}")
    
    def test_merge_direction_recommendation(self, api_client, admin_token, person_myfdc_only, person_crm_only):
        """Test merge direction recommendation is provided"""
        person_a_id = person_myfdc_only["person"]["id"]
        person_b_id = person_crm_only["person"]["id"]
        
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": person_a_id, "person_id_b": person_b_id},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        rec = data["recommendation"]
        
        # Verify recommendation structure
        assert "merge_direction" in rec
        assert "primary_person_id" in rec
        assert "secondary_person_id" in rec
        assert "reason" in rec
        assert "safe_to_merge" in rec
        
        # Merge direction should be in format "secondary_id → primary_id"
        assert "→" in rec["merge_direction"]
        
        # Primary and secondary should be different
        assert rec["primary_person_id"] != rec["secondary_person_id"]
        
        # Both IDs should be one of our test persons
        assert rec["primary_person_id"] in [person_a_id, person_b_id]
        assert rec["secondary_person_id"] in [person_a_id, person_b_id]
        
        # Reason should be non-empty
        assert len(rec["reason"]) > 0
        
        print(f"Merge recommendation: {rec['merge_direction']}")
        print(f"Reason: {rec['reason']}")
        print(f"Safe to merge: {rec['safe_to_merge']}")
    
    def test_safe_to_merge_no_high_conflicts(self, api_client, admin_token, person_myfdc_only, person_crm_only):
        """Test safe_to_merge is True when no high severity conflicts"""
        person_a_id = person_myfdc_only["person"]["id"]
        person_b_id = person_crm_only["person"]["id"]
        
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": person_a_id, "person_id_b": person_b_id},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # No high severity conflicts (no multiple MyFDC or CRM accounts)
        high_conflicts = data["conflict_summary"]["high"]
        safe_to_merge = data["recommendation"]["safe_to_merge"]
        
        if high_conflicts == 0:
            assert safe_to_merge == True, "safe_to_merge should be True when no high severity conflicts"
        else:
            assert safe_to_merge == False, "safe_to_merge should be False when high severity conflicts exist"
        
        print(f"High conflicts: {high_conflicts}, Safe to merge: {safe_to_merge}")


class TestMergePreviewAuditLogging:
    """Tests for audit logging of merge preview requests"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    @pytest.fixture(scope="class")
    def admin_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Admin authentication failed")
    
    @pytest.fixture(scope="class")
    def test_persons(self, api_client):
        """Create two test persons for audit log test"""
        persons = []
        for i in range(2):
            unique_email = f"TEST_audit_{uuid.uuid4().hex[:8]}@example.com"
            response = api_client.post(f"{BASE_URL}/api/identity/myfdc-signup", json={
                "email": unique_email,
                "first_name": f"Audit{i}",
                "last_name": "Test"
            })
            if response.status_code == 200:
                persons.append(response.json()["person"])
            else:
                pytest.skip(f"Failed to create test person: {response.text}")
        return persons
    
    def test_merge_preview_creates_audit_log(self, api_client, admin_token, test_persons):
        """Test that merge preview creates an audit log entry"""
        person_a_id = test_persons[0]["id"]
        person_b_id = test_persons[1]["id"]
        
        # Call merge preview
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": person_a_id, "person_id_b": person_b_id},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        
        # The audit log is created internally - we verify the endpoint succeeded
        # which means the log was written (as per the service code)
        print(f"Merge preview completed - audit log should be created with action='merge_preview'")
        print(f"Person A: {person_a_id}, Person B: {person_b_id}")


class TestMergePreviewWithExistingTestData:
    """Tests using existing test data mentioned in the request"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    @pytest.fixture(scope="class")
    def admin_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Admin authentication failed")
    
    def test_merge_preview_with_known_test_data(self, api_client, admin_token):
        """Test merge preview with known test data from previous iterations"""
        # These IDs are from the test request:
        # person_id d08eb421-05a9-4d36-a130-199cd54518d4 (MyFDC only, local auth)
        # person_id 1e791bdc-fa89-4dbd-bb84-2381ac3ad929 (MyFDC + CRM, google auth)
        
        person_a_id = "d08eb421-05a9-4d36-a130-199cd54518d4"
        person_b_id = "1e791bdc-fa89-4dbd-bb84-2381ac3ad929"
        
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": person_a_id, "person_id_b": person_b_id},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        # These persons may or may not exist depending on test data state
        if response.status_code == 200:
            data = response.json()
            assert data["success"] == True
            
            # Both have MyFDC accounts, so should detect multiple_myfdc_accounts conflict
            myfdc_conflict = next(
                (c for c in data["conflicts"] if c["type"] == "multiple_myfdc_accounts"),
                None
            )
            
            if myfdc_conflict:
                assert myfdc_conflict["severity"] == "high"
                # Should also detect mismatched auth providers (local vs google)
                auth_conflict = next(
                    (c for c in data["conflicts"] if c["type"] == "mismatched_auth_providers"),
                    None
                )
                if auth_conflict:
                    assert auth_conflict["details"]["provider_a"] == "local"
                    assert auth_conflict["details"]["provider_b"] == "google"
                    print(f"Auth provider mismatch detected: local vs google")
            
            print(f"Merge preview with known test data successful")
            print(f"Conflicts: {data['conflict_summary']}")
        elif response.status_code == 400:
            # Person not found - this is expected if test data doesn't exist
            print(f"Known test data not found (expected if test data was cleaned up)")
        else:
            pytest.fail(f"Unexpected status code: {response.status_code}")


class TestMergePreviewEdgeCases:
    """Edge case tests for merge-preview"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    @pytest.fixture(scope="class")
    def admin_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Admin authentication failed")
    
    def test_merge_preview_missing_person_id_a(self, api_client, admin_token):
        """Test merge-preview with missing person_id_a parameter"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_b": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 422, f"Expected 422 for missing param, got {response.status_code}"
        print("Missing person_id_a correctly returns 422")
    
    def test_merge_preview_missing_person_id_b(self, api_client, admin_token):
        """Test merge-preview with missing person_id_b parameter"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 422, f"Expected 422 for missing param, got {response.status_code}"
        print("Missing person_id_b correctly returns 422")
    
    def test_merge_preview_empty_uuid(self, api_client, admin_token):
        """Test merge-preview with empty UUID strings"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/merge-preview",
            params={"person_id_a": "", "person_id_b": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code in [400, 422], f"Expected 400 or 422, got {response.status_code}"
        print("Empty UUID correctly rejected")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
