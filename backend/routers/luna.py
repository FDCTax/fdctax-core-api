"""
Luna Escalation API Router

Endpoints for Luna AI to escalate queries to the FDC Tax team,
and for admins to review and manage escalations.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
import logging

from database import get_db
from services.luna import (
    LunaService,
    LunaEscalationRequest,
    LunaEscalation,
    EscalationFilter,
    EscalationResponse,
    EscalationStats,
    EscalationStatus,
    EscalationPriority,
    ESCALATION_TAGS
)
from middleware.auth import get_current_user, get_current_user_required, require_staff, require_admin, AuthUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/luna", tags=["Luna Escalations"])


# ==================== ESCALATION CREATION ====================

@router.post("/escalate", response_model=EscalationResponse)
async def create_escalation(
    request: Request,
    escalation_data: LunaEscalationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AuthUser = Depends(get_current_user)
):
    """
    Create a Luna escalation.
    
    Called when Luna AI determines a query needs human review.
    Creates a task for the FDC Tax team with full context.
    
    **Payload:**
    ```json
    {
      "client_id": "uuid",
      "query": "What if I use my car for both daycare and personal errands?",
      "luna_response": "This may be partially deductible. Let me flag this for review.",
      "confidence": 0.42,
      "tags": ["motor_vehicle", "mixed_use"],
      "priority": "medium",
      "additional_context": "Optional extra context"
    }
    ```
    
    **Priority Levels:**
    - `low`: Non-urgent, general questions (5 day response)
    - `medium`: Standard escalation (2 day response)
    - `high`: Complex/time-sensitive (1 day response)
    - `urgent`: Immediate attention needed (1 day, high priority task)
    
    **Confidence Score:**
    - 0.0-0.3: Very low confidence → auto-escalates as high priority
    - 0.3-0.5: Low confidence → standard escalation
    - 0.5-1.0: Moderate confidence → review requested
    """
    try:
        luna_service = LunaService(db)
        
        # Determine who triggered the escalation
        created_by = current_user.id if current_user else "luna-system"
        
        result = await luna_service.create_escalation(escalation_data, created_by=created_by)
        
        return result
        
    except Exception as e:
        logger.error(f"Error creating escalation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ADMIN ESCALATION MANAGEMENT ====================

@router.get("/escalations", response_model=List[LunaEscalation])
async def list_escalations(
    status: Optional[str] = Query(None, description="Filter by status (open, in_review, resolved, dismissed)"),
    client_id: Optional[str] = Query(None, description="Filter by client UUID"),
    min_confidence: Optional[float] = Query(None, ge=0, le=1, description="Minimum confidence score"),
    max_confidence: Optional[float] = Query(None, ge=0, le=1, description="Maximum confidence score"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    assigned_to: Optional[str] = Query(None, description="Filter by assignee"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    List Luna escalations with optional filters.
    
    Requires staff or admin role.
    
    **Filter Examples:**
    - `/api/luna/escalations?status=open` - Get open escalations
    - `/api/luna/escalations?max_confidence=0.5` - Low confidence escalations
    - `/api/luna/escalations?tag=motor_vehicle` - Motor vehicle related
    - `/api/luna/escalations?priority=high` - High priority only
    """
    try:
        luna_service = LunaService(db)
        
        filter_params = EscalationFilter(
            status=status,
            client_id=client_id,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
            tag=tag,
            priority=priority,
            assigned_to=assigned_to,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset
        )
        
        return await luna_service.list_escalations(filter_params)
        
    except Exception as e:
        logger.error(f"Error listing escalations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/escalations/stats", response_model=EscalationStats)
async def get_escalation_stats(
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get Luna escalation statistics.
    
    Returns counts by status, priority, tags, and recent activity.
    """
    try:
        luna_service = LunaService(db)
        return luna_service.get_stats()
        
    except Exception as e:
        logger.error(f"Error getting escalation stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/escalations/{escalation_id}", response_model=LunaEscalation)
async def get_escalation(
    escalation_id: str,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific escalation by ID.
    """
    try:
        luna_service = LunaService(db)
        escalation = await luna_service.get_escalation(escalation_id)
        
        if not escalation:
            raise HTTPException(status_code=404, detail="Escalation not found")
        
        return escalation
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting escalation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/escalations/{escalation_id}/status")
async def update_escalation_status(
    escalation_id: str,
    status: str = Query(..., description="New status (open, in_review, resolved, dismissed)"),
    resolution_notes: Optional[str] = Query(None, description="Notes about the resolution"),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Update escalation status.
    
    **Status Transitions:**
    - `open` → `in_review` (staff picks up the escalation)
    - `in_review` → `resolved` (issue addressed)
    - `in_review` → `dismissed` (not actionable)
    - Any → `open` (reopen if needed)
    """
    valid_statuses = [s.value for s in EscalationStatus]
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {valid_statuses}"
        )
    
    try:
        luna_service = LunaService(db)
        escalation = await luna_service.update_escalation_status(
            escalation_id=escalation_id,
            status=status,
            resolution_notes=resolution_notes,
            resolved_by=current_user.id
        )
        
        if not escalation:
            raise HTTPException(status_code=404, detail="Escalation not found")
        
        return {
            "success": True,
            "escalation_id": escalation_id,
            "new_status": status,
            "message": f"Escalation status updated to {status}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating escalation status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/escalations/{escalation_id}/assign")
async def assign_escalation(
    escalation_id: str,
    assigned_to: str = Query(..., description="Email or ID of staff member to assign"),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Assign or reassign an escalation to a staff member.
    """
    try:
        luna_service = LunaService(db)
        escalation = await luna_service.assign_escalation(
            escalation_id=escalation_id,
            assigned_to=assigned_to,
            assigned_by=current_user.id
        )
        
        if not escalation:
            raise HTTPException(status_code=404, detail="Escalation not found")
        
        return {
            "success": True,
            "escalation_id": escalation_id,
            "assigned_to": assigned_to,
            "message": f"Escalation assigned to {assigned_to}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error assigning escalation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/escalations/client/{client_id}", response_model=List[LunaEscalation])
async def get_client_escalations(
    client_id: str,
    limit: int = Query(20, le=100),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all escalations for a specific client.
    
    Useful for reviewing a client's escalation history.
    """
    try:
        luna_service = LunaService(db)
        return await luna_service.get_client_escalations(client_id, limit)
        
    except Exception as e:
        logger.error(f"Error getting client escalations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== UTILITY ENDPOINTS ====================

@router.get("/tags")
async def list_available_tags():
    """
    List all available escalation tags.
    
    Tags help categorize escalations for filtering and reporting.
    """
    return {
        "tags": ESCALATION_TAGS,
        "count": len(ESCALATION_TAGS)
    }


@router.get("/priorities")
async def list_priorities():
    """
    List all available priority levels.
    """
    return {
        "priorities": [p.value for p in EscalationPriority],
        "descriptions": {
            "low": "Non-urgent, general questions (5 day response time)",
            "medium": "Standard escalation (2 day response time)",
            "high": "Complex or time-sensitive (1 day response time)",
            "urgent": "Immediate attention needed (1 day, highest priority)"
        }
    }


@router.get("/statuses")
async def list_statuses():
    """
    List all available escalation statuses.
    """
    return {
        "statuses": [s.value for s in EscalationStatus],
        "descriptions": {
            "open": "New escalation, not yet reviewed",
            "in_review": "Staff member is working on it",
            "resolved": "Issue has been addressed",
            "dismissed": "Not actionable or duplicate"
        }
    }
