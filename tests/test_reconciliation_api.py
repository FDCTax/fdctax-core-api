"""
Reconciliation API Tests (A3-RECON-01)

Tests for the reconciliation engine endpoints:
- GET /api/reconciliation/status - Module status (public)
- GET /api/reconciliation/sources - List sources (public)
- POST /api/reconciliation/match - Run reconciliation
- POST /api/reconciliation/candidates/{client_id} - Find candidates
- GET /api/reconciliation/matches/{client_id} - Get matches
- GET /api/reconciliation/match/{match_id} - Get single match
- POST /api/reconciliation/match/{match_id}/confirm - Confirm match
- POST /api/reconciliation/match/{match_id}/reject - Reject match
- GET /api/reconciliation/stats/{client_id} - Get stats
- GET /api/reconciliation/suggested/{client_id} - Get suggested matches
"""

import pytest
import requests
import os
import uuid

# Get BASE_URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
API_KEY = "4e9d7c3b1a8f2d6c5e0b9a7d3c1f8e4b6a2d9c7f1e3b5a0c4d8f6b2e1c7a9d3"
TEST_CLIENT_ID = "4e8dab2c-c306-4b7c-997a-11c81e65a95b"


@pytest.fixture
def api_client():
    """Shared requests session."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture
def authenticated_client(api_client):
    """Session with internal API key."""
    api_client.headers.update({"X-Internal-Api-Key": API_KEY})
    return api_client


class TestPublicEndpoints:
    """Tests for public endpoints (no auth required)."""
    
    def test_status_endpoint(self, api_client):
        """GET /api/reconciliation/status - Returns module status."""
        response = api_client.get(f"{BASE_URL}/api/reconciliation/status")
        
        assert response.status_code == 200
        data = response.json()
        
        # Validate response structure
        assert data["module"] == "reconciliation"
        assert data["status"] == "operational"
        assert "version" in data
        assert "features" in data
        assert "sources_enabled" in data
        assert "timestamp" in data
        
        # Validate features
        features = data["features"]
        assert features["myfdc_matching"] is True
        assert features["auto_matching"] is True
        
        # Validate sources
        assert "MYFDC" in data["sources_enabled"]
    
    def test_sources_endpoint(self, api_client):
        """GET /api/reconciliation/sources - Returns source configurations."""
        response = api_client.get(f"{BASE_URL}/api/reconciliation/sources")
        
        assert response.status_code == 200
        data = response.json()
        
        # Validate response structure
        assert "sources" in data
        assert "enabled_count" in data
        assert data["enabled_count"] >= 1
        
        # Validate MYFDC source config
        myfdc_source = next((s for s in data["sources"] if s["source"] == "MYFDC"), None)
        assert myfdc_source is not None
        assert myfdc_source["display_name"] == "MyFDC Transactions"
        assert myfdc_source["priority"] == 1
        assert myfdc_source["enabled"] is True
        assert "BANK" in myfdc_source["match_targets"]
        assert myfdc_source["auto_match_threshold"] == 0.85
        assert myfdc_source["suggest_match_threshold"] == 0.60


class TestAuthentication:
    """Tests for API key authentication."""
    
    def test_missing_api_key_returns_401(self, api_client):
        """Endpoints requiring auth return 401 without API key."""
        response = api_client.get(f"{BASE_URL}/api/reconciliation/matches/{TEST_CLIENT_ID}")
        
        assert response.status_code == 401
        assert "Missing X-Internal-Api-Key" in response.json()["detail"]
    
    def test_invalid_api_key_returns_403(self, api_client):
        """Endpoints return 403 with invalid API key."""
        api_client.headers.update({"X-Internal-Api-Key": "invalid-key"})
        response = api_client.get(f"{BASE_URL}/api/reconciliation/matches/{TEST_CLIENT_ID}")
        
        assert response.status_code == 403
        assert "Invalid API key" in response.json()["detail"]
    
    def test_valid_api_key_accepted(self, authenticated_client):
        """Endpoints accept valid API key."""
        response = authenticated_client.get(f"{BASE_URL}/api/reconciliation/matches/{TEST_CLIENT_ID}")
        
        assert response.status_code == 200


class TestGetMatches:
    """Tests for GET /api/reconciliation/matches/{client_id}."""
    
    def test_get_matches_returns_list(self, authenticated_client):
        """Returns list of matches for client."""
        response = authenticated_client.get(f"{BASE_URL}/api/reconciliation/matches/{TEST_CLIENT_ID}")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["client_id"] == TEST_CLIENT_ID
        assert "matches" in data
        assert isinstance(data["matches"], list)
        assert "count" in data
        assert "limit" in data
        assert "offset" in data
    
    def test_get_matches_with_status_filter(self, authenticated_client):
        """Filters matches by status."""
        response = authenticated_client.get(
            f"{BASE_URL}/api/reconciliation/matches/{TEST_CLIENT_ID}?status=CONFIRMED"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # All returned matches should have CONFIRMED status
        for match in data["matches"]:
            assert match["match_status"] == "CONFIRMED"
    
    def test_get_matches_with_invalid_status(self, authenticated_client):
        """Returns 400 for invalid status filter."""
        response = authenticated_client.get(
            f"{BASE_URL}/api/reconciliation/matches/{TEST_CLIENT_ID}?status=INVALID"
        )
        
        assert response.status_code == 400
        assert "Invalid status" in response.json()["detail"]
    
    def test_get_matches_pagination(self, authenticated_client):
        """Supports limit and offset pagination."""
        response = authenticated_client.get(
            f"{BASE_URL}/api/reconciliation/matches/{TEST_CLIENT_ID}?limit=5&offset=0"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["limit"] == 5
        assert data["offset"] == 0


class TestGetSingleMatch:
    """Tests for GET /api/reconciliation/match/{match_id}."""
    
    def test_get_existing_match(self, authenticated_client):
        """Returns match details for existing match."""
        # First get a match ID from the list
        list_response = authenticated_client.get(
            f"{BASE_URL}/api/reconciliation/matches/{TEST_CLIENT_ID}"
        )
        matches = list_response.json()["matches"]
        
        if matches:
            match_id = matches[0]["id"]
            response = authenticated_client.get(f"{BASE_URL}/api/reconciliation/match/{match_id}")
            
            assert response.status_code == 200
            data = response.json()
            
            # Validate response structure
            assert data["id"] == match_id
            assert "client_id" in data
            assert "source_transaction_id" in data
            assert "source_type" in data
            assert "match_status" in data
            assert "confidence_score" in data
            assert "created_at" in data
    
    def test_get_nonexistent_match(self, authenticated_client):
        """Returns 404 for non-existent match."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = authenticated_client.get(f"{BASE_URL}/api/reconciliation/match/{fake_id}")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestRunReconciliation:
    """Tests for POST /api/reconciliation/match."""
    
    def test_run_reconciliation_success(self, authenticated_client):
        """Runs reconciliation and returns results."""
        payload = {
            "client_id": TEST_CLIENT_ID,
            "source_type": "MYFDC",
            "target_type": "BANK",
            "auto_match": True
        }
        response = authenticated_client.post(
            f"{BASE_URL}/api/reconciliation/match",
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Validate response structure
        assert "run_id" in data
        assert data["client_id"] == TEST_CLIENT_ID
        assert data["source_type"] == "MYFDC"
        assert "total_transactions" in data
        assert "auto_matched" in data
        assert "suggested" in data
        assert "no_match" in data
        assert "matches" in data
    
    def test_run_reconciliation_invalid_source_type(self, authenticated_client):
        """Returns 400 for invalid source_type."""
        payload = {
            "client_id": TEST_CLIENT_ID,
            "source_type": "INVALID",
            "target_type": "BANK"
        }
        response = authenticated_client.post(
            f"{BASE_URL}/api/reconciliation/match",
            json=payload
        )
        
        assert response.status_code == 400
        assert "Invalid source_type" in response.json()["detail"]
    
    def test_run_reconciliation_invalid_target_type(self, authenticated_client):
        """Returns 400 for invalid target_type."""
        payload = {
            "client_id": TEST_CLIENT_ID,
            "source_type": "MYFDC",
            "target_type": "INVALID"
        }
        response = authenticated_client.post(
            f"{BASE_URL}/api/reconciliation/match",
            json=payload
        )
        
        assert response.status_code == 400
        assert "Invalid target_type" in response.json()["detail"]
    
    def test_run_reconciliation_with_specific_transactions(self, authenticated_client):
        """Runs reconciliation for specific transaction IDs."""
        payload = {
            "client_id": TEST_CLIENT_ID,
            "source_type": "MYFDC",
            "target_type": "BANK",
            "transaction_ids": ["01a86d26-2c31-47db-bd56-884cdbcff003"],
            "auto_match": False
        }
        response = authenticated_client.post(
            f"{BASE_URL}/api/reconciliation/match",
            json=payload
        )
        
        assert response.status_code == 200


class TestFindCandidates:
    """Tests for POST /api/reconciliation/candidates/{client_id}."""
    
    def test_find_candidates_success(self, authenticated_client):
        """Finds match candidates for a transaction."""
        payload = {
            "source_transaction_id": "01a86d26-2c31-47db-bd56-884cdbcff003"
        }
        response = authenticated_client.post(
            f"{BASE_URL}/api/reconciliation/candidates/{TEST_CLIENT_ID}",
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Validate response structure
        assert "source_transaction_id" in data
        assert "source_type" in data
        assert "candidates_count" in data
        assert "candidates" in data
        assert "auto_matched" in data
        assert "suggested_match" in data
        
        # Validate candidate structure if any exist
        if data["candidates"]:
            candidate = data["candidates"][0]
            assert "target_id" in candidate
            assert "target_type" in candidate
            assert "confidence_score" in candidate
            assert "match_type" in candidate
            assert "scoring_breakdown" in candidate
    
    def test_find_candidates_invalid_transaction(self, authenticated_client):
        """Returns 400 for non-existent transaction."""
        payload = {
            "source_transaction_id": "00000000-0000-0000-0000-000000000000"
        }
        response = authenticated_client.post(
            f"{BASE_URL}/api/reconciliation/candidates/{TEST_CLIENT_ID}",
            json=payload
        )
        
        assert response.status_code == 400
        assert "not found" in response.json()["detail"].lower()
    
    def test_find_candidates_with_target_type_filter(self, authenticated_client):
        """Filters candidates by target type."""
        payload = {
            "source_transaction_id": "01a86d26-2c31-47db-bd56-884cdbcff003",
            "target_type": "BANK"
        }
        response = authenticated_client.post(
            f"{BASE_URL}/api/reconciliation/candidates/{TEST_CLIENT_ID}",
            json=payload
        )
        
        assert response.status_code == 200


class TestConfirmMatch:
    """Tests for POST /api/reconciliation/match/{match_id}/confirm."""
    
    def test_confirm_nonexistent_match(self, authenticated_client):
        """Returns 404 for non-existent match."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = authenticated_client.post(
            f"{BASE_URL}/api/reconciliation/match/{fake_id}/confirm"
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_confirm_match_with_user_id(self, authenticated_client):
        """Confirm endpoint accepts X-User-Id header."""
        # Get a match to confirm
        list_response = authenticated_client.get(
            f"{BASE_URL}/api/reconciliation/matches/{TEST_CLIENT_ID}?status=SUGGESTED"
        )
        matches = list_response.json()["matches"]
        
        if matches:
            match_id = matches[0]["id"]
            authenticated_client.headers.update({"X-User-Id": "test-user-pytest"})
            response = authenticated_client.post(
                f"{BASE_URL}/api/reconciliation/match/{match_id}/confirm"
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["match"]["status"] == "CONFIRMED"


class TestRejectMatch:
    """Tests for POST /api/reconciliation/match/{match_id}/reject."""
    
    def test_reject_nonexistent_match(self, authenticated_client):
        """Returns 404 for non-existent match."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = authenticated_client.post(
            f"{BASE_URL}/api/reconciliation/match/{fake_id}/reject",
            json={"reason": "Test rejection"}
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_reject_match_with_reason(self, authenticated_client):
        """Reject endpoint accepts reason in body."""
        # Get a match to reject
        list_response = authenticated_client.get(
            f"{BASE_URL}/api/reconciliation/matches/{TEST_CLIENT_ID}?status=SUGGESTED"
        )
        matches = list_response.json()["matches"]
        
        if matches:
            match_id = matches[0]["id"]
            authenticated_client.headers.update({"X-User-Id": "test-user-pytest"})
            response = authenticated_client.post(
                f"{BASE_URL}/api/reconciliation/match/{match_id}/reject",
                json={"reason": "Amount mismatch - pytest test"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["match"]["status"] == "REJECTED"


class TestGetStats:
    """Tests for GET /api/reconciliation/stats/{client_id}."""
    
    def test_get_stats_success(self, authenticated_client):
        """Returns reconciliation statistics."""
        response = authenticated_client.get(
            f"{BASE_URL}/api/reconciliation/stats/{TEST_CLIENT_ID}"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Validate response structure
        assert data["client_id"] == TEST_CLIENT_ID
        assert "total_matches" in data
        assert "by_status" in data
        assert "reconciliation_rate" in data
        
        # Validate by_status contains all statuses
        by_status = data["by_status"]
        assert "PENDING" in by_status
        assert "MATCHED" in by_status
        assert "SUGGESTED" in by_status
        assert "NO_MATCH" in by_status
        assert "REJECTED" in by_status
        assert "CONFIRMED" in by_status
        
        # Validate reconciliation_rate is a percentage
        assert 0 <= data["reconciliation_rate"] <= 100


class TestGetSuggestedMatches:
    """Tests for GET /api/reconciliation/suggested/{client_id}."""
    
    def test_get_suggested_matches(self, authenticated_client):
        """Returns suggested matches for review."""
        response = authenticated_client.get(
            f"{BASE_URL}/api/reconciliation/suggested/{TEST_CLIENT_ID}"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Validate response structure
        assert data["client_id"] == TEST_CLIENT_ID
        assert "suggested_matches" in data
        assert "count" in data
        
        # All returned matches should have SUGGESTED status
        for match in data["suggested_matches"]:
            assert match["match_status"] == "SUGGESTED"
    
    def test_get_suggested_matches_with_limit(self, authenticated_client):
        """Supports limit parameter."""
        response = authenticated_client.get(
            f"{BASE_URL}/api/reconciliation/suggested/{TEST_CLIENT_ID}?limit=10"
        )
        
        assert response.status_code == 200


class TestMatchScoring:
    """Tests for match scoring algorithm."""
    
    def test_scoring_breakdown_structure(self, authenticated_client):
        """Validates scoring breakdown structure."""
        payload = {
            "source_transaction_id": "01a86d26-2c31-47db-bd56-884cdbcff003"
        }
        response = authenticated_client.post(
            f"{BASE_URL}/api/reconciliation/candidates/{TEST_CLIENT_ID}",
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        if data["candidates"]:
            breakdown = data["candidates"][0]["scoring_breakdown"]
            
            # Validate scoring components
            assert "amount" in breakdown
            assert "date" in breakdown
            assert "category" in breakdown
            assert "description" in breakdown
            assert "gst" in breakdown
            assert "attachment" in breakdown
            assert "total" in breakdown
            
            # Validate scores are in valid range
            for key, value in breakdown.items():
                assert 0 <= value <= 1, f"{key} score {value} out of range"


class TestSourceValidation:
    """Tests for source type validation."""
    
    def test_myfdc_source_recognized(self, authenticated_client):
        """MYFDC is recognized as valid source."""
        payload = {
            "client_id": TEST_CLIENT_ID,
            "source_type": "MYFDC",
            "target_type": "BANK"
        }
        response = authenticated_client.post(
            f"{BASE_URL}/api/reconciliation/match",
            json=payload
        )
        
        assert response.status_code == 200
        assert response.json()["source_type"] == "MYFDC"
    
    def test_all_valid_source_types(self, authenticated_client):
        """All documented source types are valid."""
        valid_sources = ["MYFDC", "OCR", "BANK_FEED", "MANUAL"]
        
        for source in valid_sources:
            payload = {
                "client_id": TEST_CLIENT_ID,
                "source_type": source,
                "target_type": "BANK"
            }
            response = authenticated_client.post(
                f"{BASE_URL}/api/reconciliation/match",
                json=payload
            )
            
            # Should not return 400 for invalid source
            assert response.status_code != 400 or "Invalid source_type" not in response.json().get("detail", "")
    
    def test_all_valid_target_types(self, authenticated_client):
        """All documented target types are valid."""
        valid_targets = ["BANK", "RECEIPT", "INVOICE", "MANUAL"]
        
        for target in valid_targets:
            payload = {
                "client_id": TEST_CLIENT_ID,
                "source_type": "MYFDC",
                "target_type": target
            }
            response = authenticated_client.post(
                f"{BASE_URL}/api/reconciliation/match",
                json=payload
            )
            
            # Should not return 400 for invalid target
            assert response.status_code != 400 or "Invalid target_type" not in response.json().get("detail", "")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
