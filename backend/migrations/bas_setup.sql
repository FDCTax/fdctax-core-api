-- ============================================================================
-- BAS Backend Foundations - Database Migration
-- ============================================================================
-- Version: 1.0.0
-- Created: 2025-01-01
-- 
-- This migration creates:
-- 1. bas_statements table - BAS snapshots at completion
-- 2. bas_change_log table - Audit trail for BAS actions
-- ============================================================================

-- ============================================================================
-- SECTION A: CREATE BAS_STATEMENTS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS bas_statements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id VARCHAR(36) NOT NULL,
    job_id VARCHAR(36),
    
    -- Period
    period_from DATE NOT NULL,
    period_to DATE NOT NULL,
    
    -- GST Summary Fields
    g1_total_income NUMERIC(14, 2) DEFAULT 0,
    gst_on_income_1a NUMERIC(14, 2) DEFAULT 0,
    gst_on_expenses_1b NUMERIC(14, 2) DEFAULT 0,
    net_gst NUMERIC(14, 2) DEFAULT 0,
    
    -- PAYG Fields
    payg_instalment NUMERIC(14, 2) DEFAULT 0,
    
    -- Totals
    total_payable NUMERIC(14, 2) DEFAULT 0,
    
    -- Additional BAS fields (for comprehensive reporting)
    g2_export_sales NUMERIC(14, 2) DEFAULT 0,
    g3_gst_free_sales NUMERIC(14, 2) DEFAULT 0,
    g10_capital_purchases NUMERIC(14, 2) DEFAULT 0,
    g11_non_capital_purchases NUMERIC(14, 2) DEFAULT 0,
    
    -- Metadata
    notes TEXT,
    review_notes TEXT,
    
    -- Sign-off fields
    completed_by VARCHAR(36),
    completed_by_email VARCHAR(255),
    completed_at TIMESTAMP WITH TIME ZONE,
    
    -- Versioning
    version INTEGER NOT NULL DEFAULT 1,
    
    -- PDF storage
    pdf_url TEXT,
    pdf_generated_at TIMESTAMP WITH TIME ZONE,
    
    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT bas_status_check CHECK (status IN ('draft', 'completed', 'amended', 'lodged'))
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_bas_statements_client ON bas_statements(client_id);
CREATE INDEX IF NOT EXISTS idx_bas_statements_job ON bas_statements(job_id);
CREATE INDEX IF NOT EXISTS idx_bas_statements_period ON bas_statements(period_from, period_to);
CREATE INDEX IF NOT EXISTS idx_bas_statements_status ON bas_statements(status);
CREATE INDEX IF NOT EXISTS idx_bas_statements_completed_at ON bas_statements(completed_at);
CREATE INDEX IF NOT EXISTS idx_bas_statements_client_period ON bas_statements(client_id, period_from, period_to);

-- Add comments
COMMENT ON TABLE bas_statements IS 'Stores BAS snapshots at the time of completion for history and audit';
COMMENT ON COLUMN bas_statements.version IS 'Increments each time BAS is re-saved for same period';
COMMENT ON COLUMN bas_statements.status IS 'draft=in progress, completed=signed off, amended=corrected, lodged=submitted to ATO';


-- ============================================================================
-- SECTION B: CREATE BAS_CHANGE_LOG TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS bas_change_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- References
    bas_statement_id UUID REFERENCES bas_statements(id) ON DELETE SET NULL,
    client_id VARCHAR(36) NOT NULL,
    job_id VARCHAR(36),
    
    -- User info
    user_id VARCHAR(36) NOT NULL,
    user_email VARCHAR(255),
    user_role VARCHAR(50),
    
    -- Action details
    action_type VARCHAR(50) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id VARCHAR(36),
    
    -- Change data
    old_value JSONB,
    new_value JSONB,
    
    -- Reason/notes
    reason TEXT,
    
    -- Timestamp
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT bas_change_log_action_check CHECK (
        action_type IN ('create', 'update', 'delete', 'categorize', 'adjust', 'sign_off', 'amend', 'export', 'generate_pdf')
    ),
    CONSTRAINT bas_change_log_entity_check CHECK (
        entity_type IN ('transaction', 'category', 'bas_summary', 'gst_code', 'payg', 'note', 'pdf')
    )
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_bas_change_log_statement ON bas_change_log(bas_statement_id);
CREATE INDEX IF NOT EXISTS idx_bas_change_log_client ON bas_change_log(client_id);
CREATE INDEX IF NOT EXISTS idx_bas_change_log_job ON bas_change_log(job_id);
CREATE INDEX IF NOT EXISTS idx_bas_change_log_user ON bas_change_log(user_id);
CREATE INDEX IF NOT EXISTS idx_bas_change_log_timestamp ON bas_change_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_bas_change_log_action ON bas_change_log(action_type);
CREATE INDEX IF NOT EXISTS idx_bas_change_log_entity ON bas_change_log(entity_type);

-- Add comments
COMMENT ON TABLE bas_change_log IS 'Audit trail for all BAS-related actions for compliance reporting';
COMMENT ON COLUMN bas_change_log.old_value IS 'JSON snapshot of value before change';
COMMENT ON COLUMN bas_change_log.new_value IS 'JSON snapshot of value after change';


-- ============================================================================
-- SECTION C: VERIFICATION
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = 'bas_statements'
    ) THEN
        RAISE EXCEPTION 'ERROR: bas_statements table was not created';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = 'bas_change_log'
    ) THEN
        RAISE EXCEPTION 'ERROR: bas_change_log table was not created';
    END IF;
    
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'BAS Backend Migration Completed Successfully!';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Created:';
    RAISE NOTICE '  - Table: bas_statements';
    RAISE NOTICE '  - Table: bas_change_log';
    RAISE NOTICE '  - Indexes for performance';
    RAISE NOTICE '============================================================';
END $$;
