"""
FDC Core Workpaper Platform - Query Engine

Structured communication engine between admin and client.
Supports query creation, messaging, status lifecycle, and task bundling.
"""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import logging

from services.workpaper.models import (
    Query, QueryMessage, Task, QueryStatus, TaskType, TaskStatus,
    SenderType, QueryType, CreateQueryRequest, SendQueryRequest,
    AddMessageRequest, RespondToQueryRequest
)
from services.workpaper.storage import (
    query_storage, message_storage, task_storage,
    job_storage, module_storage
)
from services.audit import log_action, AuditAction, ResourceType

logger = logging.getLogger(__name__)


# ==================== QUERY STATUS TRANSITIONS ====================

VALID_TRANSITIONS = {
    QueryStatus.DRAFT.value: [QueryStatus.SENT_TO_CLIENT.value],
    QueryStatus.SENT_TO_CLIENT.value: [QueryStatus.AWAITING_CLIENT.value, QueryStatus.RESOLVED.value],
    QueryStatus.AWAITING_CLIENT.value: [QueryStatus.CLIENT_RESPONDED.value, QueryStatus.RESOLVED.value],
    QueryStatus.CLIENT_RESPONDED.value: [QueryStatus.AWAITING_CLIENT.value, QueryStatus.RESOLVED.value],
    QueryStatus.RESOLVED.value: [QueryStatus.CLOSED.value, QueryStatus.AWAITING_CLIENT.value],
    QueryStatus.CLOSED.value: [],  # Terminal state
}


def can_transition(current: str, target: str) -> bool:
    """Check if a status transition is valid"""
    return target in VALID_TRANSITIONS.get(current, [])


# ==================== QUERY ENGINE ====================

class QueryEngine:
    """
    Manages queries between admin and client.
    """
    
    def __init__(self):
        pass
    
    # ==================== CREATE ====================
    
    def create_query(
        self,
        request: CreateQueryRequest,
        admin_id: str,
        admin_email: Optional[str] = None
    ) -> Query:
        """Create a new query in DRAFT status"""
        query = Query(
            client_id=request.client_id,
            job_id=request.job_id,
            module_instance_id=request.module_instance_id,
            transaction_id=request.transaction_id,
            title=request.title,
            query_type=request.query_type,
            request_config=request.request_config or {},
            status=QueryStatus.DRAFT.value,
            created_by_admin_id=admin_id,
            created_by_admin_email=admin_email,
        )
        
        query = query_storage.create(query)
        
        # Add initial message if provided
        if request.initial_message:
            self.add_message(
                query.id,
                AddMessageRequest(message_text=request.initial_message),
                sender_type=SenderType.ADMIN.value,
                sender_id=admin_id,
                sender_email=admin_email
            )
        
        # Audit log
        log_action(
            action=AuditAction.WORKPAPER_QUERY_CREATE,
            resource_type=ResourceType.WORKPAPER_QUERY,
            resource_id=query.id,
            user_id=admin_id,
            user_email=admin_email,
            details={
                "job_id": request.job_id,
                "module_instance_id": request.module_instance_id,
                "query_type": request.query_type,
                "title": request.title,
            }
        )
        
        logger.info(f"Query created: {query.id} for job {request.job_id}")
        return query
    
    # ==================== SEND ====================
    
    def send_query(
        self,
        query_id: str,
        request: Optional[SendQueryRequest] = None,
        admin_id: Optional[str] = None,
        admin_email: Optional[str] = None
    ) -> Query:
        """Send a query to the client"""
        query = query_storage.get(query_id)
        if not query:
            raise ValueError(f"Query not found: {query_id}")
        
        if query.status != QueryStatus.DRAFT.value:
            raise ValueError(f"Can only send queries in DRAFT status. Current: {query.status}")
        
        # Add message if provided
        if request and request.message:
            self.add_message(
                query_id,
                AddMessageRequest(message_text=request.message),
                sender_type=SenderType.ADMIN.value,
                sender_id=admin_id or query.created_by_admin_id,
                sender_email=admin_email or query.created_by_admin_email
            )
        
        # Update status
        query = query_storage.update(query_id, {"status": QueryStatus.SENT_TO_CLIENT.value})
        
        # Update or create task
        self._update_queries_task(query.client_id, query.job_id)
        
        # Audit log
        log_action(
            action=AuditAction.WORKPAPER_QUERY_SEND,
            resource_type=ResourceType.WORKPAPER_QUERY,
            resource_id=query_id,
            user_id=admin_id,
            details={"status": QueryStatus.SENT_TO_CLIENT.value}
        )
        
        logger.info(f"Query sent: {query_id}")
        return query
    
    def send_bulk_queries(
        self,
        query_ids: List[str],
        admin_id: str,
        admin_email: Optional[str] = None
    ) -> List[Query]:
        """Send multiple queries at once"""
        sent_queries = []
        for query_id in query_ids:
            try:
                query = self.send_query(query_id, admin_id=admin_id, admin_email=admin_email)
                sent_queries.append(query)
            except Exception as e:
                logger.error(f"Error sending query {query_id}: {e}")
        return sent_queries
    
    # ==================== MESSAGES ====================
    
    def add_message(
        self,
        query_id: str,
        request: AddMessageRequest,
        sender_type: str,
        sender_id: str,
        sender_email: Optional[str] = None
    ) -> QueryMessage:
        """Add a message to a query"""
        query = query_storage.get(query_id)
        if not query:
            raise ValueError(f"Query not found: {query_id}")
        
        message = QueryMessage(
            query_id=query_id,
            sender_type=sender_type,
            sender_id=sender_id,
            sender_email=sender_email,
            message_text=request.message_text,
            attachment_url=request.attachment_url,
            attachment_name=request.attachment_name,
        )
        
        message = message_storage.create(message)
        
        # Auto-transition status based on sender
        if sender_type == SenderType.CLIENT.value:
            if query.status in [QueryStatus.SENT_TO_CLIENT.value, QueryStatus.AWAITING_CLIENT.value]:
                query_storage.update(query_id, {"status": QueryStatus.CLIENT_RESPONDED.value})
                self._update_queries_task(query.client_id, query.job_id)
        elif sender_type == SenderType.ADMIN.value:
            if query.status == QueryStatus.CLIENT_RESPONDED.value:
                query_storage.update(query_id, {"status": QueryStatus.AWAITING_CLIENT.value})
        
        return message
    
    def get_messages(self, query_id: str) -> List[QueryMessage]:
        """Get all messages for a query"""
        return message_storage.list_by_query(query_id)
    
    # ==================== CLIENT RESPONSE ====================
    
    def client_respond(
        self,
        query_id: str,
        request: RespondToQueryRequest,
        client_id: str,
        client_email: Optional[str] = None
    ) -> Query:
        """Client response to a query"""
        query = query_storage.get(query_id)
        if not query:
            raise ValueError(f"Query not found: {query_id}")
        
        if query.client_id != client_id:
            raise ValueError("Query does not belong to this client")
        
        if query.status not in [QueryStatus.SENT_TO_CLIENT.value, QueryStatus.AWAITING_CLIENT.value]:
            raise ValueError(f"Cannot respond to query in status: {query.status}")
        
        # Add message if provided
        if request.message_text:
            self.add_message(
                query_id,
                AddMessageRequest(
                    message_text=request.message_text,
                    attachment_url=request.attachment_url
                ),
                sender_type=SenderType.CLIENT.value,
                sender_id=client_id,
                sender_email=client_email
            )
        
        # Store response data
        updates = {"status": QueryStatus.CLIENT_RESPONDED.value}
        if request.response_data:
            updates["response_data"] = request.response_data
        
        query = query_storage.update(query_id, updates)
        
        # Update task
        self._update_queries_task(query.client_id, query.job_id)
        
        # Audit log
        log_action(
            action=AuditAction.WORKPAPER_QUERY_RESPOND,
            resource_type=ResourceType.WORKPAPER_QUERY,
            resource_id=query_id,
            user_id=client_id,
            user_email=client_email,
            details={
                "has_response_data": request.response_data is not None,
                "has_attachment": request.attachment_url is not None,
            }
        )
        
        logger.info(f"Client responded to query: {query_id}")
        return query
    
    # ==================== RESOLVE ====================
    
    def resolve_query(
        self,
        query_id: str,
        admin_id: str,
        admin_email: Optional[str] = None,
        resolution_message: Optional[str] = None
    ) -> Query:
        """Mark a query as resolved"""
        query = query_storage.get(query_id)
        if not query:
            raise ValueError(f"Query not found: {query_id}")
        
        if query.status in [QueryStatus.RESOLVED.value, QueryStatus.CLOSED.value]:
            raise ValueError(f"Query already resolved/closed")
        
        # Add resolution message if provided
        if resolution_message:
            self.add_message(
                query_id,
                AddMessageRequest(message_text=resolution_message),
                sender_type=SenderType.ADMIN.value,
                sender_id=admin_id,
                sender_email=admin_email
            )
        
        query = query_storage.update(query_id, {
            "status": QueryStatus.RESOLVED.value,
            "resolved_by_admin_id": admin_id,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        })
        
        # Update task
        self._update_queries_task(query.client_id, query.job_id)
        
        # Audit log
        log_action(
            action=AuditAction.WORKPAPER_QUERY_RESOLVE,
            resource_type=ResourceType.WORKPAPER_QUERY,
            resource_id=query_id,
            user_id=admin_id,
            user_email=admin_email,
            details={"resolved": True}
        )
        
        logger.info(f"Query resolved: {query_id}")
        return query
    
    def close_query(self, query_id: str, admin_id: str) -> Query:
        """Close a resolved query"""
        query = query_storage.get(query_id)
        if not query:
            raise ValueError(f"Query not found: {query_id}")
        
        if query.status != QueryStatus.RESOLVED.value:
            raise ValueError("Can only close resolved queries")
        
        query = query_storage.update(query_id, {"status": QueryStatus.CLOSED.value})
        
        # Update task
        self._update_queries_task(query.client_id, query.job_id)
        
        return query
    
    # ==================== TASK MANAGEMENT ====================
    
    def _update_queries_task(self, client_id: str, job_id: str):
        """Update or create the QUERIES task for a job"""
        open_queries = query_storage.list_open_by_job(job_id)
        open_count = len(open_queries)
        
        task = task_storage.get_queries_task(client_id, job_id)
        
        if open_count > 0:
            # Create or update task
            query_ids = [q.id for q in open_queries]
            
            if task:
                task_storage.update(task.id, {
                    "status": TaskStatus.OPEN.value,
                    "metadata": {"query_count": open_count, "query_ids": query_ids},
                    "title": f"You have {open_count} open {'query' if open_count == 1 else 'queries'}",
                })
            else:
                new_task = Task(
                    client_id=client_id,
                    job_id=job_id,
                    task_type=TaskType.QUERIES.value,
                    status=TaskStatus.OPEN.value,
                    title=f"You have {open_count} open {'query' if open_count == 1 else 'queries'}",
                    metadata={"query_count": open_count, "query_ids": query_ids},
                )
                task_storage.create(new_task)
        else:
            # Close task if no open queries
            if task and task.status != TaskStatus.COMPLETED.value:
                task_storage.update(task.id, {
                    "status": TaskStatus.COMPLETED.value,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "metadata": {"query_count": 0, "query_ids": []},
                })
    
    # ==================== QUERIES ====================
    
    def get_query(self, query_id: str) -> Optional[Query]:
        """Get a query by ID"""
        return query_storage.get(query_id)
    
    def list_queries_by_job(
        self,
        job_id: str,
        status: Optional[str] = None
    ) -> List[Query]:
        """List queries for a job"""
        return query_storage.list_by_job(job_id, status)
    
    def list_queries_by_module(self, module_instance_id: str) -> List[Query]:
        """List queries for a module"""
        return query_storage.list_by_module(module_instance_id)
    
    def list_open_queries(self, job_id: str) -> List[Query]:
        """List open queries for a job"""
        return query_storage.list_open_by_job(job_id)
    
    def get_client_tasks(self, client_id: str, job_id: str) -> List[Task]:
        """Get tasks for a client's job"""
        return task_storage.list_by_job(job_id)
    
    def get_queries_summary(self, job_id: str) -> Dict[str, Any]:
        """Get summary of queries for a job"""
        all_queries = query_storage.list_by_job(job_id)
        
        by_status = {}
        for q in all_queries:
            status = q.status
            by_status[status] = by_status.get(status, 0) + 1
        
        open_queries = [q for q in all_queries if q.status in [
            QueryStatus.SENT_TO_CLIENT.value,
            QueryStatus.AWAITING_CLIENT.value,
            QueryStatus.CLIENT_RESPONDED.value
        ]]
        
        return {
            "total": len(all_queries),
            "open": len(open_queries),
            "by_status": by_status,
            "needs_response": len([q for q in all_queries if q.status == QueryStatus.CLIENT_RESPONDED.value]),
        }


# Singleton instance
query_engine = QueryEngine()
