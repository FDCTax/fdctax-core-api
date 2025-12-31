"""
SMS Sender - High-level SMS sending service

This module provides business logic for sending SMS messages,
including templating, rate limiting, and audit logging.

Currently a stub - will be implemented in Phase 1 by Agent 4.

Features (Future):
- Message templating
- Rate limiting per recipient
- Retry logic with exponential backoff
- Audit logging
- Delivery status tracking
"""

import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .sms_client import SMSClient, SMSResult

logger = logging.getLogger(__name__)


class SMSMessageType(str, Enum):
    """Types of SMS messages"""
    NOTIFICATION = "notification"
    REMINDER = "reminder"
    VERIFICATION = "verification"
    ALERT = "alert"
    CUSTOM = "custom"


@dataclass
class SMSMessage:
    """Represents an SMS message to be sent"""
    to: str
    message: str
    message_type: SMSMessageType = SMSMessageType.CUSTOM
    client_id: Optional[str] = None
    job_id: Optional[str] = None
    template_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SMSSender:
    """
    SMS Sender - High-level service for sending SMS messages.
    
    This is a stub class for Phase 0 scaffolding.
    Business logic will be added in Phase 1.
    
    Responsibilities:
    - Message validation
    - Rate limiting
    - Template rendering
    - Audit logging
    - Delivery tracking
    """
    
    def __init__(self, client: Optional[SMSClient] = None):
        """
        Initialize SMS sender.
        
        Args:
            client: SMSClient instance (creates default if not provided)
        """
        self.client = client or SMSClient()
        self._templates: Dict[str, str] = {}
    
    def is_ready(self) -> bool:
        """Check if sender is ready to send messages."""
        return self.client.is_configured()
    
    def send(self, message: SMSMessage) -> SMSResult:
        """
        Send an SMS message.
        
        Args:
            message: SMSMessage to send
            
        Returns:
            SMSResult: Result of the send operation
            
        Raises:
            NotImplementedError: Sending not implemented yet (Phase 0)
        """
        raise NotImplementedError(
            "SMS sending not implemented yet. "
            "This is Phase 0 scaffolding - Phase 1 will add sending logic."
        )
    
    def send_bulk(self, messages: List[SMSMessage]) -> List[SMSResult]:
        """
        Send multiple SMS messages.
        
        Args:
            messages: List of SMSMessage to send
            
        Returns:
            List of SMSResult for each message
            
        Raises:
            NotImplementedError: Bulk sending not implemented yet (Phase 0)
        """
        raise NotImplementedError(
            "Bulk SMS sending not implemented yet. "
            "This is Phase 0 scaffolding."
        )
    
    def send_from_template(
        self,
        to: str,
        template_id: str,
        variables: Dict[str, str],
        client_id: Optional[str] = None
    ) -> SMSResult:
        """
        Send SMS using a template.
        
        Args:
            to: Recipient phone number
            template_id: Template identifier
            variables: Template variables for substitution
            client_id: Optional client ID for tracking
            
        Returns:
            SMSResult: Result of the send operation
            
        Raises:
            NotImplementedError: Template sending not implemented yet (Phase 0)
        """
        raise NotImplementedError(
            "Template-based SMS sending not implemented yet. "
            "This is Phase 0 scaffolding."
        )
    
    def register_template(self, template_id: str, template: str) -> None:
        """
        Register a message template.
        
        Args:
            template_id: Unique template identifier
            template: Template string with {variable} placeholders
            
        Example:
            sender.register_template(
                'appointment_reminder',
                'Hi {name}, reminder: appointment on {date} at {time}'
            )
        """
        self._templates[template_id] = template
        logger.info(f"Registered SMS template: {template_id}")
    
    def get_template(self, template_id: str) -> Optional[str]:
        """Get a registered template by ID."""
        return self._templates.get(template_id)
    
    def render_template(self, template_id: str, variables: Dict[str, str]) -> Optional[str]:
        """
        Render a template with variables.
        
        Args:
            template_id: Template identifier
            variables: Variable values for substitution
            
        Returns:
            Rendered message string or None if template not found
        """
        template = self.get_template(template_id)
        if not template:
            return None
        
        try:
            return template.format(**variables)
        except KeyError as e:
            logger.error(f"Missing template variable: {e}")
            return None


# Pre-defined templates for common use cases
DEFAULT_TEMPLATES = {
    "appointment_reminder": (
        "Hi {client_name}, this is a reminder for your appointment "
        "on {date} at {time}. Reply CONFIRM to confirm or call us to reschedule."
    ),
    "document_request": (
        "Hi {client_name}, we need the following document: {document_name}. "
        "Please upload via your client portal or reply to this message."
    ),
    "payment_reminder": (
        "Hi {client_name}, friendly reminder that invoice #{invoice_number} "
        "for ${amount} is due on {due_date}. Thank you!"
    ),
    "tax_deadline": (
        "Hi {client_name}, your {tax_type} is due on {deadline}. "
        "Please contact us if you need assistance."
    ),
}
