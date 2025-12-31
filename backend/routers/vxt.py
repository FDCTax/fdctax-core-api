"""
VXT Phone System Integration - API Router

Provides REST API endpoints for VXT integration:
- POST /api/vxt/webhook - Receive VXT webhooks
- GET /api/vxt/calls - List calls
- GET /api/vxt/calls/{id} - Get call details with transcript
- GET /api/vxt/recording/{id} - Stream audio recording
- POST /api/vxt/calls/{id}/link-workpaper - Link call to workpaper

Permissions:
- Webhook: Public (protected by signature)
- All other endpoints: admin, staff, tax_agent
"""

import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Header
from fastapi.responses import StreamingResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
import httpx

from database import get_db
from middleware.auth import RoleChecker, AuthUser

from vxt.service import VXTWebhookService, VXTCallService

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/vxt", tags=["VXT Phone System"])

# Permission checkers
require_vxt_access = RoleChecker(["admin", "staff", "tax_agent"])


# ==================== REQUEST/RESPONSE MODELS ====================

class WebhookPayload(BaseModel):
    """VXT webhook payload"""
    event_type: str = Field(..., description="Event type (call.completed, call.transcribed)")
    call_id: str = Field(..., description="VXT call ID")
    from_number: Optional[str] = None
    to_number: Optional[str] = None
    direction: Optional[str] = None
    timestamp: Optional[str] = None
    duration_seconds: Optional[int] = None
    status: Optional[str] = None
    recording_url: Optional[str] = None
    transcript_text: Optional[str] = None
    summary_text: Optional[str] = None
    webhook_id: Optional[str] = None


class LinkWorkpaperRequest(BaseModel):
    """Request to link call to workpaper"""
    workpaper_id: int = Field(..., description="Workpaper ID")
    notes: Optional[str] = Field(None, description="Notes about the link")


# ==================== WEBHOOK ENDPOINT ====================

@router.post("/webhook")
async def receive_webhook(
    request: Request,
    x_vxt_signature: Optional[str] = Header(None, alias="X-VXT-Signature"),
    db: AsyncSession = Depends(get_db)
):
    """
    Receive VXT webhook events.
    
    This endpoint is publicly accessible but protected by signature verification.
    
    **Supported Events:**
    - call.completed: New call with recording
    - call.transcribed: Transcript ready
    - call.recording_ready: Recording available
    
    **Headers:**
    - X-VXT-Signature: HMAC-SHA256 signature of payload
    """
    # Read raw body for signature verification
    body = await request.body()
    
    # Parse JSON payload
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"Invalid webhook JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    # Initialize service
    service = VXTWebhookService(db)
    
    # Verify signature
    signature_valid = service.verify_signature(body, x_vxt_signature or "")
    
    if not signature_valid:
        logger.warning(f"Invalid webhook signature for call {payload.get('call_id')}")
        # Still process but log the invalid signature
    
    # Process webhook
    event_type = payload.get('event_type', 'unknown')
    
    try:
        result = await service.process_webhook(
            event_type=event_type,
            payload=payload,
            signature_valid=signature_valid
        )
        
        return {
            "success": True,
            "event_type": event_type,
            "result": result
        }
        
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== CALL ENDPOINTS ====================

@router.get("/calls")
async def list_calls(
    client_id: Optional[int] = Query(None, description="Filter by matched client ID"),
    direction: Optional[str] = Query(None, description="Filter by direction (inbound/outbound)"),
    from_date: Optional[datetime] = Query(None, description="Filter from date"),
    to_date: Optional[datetime] = Query(None, description="Filter to date"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: AuthUser = Depends(require_vxt_access),
    db: AsyncSession = Depends(get_db)
):
    """
    List VXT calls with filters.
    
    **Permissions:** admin, staff, tax_agent
    """
    service = VXTCallService(db)
    
    calls = await service.get_calls(
        client_id=client_id,
        direction=direction,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset
    )
    
    return calls


@router.get("/calls/{call_id}")
async def get_call(
    call_id: int,
    current_user: AuthUser = Depends(require_vxt_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a single call with transcript and recording details.
    
    **Permissions:** admin, staff, tax_agent
    """
    service = VXTCallService(db)
    
    call = await service.get_call(call_id)
    
    if not call:
        raise HTTPException(status_code=404, detail=f"Call {call_id} not found")
    
    return call


@router.get("/calls/by-vxt-id/{vxt_call_id}")
async def get_call_by_vxt_id(
    vxt_call_id: str,
    current_user: AuthUser = Depends(require_vxt_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a call by VXT call ID.
    
    **Permissions:** admin, staff, tax_agent
    """
    service = VXTCallService(db)
    
    call = await service.get_call_by_vxt_id(vxt_call_id)
    
    if not call:
        raise HTTPException(status_code=404, detail=f"Call {vxt_call_id} not found")
    
    return call


# ==================== RECORDING ENDPOINT ====================

@router.get("/recording/{call_id}")
async def stream_recording(
    call_id: int,
    current_user: AuthUser = Depends(require_vxt_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Stream audio recording for a call.
    
    Redirects to VXT recording URL or streams from local storage.
    
    **Permissions:** admin, staff, tax_agent
    """
    service = VXTCallService(db)
    
    recording = await service.get_recording(call_id)
    
    if not recording:
        raise HTTPException(status_code=404, detail=f"Recording not found for call {call_id}")
    
    # If we have local storage, stream from there
    if recording.get('local_storage_path') and os.path.exists(recording['local_storage_path']):
        def iterfile():
            with open(recording['local_storage_path'], 'rb') as f:
                while chunk := f.read(65536):
                    yield chunk
        
        return StreamingResponse(
            iterfile(),
            media_type="audio/mpeg",
            headers={"Content-Disposition": f"inline; filename=call_{call_id}.mp3"}
        )
    
    # Otherwise redirect to VXT URL
    if recording.get('recording_url'):
        return RedirectResponse(url=recording['recording_url'])
    
    raise HTTPException(status_code=404, detail="Recording URL not available")


# ==================== WORKPAPER LINK ENDPOINT ====================

@router.post("/calls/{call_id}/link-workpaper")
async def link_call_to_workpaper(
    call_id: int,
    request: LinkWorkpaperRequest,
    current_user: AuthUser = Depends(require_vxt_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Link a call to a workpaper.
    
    **Permissions:** admin, staff, tax_agent
    """
    service = VXTCallService(db)
    
    # Verify call exists
    call = await service.get_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail=f"Call {call_id} not found")
    
    result = await service.link_to_workpaper(
        call_id=call_id,
        workpaper_id=request.workpaper_id,
        user_id=current_user.id,
        link_type="manual",
        notes=request.notes
    )
    
    return {
        "success": True,
        "message": "Call linked to workpaper",
        "result": result
    }


# ==================== STATS ENDPOINT ====================

@router.get("/stats")
async def get_vxt_stats(
    current_user: AuthUser = Depends(require_vxt_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Get VXT integration statistics.
    
    **Permissions:** admin, staff, tax_agent
    """
    from sqlalchemy import text
    
    # Total calls
    total_result = await db.execute(text("SELECT COUNT(*) FROM vxt_calls"))
    total_calls = total_result.scalar()
    
    # Matched calls
    matched_result = await db.execute(text("SELECT COUNT(*) FROM vxt_calls WHERE matched_client_id IS NOT NULL"))
    matched_calls = matched_result.scalar()
    
    # Calls with transcripts
    transcript_result = await db.execute(text("SELECT COUNT(*) FROM vxt_transcripts"))
    with_transcripts = transcript_result.scalar()
    
    # Calls with recordings
    recording_result = await db.execute(text("SELECT COUNT(*) FROM vxt_recordings"))
    with_recordings = recording_result.scalar()
    
    # Recent webhooks
    webhook_result = await db.execute(text("""
        SELECT COUNT(*), COUNT(*) FILTER (WHERE signature_valid = true)
        FROM vxt_webhook_log
        WHERE received_at > NOW() - INTERVAL '24 hours'
    """))
    webhook_row = webhook_result.fetchone()
    
    return {
        "total_calls": total_calls,
        "matched_calls": matched_calls,
        "match_rate": round((matched_calls / total_calls * 100) if total_calls > 0 else 0, 2),
        "with_transcripts": with_transcripts,
        "with_recordings": with_recordings,
        "webhooks_24h": {
            "total": webhook_row[0] if webhook_row else 0,
            "valid_signature": webhook_row[1] if webhook_row else 0
        }
    }
