"""
Email Integration - API Router

Provides REST API endpoints for email functionality:
- POST /api/email/send - Send email via Resend
- GET /api/email/status - Get module status
- POST /api/email/validate - Validate email/template
- GET /api/email/templates - List available templates
- POST /api/email/send-test - Send test email

Permissions:
- send: admin, staff, tax_agent
- status: public
- validate: admin, staff, tax_agent
- templates: admin, staff, tax_agent
"""

import os
import logging
import re
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, field_validator

from database import get_db
from middleware.auth import RoleChecker, AuthUser

from .email_client import EmailClient, EmailStatus
from .email_sender import EmailSender, EmailMessageType

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/email", tags=["Email Integration"])

# Permission checkers
require_email_access = RoleChecker(["admin", "staff", "tax_agent"])

# Shared client instance
_email_client: Optional[EmailClient] = None


def get_email_client() -> EmailClient:
    """Get or create email client singleton."""
    global _email_client
    if _email_client is None:
        _email_client = EmailClient()
    return _email_client


# ==================== REQUEST/RESPONSE MODELS ====================

class SendEmailRequest(BaseModel):
    """Request model for sending email"""
    to: str = Field(..., description="Recipient email address")
    subject: str = Field(..., description="Email subject", max_length=500)
    body: str = Field(..., description="Email body (HTML)")
    reply_to: Optional[str] = Field(None, description="Reply-to address")
    cc: Optional[List[str]] = Field(None, description="CC recipients")
    bcc: Optional[List[str]] = Field(None, description="BCC recipients")
    client_id: Optional[str] = Field(None, description="Client ID for tracking")
    job_id: Optional[str] = Field(None, description="Job ID for tracking")
    template_id: Optional[str] = Field(None, description="Template ID (for logging)")
    message_type: Optional[str] = Field("custom", description="Message type")
    
    @field_validator('to')
    @classmethod
    def validate_email(cls, v):
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, v.strip()):
            raise ValueError('Invalid email address format')
        return v.strip()


class SendEmailResponse(BaseModel):
    """Response model for email send operation"""
    success: bool
    status: str
    message_id: Optional[str] = None
    provider_message_id: Optional[str] = None
    error: Optional[str] = None


class SendTemplateRequest(BaseModel):
    """Request model for sending email from template"""
    to: str = Field(..., description="Recipient email address")
    template_id: str = Field(..., description="Template ID")
    variables: dict = Field(..., description="Template variables")
    client_id: Optional[str] = Field(None, description="Client ID for tracking")
    job_id: Optional[str] = Field(None, description="Job ID for tracking")
    
    @field_validator('to')
    @classmethod
    def validate_email(cls, v):
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, v.strip()):
            raise ValueError('Invalid email address format')
        return v.strip()


class ValidateEmailRequest(BaseModel):
    """Request model for email validation"""
    email: Optional[str] = Field(None, description="Email address to validate")
    template_id: Optional[str] = Field(None, description="Template ID to validate")
    variables: Optional[dict] = Field(None, description="Template variables to validate")


class ValidateEmailResponse(BaseModel):
    """Response model for email validation"""
    valid: bool
    email_valid: Optional[bool] = None
    template_valid: Optional[bool] = None
    missing_variables: Optional[List[str]] = None
    error: Optional[str] = None


class TemplateInfo(BaseModel):
    """Template information"""
    id: str
    subject_preview: str
    required_variables: List[str]


# ==================== ENDPOINTS ====================

@router.get("/status")
async def get_email_status():
    """
    Get email module status.
    
    Returns module version, configuration status, and feature availability.
    No authentication required.
    """
    client = get_email_client()
    status_info = client.get_status()
    
    # Get feature flag
    feature_flag = os.environ.get('EMAIL_FEATURE_FLAG', 'true').lower() == 'true'
    
    return {
        "status": "ok" if client.is_ready() else "not_ready",
        "module": "email",
        "version": "1.0.0",
        "features": {
            "send_email": client.is_ready(),
            "templates": True,
            "bulk_send": False,       # Future
            "scheduling": False,      # Future
            "tracking": False         # Future
        },
        "configuration": {
            "provider": status_info["provider"],
            "api_key": "✓ Set" if status_info["api_key_set"] else "✗ Not set",
            "from_address": status_info["from_address"] if status_info["from_address"] != "Not set" else "✗ Not set",
            "feature_flag": feature_flag
        },
        "ready_to_send": client.is_ready()
    }


@router.post("/send", response_model=SendEmailResponse)
async def send_email(
    request: SendEmailRequest,
    current_user: AuthUser = Depends(require_email_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Send an email via Resend.
    
    **Permissions:** admin, staff, tax_agent
    
    **Request Body:**
    - `to`: Recipient email address
    - `subject`: Email subject (max 500 chars)
    - `body`: Email body (HTML)
    - `reply_to`: Optional reply-to address
    - `cc`: Optional CC recipients
    - `bcc`: Optional BCC recipients
    - `client_id`: Optional client ID for tracking
    - `job_id`: Optional job ID for tracking
    - `template_id`: Optional template ID (for logging)
    - `message_type`: Type of message (notification, reminder, etc.)
    
    **Response:**
    - `success`: Whether email was sent
    - `message_id`: Internal message ID
    - `provider_message_id`: Resend message ID
    - `error`: Error message if failed
    """
    client = get_email_client()
    sender = EmailSender(client=client, db=db)
    
    logger.info(f"Email send request from {current_user.email} to {request.to}")
    
    # Determine message type
    msg_type = EmailMessageType.CUSTOM
    if request.message_type:
        try:
            msg_type = EmailMessageType(request.message_type)
        except ValueError:
            msg_type = EmailMessageType.CUSTOM
    
    # Send email
    result = await sender.send(
        to=request.to,
        subject=request.subject,
        body=request.body,
        reply_to=request.reply_to,
        cc=request.cc,
        bcc=request.bcc,
        client_id=request.client_id,
        job_id=request.job_id,
        template_id=request.template_id,
        message_type=msg_type
    )
    
    return SendEmailResponse(
        success=result.success,
        status=result.status.value,
        message_id=result.message_id,
        provider_message_id=result.provider_message_id,
        error=result.error
    )


@router.post("/send-template", response_model=SendEmailResponse)
async def send_template_email(
    request: SendTemplateRequest,
    current_user: AuthUser = Depends(require_email_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Send an email using a template.
    
    **Permissions:** admin, staff, tax_agent
    
    **Request Body:**
    - `to`: Recipient email address
    - `template_id`: Template identifier
    - `variables`: Template variables for substitution
    - `client_id`: Optional client ID for tracking
    - `job_id`: Optional job ID for tracking
    
    **Available Templates:**
    - `appointment_reminder`: {client_name, date, time, location}
    - `document_request`: {client_name, document_name}
    - `tax_return_ready`: {client_name, tax_year, amount}
    - `invoice`: {client_name, invoice_number, amount, due_date}
    - `welcome`: {client_name, portal_url}
    - `test`: {timestamp}
    """
    client = get_email_client()
    sender = EmailSender(client=client, db=db)
    
    logger.info(f"Template email request from {current_user.email} to {request.to} using template {request.template_id}")
    
    # Send from template
    result = await sender.send_from_template(
        to=request.to,
        template_id=request.template_id,
        variables=request.variables,
        client_id=request.client_id,
        job_id=request.job_id
    )
    
    return SendEmailResponse(
        success=result.success,
        status=result.status.value,
        message_id=result.message_id,
        provider_message_id=result.provider_message_id,
        error=result.error
    )


@router.post("/send-test", response_model=SendEmailResponse)
async def send_test_email(
    to: str = "test@example.com",
    current_user: AuthUser = Depends(require_email_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Send a test email to verify configuration.
    
    **Permissions:** admin, staff, tax_agent
    
    **Query Params:**
    - `to`: Recipient email address (default: test@example.com)
    """
    client = get_email_client()
    sender = EmailSender(client=client, db=db)
    
    # Validate email format
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, to.strip()):
        raise HTTPException(status_code=400, detail="Invalid email address format")
    
    logger.info(f"Test email request from {current_user.email} to {to}")
    
    # Send test email using template
    result = await sender.send_from_template(
        to=to,
        template_id="test",
        variables={
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        }
    )
    
    return SendEmailResponse(
        success=result.success,
        status=result.status.value,
        message_id=result.message_id,
        provider_message_id=result.provider_message_id,
        error=result.error
    )


@router.post("/validate", response_model=ValidateEmailResponse)
async def validate_email(
    request: ValidateEmailRequest,
    current_user: AuthUser = Depends(require_email_access)
):
    """
    Validate email address and/or template variables.
    
    **Permissions:** admin, staff, tax_agent
    
    **Request Body:**
    - `email`: Optional email address to validate
    - `template_id`: Optional template ID to validate
    - `variables`: Optional template variables to validate
    """
    client = get_email_client()
    sender = EmailSender(client=client)
    
    result = {
        "valid": True,
        "email_valid": None,
        "template_valid": None,
        "missing_variables": None,
        "error": None
    }
    
    # Validate email if provided
    if request.email:
        email_valid = client.validate_email_address(request.email)
        result["email_valid"] = email_valid
        if not email_valid:
            result["valid"] = False
            result["error"] = "Invalid email address format"
    
    # Validate template if provided
    if request.template_id:
        variables = request.variables or {}
        validation = sender.validate_template_variables(request.template_id, variables)
        result["template_valid"] = validation["valid"]
        result["missing_variables"] = validation.get("missing_variables", [])
        
        if not validation["valid"]:
            result["valid"] = False
            if validation.get("error"):
                result["error"] = validation["error"]
            elif validation.get("missing_variables"):
                result["error"] = f"Missing template variables: {', '.join(validation['missing_variables'])}"
    
    return ValidateEmailResponse(**result)


@router.get("/templates")
async def list_templates(
    current_user: AuthUser = Depends(require_email_access)
):
    """
    List available email templates.
    
    **Permissions:** admin, staff, tax_agent
    
    Returns list of templates with their required variables.
    """
    client = get_email_client()
    sender = EmailSender(client=client)
    
    templates = []
    for template_id in sender.list_templates():
        template = sender.get_template(template_id)
        if template:
            # Extract variables from template
            import re
            subject_vars = set(re.findall(r'\{(\w+)\}', template['subject']))
            body_vars = set(re.findall(r'\{(\w+)\}', template['body']))
            all_vars = list(subject_vars.union(body_vars))
            
            templates.append({
                "id": template_id,
                "subject_preview": template['subject'][:50] + "..." if len(template['subject']) > 50 else template['subject'],
                "required_variables": all_vars
            })
    
    return {
        "templates": templates,
        "count": len(templates)
    }


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    current_user: AuthUser = Depends(require_email_access)
):
    """
    Get a specific template details.
    
    **Permissions:** admin, staff, tax_agent
    """
    client = get_email_client()
    sender = EmailSender(client=client)
    
    template = sender.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    
    # Extract variables
    import re
    subject_vars = set(re.findall(r'\{(\w+)\}', template['subject']))
    body_vars = set(re.findall(r'\{(\w+)\}', template['body']))
    all_vars = list(subject_vars.union(body_vars))
    
    return {
        "id": template_id,
        "subject": template['subject'],
        "body": template['body'],
        "required_variables": all_vars
    }
