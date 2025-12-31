-- Email Module Database Setup
-- Migration script for email_logs table
-- Run with admin privileges

-- =============================================================================
-- EMAIL LOGS TABLE
-- Stores all sent emails for audit trail and tracking
-- =============================================================================

CREATE TABLE IF NOT EXISTS email_logs (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(100),              -- Internal message ID
    provider_message_id VARCHAR(100),     -- Resend message ID
    to_address VARCHAR(255) NOT NULL,
    from_address VARCHAR(255) NOT NULL,
    reply_to VARCHAR(255),
    cc TEXT,                              -- Comma-separated addresses
    bcc TEXT,                             -- Comma-separated addresses
    subject VARCHAR(500) NOT NULL,
    body_html TEXT NOT NULL,
    body_text TEXT,                       -- Plain text version
    provider VARCHAR(30) DEFAULT 'resend',
    status VARCHAR(30) DEFAULT 'pending', -- pending, sent, delivered, failed, bounced
    error_message TEXT,
    client_id VARCHAR(36),                -- FK to crm_clients if applicable
    job_id VARCHAR(36),                   -- FK to workpaper_jobs if applicable
    message_type VARCHAR(50),             -- notification, reminder, document, etc.
    template_id VARCHAR(50),              -- Template used (if any)
    metadata JSONB,                       -- Additional tracking data
    sent_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_email_logs_to ON email_logs(to_address);
CREATE INDEX IF NOT EXISTS idx_email_logs_client ON email_logs(client_id);
CREATE INDEX IF NOT EXISTS idx_email_logs_status ON email_logs(status);
CREATE INDEX IF NOT EXISTS idx_email_logs_created ON email_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_email_logs_type ON email_logs(message_type);
CREATE INDEX IF NOT EXISTS idx_email_logs_provider_msg ON email_logs(provider_message_id);

-- =============================================================================
-- GRANT PERMISSIONS (adjust as needed)
-- =============================================================================

-- GRANT SELECT, INSERT, UPDATE ON email_logs TO fdccore;
-- GRANT USAGE, SELECT ON SEQUENCE email_logs_id_seq TO fdccore;

-- =============================================================================
-- VERIFICATION
-- =============================================================================

-- Verify table creation
SELECT 'email_logs table created successfully' AS status
WHERE EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'email_logs');
