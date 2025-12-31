-- ============================================================================
-- VXT Phone System Integration - Database Migration
-- ============================================================================
-- Version: 1.0.0
-- Created: 2025-01-01
-- 
-- This migration creates:
-- 1. vxt_calls - Phone call records from VXT
-- 2. vxt_transcripts - Call transcriptions
-- 3. vxt_recordings - Audio recording references
-- 4. workpapers_call_links - Link calls to workpapers
-- ============================================================================

-- ============================================================================
-- SECTION A: CREATE VXT_CALLS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS vxt_calls (
    id SERIAL PRIMARY KEY,
    call_id VARCHAR(100) UNIQUE NOT NULL,
    from_number VARCHAR(50) NOT NULL,
    to_number VARCHAR(50) NOT NULL,
    direction VARCHAR(20) DEFAULT 'inbound',
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    duration_seconds INTEGER DEFAULT 0,
    status VARCHAR(30) DEFAULT 'completed',
    matched_client_id INTEGER,
    client_match_confidence VARCHAR(20),
    raw_payload JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_vxt_calls_call_id ON vxt_calls(call_id);
CREATE INDEX IF NOT EXISTS idx_vxt_calls_from_number ON vxt_calls(from_number);
CREATE INDEX IF NOT EXISTS idx_vxt_calls_to_number ON vxt_calls(to_number);
CREATE INDEX IF NOT EXISTS idx_vxt_calls_matched_client ON vxt_calls(matched_client_id);
CREATE INDEX IF NOT EXISTS idx_vxt_calls_timestamp ON vxt_calls(timestamp);
CREATE INDEX IF NOT EXISTS idx_vxt_calls_direction ON vxt_calls(direction);

-- Add comments
COMMENT ON TABLE vxt_calls IS 'Phone call records received from VXT phone system';
COMMENT ON COLUMN vxt_calls.call_id IS 'Unique call ID from VXT system';
COMMENT ON COLUMN vxt_calls.matched_client_id IS 'FK to crm.clients if phone number matched';
COMMENT ON COLUMN vxt_calls.client_match_confidence IS 'Match confidence: exact, partial, multiple, none';


-- ============================================================================
-- SECTION B: CREATE VXT_TRANSCRIPTS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS vxt_transcripts (
    id SERIAL PRIMARY KEY,
    call_id INTEGER NOT NULL REFERENCES vxt_calls(id) ON DELETE CASCADE,
    transcript_text TEXT,
    summary_text TEXT,
    language VARCHAR(10) DEFAULT 'en',
    confidence_score NUMERIC(5, 4),
    word_count INTEGER,
    speaker_labels JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure one transcript per call
    CONSTRAINT unique_call_transcript UNIQUE (call_id)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_vxt_transcripts_call ON vxt_transcripts(call_id);

-- Add comments
COMMENT ON TABLE vxt_transcripts IS 'Call transcriptions from VXT with AI-generated summaries';
COMMENT ON COLUMN vxt_transcripts.summary_text IS 'AI-generated summary of the call';
COMMENT ON COLUMN vxt_transcripts.speaker_labels IS 'JSON array of speaker segments with timestamps';


-- ============================================================================
-- SECTION C: CREATE VXT_RECORDINGS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS vxt_recordings (
    id SERIAL PRIMARY KEY,
    call_id INTEGER NOT NULL REFERENCES vxt_calls(id) ON DELETE CASCADE,
    recording_url TEXT NOT NULL,
    local_storage_path TEXT,
    file_size_bytes BIGINT,
    duration_seconds INTEGER,
    format VARCHAR(20) DEFAULT 'mp3',
    is_downloaded BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure one recording per call
    CONSTRAINT unique_call_recording UNIQUE (call_id)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_vxt_recordings_call ON vxt_recordings(call_id);
CREATE INDEX IF NOT EXISTS idx_vxt_recordings_downloaded ON vxt_recordings(is_downloaded);

-- Add comments
COMMENT ON TABLE vxt_recordings IS 'Audio recording references for VXT calls';
COMMENT ON COLUMN vxt_recordings.recording_url IS 'VXT-hosted recording URL';
COMMENT ON COLUMN vxt_recordings.local_storage_path IS 'Local path if recording is downloaded/cached';


-- ============================================================================
-- SECTION D: CREATE WORKPAPERS_CALL_LINKS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS workpapers_call_links (
    id SERIAL PRIMARY KEY,
    call_id INTEGER NOT NULL REFERENCES vxt_calls(id) ON DELETE CASCADE,
    workpaper_id INTEGER NOT NULL,
    link_type VARCHAR(50) DEFAULT 'auto',
    notes TEXT,
    created_by VARCHAR(36),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure one link per call-workpaper combination
    CONSTRAINT unique_call_workpaper UNIQUE (call_id, workpaper_id)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_workpapers_call_links_call ON workpapers_call_links(call_id);
CREATE INDEX IF NOT EXISTS idx_workpapers_call_links_workpaper ON workpapers_call_links(workpaper_id);

-- Add comments
COMMENT ON TABLE workpapers_call_links IS 'Links between VXT calls and workpapers for audit trail';
COMMENT ON COLUMN workpapers_call_links.link_type IS 'auto=system-created, manual=user-created';


-- ============================================================================
-- SECTION E: CREATE VXT WEBHOOK LOG TABLE (for audit)
-- ============================================================================

CREATE TABLE IF NOT EXISTS vxt_webhook_log (
    id SERIAL PRIMARY KEY,
    webhook_id VARCHAR(100),
    event_type VARCHAR(50),
    call_id VARCHAR(100),
    payload JSONB,
    signature_valid BOOLEAN,
    processed BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    received_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_vxt_webhook_log_call ON vxt_webhook_log(call_id);
CREATE INDEX IF NOT EXISTS idx_vxt_webhook_log_received ON vxt_webhook_log(received_at);

-- Add comments
COMMENT ON TABLE vxt_webhook_log IS 'Audit log for all VXT webhook events received';


-- ============================================================================
-- SECTION F: VERIFICATION
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'vxt_calls') THEN
        RAISE EXCEPTION 'ERROR: vxt_calls table was not created';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'vxt_transcripts') THEN
        RAISE EXCEPTION 'ERROR: vxt_transcripts table was not created';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'vxt_recordings') THEN
        RAISE EXCEPTION 'ERROR: vxt_recordings table was not created';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'workpapers_call_links') THEN
        RAISE EXCEPTION 'ERROR: workpapers_call_links table was not created';
    END IF;
    
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'VXT Integration Migration Completed Successfully!';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Created:';
    RAISE NOTICE '  - Table: vxt_calls';
    RAISE NOTICE '  - Table: vxt_transcripts';
    RAISE NOTICE '  - Table: vxt_recordings';
    RAISE NOTICE '  - Table: workpapers_call_links';
    RAISE NOTICE '  - Table: vxt_webhook_log';
    RAISE NOTICE '============================================================';
END $$;
