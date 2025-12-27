from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
import logging

from database import get_db
from services.documents import (
    DocumentService,
    DocumentRequest,
    DocumentRequestCreate,
    DocumentRequestUpdate,
    DocumentStatus,
    DocumentType,
    DOCUMENT_TYPES,
    AuditLogEntry
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["Documents"])

# Initialize service
document_service = DocumentService()


# ==================== USER ENDPOINTS ====================

@router.get("/user", response_model=List[DocumentRequest])
async def get_user_documents(
    user_id: str = Query(..., description="User ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all document requests for a user.
    Returns pending, uploaded, and dismissed requests.
    """
    try:
        if status:
            requests = document_service.storage.list_requests(
                client_id=user_id,
                status=status
            )
        else:
            requests = document_service.get_user_documents(user_id)
        return requests
    except Exception as e:
        logger.error(f"Error getting user documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user/pending", response_model=List[DocumentRequest])
async def get_pending_documents(
    user_id: str = Query(..., description="User ID"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get only pending document requests for a user.
    These are the documents the user needs to upload.
    """
    try:
        return document_service.get_pending_documents(user_id)
    except Exception as e:
        logger.error(f"Error getting pending documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user/count")
async def get_pending_count(
    user_id: str = Query(..., description="User ID"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get count of pending document requests.
    Useful for notification badges.
    """
    try:
        count = document_service.storage.get_pending_count(user_id)
        return {"user_id": user_id, "pending_count": count}
    except Exception as e:
        logger.error(f"Error getting pending count: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/user/upload", response_model=DocumentRequest)
async def upload_document(
    user_id: str = Form(..., description="User ID"),
    request_id: str = Form(..., description="Document request ID"),
    file: UploadFile = File(..., description="File to upload"),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a document for a pending request.
    
    - File is saved securely with client-specific directory
    - Request status is updated to 'uploaded'
    - Audit log entry is created
    
    Supported formats: PDF, images (jpg, png), documents (doc, docx, xls, xlsx)
    Max file size: 10MB (configurable)
    """
    try:
        # Read file content
        file_content = await file.read()
        
        # Validate file size (10MB max)
        max_size = 10 * 1024 * 1024  # 10MB
        if len(file_content) > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size is {max_size // (1024*1024)}MB"
            )
        
        # Upload document
        result = await document_service.upload_document(
            client_id=user_id,
            request_id=request_id,
            file_content=file_content,
            filename=file.filename or "document",
            content_type=file.content_type or "application/octet-stream"
        )
        
        if not result:
            raise HTTPException(status_code=500, detail="Failed to upload document")
        
        return result
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Error uploading document: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ADMIN ENDPOINTS ====================

@router.get("/admin", response_model=List[DocumentRequest])
async def list_all_documents(
    client_id: Optional[str] = Query(None, description="Filter by client ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    document_type: Optional[str] = Query(None, description="Filter by document type"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db)
):
    """
    List all document requests (admin view).
    Supports filtering by client, status, and document type.
    """
    try:
        return document_service.list_all_requests(
            client_id=client_id,
            status=status,
            document_type=document_type,
            limit=limit,
            offset=offset
        )
    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/{request_id}", response_model=DocumentRequest)
async def get_document_request(
    request_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific document request by ID.
    """
    try:
        request = document_service.storage.get_request(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="Document request not found")
        return request
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting document request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/request", response_model=DocumentRequest)
async def create_document_request(
    request_data: DocumentRequestCreate,
    created_by: str = Query(None, description="Admin user ID creating the request"),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new document request for a client.
    
    Example payload:
    ```json
    {
      "client_id": "user-uuid",
      "title": "2024 Tax Return",
      "description": "Please upload your 2024 tax return for review",
      "document_type": "Tax Return",
      "due_date": "2025-01-15"
    }
    ```
    """
    try:
        return document_service.create_document_request(
            data=request_data,
            created_by=created_by or "admin"
        )
    except Exception as e:
        logger.error(f"Error creating document request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/admin/{request_id}", response_model=DocumentRequest)
async def update_document_request(
    request_id: str,
    request_data: DocumentRequestUpdate,
    updated_by: str = Query(None, description="Admin user ID making the update"),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a document request.
    Can be used to change title, description, due date, or dismiss the request.
    """
    try:
        result = document_service.update_document_request(
            request_id=request_id,
            data=request_data,
            updated_by=updated_by or "admin"
        )
        if not result:
            raise HTTPException(status_code=404, detail="Document request not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating document request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/{request_id}/dismiss", response_model=DocumentRequest)
async def dismiss_document_request(
    request_id: str,
    dismissed_by: str = Query(None, description="Admin user ID dismissing the request"),
    reason: Optional[str] = Query(None, description="Reason for dismissal"),
    db: AsyncSession = Depends(get_db)
):
    """
    Dismiss a document request.
    Use when a document is no longer needed.
    """
    try:
        result = document_service.dismiss_request(
            request_id=request_id,
            dismissed_by=dismissed_by or "admin",
            reason=reason
        )
        if not result:
            raise HTTPException(status_code=404, detail="Document request not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error dismissing document request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/admin/{request_id}")
async def delete_document_request(
    request_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a document request permanently.
    Use with caution - consider dismissing instead.
    """
    try:
        success = document_service.storage.delete_request(request_id)
        if not success:
            raise HTTPException(status_code=404, detail="Document request not found")
        return {"success": True, "message": "Document request deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== UTILITY ENDPOINTS ====================

@router.get("/types")
async def get_document_types():
    """
    Get list of available document types.
    """
    return {"document_types": DOCUMENT_TYPES}


@router.get("/stats")
async def get_document_stats(
    db: AsyncSession = Depends(get_db)
):
    """
    Get document request statistics.
    """
    try:
        return document_service.get_document_stats()
    except Exception as e:
        logger.error(f"Error getting document stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overdue", response_model=List[DocumentRequest])
async def get_overdue_requests(
    db: AsyncSession = Depends(get_db)
):
    """
    Get all overdue pending document requests.
    """
    try:
        return document_service.storage.get_overdue_requests()
    except Exception as e:
        logger.error(f"Error getting overdue requests: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/audit", response_model=List[AuditLogEntry])
async def get_audit_logs(
    request_id: Optional[str] = Query(None, description="Filter by request ID"),
    client_id: Optional[str] = Query(None, description="Filter by client ID"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db)
):
    """
    Get audit logs for document operations.
    
    Action types:
    - request_created
    - request_updated
    - request_dismissed
    - file_uploaded
    - file_downloaded
    - file_deleted
    """
    try:
        return document_service.get_audit_logs(
            request_id=request_id,
            client_id=client_id,
            action=action,
            limit=limit
        )
    except Exception as e:
        logger.error(f"Error getting audit logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))
