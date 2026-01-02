"""
Unified Ingestion Schema (Ticket A3-INGEST-01)

Defines the canonical model for all inbound MyFDC → Core ingestion events.
This schema is the single source of truth for:
- Ingestion
- Bookkeeping
- Reconciliation
- OCR enrichment
- Downstream audit trails

Design principles:
- Deterministic
- Audit-defensible
- Source-agnostic
- Extensible for future ingestion sources
"""

import uuid
from datetime import datetime, timezone, date
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict

from pydantic import BaseModel, Field, ConfigDict


# ==================== ENUMS ====================

class IngestionSource(str, Enum):
    """Identifies the ingestion origin."""
    MYFDC = "MYFDC"
    OCR = "OCR"
    BANK_FEED = "BANK_FEED"
    MANUAL = "MANUAL"


class TransactionType(str, Enum):
    """Normalised transaction type."""
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"
    TRANSFER = "TRANSFER"
    UNKNOWN = "UNKNOWN"


class IngestionStatus(str, Enum):
    """Current ingestion lifecycle state."""
    INGESTED = "INGESTED"           # Raw data received
    NORMALISED = "NORMALISED"       # Data mapped and validated
    READY_FOR_BOOKKEEPING = "READY_FOR_BOOKKEEPING"  # Ready for downstream
    ERROR = "ERROR"                 # Ingestion or normalisation failed


class OCRStatus(str, Enum):
    """OCR processing state for attachments."""
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


# ==================== ATTACHMENT MODEL ====================

class AttachmentRef(BaseModel):
    """
    Reference to an attached file (receipt, invoice, etc.)
    Supports OCR enrichment workflow.
    """
    model_config = ConfigDict(use_enum_values=True)
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Attachment ID in Core")
    file_name: str = Field(..., description="Original filename")
    file_type: str = Field(..., description="MIME type")
    file_size: int = Field(..., description="Size in bytes")
    storage_path: str = Field(..., description="Internal storage reference")
    ocr_status: OCRStatus = Field(default=OCRStatus.PENDING, description="OCR processing state")
    ocr_result: Optional[Dict[str, Any]] = Field(default=None, description="OCR extraction result")
    uploaded_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "storage_path": self.storage_path,
            "ocr_status": self.ocr_status,
            "ocr_result": self.ocr_result,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None
        }


# ==================== AUDIT TRAIL ====================

class AuditEntry(BaseModel):
    """Single audit trail entry for transformation tracking."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    action: str = Field(..., description="Action performed (e.g., 'ingested', 'normalised', 'category_mapped')")
    actor: str = Field(..., description="Service or user that performed the action")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional context")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "action": self.action,
            "actor": self.actor,
            "details": self.details
        }


# ==================== INGESTED TRANSACTION MODEL ====================

class IngestedTransaction(BaseModel):
    """
    Unified Transaction Model - The canonical ingestion schema.
    
    This model serves as the single source of truth for all inbound
    transactions from MyFDC, OCR, bank feeds, and manual entry.
    
    Designed for:
    - Full traceability (audit field)
    - ATO defensibility
    - Multi-source compatibility
    - Downstream consumption safety (status lifecycle)
    """
    model_config = ConfigDict(use_enum_values=True)
    
    # Primary Key
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Core-generated primary key")
    
    # Source Identification
    source: IngestionSource = Field(..., description="Identifies the ingestion origin")
    source_transaction_id: str = Field(..., description="ID provided by the source system (e.g., MyFDC UID)")
    client_id: str = Field(..., description="Core client ID this transaction belongs to")
    
    # Timestamps
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp Core received the payload")
    transaction_date: date = Field(..., description="The date the educator recorded the transaction")
    
    # Transaction Details
    transaction_type: TransactionType = Field(..., description="Normalised transaction type")
    amount: Decimal = Field(..., description="Signed amount (positive for income, negative for expense)", decimal_places=2)
    currency: str = Field(default="AUD", description="Currency code")
    
    # GST Details
    gst_included: bool = Field(..., description="Whether GST is included in the amount")
    gst_amount: Optional[Decimal] = Field(default=None, description="GST component if known", decimal_places=2)
    
    # Description & Notes
    description: Optional[str] = Field(default=None, description="Free-text description from source")
    notes: Optional[str] = Field(default=None, description="Additional notes from educator")
    
    # Category Mapping
    category_raw: Optional[str] = Field(default=None, description="Category as provided by source (MyFDC)")
    category_normalised: Optional[str] = Field(default=None, description="Category mapped by ingestion engine")
    category_code: Optional[str] = Field(default=None, description="Standardised category code for bookkeeping")
    
    # Business Use
    business_percentage: Optional[int] = Field(default=100, ge=0, le=100, description="Business use percentage (0-100)")
    
    # Vendor/Payee
    vendor: Optional[str] = Field(default=None, description="Vendor or payee name")
    receipt_number: Optional[str] = Field(default=None, description="Receipt or invoice number")
    
    # Attachments (OCR-ready)
    attachments: List[AttachmentRef] = Field(default_factory=list, description="Links to OCR receipts or uploaded files")
    
    # Lifecycle Status
    status: IngestionStatus = Field(default=IngestionStatus.INGESTED, description="Current ingestion lifecycle state")
    error_message: Optional[str] = Field(default=None, description="Populated if ingestion or normalisation fails")
    
    # Audit Trail
    audit: List[AuditEntry] = Field(default_factory=list, description="Full audit trail of transformations")
    
    # Metadata
    raw_payload: Optional[Dict[str, Any]] = Field(default=None, description="Original payload for debugging")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional source-specific metadata")
    
    # Bookkeeping Link (populated after processing)
    bookkeeping_transaction_id: Optional[str] = Field(default=None, description="Link to bookkeeping transaction once processed")
    
    def add_audit_entry(self, action: str, actor: str, details: Optional[Dict[str, Any]] = None):
        """Add an audit trail entry."""
        self.audit.append(AuditEntry(
            action=action,
            actor=actor,
            details=details
        ))
    
    def mark_normalised(self, actor: str = "ingestion_engine"):
        """Mark transaction as normalised."""
        self.status = IngestionStatus.NORMALISED
        self.add_audit_entry("normalised", actor)
    
    def mark_ready_for_bookkeeping(self, actor: str = "ingestion_engine"):
        """Mark transaction as ready for bookkeeping."""
        self.status = IngestionStatus.READY_FOR_BOOKKEEPING
        self.add_audit_entry("ready_for_bookkeeping", actor)
    
    def mark_error(self, error_message: str, actor: str = "ingestion_engine"):
        """Mark transaction as failed with error message."""
        self.status = IngestionStatus.ERROR
        self.error_message = error_message
        self.add_audit_entry("error", actor, {"error": error_message})
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "source": self.source,
            "source_transaction_id": self.source_transaction_id,
            "client_id": self.client_id,
            "ingested_at": self.ingested_at.isoformat() if self.ingested_at else None,
            "transaction_date": self.transaction_date.isoformat() if self.transaction_date else None,
            "transaction_type": self.transaction_type,
            "amount": str(self.amount),
            "currency": self.currency,
            "gst_included": self.gst_included,
            "gst_amount": str(self.gst_amount) if self.gst_amount else None,
            "description": self.description,
            "notes": self.notes,
            "category_raw": self.category_raw,
            "category_normalised": self.category_normalised,
            "category_code": self.category_code,
            "business_percentage": self.business_percentage,
            "vendor": self.vendor,
            "receipt_number": self.receipt_number,
            "attachments": [a.to_dict() for a in self.attachments],
            "status": self.status,
            "error_message": self.error_message,
            "audit": [a.to_dict() for a in self.audit],
            "raw_payload": self.raw_payload,
            "metadata": self.metadata,
            "bookkeeping_transaction_id": self.bookkeeping_transaction_id
        }


# ==================== REQUEST/RESPONSE MODELS ====================

class IngestTransactionRequest(BaseModel):
    """Request model for ingesting a single transaction."""
    model_config = ConfigDict(use_enum_values=True)
    
    source: IngestionSource = Field(..., description="Ingestion source")
    source_transaction_id: str = Field(..., description="Source system's transaction ID")
    client_id: str = Field(..., description="Core client ID")
    transaction_date: date = Field(..., description="Transaction date")
    transaction_type: TransactionType = Field(..., description="Transaction type")
    amount: Decimal = Field(..., description="Amount (signed)")
    gst_included: bool = Field(..., description="Whether GST is included")
    gst_amount: Optional[Decimal] = Field(default=None, description="GST amount if known")
    description: Optional[str] = Field(default=None, description="Description")
    notes: Optional[str] = Field(default=None, description="Notes")
    category_raw: Optional[str] = Field(default=None, description="Raw category from source")
    business_percentage: Optional[int] = Field(default=100, description="Business use %")
    vendor: Optional[str] = Field(default=None, description="Vendor name")
    receipt_number: Optional[str] = Field(default=None, description="Receipt number")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")


class IngestBatchRequest(BaseModel):
    """Request model for batch ingestion."""
    model_config = ConfigDict(use_enum_values=True)
    
    source: IngestionSource = Field(..., description="Ingestion source for all transactions")
    client_id: str = Field(..., description="Core client ID")
    transactions: List[IngestTransactionRequest] = Field(..., description="List of transactions to ingest")


class IngestTransactionResponse(BaseModel):
    """Response model for ingested transaction."""
    id: str
    source: str
    source_transaction_id: str
    status: str
    ingested_at: datetime
    
    
class IngestBatchResponse(BaseModel):
    """Response model for batch ingestion."""
    success: bool
    total_count: int
    ingested_count: int
    error_count: int
    transactions: List[IngestTransactionResponse]
    errors: Optional[List[Dict[str, Any]]] = None


# ==================== FACTORY FUNCTIONS ====================

def create_ingested_transaction(
    source: IngestionSource,
    source_transaction_id: str,
    client_id: str,
    transaction_date: date,
    transaction_type: TransactionType,
    amount: Decimal,
    gst_included: bool,
    actor: str = "ingestion_engine",
    **kwargs
) -> IngestedTransaction:
    """
    Factory function to create an IngestedTransaction with proper audit trail.
    """
    txn = IngestedTransaction(
        source=source,
        source_transaction_id=source_transaction_id,
        client_id=client_id,
        transaction_date=transaction_date,
        transaction_type=transaction_type,
        amount=amount,
        gst_included=gst_included,
        **kwargs
    )
    
    # Add initial audit entry
    txn.add_audit_entry(
        action="ingested",
        actor=actor,
        details={
            "source": source.value,
            "source_transaction_id": source_transaction_id
        }
    )
    
    return txn


def create_from_myfdc_expense(
    client_id: str,
    myfdc_expense_id: str,
    expense_date: date,
    amount: Decimal,
    category: Optional[str] = None,
    description: Optional[str] = None,
    gst_included: bool = True,
    business_percentage: int = 100,
    vendor: Optional[str] = None,
    receipt_number: Optional[str] = None,
    raw_payload: Optional[Dict[str, Any]] = None
) -> IngestedTransaction:
    """
    Create an IngestedTransaction from MyFDC expense data.
    """
    return create_ingested_transaction(
        source=IngestionSource.MYFDC,
        source_transaction_id=myfdc_expense_id,
        client_id=client_id,
        transaction_date=expense_date,
        transaction_type=TransactionType.EXPENSE,
        amount=-abs(amount),  # Expenses are negative
        gst_included=gst_included,
        category_raw=category,
        description=description,
        business_percentage=business_percentage,
        vendor=vendor,
        receipt_number=receipt_number,
        raw_payload=raw_payload,
        actor="myfdc_ingestion"
    )


def create_from_myfdc_income(
    client_id: str,
    myfdc_income_id: str,
    income_date: date,
    amount: Decimal,
    category: Optional[str] = None,
    description: Optional[str] = None,
    gst_included: bool = True,
    raw_payload: Optional[Dict[str, Any]] = None
) -> IngestedTransaction:
    """
    Create an IngestedTransaction from MyFDC income data.
    """
    return create_ingested_transaction(
        source=IngestionSource.MYFDC,
        source_transaction_id=myfdc_income_id,
        client_id=client_id,
        transaction_date=income_date,
        transaction_type=TransactionType.INCOME,
        amount=abs(amount),  # Income is positive
        gst_included=gst_included,
        category_raw=category,
        description=description,
        raw_payload=raw_payload,
        actor="myfdc_ingestion"
    )
