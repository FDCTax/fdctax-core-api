from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID, uuid4
from .enums import UserRole, GSTCycle, TaskStatus, TaskSource, KBClassification


# ==================== SETUP STATE ====================
class SetupState(BaseModel):
    """JSONB structure for user onboarding state"""
    welcome_complete: bool = False
    fdc_percent_set: bool = False
    gst_status_set: bool = False
    oscar_intro_seen: bool = False
    levy_auto_enabled: bool = False

    model_config = ConfigDict(extra="allow")


# ==================== USER ====================
class UserBase(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    is_active: bool = True
    role: UserRole = UserRole.educator


class UserCreate(UserBase):
    pass


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: Optional[bool] = None
    role: Optional[UserRole] = None


class User(UserBase):
    id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserResponse(User):
    """Response model for user endpoints"""
    pass


# ==================== USER PROFILE ====================
class UserProfileBase(BaseModel):
    fdc_percent: int = 0
    gst_registered: bool = False
    gst_cycle: GSTCycle = GSTCycle.none
    oscar_enabled: bool = False
    levy_auto_enabled: bool = False
    setup_state: SetupState = Field(default_factory=SetupState)


class UserProfileCreate(UserProfileBase):
    user_id: UUID


class UserProfileUpdate(BaseModel):
    fdc_percent: Optional[int] = None
    gst_registered: Optional[bool] = None
    gst_cycle: Optional[GSTCycle] = None
    oscar_enabled: Optional[bool] = None
    levy_auto_enabled: Optional[bool] = None
    setup_state: Optional[SetupState] = None


class UserProfile(UserProfileBase):
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class UserProfileResponse(UserProfile):
    """Response model for profile endpoints"""
    pass


# ==================== TASK ====================
class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[date] = None
    status: TaskStatus = TaskStatus.pending
    source: TaskSource = TaskSource.system


class TaskCreate(TaskBase):
    user_id: UUID


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[date] = None
    status: Optional[TaskStatus] = None
    source: Optional[TaskSource] = None


class Task(TaskBase):
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TaskResponse(Task):
    """Response model for task endpoints"""
    pass


# ==================== KB ENTRY ====================
class KBEntryBase(BaseModel):
    title: str
    tags: Optional[str] = None
    variations: Optional[str] = None
    answer: str
    classification: KBClassification
    exclusive_note: Optional[str] = None
    ato_source: Optional[str] = None


class KBEntryCreate(KBEntryBase):
    pass


class KBEntryUpdate(BaseModel):
    title: Optional[str] = None
    tags: Optional[str] = None
    variations: Optional[str] = None
    answer: Optional[str] = None
    classification: Optional[KBClassification] = None
    exclusive_note: Optional[str] = None
    ato_source: Optional[str] = None


class KBEntry(KBEntryBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class KBEntryResponse(KBEntry):
    """Response model for KB endpoints"""
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
