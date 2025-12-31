"""
BAS Backend - Database Models

Models for:
- BASStatement: BAS snapshots at completion
- BASChangeLog: Audit trail for BAS actions
- BASWorkflowStep: Multi-step sign-off workflow tracking
"""

import uuid
from datetime import datetime, timezone, date
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Optional, Dict, Any

from sqlalchemy import (
    Column, String, Text, Date, DateTime, Numeric, Integer, JSON, ForeignKey, Boolean
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from database.connection import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ==================== ENUMS ====================

class BASStatus(str, PyEnum):
    """Status values for BAS statements"""
    DRAFT = "draft"
    PREPARED = "prepared"      # Bookkeeper has prepared
    REVIEWED = "reviewed"      # Tax agent has reviewed
    APPROVED = "approved"      # Client has approved
    COMPLETED = "completed"    # Legacy - keep for backwards compat
    AMENDED = "amended"
    LODGED = "lodged"


class BASActionType(str, PyEnum):
    """Action types for change log"""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    CATEGORIZE = "categorize"
    ADJUST = "adjust"
    SIGN_OFF = "sign_off"
    PREPARE = "prepare"        # New: Bookkeeper prepares
    REVIEW = "review"          # New: Tax agent reviews
    APPROVE = "approve"        # New: Client approves
    LODGE = "lodge"            # New: Lodged with ATO
    AMEND = "amend"
    EXPORT = "export"
    GENERATE_PDF = "generate_pdf"
    REJECT = "reject"          # New: Step rejected
    REASSIGN = "reassign"      # New: Step reassigned


class BASEntityType(str, PyEnum):
    """Entity types for change log"""
    TRANSACTION = "transaction"
    CATEGORY = "category"
    BAS_SUMMARY = "bas_summary"
    GST_CODE = "gst_code"
    PAYG = "payg"
    NOTE = "note"
    PDF = "pdf"
    WORKFLOW = "workflow"      # New: Workflow step


class WorkflowStepType(str, PyEnum):
    """Workflow step types"""
    PREPARE = "prepare"
    REVIEW = "review"
    APPROVE = "approve"
    LODGE = "lodge"


class WorkflowStepStatus(str, PyEnum):
    """Workflow step status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"
    SKIPPED = "skipped"


# ==================== BAS STATEMENT TABLE ====================

class BASStatementDB(Base):
    """
    BAS Statement Table - Stores BAS snapshots at completion.
    
    Enables:
    - BAS history
    - Versioning
    - PDF storage
    - Sign-off tracking
    """
    __tablename__ = 'bas_statements'
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(36), nullable=False, index=True)
    job_id = Column(String(36), nullable=True, index=True)
    
    # Period
    period_from = Column(Date, nullable=False)
    period_to = Column(Date, nullable=False)
    
    # GST Summary Fields (ATO BAS fields)
    g1_total_income = Column(Numeric(14, 2), default=0)
    gst_on_income_1a = Column(Numeric(14, 2), default=0)
    gst_on_expenses_1b = Column(Numeric(14, 2), default=0)
    net_gst = Column(Numeric(14, 2), default=0)
    
    # Additional GST fields
    g2_export_sales = Column(Numeric(14, 2), default=0)
    g3_gst_free_sales = Column(Numeric(14, 2), default=0)
    g10_capital_purchases = Column(Numeric(14, 2), default=0)
    g11_non_capital_purchases = Column(Numeric(14, 2), default=0)
    
    # PAYG
    payg_instalment = Column(Numeric(14, 2), default=0)
    
    # Totals
    total_payable = Column(Numeric(14, 2), default=0)
    
    # Notes
    notes = Column(Text, nullable=True)
    review_notes = Column(Text, nullable=True)
    
    # Sign-off fields
    completed_by = Column(String(36), nullable=True)
    completed_by_email = Column(String(255), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Versioning
    version = Column(Integer, nullable=False, default=1)
    
    # PDF storage
    pdf_url = Column(Text, nullable=True)
    pdf_generated_at = Column(DateTime(timezone=True), nullable=True)
    
    # Status
    status = Column(String(20), nullable=False, default='draft')
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    
    __table_args__ = {'extend_existing': True}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "client_id": self.client_id,
            "job_id": self.job_id,
            "period_from": self.period_from.isoformat() if self.period_from else None,
            "period_to": self.period_to.isoformat() if self.period_to else None,
            "g1_total_income": float(self.g1_total_income) if self.g1_total_income else 0,
            "gst_on_income_1a": float(self.gst_on_income_1a) if self.gst_on_income_1a else 0,
            "gst_on_expenses_1b": float(self.gst_on_expenses_1b) if self.gst_on_expenses_1b else 0,
            "net_gst": float(self.net_gst) if self.net_gst else 0,
            "g2_export_sales": float(self.g2_export_sales) if self.g2_export_sales else 0,
            "g3_gst_free_sales": float(self.g3_gst_free_sales) if self.g3_gst_free_sales else 0,
            "g10_capital_purchases": float(self.g10_capital_purchases) if self.g10_capital_purchases else 0,
            "g11_non_capital_purchases": float(self.g11_non_capital_purchases) if self.g11_non_capital_purchases else 0,
            "payg_instalment": float(self.payg_instalment) if self.payg_instalment else 0,
            "total_payable": float(self.total_payable) if self.total_payable else 0,
            "notes": self.notes,
            "review_notes": self.review_notes,
            "completed_by": self.completed_by,
            "completed_by_email": self.completed_by_email,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "version": self.version,
            "pdf_url": self.pdf_url,
            "pdf_generated_at": self.pdf_generated_at.isoformat() if self.pdf_generated_at else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ==================== BAS CHANGE LOG TABLE ====================

class BASChangeLogDB(Base):
    """
    BAS Change Log Table - Audit trail for BAS actions.
    
    Supports:
    - Full audit trail
    - Change Log UI
    - Compliance reporting
    """
    __tablename__ = 'bas_change_log'
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # References
    bas_statement_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)
    client_id = Column(String(36), nullable=False, index=True)
    job_id = Column(String(36), nullable=True)
    
    # User info
    user_id = Column(String(36), nullable=False, index=True)
    user_email = Column(String(255), nullable=True)
    user_role = Column(String(50), nullable=True)
    
    # Action details
    action_type = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(36), nullable=True)
    
    # Change data
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    
    # Reason/notes
    reason = Column(Text, nullable=True)
    
    # Timestamp
    timestamp = Column(DateTime(timezone=True), default=utc_now, index=True)
    
    __table_args__ = {'extend_existing': True}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "bas_statement_id": str(self.bas_statement_id) if self.bas_statement_id else None,
            "client_id": self.client_id,
            "job_id": self.job_id,
            "user_id": self.user_id,
            "user_email": self.user_email,
            "user_role": self.user_role,
            "action_type": self.action_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
