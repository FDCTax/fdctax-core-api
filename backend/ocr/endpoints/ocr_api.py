"""
OCR API Endpoints (A3-OCR-01)

REST API for OCR receipt processing:
- POST /api/ocr/receipt - Process receipt image and extract data
- GET /api/ocr/status - Module status

Flow:
1. Validate uploaded file URL
2. Download file to local storage
3. Call OpenAI Vision API for OCR
4. Store results and link to ingestion transaction (if provided)
5. Return structured OCR results
"""

import os
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from ocr.services.ocr_service import ocr_service, OCRResult
from ingestion.unified_schema import AttachmentRef, OCRStatus, AuditEntry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ocr", tags=["OCR"])


# ==================== Request/Response Models ====================

class OCRReceiptRequest(BaseModel):
    """Request to process a receipt image."""
    client_id: str = Field(..., description="Core client ID")
    file_url: str = Field(..., description="URL of the receipt image to process")
    transaction_id: Optional[str] = Field(
        default=None,
        description="Optional transaction ID to link OCR results to"
    )


class OCRReceiptResponse(BaseModel):
    """Response from OCR receipt processing."""
    success: bool
    attachment_id: Optional[str] = None
    ocr_result: Optional[dict] = None
    transaction_updated: bool = False
    error: Optional[str] = None


class OCRStatusResponse(BaseModel):
    """Module status response."""
    module: str
    status: str
    version: str
    features: dict
    storage_path: str
    timestamp: str


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


# ==================== Audit Logging ====================

def log_ocr_event(
    event_type: str,
    client_id: str,
    details: dict,
    success: bool = True
):
    """Log OCR event for audit trail."""
    log_entry = {
        "event": event_type,
        "client_id": client_id,
        "details": details,
        "success": success,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    if success:
        logger.info(f"OCR event: {event_type}", extra=log_entry)
    else:
        logger.warning(f"OCR event FAILED: {event_type}", extra=log_entry)


# ==================== Endpoints ====================

@router.get("/status", response_model=OCRStatusResponse, summary="Module status")
async def get_module_status():
    """
    Get OCR module status.
    
    Returns configuration and availability information.
    No authentication required.
    """
    emergent_key_configured = bool(os.environ.get('EMERGENT_LLM_KEY'))
    
    return OCRStatusResponse(
        module="ocr",
        status="operational" if emergent_key_configured else "degraded",
        version="1.0.0",
        features={
            "receipt_ocr": True,
            "pdf_support": True,
            "image_formats": ["jpeg", "png", "webp"],
            "openai_vision": emergent_key_configured,
            "transaction_linking": True
        },
        storage_path=os.environ.get('STORAGE_REF_BASE', '/app/storage/receipts'),
        timestamp=datetime.now(timezone.utc).isoformat()
    )


@router.post("/receipt", response_model=OCRReceiptResponse, summary="Process receipt")
async def process_receipt(
    request: OCRReceiptRequest,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    Process a receipt image and extract structured data.
    
    This endpoint:
    1. Downloads the image from the provided URL
    2. Stores it in local storage
    3. Sends it to OpenAI Vision API for OCR
    4. Returns structured receipt data (vendor, amount, date, items)
    5. Optionally links results to an existing ingestion transaction
    
    Requires internal API key authentication.
    """
    try:
        # Validate file URL
        if not ocr_service.validate_file_url(request.file_url):
            raise HTTPException(
                status_code=400,
                detail="Invalid file URL. Must be a valid HTTP(S) URL."
            )
        
        # Log start
        log_ocr_event(
            "ocr.receipt.started",
            request.client_id,
            {
                "file_url": request.file_url[:100],  # Truncate for logging
                "transaction_id": request.transaction_id
            }
        )
        
        # Process receipt
        ocr_result, attachment = await ocr_service.process_receipt(
            file_url=request.file_url,
            client_id=request.client_id,
            transaction_id=request.transaction_id
        )
        
        # Handle OCR failure
        if not ocr_result.success:
            log_ocr_event(
                "ocr.receipt.failed",
                request.client_id,
                {"error": ocr_result.error_message},
                success=False
            )
            
            return OCRReceiptResponse(
                success=False,
                error=ocr_result.error_message
            )
        
        # Store attachment in database
        attachment_id = None
        if attachment:
            attachment_id = await _store_attachment(
                db,
                request.client_id,
                attachment
            )
        
        # Link to transaction if provided
        transaction_updated = False
        if request.transaction_id and attachment:
            transaction_updated = await _link_ocr_to_transaction(
                db,
                request.transaction_id,
                attachment,
                ocr_result
            )
        
        # Commit changes
        try:
            await db.commit()
        except Exception as e:
            logger.error(f"Failed to commit OCR results: {e}")
            await db.rollback()
            raise HTTPException(status_code=500, detail="Failed to save OCR results")
        
        # Log success
        log_ocr_event(
            "ocr.receipt.completed",
            request.client_id,
            {
                "attachment_id": attachment_id,
                "transaction_updated": transaction_updated,
                "vendor": ocr_result.vendor,
                "amount": str(ocr_result.amount) if ocr_result.amount else None,
                "confidence": ocr_result.confidence
            }
        )
        
        return OCRReceiptResponse(
            success=True,
            attachment_id=attachment_id,
            ocr_result=ocr_result.to_dict(),
            transaction_updated=transaction_updated
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        log_ocr_event(
            "ocr.receipt.validation_error",
            request.client_id,
            {"error": str(e)},
            success=False
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"OCR processing failed: {e}")
        log_ocr_event(
            "ocr.receipt.error",
            request.client_id,
            {"error": str(e)},
            success=False
        )
        raise HTTPException(status_code=500, detail="OCR processing failed")


# ==================== Helper Functions ====================

async def _store_attachment(
    db: AsyncSession,
    client_id: str,
    attachment: AttachmentRef
) -> str:
    """Store attachment metadata in database."""
    try:
        attachment_id = attachment.id
        now = datetime.now(timezone.utc)
        
        # Get uploaded_at as datetime object (not string)
        uploaded_at = attachment.uploaded_at if attachment.uploaded_at else now
        
        query = text("""
            INSERT INTO public.ingestion_attachments (
                id, client_id, file_name, file_type, file_size,
                storage_path, ocr_status, ocr_result, uploaded_at,
                created_at, updated_at
            ) VALUES (
                :id, :client_id, :file_name, :file_type, :file_size,
                :storage_path, :ocr_status, :ocr_result, :uploaded_at,
                :created_at, :updated_at
            )
            ON CONFLICT (id) DO UPDATE SET
                ocr_status = EXCLUDED.ocr_status,
                ocr_result = EXCLUDED.ocr_result,
                updated_at = EXCLUDED.updated_at
            RETURNING id
        """)
        
        result = await db.execute(query, {
            "id": attachment_id,
            "client_id": client_id,
            "file_name": attachment.file_name,
            "file_type": attachment.file_type,
            "file_size": attachment.file_size,
            "storage_path": attachment.storage_path,
            "ocr_status": attachment.ocr_status.value if hasattr(attachment.ocr_status, 'value') else str(attachment.ocr_status),
            "ocr_result": json.dumps(attachment.ocr_result) if attachment.ocr_result else None,
            "uploaded_at": uploaded_at,
            "created_at": now,
            "updated_at": now
        })
        
        row = result.fetchone()
        return str(row[0]) if row else attachment_id
        
    except Exception as e:
        logger.error(f"Failed to store attachment: {e}")
        return attachment.id


async def _link_ocr_to_transaction(
    db: AsyncSession,
    transaction_id: str,
    attachment: AttachmentRef,
    ocr_result: OCRResult
) -> bool:
    """
    Link OCR results to an existing ingestion transaction.
    
    Updates:
    - Adds attachment to transaction's attachments array
    - Sets ocr_status = PROCESSED
    - Stores ocr_result
    - Appends audit entry
    
    Does NOT modify bookkeeping-ready fields (amount, category, etc.)
    """
    try:
        # First, get current transaction data
        get_query = text("""
            SELECT attachments, audit
            FROM public.ingested_transactions
            WHERE id = :id
        """)
        
        result = await db.execute(get_query, {"id": transaction_id})
        row = result.fetchone()
        
        if not row:
            logger.warning(f"Transaction {transaction_id} not found for OCR linking")
            return False
        
        # Parse existing data
        existing_attachments = row[0] if row[0] else []
        existing_audit = row[1] if row[1] else []
        
        if isinstance(existing_attachments, str):
            existing_attachments = json.loads(existing_attachments)
        if isinstance(existing_audit, str):
            existing_audit = json.loads(existing_audit)
        
        # Add new attachment
        existing_attachments.append(attachment.to_dict())
        
        # Add audit entry
        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "ocr_processed",
            "actor": "ocr_service",
            "details": {
                "attachment_id": attachment.id,
                "ocr_status": "PROCESSED" if ocr_result.success else "FAILED",
                "confidence": ocr_result.confidence,
                "vendor": ocr_result.vendor,
                "amount": str(ocr_result.amount) if ocr_result.amount else None
            }
        }
        existing_audit.append(audit_entry)
        
        # Update transaction
        update_query = text("""
            UPDATE public.ingested_transactions
            SET 
                attachments = :attachments,
                audit = :audit,
                updated_at = NOW()
            WHERE id = :id
            RETURNING id
        """)
        
        result = await db.execute(update_query, {
            "id": transaction_id,
            "attachments": json.dumps(existing_attachments),
            "audit": json.dumps(existing_audit)
        })
        
        updated = result.fetchone()
        return updated is not None
        
    except Exception as e:
        logger.error(f"Failed to link OCR to transaction: {e}")
        return False
