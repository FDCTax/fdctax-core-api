"""
Calendly Integration Service for FDC Tax CRM

Handles Calendly webhooks for appointment visibility and task creation.

Features:
- Webhook endpoint for Calendly events
- Signature validation for security
- Appointment record management
- CRM task creation for appointments
- Audit logging for all booking events

Storage: appointments.json (file-based, can migrate to DB later)
"""

import json
import uuid
import hmac
import hashlib
import httpx
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from pathlib import Path
import logging
import os
from enum import Enum
from pydantic import BaseModel, Field

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from services.audit import log_action, AuditAction, ResourceType

logger = logging.getLogger(__name__)

# Storage paths
DATA_DIR = Path(__file__).parent.parent / "data"
APPOINTMENTS_FILE = DATA_DIR / "appointments.json"

# Calendly API configuration
CALENDLY_API_BASE = "https://api.calendly.com"
CALENDLY_PAT = os.environ.get("CALENDLY_PAT", "")
CALENDLY_WEBHOOK_SECRET = os.environ.get("CALENDLY_WEBHOOK_SECRET", "")

# Default assignee for appointment tasks
DEFAULT_APPOINTMENT_ASSIGNEE = "admin@fdctax.com"


# ==================== MODELS ====================

class AppointmentStatus(str, Enum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"
    rescheduled = "rescheduled"


class Appointment(BaseModel):
    """Appointment record"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    calendly_event_uri: Optional[str] = None
    calendly_invitee_uri: Optional[str] = None
    client_id: Optional[str] = None
    client_email: str
    client_name: Optional[str] = None
    event_type: str
    event_type_name: Optional[str] = None
    scheduled_for: str  # ISO datetime
    end_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    location: Optional[str] = None
    location_type: Optional[str] = None  # physical, phone, google_meet, zoom, etc.
    meeting_url: Optional[str] = None
    status: str = AppointmentStatus.scheduled.value
    notes: Optional[str] = None
    questions_and_answers: Optional[List[Dict]] = None
    task_id: Optional[str] = None  # Associated CRM task
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    cancellation_reason: Optional[str] = None


class AppointmentFilter(BaseModel):
    """Filter for querying appointments"""
    client_id: Optional[str] = None
    status: Optional[str] = None
    event_type: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    limit: int = 50
    offset: int = 0


class AppointmentStats(BaseModel):
    """Statistics for appointments"""
    total: int
    scheduled: int
    completed: int
    cancelled: int
    no_show: int
    upcoming_7_days: int
    by_event_type: Dict[str, int]


class CalendlyWebhookPayload(BaseModel):
    """Calendly webhook event payload"""
    event: str  # invitee.created, invitee.canceled
    payload: Dict[str, Any]
    created_at: Optional[str] = None


# ==================== APPOINTMENT STORAGE ====================

class AppointmentStorage:
    """File-based storage for appointments"""
    
    def __init__(self, file_path: Path = APPOINTMENTS_FILE):
        self.file_path = file_path
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._save_appointments([])
    
    def _load_appointments(self) -> List[Dict]:
        try:
            with open(self.file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading appointments: {e}")
            return []
    
    def _save_appointments(self, appointments: List[Dict]):
        with open(self.file_path, 'w') as f:
            json.dump(appointments, f, indent=2, default=str)
    
    def create(self, appointment: Appointment) -> Appointment:
        """Save a new appointment"""
        appointments = self._load_appointments()
        appointments.append(appointment.model_dump())
        self._save_appointments(appointments)
        return appointment
    
    def get(self, appointment_id: str) -> Optional[Appointment]:
        """Get appointment by ID"""
        appointments = self._load_appointments()
        for a in appointments:
            if a.get('id') == appointment_id:
                return Appointment(**a)
        return None
    
    def get_by_calendly_event(self, calendly_event_uri: str) -> Optional[Appointment]:
        """Get appointment by Calendly event URI"""
        appointments = self._load_appointments()
        for a in appointments:
            if a.get('calendly_event_uri') == calendly_event_uri:
                return Appointment(**a)
        return None
    
    def get_by_invitee_email(self, email: str, event_uri: str) -> Optional[Appointment]:
        """Get appointment by invitee email and event URI"""
        appointments = self._load_appointments()
        for a in appointments:
            if a.get('client_email') == email and a.get('calendly_event_uri') == event_uri:
                return Appointment(**a)
        return None
    
    def update(self, appointment_id: str, updates: Dict[str, Any]) -> Optional[Appointment]:
        """Update an appointment"""
        appointments = self._load_appointments()
        for i, a in enumerate(appointments):
            if a.get('id') == appointment_id:
                updates['updated_at'] = datetime.now(timezone.utc).isoformat()
                appointments[i].update(updates)
                self._save_appointments(appointments)
                return Appointment(**appointments[i])
        return None
    
    def list(self, filter_params: AppointmentFilter) -> List[Appointment]:
        """List appointments with filters"""
        appointments = self._load_appointments()
        
        # Apply filters
        if filter_params.client_id:
            appointments = [a for a in appointments if a.get('client_id') == filter_params.client_id]
        
        if filter_params.status:
            appointments = [a for a in appointments if a.get('status') == filter_params.status]
        
        if filter_params.event_type:
            appointments = [a for a in appointments if filter_params.event_type.lower() in a.get('event_type', '').lower()]
        
        if filter_params.start_date:
            appointments = [a for a in appointments if a.get('scheduled_for', '')[:10] >= filter_params.start_date]
        
        if filter_params.end_date:
            appointments = [a for a in appointments if a.get('scheduled_for', '')[:10] <= filter_params.end_date]
        
        # Sort by scheduled_for descending (most recent first)
        appointments.sort(key=lambda x: x.get('scheduled_for', ''), reverse=True)
        
        # Pagination
        start = filter_params.offset
        end = start + filter_params.limit
        
        return [Appointment(**a) for a in appointments[start:end]]
    
    def list_upcoming(self, days: int = 7) -> List[Appointment]:
        """List upcoming appointments in the next N days"""
        appointments = self._load_appointments()
        now = datetime.now(timezone.utc)
        future = now.isoformat()
        future_end = (now.replace(hour=23, minute=59, second=59) + 
                      __import__('datetime').timedelta(days=days)).isoformat()
        
        upcoming = [
            a for a in appointments 
            if a.get('status') == AppointmentStatus.scheduled.value
            and a.get('scheduled_for', '') >= future
            and a.get('scheduled_for', '') <= future_end
        ]
        
        upcoming.sort(key=lambda x: x.get('scheduled_for', ''))
        return [Appointment(**a) for a in upcoming]
    
    def get_stats(self) -> AppointmentStats:
        """Get appointment statistics"""
        appointments = self._load_appointments()
        
        now = datetime.now(timezone.utc)
        week_ahead = (now + __import__('datetime').timedelta(days=7)).isoformat()
        
        total = len(appointments)
        scheduled = len([a for a in appointments if a.get('status') == AppointmentStatus.scheduled.value])
        completed = len([a for a in appointments if a.get('status') == AppointmentStatus.completed.value])
        cancelled = len([a for a in appointments if a.get('status') == AppointmentStatus.cancelled.value])
        no_show = len([a for a in appointments if a.get('status') == AppointmentStatus.no_show.value])
        
        upcoming_7_days = len([
            a for a in appointments 
            if a.get('status') == AppointmentStatus.scheduled.value
            and a.get('scheduled_for', '') >= now.isoformat()
            and a.get('scheduled_for', '') <= week_ahead
        ])
        
        # By event type
        by_event_type = {}
        for a in appointments:
            et = a.get('event_type_name') or a.get('event_type', 'Unknown')
            by_event_type[et] = by_event_type.get(et, 0) + 1
        
        return AppointmentStats(
            total=total,
            scheduled=scheduled,
            completed=completed,
            cancelled=cancelled,
            no_show=no_show,
            upcoming_7_days=upcoming_7_days,
            by_event_type=by_event_type
        )


# ==================== CALENDLY API CLIENT ====================

class CalendlyClient:
    """Client for Calendly API"""
    
    def __init__(self, pat: str = CALENDLY_PAT):
        self.pat = pat
        self.base_url = CALENDLY_API_BASE
        self.headers = {
            "Authorization": f"Bearer {self.pat}",
            "Content-Type": "application/json"
        }
    
    async def get_current_user(self) -> Optional[Dict]:
        """Get current authenticated user"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/users/me",
                    headers=self.headers,
                    timeout=30.0
                )
                if response.status_code == 200:
                    return response.json().get("resource")
                else:
                    logger.error(f"Calendly API error: {response.status_code} - {response.text}")
                    return None
        except Exception as e:
            logger.error(f"Error calling Calendly API: {e}")
            return None
    
    async def get_event(self, event_uri: str) -> Optional[Dict]:
        """Get event details by URI"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    event_uri,
                    headers=self.headers,
                    timeout=30.0
                )
                if response.status_code == 200:
                    return response.json().get("resource")
                else:
                    logger.error(f"Calendly event fetch error: {response.status_code}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching Calendly event: {e}")
            return None
    
    async def get_event_type(self, event_type_uri: str) -> Optional[Dict]:
        """Get event type details"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    event_type_uri,
                    headers=self.headers,
                    timeout=30.0
                )
                if response.status_code == 200:
                    return response.json().get("resource")
                else:
                    logger.error(f"Calendly event type fetch error: {response.status_code}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching Calendly event type: {e}")
            return None
    
    async def get_invitee(self, invitee_uri: str) -> Optional[Dict]:
        """Get invitee details"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    invitee_uri,
                    headers=self.headers,
                    timeout=30.0
                )
                if response.status_code == 200:
                    return response.json().get("resource")
                else:
                    logger.error(f"Calendly invitee fetch error: {response.status_code}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching Calendly invitee: {e}")
            return None


# ==================== CALENDLY SERVICE ====================

class CalendlyService:
    """
    Service for Calendly integration.
    Handles webhooks, appointment creation, and CRM task generation.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.storage = AppointmentStorage()
        self.calendly = CalendlyClient()
    
    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        secret: str = CALENDLY_WEBHOOK_SECRET
    ) -> bool:
        """
        Verify Calendly webhook signature.
        Calendly uses HMAC-SHA256.
        """
        if not secret:
            logger.warning("Calendly webhook secret not configured, skipping signature validation")
            return True
        
        try:
            # Calendly signature format: t=timestamp,v1=signature
            parts = dict(p.split('=') for p in signature.split(','))
            timestamp = parts.get('t', '')
            v1_signature = parts.get('v1', '')
            
            # Create signed payload
            signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
            
            # Calculate expected signature
            expected = hmac.new(
                secret.encode('utf-8'),
                signed_payload.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(expected, v1_signature)
        except Exception as e:
            logger.error(f"Webhook signature verification failed: {e}")
            return False
    
    async def find_client_by_email(self, email: str) -> Optional[str]:
        """Find client_id by email address"""
        try:
            query = text("""
                SELECT id FROM myfdc.users 
                WHERE LOWER(email) = LOWER(:email)
                LIMIT 1
            """)
            result = await self.db.execute(query, {"email": email})
            row = result.fetchone()
            if row:
                return str(row.id)
        except Exception as e:
            logger.warning(f"Error finding client by email: {e}")
        return None
    
    async def create_appointment_task(
        self,
        appointment: Appointment,
        created_by: Optional[str] = None
    ) -> Optional[str]:
        """Create a CRM task for the appointment"""
        try:
            task_id = str(uuid.uuid4())
            
            # Format the scheduled time
            scheduled_dt = datetime.fromisoformat(appointment.scheduled_for.replace('Z', '+00:00'))
            formatted_time = scheduled_dt.strftime('%B %d, %Y at %I:%M %p')
            
            # Build task description
            description = f"""
══════════════════════════════════════════════════════
CALENDLY APPOINTMENT
══════════════════════════════════════════════════════

Client: {appointment.client_name or 'Unknown'}
Email: {appointment.client_email}
Event Type: {appointment.event_type_name or appointment.event_type}
Scheduled: {formatted_time}
Duration: {appointment.duration_minutes or 'N/A'} minutes

──────────────────────────────────────────────────────
LOCATION
──────────────────────────────────────────────────────
Type: {appointment.location_type or 'Not specified'}
{f'Location: {appointment.location}' if appointment.location else ''}
{f'Meeting URL: {appointment.meeting_url}' if appointment.meeting_url else ''}

{self._format_questions(appointment.questions_and_answers) if appointment.questions_and_answers else ''}

══════════════════════════════════════════════════════
Appointment ID: {appointment.id}
Booked at: {appointment.created_at}
"""
            
            query = text("""
                INSERT INTO myfdc.user_tasks 
                (id, user_id, task_name, description, due_date, status, priority, category, task_type, created_at)
                VALUES (
                    CAST(:id AS uuid), 
                    CAST(:user_id AS uuid), 
                    :task_name, 
                    :description, 
                    :due_date, 
                    :status, 
                    :priority, 
                    :category, 
                    :task_type, 
                    :created_at
                )
                RETURNING id
            """)
            
            params = {
                "id": task_id,
                "user_id": appointment.client_id,
                "task_name": f"Upcoming: {appointment.event_type_name or appointment.event_type} with {appointment.client_name or appointment.client_email}",
                "description": description.strip(),
                "due_date": scheduled_dt.date(),
                "status": "pending",
                "priority": "normal",
                "category": "appointment",
                "task_type": "calendly_appointment",
                "created_at": datetime.now(timezone.utc)
            }
            
            result = await self.db.execute(query, params)
            await self.db.commit()
            
            if result.fetchone():
                logger.info(f"Created appointment task {task_id}")
                return task_id
            
        except Exception as e:
            logger.error(f"Error creating appointment task: {e}")
            await self.db.rollback()
        
        return None
    
    def _format_questions(self, questions: List[Dict]) -> str:
        """Format Q&A from booking form"""
        if not questions:
            return ""
        
        lines = ["──────────────────────────────────────────────────────", "BOOKING QUESTIONS", "──────────────────────────────────────────────────────"]
        for q in questions:
            question = q.get('question', '')
            answer = q.get('answer', 'No answer')
            lines.append(f"Q: {question}")
            lines.append(f"A: {answer}")
            lines.append("")
        
        return "\n".join(lines)
    
    async def handle_invitee_created(
        self,
        payload: Dict[str, Any],
        created_by: Optional[str] = None
    ) -> Appointment:
        """
        Handle invitee.created webhook event.
        Creates appointment record and optional CRM task.
        """
        # Extract data from webhook payload
        invitee = payload.get("invitee", {})
        event = payload.get("event", {})
        scheduled_event = payload.get("scheduled_event", {})
        
        # Get URIs for API calls
        event_uri = scheduled_event.get("uri") or event.get("uri")
        invitee_uri = invitee.get("uri")
        
        # Extract invitee info
        invitee_email = invitee.get("email", "")
        invitee_name = invitee.get("name", "")
        
        # Extract event info
        event_type = scheduled_event.get("name") or event.get("name", "Meeting")
        start_time = scheduled_event.get("start_time") or event.get("start_time")
        end_time = scheduled_event.get("end_time") or event.get("end_time")
        
        # Get location info
        location = scheduled_event.get("location", {})
        location_type = location.get("type") if isinstance(location, dict) else None
        location_str = location.get("location") if isinstance(location, dict) else str(location) if location else None
        meeting_url = location.get("join_url") if isinstance(location, dict) else None
        
        # Calculate duration
        duration = None
        if start_time and end_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                duration = int((end_dt - start_dt).total_seconds() / 60)
            except Exception:
                pass
        
        # Get Q&A from booking
        questions = invitee.get("questions_and_answers", [])
        
        # Try to fetch additional details from Calendly API
        event_type_name = event_type
        if event_uri:
            try:
                event_details = await self.calendly.get_event(event_uri)
                if event_details:
                    event_type_uri = event_details.get("event_type")
                    if event_type_uri:
                        event_type_info = await self.calendly.get_event_type(event_type_uri)
                        if event_type_info:
                            event_type_name = event_type_info.get("name", event_type)
            except Exception as e:
                logger.warning(f"Could not fetch event type details: {e}")
        
        # Match email to client
        client_id = await self.find_client_by_email(invitee_email)
        
        # Check for existing appointment (avoid duplicates)
        if event_uri:
            existing = self.storage.get_by_invitee_email(invitee_email, event_uri)
            if existing:
                logger.info(f"Appointment already exists for {invitee_email} / {event_uri}")
                return existing
        
        # Create appointment record
        appointment = Appointment(
            calendly_event_uri=event_uri,
            calendly_invitee_uri=invitee_uri,
            client_id=client_id,
            client_email=invitee_email,
            client_name=invitee_name,
            event_type=event_type,
            event_type_name=event_type_name,
            scheduled_for=start_time or datetime.now(timezone.utc).isoformat(),
            end_time=end_time,
            duration_minutes=duration,
            location=location_str,
            location_type=location_type,
            meeting_url=meeting_url,
            questions_and_answers=questions,
            status=AppointmentStatus.scheduled.value
        )
        
        # Create CRM task if client found
        if client_id:
            task_id = await self.create_appointment_task(appointment, created_by)
            if task_id:
                appointment.task_id = task_id
        
        # Save appointment
        self.storage.create(appointment)
        
        # Audit log
        log_action(
            action=AuditAction.APPOINTMENT_BOOKED,
            resource_type=ResourceType.APPOINTMENT,
            resource_id=appointment.id,
            user_id=client_id,
            user_email=invitee_email,
            details={
                "event_type": event_type_name,
                "scheduled_for": start_time,
                "duration_minutes": duration,
                "client_name": invitee_name,
                "location_type": location_type,
                "task_created": appointment.task_id is not None
            }
        )
        
        logger.info(f"Appointment created: {appointment.id} for {invitee_email}")
        return appointment
    
    async def handle_invitee_canceled(
        self,
        payload: Dict[str, Any]
    ) -> Optional[Appointment]:
        """Handle invitee.canceled webhook event"""
        invitee = payload.get("invitee", {})
        event = payload.get("event", {}) or payload.get("scheduled_event", {})
        
        invitee_email = invitee.get("email", "")
        event_uri = event.get("uri")
        cancellation = invitee.get("cancellation", {})
        
        if not event_uri:
            logger.warning("No event URI in cancellation webhook")
            return None
        
        # Find the appointment
        appointment = self.storage.get_by_invitee_email(invitee_email, event_uri)
        if not appointment:
            logger.warning(f"No appointment found for cancellation: {invitee_email} / {event_uri}")
            return None
        
        # Update appointment
        updates = {
            "status": AppointmentStatus.cancelled.value,
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
            "cancellation_reason": cancellation.get("reason") or cancellation.get("canceler_type")
        }
        
        appointment = self.storage.update(appointment.id, updates)
        
        # Update associated task if exists
        if appointment and appointment.task_id:
            try:
                query = text("""
                    UPDATE myfdc.user_tasks 
                    SET status = 'cancelled', updated_at = :updated_at
                    WHERE id = CAST(:task_id AS uuid)
                """)
                await self.db.execute(query, {
                    "task_id": appointment.task_id,
                    "updated_at": datetime.now(timezone.utc)
                })
                await self.db.commit()
            except Exception as e:
                logger.error(f"Error updating task on cancellation: {e}")
        
        # Audit log
        if appointment:
            log_action(
                action=AuditAction.APPOINTMENT_CANCELLED,
                resource_type=ResourceType.APPOINTMENT,
                resource_id=appointment.id,
                user_id=appointment.client_id,
                user_email=invitee_email,
                details={
                    "event_type": appointment.event_type_name,
                    "scheduled_for": appointment.scheduled_for,
                    "cancellation_reason": updates.get("cancellation_reason")
                }
            )
        
        logger.info(f"Appointment cancelled: {appointment.id if appointment else 'unknown'}")
        return appointment
    
    async def process_webhook(
        self,
        event_type: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process a Calendly webhook event"""
        logger.info(f"Processing Calendly webhook: {event_type}")
        
        if event_type == "invitee.created":
            appointment = await self.handle_invitee_created(payload)
            return {
                "success": True,
                "event": event_type,
                "appointment_id": appointment.id,
                "client_email": appointment.client_email,
                "scheduled_for": appointment.scheduled_for
            }
        
        elif event_type == "invitee.canceled":
            appointment = await self.handle_invitee_canceled(payload)
            return {
                "success": True,
                "event": event_type,
                "appointment_id": appointment.id if appointment else None,
                "status": "cancelled"
            }
        
        else:
            logger.warning(f"Unhandled Calendly event type: {event_type}")
            return {
                "success": True,
                "event": event_type,
                "status": "ignored",
                "message": f"Event type '{event_type}' not handled"
            }
    
    async def get_appointment(self, appointment_id: str) -> Optional[Appointment]:
        """Get appointment by ID"""
        return self.storage.get(appointment_id)
    
    async def list_appointments(
        self,
        filter_params: Optional[AppointmentFilter] = None
    ) -> List[Appointment]:
        """List appointments with filters"""
        if filter_params is None:
            filter_params = AppointmentFilter()
        return self.storage.list(filter_params)
    
    async def get_client_appointments(
        self,
        client_id: str,
        limit: int = 20
    ) -> List[Appointment]:
        """Get appointments for a specific client"""
        return self.storage.list(AppointmentFilter(client_id=client_id, limit=limit))
    
    async def update_appointment_status(
        self,
        appointment_id: str,
        status: str,
        notes: Optional[str] = None
    ) -> Optional[Appointment]:
        """Update appointment status"""
        updates = {"status": status}
        if notes:
            updates["notes"] = notes
        if status == AppointmentStatus.cancelled.value:
            updates["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        
        return self.storage.update(appointment_id, updates)
    
    def get_stats(self) -> AppointmentStats:
        """Get appointment statistics"""
        return self.storage.get_stats()
    
    async def get_upcoming_appointments(self, days: int = 7) -> List[Appointment]:
        """Get upcoming appointments"""
        return self.storage.list_upcoming(days)
