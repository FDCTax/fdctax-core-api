"""
E2E API Tests for Core Client API (Ticket A3-8)

Tests the unified client management endpoints:
- POST /api/clients/link-or-create (Original endpoint)
- POST /api/v1/clients/link-or-create (V1 versioned endpoint - Ticket A3-8)
- GET /api/clients/{client_id}
- GET /api/clients
- POST /api/clients/{client_id}/link-crm
- GET /api/clients/golden/test-client

Authentication: Internal API Key (X-Internal-Api-Key header)
Deduplication Logic: email match → link, ABN match → link, no match → create

Run with: pytest tests/test_clients_api.py -v --junitxml=/app/test_reports/pytest/clients_api_results.xml
"""

import pytest
import requests
import os
import uuid
from datetime import datetime

# Get backend URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    BASE_URL = "https://tax-sync-core.preview.emergentagent.com"

# Internal API Key for authentication
INTERNAL_API_KEY = "test-internal-api-key-for-luna-migration"
GOLDEN_TEST_CLIENT_ID = "4e8dab2c-c306-4b7c-997a-11c81e65a95b"


@pytest.fixture
def api_client():
    """Create a requests session with internal API key auth."""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "X-Internal-Api-Key": INTERNAL_API_KEY,
        "X-Service-Name": "test-suite"
    })
    return session


@pytest.fixture
def unauthenticated_client():
    """Create a requests session without auth."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestAuthentication:
    """Test internal API key authentication for client endpoints."""
    
    def test_missing_api_key_returns_401(self, unauthenticated_client):
        """Test that missing API key returns 401."""
        response = unauthenticated_client.get(f"{BASE_URL}/api/clients")
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data
        print(f"✓ Missing API key returns 401: {data['detail']}")
    
    def test_invalid_api_key_returns_401(self, unauthenticated_client):
        """Test that invalid API key returns 401."""
        unauthenticated_client.headers["X-Internal-Api-Key"] = "invalid-key"
        response = unauthenticated_client.get(f"{BASE_URL}/api/clients")
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data
        print(f"✓ Invalid API key returns 401: {data['detail']}")
    
    def test_valid_api_key_accepted(self, api_client):
        """Test that valid API key is accepted."""
        response = api_client.get(f"{BASE_URL}/api/clients")
        assert response.status_code == 200
        print("✓ Valid API key accepted - returned 200")


class TestLinkOrCreateOriginal:
    """Test POST /api/clients/link-or-create (original endpoint)."""
    
    def test_create_new_client(self, api_client):
        """Test creating a new client when no match found."""
        unique_id = str(uuid.uuid4())[:8]
        payload = {
            "myfdc_user_id": f"TEST_myfdc_{unique_id}",
            "email": f"TEST_newclient_{unique_id}@example.com",
            "name": f"TEST New Client {unique_id}",
            "abn": None,
            "phone": "0412345678"
        }
        
        response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert "client_id" in data
        assert data["created"] is True
        assert data["linked"] is False
        assert data["match_type"] is None
        
        print(f"✓ Created new client: {data['client_id']}")
        return data["client_id"]
    
    def test_link_by_email(self, api_client):
        """Test linking to existing client by email."""
        # First create a client
        unique_id = str(uuid.uuid4())[:8]
        email = f"TEST_emaillink_{unique_id}@example.com"
        
        create_payload = {
            "myfdc_user_id": f"TEST_myfdc_first_{unique_id}",
            "email": email,
            "name": f"TEST Email Link Client {unique_id}"
        }
        
        create_response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json=create_payload)
        assert create_response.status_code == 200
        created_data = create_response.json()
        assert created_data["created"] is True
        original_client_id = created_data["client_id"]
        
        # Now try to link with same email but different myfdc_user_id
        link_payload = {
            "myfdc_user_id": f"TEST_myfdc_second_{unique_id}",
            "email": email,  # Same email
            "name": "Different Name"
        }
        
        link_response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json=link_payload)
        assert link_response.status_code == 200
        
        link_data = link_response.json()
        assert link_data["linked"] is True
        assert link_data["created"] is False
        assert link_data["match_type"] == "email"
        assert link_data["client_id"] == original_client_id
        
        print(f"✓ Linked by email to existing client: {original_client_id}")
    
    def test_link_by_abn(self, api_client):
        """Test linking to existing client by ABN."""
        unique_id = str(uuid.uuid4())[:8]
        # Generate a unique ABN-like number
        abn = f"5182475{unique_id[:4]}"
        
        # First create a client with ABN
        create_payload = {
            "myfdc_user_id": f"TEST_myfdc_abn1_{unique_id}",
            "email": f"TEST_abnlink1_{unique_id}@example.com",
            "name": f"TEST ABN Link Client {unique_id}",
            "abn": abn
        }
        
        create_response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json=create_payload)
        assert create_response.status_code == 200
        created_data = create_response.json()
        assert created_data["created"] is True
        original_client_id = created_data["client_id"]
        
        # Now try to link with same ABN but different email
        link_payload = {
            "myfdc_user_id": f"TEST_myfdc_abn2_{unique_id}",
            "email": f"TEST_abnlink2_{unique_id}@example.com",  # Different email
            "name": "Different Name",
            "abn": abn  # Same ABN
        }
        
        link_response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json=link_payload)
        assert link_response.status_code == 200
        
        link_data = link_response.json()
        assert link_data["linked"] is True
        assert link_data["created"] is False
        assert link_data["match_type"] == "abn"
        assert link_data["client_id"] == original_client_id
        
        print(f"✓ Linked by ABN to existing client: {original_client_id}")
    
    def test_missing_required_fields(self, api_client):
        """Test validation for missing required fields."""
        # Missing email
        response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json={
            "myfdc_user_id": "test",
            "name": "Test"
        })
        assert response.status_code == 422
        print("✓ Missing email returns 422")
        
        # Missing name
        response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json={
            "myfdc_user_id": "test",
            "email": "test@example.com"
        })
        assert response.status_code == 422
        print("✓ Missing name returns 422")
        
        # Missing myfdc_user_id
        response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json={
            "email": "test@example.com",
            "name": "Test"
        })
        assert response.status_code == 422
        print("✓ Missing myfdc_user_id returns 422")
    
    def test_invalid_email_format(self, api_client):
        """Test validation for invalid email format."""
        response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json={
            "myfdc_user_id": "test",
            "email": "not-an-email",
            "name": "Test"
        })
        assert response.status_code == 422
        print("✓ Invalid email format returns 422")


class TestLinkOrCreateV1:
    """Test POST /api/v1/clients/link-or-create (V1 versioned endpoint - Ticket A3-8)."""
    
    def test_v1_create_new_client(self, api_client):
        """Test V1 endpoint creates a new client when no match found."""
        unique_id = str(uuid.uuid4())[:8]
        payload = {
            "myfdc_user_id": f"TEST_v1_myfdc_{unique_id}",
            "email": f"TEST_v1_newclient_{unique_id}@example.com",
            "name": f"TEST V1 New Client {unique_id}",
            "abn": None,
            "phone": "0412345678"
        }
        
        response = api_client.post(f"{BASE_URL}/api/v1/clients/link-or-create", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert "client_id" in data
        assert data["created"] is True
        assert data["linked"] is False
        assert data["match_type"] is None
        
        print(f"✓ V1 endpoint created new client: {data['client_id']}")
        return data["client_id"]
    
    def test_v1_link_by_email(self, api_client):
        """Test V1 endpoint links to existing client by email."""
        unique_id = str(uuid.uuid4())[:8]
        email = f"TEST_v1_emaillink_{unique_id}@example.com"
        
        # Create via V1 endpoint
        create_payload = {
            "myfdc_user_id": f"TEST_v1_first_{unique_id}",
            "email": email,
            "name": f"TEST V1 Email Link {unique_id}"
        }
        
        create_response = api_client.post(f"{BASE_URL}/api/v1/clients/link-or-create", json=create_payload)
        assert create_response.status_code == 200
        original_client_id = create_response.json()["client_id"]
        
        # Link via V1 endpoint
        link_payload = {
            "myfdc_user_id": f"TEST_v1_second_{unique_id}",
            "email": email,
            "name": "Different Name"
        }
        
        link_response = api_client.post(f"{BASE_URL}/api/v1/clients/link-or-create", json=link_payload)
        assert link_response.status_code == 200
        
        link_data = link_response.json()
        assert link_data["linked"] is True
        assert link_data["created"] is False
        assert link_data["match_type"] == "email"
        assert link_data["client_id"] == original_client_id
        
        print(f"✓ V1 endpoint linked by email: {original_client_id}")
    
    def test_v1_and_original_share_data(self, api_client):
        """Test that V1 and original endpoints share the same data store."""
        unique_id = str(uuid.uuid4())[:8]
        email = f"TEST_shared_{unique_id}@example.com"
        
        # Create via original endpoint
        create_payload = {
            "myfdc_user_id": f"TEST_shared_orig_{unique_id}",
            "email": email,
            "name": f"TEST Shared Client {unique_id}"
        }
        
        create_response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json=create_payload)
        assert create_response.status_code == 200
        original_client_id = create_response.json()["client_id"]
        
        # Link via V1 endpoint - should find the same client
        link_payload = {
            "myfdc_user_id": f"TEST_shared_v1_{unique_id}",
            "email": email,
            "name": "Different Name"
        }
        
        link_response = api_client.post(f"{BASE_URL}/api/v1/clients/link-or-create", json=link_payload)
        assert link_response.status_code == 200
        
        link_data = link_response.json()
        assert link_data["linked"] is True
        assert link_data["client_id"] == original_client_id
        
        print(f"✓ V1 and original endpoints share data: {original_client_id}")
    
    def test_v1_authentication_required(self, unauthenticated_client):
        """Test V1 endpoint requires authentication."""
        response = unauthenticated_client.post(f"{BASE_URL}/api/v1/clients/link-or-create", json={
            "myfdc_user_id": "test",
            "email": "test@example.com",
            "name": "Test"
        })
        assert response.status_code == 401
        print("✓ V1 endpoint requires authentication")


class TestGetClient:
    """Test GET /api/clients/{client_id}."""
    
    def test_get_client_by_id(self, api_client):
        """Test getting a client by ID."""
        # First create a client with unique email (no ABN to avoid linking to existing)
        unique_id = str(uuid.uuid4())[:8]
        create_payload = {
            "myfdc_user_id": f"TEST_get_{unique_id}",
            "email": f"TEST_getclient_{unique_id}@example.com",
            "name": f"TEST Get Client {unique_id}",
            "abn": None,  # No ABN to ensure new client is created
            "phone": "0412345678"
        }
        
        create_response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json=create_payload)
        assert create_response.status_code == 200
        create_data = create_response.json()
        client_id = create_data["client_id"]
        
        # Get the client
        get_response = api_client.get(f"{BASE_URL}/api/clients/{client_id}")
        assert get_response.status_code == 200
        
        data = get_response.json()
        assert data["client_id"] == client_id
        
        # If client was created (not linked), verify name matches
        if create_data["created"]:
            assert data["name"] == f"TEST Get Client {unique_id}"
            assert data["email"] == f"TEST_getclient_{unique_id}@example.com".lower()
        
        # Always verify myfdc_user_id was linked
        assert data["myfdc_user_id"] is not None
        assert data["status"] == "active"
        
        print(f"✓ Got client by ID: {client_id}")
    
    def test_get_nonexistent_client(self, api_client):
        """Test getting a non-existent client returns 404."""
        fake_id = str(uuid.uuid4())
        response = api_client.get(f"{BASE_URL}/api/clients/{fake_id}")
        assert response.status_code == 404
        print("✓ Non-existent client returns 404")


class TestListClients:
    """Test GET /api/clients."""
    
    def test_list_clients(self, api_client):
        """Test listing all clients."""
        response = api_client.get(f"{BASE_URL}/api/clients")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        
        if len(data) > 0:
            # Verify structure of first client
            client = data[0]
            assert "client_id" in client
            assert "name" in client
            assert "email" in client
            assert "linked_to_myfdc" in client
            assert "linked_to_crm" in client
            assert "status" in client
        
        print(f"✓ Listed {len(data)} clients")
    
    def test_list_clients_with_limit(self, api_client):
        """Test listing clients with limit parameter."""
        response = api_client.get(f"{BASE_URL}/api/clients?limit=5")
        assert response.status_code == 200
        
        data = response.json()
        assert len(data) <= 5
        print(f"✓ Listed clients with limit=5: got {len(data)} clients")
    
    def test_list_clients_with_offset(self, api_client):
        """Test listing clients with offset parameter."""
        # Get first page
        response1 = api_client.get(f"{BASE_URL}/api/clients?limit=2&offset=0")
        assert response1.status_code == 200
        data1 = response1.json()
        
        # Get second page
        response2 = api_client.get(f"{BASE_URL}/api/clients?limit=2&offset=2")
        assert response2.status_code == 200
        data2 = response2.json()
        
        # Verify different results (if enough data)
        if len(data1) > 0 and len(data2) > 0:
            assert data1[0]["client_id"] != data2[0]["client_id"]
        
        print("✓ Pagination with offset works")
    
    def test_list_clients_filter_by_myfdc_link(self, api_client):
        """Test filtering clients by MyFDC link status."""
        response = api_client.get(f"{BASE_URL}/api/clients?linked_to_myfdc=true")
        assert response.status_code == 200
        
        data = response.json()
        for client in data:
            assert client["linked_to_myfdc"] is True
        
        print(f"✓ Filtered by linked_to_myfdc=true: {len(data)} clients")


class TestLinkCRM:
    """Test POST /api/clients/{client_id}/link-crm."""
    
    def test_link_crm_client(self, api_client):
        """Test linking a CRM client ID to a Core client."""
        # First create a client
        unique_id = str(uuid.uuid4())[:8]
        create_payload = {
            "myfdc_user_id": f"TEST_crm_{unique_id}",
            "email": f"TEST_crmlink_{unique_id}@example.com",
            "name": f"TEST CRM Link Client {unique_id}"
        }
        
        create_response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json=create_payload)
        assert create_response.status_code == 200
        client_id = create_response.json()["client_id"]
        
        # Link CRM client ID
        crm_client_id = f"CRM_{unique_id}"
        link_response = api_client.post(
            f"{BASE_URL}/api/clients/{client_id}/link-crm",
            json={"crm_client_id": crm_client_id}
        )
        assert link_response.status_code == 200
        
        link_data = link_response.json()
        assert link_data["success"] is True
        assert link_data["client_id"] == client_id
        assert link_data["crm_client_id"] == crm_client_id
        
        # Verify the link persisted
        get_response = api_client.get(f"{BASE_URL}/api/clients/{client_id}")
        assert get_response.status_code == 200
        assert get_response.json()["crm_client_id"] == crm_client_id
        
        print(f"✓ Linked CRM client ID: {crm_client_id} to {client_id}")
    
    def test_link_crm_nonexistent_client(self, api_client):
        """Test linking CRM to non-existent client returns 404."""
        fake_id = str(uuid.uuid4())
        response = api_client.post(
            f"{BASE_URL}/api/clients/{fake_id}/link-crm",
            json={"crm_client_id": "CRM_123"}
        )
        assert response.status_code == 404
        print("✓ Link CRM to non-existent client returns 404")


class TestGoldenTestClient:
    """Test GET /api/clients/golden/test-client."""
    
    def test_get_golden_test_client(self, api_client):
        """Test getting the Golden Test Client."""
        response = api_client.get(f"{BASE_URL}/api/clients/golden/test-client")
        assert response.status_code == 200
        
        data = response.json()
        assert "client_id" in data
        assert "name" in data
        assert "email" in data
        
        # Check if it was created or already existed
        if data.get("created"):
            print(f"✓ Golden Test Client created: {data['client_id']}")
        else:
            print(f"✓ Golden Test Client found: {data['client_id']}")
        
        return data["client_id"]
    
    def test_golden_test_client_idempotent(self, api_client):
        """Test that getting Golden Test Client is idempotent."""
        # Get twice
        response1 = api_client.get(f"{BASE_URL}/api/clients/golden/test-client")
        assert response1.status_code == 200
        data1 = response1.json()
        
        response2 = api_client.get(f"{BASE_URL}/api/clients/golden/test-client")
        assert response2.status_code == 200
        data2 = response2.json()
        
        # Should return same client
        assert data1["client_id"] == data2["client_id"]
        print(f"✓ Golden Test Client is idempotent: {data1['client_id']}")


class TestEmailNormalization:
    """Test email normalization in deduplication."""
    
    def test_email_case_insensitive(self, api_client):
        """Test that email matching is case-insensitive."""
        unique_id = str(uuid.uuid4())[:8]
        email_lower = f"test_case_{unique_id}@example.com"
        email_upper = f"TEST_CASE_{unique_id}@EXAMPLE.COM"
        
        # Create with lowercase email
        create_payload = {
            "myfdc_user_id": f"TEST_case1_{unique_id}",
            "email": email_lower,
            "name": f"TEST Case Client {unique_id}"
        }
        
        create_response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json=create_payload)
        assert create_response.status_code == 200
        original_client_id = create_response.json()["client_id"]
        
        # Try to link with uppercase email
        link_payload = {
            "myfdc_user_id": f"TEST_case2_{unique_id}",
            "email": email_upper,
            "name": "Different Name"
        }
        
        link_response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json=link_payload)
        assert link_response.status_code == 200
        
        link_data = link_response.json()
        assert link_data["linked"] is True
        assert link_data["client_id"] == original_client_id
        
        print(f"✓ Email matching is case-insensitive")


class TestABNNormalization:
    """Test ABN normalization in deduplication."""
    
    def test_abn_with_spaces(self, api_client):
        """Test that ABN matching handles spaces."""
        unique_id = str(uuid.uuid4())[:8]
        abn_clean = f"5182475{unique_id[:4]}"
        abn_spaced = f"51 824 75{unique_id[:4]}"
        
        # Create with clean ABN
        create_payload = {
            "myfdc_user_id": f"TEST_abn_space1_{unique_id}",
            "email": f"TEST_abnspace1_{unique_id}@example.com",
            "name": f"TEST ABN Space Client {unique_id}",
            "abn": abn_clean
        }
        
        create_response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json=create_payload)
        assert create_response.status_code == 200
        original_client_id = create_response.json()["client_id"]
        
        # Try to link with spaced ABN
        link_payload = {
            "myfdc_user_id": f"TEST_abn_space2_{unique_id}",
            "email": f"TEST_abnspace2_{unique_id}@example.com",
            "name": "Different Name",
            "abn": abn_spaced
        }
        
        link_response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json=link_payload)
        assert link_response.status_code == 200
        
        link_data = link_response.json()
        assert link_data["linked"] is True
        assert link_data["match_type"] == "abn"
        assert link_data["client_id"] == original_client_id
        
        print(f"✓ ABN matching handles spaces")


class TestResponseStructure:
    """Test response structure matches expected schema."""
    
    def test_link_or_create_response_structure(self, api_client):
        """Test LinkOrCreateResponse structure."""
        unique_id = str(uuid.uuid4())[:8]
        payload = {
            "myfdc_user_id": f"TEST_struct_{unique_id}",
            "email": f"TEST_structure_{unique_id}@example.com",
            "name": f"TEST Structure Client {unique_id}"
        }
        
        response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify all expected fields
        assert "client_id" in data
        assert "linked" in data
        assert "created" in data
        assert "match_type" in data
        
        # Verify types
        assert isinstance(data["client_id"], str)
        assert isinstance(data["linked"], bool)
        assert isinstance(data["created"], bool)
        assert data["match_type"] is None or isinstance(data["match_type"], str)
        
        print("✓ LinkOrCreateResponse structure is correct")
    
    def test_client_response_structure(self, api_client):
        """Test ClientResponse structure."""
        unique_id = str(uuid.uuid4())[:8]
        payload = {
            "myfdc_user_id": f"TEST_resp_{unique_id}",
            "email": f"TEST_response_{unique_id}@example.com",
            "name": f"TEST Response Client {unique_id}",
            "abn": "51824753556",
            "phone": "0412345678"
        }
        
        create_response = api_client.post(f"{BASE_URL}/api/clients/link-or-create", json=payload)
        client_id = create_response.json()["client_id"]
        
        response = api_client.get(f"{BASE_URL}/api/clients/{client_id}")
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify all expected fields
        assert "client_id" in data
        assert "name" in data
        assert "email" in data
        assert "abn" in data
        assert "myfdc_user_id" in data
        assert "crm_client_id" in data
        assert "status" in data
        
        print("✓ ClientResponse structure is correct")
    
    def test_client_list_item_structure(self, api_client):
        """Test ClientListItem structure."""
        response = api_client.get(f"{BASE_URL}/api/clients?limit=1")
        assert response.status_code == 200
        
        data = response.json()
        if len(data) > 0:
            client = data[0]
            
            # Verify all expected fields
            assert "client_id" in client
            assert "name" in client
            assert "email" in client
            assert "linked_to_myfdc" in client
            assert "linked_to_crm" in client
            assert "linked_to_bookkeeping" in client
            assert "status" in client
            
            # Verify types
            assert isinstance(client["linked_to_myfdc"], bool)
            assert isinstance(client["linked_to_crm"], bool)
            assert isinstance(client["linked_to_bookkeeping"], bool)
            
            print("✓ ClientListItem structure is correct")
        else:
            print("⚠ No clients to verify list structure")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
