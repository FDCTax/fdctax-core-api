from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
import logging

from database import get_db
from models import (
    UserResponse, UserUpdate,
    UserProfileResponse, UserProfileUpdate,
    TaskResponse, TaskCreate, TaskUpdate,
    CRMTaskResponse, CRMTaskCreate, CRMTaskUpdate,
    OnboardingUpdateRequest
)
from services.crm_sync import CRMSyncService
from services.whiteglove import WhiteGloveService
from middleware.auth import get_optional_user, require_staff, AuthUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin - White Glove"])

# Note: All /admin endpoints require staff or admin role when authentication is enabled.
# Use the require_staff dependency for protected endpoints.
# Currently endpoints work without auth for backwards compatibility.
# To enforce auth, add: current_user: AuthUser = Depends(require_staff)


# ==================== USER MANAGEMENT ====================

@router.get("/users", response_model=List[UserResponse])
async def list_users(
    is_active: Optional[bool] = Query(None),
    plan: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db)
):
    """
    List all users with optional filters
    White-glove service: view client roster
    """
    try:
        crm_service = CRMSyncService(db)
        users = await crm_service.list_users(
            is_active=is_active,
            plan=plan,
            limit=limit,
            offset=offset
        )
        return users
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get specific user details
    """
    try:
        crm_service = CRMSyncService(db)
        user = await crm_service.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/email/{email}", response_model=UserResponse)
async def get_user_by_email(
    email: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get user by email address
    """
    try:
        crm_service = CRMSyncService(db)
        user = await crm_service.get_user_by_email(email)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user by email {email}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Update user details
    """
    try:
        crm_service = CRMSyncService(db)
        user = await crm_service.update_user(user_id, user_data)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== PROFILE MANAGEMENT ====================

@router.get("/profiles/{user_id}", response_model=UserProfileResponse)
async def get_user_profile_admin(
    user_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get user profile for admin review
    White-glove service: profile review
    """
    try:
        crm_service = CRMSyncService(db)
        profile = await crm_service.get_user_profile(user_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        return profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching profile {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/profiles/{user_id}", response_model=UserProfileResponse)
async def update_profile_admin(
    user_id: str,
    profile_data: UserProfileUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Admin override of user profile
    White-glove service: manual profile adjustments
    """
    try:
        whiteglove = WhiteGloveService(db)
        profile = await whiteglove.admin_profile_override(user_id, profile_data)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        return profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating profile {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/profiles/{user_id}/onboarding", response_model=UserProfileResponse)
async def override_onboarding_flags(
    user_id: str,
    request: OnboardingUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Manual override of onboarding flags
    White-glove service: skip or reset onboarding steps
    """
    try:
        whiteglove = WhiteGloveService(db)
        profile = await whiteglove.override_onboarding_state(user_id, request)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        return profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error overriding onboarding for {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profiles/{user_id}/reset-onboarding")
async def reset_onboarding(
    user_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Reset all onboarding flags for a user
    White-glove service: re-onboarding after major updates
    """
    try:
        whiteglove = WhiteGloveService(db)
        result = await whiteglove.reset_onboarding(user_id)
        return result
    except Exception as e:
        logger.error(f"Error resetting onboarding for {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/clients/{user_id}/summary")
async def get_client_summary(
    user_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get comprehensive client summary
    White-glove service: full client overview
    """
    try:
        whiteglove = WhiteGloveService(db)
        summary = await whiteglove.get_client_summary(user_id)
        if "error" in summary:
            raise HTTPException(status_code=404, detail=summary["error"])
        return summary
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting client summary for {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== TASK MANAGEMENT (myfdc.user_tasks) ====================

@router.get("/tasks", response_model=List[TaskResponse])
async def list_all_tasks(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db)
):
    """
    List all tasks with filters
    White-glove service: task dashboard
    """
    try:
        crm_service = CRMSyncService(db)
        tasks = await crm_service.list_tasks(
            status=status,
            category=category,
            user_id=user_id,
            limit=limit,
            offset=offset
        )
        return tasks
    except Exception as e:
        logger.error(f"Error listing tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks", response_model=TaskResponse)
async def create_task(
    task_data: TaskCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create and assign task to user
    White-glove service: task assignment
    """
    try:
        whiteglove = WhiteGloveService(db)
        task = await whiteglove.assign_task(task_data)
        return task
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    task_data: TaskUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Update task details or status
    """
    try:
        crm_service = CRMSyncService(db)
        task = await crm_service.update_task(task_id, task_data)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a task
    """
    try:
        crm_service = CRMSyncService(db)
        success = await crm_service.delete_task(task_id)
        if not success:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"success": True, "message": "Task deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== CRM TASKS (crm.tasks) ====================

@router.get("/crm/tasks", response_model=List[CRMTaskResponse])
async def list_crm_tasks(
    status: Optional[str] = Query(None),
    client_id: Optional[int] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db)
):
    """
    List CRM tasks (from crm.tasks table)
    """
    try:
        crm_service = CRMSyncService(db)
        tasks = await crm_service.list_crm_tasks(
            status=status,
            client_id=client_id,
            limit=limit,
            offset=offset
        )
        return tasks
    except Exception as e:
        logger.error(f"Error listing CRM tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/crm/tasks", response_model=CRMTaskResponse)
async def create_crm_task(
    task_data: CRMTaskCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create CRM task
    """
    try:
        crm_service = CRMSyncService(db)
        task = await crm_service.create_crm_task(task_data)
        return task
    except Exception as e:
        logger.error(f"Error creating CRM task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/crm/tasks/{task_id}", response_model=CRMTaskResponse)
async def update_crm_task(
    task_id: int,
    task_data: CRMTaskUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Update CRM task
    """
    try:
        crm_service = CRMSyncService(db)
        task = await crm_service.update_crm_task(task_id, task_data)
        if not task:
            raise HTTPException(status_code=404, detail="CRM Task not found")
        return task
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating CRM task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== LUNA ESCALATION ====================

@router.post("/escalate")
async def trigger_luna_escalation(
    user_id: str = Query(..., description="User ID"),
    reason: str = Query(..., description="Escalation reason"),
    db: AsyncSession = Depends(get_db)
):
    """
    Trigger Luna escalation
    Creates a task for FDC Tax team to follow up
    "This looks tricky — want help from FDC Tax?"
    """
    try:
        whiteglove = WhiteGloveService(db)
        result = await whiteglove.create_luna_escalation(user_id, reason)
        return result
    except Exception as e:
        logger.error(f"Error creating escalation for {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== OSCAR WIZARD ====================

@router.post("/oscar/complete")
async def complete_oscar_wizard(
    user_id: str = Query(..., description="User ID"),
    oscar_enabled: bool = Query(..., description="Enable Oscar preprocessing"),
    db: AsyncSession = Depends(get_db)
):
    """
    Complete Meet Oscar wizard
    Marks wizard as completed and sets oscar_enabled preference
    """
    try:
        whiteglove = WhiteGloveService(db)
        result = await whiteglove.complete_oscar_wizard(user_id, oscar_enabled)
        return result
    except Exception as e:
        logger.error(f"Error completing Oscar wizard for {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== CRM SYNC ====================

@router.post("/sync/tasks")
async def sync_crm_tasks(
    user_id: Optional[str] = Query(None, description="Sync for specific user or all"),
    db: AsyncSession = Depends(get_db)
):
    """
    Trigger CRM task sync
    Syncs tasks from internal CRM to educator dashboards
    """
    try:
        crm_service = CRMSyncService(db)
        result = await crm_service.sync_tasks_to_frontend(user_id)
        return result
    except Exception as e:
        logger.error(f"Error syncing tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/profiles")
async def sync_crm_profiles(
    user_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Trigger profile flag sync
    Syncs profile flags (levy_auto, GST status) to frontend
    """
    try:
        crm_service = CRMSyncService(db)
        result = await crm_service.sync_profiles_to_frontend(user_id)
        return result
    except Exception as e:
        logger.error(f"Error syncing profiles: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== RECURRING TASKS ====================

@router.post("/tasks/trigger-recurring")
async def trigger_recurring_tasks(
    user_id: Optional[str] = Query(None, description="Process only this user's templates"),
    force: bool = Query(False, description="Force generation even if not due"),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger the recurring task generation job.
    
    This endpoint processes all active recurring task templates and
    generates tasks for any that are due.
    
    - In production, this would be called by a daily cron job
    - Use force=true to generate tasks even if they're not yet due
    - Use user_id to process only a specific user's templates
    """
    try:
        from services.recurring_tasks import RecurringTaskEngine
        
        engine = RecurringTaskEngine(db)
        results = await engine.process_recurring_tasks(user_id=user_id, force=force)
        return results
    except Exception as e:
        logger.error(f"Error triggering recurring tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))
