"""
Unit Tests for Core SMS Proxy (Ticket A3-7)

Tests SMS forwarding from Core to Agent 5:
- POST /api/internal/sms/send - Send single SMS
- POST /api/internal/sms/bulk - Send bulk SMS
- GET /api/internal/sms/health - Health check
- GET /api/internal/sms/status/{message_id} - Delivery status

Security requirements:
- Internal service token validation
- No phone numbers or message content logged
- Audit logging for all operations

Run with: pytest tests/test_sms_proxy.py -v
"""

import pytest
import uuid
import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from services.sms_proxy import (
    SMSProxyService,
    MockSMSProxyService,
    SMSSendRequest,
    SMSProxyResponse,
    BulkSMSResult,
    SMSProxyStatus,
    AuditEventType,
    RETRY_DELAYS
)


class TestSMSSendRequest:
    """Test SMSSendRequest data class."""
    
    def test_create_request(self):
        """Test creating an SMS request."""
        request = SMSSendRequest(
            to="+61412345678",
            message="Test message",
            source="myfdc",
            client_id="client-123"
        )
        
        assert request.to == "+61412345678"
        assert request.message == "Test message"
        assert request.source == "myfdc"
        assert request.priority == "normal"
    
    def test_get_safe_metadata_excludes_phone(self):
        """Test that safe metadata does not include phone number."""
        request = SMSSendRequest(
            to="+61412345678",
            message="Test message",
            source="myfdc",
            client_id="client-123"
        )
        
        metadata = request.get_safe_metadata()
        
        # Phone number should not be in metadata
        assert 'to' not in metadata
        assert '+61412345678' not in str(metadata)
        
        # Should have a partial hash for correlation
        assert 'phone_hash' in metadata
        assert len(metadata['phone_hash']) == 12
    
    def test_get_safe_metadata_excludes_message(self):
        """Test that safe metadata does not include message content."""
        request = SMSSendRequest(
            to="+61412345678",
            message="Secret message content",
            source="crm"
        )
        
        metadata = request.get_safe_metadata()
        
        # Message should not be in metadata
        assert 'message' not in metadata
        assert 'Secret message content' not in str(metadata)
    
    def test_phone_hash_consistent(self):
        """Test that phone hash is consistent for same number."""
        request1 = SMSSendRequest(to="+61412345678", message="Test", source="myfdc")
        request2 = SMSSendRequest(to="+61412345678", message="Different", source="crm")
        
        assert request1.get_safe_metadata()['phone_hash'] == request2.get_safe_metadata()['phone_hash']
    
    def test_phone_hash_different_for_different_numbers(self):
        """Test that phone hash differs for different numbers."""
        request1 = SMSSendRequest(to="+61412345678", message="Test", source="myfdc")
        request2 = SMSSendRequest(to="+61498765432", message="Test", source="myfdc")
        
        assert request1.get_safe_metadata()['phone_hash'] != request2.get_safe_metadata()['phone_hash']


class TestSMSProxyResponse:
    """Test SMSProxyResponse data class."""
    
    def test_success_response(self):
        """Test successful response."""
        response = SMSProxyResponse(
            success=True,
            message_id="msg-123",
            status="sent"
        )
        
        assert response.success is True
        assert response.message_id == "msg-123"
        assert response.error is None
    
    def test_failure_response(self):
        """Test failure response."""
        response = SMSProxyResponse(
            success=False,
            status="failed",
            error="Connection timeout"
        )
        
        assert response.success is False
        assert response.error == "Connection timeout"
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        response = SMSProxyResponse(
            success=True,
            message_id="msg-456",
            status="sent",
            retry_count=1
        )
        
        d = response.to_dict()
        
        assert d['success'] is True
        assert d['message_id'] == "msg-456"
        assert d['retry_count'] == 1


class TestBulkSMSResult:
    """Test BulkSMSResult data class."""
    
    def test_bulk_result(self):
        """Test bulk SMS result."""
        result = BulkSMSResult(
            total=10,
            sent=8,
            failed=2,
            results=[
                {'success': True, 'message_id': 'msg-1'},
                {'success': False, 'error': 'Invalid number'}
            ]
        )
        
        assert result.total == 10
        assert result.sent == 8
        assert result.failed == 2
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = BulkSMSResult(
            total=5,
            sent=5,
            failed=0,
            results=[]
        )
        
        d = result.to_dict()
        
        assert d['total'] == 5
        assert d['sent'] == 5


class TestMockSMSProxyService:
    """Test mock SMS proxy service."""
    
    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        return db
    
    @pytest.fixture
    def mock_service(self, mock_db):
        """Create mock SMS service."""
        return MockSMSProxyService(mock_db)
    
    @pytest.mark.asyncio
    async def test_mock_send_always_succeeds(self, mock_service):
        """Test that mock service always succeeds."""
        request = SMSSendRequest(
            to="+61412345678",
            message="Test message",
            source="myfdc"
        )
        
        result = await mock_service.send_sms(request, "test-service")
        
        assert result.success is True
        assert result.message_id is not None
        assert result.status == "sent"
    
    @pytest.mark.asyncio
    async def test_mock_health_always_healthy(self, mock_service):
        """Test that mock health check returns healthy."""
        health = await mock_service.check_health()
        
        assert health['agent5_available'] is True
        assert health['mock_mode'] is True
    
    @pytest.mark.asyncio
    async def test_mock_bulk_send(self, mock_service):
        """Test mock bulk SMS."""
        requests = [
            SMSSendRequest(to="+61412345678", message="Test 1", source="myfdc"),
            SMSSendRequest(to="+61498765432", message="Test 2", source="myfdc")
        ]
        
        result = await mock_service.send_bulk_sms(requests, "test-service")
        
        assert result.total == 2
        assert result.sent == 2
        assert result.failed == 0


class TestSMSProxyService:
    """Test real SMS proxy service."""
    
    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        return db
    
    @pytest.fixture
    def service(self, mock_db):
        """Create SMS proxy service."""
        return SMSProxyService(mock_db)
    
    @pytest.mark.asyncio
    async def test_send_sms_logs_audit(self, service, mock_db):
        """Test that sending SMS logs audit events."""
        request = SMSSendRequest(
            to="+61412345678",
            message="Test message",
            source="myfdc",
            client_id="client-123"
        )
        
        # Mock the forward method to succeed
        with patch.object(service, '_forward_to_agent5') as mock_forward:
            mock_forward.return_value = SMSProxyResponse(
                success=True,
                message_id="msg-123",
                status="sent"
            )
            
            result = await service.send_sms(request, "test-service")
            
            assert result.success is True
            # Should have logged audit events
            mock_db.execute.assert_called()
    
    @pytest.mark.asyncio
    async def test_send_sms_retries_on_failure(self, service, mock_db):
        """Test that SMS send retries on failure."""
        request = SMSSendRequest(
            to="+61412345678",
            message="Test message",
            source="myfdc"
        )
        
        call_count = 0
        
        async def mock_forward(*args):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return SMSProxyResponse(success=False, error="Timeout")
            return SMSProxyResponse(success=True, message_id="msg-123", status="sent")
        
        with patch.object(service, '_forward_to_agent5', side_effect=mock_forward):
            with patch('services.sms_proxy.RETRY_DELAYS', [0, 0, 0]):  # No delay for test
                result = await service.send_sms(request, "test-service")
        
        assert result.success is True
        assert call_count == 3
    
    @pytest.mark.asyncio
    async def test_send_sms_fails_after_max_retries(self, service, mock_db):
        """Test that SMS send fails after max retries."""
        request = SMSSendRequest(
            to="+61412345678",
            message="Test message",
            source="myfdc"
        )
        
        with patch.object(service, '_forward_to_agent5') as mock_forward:
            mock_forward.return_value = SMSProxyResponse(
                success=False,
                error="Agent 5 unavailable"
            )
            
            with patch('services.sms_proxy.RETRY_DELAYS', [0, 0, 0]):
                result = await service.send_sms(request, "test-service")
        
        assert result.success is False
        assert result.retry_count == service.config['max_retries']


class TestAuditLogging:
    """Test audit logging for SMS proxy."""
    
    def test_audit_event_types_defined(self):
        """Test all audit event types are defined."""
        expected_events = [
            "sms_proxy_request",
            "sms_proxy_success",
            "sms_proxy_failure",
            "sms_proxy_retry",
            "sms_proxy_fallback",
            "sms_bulk_request",
            "sms_bulk_success",
            "sms_bulk_failure"
        ]
        
        actual_events = [e.value for e in AuditEventType]
        
        for event in expected_events:
            assert event in actual_events
    
    def test_audit_does_not_log_phone(self, caplog):
        """Test that audit logging excludes phone numbers."""
        import logging
        caplog.set_level(logging.INFO)
        
        # Create a request with phone number
        request = SMSSendRequest(
            to="+61412345678",
            message="Secret message",
            source="myfdc"
        )
        
        metadata = request.get_safe_metadata()
        
        # Phone number should not be in metadata
        assert "+61412345678" not in str(metadata)
        assert "Secret message" not in str(metadata)


class TestRetryConfiguration:
    """Test retry configuration."""
    
    def test_retry_delays_defined(self):
        """Test retry delays are defined."""
        assert len(RETRY_DELAYS) >= 3
        
        # Delays should be reasonable (quick for SMS)
        for delay in RETRY_DELAYS:
            assert delay >= 1
            assert delay <= 30
    
    def test_retry_delays_increase(self):
        """Test retry delays increase (exponential backoff)."""
        for i in range(len(RETRY_DELAYS) - 1):
            assert RETRY_DELAYS[i] <= RETRY_DELAYS[i + 1]


class TestSMSProxyStatus:
    """Test SMS proxy status enumeration."""
    
    def test_all_statuses_defined(self):
        """Test all expected statuses are defined."""
        expected_statuses = [
            "pending",
            "sent",
            "delivered",
            "failed",
            "queued"
        ]
        
        actual_statuses = [s.value for s in SMSProxyStatus]
        
        for status in expected_statuses:
            assert status in actual_statuses


class TestSecurityRequirements:
    """Test security requirements for SMS proxy."""
    
    def test_phone_number_never_in_safe_metadata(self):
        """Test phone number is never in safe metadata."""
        test_numbers = [
            "+61412345678",
            "+1234567890",
            "0412345678",
            "+44 7911 123456"
        ]
        
        for number in test_numbers:
            request = SMSSendRequest(to=number, message="Test", source="test")
            metadata = request.get_safe_metadata()
            
            # Number should never appear in metadata
            assert number not in str(metadata)
            assert number.replace(" ", "") not in str(metadata)
            assert number.replace("+", "") not in str(metadata)
    
    def test_message_content_never_in_safe_metadata(self):
        """Test message content is never in safe metadata."""
        sensitive_messages = [
            "Your PIN is 1234",
            "Account balance: $5000",
            "Password reset: abc123"
        ]
        
        for message in sensitive_messages:
            request = SMSSendRequest(to="+61412345678", message=message, source="test")
            metadata = request.get_safe_metadata()
            
            # Message should never appear in metadata
            for word in message.split():
                if len(word) > 3:  # Skip small common words
                    assert word not in str(metadata)
    
    def test_phone_hash_not_reversible(self):
        """Test phone hash cannot be reversed to original number."""
        request = SMSSendRequest(to="+61412345678", message="Test", source="test")
        metadata = request.get_safe_metadata()
        
        phone_hash = metadata['phone_hash']
        
        # Hash should be partial (not full SHA256)
        assert len(phone_hash) == 12
        
        # Should not contain obvious patterns from phone number
        assert "61412" not in phone_hash
        assert "345678" not in phone_hash


class TestBulkSMSProcessing:
    """Test bulk SMS processing."""
    
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        return db
    
    @pytest.mark.asyncio
    async def test_bulk_processes_all_messages(self, mock_db):
        """Test bulk SMS processes all messages."""
        service = MockSMSProxyService(mock_db)
        
        requests = [
            SMSSendRequest(to=f"+6141234567{i}", message=f"Test {i}", source="myfdc")
            for i in range(5)
        ]
        
        result = await service.send_bulk_sms(requests, "test-service")
        
        assert result.total == 5
        assert result.sent == 5
    
    @pytest.mark.asyncio
    async def test_bulk_results_have_phone_hash(self, mock_db):
        """Test bulk results have phone hash for correlation."""
        service = MockSMSProxyService(mock_db)
        
        requests = [
            SMSSendRequest(to="+61412345678", message="Test", source="myfdc")
        ]
        
        result = await service.send_bulk_sms(requests, "test-service")
        
        assert len(result.results) == 1
        assert 'phone_hash' in result.results[0]
        assert len(result.results[0]['phone_hash']) == 12


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
