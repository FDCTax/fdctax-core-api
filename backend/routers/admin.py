from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID
import logging

from database import get_db
from models import (
    UserResponse, UserCreate, UserUpdate,
    UserProfileResponse, UserProfileUpdate,
    TaskResponse, TaskCreate, TaskUpdate,
    OnboardingUpdateRequest
)
from services.crm_sync import CRMSyncService
from services.whiteglove import WhiteGloveService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin - White Glove"])


# ==================== USER MANAGEMENT ====================

@router.get("/users", response_model=List[UserResponse])
async def list_users(
    is_active: Optional[bool] = Query(None),
    role: Optional[str] = Query(None),
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
            role=role,
            limit=limit,
            offset=offset
        )
        return users
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
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


@router.post("/users", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create new user
    White-glove service: onboard new client
    """
    try:
        crm_service = CRMSyncService(db)
        user = await crm_service.create_user(user_data)
        return user
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
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
    user_id: UUID,
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
    user_id: UUID,
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
    user_id: UUID,
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


# ==================== TASK MANAGEMENT ====================

@router.get("/tasks", response_model=List[TaskResponse])
async def list_all_tasks(
    status: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    user_id: Optional[UUID] = Query(None),
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
            source=source,
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
    task_id: UUID,
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
    task_id: UUID,
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


# ==================== LUNA ESCALATION ====================

@router.post("/escalate")
async def trigger_luna_escalation(
    user_id: UUID = Query(..., description="User ID"),
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


# ==================== CRM SYNC ====================

@router.post("/sync/tasks")
async def sync_crm_tasks(
    user_id: Optional[UUID] = Query(None, description="Sync for specific user or all"),
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
    user_id: Optional[UUID] = Query(None),
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
