"""
Centralized Audit Logging System for FDC Tax CRM

Tracks all key actions for compliance and traceability:
- Task operations (create, update, delete)
- Document requests (create, upload, dismiss)
- Authentication (login, logout, password change)
- User management (registration, role changes)
- Recurring tasks (triggered, generated)
- Profile changes
- CRM sync operations

Storage: JSON file (can be migrated to database)
"""

import json
import os
import uuid
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any, Union
from pathlib import Path
import logging
from enum import Enum
from pydantic import BaseModel, Field
from contextlib import contextmanager
import threading

logger = logging.getLogger(__name__)

# Storage path
DATA_DIR = Path(__file__).parent.parent / "data"
AUDIT_LOG_FILE = DATA_DIR / "audit_log.jsonl"  # JSON Lines format for append efficiency

# Thread lock for file writes
_write_lock = threading.Lock()


# ==================== ENUMS ====================

class AuditAction(str, Enum):
    """All auditable actions in the system"""
    
    # Authentication
    USER_LOGIN = "user.login"
    USER_LOGIN_FAILED = "user.login_failed"
    USER_LOGOUT = "user.logout"
    USER_REGISTER = "user.register"
    USER_PASSWORD_CHANGE = "user.password_change"
    USER_PASSWORD_RESET = "user.password_reset"
    TOKEN_REFRESH = "token.refresh"
    
    # User Management
    USER_ROLE_CHANGE = "user.role_change"
    USER_UPDATE = "user.update"
    USER_DEACTIVATE = "user.deactivate"
    USER_ACTIVATE = "user.activate"
    
    # Tasks
    TASK_CREATE = "task.create"
    TASK_UPDATE = "task.update"
    TASK_DELETE = "task.delete"
    TASK_COMPLETE = "task.complete"
    TASK_ASSIGN = "task.assign"
    
    # CRM Tasks
    CRM_TASK_CREATE = "crm_task.create"
    CRM_TASK_UPDATE = "crm_task.update"
    CRM_TASK_DELETE = "crm_task.delete"
    
    # Documents
    DOCUMENT_REQUEST_CREATE = "document.request_create"
    DOCUMENT_REQUEST_UPDATE = "document.request_update"
    DOCUMENT_REQUEST_DISMISS = "document.request_dismiss"
    DOCUMENT_REQUEST_DELETE = "document.request_delete"
    DOCUMENT_UPLOAD = "document.upload"
    DOCUMENT_DOWNLOAD = "document.download"
    DOCUMENT_DELETE = "document.delete"
    
    # Profile
    PROFILE_UPDATE = "profile.update"
    PROFILE_VIEW = "profile.view"
    ONBOARDING_UPDATE = "onboarding.update"
    OSCAR_TOGGLE = "oscar.toggle"
    
    # Recurring Tasks
    RECURRING_TEMPLATE_CREATE = "recurring.template_create"
    RECURRING_TEMPLATE_UPDATE = "recurring.template_update"
    RECURRING_TEMPLATE_DELETE = "recurring.template_delete"
    RECURRING_TRIGGER = "recurring.trigger"
    RECURRING_TASK_GENERATED = "recurring.task_generated"
    
    # CRM Sync
    CRM_SYNC_TASKS = "crm.sync_tasks"
    CRM_SYNC_PROFILES = "crm.sync_profiles"
    
    # Luna / Escalation
    LUNA_ESCALATION = "luna.escalation"
    
    # Appointments / Calendly
    APPOINTMENT_BOOKED = "appointment.booked"
    APPOINTMENT_CANCELLED = "appointment.cancelled"
    APPOINTMENT_COMPLETED = "appointment.completed"
    APPOINTMENT_NO_SHOW = "appointment.no_show"
    APPOINTMENT_RESCHEDULED = "appointment.rescheduled"
    
    # Knowledge Base
    KB_ENTRY_CREATE = "kb.entry_create"
    KB_ENTRY_UPDATE = "kb.entry_update"
    KB_ENTRY_DELETE = "kb.entry_delete"
    KB_SEARCH = "kb.search"
    
    # Admin
    ADMIN_ACTION = "admin.action"
    SYSTEM_EVENT = "system.event"


class ResourceType(str, Enum):
    """Resource types for audit logging"""
    USER = "user"
    TASK = "task"
    CRM_TASK = "crm_task"
    DOCUMENT = "document"
    PROFILE = "profile"
    RECURRING_TEMPLATE = "recurring_template"
    KB_ENTRY = "kb_entry"
    AUTH = "auth"
    SYSTEM = "system"


# ==================== MODELS ====================

class AuditLogEntry(BaseModel):
    """Audit log entry model"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_id: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None
    
    class Config:
        extra = "allow"


class AuditLogFilter(BaseModel):
    """Filter for querying audit logs"""
    start_date: Optional[str] = None  # ISO date
    end_date: Optional[str] = None  # ISO date
    user_id: Optional[str] = None
    action: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    success: Optional[bool] = None
    limit: int = 100
    offset: int = 0


class AuditLogStats(BaseModel):
    """Statistics for audit logs"""
    total_entries: int
    entries_today: int
    entries_this_week: int
    by_action: Dict[str, int]
    by_resource_type: Dict[str, int]
    by_user: Dict[str, int]
    recent_errors: int


# ==================== AUDIT LOGGER ====================

class AuditLogger:
    """
    Centralized audit logger for the FDC Tax CRM.
    
    Usage:
        audit = AuditLogger()
        audit.log(
            user_id="uuid",
            action=AuditAction.TASK_CREATE,
            resource_type=ResourceType.TASK,
            resource_id="task-uuid",
            details={"title": "New Task"},
            request=request  # FastAPI Request object
        )
    """
    
    _instance = None
    
    def __new__(cls):
        """Singleton pattern for consistent logging"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.log_file = AUDIT_LOG_FILE
        self._ensure_file_exists()
        self._initialized = True
    
    def _ensure_file_exists(self):
        """Ensure the data directory and log file exist"""
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_file.exists():
            self.log_file.touch()
    
    def log(
        self,
        action: Union[AuditAction, str],
        resource_type: Union[ResourceType, str],
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request: Optional[Any] = None,  # FastAPI Request
        success: bool = True,
        error_message: Optional[str] = None
    ) -> AuditLogEntry:
        """
        Log an audit entry.
        
        Args:
            action: The action being performed
            resource_type: Type of resource affected
            user_id: ID of the user performing the action
            user_email: Email of the user (for display)
            resource_id: ID of the affected resource
            details: Additional details about the action
            ip_address: Client IP address
            user_agent: Client user agent
            request: FastAPI Request object (auto-extracts IP and user agent)
            success: Whether the action succeeded
            error_message: Error message if action failed
        
        Returns:
            The created audit log entry
        """
        # Extract from request if provided
        if request:
            if not ip_address:
                ip_address = self._get_client_ip(request)
            if not user_agent:
                user_agent = request.headers.get("user-agent", "")[:500]
        
        # Convert enums to strings
        action_str = action.value if isinstance(action, AuditAction) else action
        resource_type_str = resource_type.value if isinstance(resource_type, ResourceType) else resource_type
        
        entry = AuditLogEntry(
            user_id=user_id,
            user_email=user_email,
            action=action_str,
            resource_type=resource_type_str,
            resource_id=str(resource_id) if resource_id else None,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            error_message=error_message
        )
        
        # Write to file
        self._write_entry(entry)
        
        # Log to application logger as well
        log_level = logging.INFO if success else logging.WARNING
        logger.log(
            log_level,
            f"AUDIT: {action_str} on {resource_type_str}"
            f"{f'/{resource_id}' if resource_id else ''}"
            f" by {user_email or user_id or 'anonymous'}"
            f"{f' - FAILED: {error_message}' if not success else ''}"
        )
        
        return entry
    
    def _write_entry(self, entry: AuditLogEntry):
        """Write an entry to the log file (thread-safe)"""
        with _write_lock:
            try:
                with open(self.log_file, 'a') as f:
                    f.write(json.dumps(entry.model_dump()) + "\n")
            except Exception as e:
                logger.error(f"Failed to write audit log: {e}")
    
    def _get_client_ip(self, request) -> Optional[str]:
        """Extract client IP from request"""
        try:
            # Check for forwarded headers (proxy/load balancer)
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
            
            real_ip = request.headers.get("x-real-ip")
            if real_ip:
                return real_ip
            
            # Direct connection
            if hasattr(request, 'client') and request.client:
                return request.client.host
        except Exception:
            pass
        return None
    
    def get_logs(
        self,
        filter_params: Optional[AuditLogFilter] = None
    ) -> List[AuditLogEntry]:
        """
        Retrieve audit logs with optional filtering.
        
        Args:
            filter_params: Filter parameters
        
        Returns:
            List of matching audit log entries
        """
        if filter_params is None:
            filter_params = AuditLogFilter()
        
        logs = []
        
        try:
            with open(self.log_file, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            entry_data = json.loads(line)
                            entry = AuditLogEntry(**entry_data)
                            
                            # Apply filters
                            if not self._matches_filter(entry, filter_params):
                                continue
                            
                            logs.append(entry)
                        except (json.JSONDecodeError, Exception) as e:
                            logger.warning(f"Failed to parse audit log entry: {e}")
        except FileNotFoundError:
            return []
        
        # Sort by timestamp descending (most recent first)
        logs.sort(key=lambda x: x.timestamp, reverse=True)
        
        # Apply pagination
        start = filter_params.offset
        end = start + filter_params.limit
        
        return logs[start:end]
    
    def _matches_filter(self, entry: AuditLogEntry, filter_params: AuditLogFilter) -> bool:
        """Check if an entry matches the filter criteria"""
        # Date range filter
        if filter_params.start_date:
            entry_date = entry.timestamp[:10]  # YYYY-MM-DD
            if entry_date < filter_params.start_date:
                return False
        
        if filter_params.end_date:
            entry_date = entry.timestamp[:10]
            if entry_date > filter_params.end_date:
                return False
        
        # User filter
        if filter_params.user_id and entry.user_id != filter_params.user_id:
            return False
        
        # Action filter
        if filter_params.action and entry.action != filter_params.action:
            return False
        
        # Resource type filter
        if filter_params.resource_type and entry.resource_type != filter_params.resource_type:
            return False
        
        # Resource ID filter
        if filter_params.resource_id and entry.resource_id != filter_params.resource_id:
            return False
        
        # Success filter
        if filter_params.success is not None and entry.success != filter_params.success:
            return False
        
        return True
    
    def get_entry(self, entry_id: str) -> Optional[AuditLogEntry]:
        """Get a specific audit log entry by ID"""
        try:
            with open(self.log_file, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            entry_data = json.loads(line)
                            if entry_data.get('id') == entry_id:
                                return AuditLogEntry(**entry_data)
                        except (json.JSONDecodeError, Exception):
                            continue
        except FileNotFoundError:
            pass
        return None
    
    def get_stats(self) -> AuditLogStats:
        """Get statistics about audit logs"""
        today = date.today().isoformat()
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        
        stats = {
            "total_entries": 0,
            "entries_today": 0,
            "entries_this_week": 0,
            "by_action": {},
            "by_resource_type": {},
            "by_user": {},
            "recent_errors": 0
        }
        
        try:
            with open(self.log_file, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            entry = json.loads(line)
                            stats["total_entries"] += 1
                            
                            entry_date = entry.get("timestamp", "")[:10]
                            
                            if entry_date == today:
                                stats["entries_today"] += 1
                            
                            if entry_date >= week_ago:
                                stats["entries_this_week"] += 1
                                
                                if not entry.get("success", True):
                                    stats["recent_errors"] += 1
                            
                            # Count by action
                            action = entry.get("action", "unknown")
                            stats["by_action"][action] = stats["by_action"].get(action, 0) + 1
                            
                            # Count by resource type
                            resource_type = entry.get("resource_type", "unknown")
                            stats["by_resource_type"][resource_type] = stats["by_resource_type"].get(resource_type, 0) + 1
                            
                            # Count by user
                            user = entry.get("user_email") or entry.get("user_id") or "anonymous"
                            stats["by_user"][user] = stats["by_user"].get(user, 0) + 1
                            
                        except (json.JSONDecodeError, Exception):
                            continue
        except FileNotFoundError:
            pass
        
        return AuditLogStats(**stats)
    
    def get_user_activity(self, user_id: str, limit: int = 50) -> List[AuditLogEntry]:
        """Get recent activity for a specific user"""
        return self.get_logs(AuditLogFilter(user_id=user_id, limit=limit))
    
    def get_resource_history(
        self,
        resource_type: str,
        resource_id: str,
        limit: int = 50
    ) -> List[AuditLogEntry]:
        """Get history of actions on a specific resource"""
        return self.get_logs(AuditLogFilter(
            resource_type=resource_type,
            resource_id=resource_id,
            limit=limit
        ))
    
    def get_failed_actions(self, limit: int = 100) -> List[AuditLogEntry]:
        """Get recent failed actions"""
        return self.get_logs(AuditLogFilter(success=False, limit=limit))
    
    def clear_old_logs(self, days_to_keep: int = 90) -> int:
        """
        Clear logs older than specified days.
        Returns count of deleted entries.
        
        WARNING: This is destructive. Use with caution.
        """
        cutoff_date = (date.today() - timedelta(days=days_to_keep)).isoformat()
        kept_entries = []
        deleted_count = 0
        
        with _write_lock:
            try:
                with open(self.log_file, 'r') as f:
                    for line in f:
                        if line.strip():
                            try:
                                entry = json.loads(line)
                                entry_date = entry.get("timestamp", "")[:10]
                                
                                if entry_date >= cutoff_date:
                                    kept_entries.append(line)
                                else:
                                    deleted_count += 1
                            except (json.JSONDecodeError, Exception):
                                kept_entries.append(line)  # Keep malformed entries
                
                # Rewrite file with kept entries
                with open(self.log_file, 'w') as f:
                    for line in kept_entries:
                        f.write(line if line.endswith('\n') else line + '\n')
                
                logger.info(f"Cleared {deleted_count} old audit log entries")
                
            except Exception as e:
                logger.error(f"Failed to clear old logs: {e}")
        
        return deleted_count


# ==================== CONVENIENCE FUNCTIONS ====================

# Global audit logger instance
_audit_logger = None


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def log_action(
    action: Union[AuditAction, str],
    resource_type: Union[ResourceType, str],
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    request: Optional[Any] = None,
    success: bool = True,
    error_message: Optional[str] = None
) -> AuditLogEntry:
    """
    Convenience function to log an action.
    
    Usage:
        from services.audit import log_action, AuditAction, ResourceType
        
        log_action(
            action=AuditAction.TASK_CREATE,
            resource_type=ResourceType.TASK,
            user_id=current_user.id,
            user_email=current_user.email,
            resource_id=task.id,
            details={"title": task.title},
            request=request
        )
    """
    return get_audit_logger().log(
        action=action,
        resource_type=resource_type,
        user_id=user_id,
        user_email=user_email,
        resource_id=resource_id,
        details=details,
        request=request,
        success=success,
        error_message=error_message
    )


def log_auth_action(
    action: Union[AuditAction, str],
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    request: Optional[Any] = None,
    success: bool = True,
    error_message: Optional[str] = None
) -> AuditLogEntry:
    """Convenience function for authentication-related logging"""
    return log_action(
        action=action,
        resource_type=ResourceType.AUTH,
        user_id=user_id,
        user_email=user_email,
        details=details,
        request=request,
        success=success,
        error_message=error_message
    )


def log_task_action(
    action: Union[AuditAction, str],
    task_id: str,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    request: Optional[Any] = None
) -> AuditLogEntry:
    """Convenience function for task-related logging"""
    return log_action(
        action=action,
        resource_type=ResourceType.TASK,
        resource_id=task_id,
        user_id=user_id,
        user_email=user_email,
        details=details,
        request=request
    )


def log_document_action(
    action: Union[AuditAction, str],
    document_id: str,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    request: Optional[Any] = None
) -> AuditLogEntry:
    """Convenience function for document-related logging"""
    return log_action(
        action=action,
        resource_type=ResourceType.DOCUMENT,
        resource_id=document_id,
        user_id=user_id,
        user_email=user_email,
        details=details,
        request=request
    )


# ==================== AVAILABLE ACTIONS REFERENCE ====================

AUDIT_ACTIONS = [action.value for action in AuditAction]
RESOURCE_TYPES = [rt.value for rt in ResourceType]
