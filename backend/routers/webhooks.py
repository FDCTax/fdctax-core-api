"""
Webhook Management Router

API endpoints for managing webhook registrations and monitoring delivery.

All endpoints require Internal Service Token authentication.

Endpoints:
- POST /api/webhooks/register - Register a new webhook
- GET /api/webhooks - List all webhooks
- GET /api/webhooks/status - Module status (MUST be before /{webhook_id})
- GET /api/webhooks/events - List supported events
- GET /api/webhooks/{id} - Get specific webhook
- DELETE /api/webhooks/{id} - Delete a webhook
- PUT /api/webhooks/{id}/status - Enable/disable a webhook
- GET /api/webhooks/queue/stats - Get delivery queue statistics
- GET /api/webhooks/queue/dead-letter - Get dead letter items
- POST /api/webhooks/queue/dead-letter/{id}/retry - Retry a dead letter item
- POST /api/webhooks/queue/process - Manually trigger queue processing
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, status, Depends, Query, Path
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.internal_auth import get_internal_service, InternalService
from services.webhook_service import (
    WebhookService,
    WebhookEventType
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


# ==================== REQUEST/RESPONSE MODELS ====================

class WebhookRegisterRequest(BaseModel):
    """Request to register a new webhook."""
    service: str = Field(..., min_length=1, max_length=100, description="Service name")
    url: str = Field(..., description="Webhook callback URL")
    events: List[str] = Field(..., min_length=1, description="Event types to subscribe to")
    
    class Config:
        json_schema_extra = {
            "example": {
                "service": "crm",
                "url": "https://crm.example.com/api/webhooks/myfdc",
                "events": ["myfdc.hours.logged", "myfdc.expense.logged"]
            }
        }


class WebhookStatusRequest(BaseModel):
    """Request to update webhook status."""
    is_active: bool = Field(..., description="Enable or disable the webhook")


class WebhookRegisterResponse(BaseModel):
    """Response after registering a webhook."""
    id: str
    service_name: str
    url: str
    events: List[str]
    secret_key: str
    message: str


# ==================== INFO ENDPOINTS (MUST BE FIRST) ====================

@router.get("/status")
async def get_webhook_module_status(
    service: InternalService = Depends(get_internal_service)
):
    """
    Get webhook module status.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    """
    return {
        "module": "webhooks",
        "status": "operational",
        "version": "1.0.0",
        "supported_events": [e.value for e in WebhookEventType],
        "retry_config": {
            "max_attempts": 3,
            "backoff_delays_seconds": [60, 300, 900]
        },
        "endpoints": [
            "POST /api/webhooks/register",
            "GET /api/webhooks",
            "GET /api/webhooks/{id}",
            "DELETE /api/webhooks/{id}",
            "PUT /api/webhooks/{id}/status",
            "GET /api/webhooks/queue/stats",
            "GET /api/webhooks/queue/dead-letter",
            "POST /api/webhooks/queue/dead-letter/{id}/retry",
            "POST /api/webhooks/queue/process"
        ],
        "authentication": "Internal Service Token (X-Internal-Api-Key)"
    }


@router.get("/events")
async def list_supported_events(
    service: InternalService = Depends(get_internal_service)
):
    """
    List all supported webhook event types.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    """
    return {
        "events": [
            {
                "type": e.value,
                "description": _get_event_description(e)
            }
            for e in WebhookEventType
        ]
    }


# ==================== QUEUE MANAGEMENT ENDPOINTS ====================

@router.get("/queue/stats")
async def get_queue_stats(
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Get delivery queue statistics.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    **Returns:**
    - Count of pending, delivered, and failed deliveries
    - Dead letter queue count
    """
    webhook_service = WebhookService(db)
    
    try:
        stats = await webhook_service.get_queue_stats()
        return {
            "queue_stats": stats,
            "status": "operational"
        }
    except Exception as e:
        logger.error(f"Failed to get queue stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get queue statistics"
        )


@router.get("/queue/dead-letter")
async def get_dead_letter_items(
    limit: int = Query(50, ge=1, le=200, description="Maximum items to return"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Get items from the dead letter queue.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    These are webhook deliveries that failed after all retry attempts.
    """
    webhook_service = WebhookService(db)
    
    try:
        items = await webhook_service.get_dead_letter_items(limit=limit)
        return {
            "dead_letter_items": items,
            "count": len(items)
        }
    except Exception as e:
        logger.error(f"Failed to get dead letter items: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get dead letter items"
        )


@router.post("/queue/dead-letter/{item_id}/retry")
async def retry_dead_letter_item(
    item_id: str = Path(..., description="Dead letter item UUID"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Re-queue a dead letter item for delivery.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    """
    logger.info(f"Dead letter retry by {service.name}: {item_id}")
    
    webhook_service = WebhookService(db)
    
    success = await webhook_service.retry_dead_letter(item_id, service.name)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dead letter item not found"
        )
    
    return {
        "message": "Item re-queued for delivery",
        "id": item_id
    }


@router.post("/queue/process")
async def process_delivery_queue(
    batch_size: int = Query(10, ge=1, le=100, description="Number of items to process"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger queue processing.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    In production, this should be called by a background scheduler.
    """
    logger.info(f"Queue processing triggered by {service.name}")
    
    webhook_service = WebhookService(db)
    
    try:
        stats = await webhook_service.process_delivery_queue(batch_size=batch_size)
        return {
            "message": "Queue processing complete",
            "results": stats
        }
    except Exception as e:
        logger.error(f"Queue processing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process delivery queue"
        )


# ==================== REGISTRATION ENDPOINTS ====================

@router.post("/register", response_model=WebhookRegisterResponse)
async def register_webhook(
    request: WebhookRegisterRequest,
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new webhook.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    **Supported Events:**
    - `myfdc.profile.updated` - Educator profile updated
    - `myfdc.hours.logged` - Hours worked logged
    - `myfdc.occupancy.logged` - Occupancy data logged
    - `myfdc.diary.created` - Diary entry created
    - `myfdc.expense.logged` - Expense logged
    - `myfdc.attendance.logged` - Child attendance logged
    
    **Returns:** Webhook ID and secret key for signature verification.
    
    **Important:** Store the `secret_key` securely - it will only be returned once.
    """
    logger.info(f"Webhook registration from {service.name} for service {request.service}")
    
    webhook_service = WebhookService(db)
    
    try:
        result = await webhook_service.register_webhook(
            service_name=request.service,
            url=request.url,
            events=request.events,
            registered_by=service.name
        )
        return WebhookRegisterResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Webhook registration failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register webhook"
        )


@router.get("")
async def list_webhooks(
    service_filter: Optional[str] = Query(None, description="Filter by service name"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    List all registered webhooks.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    **Query Params:**
    - `service_filter`: Filter by service name (optional)
    """
    webhook_service = WebhookService(db)
    
    try:
        webhooks = await webhook_service.list_webhooks(service_name=service_filter)
        return {
            "webhooks": webhooks,
            "count": len(webhooks)
        }
    except Exception as e:
        logger.error(f"Failed to list webhooks: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list webhooks"
        )


# ==================== PARAMETERIZED ENDPOINTS (MUST BE LAST) ====================

@router.get("/{webhook_id}")
async def get_webhook(
    webhook_id: str = Path(..., description="Webhook UUID"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific webhook by ID.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    """
    webhook_service = WebhookService(db)
    
    webhook = await webhook_service.get_webhook(webhook_id)
    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found"
        )
    
    return webhook


@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: str = Path(..., description="Webhook UUID"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a webhook registration.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    """
    logger.info(f"Webhook deletion by {service.name} for {webhook_id}")
    
    webhook_service = WebhookService(db)
    
    success = await webhook_service.delete_webhook(webhook_id, service.name)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found"
        )
    
    return {"message": "Webhook deleted", "id": webhook_id}


@router.put("/{webhook_id}/status")
async def update_webhook_status(
    request: WebhookStatusRequest,
    webhook_id: str = Path(..., description="Webhook UUID"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Enable or disable a webhook.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    """
    logger.info(f"Webhook status update by {service.name}: {webhook_id} -> {request.is_active}")
    
    webhook_service = WebhookService(db)
    
    success = await webhook_service.update_webhook_status(
        webhook_id, request.is_active, service.name
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found"
        )
    
    return {
        "message": f"Webhook {'enabled' if request.is_active else 'disabled'}",
        "id": webhook_id,
        "is_active": request.is_active
    }


# ==================== HELPERS ====================

def _get_event_description(event: WebhookEventType) -> str:
    """Get human-readable description for an event type."""
    descriptions = {
        WebhookEventType.PROFILE_UPDATED: "Educator profile was created or updated",
        WebhookEventType.HOURS_LOGGED: "Hours worked entry was logged",
        WebhookEventType.OCCUPANCY_LOGGED: "Occupancy data was logged",
        WebhookEventType.DIARY_CREATED: "Diary entry was created",
        WebhookEventType.EXPENSE_LOGGED: "Expense entry was logged",
        WebhookEventType.ATTENDANCE_LOGGED: "Child attendance was logged"
    }
    return descriptions.get(event, "Event triggered")
