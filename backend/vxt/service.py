"""
VXT Phone System Integration - Service Layer

Provides business logic for:
- Webhook processing
- Call management
- Client matching
- Recording streaming
- Workpaper auto-creation
"""

import os
import re
import hmac
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, and_, desc

from .models import (
    VXTCallDB, VXTTranscriptDB, VXTRecordingDB,
    WorkpaperCallLinkDB, VXTWebhookLogDB
)

logger = logging.getLogger(__name__)


# ==================== PHONE NUMBER UTILITIES ====================

def normalize_phone_number(phone: str) -> str:
    """
    Normalize phone number to standard format for matching.
    
    Handles:
    - +61 4xx xxx xxx (Australian mobile)
    - 04xx xxx xxx (Australian mobile without country code)
    - Spaces, hyphens, parentheses
    
    Returns: Normalized format (digits only with country code)
    """
    if not phone:
        return ""
    
    # Remove all non-digit characters except +
    cleaned = re.sub(r'[^\d+]', '', phone)
    
    # Handle Australian numbers
    if cleaned.startswith('+61'):
        return cleaned
    elif cleaned.startswith('61') and len(cleaned) >= 11:
        return '+' + cleaned
    elif cleaned.startswith('04') and len(cleaned) == 10:
        return '+61' + cleaned[1:]
    elif cleaned.startswith('0') and len(cleaned) == 10:
        return '+61' + cleaned[1:]
    
    return cleaned


def phone_numbers_match(phone1: str, phone2: str) -> bool:
    """Check if two phone numbers match after normalization"""
    return normalize_phone_number(phone1) == normalize_phone_number(phone2)


# ==================== WEBHOOK SERVICE ====================

class VXTWebhookService:
    """Service for handling VXT webhooks"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.webhook_secret = os.environ.get('VXT_WEBHOOK_SECRET', '')
    
    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """
        Verify VXT webhook signature.
        
        VXT uses HMAC-SHA256 for webhook signatures.
        """
        if not self.webhook_secret:
            logger.warning("VXT_WEBHOOK_SECRET not configured, skipping signature verification")
            return True
        
        if not signature:
            return False
        
        expected = hmac.new(
            self.webhook_secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        # Handle different signature formats
        if signature.startswith('sha256='):
            signature = signature[7:]
        
        return hmac.compare_digest(expected, signature)
    
    async def process_webhook(
        self,
        event_type: str,
        payload: Dict[str, Any],
        signature_valid: bool
    ) -> Dict[str, Any]:
        """
        Process incoming VXT webhook event.
        
        Supported events:
        - call.completed: New call with recording
        - call.transcribed: Transcript ready
        """
        # Log webhook receipt
        log = VXTWebhookLogDB(
            webhook_id=payload.get('webhook_id'),
            event_type=event_type,
            call_id=payload.get('call_id'),
            payload=payload,
            signature_valid=signature_valid,
            processed=False
        )
        self.db.add(log)
        
        try:
            result = {}
            
            if event_type == 'call.completed':
                result = await self._process_call_completed(payload)
            elif event_type == 'call.transcribed':
                result = await self._process_transcription(payload)
            elif event_type == 'call.recording_ready':
                result = await self._process_recording(payload)
            else:
                logger.info(f"Unhandled event type: {event_type}")
                result = {"status": "ignored", "reason": f"Unhandled event: {event_type}"}
            
            log.processed = True
            await self.db.commit()
            
            return result
            
        except Exception as e:
            log.error_message = str(e)
            await self.db.commit()
            raise
    
    async def _process_call_completed(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process a completed call event"""
        call_id = payload.get('call_id')
        
        # Check if call already exists
        existing = await self.db.execute(
            select(VXTCallDB).where(VXTCallDB.call_id == call_id)
        )
        if existing.scalar_one_or_none():
            logger.info(f"Call {call_id} already exists, updating")
            return {"status": "updated", "call_id": call_id}
        
        # Parse call data
        call = VXTCallDB(
            call_id=call_id,
            from_number=payload.get('from_number', ''),
            to_number=payload.get('to_number', ''),
            direction=payload.get('direction', 'inbound'),
            timestamp=datetime.fromisoformat(payload.get('timestamp', datetime.now(timezone.utc).isoformat())),
            duration_seconds=payload.get('duration_seconds', 0),
            status=payload.get('status', 'completed'),
            raw_payload=payload
        )
        
        # Try to match client
        matched_client = await self._match_client(call.from_number, call.to_number)
        if matched_client:
            call.matched_client_id = matched_client['id']
            call.client_match_confidence = matched_client['confidence']
        
        self.db.add(call)
        await self.db.commit()
        await self.db.refresh(call)
        
        # If recording URL provided, create recording record
        recording_url = payload.get('recording_url')
        if recording_url:
            recording = VXTRecordingDB(
                call_id=call.id,
                recording_url=recording_url,
                duration_seconds=payload.get('duration_seconds')
            )
            self.db.add(recording)
            await self.db.commit()
        
        # Auto-create workpaper if client matched
        if call.matched_client_id:
            await self._auto_create_workpaper(call)
        
        return {
            "status": "created",
            "call_id": call_id,
            "db_id": call.id,
            "matched_client_id": call.matched_client_id
        }
    
    async def _process_transcription(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process transcription event"""
        call_id = payload.get('call_id')
        
        # Find the call
        result = await self.db.execute(
            select(VXTCallDB).where(VXTCallDB.call_id == call_id)
        )
        call = result.scalar_one_or_none()
        
        if not call:
            logger.warning(f"Call {call_id} not found for transcription")
            return {"status": "error", "reason": "Call not found"}
        
        # Check if transcript exists
        existing = await self.db.execute(
            select(VXTTranscriptDB).where(VXTTranscriptDB.call_id == call.id)
        )
        transcript = existing.scalar_one_or_none()
        
        if transcript:
            # Update existing
            transcript.transcript_text = payload.get('transcript_text', transcript.transcript_text)
            transcript.summary_text = payload.get('summary_text', transcript.summary_text)
            transcript.confidence_score = payload.get('confidence_score')
        else:
            # Create new
            transcript = VXTTranscriptDB(
                call_id=call.id,
                transcript_text=payload.get('transcript_text'),
                summary_text=payload.get('summary_text'),
                confidence_score=payload.get('confidence_score'),
                word_count=len(payload.get('transcript_text', '').split()) if payload.get('transcript_text') else 0,
                speaker_labels=payload.get('speaker_labels')
            )
            self.db.add(transcript)
        
        await self.db.commit()
        
        return {
            "status": "transcription_saved",
            "call_id": call_id,
            "has_summary": bool(payload.get('summary_text'))
        }
    
    async def _process_recording(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process recording ready event"""
        call_id = payload.get('call_id')
        
        result = await self.db.execute(
            select(VXTCallDB).where(VXTCallDB.call_id == call_id)
        )
        call = result.scalar_one_or_none()
        
        if not call:
            return {"status": "error", "reason": "Call not found"}
        
        # Check if recording exists
        existing = await self.db.execute(
            select(VXTRecordingDB).where(VXTRecordingDB.call_id == call.id)
        )
        recording = existing.scalar_one_or_none()
        
        if recording:
            recording.recording_url = payload.get('recording_url', recording.recording_url)
            recording.file_size_bytes = payload.get('file_size_bytes')
            recording.duration_seconds = payload.get('duration_seconds')
        else:
            recording = VXTRecordingDB(
                call_id=call.id,
                recording_url=payload.get('recording_url'),
                file_size_bytes=payload.get('file_size_bytes'),
                duration_seconds=payload.get('duration_seconds')
            )
            self.db.add(recording)
        
        await self.db.commit()
        
        return {"status": "recording_saved", "call_id": call_id}
    
    async def _match_client(self, from_number: str, to_number: str) -> Optional[Dict[str, Any]]:
        """
        Match phone number to CRM client.
        
        Returns: {id, confidence} or None
        """
        normalized_from = normalize_phone_number(from_number)
        normalized_to = normalize_phone_number(to_number)
        
        # Search in crm_clients table
        query = text("""
            SELECT id, name, phone, mobile
            FROM crm_clients
            WHERE phone IS NOT NULL OR mobile IS NOT NULL
            LIMIT 1000
        """)
        
        result = await self.db.execute(query)
        clients = result.fetchall()
        
        for client in clients:
            client_phone = normalize_phone_number(client[2] or '')
            client_mobile = normalize_phone_number(client[3] or '')
            
            # Check for exact match
            if client_phone and (client_phone == normalized_from or client_phone == normalized_to):
                return {"id": client[0], "confidence": "exact", "name": client[1]}
            if client_mobile and (client_mobile == normalized_from or client_mobile == normalized_to):
                return {"id": client[0], "confidence": "exact", "name": client[1]}
        
        return None
    
    async def _auto_create_workpaper(self, call: VXTCallDB):
        """Auto-create workpaper for matched call"""
        # This is a placeholder - actual implementation depends on workpaper system
        # For now, just log that we would create a workpaper
        logger.info(f"Would create workpaper for call {call.call_id} (client {call.matched_client_id})")


# ==================== CALL SERVICE ====================

class VXTCallService:
    """Service for managing VXT calls"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_calls(
        self,
        client_id: Optional[int] = None,
        direction: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get calls with filters"""
        query = select(VXTCallDB)
        
        if client_id:
            query = query.where(VXTCallDB.matched_client_id == client_id)
        if direction:
            query = query.where(VXTCallDB.direction == direction)
        if from_date:
            query = query.where(VXTCallDB.timestamp >= from_date)
        if to_date:
            query = query.where(VXTCallDB.timestamp <= to_date)
        
        query = query.order_by(desc(VXTCallDB.timestamp))
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        calls = result.scalars().all()
        
        return [call.to_dict() for call in calls]
    
    async def get_call(self, call_id: int) -> Optional[Dict[str, Any]]:
        """Get a single call with transcript and recording"""
        result = await self.db.execute(
            select(VXTCallDB).where(VXTCallDB.id == call_id)
        )
        call = result.scalar_one_or_none()
        
        if not call:
            return None
        
        # Load relationships
        call_dict = call.to_dict()
        
        # Get transcript
        transcript_result = await self.db.execute(
            select(VXTTranscriptDB).where(VXTTranscriptDB.call_id == call_id)
        )
        transcript = transcript_result.scalar_one_or_none()
        call_dict["transcript"] = transcript.to_dict() if transcript else None
        
        # Get recording
        recording_result = await self.db.execute(
            select(VXTRecordingDB).where(VXTRecordingDB.call_id == call_id)
        )
        recording = recording_result.scalar_one_or_none()
        call_dict["recording"] = recording.to_dict() if recording else None
        
        # Get workpaper links
        links_result = await self.db.execute(
            select(WorkpaperCallLinkDB).where(WorkpaperCallLinkDB.call_id == call_id)
        )
        links = links_result.scalars().all()
        call_dict["workpaper_links"] = [link.to_dict() for link in links]
        
        return call_dict
    
    async def get_call_by_vxt_id(self, vxt_call_id: str) -> Optional[Dict[str, Any]]:
        """Get call by VXT call ID"""
        result = await self.db.execute(
            select(VXTCallDB).where(VXTCallDB.call_id == vxt_call_id)
        )
        call = result.scalar_one_or_none()
        
        if call:
            return await self.get_call(call.id)
        return None
    
    async def get_recording(self, call_id: int) -> Optional[Dict[str, Any]]:
        """Get recording info for streaming"""
        result = await self.db.execute(
            select(VXTRecordingDB).where(VXTRecordingDB.call_id == call_id)
        )
        recording = result.scalar_one_or_none()
        
        if recording:
            return recording.to_dict()
        return None
    
    async def link_to_workpaper(
        self,
        call_id: int,
        workpaper_id: int,
        user_id: str,
        link_type: str = "manual",
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Link a call to a workpaper"""
        # Check if link exists
        existing = await self.db.execute(
            select(WorkpaperCallLinkDB).where(and_(
                WorkpaperCallLinkDB.call_id == call_id,
                WorkpaperCallLinkDB.workpaper_id == workpaper_id
            ))
        )
        
        if existing.scalar_one_or_none():
            return {"status": "exists", "message": "Link already exists"}
        
        link = WorkpaperCallLinkDB(
            call_id=call_id,
            workpaper_id=workpaper_id,
            link_type=link_type,
            notes=notes,
            created_by=user_id
        )
        
        self.db.add(link)
        await self.db.commit()
        await self.db.refresh(link)
        
        return {
            "status": "created",
            "link": link.to_dict()
        }
