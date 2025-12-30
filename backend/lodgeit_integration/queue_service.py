"""
LodgeIT Integration - Queue Service

Manages the export queue for LodgeIT.
Handles:
- Adding clients to queue (manual and automatic)
- Retrieving pending exports
- Queue status management
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
import logging

from .models import LodgeITExportQueueDB, ExportQueueStatus, LodgeITAuditLogDB, LodgeITAction

logger = logging.getLogger(__name__)


class QueueService:
    """
    Service class for managing the LodgeIT export queue.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_pending_exports(self) -> List[Dict[str, Any]]:
        """
        Get all clients pending export.
        
        Returns:
            List of queue entries with client details
        """
        query = text("""
            SELECT 
                q.id,
                q.client_id,
                q.status,
                q.trigger_reason,
                q.created_at,
                q.updated_at,
                q.last_exported_at,
                c.name as client_name,
                c.email as client_email,
                c.business_name
            FROM lodgeit_export_queue q
            LEFT JOIN crm_clients c ON c.id = q.client_id
            WHERE q.status = 'pending'
            ORDER BY q.created_at ASC
        """)
        
        result = await self.db.execute(query)
        rows = result.fetchall()
        
        return [
            {
                "id": row.id,
                "client_id": row.client_id,
                "status": row.status,
                "trigger_reason": row.trigger_reason,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "last_exported_at": row.last_exported_at.isoformat() if row.last_exported_at else None,
                "client_name": row.client_name,
                "client_email": row.client_email,
                "business_name": row.business_name,
            }
            for row in rows
        ]
    
    async def add_to_queue(
        self,
        client_id: int,
        trigger_reason: str = "manual",
        user_id: Optional[str] = None,
        user_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Add a client to the export queue.
        
        Args:
            client_id: Client ID to add
            trigger_reason: Why the client was added (manual, onboarding, address_change)
            user_id: User performing the action (for audit)
            user_email: User email (for audit)
        
        Returns:
            Result dictionary
        """
        # Check if client exists
        client_check = await self.db.execute(
            text("SELECT id, name FROM crm_clients WHERE id = :id"),
            {"id": client_id}
        )
        client = client_check.fetchone()
        
        if not client:
            return {
                "success": False,
                "error": f"Client {client_id} not found"
            }
        
        # Check if already in queue with pending status
        existing_check = await self.db.execute(
            text("""
                SELECT id FROM lodgeit_export_queue 
                WHERE client_id = :client_id AND status = 'pending'
            """),
            {"client_id": client_id}
        )
        existing = existing_check.fetchone()
        
        if existing:
            return {
                "success": True,
                "message": "Client already in queue",
                "queue_id": existing.id,
                "client_id": client_id
            }
        
        # Add to queue
        insert_query = text("""
            INSERT INTO lodgeit_export_queue (client_id, status, trigger_reason, created_at, updated_at)
            VALUES (:client_id, 'pending', :trigger_reason, :now, :now)
            RETURNING id
        """)
        
        result = await self.db.execute(insert_query, {
            "client_id": client_id,
            "trigger_reason": trigger_reason,
            "now": datetime.now(timezone.utc)
        })
        row = result.fetchone()
        queue_id = row.id if row else None
        
        # Create audit log if user provided
        if user_id:
            audit_log = LodgeITAuditLogDB(
                user_id=user_id,
                user_email=user_email,
                action=LodgeITAction.QUEUE_ADD.value,
                client_ids=[client_id],
                success=True,
                details={"trigger_reason": trigger_reason}
            )
            self.db.add(audit_log)
        
        await self.db.commit()
        
        logger.info(f"Added client {client_id} to LodgeIT export queue (reason: {trigger_reason})")
        
        return {
            "success": True,
            "message": "Client added to queue",
            "queue_id": queue_id,
            "client_id": client_id,
            "client_name": client.name
        }
    
    async def remove_from_queue(
        self,
        client_id: int,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Remove a client from the export queue.
        """
        delete_query = text("""
            DELETE FROM lodgeit_export_queue 
            WHERE client_id = :client_id AND status = 'pending'
            RETURNING id
        """)
        
        result = await self.db.execute(delete_query, {"client_id": client_id})
        deleted = result.fetchone()
        
        if not deleted:
            return {
                "success": False,
                "error": "Client not found in queue or already processed"
            }
        
        # Create audit log if user provided
        if user_id:
            audit_log = LodgeITAuditLogDB(
                user_id=user_id,
                user_email=user_email,
                action=LodgeITAction.QUEUE_REMOVE.value,
                client_ids=[client_id],
                success=True
            )
            self.db.add(audit_log)
        
        await self.db.commit()
        
        return {
            "success": True,
            "message": "Client removed from queue",
            "client_id": client_id
        }
    
    async def get_queue_stats(self) -> Dict[str, int]:
        """
        Get queue statistics.
        """
        query = text("""
            SELECT 
                status,
                COUNT(*) as count
            FROM lodgeit_export_queue
            GROUP BY status
        """)
        
        result = await self.db.execute(query)
        rows = result.fetchall()
        
        stats = {
            "pending": 0,
            "exported": 0,
            "failed": 0,
            "total": 0
        }
        
        for row in rows:
            stats[row.status] = row.count
            stats["total"] += row.count
        
        return stats


# ==================== TRIGGER FUNCTIONS ====================

async def trigger_onboarding_complete(db: AsyncSession, client_id: int):
    """
    Trigger: Called when a client completes onboarding.
    Adds the client to the export queue.
    """
    service = QueueService(db)
    await service.add_to_queue(client_id, trigger_reason="onboarding_complete")


async def trigger_address_change(db: AsyncSession, client_id: int):
    """
    Trigger: Called when a client's address changes.
    Adds the client to the export queue.
    """
    service = QueueService(db)
    await service.add_to_queue(client_id, trigger_reason="address_change")
