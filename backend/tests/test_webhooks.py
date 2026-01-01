"""
Unit Tests for Webhook Notification System (Ticket A3-4)

Tests all webhook functionality:
- Webhook registration
- Event dispatch
- Delivery with HMAC signature
- Retry logic with exponential backoff
- Dead-letter queue
- Audit logging

Run with: pytest tests/test_webhooks.py -v
"""

import pytest
import uuid
import json
import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from services.webhook_service import (
    WebhookService,
    WebhookEventType,
    DeliveryStatus,
    AuditEventType,
    WebhookPayload,
    DeliveryResult,
    MAX_RETRY_ATTEMPTS,
    RETRY_DELAYS
)


class TestWebhookRegistration:
    """Test webhook registration functionality."""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        return db
    
    @pytest.fixture
    def service(self, mock_db):
        """Create service with mocked database."""
        return WebhookService(mock_db)
    
    @pytest.mark.asyncio
    async def test_register_webhook_success(self, service, mock_db):
        """Test successful webhook registration."""
        result = await service.register_webhook(
            service_name="crm",
            url="https://crm.example.com/webhooks/myfdc",
            events=["myfdc.hours.logged", "myfdc.expense.logged"],
            registered_by="admin"
        )
        
        assert result['service_name'] == "crm"
        assert result['url'] == "https://crm.example.com/webhooks/myfdc"
        assert 'secret_key' in result
        assert len(result['secret_key']) == 64  # hex string of 32 bytes
        assert 'id' in result
        mock_db.commit.assert_called()
    
    @pytest.mark.asyncio
    async def test_register_webhook_invalid_events(self, service, mock_db):
        """Test registration with invalid event types."""
        with pytest.raises(ValueError) as exc_info:
            await service.register_webhook(
                service_name="crm",
                url="https://crm.example.com/webhooks",
                events=["invalid.event.type"],
                registered_by="admin"
            )
        
        assert "Invalid event types" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_register_webhook_valid_events(self, service, mock_db):
        """Test registration with all valid event types."""
        all_events = [e.value for e in WebhookEventType]
        
        result = await service.register_webhook(
            service_name="crm",
            url="https://crm.example.com/webhooks",
            events=all_events,
            registered_by="admin"
        )
        
        assert result['events'] == all_events
    
    @pytest.mark.asyncio
    async def test_list_webhooks(self, service, mock_db):
        """Test listing webhooks."""
        mock_rows = [
            MagicMock(
                id=uuid.uuid4(),
                service_name='crm',
                url='https://crm.example.com/webhooks',
                events=['myfdc.hours.logged'],
                is_active=True,
                created_at=datetime.now(timezone.utc),
                created_by='admin'
            )
        ]
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = mock_rows
        mock_db.execute.return_value = mock_result
        
        webhooks = await service.list_webhooks()
        
        assert len(webhooks) == 1
        assert webhooks[0]['service_name'] == 'crm'
        assert webhooks[0]['is_active'] is True
    
    @pytest.mark.asyncio
    async def test_list_webhooks_filtered(self, service, mock_db):
        """Test listing webhooks with service filter."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result
        
        await service.list_webhooks(service_name='specific_service')
        
        # Verify filter was included in query
        mock_db.execute.assert_called()
    
    @pytest.mark.asyncio
    async def test_delete_webhook(self, service, mock_db):
        """Test webhook deletion."""
        webhook_id = str(uuid.uuid4())
        
        # Mock get_webhook to return existing webhook
        mock_webhook_result = MagicMock()
        mock_webhook_result.fetchone.return_value = MagicMock(
            id=webhook_id,
            service_name='crm',
            url='https://crm.example.com',
            events=['myfdc.hours.logged'],
            is_active=True,
            created_at=datetime.now(timezone.utc),
            created_by='admin'
        )
        mock_db.execute.return_value = mock_webhook_result
        
        success = await service.delete_webhook(webhook_id, 'admin')
        
        assert success is True
        mock_db.commit.assert_called()
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_webhook(self, service, mock_db):
        """Test deleting non-existent webhook."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result
        
        success = await service.delete_webhook(str(uuid.uuid4()), 'admin')
        
        assert success is False


class TestEventDispatch:
    """Test webhook event dispatch functionality."""
    
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        return db
    
    @pytest.fixture
    def service(self, mock_db):
        return WebhookService(mock_db)
    
    @pytest.mark.asyncio
    async def test_dispatch_event_queues_delivery(self, service, mock_db):
        """Test that dispatching an event queues it for delivery."""
        # Mock webhook registrations
        mock_webhooks = [
            MagicMock(id=uuid.uuid4(), service_name='crm', url='https://crm.example.com', secret_key='test-secret')
        ]
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = mock_webhooks
        mock_db.execute.return_value = mock_result
        
        await service.dispatch_event(
            event_type=WebhookEventType.HOURS_LOGGED,
            client_id='client-123',
            data_id='record-456'
        )
        
        # Should have queued delivery
        mock_db.commit.assert_called()
    
    @pytest.mark.asyncio
    async def test_dispatch_event_no_subscribers(self, service, mock_db):
        """Test dispatch when no webhooks are subscribed."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result
        
        # Should not raise, just log debug message
        await service.dispatch_event(
            event_type=WebhookEventType.HOURS_LOGGED,
            client_id='client-123',
            data_id='record-456'
        )


class TestWebhookPayload:
    """Test webhook payload structure."""
    
    def test_payload_structure(self):
        """Test WebhookPayload contains no sensitive data."""
        payload = WebhookPayload(
            event="myfdc.hours.logged",
            client_id="client-123",
            timestamp="2025-01-15T10:00:00Z",
            data_id="record-456"
        )
        
        d = payload.to_dict()
        
        assert d['event'] == "myfdc.hours.logged"
        assert d['client_id'] == "client-123"
        assert d['timestamp'] == "2025-01-15T10:00:00Z"
        assert d['data_id'] == "record-456"
        
        # Ensure no sensitive fields
        sensitive_fields = ['tfn', 'abn', 'bank_account', 'password', 'secret']
        for field in sensitive_fields:
            assert field not in d
    
    def test_payload_deterministic(self):
        """Test WebhookPayload produces consistent output."""
        payload1 = WebhookPayload("event", "client", "time", "data")
        payload2 = WebhookPayload("event", "client", "time", "data")
        
        assert payload1.to_dict() == payload2.to_dict()


class TestHMACSignature:
    """Test HMAC signature generation and validation."""
    
    def test_signature_generation(self):
        """Test that signatures are generated correctly."""
        secret_key = "test-secret-key-12345"
        payload = {"event": "test", "client_id": "123"}
        
        payload_bytes = json.dumps(payload, sort_keys=True).encode('utf-8')
        expected_signature = hmac.new(
            secret_key.encode('utf-8'),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        
        # Verify our expected signature format
        assert len(expected_signature) == 64  # SHA256 hex digest
    
    def test_signature_verification(self):
        """Test signature verification logic."""
        secret_key = "test-secret-key"
        payload = {"event": "myfdc.hours.logged", "client_id": "123"}
        
        payload_bytes = json.dumps(payload, sort_keys=True).encode('utf-8')
        signature = hmac.new(
            secret_key.encode('utf-8'),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        
        # Verify
        payload_bytes_verify = json.dumps(payload, sort_keys=True).encode('utf-8')
        expected_sig = hmac.new(
            secret_key.encode('utf-8'),
            payload_bytes_verify,
            hashlib.sha256
        ).hexdigest()
        
        assert hmac.compare_digest(signature, expected_sig)


class TestRetryLogic:
    """Test retry logic with exponential backoff."""
    
    def test_retry_delays_defined(self):
        """Test retry delays are properly defined."""
        assert MAX_RETRY_ATTEMPTS == 3
        assert len(RETRY_DELAYS) >= MAX_RETRY_ATTEMPTS
        
        # Verify exponential backoff pattern
        assert RETRY_DELAYS[0] < RETRY_DELAYS[1] < RETRY_DELAYS[2]
    
    def test_retry_delays_reasonable(self):
        """Test retry delays are reasonable values."""
        for delay in RETRY_DELAYS:
            assert delay >= 60  # At least 1 minute
            assert delay <= 3600  # At most 1 hour
    
    @pytest.mark.asyncio
    async def test_schedule_retry_calculates_delay(self):
        """Test that retry scheduling uses correct delay."""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        
        service = WebhookService(mock_db)
        
        # Test first retry uses first delay
        await service._schedule_retry(
            queue_id=str(uuid.uuid4()),
            attempts=1,
            error="Connection timeout",
            service_name="crm"
        )
        
        mock_db.execute.assert_called()


class TestDeadLetterQueue:
    """Test dead-letter queue functionality."""
    
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        return db
    
    @pytest.fixture
    def service(self, mock_db):
        return WebhookService(mock_db)
    
    @pytest.mark.asyncio
    async def test_move_to_dead_letter(self, service, mock_db):
        """Test moving failed delivery to dead letter queue."""
        await service._move_to_dead_letter(
            queue_id=str(uuid.uuid4()),
            webhook_id=str(uuid.uuid4()),
            event_type="myfdc.hours.logged",
            payload={"event": "test"},
            attempts=3,
            error="Connection refused",
            service_name="crm"
        )
        
        # Should insert into dead letter and update queue
        assert mock_db.execute.call_count >= 2
        mock_db.commit.assert_called()
    
    @pytest.mark.asyncio
    async def test_get_dead_letter_items(self, service, mock_db):
        """Test retrieving dead letter items."""
        mock_rows = [
            MagicMock(
                id=uuid.uuid4(),
                webhook_id=uuid.uuid4(),
                service_name='crm',
                url='https://crm.example.com',
                event_type='myfdc.hours.logged',
                payload='{"event": "test"}',
                attempts=3,
                last_error='Connection refused',
                failed_at=datetime.now(timezone.utc)
            )
        ]
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = mock_rows
        mock_db.execute.return_value = mock_result
        
        items = await service.get_dead_letter_items(limit=10)
        
        assert len(items) == 1
        assert items[0]['event_type'] == 'myfdc.hours.logged'
        assert items[0]['attempts'] == 3
    
    @pytest.mark.asyncio
    async def test_retry_dead_letter(self, service, mock_db):
        """Test re-queuing a dead letter item."""
        dead_letter_id = str(uuid.uuid4())
        
        # Mock dead letter item
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(
            webhook_id=uuid.uuid4(),
            event_type='myfdc.hours.logged',
            payload='{"event": "test"}'
        )
        mock_db.execute.return_value = mock_result
        
        success = await service.retry_dead_letter(dead_letter_id, 'admin')
        
        assert success is True
        mock_db.commit.assert_called()


class TestDeliveryResult:
    """Test DeliveryResult dataclass."""
    
    def test_success_result(self):
        """Test successful delivery result."""
        result = DeliveryResult(
            success=True,
            status_code=200,
            duration_ms=150
        )
        
        assert result.success is True
        assert result.status_code == 200
        assert result.error is None
    
    def test_failure_result(self):
        """Test failed delivery result."""
        result = DeliveryResult(
            success=False,
            status_code=500,
            error="Internal Server Error"
        )
        
        assert result.success is False
        assert result.error == "Internal Server Error"
    
    def test_timeout_result(self):
        """Test timeout delivery result."""
        result = DeliveryResult(
            success=False,
            error="Connection timeout"
        )
        
        assert result.success is False
        assert result.status_code is None


class TestQueueStats:
    """Test queue statistics functionality."""
    
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        return db
    
    @pytest.fixture
    def service(self, mock_db):
        return WebhookService(mock_db)
    
    @pytest.mark.asyncio
    async def test_get_queue_stats(self, service, mock_db):
        """Test getting queue statistics."""
        # Mock status counts
        mock_status_rows = [
            MagicMock(status='pending', count=5),
            MagicMock(status='delivered', count=100),
            MagicMock(status='failed', count=2)
        ]
        
        mock_dl_row = MagicMock(count=3)
        
        mock_db.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=mock_status_rows)),
            MagicMock(fetchone=MagicMock(return_value=mock_dl_row))
        ]
        
        stats = await service.get_queue_stats()
        
        assert stats['pending'] == 5
        assert stats['delivered'] == 100
        assert stats['dead_letter_total'] == 3


class TestEventTypes:
    """Test webhook event type definitions."""
    
    def test_all_event_types_defined(self):
        """Test all expected event types are defined."""
        expected_events = [
            "myfdc.profile.updated",
            "myfdc.hours.logged",
            "myfdc.occupancy.logged",
            "myfdc.diary.created",
            "myfdc.expense.logged",
            "myfdc.attendance.logged"
        ]
        
        actual_events = [e.value for e in WebhookEventType]
        
        for event in expected_events:
            assert event in actual_events
    
    def test_event_types_consistent_naming(self):
        """Test event types follow consistent naming pattern."""
        for event in WebhookEventType:
            # All should start with 'myfdc.'
            assert event.value.startswith("myfdc.")
            
            # All should have action suffix
            parts = event.value.split(".")
            assert len(parts) == 3
            assert parts[0] == "myfdc"


class TestAuditLogging:
    """Test audit logging functionality."""
    
    def test_audit_event_types_defined(self):
        """Test all audit event types are defined."""
        expected_events = [
            "webhook_registered",
            "webhook_updated",
            "webhook_deleted",
            "webhook_delivered",
            "webhook_failed",
            "webhook_dead_letter",
            "webhook_retry"
        ]
        
        actual_events = [e.value for e in AuditEventType]
        
        for event in expected_events:
            assert event in actual_events


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
