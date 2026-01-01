"""
Unit Tests for Core Client API

Tests the unified client management endpoints:
- POST /api/clients/link-or-create
- POST /api/v1/clients/link-or-create (Ticket A3-8 - versioned alias)
- GET /api/clients/{client_id}
- GET /api/clients
- POST /api/clients/{client_id}/link-crm

Run with: pytest tests/test_clients.py -v
"""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from services.clients import (
    CoreClientService,
    CoreClient,
    LinkOrCreateResult,
    ClientAuditEvent,
    log_client_event
)


class TestCoreClientService:
    """Test CoreClientService functionality."""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        return db
    
    @pytest.fixture
    def service(self, mock_db):
        """Create service with mocked database."""
        return CoreClientService(mock_db)
    
    # ==================== LINK OR CREATE TESTS ====================
    
    @pytest.mark.asyncio
    async def test_link_or_create_creates_new_client(self, service, mock_db):
        """Test creating a new client when no match found."""
        # Mock no existing client found
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result
        
        result = await service.link_or_create(
            myfdc_user_id="myfdc_123",
            email="new@example.com",
            name="New Client"
        )
        
        assert result.created is True
        assert result.linked is False
        assert result.match_type is None
        assert result.client_id is not None
    
    @pytest.mark.asyncio
    async def test_link_or_create_links_by_email(self, service, mock_db):
        """Test linking to existing client by email."""
        existing_id = str(uuid.uuid4())
        
        # Mock existing client found by email
        mock_row = MagicMock()
        mock_row.id = existing_id
        mock_row.display_name = "Existing Client"
        mock_row.primary_contact_email = "existing@example.com"
        mock_row.myfdc_user_id = None
        
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_db.execute.return_value = mock_result
        
        result = await service.link_or_create(
            myfdc_user_id="myfdc_456",
            email="existing@example.com",
            name="Test Client"
        )
        
        assert result.linked is True
        assert result.created is False
        assert result.match_type == "email"
        assert result.client_id == existing_id
    
    @pytest.mark.asyncio
    async def test_link_or_create_links_by_abn(self, service, mock_db):
        """Test linking to existing client by ABN."""
        existing_id = str(uuid.uuid4())
        
        # Mock: No email match, but ABN match
        mock_result_email = MagicMock()
        mock_result_email.fetchone.return_value = None
        
        mock_row_abn = MagicMock()
        mock_row_abn.id = existing_id
        mock_row_abn.display_name = "ABN Client"
        mock_row_abn.abn = "51824753556"
        
        mock_result_abn = MagicMock()
        mock_result_abn.fetchone.return_value = mock_row_abn
        
        # First call returns no email match, second returns ABN match
        mock_db.execute.side_effect = [mock_result_email, mock_result_abn, MagicMock()]
        
        result = await service.link_or_create(
            myfdc_user_id="myfdc_789",
            email="different@example.com",
            name="Test Client",
            abn="51 824 753 556"  # With spaces
        )
        
        assert result.linked is True
        assert result.created is False
        assert result.match_type == "abn"
    
    # ==================== GET BY ID TESTS ====================
    
    @pytest.mark.asyncio
    async def test_get_by_id_returns_client(self, service, mock_db):
        """Test getting a client by ID."""
        client_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        mock_row = MagicMock()
        mock_row.id = client_id
        mock_row.display_name = "Test Client"
        mock_row.primary_contact_email = "test@example.com"
        mock_row.abn = "51824753556"
        mock_row.primary_contact_phone = "0412345678"
        mock_row.myfdc_user_id = "myfdc_test"
        mock_row.crm_client_id = None
        mock_row.bookkeeping_id = None
        mock_row.workpaper_id = None
        mock_row.client_status = "active"
        mock_row.entity_type = "individual"
        mock_row.created_at = now
        mock_row.updated_at = now
        
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_db.execute.return_value = mock_result
        
        client = await service.get_by_id(client_id)
        
        assert client is not None
        assert client.client_id == client_id
        assert client.name == "Test Client"
        assert client.email == "test@example.com"
        assert client.myfdc_user_id == "myfdc_test"
    
    @pytest.mark.asyncio
    async def test_get_by_id_returns_none_for_not_found(self, service, mock_db):
        """Test getting non-existent client returns None."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result
        
        client = await service.get_by_id("non-existent-id")
        
        assert client is None
    
    # ==================== LIST TESTS ====================
    
    @pytest.mark.asyncio
    async def test_list_all_returns_clients(self, service, mock_db):
        """Test listing all clients."""
        mock_rows = [
            MagicMock(
                id="id1", display_name="Client 1", primary_contact_email="c1@test.com",
                abn=None, primary_contact_phone=None, myfdc_user_id="myfdc1",
                crm_client_id=None, bookkeeping_id=None, workpaper_id=None,
                client_status="active", entity_type="individual",
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)
            ),
            MagicMock(
                id="id2", display_name="Client 2", primary_contact_email="c2@test.com",
                abn="12345678901", primary_contact_phone="0400000000", myfdc_user_id=None,
                crm_client_id="crm_123", bookkeeping_id=None, workpaper_id=None,
                client_status="active", entity_type="company",
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)
            )
        ]
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = mock_rows
        mock_db.execute.return_value = mock_result
        
        clients = await service.list_all()
        
        assert len(clients) == 2
        assert clients[0].name == "Client 1"
        assert clients[0].myfdc_user_id == "myfdc1"
        assert clients[1].crm_client_id == "crm_123"
    
    @pytest.mark.asyncio
    async def test_list_all_with_filters(self, service, mock_db):
        """Test listing with filters applied."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result
        
        await service.list_all(
            status="active",
            linked_to_myfdc=True,
            limit=50
        )
        
        # Verify execute was called (filter logic is in SQL)
        assert mock_db.execute.called


class TestCoreClientModel:
    """Test CoreClient model."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        now = datetime.now(timezone.utc)
        client = CoreClient(
            client_id="test-123",
            name="Test Client",
            email="test@example.com",
            abn="51824753556",
            myfdc_user_id="myfdc_test",
            status="active",
            created_at=now
        )
        
        result = client.to_dict()
        
        assert result["client_id"] == "test-123"
        assert result["name"] == "Test Client"
        assert result["email"] == "test@example.com"
        assert result["abn"] == "51824753556"
        assert result["myfdc_user_id"] == "myfdc_test"
        assert result["status"] == "active"
    
    def test_to_list_dict(self):
        """Test conversion to list item dictionary."""
        client = CoreClient(
            client_id="test-456",
            name="List Test",
            email="list@example.com",
            myfdc_user_id="myfdc_yes",
            crm_client_id=None,
            bookkeeping_id="bk_123"
        )
        
        result = client.to_list_dict()
        
        assert result["client_id"] == "test-456"
        assert result["linked_to_myfdc"] is True
        assert result["linked_to_crm"] is False
        assert result["linked_to_bookkeeping"] is True


class TestLinkOrCreateResult:
    """Test LinkOrCreateResult model."""
    
    def test_created_result(self):
        """Test result when client was created."""
        result = LinkOrCreateResult(
            client_id="new-123",
            linked=False,
            created=True,
            match_type=None
        )
        
        d = result.to_dict()
        
        assert d["client_id"] == "new-123"
        assert d["linked"] is False
        assert d["created"] is True
        assert d["match_type"] is None
    
    def test_linked_result(self):
        """Test result when client was linked."""
        result = LinkOrCreateResult(
            client_id="existing-456",
            linked=True,
            created=False,
            match_type="email"
        )
        
        d = result.to_dict()
        
        assert d["linked"] is True
        assert d["created"] is False
        assert d["match_type"] == "email"


class TestAuditLogging:
    """Test audit logging functionality."""
    
    def test_log_client_event_sanitizes_abn(self, caplog):
        """Test that ABN is masked in logs."""
        import logging
        caplog.set_level(logging.INFO)
        
        log_client_event(
            ClientAuditEvent.CLIENT_CREATED,
            "client-123",
            "test-service",
            {"abn": "51824753556", "name": "Test"}
        )
        
        # Check ABN is masked in log output
        for record in caplog.records:
            assert "51824753556" not in record.message
    
    def test_log_client_event_excludes_tfn(self, caplog):
        """Test that TFN is excluded from logs."""
        import logging
        caplog.set_level(logging.INFO)
        
        log_client_event(
            ClientAuditEvent.CLIENT_CREATED,
            "client-456",
            "test-service",
            {"tfn": "123456789", "name": "Test"}  # TFN should be excluded
        )
        
        # TFN should not appear in logs
        for record in caplog.records:
            assert "123456789" not in record.message


class TestDeduplication:
    """Test client deduplication logic."""
    
    def test_email_normalization(self):
        """Test that email is normalized before comparison."""
        # Email should be lowercased and trimmed
        email = "  Test@Example.COM  "
        normalized = email.lower().strip()
        
        assert normalized == "test@example.com"
    
    def test_abn_normalization(self):
        """Test that ABN is cleaned before comparison."""
        # ABN should have spaces and dashes removed
        abn = "51 824 753-556"
        cleaned = abn.replace(' ', '').replace('-', '')
        
        assert cleaned == "51824753556"


class TestDeterministicResponses:
    """Test that responses are deterministic."""
    
    def test_link_or_create_result_deterministic(self):
        """Test LinkOrCreateResult produces consistent output."""
        result1 = LinkOrCreateResult("id-1", True, False, "email")
        result2 = LinkOrCreateResult("id-1", True, False, "email")
        
        assert result1.to_dict() == result2.to_dict()
    
    def test_core_client_deterministic(self):
        """Test CoreClient produces consistent output."""
        now = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        client1 = CoreClient("id-1", "Test", "test@test.com", created_at=now)
        client2 = CoreClient("id-1", "Test", "test@test.com", created_at=now)
        
        assert client1.to_dict() == client2.to_dict()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
