"""
Identity Spine API Tests
Tests for the unified identity model linking MyFDC and CRM platforms.

Endpoints tested:
- GET /api/identity/status - Module status (public)
- POST /api/identity/myfdc-signup - MyFDC signup (public)
- POST /api/identity/crm-client-create - CRM client creation (staff auth)
- GET /api/identity/stats - Identity statistics (admin auth)
- GET /api/identity/orphaned - Orphaned records (admin auth)
- GET /api/identity/duplicates - Duplicate emails (admin auth)
- GET /api/identity/person/by-email - Get person by email (staff auth)
- GET /api/identity/person/{person_id} - Get person by ID (staff auth)
- PUT /api/identity/engagement/{person_id} - Update engagement (staff auth)
- Automatic linking when same email used for MyFDC and CRM
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


class TestIdentitySpineSetup:
    """Setup and authentication tests"""
    
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
    
    def test_api_health(self, api_client):
        """Verify API is healthy"""
        response = api_client.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        print(f"API health: {data['status']}")


class TestIdentityStatus:
    """Tests for GET /api/identity/status - Public endpoint"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    def test_identity_status_returns_ok(self, api_client):
        """Test identity module status endpoint"""
        response = api_client.get(f"{BASE_URL}/api/identity/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "ok"
        assert data["module"] == "identity_spine"
        assert data["version"] == "1.0.0"
        print(f"Identity module status: {data['status']}, version: {data['version']}")
    
    def test_identity_status_features(self, api_client):
        """Test identity module features are enabled"""
        response = api_client.get(f"{BASE_URL}/api/identity/status")
        assert response.status_code == 200
        
        data = response.json()
        features = data.get("features", {})
        assert features.get("myfdc_signup") == True
        assert features.get("crm_client_create") == True
        assert features.get("link_existing") == True
        assert features.get("merge_persons") == True
        assert features.get("orphan_detection") == True
        print(f"All identity features enabled: {features}")


class TestMyFDCSignup:
    """Tests for POST /api/identity/myfdc-signup - Public endpoint"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    def test_myfdc_signup_creates_person_and_account(self, api_client):
        """Test MyFDC signup creates new person and account"""
        unique_email = f"TEST_myfdc_{uuid.uuid4().hex[:8]}@example.com"
        
        response = api_client.post(f"{BASE_URL}/api/identity/myfdc-signup", json={
            "email": unique_email,
            "first_name": "Test",
            "last_name": "MyFDC",
            "mobile": "0400000001",
            "auth_provider": "local",
            "password_hash": "hashed_password_123"
        })
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["success"] == True
        assert data["person_created"] == True
        assert data["account_created"] == True
        
        # Verify person data
        person = data["person"]
        assert person["email"] == unique_email.lower()
        assert person["first_name"] == "Test"
        assert person["last_name"] == "MyFDC"
        assert "id" in person
        
        # Verify MyFDC account data
        myfdc_account = data["myfdc_account"]
        assert myfdc_account["person_id"] == person["id"]
        assert myfdc_account["auth_provider"] == "local"
        assert myfdc_account["status"] == "active"
        
        # Verify engagement profile
        engagement = data["engagement_profile"]
        assert engagement["is_myfdc_user"] == True
        
        print(f"MyFDC signup successful: person_id={person['id']}, email={unique_email}")
    
    def test_myfdc_signup_duplicate_email_fails(self, api_client):
        """Test MyFDC signup with existing email fails"""
        unique_email = f"TEST_myfdc_dup_{uuid.uuid4().hex[:8]}@example.com"
        
        # First signup
        response1 = api_client.post(f"{BASE_URL}/api/identity/myfdc-signup", json={
            "email": unique_email,
            "first_name": "First",
            "last_name": "User"
        })
        assert response1.status_code == 200
        
        # Second signup with same email should fail
        response2 = api_client.post(f"{BASE_URL}/api/identity/myfdc-signup", json={
            "email": unique_email,
            "first_name": "Second",
            "last_name": "User"
        })
        
        assert response2.status_code == 409, f"Expected 409 conflict, got {response2.status_code}"
        data = response2.json()
        assert "already exists" in data.get("detail", "").lower()
        print(f"Duplicate email correctly rejected: {unique_email}")
    
    def test_myfdc_signup_invalid_email_fails(self, api_client):
        """Test MyFDC signup with invalid email fails"""
        response = api_client.post(f"{BASE_URL}/api/identity/myfdc-signup", json={
            "email": "not-an-email",
            "first_name": "Test"
        })
        
        assert response.status_code == 422, f"Expected 422 validation error, got {response.status_code}"
        print("Invalid email correctly rejected")
    
    def test_myfdc_signup_google_auth_provider(self, api_client):
        """Test MyFDC signup with Google auth provider"""
        unique_email = f"TEST_myfdc_google_{uuid.uuid4().hex[:8]}@example.com"
        
        response = api_client.post(f"{BASE_URL}/api/identity/myfdc-signup", json={
            "email": unique_email,
            "first_name": "Google",
            "last_name": "User",
            "auth_provider": "google",
            "auth_provider_id": "google_123456"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["myfdc_account"]["auth_provider"] == "google"
        print(f"Google auth signup successful: {unique_email}")


class TestCRMClientCreate:
    """Tests for POST /api/identity/crm-client-create - Requires staff auth"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
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
    def admin_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Admin authentication failed")
    
    def test_crm_client_create_requires_auth(self, api_client):
        """Test CRM client creation requires authentication"""
        response = api_client.post(f"{BASE_URL}/api/identity/crm-client-create", json={
            "email": "test@example.com"
        })
        assert response.status_code == 401
        print("CRM client create correctly requires authentication")
    
    def test_crm_client_create_with_staff_auth(self, api_client, staff_token):
        """Test CRM client creation with staff authentication"""
        unique_email = f"TEST_crm_{uuid.uuid4().hex[:8]}@example.com"
        
        response = api_client.post(
            f"{BASE_URL}/api/identity/crm-client-create",
            json={
                "email": unique_email,
                "first_name": "CRM",
                "last_name": "Client",
                "mobile": "0400000002",
                "business_name": "Test Business Pty Ltd",
                "abn": "12345678901",
                "entity_type": "company",
                "gst_registered": True,
                "source": "referral",
                "notes": "Test client created by pytest",
                "tags": ["test", "pytest"]
            },
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["success"] == True
        assert data["person_created"] == True
        assert data["client_created"] == True
        
        # Verify person data
        person = data["person"]
        assert person["email"] == unique_email.lower()
        
        # Verify CRM client data
        crm_client = data["crm_client"]
        assert crm_client["person_id"] == person["id"]
        assert crm_client["business_name"] == "Test Business Pty Ltd"
        assert crm_client["abn"] == "12345678901"
        assert crm_client["entity_type"] == "company"
        assert crm_client["gst_registered"] == True
        assert crm_client["status"] == "active"
        
        # Verify client code was auto-generated
        assert crm_client["client_code"] is not None
        assert crm_client["client_code"].startswith("CLIENT-")
        
        # Verify engagement profile
        engagement = data["engagement_profile"]
        assert engagement["is_crm_client"] == True
        
        print(f"CRM client created: client_code={crm_client['client_code']}, email={unique_email}")
    
    def test_crm_client_create_with_custom_client_code(self, api_client, staff_token):
        """Test CRM client creation with custom client code"""
        unique_email = f"TEST_crm_custom_{uuid.uuid4().hex[:8]}@example.com"
        custom_code = f"CUSTOM-{uuid.uuid4().hex[:6].upper()}"
        
        response = api_client.post(
            f"{BASE_URL}/api/identity/crm-client-create",
            json={
                "email": unique_email,
                "first_name": "Custom",
                "last_name": "Code",
                "client_code": custom_code
            },
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["crm_client"]["client_code"] == custom_code
        print(f"Custom client code accepted: {custom_code}")
    
    def test_crm_client_duplicate_email_fails(self, api_client, staff_token):
        """Test CRM client creation with existing email fails"""
        unique_email = f"TEST_crm_dup_{uuid.uuid4().hex[:8]}@example.com"
        
        # First creation
        response1 = api_client.post(
            f"{BASE_URL}/api/identity/crm-client-create",
            json={"email": unique_email, "first_name": "First"},
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        assert response1.status_code == 200
        
        # Second creation with same email should fail
        response2 = api_client.post(
            f"{BASE_URL}/api/identity/crm-client-create",
            json={"email": unique_email, "first_name": "Second"},
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        
        assert response2.status_code == 409
        print(f"Duplicate CRM client correctly rejected: {unique_email}")


class TestAutomaticLinking:
    """Tests for automatic linking when same email is used for MyFDC and CRM"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    @pytest.fixture(scope="class")
    def staff_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": STAFF_EMAIL,
            "password": STAFF_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Staff authentication failed")
    
    def test_myfdc_signup_links_to_existing_crm_client(self, api_client, staff_token):
        """Test MyFDC signup links to existing CRM client with same email"""
        unique_email = f"TEST_link_crm_first_{uuid.uuid4().hex[:8]}@example.com"
        
        # First create CRM client
        crm_response = api_client.post(
            f"{BASE_URL}/api/identity/crm-client-create",
            json={
                "email": unique_email,
                "first_name": "CRM",
                "last_name": "First",
                "business_name": "Link Test Business"
            },
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        assert crm_response.status_code == 200
        crm_data = crm_response.json()
        crm_person_id = crm_data["person"]["id"]
        
        # Now signup with MyFDC using same email
        myfdc_response = api_client.post(f"{BASE_URL}/api/identity/myfdc-signup", json={
            "email": unique_email,
            "first_name": "MyFDC",
            "last_name": "Second"
        })
        
        assert myfdc_response.status_code == 200
        myfdc_data = myfdc_response.json()
        
        # Should link to existing person, not create new
        assert myfdc_data["person_created"] == False
        assert myfdc_data["account_created"] == True
        assert myfdc_data["person"]["id"] == crm_person_id
        assert myfdc_data["linked_to_crm"] == True
        
        print(f"MyFDC signup linked to existing CRM client: person_id={crm_person_id}")
    
    def test_crm_client_links_to_existing_myfdc_user(self, api_client, staff_token):
        """Test CRM client creation links to existing MyFDC user with same email"""
        unique_email = f"TEST_link_myfdc_first_{uuid.uuid4().hex[:8]}@example.com"
        
        # First create MyFDC user
        myfdc_response = api_client.post(f"{BASE_URL}/api/identity/myfdc-signup", json={
            "email": unique_email,
            "first_name": "MyFDC",
            "last_name": "First"
        })
        assert myfdc_response.status_code == 200
        myfdc_data = myfdc_response.json()
        myfdc_person_id = myfdc_data["person"]["id"]
        
        # Now create CRM client with same email
        crm_response = api_client.post(
            f"{BASE_URL}/api/identity/crm-client-create",
            json={
                "email": unique_email,
                "first_name": "CRM",
                "last_name": "Second",
                "business_name": "Link Test Business 2"
            },
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        
        assert crm_response.status_code == 200
        crm_data = crm_response.json()
        
        # Should link to existing person, not create new
        assert crm_data["person_created"] == False
        assert crm_data["client_created"] == True
        assert crm_data["person"]["id"] == myfdc_person_id
        assert crm_data["linked_to_myfdc"] == True
        
        print(f"CRM client linked to existing MyFDC user: person_id={myfdc_person_id}")


class TestPersonLookup:
    """Tests for person lookup endpoints"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
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
    def test_person(self, api_client):
        """Create a test person for lookup tests"""
        unique_email = f"TEST_lookup_{uuid.uuid4().hex[:8]}@example.com"
        response = api_client.post(f"{BASE_URL}/api/identity/myfdc-signup", json={
            "email": unique_email,
            "first_name": "Lookup",
            "last_name": "Test"
        })
        if response.status_code == 200:
            return response.json()["person"]
        pytest.skip("Failed to create test person")
    
    def test_get_person_by_email_requires_auth(self, api_client, test_person):
        """Test person lookup by email requires authentication"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/person/by-email",
            params={"email": test_person["email"]}
        )
        assert response.status_code == 401
        print("Person lookup correctly requires authentication")
    
    def test_get_person_by_email(self, api_client, staff_token, test_person):
        """Test person lookup by email"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/person/by-email",
            params={"email": test_person["email"]},
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_person["id"]
        assert data["email"] == test_person["email"]
        assert "myfdc_account" in data
        assert data["myfdc_account"] is not None
        print(f"Person found by email: {test_person['email']}")
    
    def test_get_person_by_email_not_found(self, api_client, staff_token):
        """Test person lookup by email returns 404 for non-existent email"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/person/by-email",
            params={"email": "nonexistent@example.com"},
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        assert response.status_code == 404
        print("Non-existent email correctly returns 404")
    
    def test_get_person_by_id(self, api_client, staff_token, test_person):
        """Test person lookup by ID"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/person/{test_person['id']}",
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_person["id"]
        assert data["email"] == test_person["email"]
        print(f"Person found by ID: {test_person['id']}")
    
    def test_get_person_by_id_invalid_uuid(self, api_client, staff_token):
        """Test person lookup with invalid UUID returns 400"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/person/not-a-uuid",
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        assert response.status_code == 400
        print("Invalid UUID correctly returns 400")
    
    def test_get_person_by_id_not_found(self, api_client, staff_token):
        """Test person lookup by ID returns 404 for non-existent ID"""
        fake_uuid = str(uuid.uuid4())
        response = api_client.get(
            f"{BASE_URL}/api/identity/person/{fake_uuid}",
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        assert response.status_code == 404
        print("Non-existent ID correctly returns 404")


class TestEngagementProfile:
    """Tests for PUT /api/identity/engagement/{person_id}"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
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
    def test_person(self, api_client):
        """Create a test person for engagement tests"""
        unique_email = f"TEST_engagement_{uuid.uuid4().hex[:8]}@example.com"
        response = api_client.post(f"{BASE_URL}/api/identity/myfdc-signup", json={
            "email": unique_email,
            "first_name": "Engagement",
            "last_name": "Test"
        })
        if response.status_code == 200:
            return response.json()["person"]
        pytest.skip("Failed to create test person")
    
    def test_update_engagement_profile(self, api_client, staff_token, test_person):
        """Test updating engagement profile flags"""
        response = api_client.put(
            f"{BASE_URL}/api/identity/engagement/{test_person['id']}",
            json={
                "person_id": test_person["id"],
                "is_diy_bas_user": True,
                "has_ocr": True,
                "subscription_tier": "pro"
            },
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["is_diy_bas_user"] == True
        assert data["has_ocr"] == True
        assert data["subscription_tier"] == "pro"
        print(f"Engagement profile updated for person: {test_person['id']}")
    
    def test_update_engagement_profile_invalid_uuid(self, api_client, staff_token):
        """Test updating engagement with invalid UUID returns 400"""
        response = api_client.put(
            f"{BASE_URL}/api/identity/engagement/not-a-uuid",
            json={"person_id": "not-a-uuid", "is_diy_bas_user": True},
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        assert response.status_code == 400
        print("Invalid UUID correctly returns 400")


class TestAdminEndpoints:
    """Tests for admin-only endpoints"""
    
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
    
    def test_get_stats_requires_admin(self, api_client, staff_token):
        """Test stats endpoint requires admin role"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/stats",
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        assert response.status_code == 403
        print("Stats endpoint correctly requires admin role")
    
    def test_get_stats_with_admin(self, api_client, admin_token):
        """Test stats endpoint with admin authentication"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/stats",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "total_persons" in data
        assert "active_persons" in data
        assert "myfdc_accounts" in data
        assert "crm_clients" in data
        assert "linked_both" in data
        assert "engagement" in data
        print(f"Stats: {data['total_persons']} persons, {data['myfdc_accounts']} MyFDC, {data['crm_clients']} CRM")
    
    def test_get_orphaned_requires_admin(self, api_client, staff_token):
        """Test orphaned endpoint requires admin role"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/orphaned",
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        assert response.status_code == 403
        print("Orphaned endpoint correctly requires admin role")
    
    def test_get_orphaned_with_admin(self, api_client, admin_token):
        """Test orphaned endpoint with admin authentication"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/orphaned",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "orphaned_myfdc_accounts" in data
        assert "orphaned_crm_clients" in data
        assert "unlinked_persons" in data
        assert "counts" in data
        print(f"Orphaned records: {data['counts']}")
    
    def test_get_duplicates_requires_admin(self, api_client, staff_token):
        """Test duplicates endpoint requires admin role"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/duplicates",
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        assert response.status_code == 403
        print("Duplicates endpoint correctly requires admin role")
    
    def test_get_duplicates_with_admin(self, api_client, admin_token):
        """Test duplicates endpoint with admin authentication"""
        response = api_client.get(
            f"{BASE_URL}/api/identity/duplicates",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "duplicates" in data
        assert "count" in data
        print(f"Duplicate emails found: {data['count']}")


class TestClientCodeGeneration:
    """Tests for automatic client code generation"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    @pytest.fixture(scope="class")
    def staff_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": STAFF_EMAIL,
            "password": STAFF_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Staff authentication failed")
    
    def test_client_code_auto_generated(self, api_client, staff_token):
        """Test client code is auto-generated when not provided"""
        unique_email = f"TEST_autocode_{uuid.uuid4().hex[:8]}@example.com"
        
        response = api_client.post(
            f"{BASE_URL}/api/identity/crm-client-create",
            json={"email": unique_email, "first_name": "Auto", "last_name": "Code"},
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        client_code = data["crm_client"]["client_code"]
        
        assert client_code is not None
        assert client_code.startswith("CLIENT-")
        # Should be in format CLIENT-XXXXXX (6 digits)
        assert len(client_code) == 13  # "CLIENT-" (7) + 6 digits
        print(f"Auto-generated client code: {client_code}")
    
    def test_client_codes_are_sequential(self, api_client, staff_token):
        """Test client codes are generated sequentially"""
        codes = []
        
        for i in range(2):
            unique_email = f"TEST_seq_{uuid.uuid4().hex[:8]}@example.com"
            response = api_client.post(
                f"{BASE_URL}/api/identity/crm-client-create",
                json={"email": unique_email, "first_name": f"Seq{i}", "last_name": "Test"},
                headers={"Authorization": f"Bearer {staff_token}"}
            )
            assert response.status_code == 200
            codes.append(response.json()["crm_client"]["client_code"])
        
        # Extract numbers and verify they're sequential
        nums = [int(code.split("-")[1]) for code in codes]
        assert nums[1] == nums[0] + 1, f"Codes not sequential: {codes}"
        print(f"Sequential client codes verified: {codes}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
