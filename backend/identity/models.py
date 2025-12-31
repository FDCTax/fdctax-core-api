"""
Identity Spine - Database Models

SQLAlchemy models for the unified identity system.
"""

import uuid
from datetime import datetime, timezone, date
from typing import Optional, Dict, Any, List
from enum import Enum

from sqlalchemy import (
    Column, String, Boolean, Integer, Date, DateTime, 
    ForeignKey, Text, JSON, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class PersonStatus(str, Enum):
    """Person account status"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class EntityType(str, Enum):
    """Business entity type for CRM clients"""
    INDIVIDUAL = "individual"
    SOLE_TRADER = "sole_trader"
    COMPANY = "company"
    TRUST = "trust"
    PARTNERSHIP = "partnership"
    SMSF = "smsf"


class PersonDB(Base):
    """
    Person - Central Identity Table
    
    The single source of truth for user identity.
    Email is unique and serves as the primary identifier.
    """
    __tablename__ = "person"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    mobile = Column(String(50))
    phone = Column(String(50))
    date_of_birth = Column(Date)
    status = Column(String(30), default=PersonStatus.ACTIVE.value)
    email_verified = Column(Boolean, default=False)
    mobile_verified = Column(Boolean, default=False)
    extra_data = Column("metadata", JSONB, default=dict)  # Maps to 'metadata' column (SQLAlchemy reserved word)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    myfdc_account = relationship("MyFDCAccountDB", back_populates="person", uselist=False)
    crm_client = relationship("CRMClientIdentityDB", back_populates="person", uselist=False)
    engagement_profile = relationship("EngagementProfileDB", back_populates="person", uselist=False)
    
    @property
    def full_name(self) -> str:
        """Get full name."""
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p) or self.email
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "mobile": self.mobile,
            "phone": self.phone,
            "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None,
            "status": self.status,
            "email_verified": self.email_verified,
            "mobile_verified": self.mobile_verified,
            "extra_data": self.extra_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "has_myfdc_account": self.myfdc_account is not None,
            "has_crm_client": self.crm_client is not None
        }


class MyFDCAccountDB(Base):
    """
    MyFDC Account - User account for MyFDC platform
    
    Links to person for MyFDC-specific data like settings and preferences.
    """
    __tablename__ = "myfdc_account"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id = Column(UUID(as_uuid=True), ForeignKey("person.id", ondelete="CASCADE"), nullable=False, unique=True)
    username = Column(String(100))
    password_hash = Column(String(255))
    auth_provider = Column(String(50), default="local")
    auth_provider_id = Column(String(255))
    last_login_at = Column(DateTime(timezone=True))
    login_count = Column(Integer, default=0)
    settings = Column(JSONB, default=dict)
    preferences = Column(JSONB, default=dict)
    onboarding_completed = Column(Boolean, default=False)
    onboarding_step = Column(Integer, default=0)
    status = Column(String(30), default="active")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationship
    person = relationship("PersonDB", back_populates="myfdc_account")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "person_id": str(self.person_id),
            "username": self.username,
            "auth_provider": self.auth_provider,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "login_count": self.login_count,
            "settings": self.settings,
            "preferences": self.preferences,
            "onboarding_completed": self.onboarding_completed,
            "onboarding_step": self.onboarding_step,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class CRMClientIdentityDB(Base):
    """
    CRM Client Identity - Client record for tax/accounting
    
    Links to person for CRM-specific data like ABN, TFN, business details.
    """
    __tablename__ = "crm_client_identity"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id = Column(UUID(as_uuid=True), ForeignKey("person.id", ondelete="CASCADE"), nullable=False, unique=True)
    client_code = Column(String(50), unique=True)
    abn = Column(String(20))
    tfn_encrypted = Column(String(255))
    business_name = Column(String(255))
    entity_type = Column(String(50))
    gst_registered = Column(Boolean, default=False)
    gst_registration_date = Column(Date)
    tax_agent_id = Column(String(50))
    assigned_staff_id = Column(UUID(as_uuid=True))
    source = Column(String(50))
    notes = Column(Text)
    tags = Column(JSONB, default=list)
    custom_fields = Column(JSONB, default=dict)
    status = Column(String(30), default="active")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationship
    person = relationship("PersonDB", back_populates="crm_client")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "person_id": str(self.person_id),
            "client_code": self.client_code,
            "abn": self.abn,
            "business_name": self.business_name,
            "entity_type": self.entity_type,
            "gst_registered": self.gst_registered,
            "gst_registration_date": self.gst_registration_date.isoformat() if self.gst_registration_date else None,
            "tax_agent_id": self.tax_agent_id,
            "assigned_staff_id": str(self.assigned_staff_id) if self.assigned_staff_id else None,
            "source": self.source,
            "notes": self.notes,
            "tags": self.tags,
            "custom_fields": self.custom_fields,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class EngagementProfileDB(Base):
    """
    Engagement Profile - Service engagement flags
    
    Tracks what services each person is using across MyFDC and CRM.
    """
    __tablename__ = "engagement_profile"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id = Column(UUID(as_uuid=True), ForeignKey("person.id", ondelete="CASCADE"), nullable=False, unique=True)
    
    # Account flags
    is_myfdc_user = Column(Boolean, default=False)
    is_crm_client = Column(Boolean, default=False)
    
    # Self-service flags
    has_ocr = Column(Boolean, default=False)
    is_diy_bas_user = Column(Boolean, default=False)
    is_diy_itr_user = Column(Boolean, default=False)
    
    # Full-service flags
    is_full_service_bas_client = Column(Boolean, default=False)
    is_full_service_itr_client = Column(Boolean, default=False)
    is_bookkeeping_client = Column(Boolean, default=False)
    is_payroll_client = Column(Boolean, default=False)
    
    # Subscription info
    subscription_tier = Column(String(50))
    subscription_start_date = Column(Date)
    subscription_end_date = Column(Date)
    
    # Engagement metrics
    first_engagement_at = Column(DateTime(timezone=True))
    last_engagement_at = Column(DateTime(timezone=True))
    total_interactions = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationship
    person = relationship("PersonDB", back_populates="engagement_profile")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "person_id": str(self.person_id),
            "is_myfdc_user": self.is_myfdc_user,
            "is_crm_client": self.is_crm_client,
            "has_ocr": self.has_ocr,
            "is_diy_bas_user": self.is_diy_bas_user,
            "is_diy_itr_user": self.is_diy_itr_user,
            "is_full_service_bas_client": self.is_full_service_bas_client,
            "is_full_service_itr_client": self.is_full_service_itr_client,
            "is_bookkeeping_client": self.is_bookkeeping_client,
            "is_payroll_client": self.is_payroll_client,
            "subscription_tier": self.subscription_tier,
            "subscription_start_date": self.subscription_start_date.isoformat() if self.subscription_start_date else None,
            "subscription_end_date": self.subscription_end_date.isoformat() if self.subscription_end_date else None,
            "first_engagement_at": self.first_engagement_at.isoformat() if self.first_engagement_at else None,
            "last_engagement_at": self.last_engagement_at.isoformat() if self.last_engagement_at else None,
            "total_interactions": self.total_interactions,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class IdentityLinkLogDB(Base):
    """
    Identity Link Log - Audit trail for identity operations
    
    Records all identity linking, merging, and unlinking operations.
    """
    __tablename__ = "identity_link_log"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id = Column(UUID(as_uuid=True), ForeignKey("person.id"))
    action = Column(String(50), nullable=False)  # create, link, merge, unlink, update
    source_type = Column(String(50))  # myfdc, crm, admin, migration
    source_id = Column(String(100))
    target_type = Column(String(50))
    target_id = Column(String(100))
    performed_by = Column(String(100))
    details = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "person_id": str(self.person_id) if self.person_id else None,
            "action": self.action,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "performed_by": self.performed_by,
            "details": self.details,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
