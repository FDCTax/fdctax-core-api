"""
Email Integration Module

This module provides email functionality for the FDC Tax Core application
using Resend as the email provider.

Features:
- Email sending via Resend API
- Template-based emails with variable substitution
- Database logging for audit trail
- Email validation

Phase 1: Resend Integration (Current) ✅
- Real email sending
- Template support
- Database logging
- Validation endpoints

Phase 2: Advanced Features (Future)
- Bulk email sending
- Scheduling
- Open/click tracking
"""

from .email_client import EmailClient, EmailResult, EmailMessage, EmailStatus, EmailAttachment
from .email_sender import EmailSender, EmailMessageType

__all__ = [
    'EmailClient',
    'EmailResult',
    'EmailMessage',
    'EmailStatus',
    'EmailAttachment',
    'EmailSender',
    'EmailMessageType'
]

