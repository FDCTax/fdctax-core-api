"""
Email Integration - API Router

Provides REST API endpoints for email functionality:
- POST /api/email/send - Send email via Resend
- POST /api/email/send-template - Send using template
- POST /api/email/send-test - Send test email
- POST /api/email/render - Render template without sending
- POST /api/email/validate - Validate email/template
- GET /api/email/templates - List available templates
- GET /api/email/templates/{id} - Get template details
- GET /api/email/status - Get module status

Permissions:
- send: admin, staff, tax_agent
- status: public
- templates: admin, staff, tax_agent
"""

import os
import logging
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, field_validator

from database import get_db
from middleware.auth import RoleChecker, AuthUser

from .email_client import EmailClient, EmailStatus
from .email_sender import EmailSender, EmailMessageType
from .template_engine import get_template_engine, TEMPLATE_VARIABLES

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
    variables: Dict[str, Any] = Field(..., description="Template variables")
    client_id: Optional[str] = Field(None, description="Client ID for tracking")
    job_id: Optional[str] = Field(None, description="Job ID for tracking")
    strict: bool = Field(True, description="Fail on missing required variables")
    
    @field_validator('to')
    @classmethod
    def validate_email(cls, v):
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, v.strip()):
            raise ValueError('Invalid email address format')
        return v.strip()


class RenderTemplateRequest(BaseModel):
    """Request model for template rendering"""
    template_id: Optional[str] = Field(None, description="Template ID (use registered template)")
    subject_template: Optional[str] = Field(None, description="Custom subject template")
    body_template: Optional[str] = Field(None, description="Custom body template")
    variables: Dict[str, Any] = Field(..., description="Template variables")
    strict: bool = Field(False, description="Fail on missing variables")


class RenderTemplateResponse(BaseModel):
    """Response model for template rendering"""
    success: bool
    subject: Optional[str] = None
    html: Optional[str] = None
    error: Optional[str] = None
    validation: Optional[Dict[str, Any]] = None


class ValidateEmailRequest(BaseModel):
    """Request model for email validation"""
    email: Optional[str] = Field(None, description="Email address to validate")
    template_id: Optional[str] = Field(None, description="Template ID to validate")
    template_html: Optional[str] = Field(None, description="Custom template HTML to validate")
    variables: Optional[Dict[str, Any]] = Field(None, description="Template variables to validate")


class ValidateEmailResponse(BaseModel):
    """Response model for email validation"""
    valid: bool
    email_valid: Optional[bool] = None
    template_valid: Optional[bool] = None
    missing: Optional[List[str]] = None
    unused: Optional[List[str]] = None
    invalid: Optional[List[str]] = None
    errors: Optional[List[str]] = None


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
    
    feature_flag = os.environ.get('EMAIL_FEATURE_FLAG', 'true').lower() == 'true'
    
    return {
        "status": "ok" if client.is_ready() else "not_ready",
        "module": "email",
        "version": "1.5.0",
        "features": {
            "send_email": client.is_ready(),
            "templates": True,
            "template_rendering": True,
            "bulk_send": False,
            "scheduling": False,
            "tracking": False
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
    """
    client = get_email_client()
    
    if not client.is_ready():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Email service not configured. Check EMAIL_API_KEY and EMAIL_FROM_ADDRESS."
        )
    
    sender = EmailSender(client=client, db=db)
    
    logger.info(f"Email send request from {current_user.email} to {request.to}")
    
    msg_type = EmailMessageType.CUSTOM
    if request.message_type:
        try:
            msg_type = EmailMessageType(request.message_type)
        except ValueError:
            msg_type = EmailMessageType.CUSTOM
    
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
    
    if not result.success and "API" in (result.error or ""):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.error
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
    Send an email using a template with the rendering engine.
    
    **Permissions:** admin, staff, tax_agent
    
    **Available Templates:**
    - `appointment_reminder`: {client_name, date, time, location}
    - `document_request`: {client_name, document_name}
    - `tax_return_ready`: {client_name, tax_year, amount}
    - `invoice`: {client_name, invoice_number, amount, due_date}
    - `welcome`: {client_name, portal_url}
    - `test`: {timestamp}
    - `bas_reminder`: {client_name, period, due_date}
    - `payment_receipt`: {client_name, amount, receipt_number, payment_date}
    """
    client = get_email_client()
    
    if not client.is_ready():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Email service not configured. Check EMAIL_API_KEY and EMAIL_FROM_ADDRESS."
        )
    
    sender = EmailSender(client=client, db=db)
    
    logger.info(f"Template email request from {current_user.email} to {request.to} using {request.template_id}")
    
    result = await sender.send_from_template(
        to=request.to,
        template_id=request.template_id,
        variables=request.variables,
        client_id=request.client_id,
        job_id=request.job_id,
        strict=request.strict
    )
    
    if not result.success:
        if "not found" in (result.error or "").lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result.error
            )
        if "missing" in (result.error or "").lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.error
            )
        if "API" in (result.error or ""):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=result.error
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
    """
    client = get_email_client()
    
    if not client.is_ready():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Email service not configured. Check EMAIL_API_KEY and EMAIL_FROM_ADDRESS."
        )
    
    # Validate email format
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, to.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email address format"
        )
    
    sender = EmailSender(client=client, db=db)
    
    logger.info(f"Test email request from {current_user.email} to {to}")
    
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


@router.post("/render", response_model=RenderTemplateResponse)
async def render_template(
    request: RenderTemplateRequest,
    current_user: AuthUser = Depends(require_email_access)
):
    """
    Render a template without sending.
    
    **Permissions:** admin, staff, tax_agent
    
    Use either:
    - `template_id` to render a registered template
    - `subject_template` + `body_template` for custom templates
    
    **Response:**
    - `success`: Whether rendering succeeded
    - `subject`: Rendered subject line
    - `html`: Rendered and sanitized HTML body
    - `validation`: Variable validation results
    """
    client = get_email_client()
    sender = EmailSender(client=client)
    
    # Determine which template to render
    if request.template_id:
        # Render registered template
        result = sender.render_template(
            template_id=request.template_id,
            variables=request.variables,
            strict=request.strict
        )
    elif request.subject_template and request.body_template:
        # Render custom template
        result = sender.render_custom_template(
            subject_template=request.subject_template,
            body_template=request.body_template,
            variables=request.variables,
            strict=request.strict
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either template_id or (subject_template + body_template) must be provided"
        )
    
    if not result.get("success", False):
        error_msg = result.get("error", "Rendering failed")
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg
            )
        if request.strict and "missing" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )
    
    return RenderTemplateResponse(
        success=result.get("success", False),
        subject=result.get("subject"),
        html=result.get("html"),
        error=result.get("error"),
        validation=result.get("validation")
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
    - `template_id`: Optional registered template to validate against
    - `template_html`: Optional custom template HTML to validate
    - `variables`: Variables to validate against template
    """
    client = get_email_client()
    sender = EmailSender(client=client)
    
    result: Dict[str, Any] = {
        "valid": True,
        "email_valid": None,
        "template_valid": None,
        "missing": None,
        "unused": None,
        "invalid": None,
        "errors": []
    }
    
    # Validate email if provided
    if request.email:
        email_valid = client.validate_email_address(request.email)
        result["email_valid"] = email_valid
        if not email_valid:
            result["valid"] = False
            result["errors"].append("Invalid email address format")
    
    # Validate template if provided
    variables = request.variables or {}
    
    if request.template_id:
        validation = sender.validate_template_variables(request.template_id, variables)
        result["template_valid"] = validation.get("valid", False)
        result["missing"] = validation.get("missing", [])
        result["unused"] = validation.get("unused", [])
        result["invalid"] = validation.get("invalid", [])
        
        if not validation.get("valid", False):
            result["valid"] = False
            if validation.get("error"):
                result["errors"].append(validation["error"])
            elif validation.get("errors"):
                result["errors"].extend(validation["errors"])
                
    elif request.template_html:
        validation = sender.validate_custom_template(request.template_html, variables)
        result["template_valid"] = validation.get("valid", False)
        result["missing"] = validation.get("missing", [])
        result["unused"] = validation.get("unused", [])
        result["invalid"] = validation.get("invalid", [])
        
        if not validation.get("valid", False):
            result["valid"] = False
            if validation.get("errors"):
                result["errors"].extend(validation["errors"])
    
    return ValidateEmailResponse(**result)


@router.get("/templates")
async def list_templates(
    current_user: AuthUser = Depends(require_email_access)
):
    """
    List available email templates with their required variables.
    
    **Permissions:** admin, staff, tax_agent
    """
    client = get_email_client()
    sender = EmailSender(client=client)
    
    templates = sender.get_all_templates_info()
    
    # Simplify for list view
    template_list = []
    for t in templates:
        if t:
            template_list.append({
                "id": t["id"],
                "description": t.get("description", ""),
                "subject_preview": t["subject"][:50] + "..." if len(t["subject"]) > 50 else t["subject"],
                "required_variables": t.get("required_variables", []),
                "optional_variables": t.get("optional_variables", [])
            })
    
    return {
        "templates": template_list,
        "count": len(template_list)
    }


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    current_user: AuthUser = Depends(require_email_access)
):
    """
    Get detailed information about a specific template.
    
    **Permissions:** admin, staff, tax_agent
    """
    client = get_email_client()
    sender = EmailSender(client=client)
    
    template_info = sender.get_template_info(template_id)
    if not template_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{template_id}' not found"
        )
    
    return template_info


@router.get("/template-registry")
async def get_template_registry(
    current_user: AuthUser = Depends(require_email_access)
):
    """
    Get the template variable registry.
    
    Returns all template IDs with their required and optional variables.
    Useful for building template UIs.
    
    **Permissions:** admin, staff, tax_agent
    """
    return {
        "templates": TEMPLATE_VARIABLES,
        "count": len(TEMPLATE_VARIABLES)
    }
