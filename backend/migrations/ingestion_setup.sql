-- ============================================================================
-- Bookkeeping Ingestion - Database Migration
-- ============================================================================
-- Version: 1.0.0
-- Created: 2025-01-01
-- 
-- This migration creates:
-- 1. import_batches table - tracks all file imports
-- 2. Adds import_batch_id to transactions table
-- ============================================================================

-- ============================================================================
-- SECTION A: CREATE IMPORT_BATCHES TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS import_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id VARCHAR(36) NOT NULL,
    job_id VARCHAR(36),
    file_name VARCHAR(500) NOT NULL,
    file_type VARCHAR(20) NOT NULL,
    file_path TEXT,
    uploaded_by VARCHAR(36) NOT NULL,
    uploaded_by_email VARCHAR(255),
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    row_count INTEGER DEFAULT 0,
    imported_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    notes TEXT,
    column_mapping JSONB,
    errors JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT import_batch_status_check CHECK (
        status IN ('pending', 'processing', 'completed', 'failed', 'rolled_back')
    ),
    CONSTRAINT import_batch_file_type_check CHECK (
        file_type IN ('csv', 'xlsx', 'xls')
    )
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_import_batches_client ON import_batches(client_id);
CREATE INDEX IF NOT EXISTS idx_import_batches_job ON import_batches(job_id);
CREATE INDEX IF NOT EXISTS idx_import_batches_status ON import_batches(status);
CREATE INDEX IF NOT EXISTS idx_import_batches_uploaded_at ON import_batches(uploaded_at);
CREATE INDEX IF NOT EXISTS idx_import_batches_uploaded_by ON import_batches(uploaded_by);

-- Add comments
COMMENT ON TABLE import_batches IS 'Tracks all bookkeeping file imports with status and metadata';
COMMENT ON COLUMN import_batches.column_mapping IS 'JSON mapping of file columns to transaction fields';
COMMENT ON COLUMN import_batches.errors IS 'JSON array of import errors with row numbers';


-- ============================================================================
-- SECTION B: ADD IMPORT_BATCH_ID TO TRANSACTIONS TABLE
-- ============================================================================

-- Add import_batch_id column (nullable, FK to import_batches)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'transactions' 
        AND column_name = 'import_batch_id'
    ) THEN
        ALTER TABLE transactions ADD COLUMN import_batch_id UUID;
        
        -- Add foreign key constraint
        ALTER TABLE transactions ADD CONSTRAINT fk_transactions_import_batch
            FOREIGN KEY (import_batch_id) REFERENCES import_batches(id)
            ON DELETE SET NULL;
        
        -- Create index for batch filtering and rollback
        CREATE INDEX idx_transactions_import_batch ON transactions(import_batch_id);
        
        RAISE NOTICE 'Added import_batch_id column to transactions table';
    ELSE
        RAISE NOTICE 'import_batch_id column already exists in transactions table';
    END IF;
END $$;


-- ============================================================================
-- SECTION C: CREATE DUPLICATE DETECTION FUNCTION
-- ============================================================================

-- Function to check for duplicate transactions
CREATE OR REPLACE FUNCTION check_transaction_duplicate(
    p_client_id VARCHAR(36),
    p_job_id VARCHAR(36),
    p_date DATE,
    p_amount NUMERIC(12, 2),
    p_description TEXT
) RETURNS TABLE (
    is_duplicate BOOLEAN,
    existing_id VARCHAR(36),
    match_type VARCHAR(50)
) AS $$
BEGIN
    -- Normalize description: lowercase, trim, remove extra spaces
    p_description := LOWER(TRIM(REGEXP_REPLACE(COALESCE(p_description, ''), '\s+', ' ', 'g')));
    
    RETURN QUERY
    SELECT 
        TRUE as is_duplicate,
        t.id as existing_id,
        'exact_match'::VARCHAR(50) as match_type
    FROM transactions t
    WHERE t.client_id = p_client_id
      AND t.date = p_date
      AND t.amount = p_amount
      AND LOWER(TRIM(REGEXP_REPLACE(COALESCE(t.description_raw, ''), '\s+', ' ', 'g'))) = p_description
    LIMIT 1;
    
    -- If no rows returned, return not duplicate
    IF NOT FOUND THEN
        RETURN QUERY SELECT FALSE, NULL::VARCHAR(36), NULL::VARCHAR(50);
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION check_transaction_duplicate IS 
    'Check if a transaction is a duplicate based on client_id, date, amount, and normalized description';


-- ============================================================================
-- SECTION D: CREATE IMPORT AUDIT LOG TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS import_audit_log (
    id SERIAL PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL,
    user_email VARCHAR(255),
    action VARCHAR(50) NOT NULL,
    details JSONB,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_import_audit_batch ON import_audit_log(batch_id);
CREATE INDEX IF NOT EXISTS idx_import_audit_timestamp ON import_audit_log(timestamp);

COMMENT ON TABLE import_audit_log IS 'Audit trail for all import operations';


-- ============================================================================
-- SECTION E: VERIFICATION
-- ============================================================================

DO $$
BEGIN
    -- Verify import_batches table
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name = 'import_batches'
    ) THEN
        RAISE EXCEPTION 'ERROR: import_batches table was not created';
    END IF;
    
    -- Verify import_batch_id column in transactions
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'transactions' 
        AND column_name = 'import_batch_id'
    ) THEN
        RAISE EXCEPTION 'ERROR: import_batch_id column was not added to transactions';
    END IF;
    
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Ingestion Migration Completed Successfully!';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Created:';
    RAISE NOTICE '  - Table: import_batches';
    RAISE NOTICE '  - Table: import_audit_log';
    RAISE NOTICE '  - Column: transactions.import_batch_id';
    RAISE NOTICE '  - Function: check_transaction_duplicate()';
    RAISE NOTICE '============================================================';
END $$;
