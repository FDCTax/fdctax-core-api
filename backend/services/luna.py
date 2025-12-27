"""
Luna Escalation Service for FDC Tax CRM

Handles escalation of queries from Luna AI to the FDC Tax team.
When Luna's confidence is low or the query is complex, it can escalate
to the white-glove team for human review.

Features:
- Create escalation tasks with full context
- Track escalation metadata (confidence, tags, luna response)
- Audit logging for all escalations
- Query escalations by various filters
"""

import json
import uuid
from datetime import datetime, date, timedelta, timezone
from typing import List, Optional, Dict, Any
from pathlib import Path
import logging
from enum import Enum
from pydantic import BaseModel, Field

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from services.audit import log_action, AuditAction, ResourceType
from services.crm_sync import CRMSyncService
from models import TaskCreate, TaskResponse, UserSettingsUpdate

logger = logging.getLogger(__name__)

# Storage for escalation metadata (supplements DB tasks)
DATA_DIR = Path(__file__).parent.parent / "data"
ESCALATIONS_FILE = DATA_DIR / "luna_escalations.json"

# Default assignee for escalations
DEFAULT_ESCALATION_ASSIGNEE = "luna@fdctax.com"


# ==================== MODELS ====================

class EscalationPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class EscalationStatus(str, Enum):
    open = "open"
    in_review = "in_review"
    resolved = "resolved"
    dismissed = "dismissed"


class LunaEscalationRequest(BaseModel):
    """Request to create a Luna escalation"""
    client_id: str  # User UUID
    query: str  # Original user query
    luna_response: str  # Luna's response before escalation
    confidence: float = Field(ge=0.0, le=1.0, description="Luna's confidence score (0-1)")
    tags: List[str] = Field(default_factory=list)
    priority: str = EscalationPriority.medium.value
    additional_context: Optional[str] = None


class LunaEscalation(BaseModel):
    """Luna escalation record"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str  # Reference to the created task
    client_id: str
    query: str
    luna_response: str
    confidence: float
    tags: List[str] = Field(default_factory=list)
    priority: str = EscalationPriority.medium.value
    status: str = EscalationStatus.open.value
    additional_context: Optional[str] = None
    assigned_to: str = DEFAULT_ESCALATION_ASSIGNEE
    resolution_notes: Optional[str] = None
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: Optional[str] = None


class EscalationResponse(BaseModel):
    """Response for escalation creation"""
    success: bool
    escalation_id: str
    task_id: str
    client_id: str
    message: str
    confidence: float
    priority: str
    tags: List[str]


class EscalationFilter(BaseModel):
    """Filter for querying escalations"""
    status: Optional[str] = None
    client_id: Optional[str] = None
    min_confidence: Optional[float] = None
    max_confidence: Optional[float] = None
    tag: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None
    start_date: Optional[str] = None  # ISO date
    end_date: Optional[str] = None
    limit: int = 50
    offset: int = 0


class EscalationStats(BaseModel):
    """Statistics for Luna escalations"""
    total: int
    open: int
    in_review: int
    resolved: int
    dismissed: int
    avg_confidence: float
    by_priority: Dict[str, int]
    by_tag: Dict[str, int]
    recent_24h: int


# ==================== ESCALATION STORAGE ====================

class EscalationStorage:
    """File-based storage for escalation metadata"""
    
    def __init__(self, file_path: Path = ESCALATIONS_FILE):
        self.file_path = file_path
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._save_escalations([])
    
    def _load_escalations(self) -> List[Dict]:
        try:
            with open(self.file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading escalations: {e}")
            return []
    
    def _save_escalations(self, escalations: List[Dict]):
        with open(self.file_path, 'w') as f:
            json.dump(escalations, f, indent=2, default=str)
    
    def create(self, escalation: LunaEscalation) -> LunaEscalation:
        """Save a new escalation"""
        escalations = self._load_escalations()
        escalations.append(escalation.model_dump())
        self._save_escalations(escalations)
        return escalation
    
    def get(self, escalation_id: str) -> Optional[LunaEscalation]:
        """Get escalation by ID"""
        escalations = self._load_escalations()
        for e in escalations:
            if e.get('id') == escalation_id:
                return LunaEscalation(**e)
        return None
    
    def get_by_task_id(self, task_id: str) -> Optional[LunaEscalation]:
        """Get escalation by task ID"""
        escalations = self._load_escalations()
        for e in escalations:
            if e.get('task_id') == task_id:
                return LunaEscalation(**e)
        return None
    
    def update(self, escalation_id: str, updates: Dict[str, Any]) -> Optional[LunaEscalation]:
        """Update an escalation"""
        escalations = self._load_escalations()
        for i, e in enumerate(escalations):
            if e.get('id') == escalation_id:
                updates['updated_at'] = datetime.now(timezone.utc).isoformat()
                escalations[i].update(updates)
                self._save_escalations(escalations)
                return LunaEscalation(**escalations[i])
        return None
    
    def list(self, filter_params: EscalationFilter) -> List[LunaEscalation]:
        """List escalations with filters"""
        escalations = self._load_escalations()
        
        # Apply filters
        if filter_params.status:
            escalations = [e for e in escalations if e.get('status') == filter_params.status]
        
        if filter_params.client_id:
            escalations = [e for e in escalations if e.get('client_id') == filter_params.client_id]
        
        if filter_params.min_confidence is not None:
            escalations = [e for e in escalations if e.get('confidence', 0) >= filter_params.min_confidence]
        
        if filter_params.max_confidence is not None:
            escalations = [e for e in escalations if e.get('confidence', 1) <= filter_params.max_confidence]
        
        if filter_params.tag:
            escalations = [e for e in escalations if filter_params.tag in e.get('tags', [])]
        
        if filter_params.priority:
            escalations = [e for e in escalations if e.get('priority') == filter_params.priority]
        
        if filter_params.assigned_to:
            escalations = [e for e in escalations if e.get('assigned_to') == filter_params.assigned_to]
        
        if filter_params.start_date:
            escalations = [e for e in escalations if e.get('created_at', '')[:10] >= filter_params.start_date]
        
        if filter_params.end_date:
            escalations = [e for e in escalations if e.get('created_at', '')[:10] <= filter_params.end_date]
        
        # Sort by created_at descending
        escalations.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        # Pagination
        start = filter_params.offset
        end = start + filter_params.limit
        
        return [LunaEscalation(**e) for e in escalations[start:end]]
    
    def get_stats(self) -> EscalationStats:
        """Get escalation statistics"""
        escalations = self._load_escalations()
        
        now = datetime.now(timezone.utc)
        yesterday = (now - timedelta(hours=24)).isoformat()
        
        total = len(escalations)
        open_count = len([e for e in escalations if e.get('status') == EscalationStatus.open.value])
        in_review = len([e for e in escalations if e.get('status') == EscalationStatus.in_review.value])
        resolved = len([e for e in escalations if e.get('status') == EscalationStatus.resolved.value])
        dismissed = len([e for e in escalations if e.get('status') == EscalationStatus.dismissed.value])
        
        # Average confidence
        confidences = [e.get('confidence', 0) for e in escalations if e.get('confidence') is not None]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0
        
        # By priority
        by_priority = {}
        for e in escalations:
            p = e.get('priority', 'medium')
            by_priority[p] = by_priority.get(p, 0) + 1
        
        # By tag
        by_tag = {}
        for e in escalations:
            for tag in e.get('tags', []):
                by_tag[tag] = by_tag.get(tag, 0) + 1
        
        # Recent 24h
        recent_24h = len([e for e in escalations if e.get('created_at', '') >= yesterday])
        
        return EscalationStats(
            total=total,
            open=open_count,
            in_review=in_review,
            resolved=resolved,
            dismissed=dismissed,
            avg_confidence=round(avg_confidence, 3),
            by_priority=by_priority,
            by_tag=by_tag,
            recent_24h=recent_24h
        )


# ==================== LUNA SERVICE ====================

class LunaService:
    """
    Service for Luna AI escalations to FDC Tax team.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.crm_service = CRMSyncService(db)
        self.storage = EscalationStorage()
    
    def _generate_task_title(self, query: str, confidence: float) -> str:
        """Generate a concise task title from the query"""
        # Truncate query to first 50 chars for title
        short_query = query[:50].strip()
        if len(query) > 50:
            short_query += "..."
        
        # Add confidence indicator
        if confidence < 0.3:
            return f"Luna Escalation (Low Conf): {short_query}"
        elif confidence < 0.5:
            return f"Luna Escalation: {short_query}"
        else:
            return f"Luna Review: {short_query}"
    
    def _generate_task_description(
        self,
        request: LunaEscalationRequest,
        escalation_id: str
    ) -> str:
        """Generate detailed task description"""
        tags_str = ", ".join(request.tags) if request.tags else "None"
        
        return f"""
══════════════════════════════════════════════════════
LUNA ESCALATION
══════════════════════════════════════════════════════

Escalation ID: {escalation_id}
Confidence Score: {request.confidence:.0%}
Priority: {request.priority.upper()}
Tags: {tags_str}

──────────────────────────────────────────────────────
USER QUERY
──────────────────────────────────────────────────────
{request.query}

──────────────────────────────────────────────────────
LUNA'S RESPONSE
──────────────────────────────────────────────────────
{request.luna_response}

{f'''──────────────────────────────────────────────────────
ADDITIONAL CONTEXT
──────────────────────────────────────────────────────
{request.additional_context}''' if request.additional_context else ''}

══════════════════════════════════════════════════════
ACTION REQUIRED
══════════════════════════════════════════════════════
Please review this query and provide personalized guidance.
Update the task status when resolved.

Escalated at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
"""
    
    def _determine_priority(self, confidence: float, priority: str) -> str:
        """Determine task priority based on confidence and requested priority"""
        if confidence < 0.2:
            return "high"  # Very low confidence = high priority
        elif priority == EscalationPriority.urgent.value:
            return "high"
        elif priority == EscalationPriority.high.value:
            return "high"
        elif priority == EscalationPriority.low.value:
            return "low"
        return "normal"
    
    async def create_escalation(
        self,
        request: LunaEscalationRequest,
        created_by: Optional[str] = None
    ) -> EscalationResponse:
        """
        Create a Luna escalation.
        
        This creates:
        1. A task in myfdc.user_tasks for the client
        2. An escalation record with full metadata
        3. An audit log entry
        """
        escalation_id = str(uuid.uuid4())
        
        # Generate task details
        task_title = self._generate_task_title(request.query, request.confidence)
        task_description = self._generate_task_description(request, escalation_id)
        task_priority = self._determine_priority(request.confidence, request.priority)
        
        # Calculate due date based on priority
        days_until_due = {
            "high": 1,
            "normal": 2,
            "low": 5
        }.get(task_priority, 2)
        due_date = (datetime.now(timezone.utc) + timedelta(days=days_until_due)).date()
        
        # Create the task
        task_data = TaskCreate(
            user_id=request.client_id,
            task_name=task_title,
            description=task_description,
            due_date=due_date,
            status="pending",
            priority=task_priority,
            category="escalation",
            task_type="luna_escalation"
        )
        
        task = await self.crm_service.create_task(task_data, created_by="luna")
        
        # Create escalation record
        escalation = LunaEscalation(
            id=escalation_id,
            task_id=task.id,
            client_id=request.client_id,
            query=request.query,
            luna_response=request.luna_response,
            confidence=request.confidence,
            tags=request.tags,
            priority=request.priority,
            additional_context=request.additional_context,
            assigned_to=DEFAULT_ESCALATION_ASSIGNEE
        )
        
        self.storage.create(escalation)
        
        # Update user's setup_state to track escalation
        try:
            profile = await self.crm_service.get_user_profile(request.client_id)
            if profile:
                current_state = profile.setup_state.model_dump()
                current_state['escalation_pending'] = True
                current_state['last_escalation'] = datetime.now(timezone.utc).isoformat()
                
                settings_update = UserSettingsUpdate(settings={'setup_state': current_state})
                await self.crm_service.update_user_settings(request.client_id, settings_update)
        except Exception as e:
            logger.warning(f"Could not update profile for escalation: {e}")
        
        # Audit log
        log_action(
            action=AuditAction.LUNA_ESCALATION,
            resource_type=ResourceType.TASK,
            resource_id=task.id,
            user_id=created_by,
            details={
                "escalation_id": escalation_id,
                "client_id": request.client_id,
                "query": request.query[:200],  # Truncate for log
                "luna_response": request.luna_response[:200],
                "confidence": request.confidence,
                "tags": request.tags,
                "priority": request.priority
            }
        )
        
        logger.info(f"Luna escalation created: {escalation_id} for client {request.client_id}")
        
        return EscalationResponse(
            success=True,
            escalation_id=escalation_id,
            task_id=task.id,
            client_id=request.client_id,
            message="Escalation created. FDC Tax team will review within 24-48 hours.",
            confidence=request.confidence,
            priority=request.priority,
            tags=request.tags
        )
    
    async def get_escalation(self, escalation_id: str) -> Optional[LunaEscalation]:
        """Get a specific escalation"""
        return self.storage.get(escalation_id)
    
    async def list_escalations(
        self,
        filter_params: Optional[EscalationFilter] = None
    ) -> List[LunaEscalation]:
        """List escalations with filters"""
        if filter_params is None:
            filter_params = EscalationFilter()
        return self.storage.list(filter_params)
    
    async def update_escalation_status(
        self,
        escalation_id: str,
        status: str,
        resolution_notes: Optional[str] = None,
        resolved_by: Optional[str] = None
    ) -> Optional[LunaEscalation]:
        """Update escalation status"""
        updates = {"status": status}
        
        if status in [EscalationStatus.resolved.value, EscalationStatus.dismissed.value]:
            updates["resolved_at"] = datetime.now(timezone.utc).isoformat()
            updates["resolved_by"] = resolved_by
            if resolution_notes:
                updates["resolution_notes"] = resolution_notes
        
        escalation = self.storage.update(escalation_id, updates)
        
        if escalation:
            # Also update the associated task
            try:
                task_status = "completed" if status == EscalationStatus.resolved.value else status
                if status == EscalationStatus.dismissed.value:
                    task_status = "dismissed"
                elif status == EscalationStatus.in_review.value:
                    task_status = "in_progress"
                
                from models import TaskUpdate
                await self.crm_service.update_task(
                    escalation.task_id,
                    TaskUpdate(status=task_status),
                    updated_by=resolved_by
                )
            except Exception as e:
                logger.warning(f"Could not update task status: {e}")
            
            # Clear escalation_pending flag if resolved
            if status in [EscalationStatus.resolved.value, EscalationStatus.dismissed.value]:
                try:
                    profile = await self.crm_service.get_user_profile(escalation.client_id)
                    if profile:
                        current_state = profile.setup_state.model_dump()
                        current_state['escalation_pending'] = False
                        settings_update = UserSettingsUpdate(settings={'setup_state': current_state})
                        await self.crm_service.update_user_settings(escalation.client_id, settings_update)
                except Exception as e:
                    logger.warning(f"Could not update profile escalation flag: {e}")
        
        return escalation
    
    async def assign_escalation(
        self,
        escalation_id: str,
        assigned_to: str,
        assigned_by: Optional[str] = None
    ) -> Optional[LunaEscalation]:
        """Reassign an escalation to a different staff member"""
        return self.storage.update(escalation_id, {"assigned_to": assigned_to})
    
    def get_stats(self) -> EscalationStats:
        """Get escalation statistics"""
        return self.storage.get_stats()
    
    async def get_client_escalations(
        self,
        client_id: str,
        limit: int = 20
    ) -> List[LunaEscalation]:
        """Get all escalations for a specific client"""
        return self.storage.list(EscalationFilter(client_id=client_id, limit=limit))


# ==================== PREDEFINED TAGS ====================

ESCALATION_TAGS = [
    "motor_vehicle",
    "mixed_use",
    "home_office",
    "travel",
    "meals_entertainment",
    "equipment",
    "depreciation",
    "gst",
    "bas",
    "eofy",
    "complex_deduction",
    "contractor",
    "employee",
    "superannuation",
    "investment",
    "capital_gains",
    "other"
]
