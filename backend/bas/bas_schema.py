"""
BAS Schema - Database Schema Definitions

This module contains schema definitions for the BAS module.
Actual database models are in models.py.

PLACEHOLDER SCHEMA DEFINITIONS (for reference):
These schemas document the planned database structure.
Do not run migrations from this file.

Migration files are located at:
/app/backend/migrations/bas_setup.sql
"""

# =============================================================================
# BAS RETURNS SCHEMA (PLACEHOLDER - DO NOT MIGRATE)
# =============================================================================
#
# -- bas_returns (future expansion)
# -- Stores individual BAS returns ready for lodgement
# CREATE TABLE IF NOT EXISTS bas_returns (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     client_id VARCHAR(36) NOT NULL,
#     job_id VARCHAR(36),
#     
#     -- Period
#     period_start DATE NOT NULL,
#     period_end DATE NOT NULL,
#     period_type VARCHAR(20) NOT NULL,  -- monthly, quarterly, annual
#     
#     -- GST Fields
#     gst_collected NUMERIC(14,2) DEFAULT 0,
#     gst_paid NUMERIC(14,2) DEFAULT 0,
#     net_gst NUMERIC(14,2) DEFAULT 0,
#     
#     -- Extended GST Fields
#     g1_total_sales NUMERIC(14,2) DEFAULT 0,
#     g2_export_sales NUMERIC(14,2) DEFAULT 0,
#     g3_gst_free_sales NUMERIC(14,2) DEFAULT 0,
#     g10_capital_purchases NUMERIC(14,2) DEFAULT 0,
#     g11_non_capital_purchases NUMERIC(14,2) DEFAULT 0,
#     
#     -- PAYG
#     payg_instalment NUMERIC(14,2) DEFAULT 0,
#     payg_withheld NUMERIC(14,2) DEFAULT 0,
#     
#     -- Totals
#     total_payable NUMERIC(14,2) DEFAULT 0,
#     
#     -- Status
#     status VARCHAR(20) DEFAULT 'draft',  -- draft, ready, lodged, amended
#     lodged_at TIMESTAMP WITH TIME ZONE,
#     lodgement_reference VARCHAR(100),
#     
#     -- Timestamps
#     created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
#     updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
# );
#
# CREATE INDEX idx_bas_returns_client ON bas_returns(client_id);
# CREATE INDEX idx_bas_returns_period ON bas_returns(period_start, period_end);
# CREATE INDEX idx_bas_returns_status ON bas_returns(status);
#
# =============================================================================

# =============================================================================
# BAS STATEMENTS SCHEMA (IMPLEMENTED)
# =============================================================================
#
# -- bas_statements (implemented in models.py)
# -- Stores BAS snapshots at completion with versioning
# CREATE TABLE IF NOT EXISTS bas_statements (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     client_id VARCHAR(36) NOT NULL,
#     job_id VARCHAR(36),
#     period_from DATE NOT NULL,
#     period_to DATE NOT NULL,
#     g1_total_income NUMERIC(14,2) DEFAULT 0,
#     gst_on_income_1a NUMERIC(14,2) DEFAULT 0,
#     gst_on_expenses_1b NUMERIC(14,2) DEFAULT 0,
#     net_gst NUMERIC(14,2) DEFAULT 0,
#     g2_export_sales NUMERIC(14,2) DEFAULT 0,
#     g3_gst_free_sales NUMERIC(14,2) DEFAULT 0,
#     g10_capital_purchases NUMERIC(14,2) DEFAULT 0,
#     g11_non_capital_purchases NUMERIC(14,2) DEFAULT 0,
#     payg_instalment NUMERIC(14,2) DEFAULT 0,
#     total_payable NUMERIC(14,2) DEFAULT 0,
#     notes TEXT,
#     review_notes TEXT,
#     completed_by VARCHAR(36),
#     completed_by_email VARCHAR(255),
#     completed_at TIMESTAMP WITH TIME ZONE,
#     version INTEGER DEFAULT 1,
#     pdf_url TEXT,
#     pdf_generated_at TIMESTAMP WITH TIME ZONE,
#     status VARCHAR(20) DEFAULT 'draft',
#     created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
#     updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
# );
#
# =============================================================================

# =============================================================================
# BAS CHANGE LOG SCHEMA (IMPLEMENTED)
# =============================================================================
#
# -- bas_change_log (implemented in models.py)
# -- Audit trail for BAS actions
# CREATE TABLE IF NOT EXISTS bas_change_log (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     bas_statement_id UUID,
#     client_id VARCHAR(36) NOT NULL,
#     job_id VARCHAR(36),
#     user_id VARCHAR(36) NOT NULL,
#     user_email VARCHAR(255),
#     user_role VARCHAR(50),
#     action_type VARCHAR(50) NOT NULL,
#     entity_type VARCHAR(50) NOT NULL,
#     entity_id VARCHAR(36),
#     old_value JSONB,
#     new_value JSONB,
#     reason TEXT,
#     timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
# );
#
# CREATE INDEX idx_bas_change_log_client ON bas_change_log(client_id);
# CREATE INDEX idx_bas_change_log_statement ON bas_change_log(bas_statement_id);
# CREATE INDEX idx_bas_change_log_timestamp ON bas_change_log(timestamp);
#
# =============================================================================

# =============================================================================
# FUTURE SCHEMAS (PHASE 2+)
# =============================================================================
#
# -- bas_templates (future)
# -- Pre-configured BAS templates for different business types
# CREATE TABLE IF NOT EXISTS bas_templates (
#     id SERIAL PRIMARY KEY,
#     name VARCHAR(100) NOT NULL,
#     description TEXT,
#     business_type VARCHAR(50),
#     gst_method VARCHAR(20),  -- cash, accrual
#     reporting_frequency VARCHAR(20),  -- monthly, quarterly, annual
#     fields JSONB,
#     is_active BOOLEAN DEFAULT TRUE,
#     created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
# );
#
# -- bas_lodgements (future)
# -- Records of BAS lodgements with ATO
# CREATE TABLE IF NOT EXISTS bas_lodgements (
#     id SERIAL PRIMARY KEY,
#     bas_statement_id UUID NOT NULL,
#     lodgement_type VARCHAR(20),  -- original, amended
#     ato_reference VARCHAR(100),
#     lodged_at TIMESTAMP WITH TIME ZONE,
#     lodged_by VARCHAR(36),
#     response_code VARCHAR(20),
#     response_message TEXT,
#     created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
# );
#
# =============================================================================

from typing import Optional, Dict, Any, List
from datetime import date, datetime
from enum import Enum
from pydantic import BaseModel, Field


# ==================== PYDANTIC SCHEMAS FOR API ====================

class BASPeriodType(str, Enum):
    """BAS reporting period types"""
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class BASStatus(str, Enum):
    """BAS status values"""
    DRAFT = "draft"
    READY = "ready"
    COMPLETED = "completed"
    LODGED = "lodged"
    AMENDED = "amended"


class BASValidateRequest(BaseModel):
    """Request model for BAS validation"""
    client_id: str = Field(..., description="Client ID")
    period_from: date = Field(..., description="Period start date")
    period_to: date = Field(..., description="Period end date")
    transactions: Optional[List[Dict[str, Any]]] = Field(None, description="Transactions to validate")


class BASCalculateRequest(BaseModel):
    """Request model for BAS calculation"""
    client_id: str = Field(..., description="Client ID")
    period_from: date = Field(..., description="Period start date")
    period_to: date = Field(..., description="Period end date")
    gst_method: str = Field("accrual", description="GST accounting method: cash, accrual")


class BASCalculateResponse(BaseModel):
    """Response model for BAS calculation"""
    status: str
    client_id: Optional[str] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    fields: Optional[Dict[str, Any]] = None
    warnings: Optional[List[str]] = None
    error: Optional[str] = None


class BASStatusResponse(BaseModel):
    """Response model for BAS module status"""
    status: str
    module: str
    version: str
    features: Dict[str, bool]


# ==================== PLACEHOLDER NOTE ====================
#
# This schema file is part of Phase 0 scaffolding.
# 
# Existing tables (implemented):
# - bas_statements: BAS snapshots with versioning
# - bas_change_log: Audit trail
#
# Future tables (not implemented):
# - bas_returns: Ready-to-lodge BAS
# - bas_templates: Pre-configured templates
# - bas_lodgements: ATO lodgement records
#
# ==================== END PLACEHOLDER ====================
