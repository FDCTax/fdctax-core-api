"""
FDC Core Workpaper Platform - SQLAlchemy Database Models

Phase 1: Core entities - WorkpaperJob, ModuleInstance, Transaction, TransactionOverride
Phase 2: Behaviour entities - OverrideRecord, Query, QueryMessage, Task
Phase 3: Audit + Freeze - FreezeSnapshot, WorkpaperAuditLog
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy import (
    Column, String, Text, Float, Boolean, Integer, DateTime, 
    ForeignKey, Index, Enum as SQLEnum, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID

from database.connection import Base


# ==================== HELPER FUNCTIONS ====================

def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ==================== PHASE 1: CORE ENTITIES ====================

class WorkpaperJobDB(Base):
    """
    Represents one tax year per client.
    Status is derived from its modules (lowest/least-complete status).
    """
    __tablename__ = "workpaper_jobs"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    client_id = Column(String(36), nullable=False, index=True)
    year = Column(String(10), nullable=False)  # e.g., "2024-25"
    status = Column(String(50), default="not_started", index=True)
    frozen_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=utc_now)
    
    # Relationships
    modules = relationship("ModuleInstanceDB", back_populates="job", cascade="all, delete-orphan")
    transactions = relationship("TransactionDB", back_populates="job", cascade="all, delete-orphan")
    queries = relationship("QueryDB", back_populates="job", cascade="all, delete-orphan")
    tasks = relationship("TaskDB", back_populates="job", cascade="all, delete-orphan")
    snapshots = relationship("FreezeSnapshotDB", back_populates="job", cascade="all, delete-orphan")
    
    # Unique constraint: one job per client per year
    __table_args__ = (
        Index('ix_workpaper_jobs_client_year', 'client_id', 'year', unique=True),
    )


class ModuleInstanceDB(Base):
    """
    A module within a job (e.g., Vehicle 1, Internet, FDC Income).
    """
    __tablename__ = "workpaper_modules"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(String(36), ForeignKey("workpaper_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    module_type = Column(String(50), nullable=False, index=True)  # ModuleType enum value
    label = Column(String(200), nullable=False)  # e.g., "Vehicle 1", "Primary Internet"
    status = Column(String(50), default="not_started", index=True)
    
    # Module-specific configuration (method selections, etc.)
    config = Column(JSON, default=dict)
    
    # Key results (deduction, income, percentages, etc.)
    output_summary = Column(JSON, default=dict)
    
    # Calculation inputs (populated by engine)
    calculation_inputs = Column(JSON, default=dict)
    
    frozen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=utc_now)
    
    # Relationships
    job = relationship("WorkpaperJobDB", back_populates="modules")
    transactions = relationship("TransactionDB", back_populates="module")
    overrides = relationship("OverrideRecordDB", back_populates="module", cascade="all, delete-orphan")
    queries = relationship("QueryDB", back_populates="module")
    snapshots = relationship("FreezeSnapshotDB", back_populates="module")


class TransactionDB(Base):
    """
    Immutable client data (from MyFDC or manual).
    Original transactions are never mutated by admin.
    """
    __tablename__ = "workpaper_transactions"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    client_id = Column(String(36), nullable=False, index=True)
    job_id = Column(String(36), ForeignKey("workpaper_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    module_instance_id = Column(String(36), ForeignKey("workpaper_modules.id", ondelete="SET NULL"), nullable=True, index=True)
    
    source = Column(String(50), default="manual")  # myfdc, manual, import
    date = Column(String(20), nullable=False)  # ISO date string
    amount = Column(Float, nullable=False)
    gst_amount = Column(Float, nullable=True)  # Original GST as entered
    category = Column(String(100), default="uncategorized", index=True)
    description = Column(Text, nullable=True)
    
    # Supporting documentation
    receipt_url = Column(String(500), nullable=True)
    document_id = Column(String(36), nullable=True)
    
    # Additional metadata
    vendor = Column(String(200), nullable=True)
    reference = Column(String(200), nullable=True)
    extra_data = Column(JSON, default=dict)  # Renamed from 'metadata' (reserved in SQLAlchemy)
    
    created_at = Column(DateTime(timezone=True), default=utc_now)
    # Note: No updated_at - transactions are immutable
    
    # Relationships
    job = relationship("WorkpaperJobDB", back_populates="transactions")
    module = relationship("ModuleInstanceDB", back_populates="transactions")
    overrides = relationship("TransactionOverrideDB", back_populates="transaction", cascade="all, delete-orphan")
    queries = relationship("QueryDB", back_populates="transaction")
    
    __table_args__ = (
        Index('ix_transactions_client_category', 'client_id', 'category'),
        Index('ix_transactions_job_category', 'job_id', 'category'),
    )


class TransactionOverrideDB(Base):
    """
    Admin adjustments per transaction.
    Overrides can be job-specific.
    """
    __tablename__ = "workpaper_transaction_overrides"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    transaction_id = Column(String(36), ForeignKey("workpaper_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(String(36), ForeignKey("workpaper_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Overridden values (nullable - only set if overridden)
    overridden_category = Column(String(100), nullable=True)
    overridden_amount = Column(Float, nullable=True)
    overridden_gst_amount = Column(Float, nullable=True)
    overridden_business_pct = Column(Float, nullable=True)  # 0-100
    
    # Audit fields
    reason = Column(Text, nullable=False)  # Required for any override
    admin_user_id = Column(String(36), nullable=False)
    admin_email = Column(String(255), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=utc_now)
    
    # Relationships
    transaction = relationship("TransactionDB", back_populates="overrides")
    
    # Unique: one override per transaction per job
    __table_args__ = (
        Index('ix_tx_override_tx_job', 'transaction_id', 'job_id', unique=True),
    )


# ==================== PHASE 2: BEHAVIOUR ENTITIES ====================

class OverrideRecordDB(Base):
    """
    Module-level overrides for values not tied to a single transaction.
    E.g., internet %, logbook %, chosen method.
    """
    __tablename__ = "workpaper_override_records"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    module_instance_id = Column(String(36), ForeignKey("workpaper_modules.id", ondelete="CASCADE"), nullable=False, index=True)
    
    field_key = Column(String(100), nullable=False)  # e.g., "effective_pct", "method", "business_km"
    original_value = Column(JSON, nullable=True)  # JSON-serializable
    effective_value = Column(JSON, nullable=True)  # JSON-serializable
    
    reason = Column(Text, nullable=False)  # Required
    admin_user_id = Column(String(36), nullable=False)
    admin_email = Column(String(255), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now)
    
    # Relationships
    module = relationship("ModuleInstanceDB", back_populates="overrides")
    
    # Unique: one override per field per module
    __table_args__ = (
        Index('ix_override_module_field', 'module_instance_id', 'field_key', unique=True),
    )


class QueryDB(Base):
    """
    Structured question/interaction between admin and client.
    """
    __tablename__ = "workpaper_queries"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    client_id = Column(String(36), nullable=False, index=True)
    job_id = Column(String(36), ForeignKey("workpaper_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    module_instance_id = Column(String(36), ForeignKey("workpaper_modules.id", ondelete="SET NULL"), nullable=True, index=True)
    transaction_id = Column(String(36), ForeignKey("workpaper_transactions.id", ondelete="SET NULL"), nullable=True, index=True)
    
    status = Column(String(50), default="draft", index=True)
    title = Column(String(500), nullable=False)
    query_type = Column(String(50), default="text")
    
    # For structured requests
    request_config = Column(JSON, default=dict)
    
    # Response data (populated when client responds)
    response_data = Column(JSON, nullable=True)
    
    created_by_admin_id = Column(String(36), nullable=False)
    created_by_admin_email = Column(String(255), nullable=True)
    resolved_by_admin_id = Column(String(36), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=utc_now)
    
    # Relationships
    job = relationship("WorkpaperJobDB", back_populates="queries")
    module = relationship("ModuleInstanceDB", back_populates="queries")
    transaction = relationship("TransactionDB", back_populates="queries")
    messages = relationship("QueryMessageDB", back_populates="query", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('ix_queries_job_status', 'job_id', 'status'),
        Index('ix_queries_client_status', 'client_id', 'status'),
    )


class QueryMessageDB(Base):
    """
    Message within a query thread.
    """
    __tablename__ = "workpaper_query_messages"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    query_id = Column(String(36), ForeignKey("workpaper_queries.id", ondelete="CASCADE"), nullable=False, index=True)
    
    sender_type = Column(String(20), nullable=False)  # admin, client, system
    sender_id = Column(String(36), nullable=False)
    sender_email = Column(String(255), nullable=True)
    
    message_text = Column(Text, nullable=False)
    attachment_url = Column(String(500), nullable=True)
    attachment_name = Column(String(255), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now)
    
    # Relationships
    query = relationship("QueryDB", back_populates="messages")


class TaskDB(Base):
    """
    Client-facing abstract task (e.g., "You have queries").
    A single QUERIES task per job bundles all open queries.
    """
    __tablename__ = "workpaper_tasks"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    client_id = Column(String(36), nullable=False, index=True)
    job_id = Column(String(36), ForeignKey("workpaper_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    
    task_type = Column(String(50), default="queries")  # queries, document_request, review_required
    status = Column(String(50), default="open", index=True)
    
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    
    # Metadata for task-specific info
    task_data = Column(JSON, default=dict)  # Renamed from 'metadata' (reserved in SQLAlchemy)
    
    due_date = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=utc_now)
    
    # Relationships
    job = relationship("WorkpaperJobDB", back_populates="tasks")
    
    __table_args__ = (
        Index('ix_tasks_client_status', 'client_id', 'status'),
        Index('ix_tasks_job_type', 'job_id', 'task_type'),
    )


# ==================== PHASE 3: AUDIT + FREEZE ====================

class FreezeSnapshotDB(Base):
    """
    Store frozen state for audit.
    """
    __tablename__ = "workpaper_freeze_snapshots"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(String(36), ForeignKey("workpaper_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    module_instance_id = Column(String(36), ForeignKey("workpaper_modules.id", ondelete="SET NULL"), nullable=True, index=True)
    
    snapshot_type = Column(String(50), nullable=False)  # module, bas, itr, summary
    
    # Full calculation outputs, key inputs, overrides
    data = Column(JSON, default=dict)
    
    # Summary for quick reference
    summary = Column(JSON, default=dict)
    
    created_by_admin_id = Column(String(36), nullable=False)
    created_by_admin_email = Column(String(255), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now)
    
    # Relationships
    job = relationship("WorkpaperJobDB", back_populates="snapshots")
    module = relationship("ModuleInstanceDB", back_populates="snapshots")
    
    __table_args__ = (
        Index('ix_snapshots_job_type', 'job_id', 'snapshot_type'),
    )


class WorkpaperAuditLogDB(Base):
    """
    Workpaper-specific audit logging.
    Extends the existing audit system with workpaper-specific tracking.
    """
    __tablename__ = "workpaper_audit_logs"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    
    # Action details
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(50), nullable=False, index=True)
    resource_id = Column(String(36), nullable=True, index=True)
    
    # User who performed the action
    user_id = Column(String(36), nullable=True, index=True)
    user_email = Column(String(255), nullable=True)
    user_role = Column(String(50), nullable=True)
    
    # Context
    job_id = Column(String(36), nullable=True, index=True)
    module_id = Column(String(36), nullable=True)
    client_id = Column(String(36), nullable=True, index=True)
    
    # Additional details
    details = Column(JSON, default=dict)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Status
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)
    
    __table_args__ = (
        Index('ix_audit_job_action', 'job_id', 'action'),
        Index('ix_audit_user_time', 'user_id', 'created_at'),
        Index('ix_audit_resource', 'resource_type', 'resource_id'),
    )
