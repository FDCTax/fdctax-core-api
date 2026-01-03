"""
Core SMS Proxy Router

API endpoints for SMS forwarding from MyFDC/CRM to Agent 5.
Ensures internal services never touch SMS credentials directly.

All endpoints require Internal Service Token authentication.

Endpoints:
- POST /api/internal/sms/send - Send single SMS
- POST /api/internal/sms/bulk - Send bulk SMS
- GET /api/internal/sms/health - Check Agent 5 health
- GET /api/internal/sms/status/{message_id} - Get delivery status

Security:
- Validates x-internal-service header
- Validates internal API token
- Never logs phone numbers or message content
"""

import os
import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, status, Depends, Query, Path, Header
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.internal_auth import get_internal_service, InternalService
from services.sms_proxy import (
    SMSProxyService,
    SMSSendRequest,
    SMSProxyResponse,
    BulkSMSResult
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/sms", tags=["SMS Proxy"])


# ==================== REQUEST/RESPONSE MODELS ====================

class SMSSendRequestModel(BaseModel):
    """Request to send a single SMS."""
    to: str = Field(..., description="Recipient phone number (E.164 format)")
    message: str = Field(..., min_length=1, max_length=1600, description="SMS message content")
    metadata: Optional[dict] = Field(None, description="Optional metadata")
    
    class Config:
        json_schema_extra = {
            "example": {
                "to": "+61412345678",
                "message": "Reminder: Hours not submitted.",
                "metadata": {
                    "source": "myfdc",
                    "client_id": "abc123"
                }
            }
        }


class BulkSMSRequestModel(BaseModel):
    """Request to send bulk SMS."""
    messages: List[SMSSendRequestModel] = Field(..., min_length=1, max_length=100)
    
    class Config:
        json_schema_extra = {
            "example": {
                "messages": [
                    {
                        "to": "+61412345678",
                        "message": "Reminder: Hours not submitted.",
                        "metadata": {"source": "myfdc", "client_id": "abc123"}
                    },
                    {
                        "to": "+61498765432",
                        "message": "Your BAS is ready for review.",
                        "metadata": {"source": "crm", "client_id": "def456"}
                    }
                ]
            }
        }


class SMSSendResponseModel(BaseModel):
    """Response from SMS send operation."""
    success: bool
    message_id: Optional[str] = None
    status: str
    error: Optional[str] = None
    retry_count: int = 0


class BulkSMSResponseModel(BaseModel):
    """Response from bulk SMS operation."""
    total: int
    sent: int
    failed: int
    results: List[dict]


# ==================== HELPER ====================

def get_sms_service(db: AsyncSession) -> SMSProxyService:
    """
    Get appropriate SMS service based on configuration.
    
    Uses mock service if Agent 5 token is not configured.
    """
    agent5_token = os.environ.get('AGENT5_SMS_TOKEN', '')
    
    if not agent5_token or agent5_token == 'agent5-internal-token-placeholder':
        logger.warning("Using mock SMS service - Agent 5 not configured")
        return MockSMSProxyService(db)
    
    return SMSProxyService(db)


# ==================== ENDPOINTS ====================

@router.post("/send", response_model=SMSSendResponseModel)
async def send_sms(
    request: SMSSendRequestModel,
    x_internal_service: str = Header(..., description="Internal service identifier"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Send a single SMS via Core → Agent 5 proxy.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    **Required Headers:**
    - `X-Internal-Api-Key`: Internal service authentication token
    - `X-Internal-Service`: Service identifier (e.g., 'myfdc', 'crm')
    
    **Security:**
    - Phone numbers and message content are NEVER logged
    - Only metadata (source, client_id, status) is logged for audit
    
    **Returns:**
    - `message_id`: Unique identifier for tracking
    - `status`: Current status (sent, failed, queued)
    """
    logger.info(f"SMS send request from {x_internal_service} via {service.name}")
    
    # Extract metadata
    metadata = request.metadata or {}
    source = metadata.get('source', x_internal_service)
    client_id = metadata.get('client_id')
    reference_id = metadata.get('reference_id')
    
    # Create internal request object
    sms_request = SMSSendRequest(
        to=request.to,
        message=request.message,
        source=source,
        client_id=client_id,
        reference_id=reference_id,
        priority=metadata.get('priority', 'normal')
    )
    
    # Get appropriate service and send
    sms_service = get_sms_service(db)
    
    try:
        result = await sms_service.send_sms(sms_request, service.name)
        return SMSSendResponseModel(**result.to_dict())
    except Exception as e:
        logger.error(f"SMS send failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send SMS"
        )


@router.post("/bulk", response_model=BulkSMSResponseModel)
async def send_bulk_sms(
    request: BulkSMSRequestModel,
    x_internal_service: str = Header(..., description="Internal service identifier"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Send multiple SMS messages via Core → Agent 5 proxy.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    **Required Headers:**
    - `X-Internal-Api-Key`: Internal service authentication token
    - `X-Internal-Service`: Service identifier (e.g., 'myfdc', 'crm')
    
    **Limits:**
    - Maximum 100 messages per request
    - Messages are processed in parallel batches of 10
    
    **Security:**
    - Phone numbers and message content are NEVER logged
    - Only aggregate counts and status are logged
    """
    logger.info(f"Bulk SMS request from {x_internal_service} via {service.name}: {len(request.messages)} messages")
    
    # Convert to internal request objects
    sms_requests = []
    for msg in request.messages:
        metadata = msg.metadata or {}
        sms_requests.append(SMSSendRequest(
            to=msg.to,
            message=msg.message,
            source=metadata.get('source', x_internal_service),
            client_id=metadata.get('client_id'),
            reference_id=metadata.get('reference_id'),
            priority=metadata.get('priority', 'normal')
        ))
    
    # Get appropriate service and send
    sms_service = get_sms_service(db)
    
    try:
        result = await sms_service.send_bulk_sms(sms_requests, service.name)
        return BulkSMSResponseModel(**result.to_dict())
    except Exception as e:
        logger.error(f"Bulk SMS send failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send bulk SMS"
        )


@router.get("/health")
async def check_sms_health(
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Check Agent 5 SMS service health.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    **Returns:**
    - Agent 5 availability status
    - Response time (if available)
    - Any error messages
    """
    sms_service = get_sms_service(db)
    
    try:
        health = await sms_service.check_health()
        
        return {
            "module": "sms_proxy",
            "status": "operational" if health.get('agent5_available') else "degraded",
            "agent5": health,
            "proxy_config": {
                "max_retries": int(os.environ.get('AGENT5_SMS_MAX_RETRIES', '3')),
                "timeout_seconds": int(os.environ.get('AGENT5_SMS_TIMEOUT', '30'))
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "module": "sms_proxy",
            "status": "error",
            "error": str(e)[:100]
        }


@router.get("/status/{message_id}")
async def get_sms_status(
    message_id: str = Path(..., description="SMS message ID"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Get delivery status for a sent SMS.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    **Returns:**
    - Current delivery status
    - Delivery timestamp (if delivered)
    - Error details (if failed)
    """
    sms_service = get_sms_service(db)
    
    try:
        status_result = await sms_service.get_delivery_status(message_id, service.name)
        return status_result
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get SMS status"
        )


@router.get("/module-status")
async def get_sms_proxy_status(
    service: InternalService = Depends(get_internal_service)
):
    """
    Get SMS proxy module status and configuration.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    Returns module info without exposing sensitive configuration.
    """
    agent5_configured = bool(os.environ.get('AGENT5_SMS_TOKEN', '')) and \
                        os.environ.get('AGENT5_SMS_TOKEN') != 'agent5-internal-token-placeholder'
    
    return {
        "module": "sms_proxy",
        "status": "operational",
        "version": "1.0.0",
        "agent5_configured": agent5_configured,
        "mode": "live" if agent5_configured else "mock",
        "config": {
            "max_retries": int(os.environ.get('AGENT5_SMS_MAX_RETRIES', '3')),
            "timeout_seconds": int(os.environ.get('AGENT5_SMS_TIMEOUT', '30')),
            "max_bulk_size": 100
        },
        "endpoints": [
            "POST /api/internal/sms/send",
            "POST /api/internal/sms/bulk",
            "GET /api/internal/sms/health",
            "GET /api/internal/sms/status/{message_id}"
        ],
        "required_headers": [
            "X-Internal-Api-Key",
            "X-Internal-Service"
        ],
        "audit_events": [
            "sms_proxy_request",
            "sms_proxy_success",
            "sms_proxy_failure",
            "sms_proxy_retry",
            "sms_proxy_fallback",
            "sms_bulk_request",
            "sms_bulk_success",
            "sms_bulk_failure"
        ]
    }
