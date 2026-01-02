"""
Bookkeeping Ingestion Module

Provides file upload, parsing, and transaction import functionality.
Also provides the Unified Ingestion Schema (A3-INGEST-01) for all inbound transactions.
"""

from .models import ImportBatchDB, ImportAuditLogDB, ImportBatchStatus, ImportFileType
from .service import (
    UploadService,
    ParseService,
    ImportService,
    RollbackService,
    BatchService
)
from .unified_schema import (
    # Enums
    IngestionSource,
    TransactionType,
    IngestionStatus,
    OCRStatus,
    # Models
    AttachmentRef,
    AuditEntry,
    IngestedTransaction,
    # Request/Response
    IngestTransactionRequest,
    IngestBatchRequest,
    IngestTransactionResponse,
    IngestBatchResponse,
    # Factory functions
    create_ingested_transaction,
    create_from_myfdc_expense,
    create_from_myfdc_income,
)

__all__ = [
    # Legacy models
    "ImportBatchDB",
    "ImportAuditLogDB",
    "ImportBatchStatus",
    "ImportFileType",
    # Legacy services
    "UploadService",
    "ParseService",
    "ImportService",
    "RollbackService",
    "BatchService",
    # Unified Schema (A3-INGEST-01)
    "IngestionSource",
    "TransactionType",
    "IngestionStatus",
    "OCRStatus",
    "AttachmentRef",
    "AuditEntry",
    "IngestedTransaction",
    "IngestTransactionRequest",
    "IngestBatchRequest",
    "IngestTransactionResponse",
    "IngestBatchResponse",
    "create_ingested_transaction",
    "create_from_myfdc_expense",
    "create_from_myfdc_income",
]
