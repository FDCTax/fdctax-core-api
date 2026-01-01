"""
Webhook Notification Service

Manages webhook registrations and delivers notifications to external services
when MyFDC data is submitted to Core.

Features:
- Webhook registration (URL + events)
- HMAC-SHA256 signature for payload authentication
- Retry queue with exponential backoff
- Dead-letter queue for persistent failures
- Audit logging for all webhook operations

Event Types:
- myfdc.profile.updated
- myfdc.hours.logged
- myfdc.occupancy.logged
- myfdc.diary.created
- myfdc.expense.logged
- myfdc.attendance.logged
"""

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from enum import Enum

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


# ==================== CONSTANTS ====================

class WebhookEventType(str, Enum):
    """Supported webhook event types."""
    PROFILE_UPDATED = "myfdc.profile.updated"
    HOURS_LOGGED = "myfdc.hours.logged"
    OCCUPANCY_LOGGED = "myfdc.occupancy.logged"
    DIARY_CREATED = "myfdc.diary.created"
    EXPENSE_LOGGED = "myfdc.expense.logged"
    ATTENDANCE_LOGGED = "myfdc.attendance.logged"


class DeliveryStatus(str, Enum):
    """Webhook delivery status."""
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class AuditEventType(str, Enum):
    """Audit event types for webhooks."""
    WEBHOOK_REGISTERED = "webhook_registered"
    WEBHOOK_UPDATED = "webhook_updated"
    WEBHOOK_DELETED = "webhook_deleted"
    WEBHOOK_DELIVERED = "webhook_delivered"
    WEBHOOK_FAILED = "webhook_failed"
    WEBHOOK_DEAD_LETTER = "webhook_dead_letter"
    WEBHOOK_RETRY = "webhook_retry"


# Retry configuration
MAX_RETRY_ATTEMPTS = 3
RETRY_DELAYS = [60, 300, 900]  # 1 min, 5 min, 15 min (exponential backoff)
DELIVERY_TIMEOUT = 10  # seconds


# ==================== DATA CLASSES ====================

@dataclass
class WebhookRegistration:
    """Webhook registration record."""
    id: str
    service_name: str
    url: str
    events: List[str]
    is_active: bool
    created_at: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WebhookPayload:
    """Webhook event payload (no sensitive data)."""
    event: str
    client_id: str
    timestamp: str
    data_id: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DeliveryResult:
    """Result of webhook delivery attempt."""
    success: bool
    status_code: Optional[int] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None


# ==================== AUDIT LOGGING ====================

async def log_webhook_audit(
    db: AsyncSession,
    event_type: AuditEventType,
    webhook_id: Optional[str],
    service_name: Optional[str],
    details: Dict[str, Any],
    performed_by: str
):
    """Log webhook audit event."""
    query = text("""
        INSERT INTO public.webhook_audit_log 
        (id, event_type, webhook_id, service_name, details, performed_by, created_at)
        VALUES (:id, :event_type, :webhook_id, :service_name, :details, :performed_by, :created_at)
    """)
    
    # Sanitize details - remove any potentially sensitive data
    safe_details = {k: v for k, v in details.items() 
                   if k not in ['secret_key', 'signature', 'payload']}
    
    await db.execute(query, {
        'id': str(uuid.uuid4()),
        'event_type': event_type.value,
        'webhook_id': webhook_id,
        'service_name': service_name,
        'details': json.dumps(safe_details),
        'performed_by': performed_by,
        'created_at': datetime.now(timezone.utc)
    })
    await db.commit()
    
    logger.info(f"Webhook audit: {event_type.value} for {service_name or 'unknown'}", 
                extra={'webhook_id': webhook_id, 'details': safe_details})


# ==================== WEBHOOK SERVICE ====================

class WebhookService:
    """
    Webhook Notification Service.
    
    Manages webhook registrations and delivers notifications
    when MyFDC data is submitted to Core.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ==================== REGISTRATION ====================
    
    async def register_webhook(
        self,
        service_name: str,
        url: str,
        events: List[str],
        registered_by: str
    ) -> Dict[str, Any]:
        """
        Register a new webhook.
        
        Generates a secret key for HMAC signature validation.
        """
        # Validate events
        valid_events = [e.value for e in WebhookEventType]
        invalid_events = [e for e in events if e not in valid_events]
        if invalid_events:
            raise ValueError(f"Invalid event types: {invalid_events}. Valid types: {valid_events}")
        
        # Generate secret key for signature
        secret_key = secrets.token_hex(32)
        webhook_id = str(uuid.uuid4())
        
        query = text("""
            INSERT INTO public.webhook_registrations
            (id, service_name, url, events, secret_key, is_active, created_at, created_by, updated_at)
            VALUES (:id, :service_name, :url, :events, :secret_key, TRUE, :created_at, :created_by, :created_at)
            RETURNING id
        """)
        
        await self.db.execute(query, {
            'id': webhook_id,
            'service_name': service_name,
            'url': url,
            'events': events,
            'secret_key': secret_key,
            'created_at': datetime.now(timezone.utc),
            'created_by': registered_by
        })
        await self.db.commit()
        
        # Audit log
        await log_webhook_audit(
            self.db, AuditEventType.WEBHOOK_REGISTERED,
            webhook_id, service_name,
            {'url': url, 'events': events},
            registered_by
        )
        
        return {
            'id': webhook_id,
            'service_name': service_name,
            'url': url,
            'events': events,
            'secret_key': secret_key,  # Return once for client to store
            'message': 'Webhook registered. Store the secret_key securely - it will not be shown again.'
        }
    
    async def list_webhooks(self, service_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all webhook registrations."""
        query_parts = ["""
            SELECT id, service_name, url, events, is_active, created_at, created_by
            FROM public.webhook_registrations
            WHERE 1=1
        """]
        params = {}
        
        if service_name:
            query_parts.append("AND service_name = :service_name")
            params['service_name'] = service_name
        
        query_parts.append("ORDER BY created_at DESC")
        
        query = text(" ".join(query_parts))
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        return [
            {
                'id': str(row.id),
                'service_name': row.service_name,
                'url': row.url,
                'events': row.events,
                'is_active': row.is_active,
                'created_at': row.created_at.isoformat() if row.created_at else None,
                'created_by': row.created_by
            }
            for row in rows
        ]
    
    async def get_webhook(self, webhook_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific webhook by ID."""
        query = text("""
            SELECT id, service_name, url, events, is_active, created_at, created_by
            FROM public.webhook_registrations
            WHERE id = :id
        """)
        result = await self.db.execute(query, {'id': webhook_id})
        row = result.fetchone()
        
        if not row:
            return None
        
        return {
            'id': str(row.id),
            'service_name': row.service_name,
            'url': row.url,
            'events': row.events,
            'is_active': row.is_active,
            'created_at': row.created_at.isoformat() if row.created_at else None,
            'created_by': row.created_by
        }
    
    async def delete_webhook(
        self,
        webhook_id: str,
        deleted_by: str
    ) -> bool:
        """Delete a webhook registration."""
        # Get webhook info for audit
        webhook = await self.get_webhook(webhook_id)
        if not webhook:
            return False
        
        query = text("""
            DELETE FROM public.webhook_registrations
            WHERE id = :id
        """)
        await self.db.execute(query, {'id': webhook_id})
        await self.db.commit()
        
        # Audit log
        await log_webhook_audit(
            self.db, AuditEventType.WEBHOOK_DELETED,
            webhook_id, webhook['service_name'],
            {'url': webhook['url']},
            deleted_by
        )
        
        return True
    
    async def update_webhook_status(
        self,
        webhook_id: str,
        is_active: bool,
        updated_by: str
    ) -> bool:
        """Enable or disable a webhook."""
        webhook = await self.get_webhook(webhook_id)
        if not webhook:
            return False
        
        query = text("""
            UPDATE public.webhook_registrations
            SET is_active = :is_active, updated_at = :updated_at
            WHERE id = :id
        """)
        await self.db.execute(query, {
            'id': webhook_id,
            'is_active': is_active,
            'updated_at': datetime.now(timezone.utc)
        })
        await self.db.commit()
        
        # Audit log
        await log_webhook_audit(
            self.db, AuditEventType.WEBHOOK_UPDATED,
            webhook_id, webhook['service_name'],
            {'is_active': is_active},
            updated_by
        )
        
        return True
    
    # ==================== EVENT DISPATCH ====================
    
    async def dispatch_event(
        self,
        event_type: WebhookEventType,
        client_id: str,
        data_id: str
    ):
        """
        Dispatch a webhook event to all registered listeners.
        
        Queues the event for delivery with retry support.
        Does NOT include sensitive data in payload.
        """
        # Find all active webhooks subscribed to this event
        query = text("""
            SELECT id, service_name, url, secret_key
            FROM public.webhook_registrations
            WHERE is_active = TRUE
            AND :event_type = ANY(events)
        """)
        result = await self.db.execute(query, {'event_type': event_type.value})
        webhooks = result.fetchall()
        
        if not webhooks:
            logger.debug(f"No webhooks registered for event {event_type.value}")
            return
        
        # Create payload (no sensitive data)
        payload = WebhookPayload(
            event=event_type.value,
            client_id=client_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data_id=data_id
        )
        
        # Queue delivery for each webhook
        for webhook in webhooks:
            await self._queue_delivery(
                webhook_id=str(webhook.id),
                event_type=event_type.value,
                payload=payload.to_dict()
            )
        
        logger.info(f"Queued {event_type.value} event for {len(webhooks)} webhook(s)")
    
    async def _queue_delivery(
        self,
        webhook_id: str,
        event_type: str,
        payload: Dict[str, Any]
    ):
        """Queue a webhook delivery."""
        query = text("""
            INSERT INTO public.webhook_delivery_queue
            (id, webhook_id, event_type, payload, status, attempts, max_attempts, next_retry_at, created_at)
            VALUES (:id, :webhook_id, :event_type, :payload, 'pending', 0, :max_attempts, :next_retry_at, :created_at)
        """)
        
        await self.db.execute(query, {
            'id': str(uuid.uuid4()),
            'webhook_id': webhook_id,
            'event_type': event_type,
            'payload': json.dumps(payload),
            'max_attempts': MAX_RETRY_ATTEMPTS,
            'next_retry_at': datetime.now(timezone.utc),  # Immediate delivery
            'created_at': datetime.now(timezone.utc)
        })
        await self.db.commit()
    
    # ==================== DELIVERY ====================
    
    async def process_delivery_queue(self, batch_size: int = 10) -> Dict[str, int]:
        """
        Process pending webhook deliveries.
        
        Returns counts of delivered, failed, and dead-lettered items.
        """
        # Get pending deliveries ready for retry
        query = text("""
            SELECT q.id, q.webhook_id, q.event_type, q.payload, q.attempts,
                   w.url, w.secret_key, w.service_name
            FROM public.webhook_delivery_queue q
            JOIN public.webhook_registrations w ON q.webhook_id = w.id
            WHERE q.status = 'pending'
            AND q.next_retry_at <= :now
            AND w.is_active = TRUE
            ORDER BY q.next_retry_at
            LIMIT :limit
        """)
        
        result = await self.db.execute(query, {
            'now': datetime.now(timezone.utc),
            'limit': batch_size
        })
        items = result.fetchall()
        
        stats = {'delivered': 0, 'failed': 0, 'dead_letter': 0}
        
        for item in items:
            delivery_result = await self._deliver_webhook(
                url=item.url,
                payload=json.loads(item.payload) if isinstance(item.payload, str) else item.payload,
                secret_key=item.secret_key,
                event_type=item.event_type
            )
            
            if delivery_result.success:
                await self._mark_delivered(str(item.id), item.webhook_id, item.service_name)
                stats['delivered'] += 1
            else:
                new_attempts = item.attempts + 1
                if new_attempts >= MAX_RETRY_ATTEMPTS:
                    await self._move_to_dead_letter(
                        str(item.id), str(item.webhook_id), item.event_type,
                        item.payload, new_attempts, delivery_result.error,
                        item.service_name
                    )
                    stats['dead_letter'] += 1
                else:
                    await self._schedule_retry(
                        str(item.id), new_attempts, delivery_result.error,
                        item.service_name
                    )
                    stats['failed'] += 1
        
        return stats
    
    async def _deliver_webhook(
        self,
        url: str,
        payload: Dict[str, Any],
        secret_key: str,
        event_type: str
    ) -> DeliveryResult:
        """
        Deliver a webhook to the target URL.
        
        Includes HMAC-SHA256 signature in headers.
        """
        start_time = datetime.now(timezone.utc)
        
        try:
            # Generate signature
            payload_bytes = json.dumps(payload, sort_keys=True).encode('utf-8')
            signature = hmac.new(
                secret_key.encode('utf-8'),
                payload_bytes,
                hashlib.sha256
            ).hexdigest()
            
            headers = {
                'Content-Type': 'application/json',
                'X-Webhook-Signature': f'sha256={signature}',
                'X-Webhook-Event': event_type,
                'X-Webhook-Timestamp': payload.get('timestamp', '')
            }
            
            async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
                response = await client.post(url, json=payload, headers=headers)
                
            duration = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            
            if 200 <= response.status_code < 300:
                return DeliveryResult(
                    success=True,
                    status_code=response.status_code,
                    duration_ms=duration
                )
            else:
                return DeliveryResult(
                    success=False,
                    status_code=response.status_code,
                    error=f"HTTP {response.status_code}: {response.text[:200]}",
                    duration_ms=duration
                )
                
        except httpx.TimeoutException:
            return DeliveryResult(success=False, error="Connection timeout")
        except httpx.ConnectError as e:
            return DeliveryResult(success=False, error=f"Connection failed: {str(e)[:100]}")
        except Exception as e:
            return DeliveryResult(success=False, error=f"Delivery error: {str(e)[:100]}")
    
    async def _mark_delivered(
        self,
        queue_id: str,
        webhook_id: str,
        service_name: str
    ):
        """Mark a delivery as successful."""
        query = text("""
            UPDATE public.webhook_delivery_queue
            SET status = 'delivered', delivered_at = :now, attempts = attempts + 1
            WHERE id = :id
        """)
        await self.db.execute(query, {'id': queue_id, 'now': datetime.now(timezone.utc)})
        await self.db.commit()
        
        # Audit log
        await log_webhook_audit(
            self.db, AuditEventType.WEBHOOK_DELIVERED,
            webhook_id, service_name,
            {'queue_id': queue_id},
            'system'
        )
    
    async def _schedule_retry(
        self,
        queue_id: str,
        attempts: int,
        error: str,
        service_name: str
    ):
        """Schedule a retry with exponential backoff."""
        delay_index = min(attempts - 1, len(RETRY_DELAYS) - 1)
        delay_seconds = RETRY_DELAYS[delay_index]
        next_retry = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        
        query = text("""
            UPDATE public.webhook_delivery_queue
            SET attempts = :attempts, last_error = :error, next_retry_at = :next_retry
            WHERE id = :id
        """)
        await self.db.execute(query, {
            'id': queue_id,
            'attempts': attempts,
            'error': error,
            'next_retry': next_retry
        })
        await self.db.commit()
        
        logger.warning(f"Webhook delivery failed (attempt {attempts}), retry in {delay_seconds}s: {error}")
    
    async def _move_to_dead_letter(
        self,
        queue_id: str,
        webhook_id: str,
        event_type: str,
        payload: Any,
        attempts: int,
        error: str,
        service_name: str
    ):
        """Move failed delivery to dead letter queue."""
        # Insert into dead letter
        query = text("""
            INSERT INTO public.webhook_dead_letter
            (id, original_queue_id, webhook_id, event_type, payload, attempts, last_error, failed_at)
            VALUES (:id, :original_id, :webhook_id, :event_type, :payload, :attempts, :error, :now)
        """)
        await self.db.execute(query, {
            'id': str(uuid.uuid4()),
            'original_id': queue_id,
            'webhook_id': webhook_id,
            'event_type': event_type,
            'payload': json.dumps(payload) if isinstance(payload, dict) else payload,
            'attempts': attempts,
            'error': error,
            'now': datetime.now(timezone.utc)
        })
        
        # Update queue status
        update_query = text("""
            UPDATE public.webhook_delivery_queue
            SET status = 'dead_letter', failed_at = :now, last_error = :error, attempts = :attempts
            WHERE id = :id
        """)
        await self.db.execute(update_query, {
            'id': queue_id,
            'now': datetime.now(timezone.utc),
            'error': error,
            'attempts': attempts
        })
        await self.db.commit()
        
        # Audit log
        await log_webhook_audit(
            self.db, AuditEventType.WEBHOOK_DEAD_LETTER,
            webhook_id, service_name,
            {'queue_id': queue_id, 'attempts': attempts, 'error': error[:100]},
            'system'
        )
        
        logger.error(f"Webhook moved to dead letter after {attempts} attempts: {error}")
    
    # ==================== QUEUE STATS ====================
    
    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get delivery queue statistics."""
        query = text("""
            SELECT 
                status,
                COUNT(*) as count
            FROM public.webhook_delivery_queue
            GROUP BY status
        """)
        result = await self.db.execute(query)
        rows = result.fetchall()
        
        stats = {row.status: row.count for row in rows}
        
        # Dead letter count
        dl_query = text("SELECT COUNT(*) as count FROM public.webhook_dead_letter")
        dl_result = await self.db.execute(dl_query)
        dl_row = dl_result.fetchone()
        stats['dead_letter_total'] = dl_row.count if dl_row else 0
        
        return stats
    
    async def get_dead_letter_items(
        self,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get items from the dead letter queue."""
        query = text("""
            SELECT dl.id, dl.webhook_id, dl.event_type, dl.payload,
                   dl.attempts, dl.last_error, dl.failed_at,
                   w.service_name, w.url
            FROM public.webhook_dead_letter dl
            JOIN public.webhook_registrations w ON dl.webhook_id = w.id
            ORDER BY dl.failed_at DESC
            LIMIT :limit
        """)
        result = await self.db.execute(query, {'limit': limit})
        rows = result.fetchall()
        
        return [
            {
                'id': str(row.id),
                'webhook_id': str(row.webhook_id),
                'service_name': row.service_name,
                'url': row.url,
                'event_type': row.event_type,
                'payload': json.loads(row.payload) if isinstance(row.payload, str) else row.payload,
                'attempts': row.attempts,
                'last_error': row.last_error,
                'failed_at': row.failed_at.isoformat() if row.failed_at else None
            }
            for row in rows
        ]
    
    async def retry_dead_letter(
        self,
        dead_letter_id: str,
        retried_by: str
    ) -> bool:
        """Re-queue a dead letter item for delivery."""
        # Get dead letter item
        query = text("""
            SELECT webhook_id, event_type, payload
            FROM public.webhook_dead_letter
            WHERE id = :id
        """)
        result = await self.db.execute(query, {'id': dead_letter_id})
        row = result.fetchone()
        
        if not row:
            return False
        
        # Re-queue
        await self._queue_delivery(
            webhook_id=str(row.webhook_id),
            event_type=row.event_type,
            payload=json.loads(row.payload) if isinstance(row.payload, str) else row.payload
        )
        
        # Remove from dead letter
        delete_query = text("DELETE FROM public.webhook_dead_letter WHERE id = :id")
        await self.db.execute(delete_query, {'id': dead_letter_id})
        await self.db.commit()
        
        logger.info(f"Dead letter item {dead_letter_id} re-queued by {retried_by}")
        return True


# ==================== HELPER FUNCTION FOR MYFDC INTEGRATION ====================

async def trigger_myfdc_webhook(
    db: AsyncSession,
    event_type: WebhookEventType,
    client_id: str,
    data_id: str
):
    """
    Convenience function to trigger a webhook event from MyFDC intake.
    
    Call this after successfully logging MyFDC data.
    """
    service = WebhookService(db)
    await service.dispatch_event(event_type, client_id, data_id)
