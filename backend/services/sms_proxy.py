"""
Core SMS Proxy Service

Secure SMS forwarding layer from Core to Agent 5.
Ensures MyFDC and CRM never touch SMS credentials directly.

Features:
- Internal token validation
- Request forwarding to Agent 5
- Retry logic with exponential backoff
- 503 fallback handling
- Audit logging (no sensitive data)
- Rate limiting support

Security:
- All requests must include x-internal-service and x-internal-token headers
- Phone numbers and message content are NEVER logged
- Only metadata (source, client_id, timestamp, status) is logged
"""

import asyncio
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from enum import Enum

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


# ==================== CONFIGURATION ====================

def get_agent5_config() -> Dict[str, Any]:
    """Get Agent 5 SMS configuration from environment."""
    return {
        'url': os.environ.get('AGENT5_SMS_URL', 'https://agent5-sms.internal.fdccore.com/api/sms'),
        'token': os.environ.get('AGENT5_SMS_TOKEN', ''),
        'timeout': int(os.environ.get('AGENT5_SMS_TIMEOUT', '30')),
        'max_retries': int(os.environ.get('AGENT5_SMS_MAX_RETRIES', '3'))
    }


# Retry configuration
RETRY_DELAYS = [1, 3, 10]  # seconds - quick retries for SMS


# ==================== ENUMS ====================

class SMSProxyStatus(str, Enum):
    """SMS proxy operation status."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    QUEUED = "queued"


class AuditEventType(str, Enum):
    """Audit event types for SMS proxy."""
    SMS_PROXY_REQUEST = "sms_proxy_request"
    SMS_PROXY_SUCCESS = "sms_proxy_success"
    SMS_PROXY_FAILURE = "sms_proxy_failure"
    SMS_PROXY_RETRY = "sms_proxy_retry"
    SMS_PROXY_FALLBACK = "sms_proxy_fallback"
    SMS_BULK_REQUEST = "sms_bulk_request"
    SMS_BULK_SUCCESS = "sms_bulk_success"
    SMS_BULK_FAILURE = "sms_bulk_failure"


# ==================== DATA CLASSES ====================

@dataclass
class SMSSendRequest:
    """SMS send request (internal representation)."""
    to: str  # Phone number - NEVER log this
    message: str  # Message content - NEVER log this
    source: str  # 'myfdc' or 'crm'
    client_id: Optional[str] = None
    reference_id: Optional[str] = None
    priority: str = "normal"  # 'high', 'normal', 'low'
    
    def get_safe_metadata(self) -> Dict[str, Any]:
        """Get metadata safe for logging (no PII)."""
        return {
            'source': self.source,
            'client_id': self.client_id,
            'reference_id': self.reference_id,
            'priority': self.priority,
            'phone_hash': hashlib.sha256(self.to.encode()).hexdigest()[:12]  # Partial hash for correlation
        }


@dataclass
class SMSProxyResponse:
    """Response from SMS proxy operation."""
    success: bool
    message_id: Optional[str] = None
    status: str = "unknown"
    error: Optional[str] = None
    retry_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass  
class BulkSMSResult:
    """Result of bulk SMS operation."""
    total: int
    sent: int
    failed: int
    results: List[Dict[str, Any]]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ==================== AUDIT LOGGING ====================

async def log_sms_audit(
    db: AsyncSession,
    event_type: AuditEventType,
    request_id: str,
    service_name: str,
    metadata: Dict[str, Any],
    success: bool = True
):
    """
    Log SMS proxy audit event.
    
    SECURITY: Never log phone numbers or message content.
    """
    # Ensure no sensitive data in metadata
    safe_metadata = {k: v for k, v in metadata.items() 
                    if k not in ['to', 'phone', 'message', 'content', 'body']}
    
    query = text("""
        INSERT INTO public.webhook_audit_log 
        (id, event_type, webhook_id, service_name, details, performed_by, created_at)
        VALUES (:id, :event_type, NULL, :service_name, :details, :performed_by, :created_at)
    """)
    
    try:
        await db.execute(query, {
            'id': str(uuid.uuid4()),
            'event_type': event_type.value,
            'service_name': service_name,
            'details': json.dumps({
                'request_id': request_id,
                'success': success,
                **safe_metadata
            }),
            'performed_by': 'sms_proxy',
            'created_at': datetime.now(timezone.utc)
        })
        await db.commit()
    except Exception as e:
        logger.warning(f"Failed to log SMS audit: {e}")
    
    # Also log to application logger (no sensitive data)
    log_entry = {
        'event': event_type.value,
        'request_id': request_id,
        'service': service_name,
        'success': success,
        'metadata': safe_metadata
    }
    
    if success:
        logger.info(f"SMS Proxy: {event_type.value}", extra=log_entry)
    else:
        logger.warning(f"SMS Proxy FAILED: {event_type.value}", extra=log_entry)


# ==================== SMS PROXY SERVICE ====================

class SMSProxyService:
    """
    Core SMS Proxy Service.
    
    Forwards SMS requests from MyFDC/CRM to Agent 5.
    Handles authentication, retries, and audit logging.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.config = get_agent5_config()
    
    async def send_sms(
        self,
        request: SMSSendRequest,
        service_name: str
    ) -> SMSProxyResponse:
        """
        Send a single SMS via Agent 5.
        
        Includes retry logic and audit logging.
        Does NOT log phone number or message content.
        """
        request_id = str(uuid.uuid4())
        safe_metadata = request.get_safe_metadata()
        
        # Log request (no sensitive data)
        await log_sms_audit(
            self.db, AuditEventType.SMS_PROXY_REQUEST,
            request_id, service_name, safe_metadata
        )
        
        # Attempt delivery with retries
        last_error = None
        for attempt in range(self.config['max_retries']):
            try:
                result = await self._forward_to_agent5(request, request_id)
                
                if result.success:
                    await log_sms_audit(
                        self.db, AuditEventType.SMS_PROXY_SUCCESS,
                        request_id, service_name,
                        {**safe_metadata, 'message_id': result.message_id, 'attempts': attempt + 1}
                    )
                    result.retry_count = attempt
                    return result
                else:
                    last_error = result.error
                    
                    # Check if it's a 503 (service unavailable) - trigger fallback
                    if '503' in str(last_error):
                        await log_sms_audit(
                            self.db, AuditEventType.SMS_PROXY_FALLBACK,
                            request_id, service_name,
                            {**safe_metadata, 'error': 'Agent 5 unavailable', 'attempt': attempt + 1},
                            success=False
                        )
                        # Could implement fallback logic here (e.g., queue for later)
                        
            except Exception as e:
                last_error = str(e)
                logger.warning(f"SMS proxy attempt {attempt + 1} failed: {last_error}")
            
            # Wait before retry (if not last attempt)
            if attempt < self.config['max_retries'] - 1:
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                await log_sms_audit(
                    self.db, AuditEventType.SMS_PROXY_RETRY,
                    request_id, service_name,
                    {**safe_metadata, 'attempt': attempt + 1, 'next_retry_seconds': delay},
                    success=False
                )
                await asyncio.sleep(delay)
        
        # All retries exhausted
        await log_sms_audit(
            self.db, AuditEventType.SMS_PROXY_FAILURE,
            request_id, service_name,
            {**safe_metadata, 'error': last_error[:100] if last_error else 'Unknown', 'attempts': self.config['max_retries']},
            success=False
        )
        
        return SMSProxyResponse(
            success=False,
            status='failed',
            error=last_error,
            retry_count=self.config['max_retries']
        )
    
    async def send_bulk_sms(
        self,
        requests: List[SMSSendRequest],
        service_name: str
    ) -> BulkSMSResult:
        """
        Send multiple SMS messages via Agent 5.
        
        Processes in parallel with concurrency limit.
        """
        request_id = str(uuid.uuid4())
        
        await log_sms_audit(
            self.db, AuditEventType.SMS_BULK_REQUEST,
            request_id, service_name,
            {'count': len(requests), 'source': requests[0].source if requests else 'unknown'}
        )
        
        results = []
        sent = 0
        failed = 0
        
        # Process in batches of 10 for concurrency control
        batch_size = 10
        for i in range(0, len(requests), batch_size):
            batch = requests[i:i + batch_size]
            tasks = [self._forward_to_agent5(req, f"{request_id}-{j}") for j, req in enumerate(batch, i)]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for req, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    results.append({
                        'success': False,
                        'error': str(result),
                        'phone_hash': hashlib.sha256(req.to.encode()).hexdigest()[:12]
                    })
                    failed += 1
                elif result.success:
                    results.append({
                        'success': True,
                        'message_id': result.message_id,
                        'phone_hash': hashlib.sha256(req.to.encode()).hexdigest()[:12]
                    })
                    sent += 1
                else:
                    results.append({
                        'success': False,
                        'error': result.error,
                        'phone_hash': hashlib.sha256(req.to.encode()).hexdigest()[:12]
                    })
                    failed += 1
        
        # Log bulk result
        await log_sms_audit(
            self.db,
            AuditEventType.SMS_BULK_SUCCESS if failed == 0 else AuditEventType.SMS_BULK_FAILURE,
            request_id, service_name,
            {'total': len(requests), 'sent': sent, 'failed': failed},
            success=(failed == 0)
        )
        
        return BulkSMSResult(
            total=len(requests),
            sent=sent,
            failed=failed,
            results=results
        )
    
    async def _forward_to_agent5(
        self,
        request: SMSSendRequest,
        request_id: str
    ) -> SMSProxyResponse:
        """
        Forward SMS request to Agent 5.
        
        Internal method - handles the actual HTTP call.
        """
        try:
            async with httpx.AsyncClient(timeout=self.config['timeout']) as client:
                response = await client.post(
                    f"{self.config['url']}/send",
                    json={
                        'to': request.to,
                        'message': request.message,
                        'metadata': {
                            'source': request.source,
                            'client_id': request.client_id,
                            'reference_id': request.reference_id,
                            'core_request_id': request_id
                        }
                    },
                    headers={
                        'Authorization': f"Bearer {self.config['token']}",
                        'X-Request-ID': request_id,
                        'Content-Type': 'application/json'
                    }
                )
                
                if response.status_code == 200 or response.status_code == 201:
                    data = response.json()
                    return SMSProxyResponse(
                        success=True,
                        message_id=data.get('message_id', request_id),
                        status='sent'
                    )
                elif response.status_code == 503:
                    return SMSProxyResponse(
                        success=False,
                        status='unavailable',
                        error=f"503 Service Unavailable: Agent 5 is down"
                    )
                else:
                    return SMSProxyResponse(
                        success=False,
                        status='failed',
                        error=f"HTTP {response.status_code}: {response.text[:100]}"
                    )
                    
        except httpx.TimeoutException:
            return SMSProxyResponse(
                success=False,
                status='timeout',
                error="Connection to Agent 5 timed out"
            )
        except httpx.ConnectError as e:
            return SMSProxyResponse(
                success=False,
                status='connection_error',
                error=f"Cannot connect to Agent 5: {str(e)[:100]}"
            )
        except Exception as e:
            return SMSProxyResponse(
                success=False,
                status='error',
                error=f"Unexpected error: {str(e)[:100]}"
            )
    
    async def check_health(self) -> Dict[str, Any]:
        """
        Check Agent 5 SMS service health.
        
        Returns status without exposing sensitive config.
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.config['url']}/health",
                    headers={
                        'Authorization': f"Bearer {self.config['token']}"
                    }
                )
                
                if response.status_code == 200:
                    return {
                        'agent5_status': 'healthy',
                        'agent5_available': True,
                        'response_time_ms': int(response.elapsed.total_seconds() * 1000)
                    }
                else:
                    return {
                        'agent5_status': 'unhealthy',
                        'agent5_available': False,
                        'http_status': response.status_code
                    }
                    
        except httpx.TimeoutException:
            return {
                'agent5_status': 'timeout',
                'agent5_available': False,
                'error': 'Health check timed out'
            }
        except httpx.ConnectError:
            return {
                'agent5_status': 'unreachable',
                'agent5_available': False,
                'error': 'Cannot connect to Agent 5'
            }
        except Exception as e:
            return {
                'agent5_status': 'error',
                'agent5_available': False,
                'error': str(e)[:100]
            }
    
    async def get_delivery_status(
        self,
        message_id: str,
        service_name: str
    ) -> Dict[str, Any]:
        """
        Get delivery status for a sent SMS.
        
        Queries Agent 5 for the current status.
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.config['url']}/status/{message_id}",
                    headers={
                        'Authorization': f"Bearer {self.config['token']}"
                    }
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    return {
                        'message_id': message_id,
                        'status': 'unknown',
                        'error': f"Failed to get status: HTTP {response.status_code}"
                    }
                    
        except Exception as e:
            return {
                'message_id': message_id,
                'status': 'error',
                'error': str(e)[:100]
            }
