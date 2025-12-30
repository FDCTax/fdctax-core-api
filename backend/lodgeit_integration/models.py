"""
LodgeIT Integration - Database Models

Defines SQLAlchemy models for:
- Export queue (tracks clients pending export)
- Audit log (tracks all LodgeIT operations)
"""

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey,
    Boolean, JSON, Enum as SQLEnum, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime, timezone
from enum import Enum as PyEnum
from database.connection import Base


# ==================== ENUMS ====================

class ExportQueueStatus(str, PyEnum):
    """Status values for export queue entries"""
    PENDING = "pending"
    EXPORTED = "exported"
    FAILED = "failed"


class LodgeITAction(str, PyEnum):
    """Action types for audit logging"""
    EXPORT = "export"
    IMPORT = "import"
    ITR_EXPORT = "itr_export"
    QUEUE_ADD = "queue_add"
    QUEUE_REMOVE = "queue_remove"


# ==================== EXPORT QUEUE TABLE ====================

class LodgeITExportQueueDB(Base):
    """
    Export Queue Table - Tracks clients pending export to LodgeIT.
    
    Entries are created by:
    - Automatic triggers (onboarding complete, address change)
    - Manual addition via API
    """
    __tablename__ = 'lodgeit_export_queue'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    status = Column(
        SQLEnum(
            ExportQueueStatus,
            name='lodgeit_export_status_enum',
            create_type=True,
            values_callable=lambda obj: [e.value for e in obj]
        ),
        nullable=False,
        default=ExportQueueStatus.PENDING
    )
    trigger_reason = Column(String(100), nullable=True)  # onboarding, address_change, manual
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_exported_at = Column(DateTime(timezone=True), nullable=True)
    
    # Indexes
    __table_args__ = (
        Index('idx_lodgeit_queue_status', 'status'),
        Index('idx_lodgeit_queue_client_status', 'client_id', 'status'),
    )
    
    def to_dict(self):
        return {
            "id": self.id,
            "client_id": self.client_id,
            "status": self.status.value if self.status else None,
            "trigger_reason": self.trigger_reason,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_exported_at": self.last_exported_at.isoformat() if self.last_exported_at else None,
        }


# ==================== AUDIT LOG TABLE ====================

class LodgeITAuditLogDB(Base):
    """
    Audit Log Table - Tracks all LodgeIT operations for compliance.
    """
    __tablename__ = 'lodgeit_audit_log'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False, index=True)
    user_email = Column(String(255), nullable=True)
    action = Column(
        SQLEnum(
            LodgeITAction,
            name='lodgeit_action_enum',
            create_type=True,
            values_callable=lambda obj: [e.value for e in obj]
        ),
        nullable=False
    )
    client_ids = Column(JSON, nullable=True)  # List of affected client IDs
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text, nullable=True)
    details = Column(JSON, nullable=True)  # Additional context
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    # Indexes
    __table_args__ = (
        Index('idx_lodgeit_audit_user', 'user_id'),
        Index('idx_lodgeit_audit_action', 'action'),
        Index('idx_lodgeit_audit_timestamp', 'timestamp'),
    )
    
    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_email": self.user_email,
            "action": self.action.value if self.action else None,
            "client_ids": self.client_ids,
            "success": self.success,
            "error_message": self.error_message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
