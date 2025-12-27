"""
Document Upload Request System for FDC Tax CRM

Allows FDC Tax to request documents from clients and receive uploads via MyFDC.

Features:
- Document request management
- Secure file uploads (local storage, S3-ready)
- Audit logging for all operations (integrated with centralized audit service)
- Document type categorization

Since sandbox DB has restricted permissions, this implementation uses:
1. A JSON file for document requests (can be migrated to DB later)
2. Local file storage (can be migrated to S3 later)
"""

import json
import os
import uuid
import shutil
import hashlib
from datetime import datetime, date
from typing import List, Optional, Dict, Any
from pathlib import Path
import logging
from enum import Enum
from pydantic import BaseModel, Field

# Import centralized audit service
from services.audit import (
    log_action as centralized_log_action,
    log_document_action,
    AuditAction as CentralAuditAction,
    ResourceType
)

logger = logging.getLogger(__name__)

# Storage paths
DATA_DIR = Path(__file__).parent.parent / "data"
REQUESTS_FILE = DATA_DIR / "document_requests.json"
AUDIT_LOG_FILE = DATA_DIR / "document_audit.log"
UPLOADS_DIR = DATA_DIR / "uploads"


# ==================== ENUMS ====================

class DocumentStatus(str, Enum):
    pending = "pending"
    uploaded = "uploaded"
    dismissed = "dismissed"
    expired = "expired"


class DocumentType(str, Enum):
    tax_return = "Tax Return"
    bas_statement = "BAS Statement"
    lease_agreement = "Lease Agreement"
    insurance_policy = "Insurance Policy"
    bank_statement = "Bank Statement"
    receipt = "Receipt"
    invoice = "Invoice"
    identity_document = "Identity Document"
    business_registration = "Business Registration"
    vehicle_registration = "Vehicle Registration"
    logbook = "Logbook"
    other = "Other"


class AuditAction(str, Enum):
    request_created = "request_created"
    request_updated = "request_updated"
    request_dismissed = "request_dismissed"
    file_uploaded = "file_uploaded"
    file_downloaded = "file_downloaded"
    file_deleted = "file_deleted"


# ==================== MODELS ====================

class DocumentRequest(BaseModel):
    """Document request model"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_id: str  # User ID (UUID)
    title: str
    description: Optional[str] = None
    document_type: str = DocumentType.other.value
    due_date: Optional[str] = None  # ISO date
    status: str = DocumentStatus.pending.value
    uploaded_file_url: Optional[str] = None
    uploaded_file_name: Optional[str] = None
    uploaded_file_size: Optional[int] = None
    uploaded_at: Optional[str] = None  # ISO datetime
    uploaded_by: Optional[str] = None  # "client" or "admin" or user_id
    notes: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: Optional[str] = None
    created_by: Optional[str] = None  # Admin who created the request


class DocumentRequestCreate(BaseModel):
    """Create a document request"""
    client_id: str
    title: str
    description: Optional[str] = None
    document_type: str = DocumentType.other.value
    due_date: Optional[str] = None
    notes: Optional[str] = None
    created_by: Optional[str] = None


class DocumentRequestUpdate(BaseModel):
    """Update a document request"""
    title: Optional[str] = None
    description: Optional[str] = None
    document_type: Optional[str] = None
    due_date: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class FileUploadResult(BaseModel):
    """Result of a file upload"""
    request_id: str
    file_url: str
    file_name: str
    file_size: int
    content_type: str
    checksum: str
    uploaded_at: str


class AuditLogEntry(BaseModel):
    """Audit log entry for document operations"""
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    action: str
    request_id: Optional[str] = None
    user_id: Optional[str] = None
    client_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    ip_address: Optional[str] = None


# ==================== AUDIT LOGGING ====================

class AuditLogger:
    """Audit logger for document operations"""
    
    def __init__(self, log_file: Path = AUDIT_LOG_FILE):
        self.log_file = log_file
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_file.exists():
            self.log_file.touch()
    
    def log(self, entry: AuditLogEntry):
        """Write an audit log entry"""
        try:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(entry.model_dump()) + "\n")
            logger.info(f"Audit: {entry.action} - {entry.details}")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")
    
    def get_logs(
        self,
        request_id: Optional[str] = None,
        client_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100
    ) -> List[AuditLogEntry]:
        """Retrieve audit logs with optional filters"""
        try:
            logs = []
            with open(self.log_file, 'r') as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)
                        
                        # Apply filters
                        if request_id and entry.get('request_id') != request_id:
                            continue
                        if client_id and entry.get('client_id') != client_id:
                            continue
                        if action and entry.get('action') != action:
                            continue
                        
                        logs.append(AuditLogEntry(**entry))
            
            # Return most recent first, limited
            return list(reversed(logs[-limit:]))
        except Exception as e:
            logger.error(f"Failed to read audit logs: {e}")
            return []


# ==================== FILE STORAGE ====================

class FileStorage:
    """
    File storage handler.
    Uses local storage by default, can be extended for S3.
    """
    
    def __init__(self, uploads_dir: Path = UPLOADS_DIR):
        self.uploads_dir = uploads_dir
        self._ensure_dir_exists()
    
    def _ensure_dir_exists(self):
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_client_dir(self, client_id: str) -> Path:
        """Get the directory for a client's uploads"""
        client_dir = self.uploads_dir / client_id
        client_dir.mkdir(parents=True, exist_ok=True)
        return client_dir
    
    def _generate_safe_filename(self, original_name: str, request_id: str) -> str:
        """Generate a safe, unique filename"""
        # Extract extension
        ext = Path(original_name).suffix.lower()
        # Sanitize original name
        safe_name = "".join(c for c in Path(original_name).stem if c.isalnum() or c in '-_')
        # Create unique filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return f"{request_id}_{timestamp}_{safe_name[:50]}{ext}"
    
    def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate MD5 checksum of a file"""
        hash_md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    async def save_file(
        self,
        client_id: str,
        request_id: str,
        file_content: bytes,
        original_filename: str,
        content_type: str
    ) -> FileUploadResult:
        """Save an uploaded file"""
        client_dir = self._get_client_dir(client_id)
        safe_filename = self._generate_safe_filename(original_filename, request_id)
        file_path = client_dir / safe_filename
        
        # Write file
        with open(file_path, 'wb') as f:
            f.write(file_content)
        
        # Calculate checksum
        checksum = self._calculate_checksum(file_path)
        
        # Generate URL (relative path for local, would be S3 URL in production)
        file_url = f"/uploads/{client_id}/{safe_filename}"
        
        return FileUploadResult(
            request_id=request_id,
            file_url=file_url,
            file_name=safe_filename,
            file_size=len(file_content),
            content_type=content_type,
            checksum=checksum,
            uploaded_at=datetime.now().isoformat()
        )
    
    def get_file_path(self, client_id: str, filename: str) -> Optional[Path]:
        """Get the full path to a file"""
        file_path = self.uploads_dir / client_id / filename
        if file_path.exists():
            return file_path
        return None
    
    def delete_file(self, client_id: str, filename: str) -> bool:
        """Delete a file"""
        file_path = self.get_file_path(client_id, filename)
        if file_path:
            try:
                file_path.unlink()
                return True
            except Exception as e:
                logger.error(f"Failed to delete file: {e}")
        return False
    
    def list_client_files(self, client_id: str) -> List[Dict[str, Any]]:
        """List all files for a client"""
        client_dir = self._get_client_dir(client_id)
        files = []
        
        for file_path in client_dir.iterdir():
            if file_path.is_file():
                stat = file_path.stat()
                files.append({
                    "filename": file_path.name,
                    "size": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "url": f"/uploads/{client_id}/{file_path.name}"
                })
        
        return files


# ==================== DOCUMENT REQUEST STORAGE ====================

class DocumentRequestStorage:
    """Storage for document requests"""
    
    def __init__(self, file_path: Path = REQUESTS_FILE):
        self.file_path = file_path
        self.audit_logger = AuditLogger()
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._save_requests([])
    
    def _load_requests(self) -> List[Dict]:
        try:
            with open(self.file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading requests: {e}")
            return []
    
    def _save_requests(self, requests: List[Dict]):
        with open(self.file_path, 'w') as f:
            json.dump(requests, f, indent=2, default=str)
    
    def list_requests(
        self,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        document_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[DocumentRequest]:
        """List document requests with optional filters"""
        requests = self._load_requests()
        
        if client_id:
            requests = [r for r in requests if r.get('client_id') == client_id]
        
        if status:
            requests = [r for r in requests if r.get('status') == status]
        
        if document_type:
            requests = [r for r in requests if r.get('document_type') == document_type]
        
        # Sort by created_at descending
        requests.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        # Apply pagination
        requests = requests[offset:offset + limit]
        
        return [DocumentRequest(**r) for r in requests]
    
    def get_request(self, request_id: str) -> Optional[DocumentRequest]:
        """Get a specific request by ID"""
        requests = self._load_requests()
        for r in requests:
            if r.get('id') == request_id:
                return DocumentRequest(**r)
        return None
    
    def create_request(
        self,
        data: DocumentRequestCreate,
        created_by: Optional[str] = None
    ) -> DocumentRequest:
        """Create a new document request"""
        requests = self._load_requests()
        
        request = DocumentRequest(
            client_id=data.client_id,
            title=data.title,
            description=data.description,
            document_type=data.document_type,
            due_date=data.due_date,
            notes=data.notes,
            created_by=created_by or data.created_by
        )
        
        requests.append(request.model_dump())
        self._save_requests(requests)
        
        # Local audit log (legacy)
        self.audit_logger.log(AuditLogEntry(
            action=AuditAction.request_created.value,
            request_id=request.id,
            client_id=data.client_id,
            user_id=created_by,
            details={
                "title": data.title,
                "document_type": data.document_type,
                "due_date": data.due_date
            }
        ))
        
        # Centralized audit log
        log_document_action(
            action=CentralAuditAction.DOCUMENT_REQUEST_CREATE,
            document_id=request.id,
            user_id=created_by,
            details={
                "title": data.title,
                "document_type": data.document_type,
                "due_date": data.due_date,
                "client_id": data.client_id
            }
        )
        
        return request
    
    def update_request(
        self,
        request_id: str,
        data: DocumentRequestUpdate,
        updated_by: Optional[str] = None
    ) -> Optional[DocumentRequest]:
        """Update a document request"""
        requests = self._load_requests()
        
        for i, r in enumerate(requests):
            if r.get('id') == request_id:
                update_data = data.model_dump(exclude_none=True)
                update_data['updated_at'] = datetime.now().isoformat()
                
                old_status = r.get('status')
                requests[i].update(update_data)
                self._save_requests(requests)
                
                # Determine action type
                action = AuditAction.request_updated.value
                central_action = CentralAuditAction.DOCUMENT_REQUEST_UPDATE
                if data.status == DocumentStatus.dismissed.value:
                    action = AuditAction.request_dismissed.value
                    central_action = CentralAuditAction.DOCUMENT_REQUEST_DISMISS
                
                # Local audit log (legacy)
                self.audit_logger.log(AuditLogEntry(
                    action=action,
                    request_id=request_id,
                    client_id=r.get('client_id'),
                    user_id=updated_by,
                    details={
                        "changes": update_data,
                        "old_status": old_status
                    }
                ))
                
                # Centralized audit log
                log_document_action(
                    action=central_action,
                    document_id=request_id,
                    user_id=updated_by,
                    details={
                        "changes": update_data,
                        "old_status": old_status,
                        "client_id": r.get('client_id'),
                        "title": r.get('title')
                    }
                )
                
                return DocumentRequest(**requests[i])
        
        return None
    
    def delete_request(self, request_id: str) -> bool:
        """Delete a document request"""
        requests = self._load_requests()
        original_len = len(requests)
        
        requests = [r for r in requests if r.get('id') != request_id]
        
        if len(requests) < original_len:
            self._save_requests(requests)
            return True
        
        return False
    
    def mark_uploaded(
        self,
        request_id: str,
        file_result: FileUploadResult,
        uploaded_by: str
    ) -> Optional[DocumentRequest]:
        """Mark a request as uploaded with file details"""
        requests = self._load_requests()
        
        for i, r in enumerate(requests):
            if r.get('id') == request_id:
                requests[i].update({
                    'status': DocumentStatus.uploaded.value,
                    'uploaded_file_url': file_result.file_url,
                    'uploaded_file_name': file_result.file_name,
                    'uploaded_file_size': file_result.file_size,
                    'uploaded_at': file_result.uploaded_at,
                    'uploaded_by': uploaded_by,
                    'updated_at': datetime.now().isoformat()
                })
                self._save_requests(requests)
                
                # Local audit log (legacy)
                self.audit_logger.log(AuditLogEntry(
                    action=AuditAction.file_uploaded.value,
                    request_id=request_id,
                    client_id=r.get('client_id'),
                    user_id=uploaded_by,
                    details={
                        "file_name": file_result.file_name,
                        "file_size": file_result.file_size,
                        "checksum": file_result.checksum
                    }
                ))
                
                # Centralized audit log
                log_document_action(
                    action=CentralAuditAction.DOCUMENT_UPLOAD,
                    document_id=request_id,
                    user_id=uploaded_by,
                    details={
                        "file_name": file_result.file_name,
                        "file_size": file_result.file_size,
                        "content_type": file_result.content_type,
                        "checksum": file_result.checksum,
                        "client_id": r.get('client_id'),
                        "title": r.get('title')
                    }
                )
                
                return DocumentRequest(**requests[i])
        
        return None
    
    def get_pending_count(self, client_id: str) -> int:
        """Get count of pending document requests for a client"""
        requests = self.list_requests(client_id=client_id, status=DocumentStatus.pending.value)
        return len(requests)
    
    def get_overdue_requests(self) -> List[DocumentRequest]:
        """Get all overdue pending requests"""
        today = date.today().isoformat()
        requests = self._load_requests()
        
        overdue = [
            DocumentRequest(**r) for r in requests
            if r.get('status') == DocumentStatus.pending.value
            and r.get('due_date')
            and r.get('due_date') < today
        ]
        
        return overdue


# ==================== DOCUMENT SERVICE ====================

class DocumentService:
    """
    Service for managing document requests and uploads.
    """
    
    def __init__(self):
        self.storage = DocumentRequestStorage()
        self.file_storage = FileStorage()
        self.audit_logger = AuditLogger()
    
    # Client-facing methods
    
    def get_user_documents(self, client_id: str) -> List[DocumentRequest]:
        """Get all document requests for a user"""
        return self.storage.list_requests(client_id=client_id)
    
    def get_pending_documents(self, client_id: str) -> List[DocumentRequest]:
        """Get pending document requests for a user"""
        return self.storage.list_requests(
            client_id=client_id,
            status=DocumentStatus.pending.value
        )
    
    async def upload_document(
        self,
        client_id: str,
        request_id: str,
        file_content: bytes,
        filename: str,
        content_type: str
    ) -> Optional[DocumentRequest]:
        """Upload a document for a request"""
        # Verify request exists and belongs to client
        request = self.storage.get_request(request_id)
        if not request:
            raise ValueError(f"Document request {request_id} not found")
        
        if request.client_id != client_id:
            raise PermissionError("Document request does not belong to this user")
        
        if request.status != DocumentStatus.pending.value:
            raise ValueError(f"Request is not pending (status: {request.status})")
        
        # Save file
        file_result = await self.file_storage.save_file(
            client_id=client_id,
            request_id=request_id,
            file_content=file_content,
            original_filename=filename,
            content_type=content_type
        )
        
        # Update request
        updated_request = self.storage.mark_uploaded(
            request_id=request_id,
            file_result=file_result,
            uploaded_by="client"
        )
        
        return updated_request
    
    # Admin methods
    
    def create_document_request(
        self,
        data: DocumentRequestCreate,
        created_by: str
    ) -> DocumentRequest:
        """Create a new document request (admin)"""
        return self.storage.create_request(data, created_by=created_by)
    
    def update_document_request(
        self,
        request_id: str,
        data: DocumentRequestUpdate,
        updated_by: str
    ) -> Optional[DocumentRequest]:
        """Update a document request (admin)"""
        return self.storage.update_request(request_id, data, updated_by=updated_by)
    
    def dismiss_request(
        self,
        request_id: str,
        dismissed_by: str,
        reason: Optional[str] = None
    ) -> Optional[DocumentRequest]:
        """Dismiss a document request (admin)"""
        update_data = DocumentRequestUpdate(
            status=DocumentStatus.dismissed.value,
            notes=reason
        )
        return self.storage.update_request(request_id, update_data, updated_by=dismissed_by)
    
    def list_all_requests(
        self,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        document_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[DocumentRequest]:
        """List all document requests (admin)"""
        return self.storage.list_requests(
            client_id=client_id,
            status=status,
            document_type=document_type,
            limit=limit,
            offset=offset
        )
    
    def get_document_stats(self) -> Dict[str, Any]:
        """Get document request statistics"""
        all_requests = self.storage.list_requests(limit=10000)
        
        stats = {
            "total": len(all_requests),
            "pending": len([r for r in all_requests if r.status == DocumentStatus.pending.value]),
            "uploaded": len([r for r in all_requests if r.status == DocumentStatus.uploaded.value]),
            "dismissed": len([r for r in all_requests if r.status == DocumentStatus.dismissed.value]),
            "overdue": len(self.storage.get_overdue_requests()),
            "by_type": {}
        }
        
        for r in all_requests:
            doc_type = r.document_type
            if doc_type not in stats["by_type"]:
                stats["by_type"][doc_type] = 0
            stats["by_type"][doc_type] += 1
        
        return stats
    
    def get_audit_logs(
        self,
        request_id: Optional[str] = None,
        client_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100
    ) -> List[AuditLogEntry]:
        """Get audit logs"""
        return self.audit_logger.get_logs(
            request_id=request_id,
            client_id=client_id,
            action=action,
            limit=limit
        )


# ==================== PREDEFINED DOCUMENT TYPES ====================

DOCUMENT_TYPES = [
    {"value": dt.value, "label": dt.value, "key": dt.name}
    for dt in DocumentType
]
