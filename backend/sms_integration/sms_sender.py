"""
SMS Sender - High-level SMS sending service

This module provides business logic for sending SMS messages,
including templating, validation, and logging.

Features:
- Message templating with variable substitution
- Phone number validation and normalization
- Audit logging (when database available)
- Pre-defined templates for common use cases
"""

import logging
import uuid
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
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
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class SendResult:
    """Result of a send operation with additional context"""
    success: bool
    message_id: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[int] = None
    sent_at: Optional[datetime] = None
    recipient: Optional[str] = None
    message_preview: Optional[str] = None


class SMSSender:
    """
    SMS Sender - High-level service for sending SMS messages.
    
    Responsibilities:
    - Message validation
    - Template rendering
    - Phone number normalization
    - Sending via SMSClient
    
    Usage:
        sender = SMSSender()
        if sender.is_ready():
            result = await sender.send(SMSMessage(
                to='+61400123456',
                message='Hello!'
            ))
    """
    
    def __init__(self, client: Optional[SMSClient] = None):
        """
        Initialize SMS sender.
        
        Args:
            client: SMSClient instance (creates default if not provided)
        """
        self.client = client or SMSClient()
        self._templates: Dict[str, str] = {}
        
        # Register default templates
        for template_id, template in DEFAULT_TEMPLATES.items():
            self.register_template(template_id, template)
    
    def is_ready(self) -> bool:
        """Check if sender is ready to send messages."""
        return self.client.is_configured()
    
    async def send(self, message: SMSMessage) -> SendResult:
        """
        Send an SMS message.
        
        Args:
            message: SMSMessage to send
            
        Returns:
            SendResult: Result of the send operation
        """
        if not self.is_ready():
            return SendResult(
                success=False,
                error="SMS service not configured. Check environment variables.",
                error_code=503
            )
        
        # Normalize phone number
        normalized_to = self.client.normalize_phone_number(message.to)
        
        # Validate
        if not self.client.validate_phone_number(normalized_to):
            return SendResult(
                success=False,
                error=f"Invalid phone number: {message.to}",
                error_code=400,
                recipient=message.to
            )
        
        if not message.message or not message.message.strip():
            return SendResult(
                success=False,
                error="Message cannot be empty",
                error_code=400
            )
        
        # Send via client
        logger.info(f"Sending SMS to {normalized_to[:6]}*** ({message.message_type.value})")
        
        result = await self.client.send_sms(
            to=normalized_to,
            message=message.message
        )
        
        # Build send result
        send_result = SendResult(
            success=result.success,
            message_id=result.message_id,
            status=result.status,
            error=result.error,
            error_code=result.error_code,
            sent_at=result.sent_at,
            recipient=normalized_to,
            message_preview=message.message[:50] + "..." if len(message.message) > 50 else message.message
        )
        
        if result.success:
            logger.info(f"SMS sent: {result.message_id} to {normalized_to[:6]}***")
        else:
            logger.error(f"SMS failed: {result.error}")
        
        return send_result
    
    async def send_bulk(self, messages: List[SMSMessage]) -> List[SendResult]:
        """
        Send multiple SMS messages.
        
        Args:
            messages: List of SMSMessage to send
            
        Returns:
            List of SendResult for each message
        """
        results = []
        for msg in messages:
            result = await self.send(msg)
            results.append(result)
        return results
    
    async def send_from_template(
        self,
        to: str,
        template_id: str,
        variables: Dict[str, str],
        client_id: Optional[str] = None,
        message_type: SMSMessageType = SMSMessageType.NOTIFICATION
    ) -> SendResult:
        """
        Send SMS using a template.
        
        Args:
            to: Recipient phone number
            template_id: Template identifier
            variables: Template variables for substitution
            client_id: Optional client ID for tracking
            message_type: Type of message
            
        Returns:
            SendResult: Result of the send operation
        """
        # Render template
        rendered = self.render_template(template_id, variables)
        
        if not rendered:
            return SendResult(
                success=False,
                error=f"Template not found or rendering failed: {template_id}",
                error_code=400
            )
        
        # Create message and send
        message = SMSMessage(
            to=to,
            message=rendered,
            message_type=message_type,
            client_id=client_id,
            template_id=template_id,
            metadata={"variables": variables}
        )
        
        return await self.send(message)
    
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
        logger.debug(f"Registered SMS template: {template_id}")
    
    def get_template(self, template_id: str) -> Optional[str]:
        """Get a registered template by ID."""
        return self._templates.get(template_id)
    
    def list_templates(self) -> Dict[str, str]:
        """List all registered templates."""
        return dict(self._templates)
    
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
            logger.warning(f"Template not found: {template_id}")
            return None
        
        try:
            return template.format(**variables)
        except KeyError as e:
            logger.error(f"Missing template variable: {e}")
            return None
        except Exception as e:
            logger.error(f"Template rendering error: {e}")
            return None
    
    async def get_message_status(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the status of a sent message.
        
        Args:
            message_id: Provider message ID
            
        Returns:
            Message status dict or None
        """
        return await self.client.get_message_status(message_id)


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
    "bas_ready": (
        "Hi {client_name}, your BAS for {period} is ready for review. "
        "Please log in to your portal to approve or contact us with questions."
    ),
    "bas_approved": (
        "Hi {client_name}, thank you for approving your {period} BAS. "
        "We will lodge it with the ATO shortly."
    ),
    "bas_lodged": (
        "Hi {client_name}, your {period} BAS has been lodged with the ATO. "
        "Amount payable: ${amount}. Due date: {due_date}."
    ),
    "welcome": (
        "Welcome to FDC Tax, {client_name}! We're here to help with all your "
        "tax and accounting needs. Reply HELP for assistance."
    ),
    "verification_code": (
        "Your FDC Tax verification code is: {code}. "
        "This code expires in 10 minutes. Do not share it with anyone."
    ),
}
