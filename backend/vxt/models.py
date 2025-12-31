"""
VXT Phone System Integration - Database Models

Models for:
- VXTCall: Phone call records
- VXTTranscript: Call transcriptions
- VXTRecording: Audio recording references
- WorkpaperCallLink: Call-workpaper associations
- VXTWebhookLog: Webhook audit log
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, List

from sqlalchemy import (
    Column, String, Text, Integer, BigInteger, DateTime, 
    Numeric, Boolean, JSON, ForeignKey
)
from sqlalchemy.orm import relationship

from database.connection import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ==================== VXT CALL TABLE ====================

class VXTCallDB(Base):
    """
    VXT Call Table - Phone call records from VXT system.
    """
    __tablename__ = 'vxt_calls'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    call_id = Column(String(100), unique=True, nullable=False, index=True)
    from_number = Column(String(50), nullable=False, index=True)
    to_number = Column(String(50), nullable=False, index=True)
    direction = Column(String(20), default='inbound')
    timestamp = Column(DateTime(timezone=True), nullable=False)
    duration_seconds = Column(Integer, default=0)
    status = Column(String(30), default='completed')
    matched_client_id = Column(Integer, nullable=True, index=True)
    client_match_confidence = Column(String(20), nullable=True)
    raw_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    
    # Relationships
    transcript = relationship("VXTTranscriptDB", back_populates="call", uselist=False)
    recording = relationship("VXTRecordingDB", back_populates="call", uselist=False)
    workpaper_links = relationship("WorkpaperCallLinkDB", back_populates="call")
    
    __table_args__ = {'extend_existing': True}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "call_id": self.call_id,
            "from_number": self.from_number,
            "to_number": self.to_number,
            "direction": self.direction,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "matched_client_id": self.matched_client_id,
            "client_match_confidence": self.client_match_confidence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
    
    def to_dict_full(self) -> Dict[str, Any]:
        """Include transcript and recording info"""
        data = self.to_dict()
        data["transcript"] = self.transcript.to_dict() if self.transcript else None
        data["recording"] = self.recording.to_dict() if self.recording else None
        data["workpaper_links"] = [link.to_dict() for link in self.workpaper_links] if self.workpaper_links else []
        return data


# ==================== VXT TRANSCRIPT TABLE ====================

class VXTTranscriptDB(Base):
    """
    VXT Transcript Table - Call transcriptions with AI summaries.
    """
    __tablename__ = 'vxt_transcripts'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    call_id = Column(Integer, ForeignKey('vxt_calls.id', ondelete='CASCADE'), nullable=False, index=True)
    transcript_text = Column(Text, nullable=True)
    summary_text = Column(Text, nullable=True)
    language = Column(String(10), default='en')
    confidence_score = Column(Numeric(5, 4), nullable=True)
    word_count = Column(Integer, nullable=True)
    speaker_labels = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    
    # Relationships
    call = relationship("VXTCallDB", back_populates="transcript")
    
    __table_args__ = {'extend_existing': True}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "call_id": self.call_id,
            "transcript_text": self.transcript_text,
            "summary_text": self.summary_text,
            "language": self.language,
            "confidence_score": float(self.confidence_score) if self.confidence_score else None,
            "word_count": self.word_count,
            "speaker_labels": self.speaker_labels,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ==================== VXT RECORDING TABLE ====================

class VXTRecordingDB(Base):
    """
    VXT Recording Table - Audio recording references.
    """
    __tablename__ = 'vxt_recordings'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    call_id = Column(Integer, ForeignKey('vxt_calls.id', ondelete='CASCADE'), nullable=False, index=True)
    recording_url = Column(Text, nullable=False)
    local_storage_path = Column(Text, nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    format = Column(String(20), default='mp3')
    is_downloaded = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    
    # Relationships
    call = relationship("VXTCallDB", back_populates="recording")
    
    __table_args__ = {'extend_existing': True}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "call_id": self.call_id,
            "recording_url": self.recording_url,
            "local_storage_path": self.local_storage_path,
            "file_size_bytes": self.file_size_bytes,
            "duration_seconds": self.duration_seconds,
            "format": self.format,
            "is_downloaded": self.is_downloaded,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ==================== WORKPAPER CALL LINK TABLE ====================

class WorkpaperCallLinkDB(Base):
    """
    Workpaper Call Link Table - Associates calls with workpapers.
    """
    __tablename__ = 'workpapers_call_links'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    call_id = Column(Integer, ForeignKey('vxt_calls.id', ondelete='CASCADE'), nullable=False, index=True)
    workpaper_id = Column(Integer, nullable=False, index=True)
    link_type = Column(String(50), default='auto')
    notes = Column(Text, nullable=True)
    created_by = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    
    # Relationships
    call = relationship("VXTCallDB", back_populates="workpaper_links")
    
    __table_args__ = {'extend_existing': True}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "call_id": self.call_id,
            "workpaper_id": self.workpaper_id,
            "link_type": self.link_type,
            "notes": self.notes,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ==================== VXT WEBHOOK LOG TABLE ====================

class VXTWebhookLogDB(Base):
    """
    VXT Webhook Log Table - Audit trail for webhook events.
    """
    __tablename__ = 'vxt_webhook_log'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    webhook_id = Column(String(100), nullable=True)
    event_type = Column(String(50), nullable=True)
    call_id = Column(String(100), nullable=True, index=True)
    payload = Column(JSON, nullable=True)
    signature_valid = Column(Boolean, nullable=True)
    processed = Column(Boolean, default=False)
    error_message = Column(Text, nullable=True)
    received_at = Column(DateTime(timezone=True), default=utc_now, index=True)
    
    __table_args__ = {'extend_existing': True}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "webhook_id": self.webhook_id,
            "event_type": self.event_type,
            "call_id": self.call_id,
            "signature_valid": self.signature_valid,
            "processed": self.processed,
            "error_message": self.error_message,
            "received_at": self.received_at.isoformat() if self.received_at else None,
        }
