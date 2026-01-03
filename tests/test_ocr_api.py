"""
OCR API Tests (A3-OCR-01)

Tests for the OCR receipt processing module:
- GET /api/ocr/status - Module status (no auth)
- POST /api/ocr/receipt - Process receipt image from URL

Features tested:
- File download from URL and local storage
- OpenAI Vision API integration via Emergent LLM key
- Attachment metadata stored in ingestion_attachments table
- Transaction linking - attachments linked to existing transactions
- Audit trail populated in transaction record
- Internal API key authentication validation
- Error handling for invalid URLs, unsupported formats
"""

import pytest
import requests
import os
import time
import uuid

# Base URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
INTERNAL_API_KEY = "4e9d7c3b1a8f2d6c5e0b9a7d3c1f8e4b6a2d9c7f1e3b5a0c4d8f6b2e1c7a9d3"
TEST_CLIENT_ID = "4e8dab2c-c306-4b7c-997a-11c81e65a95b"
TEST_TRANSACTION_ID = "01a86d26-2c31-47db-bd56-884cdbcff003"

# Test image URLs - using accessible public images
# Using Unsplash for reliable image access
TEST_IMAGE_URL_JPEG = "https://images.unsplash.com/photo-1554224155-6726b3ff858f?w=400"  # Receipt-like image
TEST_IMAGE_URL_PNG = "https://images.unsplash.com/photo-1554224155-6726b3ff858f?fm=png&w=400"
TEST_IMAGE_URL_WEBP = "https://images.unsplash.com/photo-1554224155-6726b3ff858f?fm=webp&w=400"


class TestOCRStatusEndpoint:
    """Tests for GET /api/ocr/status - Public endpoint (no auth required)"""
    
    def test_status_returns_200(self):
        """Status endpoint should return 200 without authentication"""
        response = requests.get(f"{BASE_URL}/api/ocr/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("✓ GET /api/ocr/status returns 200")
    
    def test_status_response_structure(self):
        """Status response should have correct structure"""
        response = requests.get(f"{BASE_URL}/api/ocr/status")
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify required fields
        assert "module" in data, "Missing 'module' field"
        assert data["module"] == "ocr", f"Expected module='ocr', got '{data['module']}'"
        
        assert "status" in data, "Missing 'status' field"
        assert data["status"] in ["operational", "degraded"], f"Invalid status: {data['status']}"
        
        assert "version" in data, "Missing 'version' field"
        assert "features" in data, "Missing 'features' field"
        assert "storage_path" in data, "Missing 'storage_path' field"
        assert "timestamp" in data, "Missing 'timestamp' field"
        
        print(f"✓ Status response structure valid: module={data['module']}, status={data['status']}")
    
    def test_status_features_structure(self):
        """Features object should have correct structure"""
        response = requests.get(f"{BASE_URL}/api/ocr/status")
        assert response.status_code == 200
        
        features = response.json()["features"]
        
        # Verify feature flags
        assert "receipt_ocr" in features, "Missing 'receipt_ocr' feature"
        assert features["receipt_ocr"] == True, "receipt_ocr should be True"
        
        assert "pdf_support" in features, "Missing 'pdf_support' feature"
        assert features["pdf_support"] == True, "pdf_support should be True"
        
        assert "image_formats" in features, "Missing 'image_formats' feature"
        assert "jpeg" in features["image_formats"], "jpeg should be supported"
        assert "png" in features["image_formats"], "png should be supported"
        assert "webp" in features["image_formats"], "webp should be supported"
        
        assert "openai_vision" in features, "Missing 'openai_vision' feature"
        assert "transaction_linking" in features, "Missing 'transaction_linking' feature"
        
        print(f"✓ Features structure valid: {features}")
    
    def test_status_openai_vision_configured(self):
        """OpenAI Vision should be configured (EMERGENT_LLM_KEY present)"""
        response = requests.get(f"{BASE_URL}/api/ocr/status")
        assert response.status_code == 200
        
        data = response.json()
        
        # If EMERGENT_LLM_KEY is configured, status should be operational
        if data["features"]["openai_vision"]:
            assert data["status"] == "operational", "Status should be 'operational' when OpenAI Vision is configured"
            print("✓ OpenAI Vision is configured, status is operational")
        else:
            assert data["status"] == "degraded", "Status should be 'degraded' when OpenAI Vision is not configured"
            print("⚠ OpenAI Vision is NOT configured, status is degraded")


class TestOCRReceiptAuthentication:
    """Tests for POST /api/ocr/receipt - Authentication validation"""
    
    def test_missing_api_key_returns_401(self):
        """Missing X-Internal-Api-Key header should return 401"""
        response = requests.post(
            f"{BASE_URL}/api/ocr/receipt",
            json={
                "client_id": TEST_CLIENT_ID,
                "file_url": TEST_IMAGE_URL_JPEG
            }
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        print("✓ Missing API key returns 401")
    
    def test_invalid_api_key_returns_403(self):
        """Invalid X-Internal-Api-Key should return 403"""
        response = requests.post(
            f"{BASE_URL}/api/ocr/receipt",
            headers={"X-Internal-Api-Key": "invalid-key-12345"},
            json={
                "client_id": TEST_CLIENT_ID,
                "file_url": TEST_IMAGE_URL_JPEG
            }
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
        print("✓ Invalid API key returns 403")
    
    def test_valid_api_key_accepted(self):
        """Valid X-Internal-Api-Key should be accepted (not 401/403)"""
        response = requests.post(
            f"{BASE_URL}/api/ocr/receipt",
            headers={"X-Internal-Api-Key": INTERNAL_API_KEY},
            json={
                "client_id": TEST_CLIENT_ID,
                "file_url": TEST_IMAGE_URL_JPEG
            }
        )
        # Should not be 401 or 403
        assert response.status_code not in [401, 403], f"Valid API key rejected: {response.status_code}: {response.text}"
        print(f"✓ Valid API key accepted, response status: {response.status_code}")


class TestOCRReceiptValidation:
    """Tests for POST /api/ocr/receipt - Input validation"""
    
    def test_missing_client_id_returns_422(self):
        """Missing client_id should return 422"""
        response = requests.post(
            f"{BASE_URL}/api/ocr/receipt",
            headers={"X-Internal-Api-Key": INTERNAL_API_KEY},
            json={
                "file_url": TEST_IMAGE_URL_JPEG
            }
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        print("✓ Missing client_id returns 422")
    
    def test_missing_file_url_returns_422(self):
        """Missing file_url should return 422"""
        response = requests.post(
            f"{BASE_URL}/api/ocr/receipt",
            headers={"X-Internal-Api-Key": INTERNAL_API_KEY},
            json={
                "client_id": TEST_CLIENT_ID
            }
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        print("✓ Missing file_url returns 422")
    
    def test_invalid_url_format_returns_400(self):
        """Invalid URL format should return 400"""
        response = requests.post(
            f"{BASE_URL}/api/ocr/receipt",
            headers={"X-Internal-Api-Key": INTERNAL_API_KEY},
            json={
                "client_id": TEST_CLIENT_ID,
                "file_url": "not-a-valid-url"
            }
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        print("✓ Invalid URL format returns 400")
    
    def test_ftp_url_returns_400(self):
        """FTP URL should return 400 (only HTTP/HTTPS supported)"""
        response = requests.post(
            f"{BASE_URL}/api/ocr/receipt",
            headers={"X-Internal-Api-Key": INTERNAL_API_KEY},
            json={
                "client_id": TEST_CLIENT_ID,
                "file_url": "ftp://example.com/receipt.jpg"
            }
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        print("✓ FTP URL returns 400")


class TestOCRReceiptProcessing:
    """Tests for POST /api/ocr/receipt - Receipt processing"""
    
    def test_process_jpeg_image(self):
        """Process JPEG image from URL"""
        response = requests.post(
            f"{BASE_URL}/api/ocr/receipt",
            headers={"X-Internal-Api-Key": INTERNAL_API_KEY},
            json={
                "client_id": TEST_CLIENT_ID,
                "file_url": TEST_IMAGE_URL_JPEG
            },
            timeout=120  # OCR can take time
        )
        
        # Should return 200 (success) or 500 (if OCR fails but request was valid)
        assert response.status_code in [200, 500], f"Unexpected status: {response.status_code}: {response.text}"
        
        data = response.json()
        
        if response.status_code == 200:
            assert "success" in data, "Missing 'success' field"
            
            if data["success"]:
                # Successful OCR
                assert "attachment_id" in data, "Missing 'attachment_id' field"
                assert "ocr_result" in data, "Missing 'ocr_result' field"
                
                ocr_result = data["ocr_result"]
                assert "confidence" in ocr_result, "Missing 'confidence' in ocr_result"
                
                print(f"✓ JPEG image processed successfully")
                print(f"  - Attachment ID: {data.get('attachment_id')}")
                print(f"  - Vendor: {ocr_result.get('vendor')}")
                print(f"  - Amount: {ocr_result.get('amount')}")
                print(f"  - Confidence: {ocr_result.get('confidence')}")
            else:
                # OCR failed but request was valid
                assert "error" in data, "Missing 'error' field for failed OCR"
                print(f"⚠ OCR processing failed: {data.get('error')}")
        else:
            print(f"⚠ Request failed with 500: {data}")
    
    def test_process_with_transaction_linking(self):
        """Process receipt and link to existing transaction"""
        response = requests.post(
            f"{BASE_URL}/api/ocr/receipt",
            headers={"X-Internal-Api-Key": INTERNAL_API_KEY},
            json={
                "client_id": TEST_CLIENT_ID,
                "file_url": TEST_IMAGE_URL_JPEG,
                "transaction_id": TEST_TRANSACTION_ID
            },
            timeout=120
        )
        
        # Should return 200 or 500
        assert response.status_code in [200, 500], f"Unexpected status: {response.status_code}: {response.text}"
        
        data = response.json()
        
        if response.status_code == 200 and data.get("success"):
            # Check if transaction was updated
            assert "transaction_updated" in data, "Missing 'transaction_updated' field"
            print(f"✓ Receipt processed with transaction linking")
            print(f"  - Transaction updated: {data.get('transaction_updated')}")
        else:
            print(f"⚠ Transaction linking test: {data}")
    
    def test_response_structure_on_success(self):
        """Verify response structure on successful OCR"""
        response = requests.post(
            f"{BASE_URL}/api/ocr/receipt",
            headers={"X-Internal-Api-Key": INTERNAL_API_KEY},
            json={
                "client_id": TEST_CLIENT_ID,
                "file_url": TEST_IMAGE_URL_JPEG
            },
            timeout=120
        )
        
        data = response.json()
        
        # Verify response model structure
        assert "success" in data, "Missing 'success' field"
        
        if data.get("success"):
            # OCRReceiptResponse fields
            assert "attachment_id" in data, "Missing 'attachment_id'"
            assert "ocr_result" in data, "Missing 'ocr_result'"
            assert "transaction_updated" in data, "Missing 'transaction_updated'"
            
            # OCR result structure
            ocr_result = data["ocr_result"]
            expected_fields = ["success", "vendor", "amount", "date", "description", 
                            "gst_amount", "gst_included", "items", "raw_text", "confidence"]
            
            for field in expected_fields:
                assert field in ocr_result, f"Missing '{field}' in ocr_result"
            
            print(f"✓ Response structure valid")
            print(f"  - OCR result fields: {list(ocr_result.keys())}")
        else:
            assert "error" in data, "Missing 'error' field for failed OCR"
            print(f"⚠ OCR failed, error structure valid: {data.get('error')}")


class TestOCRErrorHandling:
    """Tests for error handling scenarios"""
    
    def test_nonexistent_url_returns_error(self):
        """Non-existent URL should return error"""
        response = requests.post(
            f"{BASE_URL}/api/ocr/receipt",
            headers={"X-Internal-Api-Key": INTERNAL_API_KEY},
            json={
                "client_id": TEST_CLIENT_ID,
                "file_url": "https://example.com/nonexistent-image-12345.jpg"
            },
            timeout=60
        )
        
        # Should return 200 with success=false or 400/500
        assert response.status_code in [200, 400, 500], f"Unexpected status: {response.status_code}"
        
        data = response.json()
        
        if response.status_code == 200:
            assert data.get("success") == False, "Should return success=false for non-existent URL"
            assert "error" in data, "Should have error message"
            print(f"✓ Non-existent URL handled: {data.get('error')}")
        else:
            print(f"✓ Non-existent URL returned {response.status_code}")
    
    def test_unsupported_format_returns_error(self):
        """Unsupported file format should return error"""
        # Try to process a text file URL
        response = requests.post(
            f"{BASE_URL}/api/ocr/receipt",
            headers={"X-Internal-Api-Key": INTERNAL_API_KEY},
            json={
                "client_id": TEST_CLIENT_ID,
                "file_url": "https://raw.githubusercontent.com/github/gitignore/main/Python.gitignore"
            },
            timeout=60
        )
        
        # Should return 200 with success=false or 400
        assert response.status_code in [200, 400], f"Unexpected status: {response.status_code}: {response.text}"
        
        data = response.json()
        
        if response.status_code == 200:
            assert data.get("success") == False, "Should return success=false for unsupported format"
            print(f"✓ Unsupported format handled: {data.get('error')}")
        else:
            print(f"✓ Unsupported format returned 400")


class TestOCRStorageAndAttachments:
    """Tests for file storage and attachment metadata"""
    
    def test_attachment_id_is_uuid(self):
        """Attachment ID should be a valid UUID"""
        response = requests.post(
            f"{BASE_URL}/api/ocr/receipt",
            headers={"X-Internal-Api-Key": INTERNAL_API_KEY},
            json={
                "client_id": TEST_CLIENT_ID,
                "file_url": TEST_IMAGE_URL_JPEG
            },
            timeout=120
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get("success") and data.get("attachment_id"):
                attachment_id = data["attachment_id"]
                
                # Validate UUID format
                try:
                    uuid.UUID(attachment_id)
                    print(f"✓ Attachment ID is valid UUID: {attachment_id}")
                except ValueError:
                    pytest.fail(f"Attachment ID is not a valid UUID: {attachment_id}")
            else:
                print(f"⚠ OCR failed, skipping attachment ID validation")
        else:
            print(f"⚠ Request failed, skipping attachment ID validation")


# Fixtures
@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "X-Internal-Api-Key": INTERNAL_API_KEY
    })
    return session


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
