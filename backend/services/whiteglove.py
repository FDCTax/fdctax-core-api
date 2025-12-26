from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timezone, timedelta
import logging
import json

from models import (
    UserProfileResponse, UserProfileUpdate,
    TaskResponse, TaskCreate,
    OnboardingUpdateRequest, SetupState, TaskSource, TaskStatus
)
from services.crm_sync import CRMSyncService

logger = logging.getLogger(__name__)


class WhiteGloveService:
    """
    White-Glove Service Layer for FDC Tax
    Backend services for managing clients with personalized support
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.crm_service = CRMSyncService(db)
    
    async def admin_profile_override(
        self,
        user_id: UUID,
        profile_data: UserProfileUpdate
    ) -> Optional[UserProfileResponse]:
        """
        Admin override of user profile
        Allows FDC Tax team to manually adjust client profiles
        """
        logger.info(f"Admin profile override for user {user_id}")
        
        # Update the profile
        profile = await self.crm_service.update_user_profile(user_id, profile_data)
        
        if profile:
            # Log the admin action (could be expanded to audit table)
            logger.info(f"Profile updated by admin: {user_id}, changes: {profile_data.model_dump(exclude_none=True)}")
        
        return profile
    
    async def override_onboarding_state(
        self,
        user_id: UUID,
        request: OnboardingUpdateRequest
    ) -> Optional[UserProfileResponse]:
        """
        Manual override of onboarding flags
        Use cases:
        - Skip steps for returning clients
        - Reset steps for re-onboarding
        - Force completion for VIP setup
        """
        logger.info(f"Onboarding override for user {user_id}: {request.model_dump(exclude_none=True)}")
        return await self.crm_service.update_onboarding_state(user_id, request)
    
    async def assign_task(
        self,
        task_data: TaskCreate
    ) -> TaskResponse:
        """
        Assign a task to a user
        White-glove service: task assignment to educator dashboard
        """
        # Set source as internal_crm since it's coming from admin
        task_data.source = TaskSource.internal_crm
        
        logger.info(f"Assigning task to user {task_data.user_id}: {task_data.title}")
        
        task = await self.crm_service.create_task(task_data)
        
        # Log the assignment
        logger.info(f"Task {task.id} assigned to {task.user_id}")
        
        return task
    
    async def create_luna_escalation(
        self,
        user_id: UUID,
        reason: str
    ) -> Dict[str, Any]:
        """
        Trigger Luna escalation
        Creates a high-priority task for FDC Tax team to follow up
        
        Use case: "This looks tricky — want help from FDC Tax?"
        When Luna detects a complex situation, this creates a task
        for the white-glove team to assist.
        """
        logger.info(f"Luna escalation triggered for user {user_id}: {reason}")
        
        # Create escalation task
        escalation_task = TaskCreate(
            user_id=user_id,
            title=f"Luna Escalation: {reason[:50]}...",
            description=f"""
            LUNA ESCALATION
            ===============
            User requested help from FDC Tax team.
            
            Reason: {reason}
            
            Escalated at: {datetime.now(timezone.utc).isoformat()}
            
            Action Required: Review user's situation and provide personalized assistance.
            """,
            due_date=(datetime.now(timezone.utc) + timedelta(days=1)).date(),
            status=TaskStatus.pending,
            source=TaskSource.luna
        )
        
        task = await self.crm_service.create_task(escalation_task)
        
        # Mark in user's profile that they've requested help
        # This could trigger different UI states
        try:
            profile = await self.crm_service.get_user_profile(user_id)
            if profile:
                # Could add an 'escalation_pending' flag to setup_state
                current_state = profile.setup_state.model_dump()
                current_state['escalation_pending'] = True
                current_state['last_escalation'] = datetime.now(timezone.utc).isoformat()
                
                query = text("""
                    UPDATE user_profiles 
                    SET setup_state = :setup_state::jsonb, updated_at = :updated_at
                    WHERE user_id = :user_id
                """)
                
                await self.db.execute(query, {
                    "user_id": str(user_id),
                    "setup_state": json.dumps(current_state),
                    "updated_at": datetime.now(timezone.utc)
                })
                await self.db.commit()
        except Exception as e:
            logger.warning(f"Could not update profile for escalation: {e}")
        
        return {
            "success": True,
            "escalation_id": str(task.id),
            "user_id": str(user_id),
            "reason": reason,
            "task_created": True,
            "message": "Escalation created. FDC Tax team will follow up within 24 hours."
        }
    
    async def get_client_summary(self, user_id: UUID) -> Dict[str, Any]:
        """
        Get comprehensive client summary for white-glove review
        Combines user, profile, and tasks data
        """
        user = await self.crm_service.get_user(user_id)
        if not user:
            return {"error": "User not found"}
        
        profile = await self.crm_service.get_user_profile(user_id)
        tasks = await self.crm_service.get_user_tasks(user_id)
        
        pending_tasks = [t for t in tasks if t.status == TaskStatus.pending]
        in_progress_tasks = [t for t in tasks if t.status == TaskStatus.in_progress]
        
        return {
            "user": user.model_dump(),
            "profile": profile.model_dump() if profile else None,
            "tasks": {
                "total": len(tasks),
                "pending": len(pending_tasks),
                "in_progress": len(in_progress_tasks),
                "items": [t.model_dump() for t in tasks[:10]]  # Last 10 tasks
            },
            "onboarding_status": profile.setup_state.model_dump() if profile else None,
            "flags": {
                "oscar_enabled": profile.oscar_enabled if profile else False,
                "levy_auto_enabled": profile.levy_auto_enabled if profile else False,
                "gst_registered": profile.gst_registered if profile else False
            } if profile else None
        }
    
    async def bulk_task_assignment(
        self,
        user_ids: list[UUID],
        title: str,
        description: str,
        due_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Assign the same task to multiple users
        Use case: Quarterly reminders, compliance updates, etc.
        """
        results = []
        errors = []
        
        for user_id in user_ids:
            try:
                task_data = TaskCreate(
                    user_id=user_id,
                    title=title,
                    description=description,
                    due_date=due_date.date() if due_date else None,
                    status=TaskStatus.pending,
                    source=TaskSource.internal_crm
                )
                task = await self.crm_service.create_task(task_data)
                results.append({"user_id": str(user_id), "task_id": str(task.id)})
            except Exception as e:
                errors.append({"user_id": str(user_id), "error": str(e)})
        
        return {
            "success": len(errors) == 0,
            "tasks_created": len(results),
            "errors": len(errors),
            "results": results,
            "error_details": errors if errors else None
        }
