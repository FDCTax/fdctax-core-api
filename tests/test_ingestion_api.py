"""
Bookkeeping Ingestion API Tests
Tests for:
- Authentication (login/logout)
- File upload
- File parsing
- Transaction import
- Batch rollback
- Batch listing
"""

import pytest
import requests
import os
import io

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@fdctax.com"
ADMIN_PASSWORD = "admin123"
STAFF_EMAIL = "staff@fdctax.com"
STAFF_PASSWORD = "staff123"
TAX_AGENT_EMAIL = "taxagent@fdctax.com"
TAX_AGENT_PASSWORD = "taxagent123"


class TestAuthentication:
    """Authentication endpoint tests"""
    
    def test_login_admin_success(self):
        """Test admin login with valid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "access_token" in data, "Response should contain access_token"
        assert "user_id" in data, "Response should contain user_id"
        assert "email" in data, "Response should contain email"
        assert "role" in data, "Response should contain role"
        assert data["email"] == ADMIN_EMAIL
        assert data["role"] == "admin"
        print(f"✓ Admin login successful: {data['email']} (role: {data['role']})")
    
    def test_login_staff_success(self):
        """Test staff login with valid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": STAFF_EMAIL,
            "password": STAFF_PASSWORD
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "access_token" in data
        assert data["email"] == STAFF_EMAIL
        assert data["role"] == "staff"
        print(f"✓ Staff login successful: {data['email']} (role: {data['role']})")
    
    def test_login_invalid_credentials(self):
        """Test login with invalid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "wrong@example.com",
            "password": "wrongpassword"
        })
        assert response.status_code in [401, 400], f"Expected 401/400, got {response.status_code}"
        print("✓ Invalid credentials correctly rejected")


class TestIngestionUpload:
    """File upload endpoint tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get admin auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Authentication failed")
    
    def test_upload_csv_file(self, auth_token):
        """Test uploading a CSV file"""
        # Create a simple CSV content
        csv_content = """Date,Amount,Description,Payee
2025-01-15,100.50,Office supplies,Staples
2025-01-16,-50.00,Coffee,Starbucks
2025-01-17,200.00,Client payment,ABC Corp
"""
        files = {
            'file': ('test_transactions.csv', io.BytesIO(csv_content.encode()), 'text/csv')
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ingestion/upload?client_id=TEST_client_001",
            files=files,
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        assert "batch_id" in data
        assert data.get("file_name") == "test_transactions.csv"
        assert data.get("file_type") == "csv"
        print(f"✓ CSV upload successful: batch_id={data['batch_id']}")
        return data["batch_id"]
    
    def test_upload_without_auth(self):
        """Test upload without authentication"""
        csv_content = "Date,Amount\n2025-01-15,100.00"
        files = {
            'file': ('test.csv', io.BytesIO(csv_content.encode()), 'text/csv')
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ingestion/upload?client_id=TEST_client_001",
            files=files
        )
        
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✓ Upload without auth correctly rejected")
    
    def test_upload_invalid_file_type(self, auth_token):
        """Test uploading an invalid file type"""
        files = {
            'file': ('test.txt', io.BytesIO(b"invalid content"), 'text/plain')
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ingestion/upload?client_id=TEST_client_001",
            files=files,
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        print("✓ Invalid file type correctly rejected")


class TestIngestionParse:
    """File parsing endpoint tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get admin auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Authentication failed")
    
    @pytest.fixture
    def uploaded_batch(self, auth_token):
        """Upload a file and return batch_id"""
        csv_content = """Date,Amount,Description,Payee
2025-01-15,100.50,Office supplies,Staples
2025-01-16,-50.00,Coffee,Starbucks
2025-01-17,200.00,Client payment,ABC Corp
"""
        files = {
            'file': ('test_parse.csv', io.BytesIO(csv_content.encode()), 'text/csv')
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ingestion/upload?client_id=TEST_client_parse",
            files=files,
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        if response.status_code == 200:
            return response.json().get("batch_id")
        pytest.skip("Upload failed")
    
    def test_parse_file(self, auth_token, uploaded_batch):
        """Test parsing an uploaded file"""
        response = requests.post(
            f"{BASE_URL}/api/ingestion/parse",
            json={"batch_id": uploaded_batch},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        assert "columns" in data
        assert "preview" in data
        assert "row_count" in data
        assert "mapping_suggestions" in data
        
        # Verify columns detected
        assert "Date" in data["columns"]
        assert "Amount" in data["columns"]
        assert "Description" in data["columns"]
        assert "Payee" in data["columns"]
        
        # Verify row count
        assert data["row_count"] == 3
        
        # Verify preview data
        assert len(data["preview"]) > 0
        
        print(f"✓ Parse successful: {data['row_count']} rows, columns: {data['columns']}")
        print(f"  Mapping suggestions: {data['mapping_suggestions']}")
    
    def test_parse_invalid_batch(self, auth_token):
        """Test parsing with invalid batch ID"""
        response = requests.post(
            f"{BASE_URL}/api/ingestion/parse",
            json={"batch_id": "00000000-0000-0000-0000-000000000000"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Invalid batch ID correctly rejected")


class TestIngestionImport:
    """Transaction import endpoint tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get admin auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Authentication failed")
    
    @pytest.fixture
    def parsed_batch(self, auth_token):
        """Upload and parse a file, return batch_id"""
        csv_content = """Date,Amount,Description,Payee
2025-01-15,100.50,TEST_Office supplies,Staples
2025-01-16,-50.00,TEST_Coffee,Starbucks
2025-01-17,200.00,TEST_Client payment,ABC Corp
"""
        files = {
            'file': ('test_import.csv', io.BytesIO(csv_content.encode()), 'text/csv')
        }
        
        # Upload
        response = requests.post(
            f"{BASE_URL}/api/ingestion/upload?client_id=TEST_client_import",
            files=files,
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        if response.status_code != 200:
            pytest.skip("Upload failed")
        
        batch_id = response.json().get("batch_id")
        
        # Parse
        response = requests.post(
            f"{BASE_URL}/api/ingestion/parse",
            json={"batch_id": batch_id},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        if response.status_code != 200:
            pytest.skip("Parse failed")
        
        return batch_id
    
    def test_import_transactions(self, auth_token, parsed_batch):
        """Test importing transactions with column mapping"""
        response = requests.post(
            f"{BASE_URL}/api/ingestion/import",
            json={
                "batch_id": parsed_batch,
                "column_mapping": {
                    "date": "Date",
                    "amount": "Amount",
                    "description": "Description",
                    "payee": "Payee"
                },
                "skip_duplicates": True
            },
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        assert "imported_count" in data
        assert "skipped_duplicates" in data
        assert "error_count" in data
        
        print(f"✓ Import successful: {data['imported_count']} imported, {data['skipped_duplicates']} skipped, {data['error_count']} errors")
    
    def test_import_missing_required_mapping(self, auth_token, parsed_batch):
        """Test import with missing required column mapping"""
        response = requests.post(
            f"{BASE_URL}/api/ingestion/import",
            json={
                "batch_id": parsed_batch,
                "column_mapping": {
                    "description": "Description"
                    # Missing date and amount
                },
                "skip_duplicates": True
            },
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        print("✓ Missing required mapping correctly rejected")


class TestIngestionBatches:
    """Batch listing and details endpoint tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get admin auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Authentication failed")
    
    def test_list_batches(self, auth_token):
        """Test listing import batches"""
        response = requests.get(
            f"{BASE_URL}/api/ingestion/batches",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert isinstance(data, list)
        
        if len(data) > 0:
            batch = data[0]
            assert "id" in batch
            assert "client_id" in batch
            assert "file_name" in batch
            assert "status" in batch
            print(f"✓ List batches successful: {len(data)} batches found")
            print(f"  First batch: {batch['file_name']} (status: {batch['status']})")
        else:
            print("✓ List batches successful: 0 batches (empty)")
    
    def test_list_batches_with_filter(self, auth_token):
        """Test listing batches with client_id filter"""
        response = requests.get(
            f"{BASE_URL}/api/ingestion/batches?client_id=TEST_client_001",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert isinstance(data, list)
        
        # All returned batches should have the filtered client_id
        for batch in data:
            assert batch["client_id"] == "TEST_client_001"
        
        print(f"✓ List batches with filter successful: {len(data)} batches")
    
    def test_get_batch_details(self, auth_token):
        """Test getting batch details"""
        # First, list batches to get a valid ID
        list_response = requests.get(
            f"{BASE_URL}/api/ingestion/batches?limit=1",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        if list_response.status_code != 200 or len(list_response.json()) == 0:
            pytest.skip("No batches available for testing")
        
        batch_id = list_response.json()[0]["id"]
        
        response = requests.get(
            f"{BASE_URL}/api/ingestion/batches/{batch_id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["id"] == batch_id
        assert "file_name" in data
        assert "status" in data
        assert "row_count" in data
        
        print(f"✓ Get batch details successful: {data['file_name']}")
    
    def test_get_invalid_batch(self, auth_token):
        """Test getting non-existent batch"""
        response = requests.get(
            f"{BASE_URL}/api/ingestion/batches/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Invalid batch ID correctly returns 404")


class TestIngestionRollback:
    """Batch rollback endpoint tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get admin auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Authentication failed")
    
    def test_rollback_invalid_batch(self, auth_token):
        """Test rollback with invalid batch ID"""
        response = requests.post(
            f"{BASE_URL}/api/ingestion/rollback",
            json={"batch_id": "00000000-0000-0000-0000-000000000000"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        # Should return 400 or 404 for invalid batch
        assert response.status_code in [400, 404], f"Expected 400/404, got {response.status_code}"
        print("✓ Invalid batch rollback correctly rejected")


class TestAccessControl:
    """Access control tests for different roles"""
    
    def test_tax_agent_can_read_batches(self):
        """Test that tax_agent can read batches (read-only access)"""
        # Login as tax_agent
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TAX_AGENT_EMAIL,
            "password": TAX_AGENT_PASSWORD
        })
        
        if login_response.status_code != 200:
            pytest.skip("Tax agent login failed - user may not exist")
        
        token = login_response.json().get("access_token")
        
        # Try to list batches
        response = requests.get(
            f"{BASE_URL}/api/ingestion/batches",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200, f"Tax agent should be able to read batches, got {response.status_code}"
        print("✓ Tax agent can read batches")
    
    def test_tax_agent_cannot_upload(self):
        """Test that tax_agent cannot upload files"""
        # Login as tax_agent
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TAX_AGENT_EMAIL,
            "password": TAX_AGENT_PASSWORD
        })
        
        if login_response.status_code != 200:
            pytest.skip("Tax agent login failed - user may not exist")
        
        token = login_response.json().get("access_token")
        
        # Try to upload
        csv_content = "Date,Amount\n2025-01-15,100.00"
        files = {
            'file': ('test.csv', io.BytesIO(csv_content.encode()), 'text/csv')
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ingestion/upload?client_id=TEST_client",
            files=files,
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 403, f"Tax agent should not be able to upload, got {response.status_code}"
        print("✓ Tax agent correctly denied upload access")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
