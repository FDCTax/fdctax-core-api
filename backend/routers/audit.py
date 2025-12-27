from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
import logging

from database import get_db
from services.audit import (
    AuditLogger,
    AuditLogEntry,
    AuditLogFilter,
    AuditLogStats,
    AuditAction,
    ResourceType,
    AUDIT_ACTIONS,
    RESOURCE_TYPES,
    get_audit_logger,
    log_action
)
from middleware.auth import require_admin, require_staff, AuthUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audit", tags=["Audit Logs"])


# ==================== ADMIN ENDPOINTS ====================

@router.get("", response_model=List[AuditLogEntry])
async def list_audit_logs(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    resource_id: Optional[str] = Query(None, description="Filter by resource ID"),
    success: Optional[bool] = Query(None, description="Filter by success status"),
    limit: int = Query(100, le=500, description="Max entries to return"),
    offset: int = Query(0, description="Offset for pagination"),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    List audit logs with optional filtering.
    
    Requires staff or admin role.
    
    Filters:
    - start_date/end_date: Date range (YYYY-MM-DD format)
    - user_id: Filter by user who performed the action
    - action: Filter by action type (e.g., "task.create", "user.login")
    - resource_type: Filter by resource type (e.g., "task", "document")
    - resource_id: Filter by specific resource ID
    - success: Filter by success/failure status
    """
    try:
        audit_logger = get_audit_logger()
        
        filter_params = AuditLogFilter(
            start_date=start_date,
            end_date=end_date,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            success=success,
            limit=limit,
            offset=offset
        )
        
        logs = audit_logger.get_logs(filter_params)
        return logs
        
    except Exception as e:
        logger.error(f"Error fetching audit logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entry/{entry_id}", response_model=AuditLogEntry)
async def get_audit_log_entry(
    entry_id: str,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific audit log entry by ID.
    
    Requires staff or admin role.
    """
    try:
        audit_logger = get_audit_logger()
        entry = audit_logger.get_entry(entry_id)
        
        if not entry:
            raise HTTPException(status_code=404, detail="Audit log entry not found")
        
        return entry
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching audit log entry: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", response_model=AuditLogStats)
async def get_audit_stats(
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get audit log statistics.
    
    Returns:
    - Total entries
    - Entries today
    - Entries this week
    - Breakdown by action type
    - Breakdown by resource type
    - Breakdown by user
    - Recent error count
    """
    try:
        audit_logger = get_audit_logger()
        return audit_logger.get_stats()
        
    except Exception as e:
        logger.error(f"Error fetching audit stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user/{user_id}", response_model=List[AuditLogEntry])
async def get_user_activity(
    user_id: str,
    limit: int = Query(50, le=200),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get recent activity for a specific user.
    
    Useful for user activity reports and investigations.
    """
    try:
        audit_logger = get_audit_logger()
        return audit_logger.get_user_activity(user_id, limit)
        
    except Exception as e:
        logger.error(f"Error fetching user activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/resource/{resource_type}/{resource_id}", response_model=List[AuditLogEntry])
async def get_resource_history(
    resource_type: str,
    resource_id: str,
    limit: int = Query(50, le=200),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get history of actions on a specific resource.
    
    Example: /api/audit/resource/task/uuid-here
    
    Useful for tracking all changes to a specific task, document, etc.
    """
    try:
        audit_logger = get_audit_logger()
        return audit_logger.get_resource_history(resource_type, resource_id, limit)
        
    except Exception as e:
        logger.error(f"Error fetching resource history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/errors", response_model=List[AuditLogEntry])
async def get_failed_actions(
    limit: int = Query(100, le=500),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get recent failed actions.
    
    Useful for debugging and security monitoring.
    """
    try:
        audit_logger = get_audit_logger()
        return audit_logger.get_failed_actions(limit)
        
    except Exception as e:
        logger.error(f"Error fetching failed actions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/actions")
async def list_available_actions(
    current_user: AuthUser = Depends(require_staff)
):
    """
    List all available audit action types.
    
    Useful for building filter dropdowns in the UI.
    """
    return {
        "actions": AUDIT_ACTIONS,
        "resource_types": RESOURCE_TYPES,
        "categories": {
            "authentication": [a for a in AUDIT_ACTIONS if a.startswith("user.") or a.startswith("token.")],
            "tasks": [a for a in AUDIT_ACTIONS if a.startswith("task.") or a.startswith("crm_task.")],
            "documents": [a for a in AUDIT_ACTIONS if a.startswith("document.")],
            "recurring": [a for a in AUDIT_ACTIONS if a.startswith("recurring.")],
            "profile": [a for a in AUDIT_ACTIONS if a.startswith("profile.") or a.startswith("onboarding.") or a.startswith("oscar.")],
            "kb": [a for a in AUDIT_ACTIONS if a.startswith("kb.")],
            "crm": [a for a in AUDIT_ACTIONS if a.startswith("crm.")],
            "other": [a for a in AUDIT_ACTIONS if a.startswith("luna.") or a.startswith("admin.") or a.startswith("system.")]
        }
    }


@router.post("/cleanup")
async def cleanup_old_logs(
    days_to_keep: int = Query(90, ge=7, le=365, description="Days of logs to keep"),
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Clean up old audit logs.
    
    Admin only. Deletes logs older than specified days.
    Default: Keep 90 days.
    """
    try:
        audit_logger = get_audit_logger()
        deleted_count = audit_logger.clear_old_logs(days_to_keep)
        
        # Log this action too
        log_action(
            action=AuditAction.ADMIN_ACTION,
            resource_type=ResourceType.SYSTEM,
            user_id=current_user.id,
            user_email=current_user.email,
            details={
                "action": "cleanup_audit_logs",
                "days_kept": days_to_keep,
                "entries_deleted": deleted_count
            }
        )
        
        return {
            "success": True,
            "message": f"Deleted {deleted_count} old audit log entries",
            "days_kept": days_to_keep
        }
        
    except Exception as e:
        logger.error(f"Error cleaning up logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== SELF-SERVICE ENDPOINTS ====================

@router.get("/my-activity", response_model=List[AuditLogEntry])
async def get_my_activity(
    limit: int = Query(50, le=100),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current user's own activity log.
    
    Available to any authenticated user for their own activity.
    """
    try:
        audit_logger = get_audit_logger()
        return audit_logger.get_user_activity(current_user.id, limit)
        
    except Exception as e:
        logger.error(f"Error fetching own activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))
