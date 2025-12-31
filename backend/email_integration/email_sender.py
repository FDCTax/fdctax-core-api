"""
Email Sender - High-level Email Service

This module provides business logic for sending emails:
- Message templating with variable substitution
- Database logging for audit trail
- Error handling and retry logic
- Template validation
"""

import logging
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from .email_client import EmailClient, EmailResult, EmailMessage, EmailStatus, EmailAttachment

logger = logging.getLogger(__name__)


class EmailMessageType(str, Enum):
    """Types of email messages"""
    NOTIFICATION = "notification"
    REMINDER = "reminder"
    DOCUMENT = "document"
    INVOICE = "invoice"
    WELCOME = "welcome"
    VERIFICATION = "verification"
    MARKETING = "marketing"
    TEST = "test"
    CUSTOM = "custom"


class EmailSender:
    """
    Email Sender - High-level service for sending emails.
    
    Provides:
    - Template-based sending
    - Database logging
    - Variable validation
    - Error tracking
    """
    
    def __init__(self, client: Optional[EmailClient] = None, db: Optional[AsyncSession] = None):
        """
        Initialize email sender.
        
        Args:
            client: EmailClient instance (creates default if not provided)
            db: Database session for logging (optional)
        """
        self.client = client or EmailClient()
        self.db = db
        self._templates: Dict[str, Dict[str, str]] = {}
        
        # Register default templates
        self._register_default_templates()
    
    def is_ready(self) -> bool:
        """Check if sender is ready to send emails."""
        return self.client.is_ready()
    
    async def send(
        self,
        to: str,
        subject: str,
        body: str,
        from_address: Optional[str] = None,
        reply_to: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        html: bool = True,
        attachments: Optional[List[Dict[str, Any]]] = None,
        message_type: EmailMessageType = EmailMessageType.CUSTOM,
        client_id: Optional[str] = None,
        job_id: Optional[str] = None,
        template_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> EmailResult:
        """
        Send an email with logging.
        
        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (HTML by default)
            from_address: Optional sender override
            reply_to: Optional reply-to address
            cc: Optional CC recipients
            bcc: Optional BCC recipients
            html: Whether body is HTML (default True)
            attachments: Optional list of attachment dicts
            message_type: Type of message for tracking
            client_id: Optional client ID
            job_id: Optional job ID
            template_id: Optional template ID used
            metadata: Optional additional metadata
            
        Returns:
            EmailResult with send status
        """
        # Convert attachments if provided
        email_attachments = None
        if attachments:
            email_attachments = [
                EmailAttachment(
                    filename=att.get('filename', 'attachment'),
                    content=att.get('content', b''),
                    content_type=att.get('content_type', 'application/octet-stream')
                )
                for att in attachments
            ]
        
        # Create message
        message = EmailMessage(
            to=to,
            subject=subject,
            body=body,
            from_address=from_address,
            reply_to=reply_to,
            cc=cc,
            bcc=bcc,
            html=html,
            attachments=email_attachments,
            metadata=metadata,
            client_id=client_id,
            job_id=job_id,
            message_type=message_type.value if isinstance(message_type, EmailMessageType) else message_type,
            template_id=template_id
        )
        
        # Send email
        result = self.client.send_email(message)
        
        # Log to database if available
        if self.db:
            await self._log_email(message, result)
        
        return result
    
    async def send_from_template(
        self,
        to: str,
        template_id: str,
        variables: Dict[str, str],
        from_address: Optional[str] = None,
        client_id: Optional[str] = None,
        job_id: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> EmailResult:
        """
        Send email using a template.
        
        Args:
            to: Recipient email address
            template_id: Template identifier
            variables: Template variables for substitution
            from_address: Optional sender override
            client_id: Optional client ID
            job_id: Optional job ID
            attachments: Optional attachments
            
        Returns:
            EmailResult with send status
        """
        # Get template
        template = self.get_template(template_id)
        if not template:
            return EmailResult(
                success=False,
                error=f"Template '{template_id}' not found",
                status=EmailStatus.FAILED
            )
        
        # Render template
        rendered = self.render_template(template_id, variables)
        if not rendered:
            return EmailResult(
                success=False,
                error=f"Failed to render template '{template_id}' - missing variables",
                status=EmailStatus.FAILED
            )
        
        # Send email
        return await self.send(
            to=to,
            subject=rendered['subject'],
            body=rendered['body'],
            from_address=from_address,
            template_id=template_id,
            client_id=client_id,
            job_id=job_id,
            attachments=attachments,
            message_type=EmailMessageType.NOTIFICATION
        )
    
    def validate_template_variables(
        self,
        template_id: str,
        variables: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Validate that all required template variables are provided.
        
        Args:
            template_id: Template identifier
            variables: Provided variables
            
        Returns:
            Validation result dict
        """
        template = self.get_template(template_id)
        if not template:
            return {
                "valid": False,
                "error": f"Template '{template_id}' not found",
                "missing_variables": []
            }
        
        # Find variables in template
        import re
        subject_vars = set(re.findall(r'\{(\w+)\}', template['subject']))
        body_vars = set(re.findall(r'\{(\w+)\}', template['body']))
        required_vars = subject_vars.union(body_vars)
        
        # Check which are missing
        provided_vars = set(variables.keys())
        missing = required_vars - provided_vars
        
        return {
            "valid": len(missing) == 0,
            "template_id": template_id,
            "required_variables": list(required_vars),
            "provided_variables": list(provided_vars),
            "missing_variables": list(missing)
        }
    
    def register_template(
        self,
        template_id: str,
        subject: str,
        body: str
    ) -> None:
        """
        Register an email template.
        
        Args:
            template_id: Unique template identifier
            subject: Subject template with {variable} placeholders
            body: Body template with {variable} placeholders
        """
        self._templates[template_id] = {
            'subject': subject,
            'body': body
        }
        logger.info(f"Registered email template: {template_id}")
    
    def get_template(self, template_id: str) -> Optional[Dict[str, str]]:
        """Get a registered template by ID."""
        return self._templates.get(template_id)
    
    def list_templates(self) -> List[str]:
        """List all registered template IDs."""
        return list(self._templates.keys())
    
    def render_template(
        self,
        template_id: str,
        variables: Dict[str, str]
    ) -> Optional[Dict[str, str]]:
        """
        Render a template with variables.
        
        Args:
            template_id: Template identifier
            variables: Variable values for substitution
            
        Returns:
            Dict with rendered 'subject' and 'body' or None if failed
        """
        template = self.get_template(template_id)
        if not template:
            return None
        
        try:
            return {
                'subject': template['subject'].format(**variables),
                'body': template['body'].format(**variables)
            }
        except KeyError as e:
            logger.error(f"Missing template variable: {e}")
            return None
    
    async def _log_email(self, message: EmailMessage, result: EmailResult) -> None:
        """Log email to database."""
        try:
            query = text("""
                INSERT INTO email_logs (
                    message_id, provider_message_id, to_address, from_address,
                    reply_to, cc, bcc, subject, body_html, provider, status,
                    error_message, client_id, job_id, message_type, template_id,
                    metadata, sent_at, created_at
                ) VALUES (
                    :message_id, :provider_message_id, :to_address, :from_address,
                    :reply_to, :cc, :bcc, :subject, :body_html, :provider, :status,
                    :error_message, :client_id, :job_id, :message_type, :template_id,
                    :metadata, :sent_at, NOW()
                )
            """)
            
            import json
            await self.db.execute(query, {
                "message_id": result.message_id,
                "provider_message_id": result.provider_message_id,
                "to_address": message.to,
                "from_address": message.from_address or self.client.from_address,
                "reply_to": message.reply_to,
                "cc": ",".join(message.cc) if message.cc else None,
                "bcc": ",".join(message.bcc) if message.bcc else None,
                "subject": message.subject,
                "body_html": message.body,
                "provider": self.client.provider,
                "status": result.status.value,
                "error_message": result.error,
                "client_id": message.client_id,
                "job_id": message.job_id,
                "message_type": message.message_type,
                "template_id": message.template_id,
                "metadata": json.dumps(message.metadata) if message.metadata else None,
                "sent_at": datetime.now(timezone.utc) if result.success else None
            })
            await self.db.commit()
            logger.info(f"Email logged to database: {result.message_id}")
        except Exception as e:
            logger.error(f"Failed to log email to database: {e}")
            # Don't fail the send if logging fails
    
    def _register_default_templates(self) -> None:
        """Register default email templates."""
        
        self.register_template(
            "appointment_reminder",
            "Reminder: Your appointment on {date}",
            """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #333;">Appointment Reminder</h2>
                <p>Hi {client_name},</p>
                <p>This is a friendly reminder that you have an appointment scheduled:</p>
                <div style="background: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <p style="margin: 5px 0;"><strong>Date:</strong> {date}</p>
                    <p style="margin: 5px 0;"><strong>Time:</strong> {time}</p>
                    <p style="margin: 5px 0;"><strong>Location:</strong> {location}</p>
                </div>
                <p>If you need to reschedule, please contact us as soon as possible.</p>
                <p>Best regards,<br><strong>FDC Tax Team</strong></p>
            </div>
            """
        )
        
        self.register_template(
            "document_request",
            "Document Required: {document_name}",
            """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #333;">Document Request</h2>
                <p>Hi {client_name},</p>
                <p>We require the following document to continue processing your tax return:</p>
                <div style="background: #fff3cd; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #ffc107;">
                    <p style="margin: 0; font-weight: bold;">{document_name}</p>
                </div>
                <p>Please upload this document via your client portal or reply to this email with the document attached.</p>
                <p>Best regards,<br><strong>FDC Tax Team</strong></p>
            </div>
            """
        )
        
        self.register_template(
            "tax_return_ready",
            "Your {tax_year} Tax Return is Ready",
            """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #333;">Tax Return Complete</h2>
                <p>Hi {client_name},</p>
                <p>Great news! Your {tax_year} tax return has been completed and is ready for your review.</p>
                <div style="background: #d4edda; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #28a745;">
                    <p style="margin: 0;"><strong>Amount:</strong> {amount}</p>
                </div>
                <p>Please log in to your client portal to review and sign off on your return.</p>
                <p>Best regards,<br><strong>FDC Tax Team</strong></p>
            </div>
            """
        )
        
        self.register_template(
            "invoice",
            "Invoice #{invoice_number} from FDC Tax",
            """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #333;">Invoice</h2>
                <p>Hi {client_name},</p>
                <p>Please find below your invoice details:</p>
                <div style="background: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <p style="margin: 5px 0;"><strong>Invoice #:</strong> {invoice_number}</p>
                    <p style="margin: 5px 0;"><strong>Amount Due:</strong> ${amount}</p>
                    <p style="margin: 5px 0;"><strong>Due Date:</strong> {due_date}</p>
                </div>
                <p>Payment can be made via bank transfer or credit card through your client portal.</p>
                <p>Best regards,<br><strong>FDC Tax Team</strong></p>
            </div>
            """
        )
        
        self.register_template(
            "welcome",
            "Welcome to FDC Tax, {client_name}!",
            """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #333;">Welcome to FDC Tax!</h2>
                <p>Hi {client_name},</p>
                <p>Thank you for choosing FDC Tax for your accounting needs. We're excited to have you on board!</p>
                <p>Your account has been created and you can now access your client portal:</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{portal_url}" style="background: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">Access Your Portal</a>
                </div>
                <p>If you have any questions, feel free to reach out to us.</p>
                <p>Best regards,<br><strong>FDC Tax Team</strong></p>
            </div>
            """
        )
        
        self.register_template(
            "test",
            "Test Email from FDC Tax",
            """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #333;">Test Email</h2>
                <p>This is a test email from the FDC Tax email system.</p>
                <div style="background: #e7f3ff; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <p style="margin: 0;">If you received this email, the email integration is working correctly!</p>
                </div>
                <p>Sent at: {timestamp}</p>
            </div>
            """
        )
        
        logger.info(f"Registered {len(self._templates)} default email templates")
