from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
import logging

from database import get_db
from models import (
    UserProfileResponse, UserProfileUpdate,
    TaskResponse, SetupState, OscarToggleRequest, OnboardingUpdateRequest
)
from services.crm_sync import CRMSyncService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/user", tags=["User"])


@router.get("/tasks", response_model=List[TaskResponse])
async def get_user_tasks(
    user_id: str = Query(..., description="User ID to fetch tasks for"),
    status: Optional[str] = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_db)
):
    """
    GET tasks for logged-in user
    Returns all tasks assigned to the specified user
    """
    try:
        crm_service = CRMSyncService(db)
        tasks = await crm_service.get_user_tasks(user_id, status)
        return tasks
    except Exception as e:
        logger.error(f"Error fetching tasks for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profile", response_model=UserProfileResponse)
async def get_user_profile(
    user_id: str = Query(..., description="User ID to fetch profile for"),
    db: AsyncSession = Depends(get_db)
):
    """
    GET user profile + setup state
    Returns the complete profile including onboarding state
    """
    try:
        crm_service = CRMSyncService(db)
        profile = await crm_service.get_user_profile(user_id)
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        return profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching profile for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profile", response_model=UserProfileResponse)
async def create_or_update_profile(
    user_id: str = Query(..., description="User ID"),
    profile_data: UserProfileUpdate = None,
    db: AsyncSession = Depends(get_db)
):
    """
    POST user profile + setup state
    Creates or updates the user's profile
    """
    try:
        crm_service = CRMSyncService(db)
        
        # Update profile
        if profile_data:
            profile = await crm_service.update_user_profile(user_id, profile_data)
        else:
            profile = await crm_service.get_user_profile(user_id)
        
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        
        return profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating/updating profile for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/oscar", response_model=dict)
async def toggle_oscar_preprocessing(
    user_id: str = Query(..., description="User ID"),
    request: OscarToggleRequest = None,
    db: AsyncSession = Depends(get_db)
):
    """
    POST toggle Oscar preprocessing
    Enables/disables Oscar enhanced OCR for receipts
    Updates both oscar_enabled flag and oscar_intro_seen in setup_state
    """
    try:
        crm_service = CRMSyncService(db)
        
        # Update oscar_enabled flag
        profile_update = UserProfileUpdate(oscar_enabled=request.enabled)
        profile = await crm_service.update_user_profile(user_id, profile_update)
        
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        
        # Also mark oscar_intro_seen in setup_state
        onboarding_update = OnboardingUpdateRequest(oscar_intro_seen=True)
        await crm_service.update_onboarding_state(user_id, onboarding_update)
        
        return {
            "success": True,
            "oscar_enabled": request.enabled,
            "message": f"Oscar preprocessing {'enabled' if request.enabled else 'disabled'}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling Oscar for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/onboarding", response_model=UserProfileResponse)
async def update_onboarding_state(
    user_id: str = Query(..., description="User ID"),
    request: OnboardingUpdateRequest = None,
    db: AsyncSession = Depends(get_db)
):
    """
    PATCH setup_state flags
    Updates specific onboarding flags without affecting others
    """
    try:
        crm_service = CRMSyncService(db)
        profile = await crm_service.update_onboarding_state(user_id, request)
        
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        
        return profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating onboarding for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/onboarding/status", response_model=SetupState)
async def get_onboarding_status(
    user_id: str = Query(..., description="User ID"),
    db: AsyncSession = Depends(get_db)
):
    """
    GET current onboarding status
    Returns just the setup_state for the wizard UI
    """
    try:
        crm_service = CRMSyncService(db)
        profile = await crm_service.get_user_profile(user_id)
        
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        
        return profile.setup_state
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching onboarding status for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# ==================== DOCUMENT SHORTCUTS ====================
# These are convenience endpoints that redirect to /api/documents/user/*

@router.get("/documents")
async def get_user_documents_shortcut(
    user_id: str = Query(..., description="User ID"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all document requests for a user.
    This is a convenience endpoint - see /api/documents/user for full API.
    """
    try:
        from services.documents import DocumentService
        service = DocumentService()
        return service.get_user_documents(user_id)
    except Exception as e:
        logger.error(f"Error getting user documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))
