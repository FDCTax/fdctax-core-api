"""
SMS Schema - Database models placeholder

This module contains database schema definitions for SMS functionality.
These are PLACEHOLDERS ONLY - no migrations should be run in Phase 0.

Tables (Future - Phase 2):
- sms_messages: Stores all inbound/outbound SMS
- sms_templates: Message templates
- sms_audit_log: Audit trail for SMS operations
"""

# =============================================================================
# SQL SCHEMA PLACEHOLDER - DO NOT RUN IN PHASE 0
# =============================================================================
#
# This SQL will be used in Phase 2 when inbound SMS storage is needed.
# Migration script will be created at that time.
#
# -- sms_messages table
# CREATE TABLE IF NOT EXISTS sms_messages (
#     id SERIAL PRIMARY KEY,
#     message_id VARCHAR(100) UNIQUE,  -- Provider message ID
#     direction VARCHAR(20) NOT NULL,   -- inbound, outbound
#     from_number VARCHAR(50) NOT NULL,
#     to_number VARCHAR(50) NOT NULL,
#     body TEXT NOT NULL,
#     status VARCHAR(30) DEFAULT 'pending',
#     provider VARCHAR(30) DEFAULT 'twilio',
#     client_id VARCHAR(36),            -- FK to crm_clients if matched
#     job_id INTEGER,                   -- FK to workpaper_jobs if relevant
#     template_id VARCHAR(50),          -- Template used (if any)
#     metadata JSONB,                   -- Additional data
#     error_message TEXT,               -- Error if failed
#     sent_at TIMESTAMP WITH TIME ZONE,
#     delivered_at TIMESTAMP WITH TIME ZONE,
#     created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
#     updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
# );
#
# CREATE INDEX idx_sms_messages_direction ON sms_messages(direction);
# CREATE INDEX idx_sms_messages_from ON sms_messages(from_number);
# CREATE INDEX idx_sms_messages_to ON sms_messages(to_number);
# CREATE INDEX idx_sms_messages_client ON sms_messages(client_id);
# CREATE INDEX idx_sms_messages_status ON sms_messages(status);
# CREATE INDEX idx_sms_messages_created ON sms_messages(created_at);
#
# -- sms_templates table
# CREATE TABLE IF NOT EXISTS sms_templates (
#     id SERIAL PRIMARY KEY,
#     template_id VARCHAR(50) UNIQUE NOT NULL,
#     name VARCHAR(100) NOT NULL,
#     body TEXT NOT NULL,
#     variables JSONB,                  -- List of required variables
#     category VARCHAR(50),             -- reminder, notification, etc.
#     is_active BOOLEAN DEFAULT TRUE,
#     created_by VARCHAR(36),
#     created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
#     updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
# );
#
# -- sms_audit_log table
# CREATE TABLE IF NOT EXISTS sms_audit_log (
#     id SERIAL PRIMARY KEY,
#     message_id INTEGER REFERENCES sms_messages(id),
#     action VARCHAR(50) NOT NULL,      -- sent, delivered, failed, received
#     user_id VARCHAR(36),
#     details JSONB,
#     timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
# );
#
# =============================================================================

from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


# =============================================================================
# PYDANTIC MODELS FOR API
# =============================================================================

class SMSDirection(str, Enum):
    """Direction of SMS message"""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class SMSStatus(str, Enum):
    """Status of SMS message"""
    PENDING = "pending"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    RECEIVED = "received"


class SendSMSRequest(BaseModel):
    """Request model for sending SMS"""
    to: str = Field(..., description="Recipient phone number (E.164 format preferred)")
    message: str = Field(..., description="Message content", max_length=1600)
    client_id: Optional[str] = Field(None, description="Optional client ID for tracking")
    template_id: Optional[str] = Field(None, description="Optional template ID")
    template_variables: Optional[Dict[str, str]] = Field(None, description="Template variables")


class SendSMSResponse(BaseModel):
    """Response model for SMS send operation"""
    success: bool
    status: str
    message_id: Optional[str] = None
    error: Optional[str] = None


class SMSMessageResponse(BaseModel):
    """Response model for SMS message details"""
    id: int
    message_id: Optional[str]
    direction: SMSDirection
    from_number: str
    to_number: str
    body: str
    status: SMSStatus
    client_id: Optional[str]
    sent_at: Optional[datetime]
    delivered_at: Optional[datetime]
    created_at: datetime


class SMSStatsResponse(BaseModel):
    """Response model for SMS statistics"""
    total_sent: int = 0
    total_received: int = 0
    delivered: int = 0
    failed: int = 0
    pending: int = 0


# =============================================================================
# PLACEHOLDER NOTE
# =============================================================================
# 
# This schema file is part of Phase 0 scaffolding.
# No database tables should be created yet.
# 
# Phase 1: Add outbound SMS storage (optional)
# Phase 2: Add inbound SMS storage and templates
# 
# When ready to implement, create a migration file at:
# /app/backend/migrations/sms_setup.sql
#
# =============================================================================
