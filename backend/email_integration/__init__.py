"""
Email Integration Module

This module provides email functionality for the FDC Tax Core application.

Phase 0: Scaffolding (Current)
- Module structure created
- Stub classes and endpoints
- Environment variable placeholders

Phase 1: Provider Integration (Future)
- Resend SDK integration
- Outbound email sending
- Delivery status tracking

Phase 2: Templates (Future)
- Email templates
- Variable substitution
- HTML/plain text support

Phase 3: Automation (Future)
- Appointment reminders
- Document request notifications
- Tax deadline alerts
- Bulk email campaigns
"""

from .email_client import EmailClient
from .email_sender import EmailSender

__all__ = ['EmailClient', 'EmailSender']
