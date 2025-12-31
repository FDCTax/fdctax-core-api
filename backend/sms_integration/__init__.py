"""
SMS Integration Module

This module provides SMS functionality for the FDC Tax Core application.

Phase 0: Scaffolding (Current)
- Module structure created
- Stub classes and endpoints
- Environment variable placeholders

Phase 1: Provider Integration (Future - Agent 4)
- Twilio/provider integration
- Outbound SMS sending
- Delivery status tracking

Phase 2: Inbound SMS (Future)
- Webhook handling for incoming SMS
- Message storage and routing
- Auto-reply functionality

Phase 3: Automation (Future)
- Appointment reminders
- Document request notifications
- Payment reminders
"""

from .sms_client import SMSClient
from .sms_sender import SMSSender
from .webhook_handler import SMSWebhookHandler

__all__ = ['SMSClient', 'SMSSender', 'SMSWebhookHandler']
