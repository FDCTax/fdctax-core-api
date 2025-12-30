"""
Bookkeeping Ingestion - Database Models

Defines SQLAlchemy models for:
- ImportBatch: Tracks file imports
- ImportAuditLog: Audit trail for import operations
"""

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Text, Integer, DateTime, JSON, ForeignKey
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from database.connection import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ==================== ENUMS ====================

class ImportBatchStatus(str, PyEnum):
    """Status values for import batches"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ImportFileType(str, PyEnum):
    """Supported file types"""
    CSV = "csv"
    XLSX = "xlsx"
    XLS = "xls"


# ==================== IMPORT BATCH TABLE ====================

class ImportBatchDB(Base):
    """
    Import Batch Table - Tracks all file imports.
    
    Enables:
    - Import history
    - Undo/rollback
    - Duplicate detection
    - Batch-level reporting
    """
    __tablename__ = 'import_batches'
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(36), nullable=False, index=True)
    job_id = Column(String(36), nullable=True, index=True)
    
    # File info
    file_name = Column(String(500), nullable=False)
    file_type = Column(String(20), nullable=False)  # csv, xlsx, xls
    file_path = Column(Text, nullable=True)
    
    # Upload info
    uploaded_by = Column(String(36), nullable=False, index=True)
    uploaded_by_email = Column(String(255), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), default=utc_now)
    
    # Import stats
    row_count = Column(Integer, default=0)
    imported_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    
    # Status
    status = Column(String(20), nullable=False, default='pending', index=True)
    notes = Column(Text, nullable=True)
    
    # Column mapping used for import
    column_mapping = Column(JSON, nullable=True)
    
    # Errors (JSON array of error objects)
    errors = Column(JSON, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    
    # Table args
    __table_args__ = {'extend_existing': True}
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "client_id": self.client_id,
            "job_id": self.job_id,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "file_path": self.file_path,
            "uploaded_by": self.uploaded_by,
            "uploaded_by_email": self.uploaded_by_email,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
            "row_count": self.row_count,
            "imported_count": self.imported_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "status": self.status,
            "notes": self.notes,
            "column_mapping": self.column_mapping,
            "errors": self.errors,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ==================== IMPORT AUDIT LOG TABLE ====================

class ImportAuditLogDB(Base):
    """
    Import Audit Log - Tracks all import operations.
    """
    __tablename__ = 'import_audit_log'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(PGUUID(as_uuid=True), ForeignKey('import_batches.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(String(36), nullable=False)
    user_email = Column(String(255), nullable=True)
    action = Column(String(50), nullable=False)  # upload, parse, import, rollback
    details = Column(JSON, nullable=True)
    timestamp = Column(DateTime(timezone=True), default=utc_now, index=True)
    
    __table_args__ = {'extend_existing': True}
    
    def to_dict(self):
        return {
            "id": self.id,
            "batch_id": str(self.batch_id),
            "user_id": self.user_id,
            "user_email": self.user_email,
            "action": self.action,
            "details": self.details,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
