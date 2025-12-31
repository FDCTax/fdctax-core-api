"""
SMS Integration - API Router

Provides REST API endpoints for SMS functionality:
- POST /api/sms/send - Send SMS (stub in Phase 0)

Phase 0: Stub endpoints only
Phase 1: Real SMS sending (Agent 4)
Phase 2: Inbound webhooks, message history

Permissions:
- send: admin, staff, tax_agent
- webhook: public (signature protected)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from middleware.auth import RoleChecker, AuthUser

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/sms", tags=["SMS Integration"])

# Permission checkers
require_sms_access = RoleChecker(["admin", "staff", "tax_agent"])


# ==================== REQUEST/RESPONSE MODELS ====================

class SendSMSRequest(BaseModel):
    """Request model for sending SMS"""
    to: str = Field(..., description="Recipient phone number (E.164 format preferred)")
    message: str = Field(..., description="Message content", max_length=1600)
    client_id: Optional[str] = Field(None, description="Optional client ID for tracking")
    template_id: Optional[str] = Field(None, description="Optional template ID")


class SendSMSResponse(BaseModel):
    """Response model for SMS send operation"""
    status: str
    message: Optional[str] = None
    message_id: Optional[str] = None
    error: Optional[str] = None


# ==================== ENDPOINTS ====================

@router.post("/send", response_model=SendSMSResponse)
async def send_sms(
    request: SendSMSRequest,
    current_user: AuthUser = Depends(require_sms_access)
):
    """
    Send an SMS message.
    
    **Phase 0 Status:** This endpoint is a stub and will return `not_implemented`.
    Real SMS sending will be added in Phase 1.
    
    **Permissions:** admin, staff, tax_agent
    
    **Request Body:**
    - `to`: Recipient phone number (E.164 format preferred, e.g., +61400123456)
    - `message`: Message content (max 1600 characters)
    - `client_id`: Optional client ID for tracking
    - `template_id`: Optional template ID (Phase 2)
    
    **Response:**
    - `status`: Operation status
    - `message_id`: Provider message ID (when implemented)
    - `error`: Error message if failed
    """
    logger.info(f"SMS send request from {current_user.email} to {request.to} (stub)")
    
    # Phase 0: Return stub response
    return SendSMSResponse(
        status="not_implemented",
        message="SMS sending is not implemented yet. This is Phase 0 scaffolding.",
        message_id=None,
        error=None
    )


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
    
    # Check configuration
    provider = os.environ.get('SMS_PROVIDER', 'not_configured')
    has_sid = bool(os.environ.get('SMS_ACCOUNT_SID'))
    has_token = bool(os.environ.get('SMS_AUTH_TOKEN'))
    has_number = bool(os.environ.get('SMS_FROM_NUMBER'))
    
    is_configured = has_sid and has_token and has_number
    
    return {
        "phase": "0 - Scaffolding",
        "status": "stub" if not is_configured else "configured_but_not_implemented",
        "provider": provider,
        "configuration": {
            "account_sid": "✓ Set" if has_sid else "✗ Not set",
            "auth_token": "✓ Set" if has_token else "✗ Not set",
            "from_number": "✓ Set" if has_number else "✗ Not set",
        },
        "ready_to_send": False,
        "message": "Phase 0 scaffolding complete. Phase 1 will add real SMS sending."
    }
