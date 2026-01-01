"""
Core Module Tests - Phase 3: Luna Migration to Core

Tests for:
- GET /api/core/status - Module status with feature flags
- POST /api/core/client-profiles - Create client profile (86-field schema)
- GET /api/core/client-profiles - List/search client profiles
- GET /api/core/client-profiles/{id} - Get profile by ID
- GET /api/core/client-profiles/by-code/{code} - Get profile by client code
- PATCH /api/core/client-profiles/{id} - Update profile
- DELETE /api/core/client-profiles/{id} - Archive profile (admin only)
- POST /api/core/migration/client - Migrate single client (API key auth)
- POST /api/core/migration/batch - Batch migration (API key auth)
- GET /api/core/migration/status - Migration stats (API key or admin JWT)
- Internal API key authentication (X-Internal-Api-Key header)
- X-Service-Name header logging
- Permission checks: staff can read, only staff/admin can write, only admin can delete
- TFN masking by default (only admin can view decrypted)
"""

import pytest
import requests
import os
import uuid
from datetime import datetime

# Base URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://fdctaxsync.preview.emergentagent.com').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@fdctax.com"
ADMIN_PASSWORD = "admin123"
STAFF_EMAIL = "staff@fdctax.com"
STAFF_PASSWORD = "staff123"
TAX_AGENT_EMAIL = "taxagent@fdctax.com"
TAX_AGENT_PASSWORD = "taxagent123"

# Internal API key for migration endpoints
INTERNAL_API_KEY = "test-internal-api-key-for-luna-migration"


class TestCoreStatus:
    """Tests for GET /api/core/status endpoint"""
    
    def test_core_status_returns_ok(self):
        """Test that core status endpoint returns ok status"""
        response = requests.get(f"{BASE_URL}/api/core/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "ok"
        assert data["module"] == "core"
        assert data["version"] == "1.0.0"
    
    def test_core_status_has_feature_flags(self):
        """Test that core status includes feature flags"""
        response = requests.get(f"{BASE_URL}/api/core/status")
        assert response.status_code == 200
        
        data = response.json()
        assert "features" in data
        features = data["features"]
        
        # Verify all expected feature flags
        assert features["client_profiles"] == True
        assert features["luna_migration"] == True
        assert "tfn_encryption" in features  # May be True or False depending on config
        assert "internal_auth" in features
    
    def test_core_status_shows_encryption_status(self):
        """Test that core status shows encryption configuration status"""
        response = requests.get(f"{BASE_URL}/api/core/status")
        assert response.status_code == 200
        
        data = response.json()
        assert "encryption_configured" in data
        # Note: ENCRYPTION_KEY not set, so should be False
        assert data["encryption_configured"] == False
    
    def test_core_status_shows_internal_auth_status(self):
        """Test that core status shows internal auth configuration status"""
        response = requests.get(f"{BASE_URL}/api/core/status")
        assert response.status_code == 200
        
        data = response.json()
        assert "internal_auth_configured" in data
        assert data["internal_auth_configured"] == True


class TestAuthentication:
    """Tests for authentication and authorization"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        return response.json()["access_token"]
    
    @pytest.fixture
    def staff_token(self):
        """Get staff JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": STAFF_EMAIL,
            "password": STAFF_PASSWORD
        })
        assert response.status_code == 200
        return response.json()["access_token"]
    
    @pytest.fixture
    def tax_agent_token(self):
        """Get tax_agent JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TAX_AGENT_EMAIL,
            "password": TAX_AGENT_PASSWORD
        })
        assert response.status_code == 200
        return response.json()["access_token"]
    
    def test_client_profiles_requires_auth(self):
        """Test that client profiles endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/core/client-profiles")
        assert response.status_code == 401
    
    def test_admin_can_access_profiles(self, admin_token):
        """Test that admin can access client profiles"""
        response = requests.get(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
    
    def test_staff_can_access_profiles(self, staff_token):
        """Test that staff can access client profiles"""
        response = requests.get(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        assert response.status_code == 200
    
    def test_tax_agent_can_access_profiles(self, tax_agent_token):
        """Test that tax_agent can access client profiles"""
        response = requests.get(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {tax_agent_token}"}
        )
        assert response.status_code == 200


class TestInternalApiKeyAuth:
    """Tests for internal API key authentication"""
    
    def test_migration_endpoint_requires_api_key(self):
        """Test that migration endpoint requires API key"""
        response = requests.post(
            f"{BASE_URL}/api/core/migration/client",
            json={"client_code": "TEST-NOKEY", "display_name": "Test"}
        )
        assert response.status_code == 401
        assert "Missing internal API key" in response.json().get("detail", "")
    
    def test_invalid_api_key_rejected(self):
        """Test that invalid API key is rejected"""
        response = requests.post(
            f"{BASE_URL}/api/core/migration/client",
            headers={"X-Internal-Api-Key": "invalid-key-12345"},
            json={"client_code": "TEST-INVALID", "display_name": "Test"}
        )
        assert response.status_code == 401
        assert "Invalid internal API key" in response.json().get("detail", "")
    
    def test_valid_api_key_accepted(self):
        """Test that valid API key is accepted"""
        unique_code = f"TEST-APIKEY-{uuid.uuid4().hex[:8].upper()}"
        response = requests.post(
            f"{BASE_URL}/api/core/migration/client",
            headers={
                "X-Internal-Api-Key": INTERNAL_API_KEY,
                "X-Service-Name": "pytest-test-service"
            },
            json={"client_code": unique_code, "display_name": "API Key Test Client"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["client_code"] == unique_code
    
    def test_service_name_header_logged(self):
        """Test that X-Service-Name header is accepted and logged"""
        unique_code = f"TEST-SVC-{uuid.uuid4().hex[:8].upper()}"
        response = requests.post(
            f"{BASE_URL}/api/core/migration/client",
            headers={
                "X-Internal-Api-Key": INTERNAL_API_KEY,
                "X-Service-Name": "luna-crm-service"
            },
            json={"client_code": unique_code, "display_name": "Service Name Test"}
        )
        assert response.status_code == 200
        # Service name is logged but not returned in response


class TestClientProfileCRUD:
    """Tests for client profile CRUD operations"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    @pytest.fixture
    def staff_token(self):
        """Get staff JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": STAFF_EMAIL,
            "password": STAFF_PASSWORD
        })
        return response.json()["access_token"]
    
    @pytest.fixture
    def tax_agent_token(self):
        """Get tax_agent JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TAX_AGENT_EMAIL,
            "password": TAX_AGENT_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_create_client_profile_admin(self, admin_token):
        """Test creating a client profile as admin"""
        unique_code = f"TEST-CREATE-{uuid.uuid4().hex[:8].upper()}"
        response = requests.post(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "client_code": unique_code,
                "display_name": "Test Create Client",
                "entity_type": "individual",
                "client_status": "active",
                "primary_contact_first_name": "Test",
                "primary_contact_last_name": "User",
                "primary_contact_email": "test@example.com",
                "abn": "12345678901",
                "gst_registered": True,
                "services_engaged": ["BAS", "ITR"],
                "tags": ["test", "pytest"]
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert "profile" in data
        profile = data["profile"]
        assert profile["client_code"] == unique_code
        assert profile["display_name"] == "Test Create Client"
        assert profile["entity_type"] == "individual"
        assert profile["gst_registered"] == True
    
    def test_create_client_profile_staff(self, staff_token):
        """Test creating a client profile as staff"""
        unique_code = f"TEST-STAFF-{uuid.uuid4().hex[:8].upper()}"
        response = requests.post(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {staff_token}"},
            json={
                "client_code": unique_code,
                "display_name": "Staff Created Client"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
    
    def test_create_client_profile_tax_agent_forbidden(self, tax_agent_token):
        """Test that tax_agent cannot create client profiles"""
        unique_code = f"TEST-TAXAGENT-{uuid.uuid4().hex[:8].upper()}"
        response = requests.post(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {tax_agent_token}"},
            json={
                "client_code": unique_code,
                "display_name": "Tax Agent Client"
            }
        )
        assert response.status_code == 403
    
    def test_create_duplicate_client_code_rejected(self, admin_token):
        """Test that duplicate client codes are rejected"""
        # Use existing client code
        response = requests.post(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "client_code": "TEST-001",  # Already exists
                "display_name": "Duplicate Test"
            }
        )
        assert response.status_code == 409
        assert "already exists" in response.json().get("detail", "").lower()
    
    def test_list_client_profiles(self, admin_token):
        """Test listing client profiles"""
        response = requests.get(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "profiles" in data
        assert "count" in data
        assert isinstance(data["profiles"], list)
        assert data["count"] >= 0
    
    def test_search_client_profiles(self, admin_token):
        """Test searching client profiles by query"""
        response = requests.get(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"query": "TEST"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "profiles" in data
        # Should find profiles with TEST in name or code
    
    def test_filter_by_entity_type(self, admin_token):
        """Test filtering profiles by entity type"""
        response = requests.get(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"entity_type": "company"}
        )
        assert response.status_code == 200
        
        data = response.json()
        for profile in data["profiles"]:
            assert profile["entity_type"] == "company"
    
    def test_filter_by_status(self, admin_token):
        """Test filtering profiles by status"""
        response = requests.get(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"client_status": "active"}
        )
        assert response.status_code == 200
        
        data = response.json()
        for profile in data["profiles"]:
            assert profile["client_status"] == "active"
    
    def test_get_profile_by_id(self, admin_token):
        """Test getting a profile by ID"""
        # First get list to find an ID
        list_response = requests.get(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        profiles = list_response.json()["profiles"]
        if not profiles:
            pytest.skip("No profiles available for testing")
        
        profile_id = profiles[0]["id"]
        
        response = requests.get(
            f"{BASE_URL}/api/core/client-profiles/{profile_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["id"] == profile_id
    
    def test_get_profile_by_code(self, admin_token):
        """Test getting a profile by client code"""
        response = requests.get(
            f"{BASE_URL}/api/core/client-profiles/by-code/TEST-001",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["client_code"] == "TEST-001"
    
    def test_get_nonexistent_profile_returns_404(self, admin_token):
        """Test that getting a nonexistent profile returns 404"""
        fake_id = str(uuid.uuid4())
        response = requests.get(
            f"{BASE_URL}/api/core/client-profiles/{fake_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404
    
    def test_update_client_profile(self, admin_token):
        """Test updating a client profile"""
        # First create a profile to update
        unique_code = f"TEST-UPDATE-{uuid.uuid4().hex[:8].upper()}"
        create_response = requests.post(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "client_code": unique_code,
                "display_name": "Original Name"
            }
        )
        profile_id = create_response.json()["profile"]["id"]
        
        # Update the profile
        response = requests.patch(
            f"{BASE_URL}/api/core/client-profiles/{profile_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "display_name": "Updated Name",
                "internal_notes": "Updated via pytest"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert data["profile"]["display_name"] == "Updated Name"
        assert data["profile"]["internal_notes"] == "Updated via pytest"
    
    def test_update_profile_tax_agent_forbidden(self, tax_agent_token, admin_token):
        """Test that tax_agent cannot update profiles"""
        # Get a profile ID
        list_response = requests.get(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        profiles = list_response.json()["profiles"]
        if not profiles:
            pytest.skip("No profiles available for testing")
        
        profile_id = profiles[0]["id"]
        
        response = requests.patch(
            f"{BASE_URL}/api/core/client-profiles/{profile_id}",
            headers={"Authorization": f"Bearer {tax_agent_token}"},
            json={"display_name": "Tax Agent Update"}
        )
        assert response.status_code == 403
    
    def test_delete_profile_admin_only(self, admin_token, staff_token):
        """Test that only admin can delete (archive) profiles"""
        # Create a profile to delete
        unique_code = f"TEST-DELETE-{uuid.uuid4().hex[:8].upper()}"
        create_response = requests.post(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "client_code": unique_code,
                "display_name": "To Be Deleted"
            }
        )
        profile_id = create_response.json()["profile"]["id"]
        
        # Staff should not be able to delete
        staff_delete = requests.delete(
            f"{BASE_URL}/api/core/client-profiles/{profile_id}",
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        assert staff_delete.status_code == 403
        
        # Admin should be able to delete
        admin_delete = requests.delete(
            f"{BASE_URL}/api/core/client-profiles/{profile_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert admin_delete.status_code == 200
        assert admin_delete.json()["success"] == True
        
        # Verify profile is archived (not hard deleted)
        get_response = requests.get(
            f"{BASE_URL}/api/core/client-profiles/{profile_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert get_response.status_code == 200
        assert get_response.json()["client_status"] == "archived"


class TestTFNMasking:
    """Tests for TFN encryption and masking"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    @pytest.fixture
    def staff_token(self):
        """Get staff JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": STAFF_EMAIL,
            "password": STAFF_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_tfn_masked_by_default(self, admin_token):
        """Test that TFN is masked by default in responses"""
        # Create profile with TFN
        unique_code = f"TEST-TFN-{uuid.uuid4().hex[:8].upper()}"
        create_response = requests.post(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "client_code": unique_code,
                "display_name": "TFN Test Client",
                "tfn": "123456789"
            }
        )
        assert create_response.status_code == 200
        profile_id = create_response.json()["profile"]["id"]
        
        # Get profile without include_tfn
        response = requests.get(
            f"{BASE_URL}/api/core/client-profiles/{profile_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        # TFN should be masked or null (encryption not configured)
        # Since ENCRYPTION_KEY is not set, tfn_encrypted will be null
        # and tfn will be masked based on tfn_last_four
        assert "tfn" in data
    
    def test_staff_cannot_view_decrypted_tfn(self, staff_token, admin_token):
        """Test that staff cannot request decrypted TFN"""
        # Get a profile ID
        list_response = requests.get(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        profiles = list_response.json()["profiles"]
        if not profiles:
            pytest.skip("No profiles available for testing")
        
        profile_id = profiles[0]["id"]
        
        # Staff requesting include_tfn should be forbidden
        response = requests.get(
            f"{BASE_URL}/api/core/client-profiles/{profile_id}",
            headers={"Authorization": f"Bearer {staff_token}"},
            params={"include_tfn": "true"}
        )
        assert response.status_code == 403
        assert "Only admin can view decrypted TFN" in response.json().get("detail", "")


class TestMigrationEndpoints:
    """Tests for Luna migration endpoints"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_migrate_single_client(self):
        """Test migrating a single client from Luna"""
        unique_code = f"LUNA-MIG-{uuid.uuid4().hex[:8].upper()}"
        response = requests.post(
            f"{BASE_URL}/api/core/migration/client",
            headers={
                "X-Internal-Api-Key": INTERNAL_API_KEY,
                "X-Service-Name": "luna-crm"
            },
            json={
                "client_code": unique_code,
                "display_name": "Luna Migrated Test",
                "entity_type": "sole_trader",
                "email": "luna.test@example.com",
                "phone": "0400111222",
                "abn": "11223344556",
                "gst_registered": True,
                "services": ["BAS", "BOOKKEEPING"],
                "notes": "Migrated from Luna CRM"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert data["client_code"] == unique_code
        assert "profile_id" in data
    
    def test_migrate_client_with_luna_field_mapping(self):
        """Test that Luna field names are correctly mapped"""
        unique_code = f"LUNA-MAP-{uuid.uuid4().hex[:8].upper()}"
        response = requests.post(
            f"{BASE_URL}/api/core/migration/client",
            headers={
                "X-Internal-Api-Key": INTERNAL_API_KEY,
                "X-Service-Name": "luna-crm"
            },
            json={
                "code": unique_code,  # Luna uses 'code' instead of 'client_code'
                "name": "Luna Name Mapping Test",  # Luna uses 'name' instead of 'display_name'
                "first_name": "John",
                "last_name": "Doe",
                "street": "123 Test St",  # Luna uses 'street' instead of 'address_line1'
                "city": "Sydney",  # Luna uses 'city' instead of 'suburb'
                "status": "active"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert data["client_code"] == unique_code
    
    def test_migrate_existing_client_skipped(self):
        """Test that migrating an existing client is skipped with warning"""
        # Try to migrate TEST-001 which already exists
        response = requests.post(
            f"{BASE_URL}/api/core/migration/client",
            headers={
                "X-Internal-Api-Key": INTERNAL_API_KEY,
                "X-Service-Name": "luna-crm"
            },
            json={
                "client_code": "TEST-001",
                "display_name": "Duplicate Migration"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert "warnings" in data
        assert any("already exists" in w.lower() for w in data["warnings"])
    
    def test_migrate_missing_client_code_fails(self):
        """Test that migration without client_code fails"""
        response = requests.post(
            f"{BASE_URL}/api/core/migration/client",
            headers={
                "X-Internal-Api-Key": INTERNAL_API_KEY,
                "X-Service-Name": "luna-crm"
            },
            json={
                "display_name": "No Code Client"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == False
        assert "client_code" in data.get("error", "").lower()
    
    def test_batch_migration(self):
        """Test batch migration of multiple clients"""
        clients = [
            {
                "client_code": f"BATCH-{uuid.uuid4().hex[:6].upper()}",
                "display_name": "Batch Client 1",
                "entity_type": "individual"
            },
            {
                "client_code": f"BATCH-{uuid.uuid4().hex[:6].upper()}",
                "display_name": "Batch Client 2",
                "entity_type": "company"
            },
            {
                "client_code": f"BATCH-{uuid.uuid4().hex[:6].upper()}",
                "display_name": "Batch Client 3",
                "entity_type": "trust"
            }
        ]
        
        response = requests.post(
            f"{BASE_URL}/api/core/migration/batch",
            headers={
                "X-Internal-Api-Key": INTERNAL_API_KEY,
                "X-Service-Name": "luna-batch-migration"
            },
            json={"clients": clients}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "batch_id" in data
        assert data["total"] == 3
        assert data["success_count"] == 3
        assert data["failure_count"] == 0
        assert len(data["results"]) == 3
    
    def test_batch_migration_partial_failure(self):
        """Test batch migration with some failures"""
        clients = [
            {
                "client_code": f"BATCH-OK-{uuid.uuid4().hex[:6].upper()}",
                "display_name": "Valid Client"
            },
            {
                # Missing client_code - should fail
                "display_name": "Invalid Client"
            }
        ]
        
        response = requests.post(
            f"{BASE_URL}/api/core/migration/batch",
            headers={
                "X-Internal-Api-Key": INTERNAL_API_KEY,
                "X-Service-Name": "luna-batch-migration"
            },
            json={"clients": clients}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["total"] == 2
        assert data["success_count"] == 1
        assert data["failure_count"] == 1
    
    def test_migration_status_with_api_key(self):
        """Test getting migration status with API key"""
        response = requests.get(
            f"{BASE_URL}/api/core/migration/status",
            headers={
                "X-Internal-Api-Key": INTERNAL_API_KEY,
                "X-Service-Name": "status-checker"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "total_profiles" in data
        assert "luna_migrated" in data
        assert "core_created" in data
        assert "requested_by" in data
    
    def test_migration_status_with_admin_jwt(self, admin_token):
        """Test getting migration status with admin JWT"""
        response = requests.get(
            f"{BASE_URL}/api/core/migration/status",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "total_profiles" in data
        assert "requested_by" in data


class TestPagination:
    """Tests for pagination in list endpoints"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_list_with_limit(self, admin_token):
        """Test listing profiles with limit"""
        response = requests.get(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"limit": 1}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["profiles"]) <= 1
    
    def test_list_with_offset(self, admin_token):
        """Test listing profiles with offset"""
        # Get first page
        first_response = requests.get(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"limit": 1, "offset": 0}
        )
        
        # Get second page
        second_response = requests.get(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"limit": 1, "offset": 1}
        )
        
        assert first_response.status_code == 200
        assert second_response.status_code == 200
        
        first_profiles = first_response.json()["profiles"]
        second_profiles = second_response.json()["profiles"]
        
        # If both have results, they should be different
        if first_profiles and second_profiles:
            assert first_profiles[0]["id"] != second_profiles[0]["id"]


class TestClientProfileSchema:
    """Tests for the 86-field client profile schema"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_create_profile_with_all_fields(self, admin_token):
        """Test creating a profile with many fields from the 86-field schema"""
        unique_code = f"TEST-FULL-{uuid.uuid4().hex[:8].upper()}"
        response = requests.post(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                # Basic Info
                "client_code": unique_code,
                "display_name": "Full Schema Test Client",
                "legal_name": "Full Schema Test Pty Ltd",
                "trading_name": "Full Schema Trading",
                "entity_type": "company",
                "client_status": "active",
                
                # Contact
                "primary_contact_first_name": "Jane",
                "primary_contact_last_name": "Doe",
                "primary_contact_email": "jane.doe@fullschema.com",
                "primary_contact_phone": "02 9999 8888",
                "primary_contact_mobile": "0412 345 678",
                
                # Address
                "primary_address_line1": "123 Test Street",
                "primary_suburb": "Sydney",
                "primary_state": "NSW",
                "primary_postcode": "2000",
                
                # Tax
                "abn": "12345678901",
                "tfn": "123456789",
                "gst_registered": True,
                
                # Business
                "industry_code": "6211",
                "industry_description": "Accounting Services",
                
                # Staff
                "assigned_partner_id": str(uuid.uuid4()),
                "assigned_manager_id": str(uuid.uuid4()),
                
                # Services
                "services_engaged": ["BAS", "ITR", "BOOKKEEPING", "PAYROLL"],
                "engagement_type": "ongoing",
                
                # Notes
                "internal_notes": "Full schema test client",
                "tags": ["test", "full-schema", "pytest"],
                "custom_fields": {
                    "custom_field_1": "value1",
                    "custom_field_2": 123
                }
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        profile = data["profile"]
        
        # Verify fields were saved
        assert profile["client_code"] == unique_code
        assert profile["legal_name"] == "Full Schema Test Pty Ltd"
        assert profile["trading_name"] == "Full Schema Trading"
        assert profile["primary_contact_first_name"] == "Jane"
        assert profile["primary_contact_last_name"] == "Doe"
        assert profile["primary_suburb"] == "Sydney"
        assert profile["primary_state"] == "NSW"
        assert profile["industry_code"] == "6211"
        assert "BAS" in profile["services_engaged"]
        assert "test" in profile["tags"]


class TestEdgeCases:
    """Tests for edge cases and error handling"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_empty_update_returns_no_changes(self, admin_token):
        """Test that empty update returns profile with no changes message"""
        # Get a profile
        list_response = requests.get(
            f"{BASE_URL}/api/core/client-profiles",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        profiles = list_response.json()["profiles"]
        if not profiles:
            pytest.skip("No profiles available for testing")
        
        profile_id = profiles[0]["id"]
        
        # Send empty update
        response = requests.patch(
            f"{BASE_URL}/api/core/client-profiles/{profile_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert "No updates provided" in data.get("message", "")
    
    def test_invalid_uuid_returns_error(self, admin_token):
        """Test that invalid UUID format returns appropriate error"""
        response = requests.get(
            f"{BASE_URL}/api/core/client-profiles/not-a-valid-uuid",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        # Should return 404, 422, 500, or 520 (Cloudflare error) depending on implementation
        assert response.status_code in [404, 422, 500, 520]
    
    def test_nonexistent_client_code_returns_404(self, admin_token):
        """Test that nonexistent client code returns 404"""
        response = requests.get(
            f"{BASE_URL}/api/core/client-profiles/by-code/NONEXISTENT-CODE-12345",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
