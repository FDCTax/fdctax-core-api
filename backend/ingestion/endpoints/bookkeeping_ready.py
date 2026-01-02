"""
Bookkeeping Ready Transactions API (A3-BOOK-01)

Exposes a deterministic, audit-defensible API for transactions that have
completed the ingestion lifecycle and are ready for bookkeeping.

Bookkeeping-Ready Criteria:
- status = READY_FOR_BOOKKEEPING
- category_normalised is populated
- category_code is populated
- amount is valid and signed
- audit.normalised exists

Endpoints:
- GET /api/bookkeeping/transactions/{client_id} - List bookkeeping-ready transactions
- GET /api/bookkeeping/transaction/{id} - Get single transaction with full audit
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from middleware.auth import get_current_user_required, AuthUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bookkeeping", tags=["Bookkeeping"])


# ==================== RESPONSE MODELS ====================

class AuditEntryResponse(BaseModel):
    """Single audit trail entry."""
    timestamp: str
    action: str
    actor: str
    details: Optional[Dict[str, Any]] = None


class AttachmentResponse(BaseModel):
    """Attachment reference in response."""
    id: str
    file_name: str
    file_type: str
    file_size: int
    storage_path: str
    ocr_status: str
    ocr_result: Optional[Dict[str, Any]] = None


class BookkeepingReadyTransaction(BaseModel):
    """
    Transaction ready for bookkeeping consumption.
    
    Contains all fields required by the bookkeeping engine
    with full audit trail for defensibility.
    """
    # Core identifiers
    id: str = Field(..., description="Core transaction ID")
    client_id: str = Field(..., description="Core client ID")
    source: str = Field(..., description="Ingestion source (MYFDC, OCR, etc.)")
    source_transaction_id: str = Field(..., description="Original source ID")
    
    # Transaction details
    transaction_date: str = Field(..., description="Transaction date (ISO format)")
    transaction_type: str = Field(..., description="INCOME, EXPENSE, TRANSFER")
    amount: str = Field(..., description="Signed amount as string (for precision)")
    currency: str = Field(default="AUD", description="Currency code")
    
    # GST
    gst_included: bool = Field(..., description="Whether GST is included")
    gst_amount: Optional[str] = Field(None, description="GST component if known")
    
    # Category (normalised by Agent 8)
    category_raw: Optional[str] = Field(None, description="Original category from source")
    category_normalised: str = Field(..., description="Normalised category name")
    category_code: str = Field(..., description="Standardised category code")
    
    # Business use
    business_percentage: int = Field(default=100, description="Business use percentage")
    
    # Vendor info
    description: Optional[str] = Field(None, description="Transaction description")
    vendor: Optional[str] = Field(None, description="Vendor name")
    receipt_number: Optional[str] = Field(None, description="Receipt/invoice number")
    
    # Attachments
    attachments: List[AttachmentResponse] = Field(default_factory=list, description="File attachments")
    
    # Audit trail (immutable)
    audit: List[AuditEntryResponse] = Field(..., description="Full audit trail")
    
    # Lifecycle
    status: str = Field(..., description="Current status (should be READY_FOR_BOOKKEEPING)")
    ingested_at: str = Field(..., description="When transaction was ingested")
    
    # Metadata
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class BookkeepingTransactionListResponse(BaseModel):
    """Response for listing bookkeeping-ready transactions."""
    success: bool = True
    client_id: str
    total_count: int = Field(..., description="Total matching transactions")
    page: int = Field(..., description="Current page (1-based)")
    page_size: int = Field(..., description="Items per page")
    has_more: bool = Field(..., description="Whether more pages exist")
    transactions: List[BookkeepingReadyTransaction]


class BookkeepingTransactionResponse(BaseModel):
    """Response for single transaction."""
    success: bool = True
    transaction: BookkeepingReadyTransaction


# ==================== SERVICE ====================

class BookkeepingReadyService:
    """
    Service for querying bookkeeping-ready transactions.
    
    Enforces strict criteria:
    - Only READY_FOR_BOOKKEEPING status
    - Must have normalised category
    - Must have category code
    - Audit trail preserved
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_transactions(
        self,
        client_id: str,
        page: int = 1,
        page_size: int = 50,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        transaction_type: Optional[str] = None,
        category_code: Optional[str] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Get bookkeeping-ready transactions for a client.
        
        Args:
            client_id: Core client ID
            page: Page number (1-based)
            page_size: Items per page
            date_from: Filter by start date
            date_to: Filter by end date
            transaction_type: Filter by type (INCOME, EXPENSE, etc.)
            category_code: Filter by category code
            min_amount: Filter by minimum amount (absolute value)
            max_amount: Filter by maximum amount (absolute value)
            
        Returns:
            Tuple of (transactions, total_count)
        """
        # Build WHERE conditions
        conditions = [
            "client_id = :client_id",
            "status = 'READY_FOR_BOOKKEEPING'",
            "category_normalised IS NOT NULL",
            "category_code IS NOT NULL"
        ]
        params = {"client_id": client_id}
        
        if date_from:
            conditions.append("transaction_date >= :date_from")
            params["date_from"] = date_from
        
        if date_to:
            conditions.append("transaction_date <= :date_to")
            params["date_to"] = date_to
        
        if transaction_type:
            conditions.append("transaction_type = :transaction_type")
            params["transaction_type"] = transaction_type.upper()
        
        if category_code:
            conditions.append("category_code = :category_code")
            params["category_code"] = category_code
        
        if min_amount is not None:
            conditions.append("ABS(amount) >= :min_amount")
            params["min_amount"] = min_amount
        
        if max_amount is not None:
            conditions.append("ABS(amount) <= :max_amount")
            params["max_amount"] = max_amount
        
        where_clause = " AND ".join(conditions)
        
        # Get total count
        count_query = text(f"""
            SELECT COUNT(*) 
            FROM public.ingested_transactions
            WHERE {where_clause}
        """)
        count_result = await self.db.execute(count_query, params)
        total_count = count_result.scalar() or 0
        
        # Get paginated results
        offset = (page - 1) * page_size
        params["limit"] = page_size
        params["offset"] = offset
        
        data_query = text(f"""
            SELECT 
                id, client_id, source, source_transaction_id,
                transaction_date, transaction_type, amount, currency,
                gst_included, gst_amount,
                category_raw, category_normalised, category_code,
                business_percentage, description, vendor, receipt_number,
                attachments, audit, status, ingested_at, metadata
            FROM public.ingested_transactions
            WHERE {where_clause}
            ORDER BY transaction_date DESC, ingested_at DESC
            LIMIT :limit OFFSET :offset
        """)
        
        result = await self.db.execute(data_query, params)
        rows = result.fetchall()
        
        transactions = []
        for row in rows:
            transactions.append(self._row_to_dict(row))
        
        return transactions, total_count
    
    async def get_transaction_by_id(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single bookkeeping-ready transaction by ID.
        
        Only returns if status is READY_FOR_BOOKKEEPING.
        """
        query = text("""
            SELECT 
                id, client_id, source, source_transaction_id,
                transaction_date, transaction_type, amount, currency,
                gst_included, gst_amount,
                category_raw, category_normalised, category_code,
                business_percentage, description, vendor, receipt_number,
                attachments, audit, status, ingested_at, metadata
            FROM public.ingested_transactions
            WHERE id = :id
            AND status = 'READY_FOR_BOOKKEEPING'
            AND category_normalised IS NOT NULL
            AND category_code IS NOT NULL
        """)
        
        result = await self.db.execute(query, {"id": transaction_id})
        row = result.fetchone()
        
        if not row:
            return None
        
        return self._row_to_dict(row)
    
    async def get_summary_by_category(
        self,
        client_id: str,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Get summary of bookkeeping-ready transactions by category.
        
        Useful for bookkeeping dashboard/overview.
        """
        conditions = [
            "client_id = :client_id",
            "status = 'READY_FOR_BOOKKEEPING'",
            "category_code IS NOT NULL"
        ]
        params = {"client_id": client_id}
        
        if date_from:
            conditions.append("transaction_date >= :date_from")
            params["date_from"] = date_from
        
        if date_to:
            conditions.append("transaction_date <= :date_to")
            params["date_to"] = date_to
        
        where_clause = " AND ".join(conditions)
        
        query = text(f"""
            SELECT 
                category_code,
                category_normalised,
                transaction_type,
                COUNT(*) as transaction_count,
                SUM(amount) as total_amount,
                SUM(COALESCE(gst_amount, 0)) as total_gst
            FROM public.ingested_transactions
            WHERE {where_clause}
            GROUP BY category_code, category_normalised, transaction_type
            ORDER BY category_code, transaction_type
        """)
        
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        summary = []
        for row in rows:
            summary.append({
                "category_code": row[0],
                "category_normalised": row[1],
                "transaction_type": row[2],
                "transaction_count": row[3],
                "total_amount": str(row[4]) if row[4] else "0",
                "total_gst": str(row[5]) if row[5] else "0"
            })
        
        return summary
    
    def _row_to_dict(self, row) -> Dict[str, Any]:
        """Convert database row to dictionary."""
        import json
        
        # Parse JSON fields
        attachments = row[17]
        if isinstance(attachments, str):
            attachments = json.loads(attachments)
        elif attachments is None:
            attachments = []
        
        audit = row[18]
        if isinstance(audit, str):
            audit = json.loads(audit)
        elif audit is None:
            audit = []
        
        metadata = row[21]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        
        return {
            "id": str(row[0]),
            "client_id": str(row[1]),
            "source": row[2],
            "source_transaction_id": row[3],
            "transaction_date": row[4].isoformat() if row[4] else None,
            "transaction_type": row[5],
            "amount": str(row[6]) if row[6] else "0",
            "currency": row[7] or "AUD",
            "gst_included": row[8],
            "gst_amount": str(row[9]) if row[9] else None,
            "category_raw": row[10],
            "category_normalised": row[11],
            "category_code": row[12],
            "business_percentage": row[13] or 100,
            "description": row[14],
            "vendor": row[15],
            "receipt_number": row[16],
            "attachments": attachments,
            "audit": audit,
            "status": row[19],
            "ingested_at": row[20].isoformat() if row[20] else None,
            "metadata": metadata
        }


# ==================== ENDPOINTS ====================

@router.get("/transactions/{client_id}", response_model=BookkeepingTransactionListResponse)
async def get_bookkeeping_ready_transactions(
    client_id: str,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    date_from: Optional[date] = Query(None, description="Filter by start date (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="Filter by end date (YYYY-MM-DD)"),
    transaction_type: Optional[str] = Query(None, description="Filter by type: INCOME, EXPENSE, TRANSFER"),
    category_code: Optional[str] = Query(None, description="Filter by category code"),
    min_amount: Optional[float] = Query(None, description="Filter by minimum amount (absolute)"),
    max_amount: Optional[float] = Query(None, description="Filter by maximum amount (absolute)"),
    current_user: AuthUser = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all bookkeeping-ready transactions for a client.
    
    **Auth:** Standard Core JWT
    
    **Bookkeeping-Ready Criteria:**
    - status = READY_FOR_BOOKKEEPING
    - category_normalised is populated
    - category_code is populated
    - amount is valid and signed
    - audit.normalised exists
    
    **Filtering:**
    - Date range (date_from, date_to)
    - Transaction type (INCOME, EXPENSE, TRANSFER)
    - Category code
    - Amount range (min_amount, max_amount - absolute values)
    
    **Pagination:**
    - page: 1-based page number
    - page_size: 1-200 items per page
    
    **Note:** Transactions in ERROR or NORMALISED status will never appear.
    """
    service = BookkeepingReadyService(db)
    
    transactions, total_count = await service.get_transactions(
        client_id=client_id,
        page=page,
        page_size=page_size,
        date_from=date_from,
        date_to=date_to,
        transaction_type=transaction_type,
        category_code=category_code,
        min_amount=min_amount,
        max_amount=max_amount
    )
    
    has_more = (page * page_size) < total_count
    
    # Convert to response models
    txn_responses = []
    for txn in transactions:
        # Convert attachments
        attachments = []
        for att in txn.get("attachments", []):
            if isinstance(att, dict):
                attachments.append(AttachmentResponse(
                    id=att.get("id", ""),
                    file_name=att.get("file_name", ""),
                    file_type=att.get("file_type", ""),
                    file_size=att.get("file_size", 0),
                    storage_path=att.get("storage_path", ""),
                    ocr_status=att.get("ocr_status", "PENDING"),
                    ocr_result=att.get("ocr_result")
                ))
        
        # Convert audit entries
        audit_entries = []
        for entry in txn.get("audit", []):
            if isinstance(entry, dict):
                audit_entries.append(AuditEntryResponse(
                    timestamp=entry.get("timestamp", ""),
                    action=entry.get("action", ""),
                    actor=entry.get("actor", ""),
                    details=entry.get("details")
                ))
        
        txn_responses.append(BookkeepingReadyTransaction(
            id=txn["id"],
            client_id=txn["client_id"],
            source=txn["source"],
            source_transaction_id=txn["source_transaction_id"],
            transaction_date=txn["transaction_date"],
            transaction_type=txn["transaction_type"],
            amount=txn["amount"],
            currency=txn["currency"],
            gst_included=txn["gst_included"],
            gst_amount=txn["gst_amount"],
            category_raw=txn["category_raw"],
            category_normalised=txn["category_normalised"],
            category_code=txn["category_code"],
            business_percentage=txn["business_percentage"],
            description=txn["description"],
            vendor=txn["vendor"],
            receipt_number=txn["receipt_number"],
            attachments=attachments,
            audit=audit_entries,
            status=txn["status"],
            ingested_at=txn["ingested_at"],
            metadata=txn["metadata"]
        ))
    
    return BookkeepingTransactionListResponse(
        success=True,
        client_id=client_id,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_more=has_more,
        transactions=txn_responses
    )


@router.get("/transaction/{transaction_id}", response_model=BookkeepingTransactionResponse)
async def get_bookkeeping_transaction(
    transaction_id: str,
    current_user: AuthUser = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a single bookkeeping-ready transaction.
    
    **Auth:** Standard Core JWT
    
    **Returns:**
    - Full transaction details
    - Complete audit trail
    - All attachments
    
    **Note:** Returns 404 if transaction is not in READY_FOR_BOOKKEEPING status.
    """
    service = BookkeepingReadyService(db)
    
    transaction = await service.get_transaction_by_id(transaction_id)
    
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found or not ready for bookkeeping"
        )
    
    # Convert attachments
    attachments = []
    for att in transaction.get("attachments", []):
        if isinstance(att, dict):
            attachments.append(AttachmentResponse(
                id=att.get("id", ""),
                file_name=att.get("file_name", ""),
                file_type=att.get("file_type", ""),
                file_size=att.get("file_size", 0),
                storage_path=att.get("storage_path", ""),
                ocr_status=att.get("ocr_status", "PENDING"),
                ocr_result=att.get("ocr_result")
            ))
    
    # Convert audit entries
    audit_entries = []
    for entry in transaction.get("audit", []):
        if isinstance(entry, dict):
            audit_entries.append(AuditEntryResponse(
                timestamp=entry.get("timestamp", ""),
                action=entry.get("action", ""),
                actor=entry.get("actor", ""),
                details=entry.get("details")
            ))
    
    txn_response = BookkeepingReadyTransaction(
        id=transaction["id"],
        client_id=transaction["client_id"],
        source=transaction["source"],
        source_transaction_id=transaction["source_transaction_id"],
        transaction_date=transaction["transaction_date"],
        transaction_type=transaction["transaction_type"],
        amount=transaction["amount"],
        currency=transaction["currency"],
        gst_included=transaction["gst_included"],
        gst_amount=transaction["gst_amount"],
        category_raw=transaction["category_raw"],
        category_normalised=transaction["category_normalised"],
        category_code=transaction["category_code"],
        business_percentage=transaction["business_percentage"],
        description=transaction["description"],
        vendor=transaction["vendor"],
        receipt_number=transaction["receipt_number"],
        attachments=attachments,
        audit=audit_entries,
        status=transaction["status"],
        ingested_at=transaction["ingested_at"],
        metadata=transaction["metadata"]
    )
    
    return BookkeepingTransactionResponse(
        success=True,
        transaction=txn_response
    )


@router.get("/summary/{client_id}")
async def get_bookkeeping_summary(
    client_id: str,
    date_from: Optional[date] = Query(None, description="Filter by start date"),
    date_to: Optional[date] = Query(None, description="Filter by end date"),
    current_user: AuthUser = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """
    Get summary of bookkeeping-ready transactions by category.
    
    **Auth:** Standard Core JWT
    
    **Returns:**
    - Grouped totals by category_code and transaction_type
    - Transaction count, total amount, total GST per group
    
    Useful for bookkeeping dashboard and reporting.
    """
    service = BookkeepingReadyService(db)
    
    summary = await service.get_summary_by_category(
        client_id=client_id,
        date_from=date_from,
        date_to=date_to
    )
    
    return {
        "success": True,
        "client_id": client_id,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "summary": summary
    }
