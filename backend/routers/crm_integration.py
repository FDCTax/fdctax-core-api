"""
CRM Integration Endpoints

Additional endpoints required for CRM → Core integration.
All endpoints support internal API key authentication.

Endpoints:
- GET /api/bookkeeping/transactions - List all bookkeeping-ready transactions (with optional client filter)
- GET /api/reconciliation/groups - Get reconciliation match groups
- POST /api/ocr/extract - Extract data from receipt (alias for /api/ocr/receipt)
- GET /api/ingestion/myfdc/imports - List import batches
"""

import os
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from utils.validation_errors import validate_client_id, raise_missing_parameter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["CRM Integration"])


# ==================== Authentication ====================

def get_internal_api_keys() -> List[str]:
    """Get list of valid internal API keys."""
    primary_key = os.environ.get('INTERNAL_API_KEY', '')
    legacy_keys = os.environ.get('INTERNAL_API_KEYS', '')
    
    keys = []
    if primary_key:
        keys.append(primary_key)
    if legacy_keys:
        keys.extend([k.strip() for k in legacy_keys.split(',') if k.strip()])
    
    return keys


def verify_internal_auth(x_internal_api_key: Optional[str] = Header(None, alias="X-Internal-Api-Key")):
    """Verify internal API key authentication."""
    valid_keys = get_internal_api_keys()
    
    if not valid_keys:
        logger.warning("No internal API keys configured")
        raise HTTPException(status_code=503, detail="Internal authentication not configured")
    
    if not x_internal_api_key:
        raise HTTPException(status_code=401, detail="Missing X-Internal-Api-Key header")
    
    if x_internal_api_key not in valid_keys:
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    return True


async def resolve_client_id(db: AsyncSession, client_id: str) -> Optional[str]:
    """
    Resolve a client ID to a Core UUID.
    
    Accepts:
    - UUID format: Returns as-is if valid
    - Numeric format: Looks up by crm_client_id
    
    Returns None if client not found (allows empty result queries).
    """
    import uuid
    
    if not client_id:
        return None
    
    # Check if it's a valid UUID
    try:
        uuid.UUID(client_id)
        return client_id
    except ValueError:
        pass
    
    # Try to look up by crm_client_id
    query = text("""
        SELECT id::text FROM public.client_profiles
        WHERE crm_client_id = :crm_id
        LIMIT 1
    """)
    
    result = await db.execute(query, {"crm_id": client_id})
    row = result.fetchone()
    
    if row:
        return row[0]
    
    # Return a placeholder UUID that won't match anything
    # This allows the query to run but return empty results
    return "00000000-0000-0000-0000-000000000000"


# ==================== Response Models ====================

class TransactionSummary(BaseModel):
    """Summary of a bookkeeping-ready transaction."""
    id: str
    client_id: str
    source: str
    transaction_date: Optional[str]
    transaction_type: str
    amount: str
    category_code: Optional[str]
    category_normalised: Optional[str]
    vendor: Optional[str]
    description: Optional[str]
    status: str
    ingested_at: Optional[str]


class ReconciliationGroup(BaseModel):
    """Group of matched transactions."""
    group_id: str
    client_id: str
    source_type: str
    target_type: str
    match_count: int
    status: str
    total_amount: str
    created_at: str


class ImportBatch(BaseModel):
    """Import batch summary."""
    batch_id: str
    client_id: str
    source: str
    total_count: int
    ingested_count: int
    error_count: int
    created_at: str
    status: str


# ==================== BOOKKEEPING ENDPOINTS ====================

@router.get("/bookkeeping/transactions", summary="List bookkeeping transactions")
async def list_bookkeeping_transactions(
    client_id: Optional[str] = Query(None, description="Filter by client ID (UUID or CRM ID)"),
    status: Optional[str] = Query(None, description="Filter by status"),
    source: Optional[str] = Query(None, description="Filter by source"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    List bookkeeping-ready transactions.
    
    **Auth:** Internal API Key (X-Internal-Api-Key header)
    
    **Filters:**
    - client_id: Filter by specific client (accepts UUID or CRM numeric ID)
    - status: Filter by status (READY_FOR_BOOKKEEPING, INGESTED, etc.)
    - source: Filter by source (MYFDC, OCR, etc.)
    
    **Pagination:**
    - limit: Max results (1-500, default 100)
    - offset: Skip N records
    """
    conditions = []
    params = {"limit": limit, "offset": offset}
    
    # Resolve client_id to Core UUID (handles both UUID and CRM numeric IDs)
    if client_id:
        resolved_client_id = await resolve_client_id(db, client_id)
        conditions.append("client_id = :client_id::uuid")
        params["client_id"] = resolved_client_id
    
    if status:
        conditions.append("status = :status")
        params["status"] = status
    else:
        # Default to bookkeeping-ready
        conditions.append("status = 'READY_FOR_BOOKKEEPING'")
    
    if source:
        conditions.append("source = :source")
        params["source"] = source
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    # Get total count
    count_query = text(f"""
        SELECT COUNT(*) FROM public.ingested_transactions
        WHERE {where_clause}
    """)
    count_result = await db.execute(count_query, params)
    total_count = count_result.scalar() or 0
    
    # Get transactions
    query = text(f"""
        SELECT 
            id::text, client_id::text, source, 
            transaction_date, transaction_type, amount,
            category_code, category_normalised, vendor,
            description, status, ingested_at
        FROM public.ingested_transactions
        WHERE {where_clause}
        ORDER BY transaction_date DESC, ingested_at DESC
        LIMIT :limit OFFSET :offset
    """)
    
    result = await db.execute(query, params)
    rows = result.fetchall()
    
    transactions = []
    for row in rows:
        # Handle date serialization
        txn_date = row[3]
        if txn_date and hasattr(txn_date, 'isoformat'):
            txn_date = txn_date.isoformat()
        elif txn_date:
            txn_date = str(txn_date)
            
        ingested_at = row[11]
        if ingested_at and hasattr(ingested_at, 'isoformat'):
            ingested_at = ingested_at.isoformat()
        elif ingested_at:
            ingested_at = str(ingested_at)
        
        transactions.append({
            "id": row[0],
            "client_id": row[1],
            "source": row[2],
            "transaction_date": txn_date,
            "transaction_type": row[4],
            "amount": str(row[5]) if row[5] else "0",
            "category_code": row[6],
            "category_normalised": row[7],
            "vendor": row[8],
            "description": row[9],
            "status": row[10],
            "ingested_at": ingested_at
        })
    
    return {
        "success": True,
        "total_count": total_count,
        "count": len(transactions),
        "limit": limit,
        "offset": offset,
        "has_more": (offset + len(transactions)) < total_count,
        "transactions": transactions
    }


# ==================== RECONCILIATION ENDPOINTS ====================

@router.get("/reconciliation/groups", summary="Get reconciliation groups")
async def get_reconciliation_groups(
    client_id: Optional[str] = Query(None, description="Filter by client ID (UUID or CRM ID)"),
    status: Optional[str] = Query(None, description="Filter by match status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    Get reconciliation match groups.
    
    **Auth:** Internal API Key (X-Internal-Api-Key header)
    
    Groups transactions by reconciliation run/batch for easier management.
    
    **Filters:**
    - client_id: Filter by specific client (accepts UUID or CRM numeric ID)
    - status: Filter by match status (MATCHED, SUGGESTED, NO_MATCH, etc.)
    """
    conditions = []
    params = {"limit": limit, "offset": offset}
    
    # Resolve client_id to Core UUID (handles both UUID and CRM numeric IDs)
    if client_id:
        resolved_client_id = await resolve_client_id(db, client_id)
        conditions.append("client_id = :client_id::uuid")
        params["client_id"] = resolved_client_id
    
    if status:
        conditions.append("match_status = :status")
        params["status"] = status
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    # Group by client and source type to create logical groups
    query = text(f"""
        SELECT 
            client_id::text,
            source_type,
            target_type,
            match_status,
            COUNT(*) as match_count,
            COALESCE(SUM(confidence_score), 0) as total_confidence,
            MIN(created_at) as first_match,
            MAX(created_at) as last_match
        FROM public.reconciliation_matches
        WHERE {where_clause}
        GROUP BY client_id, source_type, target_type, match_status
        ORDER BY MAX(created_at) DESC
        LIMIT :limit OFFSET :offset
    """)
    
    result = await db.execute(query, params)
    rows = result.fetchall()
    
    groups = []
    for i, row in enumerate(rows):
        first_match = row[6]
        if first_match and hasattr(first_match, 'isoformat'):
            first_match = first_match.isoformat()
        
        groups.append({
            "group_id": f"grp-{row[0][:8]}-{row[1]}-{row[3]}".lower(),
            "client_id": row[0],
            "source_type": row[1],
            "target_type": row[2] or "BANK",
            "status": row[3],
            "match_count": row[4],
            "avg_confidence": round(float(row[5]) / row[4], 2) if row[4] > 0 else 0,
            "created_at": first_match
        })
    
    # Get total count
    count_query = text(f"""
        SELECT COUNT(DISTINCT (client_id, source_type, target_type, match_status))
        FROM public.reconciliation_matches
        WHERE {where_clause}
    """)
    count_result = await db.execute(count_query, params)
    total_count = count_result.scalar() or 0
    
    return {
        "success": True,
        "total_count": total_count,
        "count": len(groups),
        "limit": limit,
        "offset": offset,
        "groups": groups
    }


# ==================== OCR ENDPOINTS ====================

@router.post("/ocr/extract", summary="Extract data from receipt")
async def extract_receipt_data(
    request: dict,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    Extract data from a receipt image.
    
    **Auth:** Internal API Key (X-Internal-Api-Key header)
    
    This is an alias for POST /api/ocr/receipt with CRM-friendly naming.
    
    **Request Body:**
    - client_id: Core client ID
    - file_url: URL of the receipt image
    - transaction_id: Optional transaction to link OCR results to
    """
    # Import and delegate to OCR service
    from ocr.services.ocr_service import ocr_service
    from ocr.endpoints.ocr_api import _store_attachment, _link_ocr_to_transaction
    import json
    
    # Validate request
    client_id = request.get("client_id")
    file_url = request.get("file_url")
    transaction_id = request.get("transaction_id")
    
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")
    if not file_url:
        raise HTTPException(status_code=400, detail="file_url is required")
    
    if not ocr_service.validate_file_url(file_url):
        raise HTTPException(status_code=400, detail="Invalid file URL. Must be HTTP(S).")
    
    try:
        # Process receipt
        ocr_result, attachment = await ocr_service.process_receipt(
            file_url=file_url,
            client_id=client_id,
            transaction_id=transaction_id
        )
        
        if not ocr_result.success:
            return {
                "success": False,
                "error": ocr_result.error_message,
                "extracted_data": None
            }
        
        # Store attachment
        attachment_id = None
        if attachment:
            attachment_id = await _store_attachment(db, client_id, attachment)
        
        # Link to transaction if provided
        transaction_updated = False
        if transaction_id and attachment:
            transaction_updated = await _link_ocr_to_transaction(
                db, transaction_id, attachment, ocr_result
            )
        
        await db.commit()
        
        return {
            "success": True,
            "attachment_id": attachment_id,
            "transaction_updated": transaction_updated,
            "extracted_data": {
                "vendor": ocr_result.vendor,
                "amount": str(ocr_result.amount) if ocr_result.amount else None,
                "date": ocr_result.date,
                "description": ocr_result.description,
                "gst_amount": str(ocr_result.gst_amount) if ocr_result.gst_amount else None,
                "gst_included": ocr_result.gst_included,
                "items": ocr_result.items,
                "raw_text": ocr_result.raw_text,
                "confidence": ocr_result.confidence
            }
        }
        
    except Exception as e:
        logger.error(f"OCR extraction failed: {e}")
        raise HTTPException(status_code=500, detail=f"OCR extraction failed: {str(e)}")


# ==================== INGESTION ENDPOINTS ====================

@router.get("/ingestion/myfdc/imports", summary="List MyFDC import batches")
async def list_myfdc_imports(
    client_id: Optional[str] = Query(None, description="Filter by client ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    List MyFDC import batches.
    
    **Auth:** Internal API Key (X-Internal-Api-Key header)
    
    Returns summary of import batches with counts and status.
    
    **Filters:**
    - client_id: Filter by specific client (accepts UUID or numeric format)
    """
    # Validate client_id accepts both UUID (Core) and numeric (CRM) formats
    validated_client_id = validate_client_id(client_id, "client_id", required=False)
    
    conditions = ["source = 'MYFDC'"]
    params = {"limit": limit, "offset": offset}
    
    if validated_client_id:
        conditions.append("client_id = :client_id")
        params["client_id"] = validated_client_id
    
    where_clause = " AND ".join(conditions)
    
    # Group by client and ingestion date to simulate batches
    query = text(f"""
        SELECT 
            client_id::text,
            DATE(ingested_at) as import_date,
            COUNT(*) as total_count,
            COUNT(*) FILTER (WHERE status = 'INGESTED') as ingested_count,
            COUNT(*) FILTER (WHERE status = 'READY_FOR_BOOKKEEPING') as ready_count,
            COUNT(*) FILTER (WHERE status = 'ERROR') as error_count,
            MIN(ingested_at) as first_ingested,
            MAX(ingested_at) as last_ingested
        FROM public.ingested_transactions
        WHERE {where_clause}
        GROUP BY client_id, DATE(ingested_at)
        ORDER BY MAX(ingested_at) DESC
        LIMIT :limit OFFSET :offset
    """)
    
    result = await db.execute(query, params)
    rows = result.fetchall()
    
    imports = []
    for row in rows:
        import_date = row[1]
        if import_date and hasattr(import_date, 'isoformat'):
            import_date_str = import_date.isoformat()
        else:
            import_date_str = str(import_date) if import_date else None
            
        first_ingested = row[6]
        if first_ingested and hasattr(first_ingested, 'isoformat'):
            first_ingested = first_ingested.isoformat()
        
        # Determine overall status
        if row[5] > 0:  # Has errors
            status = "PARTIAL"
        elif row[4] == row[2]:  # All ready
            status = "COMPLETED"
        elif row[3] > 0:  # Still processing
            status = "PROCESSING"
        else:
            status = "UNKNOWN"
        
        imports.append({
            "batch_id": f"batch-{row[0][:8]}-{import_date_str}",
            "client_id": row[0],
            "source": "MYFDC",
            "import_date": import_date_str,
            "total_count": row[2],
            "ingested_count": row[3],
            "ready_count": row[4],
            "error_count": row[5],
            "created_at": first_ingested,
            "status": status
        })
    
    return {
        "success": True,
        "count": len(imports),
        "limit": limit,
        "offset": offset,
        "imports": imports
    }


@router.post("/ingestion/myfdc", summary="Ingest MyFDC transactions")
async def ingest_myfdc_transactions(
    request: dict,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    Ingest transactions from MyFDC (internal API key auth).
    
    **Auth:** Internal API Key (X-Internal-Api-Key header)
    
    **Request Body:**
    ```json
    {
        "client_id": "uuid",
        "transactions": [
            {
                "id": "MYFDC-001",
                "transaction_date": "2026-01-03",
                "transaction_type": "expense",
                "amount": 150.00,
                "gst_included": true,
                "category": "Office Supplies",
                "description": "Printer paper",
                "vendor": "Officeworks",
                "receipt_number": "INV-123",
                "business_percentage": 100
            }
        ]
    }
    ```
    """
    from ingestion.services.ingestion_service import IngestionService
    
    client_id = request.get("client_id")
    transactions = request.get("transactions", [])
    
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")
    if not transactions:
        raise HTTPException(status_code=400, detail="transactions list is required and cannot be empty")
    
    service = IngestionService(db)
    
    try:
        result = await service.ingest_myfdc_batch(
            client_id=client_id,
            payloads=transactions,
            user_id="crm-service",
            user_email="crm@internal.fdccore.com"
        )
        
        return {
            "success": result.error_count == 0,
            "batch_id": result.batch_id,
            "client_id": result.client_id,
            "source": result.source,
            "total_count": result.total_count,
            "ingested_count": result.ingested_count,
            "error_count": result.error_count,
            "normalisation_queued": result.ingested_count > 0,
            "transactions": [
                {
                    "id": t.id,
                    "source": t.source,
                    "source_transaction_id": t.source_transaction_id,
                    "status": t.status,
                    "ingested_at": t.ingested_at.isoformat()
                }
                for t in result.transactions
            ],
            "errors": result.errors if result.errors else None
        }
        
    except Exception as e:
        logger.error(f"MyFDC ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


# ==================== DOCUMENT PREPARATION ENDPOINT ====================

@router.post("/ingestion/prepare-document", summary="Prepare document for ingestion")
async def prepare_document(
    request: dict,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    Prepare a document for ingestion (OCR or file parsing).
    
    **Auth:** Internal API Key (X-Internal-Api-Key header)
    
    **Request Body:**
    ```json
    {
        "client_id": "uuid",
        "document_url": "https://...",
        "document_type": "receipt|invoice|bank_statement",
        "transaction_id": "optional-uuid-to-link"
    }
    ```
    
    **Processing:**
    1. Downloads the document
    2. Determines document type (image → OCR, CSV/Excel → parse)
    3. Extracts data based on type
    4. Returns structured data ready for import
    """
    from ocr.services.ocr_service import ocr_service
    
    client_id = request.get("client_id")
    document_url = request.get("document_url")
    document_type = request.get("document_type", "receipt")
    transaction_id = request.get("transaction_id")
    
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")
    if not document_url:
        raise HTTPException(status_code=400, detail="document_url is required")
    
    # Determine processing method based on URL/type
    url_lower = document_url.lower()
    is_image = any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.webp', '.pdf'])
    
    if is_image or document_type in ['receipt', 'invoice']:
        # Use OCR for images and receipts
        if not ocr_service.validate_file_url(document_url):
            raise HTTPException(status_code=400, detail="Invalid document URL")
        
        try:
            ocr_result, attachment = await ocr_service.process_receipt(
                file_url=document_url,
                client_id=client_id,
                transaction_id=transaction_id
            )
            
            return {
                "success": ocr_result.success,
                "document_id": attachment.id if attachment else None,
                "processing_type": "ocr",
                "document_type": document_type,
                "extracted_data": {
                    "vendor": ocr_result.vendor,
                    "amount": str(ocr_result.amount) if ocr_result.amount else None,
                    "date": ocr_result.date,
                    "description": ocr_result.description,
                    "gst_amount": str(ocr_result.gst_amount) if ocr_result.gst_amount else None,
                    "gst_included": ocr_result.gst_included,
                    "items": ocr_result.items,
                    "raw_text": ocr_result.raw_text,
                    "confidence": ocr_result.confidence
                } if ocr_result.success else None,
                "error": ocr_result.error_message if not ocr_result.success else None,
                "ready_for_import": ocr_result.success
            }
            
        except Exception as e:
            logger.error(f"Document preparation failed: {e}")
            return {
                "success": False,
                "processing_type": "ocr",
                "document_type": document_type,
                "error": str(e),
                "ready_for_import": False
            }
    else:
        # For CSV/Excel, return info about the document
        return {
            "success": True,
            "processing_type": "file_parse",
            "document_type": document_type,
            "message": "Document URL stored. Use /api/ingestion/upload to upload the file for parsing.",
            "next_steps": [
                "1. Download the document from document_url",
                "2. POST to /api/ingestion/upload with the file",
                "3. POST to /api/ingestion/parse with the batch_id",
                "4. POST to /api/ingestion/import with column mappings"
            ],
            "ready_for_import": False
        }


# ==================== IMPORT ENDPOINT (Internal Auth) ====================

@router.post("/ingestion/import", summary="Import transactions from batch")
async def import_from_batch(
    request: dict,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    Import transactions from a parsed batch (internal API key auth).
    
    **Auth:** Internal API Key (X-Internal-Api-Key header)
    
    **Request Body:**
    ```json
    {
        "batch_id": "uuid",
        "column_mapping": {
            "date": "Transaction Date",
            "amount": "Amount",
            "description": "Description",
            "payee": "Merchant"
        },
        "skip_duplicates": true
    }
    ```
    
    **Alternative - Direct Transaction Import:**
    ```json
    {
        "client_id": "uuid",
        "transactions": [
            {
                "date": "2026-01-03",
                "amount": -150.00,
                "description": "Office supplies",
                "payee": "Officeworks",
                "category": "office_expenses"
            }
        ]
    }
    ```
    """
    from ingestion.service import ImportService
    from ingestion.services.ingestion_service import IngestionService
    
    # Check which mode: batch import or direct import
    batch_id = request.get("batch_id")
    client_id = request.get("client_id")
    transactions = request.get("transactions")
    
    if batch_id:
        # Batch import mode - use existing ImportService
        column_mapping = request.get("column_mapping", {})
        skip_duplicates = request.get("skip_duplicates", True)
        
        if "date" not in column_mapping:
            raise HTTPException(status_code=400, detail="column_mapping must include 'date'")
        if "amount" not in column_mapping:
            raise HTTPException(status_code=400, detail="column_mapping must include 'amount'")
        
        service = ImportService(db)
        
        try:
            result = await service.import_transactions(
                batch_id=batch_id,
                column_mapping=column_mapping,
                user_id="crm-service",
                user_email="crm@internal.fdccore.com",
                skip_duplicates=skip_duplicates
            )
            
            return {
                "success": True,
                "import_type": "batch",
                **result
            }
            
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            logger.error(f"Batch import failed: {e}")
            raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")
    
    elif client_id and transactions:
        # Direct transaction import mode - convert to MyFDC format
        service = IngestionService(db)
        
        # Transform simple format to MyFDC format
        myfdc_payloads = []
        for i, txn in enumerate(transactions):
            myfdc_payloads.append({
                "id": txn.get("id", f"CRM-IMPORT-{i}"),
                "transaction_date": txn.get("date"),
                "transaction_type": "expense" if (txn.get("amount", 0) < 0) else "income",
                "amount": abs(float(txn.get("amount", 0))),
                "description": txn.get("description"),
                "vendor": txn.get("payee") or txn.get("vendor"),
                "category": txn.get("category"),
                "gst_included": txn.get("gst_included", True),
                "business_percentage": txn.get("business_percentage", 100)
            })
        
        try:
            result = await service.ingest_myfdc_batch(
                client_id=client_id,
                payloads=myfdc_payloads,
                user_id="crm-service",
                user_email="crm@internal.fdccore.com"
            )
            
            return {
                "success": result.error_count == 0,
                "import_type": "direct",
                "batch_id": result.batch_id,
                "client_id": result.client_id,
                "imported_count": result.ingested_count,
                "error_count": result.error_count,
                "errors": result.errors if result.errors else None
            }
            
        except Exception as e:
            logger.error(f"Direct import failed: {e}")
            raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")
    
    else:
        raise HTTPException(
            status_code=400,
            detail="Request must include either 'batch_id' with 'column_mapping', or 'client_id' with 'transactions'"
        )
