from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import Optional, List, Any, Dict
from datetime import datetime, date
from uuid import UUID
import json


# ==================== SETUP STATE ====================
class SetupState(BaseModel):
    """JSONB structure for user onboarding state (stored in user_settings)"""
    welcome_complete: bool = False
    fdc_percent_set: bool = False
    gst_status_set: bool = False
    oscar_intro_seen: bool = False
    levy_auto_enabled: bool = False
    escalation_pending: Optional[bool] = None
    last_escalation: Optional[str] = None

    model_config = ConfigDict(extra="allow")


# ==================== USER (myfdc.users) ====================
class UserBase(BaseModel):
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    name: Optional[str] = None
    is_active: bool = True
    plan: Optional[str] = None
    gst_registered: Optional[bool] = False
    bas_frequency: Optional[str] = None


class UserCreate(BaseModel):
    email: str
    first_name: str
    last_name: str
    password_hash: Optional[str] = None
    plan: str = "basic"
    gst_registered: bool = False
    bas_frequency: str = "quarterly"


class UserUpdate(BaseModel):
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    name: Optional[str] = None
    is_active: Optional[bool] = None
    plan: Optional[str] = None
    gst_registered: Optional[bool] = None
    bas_frequency: Optional[str] = None


class User(UserBase):
    id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    tax_year: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UserResponse(User):
    """Response model for user endpoints"""
    pass


# ==================== USER SETTINGS / PROFILE (myfdc.user_settings) ====================
class UserSettingsBase(BaseModel):
    settings: Optional[Dict[str, Any]] = Field(default_factory=dict)
    scheme_name: Optional[str] = None


class UserSettingsCreate(UserSettingsBase):
    user_id: str


class UserSettingsUpdate(BaseModel):
    settings: Optional[Dict[str, Any]] = None
    scheme_name: Optional[str] = None


class UserSettings(UserSettingsBase):
    id: str
    user_id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class UserSettingsResponse(UserSettings):
    """Response model for settings endpoints"""
    pass


# ==================== USER PROFILE (combined view) ====================
class UserProfileBase(BaseModel):
    """Combined user profile view with settings"""
    fdc_percent: Optional[float] = 0
    gst_registered: bool = False
    gst_cycle: Optional[str] = "none"  # bas_frequency
    oscar_enabled: bool = False
    levy_auto_enabled: bool = False
    setup_state: SetupState = Field(default_factory=SetupState)


class UserProfileCreate(UserProfileBase):
    user_id: str


class UserProfileUpdate(BaseModel):
    fdc_percent: Optional[float] = None
    gst_registered: Optional[bool] = None
    gst_cycle: Optional[str] = None
    oscar_enabled: Optional[bool] = None
    levy_auto_enabled: Optional[bool] = None
    setup_state: Optional[SetupState] = None


class UserProfile(UserProfileBase):
    id: str
    user_id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class UserProfileResponse(UserProfile):
    """Response model for profile endpoints"""
    pass


# ==================== TASK (myfdc.user_tasks) ====================
class TaskBase(BaseModel):
    task_name: str
    description: Optional[str] = None
    due_date: Optional[date] = None
    status: str = "pending"
    priority: Optional[str] = "normal"
    category: Optional[str] = None
    task_type: Optional[str] = None


class TaskCreate(TaskBase):
    user_id: str  # UUID as string


class TaskUpdate(BaseModel):
    task_name: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[date] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    task_type: Optional[str] = None


class Task(TaskBase):
    id: str  # UUID as string
    user_id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TaskResponse(Task):
    """Response model for task endpoints"""
    pass


# ==================== CRM TASK (crm.tasks) ====================
class CRMTaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    status: str = "pending"
    due_date: Optional[date] = None
    priority: Optional[str] = "normal"
    assigned_to: Optional[str] = None
    input_type: Optional[str] = None
    custom_options: Optional[List[str]] = None
    notify_on_complete: bool = False


class CRMTaskCreate(CRMTaskBase):
    client_id: int


class CRMTaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[date] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None
    client_response: Optional[str] = None
    client_amount: Optional[float] = None
    client_comment: Optional[str] = None
    agent_notes: Optional[str] = None


class CRMTask(CRMTaskBase):
    id: int
    client_id: int
    client_response: Optional[str] = None
    client_amount: Optional[float] = None
    client_files: Optional[Dict[str, Any]] = None
    client_comment: Optional[str] = None
    submitted_at: Optional[datetime] = None
    agent_notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CRMTaskResponse(CRMTask):
    """Response model for CRM task endpoints"""
    pass


# ==================== KB ENTRY (myfdc.luna_knowledge_base) ====================
class KBEntryBase(BaseModel):
    question: str
    answer: str
    category: Optional[str] = None
    is_active: bool = True
    tags: Optional[str] = None
    question_variations: Optional[str] = None
    related_questions: Optional[str] = None
    answer_format: Optional[str] = None


class KBEntryCreate(KBEntryBase):
    pass


class KBEntryUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None
    tags: Optional[str] = None
    question_variations: Optional[str] = None
    related_questions: Optional[str] = None
    answer_format: Optional[str] = None


class KBEntry(KBEntryBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class KBEntryResponse(KBEntry):
    """Response model for KB endpoints"""
    pass


# ==================== LUNA USER SETTINGS (myfdc.luna_user_settings) ====================
class LunaUserSettingsBase(BaseModel):
    has_seen_welcome: bool = False


class LunaUserSettingsCreate(LunaUserSettingsBase):
    user_email: str


class LunaUserSettingsUpdate(BaseModel):
    has_seen_welcome: Optional[bool] = None


class LunaUserSettings(LunaUserSettingsBase):
    user_email: str
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class LunaUserSettingsResponse(LunaUserSettings):
    """Response model for Luna settings endpoints"""
    pass


# ==================== FDC PERCENTAGE (myfdc.user_fdc_percentages) ====================
class FDCPercentageBase(BaseModel):
    percentage: float
    business_year_id: Optional[str] = None


class FDCPercentageCreate(FDCPercentageBase):
    user_id: str


class FDCPercentageUpdate(BaseModel):
    percentage: Optional[float] = None
    business_year_id: Optional[str] = None


class FDCPercentage(FDCPercentageBase):
    id: str
    user_id: str
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class FDCPercentageResponse(FDCPercentage):
    """Response model for FDC percentage endpoints"""
    pass


# ==================== REQUEST MODELS ====================
class OscarToggleRequest(BaseModel):
    """Request to toggle Oscar preprocessing"""
    enabled: bool


class OnboardingUpdateRequest(BaseModel):
    """Request to update specific onboarding flags"""
    welcome_complete: Optional[bool] = None
    fdc_percent_set: Optional[bool] = None
    gst_status_set: Optional[bool] = None
    oscar_intro_seen: Optional[bool] = None
    levy_auto_enabled: Optional[bool] = None
