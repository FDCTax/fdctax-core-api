from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import logging
import json
import uuid

from models import (
    UserResponse, UserCreate, UserUpdate,
    UserProfileResponse, UserProfileCreate, UserProfileUpdate,
    UserSettingsResponse, UserSettingsCreate, UserSettingsUpdate,
    TaskResponse, TaskCreate, TaskUpdate,
    CRMTaskResponse, CRMTaskCreate, CRMTaskUpdate,
    KBEntryResponse, KBEntryCreate, KBEntryUpdate,
    LunaUserSettingsResponse, LunaUserSettingsCreate,
    FDCPercentageResponse,
    SetupState, OnboardingUpdateRequest
)

logger = logging.getLogger(__name__)


class CRMSyncService:
    """
    CRM Sync Service for FDC Tax
    Handles data sync between internal CRM and MyFDC frontend
    Uses myfdc and crm schemas
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ==================== USER OPERATIONS (myfdc.users) ====================
    
    async def get_user(self, user_id: str) -> Optional[UserResponse]:
        """Get user by ID"""
        query = text("""
            SELECT id, email, first_name, last_name, name, is_active, plan,
                   gst_registered, bas_frequency, created_at, updated_at, tax_year
            FROM myfdc.users WHERE id = :user_id
        """)
        result = await self.db.execute(query, {"user_id": user_id})
        row = result.fetchone()
        
        if not row:
            return None
        
        return UserResponse(
            id=row.id,
            email=row.email,
            first_name=row.first_name,
            last_name=row.last_name,
            name=row.name,
            is_active=row.is_active if row.is_active is not None else True,
            plan=row.plan,
            gst_registered=row.gst_registered,
            bas_frequency=row.bas_frequency,
            created_at=row.created_at,
            updated_at=row.updated_at,
            tax_year=row.tax_year
        )
    
    async def get_user_by_email(self, email: str) -> Optional[UserResponse]:
        """Get user by email"""
        query = text("""
            SELECT id, email, first_name, last_name, name, is_active, plan,
                   gst_registered, bas_frequency, created_at, updated_at, tax_year
            FROM myfdc.users WHERE email = :email
        """)
        result = await self.db.execute(query, {"email": email})
        row = result.fetchone()
        
        if not row:
            return None
        
        return UserResponse(
            id=row.id,
            email=row.email,
            first_name=row.first_name,
            last_name=row.last_name,
            name=row.name,
            is_active=row.is_active if row.is_active is not None else True,
            plan=row.plan,
            gst_registered=row.gst_registered,
            bas_frequency=row.bas_frequency,
            created_at=row.created_at,
            updated_at=row.updated_at,
            tax_year=row.tax_year
        )
    
    async def list_users(
        self,
        is_active: Optional[bool] = None,
        plan: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[UserResponse]:
        """List users with optional filters"""
        conditions = []
        params = {"limit": limit, "offset": offset}
        
        if is_active is not None:
            conditions.append("is_active = :is_active")
            params["is_active"] = is_active
        
        if plan:
            conditions.append("plan = :plan")
            params["plan"] = plan
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        query = text(f"""
            SELECT id, email, first_name, last_name, name, is_active, plan,
                   gst_registered, bas_frequency, created_at, updated_at, tax_year
            FROM myfdc.users
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
                name=row.name,
                is_active=row.is_active if row.is_active is not None else True,
                plan=row.plan,
                gst_registered=row.gst_registered,
                bas_frequency=row.bas_frequency,
                created_at=row.created_at,
                updated_at=row.updated_at,
                tax_year=row.tax_year
            )
            for row in rows
        ]
    
    async def update_user(self, user_id: str, user_data: UserUpdate) -> Optional[UserResponse]:
        """Update user"""
        updates = ["updated_at = :updated_at"]
        params = {
            "user_id": user_id,
            "updated_at": datetime.now()
        }
        
        update_dict = user_data.model_dump(exclude_none=True)
        for key, value in update_dict.items():
            updates.append(f"{key} = :{key}")
            params[key] = value
        
        if len(updates) == 1:  # Only updated_at
            return await self.get_user(user_id)
        
        query = text(f"""
            UPDATE myfdc.users SET {', '.join(updates)}
            WHERE id = :user_id
            RETURNING id, email, first_name, last_name, name, is_active, plan,
                      gst_registered, bas_frequency, created_at, updated_at, tax_year
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
            name=row.name,
            is_active=row.is_active if row.is_active is not None else True,
            plan=row.plan,
            gst_registered=row.gst_registered,
            bas_frequency=row.bas_frequency,
            created_at=row.created_at,
            updated_at=row.updated_at,
            tax_year=row.tax_year
        )
    
    # ==================== USER SETTINGS (myfdc.user_settings) ====================
    
    async def get_user_settings(self, user_id: str) -> Optional[UserSettingsResponse]:
        """Get user settings by user_id"""
        query = text("""
            SELECT id, user_id, settings, scheme_name, created_at, updated_at
            FROM myfdc.user_settings WHERE user_id = :user_id
        """)
        
        result = await self.db.execute(query, {"user_id": user_id})
        row = result.fetchone()
        
        if not row:
            return None
        
        settings_data = row.settings if row.settings else {}
        if isinstance(settings_data, str):
            settings_data = json.loads(settings_data)
        
        return UserSettingsResponse(
            id=row.id,
            user_id=row.user_id,
            settings=settings_data,
            scheme_name=row.scheme_name,
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    async def update_user_settings(
        self,
        user_id: str,
        settings_data: UserSettingsUpdate
    ) -> Optional[UserSettingsResponse]:
        """Update user settings - merges with existing settings"""
        # Get current settings
        current = await self.get_user_settings(user_id)
        
        if not current:
            # Create new settings
            new_id = str(uuid.uuid4())
            settings_json = json.dumps(settings_data.settings or {})
            
            query = text("""
                INSERT INTO myfdc.user_settings (id, user_id, settings, scheme_name, created_at)
                VALUES (:id, :user_id, CAST(:settings AS jsonb), :scheme_name, :created_at)
                RETURNING id, user_id, settings, scheme_name, created_at, updated_at
            """)
            
            result = await self.db.execute(query, {
                "id": new_id,
                "user_id": user_id,
                "settings": settings_json,
                "scheme_name": settings_data.scheme_name,
                "created_at": datetime.now()
            })
        else:
            # Merge settings
            merged_settings = current.settings or {}
            if settings_data.settings:
                merged_settings.update(settings_data.settings)
            
            updates = ["updated_at = :updated_at", "settings = CAST(:settings AS jsonb)"]
            params = {
                "user_id": user_id,
                "updated_at": datetime.now(),
                "settings": json.dumps(merged_settings)
            }
            
            if settings_data.scheme_name is not None:
                updates.append("scheme_name = :scheme_name")
                params["scheme_name"] = settings_data.scheme_name
            
            query = text(f"""
                UPDATE myfdc.user_settings SET {', '.join(updates)}
                WHERE user_id = :user_id
                RETURNING id, user_id, settings, scheme_name, created_at, updated_at
            """)
            
            result = await self.db.execute(query, params)
        
        await self.db.commit()
        row = result.fetchone()
        
        if not row:
            return None
        
        settings_data_result = row.settings if row.settings else {}
        if isinstance(settings_data_result, str):
            settings_data_result = json.loads(settings_data_result)
        
        return UserSettingsResponse(
            id=row.id,
            user_id=row.user_id,
            settings=settings_data_result,
            scheme_name=row.scheme_name,
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    # ==================== USER PROFILE (combined view) ====================
    
    async def get_user_profile(self, user_id: str) -> Optional[UserProfileResponse]:
        """Get user profile - combines user data, settings, and FDC percentage"""
        # Get user
        user = await self.get_user(user_id)
        if not user:
            return None
        
        # Get settings
        settings = await self.get_user_settings(user_id)
        
        # Get latest FDC percentage
        fdc_query = text("""
            SELECT percentage FROM myfdc.user_fdc_percentages 
            WHERE user_id = :user_id 
            ORDER BY created_at DESC LIMIT 1
        """)
        fdc_result = await self.db.execute(fdc_query, {"user_id": user_id})
        fdc_row = fdc_result.fetchone()
        fdc_percent = float(fdc_row.percentage) if fdc_row and fdc_row.percentage else 0
        
        # Build setup_state from settings
        setup_state_data = {}
        if settings and settings.settings:
            setup_state_data = settings.settings.get('setup_state', {})
        
        # Check luna_user_settings for welcome state
        luna_query = text("""
            SELECT has_seen_welcome FROM myfdc.luna_user_settings 
            WHERE user_email = :email
        """)
        luna_result = await self.db.execute(luna_query, {"email": user.email})
        luna_row = luna_result.fetchone()
        if luna_row:
            setup_state_data['welcome_complete'] = luna_row.has_seen_welcome or False
        
        setup_state = SetupState(**setup_state_data)
        
        return UserProfileResponse(
            id=user.id,
            user_id=user.id,
            fdc_percent=fdc_percent,
            gst_registered=user.gst_registered or False,
            gst_cycle=user.bas_frequency or "none",
            oscar_enabled=settings.settings.get('oscar_enabled', False) if settings and settings.settings else False,
            levy_auto_enabled=settings.settings.get('levy_auto_enabled', False) if settings and settings.settings else False,
            setup_state=setup_state,
            created_at=user.created_at,
            updated_at=user.updated_at
        )
    
    async def update_user_profile(
        self,
        user_id: str,
        profile_data: UserProfileUpdate
    ) -> Optional[UserProfileResponse]:
        """Update user profile - updates relevant tables"""
        user = await self.get_user(user_id)
        if not user:
            return None
        
        # Update user table fields
        if profile_data.gst_registered is not None or profile_data.gst_cycle is not None:
            user_update = UserUpdate()
            if profile_data.gst_registered is not None:
                user_update.gst_registered = profile_data.gst_registered
            if profile_data.gst_cycle is not None:
                user_update.bas_frequency = profile_data.gst_cycle
            await self.update_user(user_id, user_update)
        
        # Update settings
        settings_update = {}
        if profile_data.oscar_enabled is not None:
            settings_update['oscar_enabled'] = profile_data.oscar_enabled
        if profile_data.levy_auto_enabled is not None:
            settings_update['levy_auto_enabled'] = profile_data.levy_auto_enabled
        if profile_data.setup_state is not None:
            settings_update['setup_state'] = profile_data.setup_state.model_dump()
        
        if settings_update:
            await self.update_user_settings(user_id, UserSettingsUpdate(settings=settings_update))
        
        # Update FDC percentage
        if profile_data.fdc_percent is not None:
            new_id = str(uuid.uuid4())
            fdc_query = text("""
                INSERT INTO myfdc.user_fdc_percentages (id, user_id, percentage, created_at)
                VALUES (:id, :user_id, :percentage, :created_at)
            """)
            await self.db.execute(fdc_query, {
                "id": new_id,
                "user_id": user_id,
                "percentage": profile_data.fdc_percent,
                "created_at": datetime.now()
            })
            await self.db.commit()
        
        return await self.get_user_profile(user_id)
    
    async def update_onboarding_state(
        self,
        user_id: str,
        request: OnboardingUpdateRequest
    ) -> Optional[UserProfileResponse]:
        """Update specific onboarding flags in setup_state"""
        profile = await self.get_user_profile(user_id)
        if not profile:
            return None
        
        # Merge updates with existing state
        current_state = profile.setup_state.model_dump()
        update_dict = request.model_dump(exclude_none=True)
        current_state.update(update_dict)
        
        # Update via settings
        settings_update = UserSettingsUpdate(settings={'setup_state': current_state})
        await self.update_user_settings(user_id, settings_update)
        
        # Update luna_user_settings if welcome_complete changed
        if request.welcome_complete is not None:
            user = await self.get_user(user_id)
            if user:
                luna_check = text("SELECT 1 FROM myfdc.luna_user_settings WHERE user_email = :email")
                exists = (await self.db.execute(luna_check, {"email": user.email})).fetchone()
                
                if exists:
                    luna_update = text("""
                        UPDATE myfdc.luna_user_settings 
                        SET has_seen_welcome = :has_seen 
                        WHERE user_email = :email
                    """)
                else:
                    luna_update = text("""
                        INSERT INTO myfdc.luna_user_settings (user_email, has_seen_welcome, created_at)
                        VALUES (:email, :has_seen, :created_at)
                    """)
                
                await self.db.execute(luna_update, {
                    "email": user.email,
                    "has_seen": request.welcome_complete,
                    "created_at": datetime.now()
                })
                await self.db.commit()
        
        return await self.get_user_profile(user_id)
    
    # ==================== TASK OPERATIONS (myfdc.user_tasks) ====================
    
    async def get_user_tasks(
        self,
        user_id: str,
        status: Optional[str] = None
    ) -> List[TaskResponse]:
        """Get tasks for a specific user"""
        conditions = ["user_id = CAST(:user_id AS uuid)"]
        params = {"user_id": user_id}
        
        if status:
            conditions.append("status = :status")
            params["status"] = status
        
        query = text(f"""
            SELECT id, user_id, task_name, description, due_date, status, 
                   priority, category, task_type, created_at, updated_at
            FROM myfdc.user_tasks
            WHERE {' AND '.join(conditions)}
            ORDER BY due_date ASC NULLS LAST, created_at DESC
        """)
        
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        return [
            TaskResponse(
                id=str(row.id),
                user_id=str(row.user_id),
                task_name=row.task_name,
                description=row.description,
                due_date=row.due_date,
                status=row.status or 'pending',
                priority=row.priority,
                category=row.category,
                task_type=row.task_type,
                created_at=row.created_at,
                updated_at=row.updated_at
            )
            for row in rows
        ]
    
    async def list_tasks(
        self,
        status: Optional[str] = None,
        user_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[TaskResponse]:
        """List all tasks with filters"""
        conditions = []
        params = {"limit": limit, "offset": offset}
        
        if status:
            conditions.append("status = :status")
            params["status"] = status
        
        if user_id:
            conditions.append("user_id = CAST(:user_id AS uuid)")
            params["user_id"] = user_id
        
        if category:
            conditions.append("category = :category")
            params["category"] = category
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        query = text(f"""
            SELECT id, user_id, task_name, description, due_date, status,
                   priority, category, task_type, created_at, updated_at
            FROM myfdc.user_tasks
            {where_clause}
            ORDER BY due_date ASC NULLS LAST, created_at DESC
            LIMIT :limit OFFSET :offset
        """)
        
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        return [
            TaskResponse(
                id=str(row.id),
                user_id=str(row.user_id),
                task_name=row.task_name,
                description=row.description,
                due_date=row.due_date,
                status=row.status or 'pending',
                priority=row.priority,
                category=row.category,
                task_type=row.task_type,
                created_at=row.created_at,
                updated_at=row.updated_at
            )
            for row in rows
        ]
    
    async def create_task(self, task_data: TaskCreate) -> TaskResponse:
        """Create new task"""
        new_id = str(uuid.uuid4())
        
        query = text("""
            INSERT INTO myfdc.user_tasks 
            (id, user_id, task_name, description, due_date, status, priority, category, task_type, created_at)
            VALUES (CAST(:id AS uuid), CAST(:user_id AS uuid), :task_name, :description, :due_date, :status, :priority, :category, :task_type, :created_at)
            RETURNING id, user_id, task_name, description, due_date, status, priority, category, task_type, created_at, updated_at
        """)
        
        params = {
            "id": new_id,
            "user_id": task_data.user_id,
            "task_name": task_data.task_name,
            "description": task_data.description,
            "due_date": task_data.due_date,
            "status": task_data.status,
            "priority": task_data.priority,
            "category": task_data.category,
            "task_type": task_data.task_type,
            "created_at": datetime.now()
        }
        
        result = await self.db.execute(query, params)
        await self.db.commit()
        row = result.fetchone()
        
        return TaskResponse(
            id=str(row.id),
            user_id=str(row.user_id),
            task_name=row.task_name,
            description=row.description,
            due_date=row.due_date,
            status=row.status,
            priority=row.priority,
            category=row.category,
            task_type=row.task_type,
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    async def update_task(self, task_id: str, task_data: TaskUpdate) -> Optional[TaskResponse]:
        """Update task"""
        updates = ["updated_at = :updated_at"]
        params = {
            "task_id": task_id,
            "updated_at": datetime.now()
        }
        
        update_dict = task_data.model_dump(exclude_none=True)
        for key, value in update_dict.items():
            updates.append(f"{key} = :{key}")
            params[key] = value
        
        query = text(f"""
            UPDATE myfdc.user_tasks SET {', '.join(updates)}
            WHERE id = CAST(:task_id AS uuid)
            RETURNING id, user_id, task_name, description, due_date, status, priority, category, task_type, created_at, updated_at
        """)
        
        result = await self.db.execute(query, params)
        await self.db.commit()
        row = result.fetchone()
        
        if not row:
            return None
        
        return TaskResponse(
            id=str(row.id),
            user_id=str(row.user_id),
            task_name=row.task_name,
            description=row.description,
            due_date=row.due_date,
            status=row.status,
            priority=row.priority,
            category=row.category,
            task_type=row.task_type,
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    async def delete_task(self, task_id: str) -> bool:
        """Delete task"""
        query = text("DELETE FROM myfdc.user_tasks WHERE id = CAST(:task_id AS uuid) RETURNING id")
        result = await self.db.execute(query, {"task_id": task_id})
        await self.db.commit()
        return result.fetchone() is not None
    
    # ==================== CRM TASK OPERATIONS (crm.tasks) ====================
    
    async def list_crm_tasks(
        self,
        status: Optional[str] = None,
        client_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[CRMTaskResponse]:
        """List CRM tasks"""
        conditions = []
        params = {"limit": limit, "offset": offset}
        
        if status:
            conditions.append("status = :status")
            params["status"] = status
        
        if client_id:
            conditions.append("client_id = :client_id")
            params["client_id"] = client_id
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        query = text(f"""
            SELECT id, client_id, title, description, status, due_date, priority,
                   assigned_to, input_type, custom_options, notify_on_complete,
                   client_response, client_amount, client_files, client_comment,
                   submitted_at, agent_notes, created_at, updated_at
            FROM crm.tasks
            {where_clause}
            ORDER BY due_date ASC NULLS LAST, created_at DESC
            LIMIT :limit OFFSET :offset
        """)
        
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        return [
            CRMTaskResponse(
                id=row.id,
                client_id=row.client_id,
                title=row.title,
                description=row.description,
                status=row.status or 'pending',
                due_date=row.due_date,
                priority=row.priority,
                assigned_to=row.assigned_to,
                input_type=row.input_type,
                custom_options=list(row.custom_options) if row.custom_options else None,
                notify_on_complete=row.notify_on_complete or False,
                client_response=row.client_response,
                client_amount=float(row.client_amount) if row.client_amount else None,
                client_files=row.client_files,
                client_comment=row.client_comment,
                submitted_at=row.submitted_at,
                agent_notes=row.agent_notes,
                created_at=row.created_at,
                updated_at=row.updated_at
            )
            for row in rows
        ]
    
    async def create_crm_task(self, task_data: CRMTaskCreate) -> CRMTaskResponse:
        """Create CRM task"""
        query = text("""
            INSERT INTO crm.tasks 
            (client_id, title, description, status, due_date, priority, assigned_to, 
             input_type, custom_options, notify_on_complete, created_at)
            VALUES (:client_id, :title, :description, :status, :due_date, :priority, 
                    :assigned_to, :input_type, :custom_options, :notify_on_complete, :created_at)
            RETURNING id, client_id, title, description, status, due_date, priority,
                      assigned_to, input_type, custom_options, notify_on_complete,
                      client_response, client_amount, client_files, client_comment,
                      submitted_at, agent_notes, created_at, updated_at
        """)
        
        params = {
            "client_id": task_data.client_id,
            "title": task_data.title,
            "description": task_data.description,
            "status": task_data.status,
            "due_date": task_data.due_date,
            "priority": task_data.priority,
            "assigned_to": task_data.assigned_to,
            "input_type": task_data.input_type,
            "custom_options": task_data.custom_options,
            "notify_on_complete": task_data.notify_on_complete,
            "created_at": datetime.now(timezone.utc)
        }
        
        result = await self.db.execute(query, params)
        await self.db.commit()
        row = result.fetchone()
        
        return CRMTaskResponse(
            id=row.id,
            client_id=row.client_id,
            title=row.title,
            description=row.description,
            status=row.status,
            due_date=row.due_date,
            priority=row.priority,
            assigned_to=row.assigned_to,
            input_type=row.input_type,
            custom_options=list(row.custom_options) if row.custom_options else None,
            notify_on_complete=row.notify_on_complete or False,
            client_response=row.client_response,
            client_amount=float(row.client_amount) if row.client_amount else None,
            client_files=row.client_files,
            client_comment=row.client_comment,
            submitted_at=row.submitted_at,
            agent_notes=row.agent_notes,
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    async def update_crm_task(self, task_id: int, task_data: CRMTaskUpdate) -> Optional[CRMTaskResponse]:
        """Update CRM task"""
        updates = ["updated_at = :updated_at"]
        params = {
            "task_id": task_id,
            "updated_at": datetime.now()
        }
        
        update_dict = task_data.model_dump(exclude_none=True)
        for key, value in update_dict.items():
            updates.append(f"{key} = :{key}")
            params[key] = value
        
        query = text(f"""
            UPDATE crm.tasks SET {', '.join(updates)}
            WHERE id = :task_id
            RETURNING id, client_id, title, description, status, due_date, priority,
                      assigned_to, input_type, custom_options, notify_on_complete,
                      client_response, client_amount, client_files, client_comment,
                      submitted_at, agent_notes, created_at, updated_at
        """)
        
        result = await self.db.execute(query, params)
        await self.db.commit()
        row = result.fetchone()
        
        if not row:
            return None
        
        return CRMTaskResponse(
            id=row.id,
            client_id=row.client_id,
            title=row.title,
            description=row.description,
            status=row.status,
            due_date=row.due_date,
            priority=row.priority,
            assigned_to=row.assigned_to,
            input_type=row.input_type,
            custom_options=list(row.custom_options) if row.custom_options else None,
            notify_on_complete=row.notify_on_complete or False,
            client_response=row.client_response,
            client_amount=float(row.client_amount) if row.client_amount else None,
            client_files=row.client_files,
            client_comment=row.client_comment,
            submitted_at=row.submitted_at,
            agent_notes=row.agent_notes,
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    # ==================== KB ENTRY OPERATIONS (myfdc.luna_knowledge_base) ====================
    
    async def list_kb_entries(
        self,
        category: Optional[str] = None,
        search: Optional[str] = None,
        is_active: Optional[bool] = True,
        limit: int = 50,
        offset: int = 0
    ) -> List[KBEntryResponse]:
        """List KB entries with filters"""
        conditions = []
        params = {"limit": limit, "offset": offset}
        
        if category:
            conditions.append("category = :category")
            params["category"] = category
        
        if is_active is not None:
            conditions.append("is_active = :is_active")
            params["is_active"] = is_active
        
        if search:
            conditions.append("""
                (question ILIKE :search OR tags ILIKE :search OR 
                 question_variations ILIKE :search OR answer ILIKE :search)
            """)
            params["search"] = f"%{search}%"
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        query = text(f"""
            SELECT id, question, answer, category, is_active, tags,
                   question_variations, related_questions, answer_format,
                   created_at, updated_at
            FROM myfdc.luna_knowledge_base
            {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """)
        
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        return [
            KBEntryResponse(
                id=row.id,
                question=row.question,
                answer=row.answer,
                category=row.category,
                is_active=row.is_active if row.is_active is not None else True,
                tags=row.tags,
                question_variations=row.question_variations,
                related_questions=row.related_questions,
                answer_format=row.answer_format,
                created_at=row.created_at,
                updated_at=row.updated_at
            )
            for row in rows
        ]
    
    async def get_kb_entry(self, entry_id: int) -> Optional[KBEntryResponse]:
        """Get KB entry by ID"""
        query = text("""
            SELECT id, question, answer, category, is_active, tags,
                   question_variations, related_questions, answer_format,
                   created_at, updated_at
            FROM myfdc.luna_knowledge_base WHERE id = :entry_id
        """)
        
        result = await self.db.execute(query, {"entry_id": entry_id})
        row = result.fetchone()
        
        if not row:
            return None
        
        return KBEntryResponse(
            id=row.id,
            question=row.question,
            answer=row.answer,
            category=row.category,
            is_active=row.is_active if row.is_active is not None else True,
            tags=row.tags,
            question_variations=row.question_variations,
            related_questions=row.related_questions,
            answer_format=row.answer_format,
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    async def search_kb(self, query_text: str, limit: int = 10) -> List[KBEntryResponse]:
        """Search KB entries for Luna"""
        query = text("""
            SELECT id, question, answer, category, is_active, tags,
                   question_variations, related_questions, answer_format,
                   created_at, updated_at
            FROM myfdc.luna_knowledge_base
            WHERE is_active = true AND (
                question ILIKE :search OR tags ILIKE :search OR 
                question_variations ILIKE :search OR answer ILIKE :search
            )
            ORDER BY 
                CASE WHEN question ILIKE :exact THEN 1
                     WHEN tags ILIKE :exact THEN 2
                     WHEN question_variations ILIKE :exact THEN 3
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
                question=row.question,
                answer=row.answer,
                category=row.category,
                is_active=row.is_active if row.is_active is not None else True,
                tags=row.tags,
                question_variations=row.question_variations,
                related_questions=row.related_questions,
                answer_format=row.answer_format,
                created_at=row.created_at,
                updated_at=row.updated_at
            )
            for row in rows
        ]
    
    # ==================== SYNC OPERATIONS ====================
    
    async def sync_tasks_to_frontend(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Sync tasks from internal CRM to educator dashboards
        This is the CRM → MyFDC frontend sync direction
        """
        try:
            if user_id:
                tasks = await self.get_user_tasks(user_id)
                return {
                    "success": True,
                    "user_id": user_id,
                    "tasks_synced": len(tasks),
                    "tasks": [t.model_dump() for t in tasks]
                }
            else:
                all_tasks = await self.list_tasks(limit=500)
                return {
                    "success": True,
                    "total_tasks_synced": len(all_tasks),
                    "message": "Full task sync completed"
                }
        except Exception as e:
            logger.error(f"Task sync error: {e}")
            return {"success": False, "error": str(e)}
    
    async def sync_profiles_to_frontend(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Sync profile flags (levy_auto, GST status) to frontend
        """
        try:
            if user_id:
                profile = await self.get_user_profile(user_id)
                if profile:
                    return {
                        "success": True,
                        "user_id": user_id,
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
                return {
                    "success": True,
                    "message": "Profile sync endpoint - use with user_id for specific sync"
                }
        except Exception as e:
            logger.error(f"Profile sync error: {e}")
            return {"success": False, "error": str(e)}
