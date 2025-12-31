"""
SMS Integration - API Router

Provides REST API endpoints for SMS functionality:
- POST /api/sms/send - Send SMS message
- POST /api/sms/send-template - Send SMS from template
- GET /api/sms/status - Get integration status
- GET /api/sms/message/{message_id} - Get message status
- GET /api/sms/templates - List available templates

Phase 1: Real SMS sending via Twilio
Phase 2: Inbound webhooks, message history (future)

Permissions:
- send: admin, staff, tax_agent
- status: admin, staff, tax_agent
"""

import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import RoleChecker, AuthUser
from sms_integration.sms_client import SMSClient
from sms_integration.sms_sender import SMSSender, SMSMessage, SMSMessageType

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/sms", tags=["SMS Integration"])

# Permission checkers
require_sms_access = RoleChecker(["admin", "staff", "tax_agent"])
require_admin = RoleChecker(["admin"])


# ==================== REQUEST/RESPONSE MODELS ====================

class SendSMSRequest(BaseModel):
    """Request model for sending SMS"""
    to: str = Field(..., description="Recipient phone number (E.164 format preferred)")
    message: str = Field(..., description="Message content", max_length=1600)
    client_id: Optional[str] = Field(None, description="Optional client ID for tracking")
    message_type: Optional[str] = Field("custom", description="Message type: notification, reminder, verification, alert, custom")


class SendTemplateRequest(BaseModel):
    """Request model for sending SMS from template"""
    to: str = Field(..., description="Recipient phone number")
    template_id: str = Field(..., description="Template ID")
    variables: Dict[str, str] = Field(..., description="Template variables")
    client_id: Optional[str] = Field(None, description="Optional client ID for tracking")


class SendSMSResponse(BaseModel):
    """Response model for SMS send operation"""
    success: bool
    status: Optional[str] = None
    message: Optional[str] = None
    message_id: Optional[str] = None
    recipient: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[int] = None


# ==================== ENDPOINTS ====================

@router.post("/send", response_model=SendSMSResponse)
async def send_sms(
    request: SendSMSRequest,
    current_user: AuthUser = Depends(require_sms_access)
):
    """
    Send an SMS message.
    
    **Permissions:** admin, staff, tax_agent
    
    **Request Body:**
    - `to`: Recipient phone number (E.164 format preferred, e.g., +61400123456)
    - `message`: Message content (max 1600 characters)
    - `client_id`: Optional client ID for tracking
    - `message_type`: Optional type (notification, reminder, verification, alert, custom)
    
    **Response:**
    - `success`: Whether the message was sent
    - `message_id`: Provider message ID (Twilio SID)
    - `status`: Message status (queued, sent, etc.)
    - `error`: Error message if failed
    """
    logger.info(f"SMS send request from {current_user.email} to {request.to}")
    
    sender = SMSSender()
    
    if not sender.is_ready():
        return SendSMSResponse(
            success=False,
            status="not_configured",
            error="SMS service not configured. Contact administrator.",
            error_code=503
        )
    
    # Map message type
    try:
        msg_type = SMSMessageType(request.message_type) if request.message_type else SMSMessageType.CUSTOM
    except ValueError:
        msg_type = SMSMessageType.CUSTOM
    
    # Create message
    message = SMSMessage(
        to=request.to,
        message=request.message,
        message_type=msg_type,
        client_id=request.client_id,
        metadata={"sent_by": current_user.email}
    )
    
    # Send
    result = await sender.send(message)
    
    return SendSMSResponse(
        success=result.success,
        status=result.status,
        message="SMS sent successfully" if result.success else None,
        message_id=result.message_id,
        recipient=result.recipient,
        error=result.error,
        error_code=result.error_code
    )


@router.post("/send-template", response_model=SendSMSResponse)
async def send_template_sms(
    request: SendTemplateRequest,
    current_user: AuthUser = Depends(require_sms_access)
):
    """
    Send an SMS using a predefined template.
    
    **Permissions:** admin, staff, tax_agent
    
    **Request Body:**
    - `to`: Recipient phone number
    - `template_id`: Template identifier (e.g., 'appointment_reminder', 'bas_ready')
    - `variables`: Dict of template variables
    - `client_id`: Optional client ID for tracking
    
    **Available Templates:**
    - `appointment_reminder`: {client_name, date, time}
    - `document_request`: {client_name, document_name}
    - `payment_reminder`: {client_name, invoice_number, amount, due_date}
    - `tax_deadline`: {client_name, tax_type, deadline}
    - `bas_ready`: {client_name, period}
    - `bas_approved`: {client_name, period}
    - `bas_lodged`: {client_name, period, amount, due_date}
    - `welcome`: {client_name}
    - `verification_code`: {code}
    """
    logger.info(f"Template SMS request from {current_user.email}: {request.template_id}")
    
    sender = SMSSender()
    
    if not sender.is_ready():
        return SendSMSResponse(
            success=False,
            status="not_configured",
            error="SMS service not configured. Contact administrator.",
            error_code=503
        )
    
    result = await sender.send_from_template(
        to=request.to,
        template_id=request.template_id,
        variables=request.variables,
        client_id=request.client_id
    )
    
    return SendSMSResponse(
        success=result.success,
        status=result.status,
        message="SMS sent successfully" if result.success else None,
        message_id=result.message_id,
        recipient=result.recipient,
        error=result.error,
        error_code=result.error_code
    )


@router.get("/message/{message_id}")
async def get_message_status(
    message_id: str,
    current_user: AuthUser = Depends(require_sms_access)
):
    """
    Get the status of a sent SMS message.
    
    **Permissions:** admin, staff, tax_agent
    
    **Path Parameters:**
    - `message_id`: Twilio message SID
    
    **Response:**
    - Message details including status, timestamps, error info
    """
    sender = SMSSender()
    
    if not sender.is_ready():
        raise HTTPException(
            status_code=503,
            detail="SMS service not configured"
        )
    
    status = await sender.get_message_status(message_id)
    
    if not status:
        raise HTTPException(
            status_code=404,
            detail=f"Message not found: {message_id}"
        )
    
    return status


@router.get("/templates")
async def list_templates(
    current_user: AuthUser = Depends(require_sms_access)
):
    """
    List available SMS templates.
    
    **Permissions:** admin, staff, tax_agent
    
    **Response:**
    - Dictionary of template_id -> template_content
    """
    sender = SMSSender()
    return {
        "templates": sender.list_templates(),
        "count": len(sender.list_templates())
    }


@router.get("/status")
async def get_sms_status(
    current_user: AuthUser = Depends(require_sms_access)
):
    """
    Get SMS integration status.
    
    Returns current configuration status and whether SMS is ready to use.
    
    **Permissions:** admin, staff, tax_agent
    """
    import os
    
    client = SMSClient()
    
    # Check configuration
    provider = os.environ.get('SMS_PROVIDER', 'twilio')
    has_sid = bool(os.environ.get('SMS_ACCOUNT_SID'))
    has_token = bool(os.environ.get('SMS_AUTH_TOKEN'))
    has_number = bool(os.environ.get('SMS_FROM_NUMBER'))
    
    is_configured = has_sid and has_token and has_number
    
    # Get account info if configured
    account_info = None
    if is_configured:
        account_info = client.get_account_info()
    
    return {
        "phase": "1 - Production",
        "status": "ready" if is_configured else "not_configured",
        "provider": provider,
        "configuration": {
            "account_sid": "✓ Set" if has_sid else "✗ Not set",
            "auth_token": "✓ Set" if has_token else "✗ Not set",
            "from_number": "✓ Set" if has_number else "✗ Not set",
        },
        "ready_to_send": is_configured,
        "account_info": account_info,
        "templates_available": len(SMSSender().list_templates()),
        "message": "SMS service is ready" if is_configured else "Configure SMS_ACCOUNT_SID, SMS_AUTH_TOKEN, and SMS_FROM_NUMBER"
    }


@router.post("/test")
async def test_sms(
    current_user: AuthUser = Depends(require_admin)
):
    """
    Test SMS configuration by sending a test message.
    
    **Permissions:** admin only
    
    Sends a test SMS to the admin's registered phone (if configured).
    """
    import os
    
    test_number = os.environ.get('SMS_TEST_NUMBER')
    
    if not test_number:
        raise HTTPException(
            status_code=400,
            detail="SMS_TEST_NUMBER not configured. Set it in environment variables."
        )
    
    sender = SMSSender()
    
    if not sender.is_ready():
        raise HTTPException(
            status_code=503,
            detail="SMS service not configured"
        )
    
    result = await sender.send(SMSMessage(
        to=test_number,
        message=f"FDC Tax SMS Test - Sent by {current_user.email} at {__import__('datetime').datetime.now().isoformat()}",
        message_type=SMSMessageType.NOTIFICATION
    ))
    
    return {
        "success": result.success,
        "message_id": result.message_id,
        "status": result.status,
        "error": result.error,
        "sent_to": test_number[:6] + "***"
    }
