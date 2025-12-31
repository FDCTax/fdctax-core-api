"""
Email Sender - High-level Email Service

This module provides business logic for sending emails:
- Message templating with variable substitution
- Template rendering via TemplateEngine
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
from .template_engine import TemplateEngine, get_template_engine, TEMPLATE_VARIABLES

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
    - Template-based sending with rendering engine
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
        self._engine = get_template_engine()
        
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
        variables: Dict[str, Any],
        from_address: Optional[str] = None,
        client_id: Optional[str] = None,
        job_id: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        strict: bool = True
    ) -> EmailResult:
        """
        Send email using a template with the rendering engine.
        
        Args:
            to: Recipient email address
            template_id: Template identifier
            variables: Template variables for substitution
            from_address: Optional sender override
            client_id: Optional client ID
            job_id: Optional job ID
            attachments: Optional attachments
            strict: If True, fail on missing required variables
            
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
        
        # Render template using engine
        render_result = self._engine.render_with_subject(
            subject_template=template['subject'],
            body_template=template['body'],
            variables=variables,
            strict=strict
        )
        
        if not render_result.success:
            return EmailResult(
                success=False,
                error=render_result.error or "Template rendering failed",
                status=EmailStatus.FAILED
            )
        
        # Send email with rendered content
        return await self.send(
            to=to,
            subject=render_result.subject or template['subject'],
            body=render_result.html or template['body'],
            from_address=from_address,
            template_id=template_id,
            client_id=client_id,
            job_id=job_id,
            attachments=attachments,
            message_type=EmailMessageType.NOTIFICATION
        )
    
    def render_template(
        self,
        template_id: str,
        variables: Dict[str, Any],
        strict: bool = False
    ) -> Dict[str, Any]:
        """
        Render a template without sending.
        
        Args:
            template_id: Template identifier
            variables: Template variables
            strict: If True, fail on missing required variables
            
        Returns:
            Dict with rendered subject, html, and validation info
        """
        template = self.get_template(template_id)
        if not template:
            return {
                "success": False,
                "error": f"Template '{template_id}' not found"
            }
        
        result = self._engine.render_with_subject(
            subject_template=template['subject'],
            body_template=template['body'],
            variables=variables,
            strict=strict
        )
        
        return result.to_dict()
    
    def render_custom_template(
        self,
        subject_template: str,
        body_template: str,
        variables: Dict[str, Any],
        strict: bool = False
    ) -> Dict[str, Any]:
        """
        Render a custom template (not from registry).
        
        Args:
            subject_template: Subject line template
            body_template: HTML body template
            variables: Template variables
            strict: If True, fail on missing required variables
            
        Returns:
            Dict with rendered subject, html, and validation info
        """
        result = self._engine.render_with_subject(
            subject_template=subject_template,
            body_template=body_template,
            variables=variables,
            strict=strict
        )
        
        return result.to_dict()
    
    def validate_template_variables(
        self,
        template_id: str,
        variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate that all required template variables are provided.
        
        Args:
            template_id: Template identifier
            variables: Provided variables
            
        Returns:
            Validation result dict with missing, unused, invalid
        """
        template = self.get_template(template_id)
        if not template:
            return {
                "valid": False,
                "error": f"Template '{template_id}' not found",
                "missing": [],
                "unused": [],
                "invalid": []
            }
        
        # Combine subject and body for validation
        combined = template['subject'] + " " + template['body']
        
        # Use template engine for validation
        validation = self._engine.validate_variables(combined, variables)
        
        return {
            "valid": validation.valid,
            "template_id": template_id,
            "required_variables": self._extract_required_vars(template_id),
            "provided_variables": list(variables.keys()),
            "missing": validation.missing,
            "unused": validation.unused,
            "invalid": validation.invalid,
            "errors": validation.errors
        }
    
    def validate_custom_template(
        self,
        template_html: str,
        variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate variables for a custom template.
        
        Args:
            template_html: HTML template with placeholders
            variables: Provided variables
            
        Returns:
            Validation result dict
        """
        validation = self._engine.validate_variables(template_html, variables)
        
        return {
            "valid": validation.valid,
            "placeholders_found": self._engine.extract_placeholders(template_html),
            "provided_variables": list(variables.keys()),
            "missing": validation.missing,
            "unused": validation.unused,
            "invalid": validation.invalid,
            "errors": validation.errors
        }
    
    def _extract_required_vars(self, template_id: str) -> List[str]:
        """Extract required variable names from template registry."""
        info = TEMPLATE_VARIABLES.get(template_id)
        if info:
            return info.get("required", [])
        
        # Fallback: extract from template
        template = self.get_template(template_id)
        if template:
            combined = template['subject'] + " " + template['body']
            return self._engine.extract_placeholders(combined)
        
        return []
    
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
            subject: Subject template with {{variable}} placeholders
            body: Body template with {{variable}} placeholders
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
    
    def get_template_info(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed info about a template including required variables."""
        template = self.get_template(template_id)
        if not template:
            return None
        
        # Get registry info
        registry_info = TEMPLATE_VARIABLES.get(template_id, {})
        
        # Extract placeholders from actual template
        combined = template['subject'] + " " + template['body']
        placeholders = self._engine.extract_placeholders(combined)
        
        return {
            "id": template_id,
            "subject": template['subject'],
            "body": template['body'],
            "required_variables": registry_info.get("required", placeholders),
            "optional_variables": registry_info.get("optional", []),
            "description": registry_info.get("description", ""),
            "placeholders": placeholders
        }
    
    def get_all_templates_info(self) -> List[Dict[str, Any]]:
        """Get info for all registered templates."""
        return [
            self.get_template_info(tid)
            for tid in self.list_templates()
            if self.get_template_info(tid)
        ]
    
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
        """Register default email templates with {{variable}} syntax."""
        
        self.register_template(
            "appointment_reminder",
            "Reminder: Your appointment on {{date}}",
            """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #333;">Appointment Reminder</h2>
                <p>Hi {{client_name}},</p>
                <p>This is a friendly reminder that you have an appointment scheduled:</p>
                <div style="background: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <p style="margin: 5px 0;"><strong>Date:</strong> {{date}}</p>
                    <p style="margin: 5px 0;"><strong>Time:</strong> {{time}}</p>
                    <p style="margin: 5px 0;"><strong>Location:</strong> {{location}}</p>
                </div>
                <p>If you need to reschedule, please contact us as soon as possible.</p>
                <p>Best regards,<br><strong>FDC Tax Team</strong></p>
            </div>
            """
        )
        
        self.register_template(
            "document_request",
            "Document Required: {{document_name}}",
            """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #333;">Document Request</h2>
                <p>Hi {{client_name}},</p>
                <p>We require the following document to continue processing your tax return:</p>
                <div style="background: #fff3cd; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #ffc107;">
                    <p style="margin: 0; font-weight: bold;">{{document_name}}</p>
                </div>
                <p>Please upload this document via your client portal or reply to this email with the document attached.</p>
                <p>Best regards,<br><strong>FDC Tax Team</strong></p>
            </div>
            """
        )
        
        self.register_template(
            "tax_return_ready",
            "Your {{tax_year}} Tax Return is Ready",
            """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #333;">Tax Return Complete</h2>
                <p>Hi {{client_name}},</p>
                <p>Great news! Your {{tax_year}} tax return has been completed and is ready for your review.</p>
                <div style="background: #d4edda; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #28a745;">
                    <p style="margin: 0;"><strong>Amount:</strong> {{amount}}</p>
                </div>
                <p>Please log in to your client portal to review and sign off on your return.</p>
                <p>Best regards,<br><strong>FDC Tax Team</strong></p>
            </div>
            """
        )
        
        self.register_template(
            "invoice",
            "Invoice #{{invoice_number}} from FDC Tax",
            """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #333;">Invoice</h2>
                <p>Hi {{client_name}},</p>
                <p>Please find below your invoice details:</p>
                <div style="background: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <p style="margin: 5px 0;"><strong>Invoice #:</strong> {{invoice_number}}</p>
                    <p style="margin: 5px 0;"><strong>Amount Due:</strong> ${{amount}}</p>
                    <p style="margin: 5px 0;"><strong>Due Date:</strong> {{due_date}}</p>
                </div>
                <p>Payment can be made via bank transfer or credit card through your client portal.</p>
                <p>Best regards,<br><strong>FDC Tax Team</strong></p>
            </div>
            """
        )
        
        self.register_template(
            "welcome",
            "Welcome to FDC Tax, {{client_name}}!",
            """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #333;">Welcome to FDC Tax!</h2>
                <p>Hi {{client_name}},</p>
                <p>Thank you for choosing FDC Tax for your accounting needs. We're excited to have you on board!</p>
                <p>Your account has been created and you can now access your client portal:</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{portal_url}}" style="background: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">Access Your Portal</a>
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
                <p>Sent at: {{timestamp}}</p>
            </div>
            """
        )
        
        self.register_template(
            "bas_reminder",
            "BAS Reminder: {{period}} Due {{due_date}}",
            """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #333;">BAS Lodgement Reminder</h2>
                <p>Hi {{client_name}},</p>
                <p>This is a reminder that your BAS for <strong>{{period}}</strong> is due on <strong>{{due_date}}</strong>.</p>
                <div style="background: #fff3cd; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #ffc107;">
                    <p style="margin: 0;">Please ensure all transactions are up to date so we can prepare your BAS.</p>
                </div>
                <p>If you have any questions, please don't hesitate to contact us.</p>
                <p>Best regards,<br><strong>FDC Tax Team</strong></p>
            </div>
            """
        )
        
        self.register_template(
            "payment_receipt",
            "Payment Receipt #{{receipt_number}}",
            """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #333;">Payment Receipt</h2>
                <p>Hi {{client_name}},</p>
                <p>Thank you for your payment. Here are your receipt details:</p>
                <div style="background: #d4edda; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #28a745;">
                    <p style="margin: 5px 0;"><strong>Receipt #:</strong> {{receipt_number}}</p>
                    <p style="margin: 5px 0;"><strong>Amount:</strong> ${{amount}}</p>
                    <p style="margin: 5px 0;"><strong>Date:</strong> {{payment_date}}</p>
                </div>
                <p>Best regards,<br><strong>FDC Tax Team</strong></p>
            </div>
            """
        )
        
        logger.info(f"Registered {len(self._templates)} default email templates")
