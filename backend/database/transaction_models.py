"""
FDC Core - Unified Transaction Engine Database Models

This is the canonical transaction ledger for the entire FDC system.
Supports: Bookkeeper Tab, MyFDC ingestion, Workpaper routing, Audit trail, Locking/versioning.

Tables:
- transactions: Main transaction ledger
- transaction_history: Immutable audit trail
- transaction_attachments: Receipt metadata
- transaction_workpaper_links: Transaction-workpaper snapshots
"""

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Text, Float, Boolean, Date, DateTime,
    ForeignKey, Index, Enum as SQLEnum, JSON, Numeric
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from database.connection import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ==================== ENUMS (FROZEN) ====================

class TransactionStatus(str, PyEnum):
    """Transaction status in bookkeeper workflow"""
    NEW = "NEW"
    PENDING = "PENDING"
    REVIEWED = "REVIEWED"
    READY_FOR_WORKPAPER = "READY_FOR_WORKPAPER"
    EXCLUDED = "EXCLUDED"
    LOCKED = "LOCKED"


class GSTCode(str, PyEnum):
    """Australian GST codes"""
    GST = "GST"                    # Standard GST (10%)
    GST_FREE = "GST_FREE"          # GST-free supply
    INPUT_TAXED = "INPUT_TAXED"    # Input taxed (no GST credit)
    OUT_OF_SCOPE = "OUT_OF_SCOPE"  # Outside GST system
    PRIVATE = "PRIVATE"            # Private/non-business


class TransactionSource(str, PyEnum):
    """Source of transaction data"""
    BANK = "BANK"      # Bank feed import
    MYFDC = "MYFDC"    # MyFDC client app
    OCR = "OCR"        # OCR/receipt scan
    MANUAL = "MANUAL"  # Manual entry


class ModuleRouting(str, PyEnum):
    """Target module for transaction"""
    MOTOR_VEHICLE = "MOTOR_VEHICLE"
    HOME_OCCUPANCY = "HOME_OCCUPANCY"
    UTILITIES = "UTILITIES"
    INTERNET = "INTERNET"
    GENERAL = "GENERAL"
    DISALLOWED = "DISALLOWED"


class HistoryActionType(str, PyEnum):
    """Types of history actions"""
    MANUAL = "manual"              # Manual edit by user
    BULK_RECODE = "bulk_recode"    # Bulk update operation
    IMPORT = "import"              # Import from external source
    MYFDC_CREATE = "myfdc_create"  # Created via MyFDC sync
    MYFDC_UPDATE = "myfdc_update"  # Updated via MyFDC sync
    WORKPAPER_OVERRIDE = "workpaper_override"  # Override from workpaper
    LOCK = "lock"                  # Locked for workpaper
    UNLOCK = "unlock"              # Admin unlock
    ATTACHMENT_ADD = "attachment_add"
    ATTACHMENT_REMOVE = "attachment_remove"


# Status hierarchy for comparison
STATUS_HIERARCHY = {
    TransactionStatus.NEW: 0,
    TransactionStatus.PENDING: 1,
    TransactionStatus.REVIEWED: 2,
    TransactionStatus.READY_FOR_WORKPAPER: 3,
    TransactionStatus.EXCLUDED: 4,
    TransactionStatus.LOCKED: 5,
}


# ==================== DATABASE MODELS ====================

class TransactionDB(Base):
    """
    Main transaction ledger.
    
    Contains:
    - Raw transaction data
    - Client-entered fields (from MyFDC)
    - Bookkeeper fields (for review)
    - Status and routing information
    """
    __tablename__ = "transactions"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    client_id = Column(String(36), nullable=False, index=True)
    
    # Core transaction data
    date = Column(Date, nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    payee_raw = Column(Text, nullable=True)
    description_raw = Column(Text, nullable=True)
    
    # Source tracking
    source = Column(
        SQLEnum(TransactionSource, name='transaction_source_enum', create_type=False),
        nullable=False,
        default=TransactionSource.MANUAL,
        index=True
    )
    
    # Client fields (from MyFDC)
    category_client = Column(Text, nullable=True)
    module_hint_client = Column(Text, nullable=True)
    notes_client = Column(Text, nullable=True)
    
    # Bookkeeper fields
    category_bookkeeper = Column(Text, nullable=True, index=True)
    gst_code_bookkeeper = Column(
        SQLEnum(GSTCode, name='gst_code_enum', create_type=False),
        nullable=True
    )
    notes_bookkeeper = Column(Text, nullable=True)
    
    # Status and workflow
    status_bookkeeper = Column(
        SQLEnum(TransactionStatus, name='transaction_status_enum', create_type=False),
        nullable=False,
        default=TransactionStatus.NEW,
        index=True
    )
    
    # Flags (stored as JSON: {"late": true, "duplicate": false, "high_risk": false})
    flags = Column(JSON, nullable=True, default=dict)
    
    # Module routing
    module_routing = Column(
        SQLEnum(ModuleRouting, name='module_routing_enum', create_type=False),
        nullable=True,
        index=True
    )
    
    # Duplicate/late flags (for quick filtering)
    is_duplicate = Column(Boolean, default=False, index=True)
    is_late_receipt = Column(Boolean, default=False, index=True)
    
    # Locking
    locked_at = Column(DateTime(timezone=True), nullable=True)
    locked_by_role = Column(String(50), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    
    # Relationships
    history = relationship("TransactionHistoryDB", back_populates="transaction", cascade="all, delete-orphan")
    attachments = relationship("TransactionAttachmentDB", back_populates="transaction", cascade="all, delete-orphan")
    workpaper_links = relationship("TransactionWorkpaperLinkDB", back_populates="transaction", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('ix_transactions_client_date', 'client_id', 'date'),
        Index('ix_transactions_client_status', 'client_id', 'status_bookkeeper'),
        Index('ix_transactions_client_category', 'client_id', 'category_bookkeeper'),
        Index('ix_transactions_date_range', 'date', 'client_id'),
    )


class TransactionHistoryDB(Base):
    """
    Immutable audit trail for all transaction changes.
    
    Every modification creates a new history entry with:
    - Who made the change (user_id, role)
    - What action was taken
    - Before/after state (JSON snapshots)
    - Optional comment (required for sensitive actions)
    """
    __tablename__ = "transaction_history"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    transaction_id = Column(String(36), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Who made the change
    user_id = Column(String(36), nullable=True)  # Null for system actions
    role = Column(String(50), nullable=False)  # client, bookkeeper, accountant, admin, system
    
    # What action
    action_type = Column(
        SQLEnum(HistoryActionType, name='history_action_type_enum', create_type=False),
        nullable=False
    )
    
    # State change
    before = Column(JSON, nullable=True)  # Null for create actions
    after = Column(JSON, nullable=True)   # Null for delete actions
    
    # Metadata
    timestamp = Column(DateTime(timezone=True), default=utc_now, index=True)
    comment = Column(Text, nullable=True)  # Required for unlock, workpaper_override
    
    # Relationship
    transaction = relationship("TransactionDB", back_populates="history")
    
    __table_args__ = (
        Index('ix_history_transaction_time', 'transaction_id', 'timestamp'),
        Index('ix_history_user', 'user_id', 'timestamp'),
    )


class TransactionAttachmentDB(Base):
    """
    Receipt/document attachments for transactions.
    
    storage_ref is an opaque reference (not filesystem path).
    Could be: S3 key, document ID, or other storage reference.
    """
    __tablename__ = "transaction_attachments"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    transaction_id = Column(String(36), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Storage reference (opaque - could be S3 key, document ID, etc.)
    storage_ref = Column(Text, nullable=False)
    
    # Metadata
    uploaded_by_role = Column(String(50), nullable=False)  # client, bookkeeper, admin
    uploaded_at = Column(DateTime(timezone=True), default=utc_now)
    
    # For duplicate detection
    checksum = Column(String(64), nullable=True, index=True)  # SHA-256
    
    # Optional metadata
    filename = Column(String(255), nullable=True)
    mime_type = Column(String(100), nullable=True)
    file_size = Column(Numeric, nullable=True)
    
    # Relationship
    transaction = relationship("TransactionDB", back_populates="attachments")


class TransactionWorkpaperLinkDB(Base):
    """
    Links transactions to workpapers with snapshot of state at time of lock.
    
    When a workpaper pulls transactions:
    1. Snapshot of bookkeeper fields is stored
    2. Transaction is locked
    3. This link records the relationship and frozen state
    """
    __tablename__ = "transaction_workpaper_links"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    transaction_id = Column(String(36), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Link to workpaper job
    workpaper_id = Column(String(36), ForeignKey("workpaper_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Module and period
    module = Column(
        SQLEnum(ModuleRouting, name='module_routing_enum', create_type=False),
        nullable=False
    )
    period = Column(String(20), nullable=False)  # e.g., "2024-25", "Q1-2025"
    
    # Snapshot of bookkeeper fields at time of lock
    snapshot = Column(JSON, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=utc_now)
    
    # Relationships
    transaction = relationship("TransactionDB", back_populates="workpaper_links")
    
    __table_args__ = (
        Index('ix_workpaper_links_workpaper', 'workpaper_id'),
        Index('ix_workpaper_links_module', 'workpaper_id', 'module'),
    )


# ==================== ENUM EXPORTS ====================

# Export all enums for use in other modules
__all__ = [
    'TransactionStatus',
    'GSTCode',
    'TransactionSource',
    'ModuleRouting',
    'HistoryActionType',
    'STATUS_HIERARCHY',
    'TransactionDB',
    'TransactionHistoryDB',
    'TransactionAttachmentDB',
    'TransactionWorkpaperLinkDB',
]
