"""
Calendly Integration API Router

Endpoints for Calendly webhooks and appointment management.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
import logging

from database import get_db
from services.calendly import (
    CalendlyService,
    CalendlyWebhookPayload,
    Appointment,
    AppointmentFilter,
    AppointmentStats,
    AppointmentStatus,
    CalendlyClient,
    CALENDLY_WEBHOOK_SECRET
)
from middleware.auth import get_current_user, get_current_user_required, require_staff, require_admin, AuthUser

logger = logging.getLogger(__name__)

# Create router for integrations
integrations_router = APIRouter(prefix="/integrations", tags=["Integrations"])

# Create router for appointments
appointments_router = APIRouter(prefix="/appointments", tags=["Appointments"])


# ==================== CALENDLY WEBHOOK ====================

@integrations_router.post("/calendly/webhook")
async def calendly_webhook(
    request: Request,
    calendly_webhook_signature: Optional[str] = Header(None, alias="Calendly-Webhook-Signature"),
    db: AsyncSession = Depends(get_db)
):
    """
    Webhook endpoint for Calendly events.
    
    Calendly sends events when:
    - `invitee.created`: A new booking is made
    - `invitee.canceled`: A booking is cancelled
    
    **Webhook Setup:**
    1. Go to Calendly Developer Portal → Webhooks
    2. Create webhook subscription with URL: `{your-domain}/api/integrations/calendly/webhook`
    3. Subscribe to events: `invitee.created`, `invitee.canceled`
    4. (Optional) Set signing key for signature validation
    
    **Signature Validation:**
    If CALENDLY_WEBHOOK_SECRET is configured, the webhook signature will be validated.
    """
    try:
        # Get raw body for signature verification
        body = await request.body()
        
        # Verify signature if configured
        calendly_service = CalendlyService(db)
        if CALENDLY_WEBHOOK_SECRET and calendly_webhook_signature:
            if not calendly_service.verify_webhook_signature(body, calendly_webhook_signature):
                logger.warning("Invalid Calendly webhook signature")
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
        
        # Parse JSON payload
        try:
            import json
            data = json.loads(body)
        except Exception as e:
            logger.error(f"Failed to parse webhook payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON payload")
        
        # Extract event type and payload
        event_type = data.get("event")
        payload = data.get("payload", {})
        
        if not event_type:
            raise HTTPException(status_code=400, detail="Missing event type")
        
        # Process the webhook
        result = await calendly_service.process_webhook(event_type, payload)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing Calendly webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@integrations_router.get("/calendly/status")
async def calendly_status(
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Check Calendly integration status.
    
    Verifies the PAT is valid and returns current user info.
    """
    try:
        client = CalendlyClient()
        user = await client.get_current_user()
        
        if user:
            return {
                "connected": True,
                "user": {
                    "name": user.get("name"),
                    "email": user.get("email"),
                    "scheduling_url": user.get("scheduling_url"),
                    "timezone": user.get("timezone")
                },
                "webhook_secret_configured": bool(CALENDLY_WEBHOOK_SECRET)
            }
        else:
            return {
                "connected": False,
                "error": "Could not verify Calendly credentials",
                "webhook_secret_configured": bool(CALENDLY_WEBHOOK_SECRET)
            }
            
    except Exception as e:
        logger.error(f"Error checking Calendly status: {e}")
        return {
            "connected": False,
            "error": str(e),
            "webhook_secret_configured": bool(CALENDLY_WEBHOOK_SECRET)
        }


# ==================== APPOINTMENT ENDPOINTS ====================

@appointments_router.get("/admin", response_model=List[Appointment])
async def list_all_appointments(
    status: Optional[str] = Query(None, description="Filter by status"),
    client_id: Optional[str] = Query(None, description="Filter by client ID"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    List all appointments (staff/admin).
    
    **Filter Examples:**
    - `/api/appointments/admin?status=scheduled` - Only scheduled
    - `/api/appointments/admin?client_id=uuid` - Specific client
    - `/api/appointments/admin?start_date=2025-01-01&end_date=2025-01-31` - Date range
    """
    try:
        calendly_service = CalendlyService(db)
        
        filter_params = AppointmentFilter(
            status=status,
            client_id=client_id,
            event_type=event_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset
        )
        
        return await calendly_service.list_appointments(filter_params)
        
    except Exception as e:
        logger.error(f"Error listing appointments: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@appointments_router.get("/admin/stats", response_model=AppointmentStats)
async def get_appointment_stats(
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get appointment statistics.
    """
    try:
        calendly_service = CalendlyService(db)
        return calendly_service.get_stats()
        
    except Exception as e:
        logger.error(f"Error getting appointment stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@appointments_router.get("/admin/upcoming", response_model=List[Appointment])
async def get_upcoming_appointments(
    days: int = Query(7, description="Number of days ahead to look"),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get upcoming appointments in the next N days.
    """
    try:
        calendly_service = CalendlyService(db)
        return await calendly_service.get_upcoming_appointments(days)
        
    except Exception as e:
        logger.error(f"Error getting upcoming appointments: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@appointments_router.get("/admin/{appointment_id}", response_model=Appointment)
async def get_appointment(
    appointment_id: str,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific appointment by ID.
    """
    try:
        calendly_service = CalendlyService(db)
        appointment = await calendly_service.get_appointment(appointment_id)
        
        if not appointment:
            raise HTTPException(status_code=404, detail="Appointment not found")
        
        return appointment
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting appointment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@appointments_router.patch("/admin/{appointment_id}/status")
async def update_appointment_status(
    appointment_id: str,
    status: str = Query(..., description="New status (scheduled, completed, cancelled, no_show)"),
    notes: Optional[str] = Query(None, description="Optional notes"),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Update appointment status.
    
    Use this to mark appointments as completed, cancelled, or no-show.
    """
    valid_statuses = [s.value for s in AppointmentStatus]
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {valid_statuses}"
        )
    
    try:
        calendly_service = CalendlyService(db)
        appointment = await calendly_service.update_appointment_status(
            appointment_id=appointment_id,
            status=status,
            notes=notes
        )
        
        if not appointment:
            raise HTTPException(status_code=404, detail="Appointment not found")
        
        return {
            "success": True,
            "appointment_id": appointment_id,
            "new_status": status,
            "message": f"Appointment status updated to {status}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating appointment status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@appointments_router.get("/client/{client_id}", response_model=List[Appointment])
async def get_client_appointments(
    client_id: str,
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(20, le=100),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all appointments for a specific client.
    """
    try:
        calendly_service = CalendlyService(db)
        
        filter_params = AppointmentFilter(
            client_id=client_id,
            status=status,
            limit=limit
        )
        
        return await calendly_service.list_appointments(filter_params)
        
    except Exception as e:
        logger.error(f"Error getting client appointments: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@appointments_router.get("/my-appointments", response_model=List[Appointment])
async def get_my_appointments(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(20, le=100),
    current_user: AuthUser = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current user's appointments.
    """
    try:
        calendly_service = CalendlyService(db)
        
        filter_params = AppointmentFilter(
            client_id=current_user.id,
            status=status,
            limit=limit
        )
        
        return await calendly_service.list_appointments(filter_params)
        
    except Exception as e:
        logger.error(f"Error getting user appointments: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== UTILITY ENDPOINTS ====================

@appointments_router.get("/statuses")
async def list_appointment_statuses():
    """
    List all available appointment statuses.
    """
    return {
        "statuses": [s.value for s in AppointmentStatus],
        "descriptions": {
            "scheduled": "Appointment is booked and upcoming",
            "completed": "Appointment has been completed",
            "cancelled": "Appointment was cancelled",
            "no_show": "Client did not show up",
            "rescheduled": "Appointment was rescheduled"
        }
    }


# ==================== MANUAL APPOINTMENT CREATION ====================

@appointments_router.post("/admin/create", response_model=Appointment)
async def create_manual_appointment(
    client_email: str = Query(..., description="Client email"),
    client_name: Optional[str] = Query(None, description="Client name"),
    event_type: str = Query(..., description="Event type name"),
    scheduled_for: str = Query(..., description="ISO datetime for appointment"),
    duration_minutes: int = Query(30, description="Duration in minutes"),
    location: Optional[str] = Query(None, description="Meeting location or URL"),
    location_type: Optional[str] = Query("phone", description="Location type (phone, video, in_person)"),
    notes: Optional[str] = Query(None, description="Additional notes"),
    create_task: bool = Query(True, description="Create CRM task for appointment"),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually create an appointment (not from Calendly webhook).
    
    Useful for appointments booked outside of Calendly.
    """
    try:
        from datetime import timedelta
        from services.calendly import Appointment, AppointmentStorage
        from services.audit import log_action, AuditAction, ResourceType
        
        calendly_service = CalendlyService(db)
        storage = AppointmentStorage()
        
        # Find client by email
        client_id = await calendly_service.find_client_by_email(client_email)
        
        # Calculate end time
        from datetime import datetime, timezone as tz
        try:
            start_dt = datetime.fromisoformat(scheduled_for.replace('Z', '+00:00'))
            end_dt = start_dt + timedelta(minutes=duration_minutes)
            end_time = end_dt.isoformat()
        except Exception:
            end_time = None
        
        # Create appointment
        appointment = Appointment(
            client_id=client_id,
            client_email=client_email,
            client_name=client_name,
            event_type=event_type,
            event_type_name=event_type,
            scheduled_for=scheduled_for,
            end_time=end_time,
            duration_minutes=duration_minutes,
            location=location,
            location_type=location_type,
            notes=notes,
            status=AppointmentStatus.scheduled.value
        )
        
        # Create CRM task if requested and client found
        if create_task and client_id:
            task_id = await calendly_service.create_appointment_task(appointment, created_by=current_user.id)
            if task_id:
                appointment.task_id = task_id
        
        # Save appointment
        storage.create(appointment)
        
        # Audit log
        log_action(
            action=AuditAction.APPOINTMENT_BOOKED,
            resource_type=ResourceType.APPOINTMENT,
            resource_id=appointment.id,
            user_id=current_user.id,
            user_email=current_user.email,
            details={
                "event_type": event_type,
                "scheduled_for": scheduled_for,
                "client_email": client_email,
                "manual_creation": True
            }
        )
        
        return appointment
        
    except Exception as e:
        logger.error(f"Error creating manual appointment: {e}")
        raise HTTPException(status_code=500, detail=str(e))
