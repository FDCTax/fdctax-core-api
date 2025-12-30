"""
LodgeIT Integration - API Router

Provides REST API endpoints for LodgeIT integration:
- GET /api/lodgeit/export-queue - List pending exports
- POST /api/lodgeit/export - Export clients to CSV
- POST /api/lodgeit/import - Import from CSV
- POST /api/lodgeit/export-itr-template - Generate ITR JSON
- POST /api/lodgeit/queue/add - Manually add to queue

Permissions:
- Only accountant and admin roles can access these endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import io
import logging

from database import get_db
from middleware.auth import get_current_user_required, AuthUser, RoleChecker

# Import LodgeIT services
from lodgeit_integration.export_service import export_clients
from lodgeit_integration.import_service import import_csv
from lodgeit_integration.itr_export import generate_itr_template
from lodgeit_integration.queue_service import QueueService
from lodgeit_integration.models import LodgeITAuditLogDB, LodgeITAction

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/lodgeit", tags=["LodgeIT Integration"])

# Permission checker - only accountant and admin can access
require_lodgeit_access = RoleChecker(["admin", "staff", "accountant"])


# ==================== REQUEST/RESPONSE MODELS ====================

class ExportRequest(BaseModel):
    """Request body for export endpoint"""
    client_ids: List[int] = Field(..., min_length=1, description="List of client IDs to export")


class ImportResponse(BaseModel):
    """Response model for import endpoint"""
    success: bool
    created_count: int
    updated_count: int
    skipped_count: int
    errors: List[dict] = []


class ITRTemplateRequest(BaseModel):
    """Request body for ITR template generation"""
    client_id: int = Field(..., description="Client ID for ITR template")


class QueueAddRequest(BaseModel):
    """Request body for adding client to queue"""
    client_id: int = Field(..., description="Client ID to add to queue")


class QueueEntry(BaseModel):
    """Response model for queue entries"""
    id: int
    client_id: int
    status: str
    trigger_reason: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    last_exported_at: Optional[str]
    client_name: Optional[str]
    client_email: Optional[str]
    business_name: Optional[str]


class QueueStats(BaseModel):
    """Response model for queue statistics"""
    pending: int
    exported: int
    failed: int
    total: int


# ==================== ENDPOINTS ====================

@router.get("/export-queue", response_model=List[QueueEntry])
async def get_export_queue(
    current_user: AuthUser = Depends(require_lodgeit_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the list of clients pending export to LodgeIT.
    
    Returns all clients in the export queue with status 'pending'.
    
    **Permissions:** accountant, admin
    """
    service = QueueService(db)
    queue = await service.get_pending_exports()
    return queue


@router.get("/export-queue/stats", response_model=QueueStats)
async def get_queue_stats(
    current_user: AuthUser = Depends(require_lodgeit_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Get export queue statistics.
    
    **Permissions:** accountant, admin
    """
    service = QueueService(db)
    stats = await service.get_queue_stats()
    return stats


@router.post("/export")
async def export_to_lodgeit(
    request: ExportRequest,
    current_user: AuthUser = Depends(require_lodgeit_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Export clients to LodgeIT CSV format.
    
    Generates a CSV file containing the specified clients in LodgeIT format.
    Updates the export queue status for each client.
    
    **Permissions:** accountant, admin
    
    **Request Body:**
    - client_ids: List of client IDs to export
    
    **Response:**
    - CSV file stream
    """
    result = await export_clients(
        db=db,
        client_ids=request.client_ids,
        user_id=current_user.id,
        user_email=current_user.email
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Export failed"))
    
    # Return CSV as streaming response
    csv_content = result["csv_content"]
    filename = f"lodgeit_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return StreamingResponse(
        io.StringIO(csv_content),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Exported-Count": str(result["exported_count"])
        }
    )


@router.post("/import", response_model=ImportResponse)
async def import_from_lodgeit(
    file: UploadFile = File(..., description="LodgeIT CSV file to import"),
    force_overwrite: bool = Query(False, description="Force overwrite existing data (admin only)"),
    current_user: AuthUser = Depends(require_lodgeit_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Import clients from LodgeIT CSV file.
    
    Applies safe overwrite rules:
    - Only updates empty fields unless force_overwrite is True
    - Creates new records for unknown client IDs
    - Logs all changes for audit compliance
    
    **Permissions:** accountant, admin (force_overwrite requires admin)
    
    **Request:**
    - file: CSV file in LodgeIT format
    - force_overwrite: Override safe overwrite rules (admin only)
    """
    # Only admin can force overwrite
    if force_overwrite and current_user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admin can use force_overwrite"
        )
    
    # Read file content
    try:
        content = await file.read()
        file_content = content.decode("utf-8")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {e}")
    
    # Import
    result = await import_csv(
        db=db,
        file_content=file_content,
        user_id=current_user.id,
        user_email=current_user.email,
        force_overwrite=force_overwrite
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Import failed"))
    
    return ImportResponse(
        success=result["success"],
        created_count=result["created_count"],
        updated_count=result["updated_count"],
        skipped_count=result["skipped_count"],
        errors=result.get("errors", [])
    )


@router.post("/export-itr-template")
async def export_itr_template(
    request: ITRTemplateRequest,
    current_user: AuthUser = Depends(require_lodgeit_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate a LodgeIT ITR JSON template for a client.
    
    Produces a JSON template containing the client's tax information
    in the format required by LodgeIT for ITR lodgement.
    
    **Permissions:** accountant, admin
    
    **Request Body:**
    - client_id: Client ID for ITR template
    
    **Response:**
    - ITR JSON template
    """
    result = await generate_itr_template(
        db=db,
        client_id=request.client_id,
        user_id=current_user.id,
        user_email=current_user.email
    )
    
    if not result["success"]:
        raise HTTPException(
            status_code=404 if "not found" in result.get("error", "").lower() else 400,
            detail=result.get("error", "ITR template generation failed")
        )
    
    return {
        "success": True,
        "client_id": result["client_id"],
        "template": result["template"]
    }


@router.post("/queue/add")
async def add_to_queue(
    request: QueueAddRequest,
    current_user: AuthUser = Depends(require_lodgeit_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually add a client to the export queue.
    
    **Permissions:** accountant, admin
    
    **Request Body:**
    - client_id: Client ID to add
    """
    service = QueueService(db)
    result = await service.add_to_queue(
        client_id=request.client_id,
        trigger_reason="manual",
        user_id=current_user.id,
        user_email=current_user.email
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    
    return result


@router.delete("/queue/{client_id}")
async def remove_from_queue(
    client_id: int,
    current_user: AuthUser = Depends(require_lodgeit_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Remove a client from the export queue.
    
    **Permissions:** accountant, admin
    """
    service = QueueService(db)
    result = await service.remove_from_queue(
        client_id=client_id,
        user_id=current_user.id,
        user_email=current_user.email
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    
    return result


@router.get("/audit-log")
async def get_audit_log(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None, description="Filter by action type"),
    current_user: AuthUser = Depends(require_lodgeit_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Get LodgeIT audit log entries.
    
    **Permissions:** accountant, admin
    """
    from sqlalchemy import text
    
    # Build query
    query_parts = ["SELECT * FROM lodgeit_audit_log"]
    params = {"limit": limit, "offset": offset}
    
    if action:
        query_parts.append("WHERE action = :action")
        params["action"] = action
    
    query_parts.append("ORDER BY timestamp DESC LIMIT :limit OFFSET :offset")
    
    query = text(" ".join(query_parts))
    result = await db.execute(query, params)
    rows = result.fetchall()
    
    return [
        {
            "id": row.id,
            "user_id": row.user_id,
            "user_email": row.user_email,
            "action": row.action,
            "client_ids": row.client_ids,
            "success": row.success,
            "error_message": row.error_message,
            "details": row.details,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None
        }
        for row in rows
    ]
