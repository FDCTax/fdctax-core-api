"""
MyFDC Ingestion Endpoint (A3-INGEST-02)

Entry point for the MyFDC → Ingestion → Bookkeeping → Reconciliation pipeline.

Endpoint: POST /api/ingestion/myfdc
Auth: Standard Core JWT (educator or admin)
Response: 202 Accepted with batch ID
"""

import logging
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from middleware.auth import get_current_user, require_authenticated, AuthUser
from ingestion.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingestion", tags=["Ingestion"])


# ==================== REQUEST/RESPONSE MODELS ====================

class MyFDCTransactionPayload(BaseModel):
    """Single MyFDC transaction payload."""
    id: Optional[str] = Field(None, description="MyFDC transaction ID")
    myfdc_id: Optional[str] = Field(None, description="Alternative MyFDC ID field")
    transaction_id: Optional[str] = Field(None, description="Alternative transaction ID field")
    
    # Date fields (multiple accepted formats)
    transaction_date: Optional[str] = Field(None, description="Transaction date")
    date: Optional[str] = Field(None, description="Alternative date field")
    expense_date: Optional[str] = Field(None, description="Expense date")
    income_date: Optional[str] = Field(None, description="Income date")
    
    # Type and amount
    transaction_type: Optional[str] = Field(None, description="Transaction type: expense, income, transfer")
    type: Optional[str] = Field(None, description="Alternative type field")
    amount: Optional[float] = Field(None, description="Transaction amount")
    total: Optional[float] = Field(None, description="Alternative amount field")
    
    # GST
    gst_included: Optional[bool] = Field(True, description="Whether GST is included")
    gst_amount: Optional[float] = Field(None, description="GST amount")
    
    # Description and category
    description: Optional[str] = Field(None, description="Transaction description")
    notes: Optional[str] = Field(None, description="Notes")
    category: Optional[str] = Field(None, description="Category")
    expense_category: Optional[str] = Field(None, description="Expense category")
    
    # Business use
    business_percentage: Optional[int] = Field(100, description="Business use percentage")
    
    # Vendor info
    vendor: Optional[str] = Field(None, description="Vendor name")
    payee: Optional[str] = Field(None, description="Payee name")
    receipt_number: Optional[str] = Field(None, description="Receipt/invoice number")
    
    # Attachments
    attachments: Optional[List[Dict[str, Any]]] = Field(None, description="File attachments")
    
    # Allow extra fields
    class Config:
        extra = "allow"


class MyFDCIngestionRequest(BaseModel):
    """Request to ingest MyFDC transactions."""
    client_id: str = Field(..., description="Core client ID to ingest for")
    transactions: List[MyFDCTransactionPayload] = Field(..., description="List of transactions to ingest")
    
    class Config:
        json_schema_extra = {
            "example": {
                "client_id": "4e8dab2c-c306-4b7c-997a-11c81e65a95b",
                "transactions": [
                    {
                        "id": "MYFDC-EXP-001",
                        "transaction_date": "2025-01-02",
                        "transaction_type": "expense",
                        "amount": 150.00,
                        "gst_included": True,
                        "category": "Office Supplies",
                        "description": "Printer paper and ink",
                        "vendor": "Officeworks",
                        "receipt_number": "INV-12345",
                        "business_percentage": 100
                    }
                ]
            }
        }


class IngestionTransactionResult(BaseModel):
    """Result for a single ingested transaction."""
    id: str = Field(..., description="Core transaction ID")
    source: str = Field(..., description="Source system")
    source_transaction_id: str = Field(..., description="Source transaction ID")
    status: str = Field(..., description="Ingestion status")
    ingested_at: str = Field(..., description="Ingestion timestamp")


class IngestionErrorDetail(BaseModel):
    """Error detail for failed ingestion."""
    source_transaction_id: str = Field(..., description="Source transaction ID that failed")
    error: str = Field(..., description="Error message")


class MyFDCIngestionResponse(BaseModel):
    """Response from MyFDC ingestion."""
    success: bool = Field(..., description="Overall success")
    batch_id: str = Field(..., description="Ingestion batch ID")
    client_id: str = Field(..., description="Client ID")
    source: str = Field(..., description="Ingestion source")
    total_count: int = Field(..., description="Total transactions submitted")
    ingested_count: int = Field(..., description="Successfully ingested count")
    error_count: int = Field(..., description="Failed transaction count")
    transactions: List[IngestionTransactionResult] = Field(..., description="Individual results")
    errors: Optional[List[IngestionErrorDetail]] = Field(None, description="Error details")
    normalisation_queued: bool = Field(..., description="Whether normalisation was queued")


# ==================== ENDPOINTS ====================

@router.post("/myfdc", response_model=MyFDCIngestionResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_myfdc_transactions(
    request: MyFDCIngestionRequest,
    current_user: AuthUser = Depends(require_authenticated),
    db: AsyncSession = Depends(get_db)
):
    """
    Ingest transactions from MyFDC into Core.
    
    **Auth:** Standard Core JWT (educator, staff, or admin)
    
    **Processing Flow:**
    1. Validate incoming payloads
    2. Transform to unified IngestedTransaction schema
    3. Store in `ingested_transactions` table
    4. Queue normalisation task for Agent 8
    5. Return batch summary
    
    **Error Handling:**
    - Invalid items are stored with `status = ERROR`
    - Errors are returned per-item, not batch-level failures
    - All items are processed regardless of individual errors
    
    **Response:** 202 Accepted with ingestion batch details
    """
    logger.info(f"MyFDC ingestion request: {len(request.transactions)} transactions for client {request.client_id}")
    
    # Validate client access (user must have access to this client)
    # For now, staff/admin can ingest for any client
    # Educators can only ingest for their own linked client
    if current_user.role == "client":
        # Check if user is linked to this client
        # This would need client-user mapping check
        pass  # Allow for now, implement stricter checks later
    
    # Convert Pydantic models to dicts for transformer
    payloads = [txn.model_dump(exclude_none=False) for txn in request.transactions]
    
    # Perform ingestion
    service = IngestionService(db)
    
    try:
        result = await service.ingest_myfdc_batch(
            client_id=request.client_id,
            payloads=payloads,
            user_id=current_user.id,
            user_email=current_user.email
        )
        
        return MyFDCIngestionResponse(
            success=result.error_count == 0,
            batch_id=result.batch_id,
            client_id=result.client_id,
            source=result.source,
            total_count=result.total_count,
            ingested_count=result.ingested_count,
            error_count=result.error_count,
            transactions=[
                IngestionTransactionResult(
                    id=t.id,
                    source=t.source,
                    source_transaction_id=t.source_transaction_id,
                    status=t.status,
                    ingested_at=t.ingested_at.isoformat()
                )
                for t in result.transactions
            ],
            errors=[
                IngestionErrorDetail(
                    source_transaction_id=e["source_transaction_id"],
                    error=e["error"]
                )
                for e in result.errors
            ] if result.errors else None,
            normalisation_queued=result.ingested_count > 0
        )
        
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {str(e)}"
        )


@router.get("/myfdc/{client_id}")
async def get_ingested_transactions(
    client_id: str,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: AuthUser = Depends(require_authenticated),
    db: AsyncSession = Depends(get_db)
):
    """
    Get ingested transactions for a client.
    
    **Auth:** Standard Core JWT
    
    **Query Parameters:**
    - `status`: Filter by status (INGESTED, NORMALISED, READY_FOR_BOOKKEEPING, ERROR)
    - `limit`: Max results (default 100)
    - `offset`: Pagination offset
    """
    service = IngestionService(db)
    
    transactions = await service.get_transactions_by_client(
        client_id=client_id,
        status=status,
        source="MYFDC",
        limit=limit,
        offset=offset
    )
    
    return {
        "success": True,
        "client_id": client_id,
        "count": len(transactions),
        "transactions": transactions
    }


@router.get("/transaction/{transaction_id}")
async def get_ingested_transaction(
    transaction_id: str,
    current_user: AuthUser = Depends(require_authenticated),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a single ingested transaction by ID.
    
    **Auth:** Standard Core JWT
    """
    service = IngestionService(db)
    
    transaction = await service.get_transaction_by_id(transaction_id)
    
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction not found: {transaction_id}"
        )
    
    return {
        "success": True,
        "transaction": transaction
    }
