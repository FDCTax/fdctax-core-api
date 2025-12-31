"""
Email Client - Resend Provider Implementation

This module provides email sending via the Resend API.
Implements the EmailClient interface with full Resend SDK integration.

Resend API Reference:
- Endpoint: POST https://api.resend.com/emails
- Auth: Bearer token in Authorization header
- Response: { id: "message_id" }
"""

import os
import logging
import uuid
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

import resend

logger = logging.getLogger(__name__)


class EmailProvider(str, Enum):
    """Supported email providers"""
    RESEND = "resend"
    SENDGRID = "sendgrid"
    SES = "ses"
    SMTP = "smtp"


class EmailStatus(str, Enum):
    """Email delivery status"""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"


@dataclass
class EmailResult:
    """Result of an email operation"""
    success: bool
    message_id: Optional[str] = None
    provider_message_id: Optional[str] = None
    error: Optional[str] = None
    status: EmailStatus = EmailStatus.PENDING
    provider_response: Optional[Dict[str, Any]] = None


@dataclass
class EmailAttachment:
    """Email attachment"""
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


@dataclass
class EmailMessage:
    """Represents an email message to send"""
    to: str
    subject: str
    body: str
    from_address: Optional[str] = None
    reply_to: Optional[str] = None
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None
    html: bool = True
    attachments: Optional[List[EmailAttachment]] = None
    metadata: Optional[Dict[str, Any]] = None
    client_id: Optional[str] = None
    job_id: Optional[str] = None
    message_type: Optional[str] = None
    template_id: Optional[str] = None


class EmailClient:
    """
    Email Client - Resend Provider Implementation.
    
    Provides email sending via the Resend API with:
    - Full SDK integration
    - Error handling and logging
    - Attachment support
    - Metadata tracking
    
    Usage:
        client = EmailClient()
        result = client.send_email(EmailMessage(
            to="user@example.com",
            subject="Hello",
            body="<p>Welcome!</p>"
        ))
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        from_address: Optional[str] = None,
        provider: str = "resend"
    ):
        """
        Initialize email client.
        
        Args:
            api_key: Resend API key (from EMAIL_API_KEY env var)
            from_address: Default sender address (from EMAIL_FROM_ADDRESS env var)
            provider: Email provider name (from EMAIL_PROVIDER env var)
        """
        self.api_key = api_key or os.environ.get('EMAIL_API_KEY', '')
        self.from_address = from_address or os.environ.get('EMAIL_FROM_ADDRESS', '')
        self.provider = provider or os.environ.get('EMAIL_PROVIDER', 'resend')
        
        self._initialized = False
        
        # Initialize Resend if configured
        if self.api_key:
            resend.api_key = self.api_key
            self._initialized = True
            logger.info(f"Email client initialized (provider: {self.provider})")
        else:
            logger.warning("Email client not initialized - EMAIL_API_KEY not set")
    
    def is_configured(self) -> bool:
        """Check if email client is properly configured."""
        return bool(self.api_key and self.from_address)
    
    def is_ready(self) -> bool:
        """Check if client is ready to send emails."""
        return self._initialized and self.is_configured()
    
    def send_email(self, message: EmailMessage) -> EmailResult:
        """
        Send an email via Resend.
        
        Args:
            message: EmailMessage to send
            
        Returns:
            EmailResult with send status
        """
        if not self.is_ready():
            return EmailResult(
                success=False,
                error="Email client not configured. Check EMAIL_API_KEY and EMAIL_FROM_ADDRESS.",
                status=EmailStatus.FAILED
            )
        
        # Generate internal message ID
        internal_id = str(uuid.uuid4())
        
        # Prepare sender address
        sender = message.from_address or self.from_address
        
        try:
            # Build Resend params
            params: Dict[str, Any] = {
                "from": sender,
                "to": [message.to] if isinstance(message.to, str) else message.to,
                "subject": message.subject,
            }
            
            # Add body (HTML or text)
            if message.html:
                params["html"] = message.body
            else:
                params["text"] = message.body
            
            # Optional fields
            if message.reply_to:
                params["reply_to"] = [message.reply_to]
            
            if message.cc:
                params["cc"] = message.cc
            
            if message.bcc:
                params["bcc"] = message.bcc
            
            # Attachments
            if message.attachments:
                params["attachments"] = [
                    {
                        "filename": att.filename,
                        "content": att.content,
                        "content_type": att.content_type
                    }
                    for att in message.attachments
                ]
            
            # Headers/tags for tracking
            if message.metadata:
                params["headers"] = {
                    "X-FDC-Message-ID": internal_id,
                    "X-FDC-Client-ID": message.client_id or "",
                    "X-FDC-Message-Type": message.message_type or "custom"
                }
            
            # Send via Resend SDK
            logger.info(f"Sending email to {message.to} via Resend")
            response = resend.Emails.send(params)
            
            # Extract provider message ID
            provider_msg_id = None
            if isinstance(response, dict):
                provider_msg_id = response.get("id")
            elif hasattr(response, "id"):
                provider_msg_id = response.id
            
            logger.info(f"Email sent successfully: {provider_msg_id}")
            
            return EmailResult(
                success=True,
                message_id=internal_id,
                provider_message_id=provider_msg_id,
                status=EmailStatus.SENT,
                provider_response=response if isinstance(response, dict) else {"id": provider_msg_id}
            )
            
        except resend.exceptions.ResendError as e:
            error_msg = str(e)
            logger.error(f"Resend API error: {error_msg}")
            return EmailResult(
                success=False,
                message_id=internal_id,
                error=error_msg,
                status=EmailStatus.FAILED
            )
        except Exception as e:
            error_msg = f"Unexpected error sending email: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return EmailResult(
                success=False,
                message_id=internal_id,
                error=error_msg,
                status=EmailStatus.FAILED
            )
    
    def send_batch(self, messages: List[EmailMessage]) -> List[EmailResult]:
        """
        Send multiple emails.
        
        Args:
            messages: List of EmailMessage to send
            
        Returns:
            List of EmailResult for each message
        """
        results = []
        for message in messages:
            result = self.send_email(message)
            results.append(result)
        return results
    
    def validate_email_address(self, email: str) -> bool:
        """
        Validate an email address format.
        
        Args:
            email: Email address to validate
            
        Returns:
            bool: True if valid format
        """
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email.strip()))
    
    def get_status(self) -> Dict[str, Any]:
        """Get client configuration status."""
        return {
            "provider": self.provider,
            "configured": self.is_configured(),
            "ready": self.is_ready(),
            "from_address": self.from_address or "Not set",
            "api_key_set": bool(self.api_key)
        }
