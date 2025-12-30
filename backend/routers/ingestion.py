"""
Bookkeeping Ingestion - API Router

Provides REST API endpoints for the ingestion pipeline:
- POST /api/ingestion/upload - Upload file, create batch
- POST /api/ingestion/parse - Parse file, suggest mappings
- POST /api/ingestion/import - Import transactions
- POST /api/ingestion/rollback - Rollback batch
- GET /api/ingestion/batches - List batches
- GET /api/ingestion/batches/{id} - Get batch details

Permissions:
- admin: full access
- staff: full access (bookkeepers)
- tax_agent: read-only (view batches)
- client: no access
"""

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import logging

from database import get_db
from middleware.auth import RoleChecker, AuthUser

# Import services
from ingestion.service import (
    UploadService,
    ParseService,
    ImportService,
    RollbackService,
    BatchService
)

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/ingestion", tags=["Bookkeeping Ingestion"])

# Permission checkers
require_ingestion_write = RoleChecker(["admin", "staff"])
require_ingestion_read = RoleChecker(["admin", "staff", "tax_agent"])


# ==================== REQUEST/RESPONSE MODELS ====================

class UploadResponse(BaseModel):
    """Response for file upload"""
    success: bool = True
    batch_id: str
    file_name: str
    file_type: str
    file_url: Optional[str] = None


class ParseRequest(BaseModel):
    """Request for parsing a batch"""
    batch_id: str = Field(..., description="Batch ID from upload")


class ParseResponse(BaseModel):
    """Response for file parsing"""
    success: bool = True
    batch_id: str
    columns: List[str]
    preview: List[Dict[str, Any]]
    row_count: int
    mapping_suggestions: Dict[str, str]
    detected_format: Optional[str] = None


class ImportRequest(BaseModel):
    """Request for importing transactions"""
    batch_id: str = Field(..., description="Batch ID to import")
    column_mapping: Dict[str, str] = Field(
        ..., 
        description="Map of transaction fields to file columns",
        examples=[{
            "date": "Transaction Date",
            "amount": "Amount",
            "description": "Description",
            "payee": "Merchant"
        }]
    )
    skip_duplicates: bool = Field(True, description="Skip duplicate transactions")


class ImportResponse(BaseModel):
    """Response for import operation"""
    success: bool = True
    batch_id: str
    imported_count: int
    skipped_duplicates: int
    error_count: int
    errors: List[Dict[str, Any]] = []


class RollbackRequest(BaseModel):
    """Request for batch rollback"""
    batch_id: str = Field(..., description="Batch ID to rollback")


class RollbackResponse(BaseModel):
    """Response for rollback operation"""
    success: bool = True
    batch_id: str
    deleted_count: int


class BatchResponse(BaseModel):
    """Response for batch details"""
    id: str
    client_id: str
    job_id: Optional[str]
    file_name: str
    file_type: str
    uploaded_by: str
    uploaded_at: Optional[str]
    row_count: int
    imported_count: int
    skipped_count: int
    error_count: int
    status: str
    notes: Optional[str]
    column_mapping: Optional[Dict[str, str]]
    errors: Optional[List[Dict[str, Any]]]


# ==================== ENDPOINTS ====================

@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(..., description="CSV or Excel file to upload"),
    client_id: str = Query(..., description="Client ID for the import"),
    job_id: Optional[str] = Query(None, description="Optional job ID"),
    current_user: AuthUser = Depends(require_ingestion_write),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a file for ingestion.
    
    Accepts CSV (.csv) or Excel (.xlsx, .xls) files.
    Creates an import batch record for tracking.
    
    **Permissions:** staff, admin
    
    **Returns:** Batch ID and file URL for next steps
    """
    # Validate file type
    file_ext = file.filename.split('.')[-1].lower() if file.filename else ""
    if file_ext not in ['csv', 'xlsx', 'xls']:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file_ext}. Supported: csv, xlsx, xls"
        )
    
    # Read file content
    try:
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Empty file")
        if len(content) > 50 * 1024 * 1024:  # 50MB limit
            raise HTTPException(status_code=400, detail="File too large (max 50MB)")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {e}")
    
    # Upload
    service = UploadService(db)
    try:
        result = await service.upload_file(
            file_content=content,
            file_name=file.filename,
            file_type=file_ext,
            client_id=client_id,
            job_id=job_id,
            user_id=current_user.id,
            user_email=current_user.email
        )
        
        return UploadResponse(
            batch_id=result["batch_id"],
            file_name=result["file_name"],
            file_type=result["file_type"],
            file_url=result.get("file_url")
        )
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/parse", response_model=ParseResponse)
async def parse_file(
    request: ParseRequest,
    current_user: AuthUser = Depends(require_ingestion_write),
    db: AsyncSession = Depends(get_db)
):
    """
    Parse an uploaded file and suggest column mappings.
    
    Returns:
    - List of columns found in the file
    - Preview of first 20 rows
    - Auto-detected column mappings
    - Detected bank format (if recognized)
    
    **Permissions:** staff, admin
    """
    service = ParseService(db)
    
    try:
        result = await service.parse_file(
            batch_id=request.batch_id,
            user_id=current_user.id,
            user_email=current_user.email
        )
        
        return ParseResponse(
            batch_id=request.batch_id,
            columns=result["columns"],
            preview=result["preview"],
            row_count=result["row_count"],
            mapping_suggestions=result["mapping_suggestions"],
            detected_format=result.get("detected_format")
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Parse failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import", response_model=ImportResponse)
async def import_transactions(
    request: ImportRequest,
    current_user: AuthUser = Depends(require_ingestion_write),
    db: AsyncSession = Depends(get_db)
):
    """
    Import transactions from a parsed batch.
    
    Requires column_mapping to specify which file columns map to:
    - date (required): Transaction date
    - amount (required): Transaction amount
    - description (optional): Transaction description
    - payee (optional): Payee/merchant name
    - category (optional): Category hint
    
    **Duplicate Detection:**
    Transactions are considered duplicates if they have the same:
    - client_id
    - date
    - amount
    - normalized description
    
    **Permissions:** staff, admin
    """
    # Validate required mappings
    if "date" not in request.column_mapping:
        raise HTTPException(status_code=400, detail="Column mapping must include 'date'")
    if "amount" not in request.column_mapping:
        raise HTTPException(status_code=400, detail="Column mapping must include 'amount'")
    
    service = ImportService(db)
    
    try:
        result = await service.import_transactions(
            batch_id=request.batch_id,
            column_mapping=request.column_mapping,
            user_id=current_user.id,
            user_email=current_user.email,
            skip_duplicates=request.skip_duplicates
        )
        
        return ImportResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Import failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rollback", response_model=RollbackResponse)
async def rollback_batch(
    request: RollbackRequest,
    current_user: AuthUser = Depends(require_ingestion_write),
    db: AsyncSession = Depends(get_db)
):
    """
    Rollback all transactions from an import batch.
    
    Deletes all transactions that were imported with the specified batch_id.
    Marks the batch status as 'rolled_back'.
    
    **Note:** Requires the import_batch_id column in transactions table.
    Run migrations/ingestion_setup.sql if not yet applied.
    
    **Permissions:** staff, admin
    """
    service = RollbackService(db)
    
    try:
        result = await service.rollback_batch(
            batch_id=request.batch_id,
            user_id=current_user.id,
            user_email=current_user.email
        )
        
        return RollbackResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Rollback failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batches", response_model=List[BatchResponse])
async def list_batches(
    client_id: Optional[str] = Query(None, description="Filter by client ID"),
    job_id: Optional[str] = Query(None, description="Filter by job ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: AuthUser = Depends(require_ingestion_read),
    db: AsyncSession = Depends(get_db)
):
    """
    List import batches with optional filters.
    
    **Permissions:** staff, tax_agent, admin
    """
    service = BatchService(db)
    
    batches = await service.list_batches(
        client_id=client_id,
        job_id=job_id,
        status=status,
        limit=limit,
        offset=offset
    )
    
    return batches


@router.get("/batches/{batch_id}")
async def get_batch(
    batch_id: str,
    current_user: AuthUser = Depends(require_ingestion_read),
    db: AsyncSession = Depends(get_db)
):
    """
    Get details of a specific import batch.
    
    **Permissions:** staff, tax_agent, admin
    """
    service = BatchService(db)
    batch = await service.get_batch(batch_id)
    
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")
    
    return batch


@router.get("/batches/{batch_id}/audit-log")
async def get_batch_audit_log(
    batch_id: str,
    current_user: AuthUser = Depends(require_ingestion_read),
    db: AsyncSession = Depends(get_db)
):
    """
    Get audit log for a specific batch.
    
    **Permissions:** staff, tax_agent, admin
    """
    service = BatchService(db)
    
    # Verify batch exists
    batch = await service.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")
    
    logs = await service.get_batch_audit_log(batch_id)
    return logs
