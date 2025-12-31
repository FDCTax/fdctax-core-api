"""
Email Integration Module

This module provides email functionality for the FDC Tax Core application
using Resend as the email provider.

Features:
- Email sending via Resend API
- Template rendering with {{variable}} placeholders
- Nested variable support ({{client.address.city}})
- Default values ({{name | default:"Guest"}})
- HTML sanitization
- Database logging for audit trail
- Variable validation

Phase 1: Resend Integration ✅
- Real email sending
- Basic template support

Phase 1.5: Template Rendering Engine ✅
- Advanced placeholder syntax
- Variable validation
- HTML sanitization
- Render preview endpoint
"""

from .email_client import EmailClient, EmailResult, EmailMessage, EmailStatus, EmailAttachment
from .email_sender import EmailSender, EmailMessageType
from .template_engine import (
    TemplateEngine,
    get_template_engine,
    render_template,
    TemplateValidationResult,
    RenderResult,
    TEMPLATE_VARIABLES
)

__all__ = [
    # Client
    'EmailClient',
    'EmailResult',
    'EmailMessage',
    'EmailStatus',
    'EmailAttachment',
    # Sender
    'EmailSender',
    'EmailMessageType',
    # Template Engine
    'TemplateEngine',
    'get_template_engine',
    'render_template',
    'TemplateValidationResult',
    'RenderResult',
    'TEMPLATE_VARIABLES'
]

