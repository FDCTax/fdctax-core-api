"""
Email Schema - Database Schema Definitions

This module contains database schema definitions for email functionality.
These are PLACEHOLDERS ONLY - no migrations should be run in Phase 0.

Tables (Future - Phase 2):
- email_logs: Stores all sent emails for audit trail
- email_templates: Reusable email templates
- email_queue: Queue for scheduled/bulk emails
"""

# =============================================================================
# SQL SCHEMA PLACEHOLDER - DO NOT RUN IN PHASE 0
# =============================================================================
#
# This SQL will be used in Phase 2 when email logging is needed.
# Migration script will be created at that time.
#
# -- email_logs table
# CREATE TABLE IF NOT EXISTS email_logs (
#     id SERIAL PRIMARY KEY,
#     message_id VARCHAR(100) UNIQUE,     -- Provider message ID
#     to_address VARCHAR(255) NOT NULL,
#     from_address VARCHAR(255) NOT NULL,
#     reply_to VARCHAR(255),
#     cc TEXT,                             -- Comma-separated addresses
#     bcc TEXT,                            -- Comma-separated addresses
#     subject VARCHAR(500) NOT NULL,
#     body TEXT NOT NULL,
#     body_type VARCHAR(10) DEFAULT 'html', -- html, text
#     provider VARCHAR(30) DEFAULT 'resend',
#     provider_message_id VARCHAR(100),
#     status VARCHAR(30) DEFAULT 'pending', -- pending, sent, delivered, failed, bounced
#     error_message TEXT,
#     client_id VARCHAR(36),               -- FK to crm_clients if applicable
#     job_id VARCHAR(36),                  -- FK to workpaper_jobs if applicable
#     message_type VARCHAR(50),            -- notification, reminder, document, etc.
#     template_id VARCHAR(50),             -- Template used (if any)
#     metadata JSONB,                      -- Additional tracking data
#     sent_at TIMESTAMP WITH TIME ZONE,
#     delivered_at TIMESTAMP WITH TIME ZONE,
#     opened_at TIMESTAMP WITH TIME ZONE,  -- If tracking enabled
#     clicked_at TIMESTAMP WITH TIME ZONE, -- If tracking enabled
#     created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
#     updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
# );
#
# CREATE INDEX idx_email_logs_to ON email_logs(to_address);
# CREATE INDEX idx_email_logs_client ON email_logs(client_id);
# CREATE INDEX idx_email_logs_status ON email_logs(status);
# CREATE INDEX idx_email_logs_created ON email_logs(created_at);
# CREATE INDEX idx_email_logs_type ON email_logs(message_type);
#
# -- email_templates table
# CREATE TABLE IF NOT EXISTS email_templates (
#     id SERIAL PRIMARY KEY,
#     template_id VARCHAR(50) UNIQUE NOT NULL,
#     name VARCHAR(100) NOT NULL,
#     subject VARCHAR(500) NOT NULL,
#     body TEXT NOT NULL,
#     body_type VARCHAR(10) DEFAULT 'html',
#     variables JSONB,                     -- List of required variables
#     category VARCHAR(50),                -- reminder, notification, etc.
#     is_active BOOLEAN DEFAULT TRUE,
#     created_by VARCHAR(36),
#     created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
#     updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
# );
#
# -- email_queue table (for scheduled/bulk sending)
# CREATE TABLE IF NOT EXISTS email_queue (
#     id SERIAL PRIMARY KEY,
#     to_address VARCHAR(255) NOT NULL,
#     subject VARCHAR(500) NOT NULL,
#     body TEXT NOT NULL,
#     template_id VARCHAR(50),
#     variables JSONB,
#     scheduled_at TIMESTAMP WITH TIME ZONE,
#     priority INTEGER DEFAULT 5,          -- 1=highest, 10=lowest
#     attempts INTEGER DEFAULT 0,
#     max_attempts INTEGER DEFAULT 3,
#     status VARCHAR(30) DEFAULT 'queued', -- queued, processing, sent, failed
#     error_message TEXT,
#     client_id VARCHAR(36),
#     created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
# );
#
# CREATE INDEX idx_email_queue_status ON email_queue(status);
# CREATE INDEX idx_email_queue_scheduled ON email_queue(scheduled_at);
#
# =============================================================================

from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, EmailStr


# =============================================================================
# PYDANTIC MODELS FOR API
# =============================================================================

class EmailStatus(str, Enum):
    """Status of email message"""
    PENDING = "pending"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"
    OPENED = "opened"


class EmailMessageType(str, Enum):
    """Types of email messages"""
    NOTIFICATION = "notification"
    REMINDER = "reminder"
    DOCUMENT = "document"
    INVOICE = "invoice"
    WELCOME = "welcome"
    VERIFICATION = "verification"
    MARKETING = "marketing"
    CUSTOM = "custom"


class SendEmailRequest(BaseModel):
    """Request model for sending email"""
    to: str = Field(..., description="Recipient email address")
    subject: str = Field(..., description="Email subject", max_length=500)
    body: str = Field(..., description="Email body (HTML)")
    reply_to: Optional[str] = Field(None, description="Reply-to address")
    cc: Optional[List[str]] = Field(None, description="CC recipients")
    bcc: Optional[List[str]] = Field(None, description="BCC recipients")
    client_id: Optional[str] = Field(None, description="Client ID for tracking")
    template_id: Optional[str] = Field(None, description="Template ID if using template")
    template_variables: Optional[Dict[str, str]] = Field(None, description="Template variables")
    message_type: Optional[EmailMessageType] = Field(EmailMessageType.CUSTOM, description="Message type")


class SendEmailResponse(BaseModel):
    """Response model for email send operation"""
    success: bool
    status: str
    message_id: Optional[str] = None
    error: Optional[str] = None


class ValidateEmailRequest(BaseModel):
    """Request model for email validation"""
    email: str = Field(..., description="Email address to validate")


class ValidateEmailResponse(BaseModel):
    """Response model for email validation"""
    valid: bool
    email: str
    error: Optional[str] = None


class EmailLogResponse(BaseModel):
    """Response model for email log entry"""
    id: int
    message_id: Optional[str]
    to_address: str
    subject: str
    status: EmailStatus
    client_id: Optional[str]
    sent_at: Optional[datetime]
    created_at: datetime


class EmailStatsResponse(BaseModel):
    """Response model for email statistics"""
    total_sent: int = 0
    delivered: int = 0
    failed: int = 0
    bounced: int = 0
    opened: int = 0
    pending: int = 0


# =============================================================================
# PLACEHOLDER NOTE
# =============================================================================
# 
# This schema file is part of Phase 0 scaffolding.
# No database tables should be created yet.
# 
# Phase 1: Add basic email logging (optional)
# Phase 2: Add templates and queue tables
# 
# When ready to implement, create a migration file at:
# /app/backend/migrations/email_setup.sql
#
# =============================================================================
