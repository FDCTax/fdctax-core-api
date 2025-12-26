from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timezone
import logging
import json

from models import (
    UserResponse, UserCreate, UserUpdate,
    UserProfileResponse, UserProfileCreate, UserProfileUpdate,
    TaskResponse, TaskCreate, TaskUpdate,
    KBEntryResponse, KBEntryCreate, KBEntryUpdate,
    SetupState, OnboardingUpdateRequest
)

logger = logging.getLogger(__name__)


class CRMSyncService:
    """
    CRM Sync Service for FDC Tax
    Handles data sync between internal CRM and MyFDC frontend
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ==================== USER OPERATIONS ====================
    
    async def get_user(self, user_id: UUID) -> Optional[UserResponse]:
        """Get user by ID"""
        query = text("""
            SELECT id, email, first_name, last_name, created_at, is_active, role
            FROM users WHERE id = :user_id
        """)
        result = await self.db.execute(query, {"user_id": str(user_id)})
        row = result.fetchone()
        
        if not row:
            return None
        
        return UserResponse(
            id=row.id,
            email=row.email,
            first_name=row.first_name,
            last_name=row.last_name,
            created_at=row.created_at,
            is_active=row.is_active,
            role=row.role
        )
    
    async def list_users(
        self,
        is_active: Optional[bool] = None,
        role: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[UserResponse]:
        """List users with optional filters"""
        conditions = []
        params = {"limit": limit, "offset": offset}
        
        if is_active is not None:
            conditions.append("is_active = :is_active")
            params["is_active"] = is_active
        
        if role:
            conditions.append("role = :role")
            params["role"] = role
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        query = text(f"""
            SELECT id, email, first_name, last_name, created_at, is_active, role
            FROM users
            {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """)
        
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        return [
            UserResponse(
                id=row.id,
                email=row.email,
                first_name=row.first_name,
                last_name=row.last_name,
                created_at=row.created_at,
                is_active=row.is_active,
                role=row.role
            )
            for row in rows
        ]
    
    async def create_user(self, user_data: UserCreate) -> UserResponse:
        """Create new user"""
        query = text("""
            INSERT INTO users (email, first_name, last_name, is_active, role, created_at)
            VALUES (:email, :first_name, :last_name, :is_active, :role, :created_at)
            RETURNING id, email, first_name, last_name, created_at, is_active, role
        """)
        
        params = {
            "email": user_data.email,
            "first_name": user_data.first_name,
            "last_name": user_data.last_name,
            "is_active": user_data.is_active,
            "role": user_data.role.value,
            "created_at": datetime.now(timezone.utc)
        }
        
        result = await self.db.execute(query, params)
        await self.db.commit()
        row = result.fetchone()
        
        return UserResponse(
            id=row.id,
            email=row.email,
            first_name=row.first_name,
            last_name=row.last_name,
            created_at=row.created_at,
            is_active=row.is_active,
            role=row.role
        )
    
    async def update_user(self, user_id: UUID, user_data: UserUpdate) -> Optional[UserResponse]:
        """Update user"""
        updates = []
        params = {"user_id": str(user_id)}
        
        update_dict = user_data.model_dump(exclude_none=True)
        for key, value in update_dict.items():
            if key == 'role' and value:
                updates.append(f"{key} = :{key}")
                params[key] = value.value
            else:
                updates.append(f"{key} = :{key}")
                params[key] = value
        
        if not updates:
            return await self.get_user(user_id)
        
        query = text(f"""
            UPDATE users SET {', '.join(updates)}
            WHERE id = :user_id
            RETURNING id, email, first_name, last_name, created_at, is_active, role
        """)
        
        result = await self.db.execute(query, params)
        await self.db.commit()
        row = result.fetchone()
        
        if not row:
            return None
        
        return UserResponse(
            id=row.id,
            email=row.email,
            first_name=row.first_name,
            last_name=row.last_name,
            created_at=row.created_at,
            is_active=row.is_active,
            role=row.role
        )
    
    # ==================== USER PROFILE OPERATIONS ====================
    
    async def get_user_profile(self, user_id: UUID) -> Optional[UserProfileResponse]:
        """Get user profile by user_id"""
        query = text("""
            SELECT id, user_id, fdc_percent, gst_registered, gst_cycle,
                   oscar_enabled, levy_auto_enabled, setup_state,
                   created_at, updated_at
            FROM user_profiles WHERE user_id = :user_id
        """)
        
        result = await self.db.execute(query, {"user_id": str(user_id)})
        row = result.fetchone()
        
        if not row:
            return None
        
        # Parse setup_state JSONB
        setup_state_data = row.setup_state if row.setup_state else {}
        if isinstance(setup_state_data, str):
            setup_state_data = json.loads(setup_state_data)
        
        return UserProfileResponse(
            id=row.id,
            user_id=row.user_id,
            fdc_percent=row.fdc_percent or 0,
            gst_registered=row.gst_registered or False,
            gst_cycle=row.gst_cycle or 'none',
            oscar_enabled=row.oscar_enabled or False,
            levy_auto_enabled=row.levy_auto_enabled or False,
            setup_state=SetupState(**setup_state_data),
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    async def create_user_profile(self, profile_data: UserProfileCreate) -> UserProfileResponse:
        """Create new user profile"""
        setup_state_json = json.dumps(profile_data.setup_state.model_dump())
        
        query = text("""
            INSERT INTO user_profiles 
            (user_id, fdc_percent, gst_registered, gst_cycle, oscar_enabled, 
             levy_auto_enabled, setup_state, created_at)
            VALUES (:user_id, :fdc_percent, :gst_registered, :gst_cycle, 
                    :oscar_enabled, :levy_auto_enabled, :setup_state::jsonb, :created_at)
            RETURNING id, user_id, fdc_percent, gst_registered, gst_cycle,
                      oscar_enabled, levy_auto_enabled, setup_state, created_at, updated_at
        """)
        
        params = {
            "user_id": str(profile_data.user_id),
            "fdc_percent": profile_data.fdc_percent,
            "gst_registered": profile_data.gst_registered,
            "gst_cycle": profile_data.gst_cycle.value,
            "oscar_enabled": profile_data.oscar_enabled,
            "levy_auto_enabled": profile_data.levy_auto_enabled,
            "setup_state": setup_state_json,
            "created_at": datetime.now(timezone.utc)
        }
        
        result = await self.db.execute(query, params)
        await self.db.commit()
        row = result.fetchone()
        
        setup_state_data = row.setup_state if row.setup_state else {}
        if isinstance(setup_state_data, str):
            setup_state_data = json.loads(setup_state_data)
        
        return UserProfileResponse(
            id=row.id,
            user_id=row.user_id,
            fdc_percent=row.fdc_percent,
            gst_registered=row.gst_registered,
            gst_cycle=row.gst_cycle,
            oscar_enabled=row.oscar_enabled,
            levy_auto_enabled=row.levy_auto_enabled,
            setup_state=SetupState(**setup_state_data),
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    async def update_user_profile(
        self,
        user_id: UUID,
        profile_data: UserProfileUpdate
    ) -> Optional[UserProfileResponse]:
        """Update user profile"""
        updates = ["updated_at = :updated_at"]
        params = {
            "user_id": str(user_id),
            "updated_at": datetime.now(timezone.utc)
        }
        
        update_dict = profile_data.model_dump(exclude_none=True)
        for key, value in update_dict.items():
            if key == 'setup_state' and value:
                updates.append(f"{key} = :{key}::jsonb")
                params[key] = json.dumps(value.model_dump() if hasattr(value, 'model_dump') else value)
            elif key == 'gst_cycle' and value:
                updates.append(f"{key} = :{key}")
                params[key] = value.value if hasattr(value, 'value') else value
            else:
                updates.append(f"{key} = :{key}")
                params[key] = value
        
        query = text(f"""
            UPDATE user_profiles SET {', '.join(updates)}
            WHERE user_id = :user_id
            RETURNING id, user_id, fdc_percent, gst_registered, gst_cycle,
                      oscar_enabled, levy_auto_enabled, setup_state, created_at, updated_at
        """)
        
        result = await self.db.execute(query, params)
        await self.db.commit()
        row = result.fetchone()
        
        if not row:
            return None
        
        setup_state_data = row.setup_state if row.setup_state else {}
        if isinstance(setup_state_data, str):
            setup_state_data = json.loads(setup_state_data)
        
        return UserProfileResponse(
            id=row.id,
            user_id=row.user_id,
            fdc_percent=row.fdc_percent or 0,
            gst_registered=row.gst_registered or False,
            gst_cycle=row.gst_cycle or 'none',
            oscar_enabled=row.oscar_enabled or False,
            levy_auto_enabled=row.levy_auto_enabled or False,
            setup_state=SetupState(**setup_state_data),
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    async def update_onboarding_state(
        self,
        user_id: UUID,
        request: OnboardingUpdateRequest
    ) -> Optional[UserProfileResponse]:
        """Update specific onboarding flags in setup_state JSONB"""
        # First get current setup_state
        profile = await self.get_user_profile(user_id)
        if not profile:
            return None
        
        # Merge updates with existing state
        current_state = profile.setup_state.model_dump()
        update_dict = request.model_dump(exclude_none=True)
        current_state.update(update_dict)
        
        # Update with merged state
        query = text("""
            UPDATE user_profiles 
            SET setup_state = :setup_state::jsonb, updated_at = :updated_at
            WHERE user_id = :user_id
            RETURNING id, user_id, fdc_percent, gst_registered, gst_cycle,
                      oscar_enabled, levy_auto_enabled, setup_state, created_at, updated_at
        """)
        
        params = {
            "user_id": str(user_id),
            "setup_state": json.dumps(current_state),
            "updated_at": datetime.now(timezone.utc)
        }
        
        result = await self.db.execute(query, params)
        await self.db.commit()
        row = result.fetchone()
        
        if not row:
            return None
        
        setup_state_data = row.setup_state if row.setup_state else {}
        if isinstance(setup_state_data, str):
            setup_state_data = json.loads(setup_state_data)
        
        return UserProfileResponse(
            id=row.id,
            user_id=row.user_id,
            fdc_percent=row.fdc_percent or 0,
            gst_registered=row.gst_registered or False,
            gst_cycle=row.gst_cycle or 'none',
            oscar_enabled=row.oscar_enabled or False,
            levy_auto_enabled=row.levy_auto_enabled or False,
            setup_state=SetupState(**setup_state_data),
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    # ==================== TASK OPERATIONS ====================
    
    async def get_user_tasks(
        self,
        user_id: UUID,
        status: Optional[str] = None
    ) -> List[TaskResponse]:
        """Get tasks for a specific user"""
        conditions = ["user_id = :user_id"]
        params = {"user_id": str(user_id)}
        
        if status:
            conditions.append("status = :status")
            params["status"] = status
        
        query = text(f"""
            SELECT id, user_id, title, description, due_date, status, source,
                   created_at, updated_at
            FROM tasks
            WHERE {' AND '.join(conditions)}
            ORDER BY due_date ASC NULLS LAST, created_at DESC
        """)
        
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        return [
            TaskResponse(
                id=row.id,
                user_id=row.user_id,
                title=row.title,
                description=row.description,
                due_date=row.due_date,
                status=row.status,
                source=row.source,
                created_at=row.created_at,
                updated_at=row.updated_at
            )
            for row in rows
        ]
    
    async def list_tasks(
        self,
        status: Optional[str] = None,
        source: Optional[str] = None,
        user_id: Optional[UUID] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[TaskResponse]:
        """List all tasks with filters"""
        conditions = []
        params = {"limit": limit, "offset": offset}
        
        if status:
            conditions.append("status = :status")
            params["status"] = status
        
        if source:
            conditions.append("source = :source")
            params["source"] = source
        
        if user_id:
            conditions.append("user_id = :user_id")
            params["user_id"] = str(user_id)
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        query = text(f"""
            SELECT id, user_id, title, description, due_date, status, source,
                   created_at, updated_at
            FROM tasks
            {where_clause}
            ORDER BY due_date ASC NULLS LAST, created_at DESC
            LIMIT :limit OFFSET :offset
        """)
        
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        return [
            TaskResponse(
                id=row.id,
                user_id=row.user_id,
                title=row.title,
                description=row.description,
                due_date=row.due_date,
                status=row.status,
                source=row.source,
                created_at=row.created_at,
                updated_at=row.updated_at
            )
            for row in rows
        ]
    
    async def create_task(self, task_data: TaskCreate) -> TaskResponse:
        """Create new task"""
        query = text("""
            INSERT INTO tasks 
            (user_id, title, description, due_date, status, source, created_at)
            VALUES (:user_id, :title, :description, :due_date, :status, :source, :created_at)
            RETURNING id, user_id, title, description, due_date, status, source,
                      created_at, updated_at
        """)
        
        params = {
            "user_id": str(task_data.user_id),
            "title": task_data.title,
            "description": task_data.description,
            "due_date": task_data.due_date,
            "status": task_data.status.value,
            "source": task_data.source.value,
            "created_at": datetime.now(timezone.utc)
        }
        
        result = await self.db.execute(query, params)
        await self.db.commit()
        row = result.fetchone()
        
        return TaskResponse(
            id=row.id,
            user_id=row.user_id,
            title=row.title,
            description=row.description,
            due_date=row.due_date,
            status=row.status,
            source=row.source,
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    async def update_task(self, task_id: UUID, task_data: TaskUpdate) -> Optional[TaskResponse]:
        """Update task"""
        updates = ["updated_at = :updated_at"]
        params = {
            "task_id": str(task_id),
            "updated_at": datetime.now(timezone.utc)
        }
        
        update_dict = task_data.model_dump(exclude_none=True)
        for key, value in update_dict.items():
            if key in ('status', 'source') and value:
                updates.append(f"{key} = :{key}")
                params[key] = value.value if hasattr(value, 'value') else value
            else:
                updates.append(f"{key} = :{key}")
                params[key] = value
        
        query = text(f"""
            UPDATE tasks SET {', '.join(updates)}
            WHERE id = :task_id
            RETURNING id, user_id, title, description, due_date, status, source,
                      created_at, updated_at
        """)
        
        result = await self.db.execute(query, params)
        await self.db.commit()
        row = result.fetchone()
        
        if not row:
            return None
        
        return TaskResponse(
            id=row.id,
            user_id=row.user_id,
            title=row.title,
            description=row.description,
            due_date=row.due_date,
            status=row.status,
            source=row.source,
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    async def delete_task(self, task_id: UUID) -> bool:
        """Delete task"""
        query = text("DELETE FROM tasks WHERE id = :task_id RETURNING id")
        result = await self.db.execute(query, {"task_id": str(task_id)})
        await self.db.commit()
        return result.fetchone() is not None
    
    # ==================== KB ENTRY OPERATIONS ====================
    
    async def list_kb_entries(
        self,
        classification: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[KBEntryResponse]:
        """List KB entries with filters"""
        conditions = []
        params = {"limit": limit, "offset": offset}
        
        if classification:
            conditions.append("classification = :classification")
            params["classification"] = classification
        
        if search:
            conditions.append("""
                (title ILIKE :search OR tags ILIKE :search OR 
                 variations ILIKE :search OR answer ILIKE :search)
            """)
            params["search"] = f"%{search}%"
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        query = text(f"""
            SELECT id, title, tags, variations, answer, classification,
                   exclusive_note, ato_source, created_at, updated_at
            FROM kb_entries
            {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """)
        
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        return [
            KBEntryResponse(
                id=row.id,
                title=row.title,
                tags=row.tags,
                variations=row.variations,
                answer=row.answer,
                classification=row.classification,
                exclusive_note=row.exclusive_note,
                ato_source=row.ato_source,
                created_at=row.created_at,
                updated_at=row.updated_at
            )
            for row in rows
        ]
    
    async def get_kb_entry(self, entry_id: int) -> Optional[KBEntryResponse]:
        """Get KB entry by ID"""
        query = text("""
            SELECT id, title, tags, variations, answer, classification,
                   exclusive_note, ato_source, created_at, updated_at
            FROM kb_entries WHERE id = :entry_id
        """)
        
        result = await self.db.execute(query, {"entry_id": entry_id})
        row = result.fetchone()
        
        if not row:
            return None
        
        return KBEntryResponse(
            id=row.id,
            title=row.title,
            tags=row.tags,
            variations=row.variations,
            answer=row.answer,
            classification=row.classification,
            exclusive_note=row.exclusive_note,
            ato_source=row.ato_source,
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    async def create_kb_entry(self, entry_data: KBEntryCreate) -> KBEntryResponse:
        """Create new KB entry"""
        query = text("""
            INSERT INTO kb_entries 
            (title, tags, variations, answer, classification, 
             exclusive_note, ato_source, created_at)
            VALUES (:title, :tags, :variations, :answer, :classification,
                    :exclusive_note, :ato_source, :created_at)
            RETURNING id, title, tags, variations, answer, classification,
                      exclusive_note, ato_source, created_at, updated_at
        """)
        
        params = {
            "title": entry_data.title,
            "tags": entry_data.tags,
            "variations": entry_data.variations,
            "answer": entry_data.answer,
            "classification": entry_data.classification.value,
            "exclusive_note": entry_data.exclusive_note,
            "ato_source": entry_data.ato_source,
            "created_at": datetime.now(timezone.utc)
        }
        
        result = await self.db.execute(query, params)
        await self.db.commit()
        row = result.fetchone()
        
        return KBEntryResponse(
            id=row.id,
            title=row.title,
            tags=row.tags,
            variations=row.variations,
            answer=row.answer,
            classification=row.classification,
            exclusive_note=row.exclusive_note,
            ato_source=row.ato_source,
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    async def update_kb_entry(
        self,
        entry_id: int,
        entry_data: KBEntryUpdate
    ) -> Optional[KBEntryResponse]:
        """Update KB entry"""
        updates = ["updated_at = :updated_at"]
        params = {
            "entry_id": entry_id,
            "updated_at": datetime.now(timezone.utc)
        }
        
        update_dict = entry_data.model_dump(exclude_none=True)
        for key, value in update_dict.items():
            if key == 'classification' and value:
                updates.append(f"{key} = :{key}")
                params[key] = value.value if hasattr(value, 'value') else value
            else:
                updates.append(f"{key} = :{key}")
                params[key] = value
        
        query = text(f"""
            UPDATE kb_entries SET {', '.join(updates)}
            WHERE id = :entry_id
            RETURNING id, title, tags, variations, answer, classification,
                      exclusive_note, ato_source, created_at, updated_at
        """)
        
        result = await self.db.execute(query, params)
        await self.db.commit()
        row = result.fetchone()
        
        if not row:
            return None
        
        return KBEntryResponse(
            id=row.id,
            title=row.title,
            tags=row.tags,
            variations=row.variations,
            answer=row.answer,
            classification=row.classification,
            exclusive_note=row.exclusive_note,
            ato_source=row.ato_source,
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    async def delete_kb_entry(self, entry_id: int) -> bool:
        """Delete KB entry"""
        query = text("DELETE FROM kb_entries WHERE id = :entry_id RETURNING id")
        result = await self.db.execute(query, {"entry_id": entry_id})
        await self.db.commit()
        return result.fetchone() is not None
    
    async def search_kb(self, query_text: str, limit: int = 10) -> List[KBEntryResponse]:
        """Search KB entries for Luna"""
        query = text("""
            SELECT id, title, tags, variations, answer, classification,
                   exclusive_note, ato_source, created_at, updated_at
            FROM kb_entries
            WHERE title ILIKE :search OR tags ILIKE :search OR 
                  variations ILIKE :search OR answer ILIKE :search
            ORDER BY 
                CASE WHEN title ILIKE :exact THEN 1
                     WHEN tags ILIKE :exact THEN 2
                     WHEN variations ILIKE :exact THEN 3
                     ELSE 4 END,
                created_at DESC
            LIMIT :limit
        """)
        
        params = {
            "search": f"%{query_text}%",
            "exact": f"%{query_text}%",
            "limit": limit
        }
        
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        return [
            KBEntryResponse(
                id=row.id,
                title=row.title,
                tags=row.tags,
                variations=row.variations,
                answer=row.answer,
                classification=row.classification,
                exclusive_note=row.exclusive_note,
                ato_source=row.ato_source,
                created_at=row.created_at,
                updated_at=row.updated_at
            )
            for row in rows
        ]
    
    # ==================== SYNC OPERATIONS ====================
    
    async def sync_tasks_to_frontend(self, user_id: Optional[UUID] = None) -> Dict[str, Any]:
        """
        Sync tasks from internal CRM to educator dashboards
        This is the CRM → MyFDC frontend sync direction
        """
        try:
            if user_id:
                tasks = await self.get_user_tasks(user_id)
                return {
                    "success": True,
                    "user_id": str(user_id),
                    "tasks_synced": len(tasks),
                    "tasks": [t.model_dump() for t in tasks]
                }
            else:
                # Sync all tasks
                all_tasks = await self.list_tasks(limit=500)
                return {
                    "success": True,
                    "total_tasks_synced": len(all_tasks),
                    "message": "Full task sync completed"
                }
        except Exception as e:
            logger.error(f"Task sync error: {e}")
            return {"success": False, "error": str(e)}
    
    async def sync_profiles_to_frontend(self, user_id: Optional[UUID] = None) -> Dict[str, Any]:
        """
        Sync profile flags (levy_auto, GST status) to frontend
        """
        try:
            if user_id:
                profile = await self.get_user_profile(user_id)
                if profile:
                    return {
                        "success": True,
                        "user_id": str(user_id),
                        "profile_synced": True,
                        "flags": {
                            "levy_auto_enabled": profile.levy_auto_enabled,
                            "gst_registered": profile.gst_registered,
                            "gst_cycle": profile.gst_cycle,
                            "oscar_enabled": profile.oscar_enabled
                        }
                    }
                return {"success": False, "error": "Profile not found"}
            else:
                # Return sync status for all
                return {
                    "success": True,
                    "message": "Profile sync endpoint - use with user_id for specific sync"
                }
        except Exception as e:
            logger.error(f"Profile sync error: {e}")
            return {"success": False, "error": str(e)}
