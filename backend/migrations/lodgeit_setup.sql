-- LodgeIT Integration - Database Setup
-- Run this migration to create tables and triggers for LodgeIT integration
-- Version: 1.0.0
-- Created: 2025-01-01

-- ==================== TABLES ====================

-- Export Queue Table - Tracks clients pending export to LodgeIT
CREATE TABLE IF NOT EXISTS lodgeit_export_queue (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    trigger_reason VARCHAR(100),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_exported_at TIMESTAMP WITH TIME ZONE
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_lodgeit_queue_status ON lodgeit_export_queue(status);
CREATE INDEX IF NOT EXISTS idx_lodgeit_queue_client_status ON lodgeit_export_queue(client_id, status);
CREATE INDEX IF NOT EXISTS idx_lodgeit_queue_created ON lodgeit_export_queue(created_at);

-- Audit Log Table - Tracks all LodgeIT operations for compliance
CREATE TABLE IF NOT EXISTS lodgeit_audit_log (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    user_email VARCHAR(255),
    action VARCHAR(50) NOT NULL,
    client_ids JSONB,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT,
    details JSONB,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for audit log
CREATE INDEX IF NOT EXISTS idx_lodgeit_audit_user ON lodgeit_audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_lodgeit_audit_action ON lodgeit_audit_log(action);
CREATE INDEX IF NOT EXISTS idx_lodgeit_audit_timestamp ON lodgeit_audit_log(timestamp);


-- ==================== TRIGGERS ====================

-- First, add the required columns to crm_clients if they don't exist
DO $$ 
BEGIN
    -- Add onboarding_completed column
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'crm_clients' 
        AND column_name = 'onboarding_completed'
    ) THEN
        ALTER TABLE crm_clients ADD COLUMN onboarding_completed BOOLEAN DEFAULT FALSE;
    END IF;
    
    -- Add address fields if they don't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'crm_clients' 
        AND column_name = 'residential_address_line1'
    ) THEN
        ALTER TABLE crm_clients ADD COLUMN residential_address_line1 VARCHAR(255);
        ALTER TABLE crm_clients ADD COLUMN residential_address_line2 VARCHAR(255);
        ALTER TABLE crm_clients ADD COLUMN residential_suburb VARCHAR(100);
        ALTER TABLE crm_clients ADD COLUMN residential_state VARCHAR(50);
        ALTER TABLE crm_clients ADD COLUMN residential_postcode VARCHAR(20);
        ALTER TABLE crm_clients ADD COLUMN residential_country VARCHAR(100) DEFAULT 'Australia';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'crm_clients' 
        AND column_name = 'postal_address_line1'
    ) THEN
        ALTER TABLE crm_clients ADD COLUMN postal_address_line1 VARCHAR(255);
        ALTER TABLE crm_clients ADD COLUMN postal_address_line2 VARCHAR(255);
        ALTER TABLE crm_clients ADD COLUMN postal_suburb VARCHAR(100);
        ALTER TABLE crm_clients ADD COLUMN postal_state VARCHAR(50);
        ALTER TABLE crm_clients ADD COLUMN postal_postcode VARCHAR(20);
        ALTER TABLE crm_clients ADD COLUMN postal_country VARCHAR(100) DEFAULT 'Australia';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'crm_clients' 
        AND column_name = 'business_address_line1'
    ) THEN
        ALTER TABLE crm_clients ADD COLUMN business_address_line1 VARCHAR(255);
        ALTER TABLE crm_clients ADD COLUMN business_address_line2 VARCHAR(255);
        ALTER TABLE crm_clients ADD COLUMN business_suburb VARCHAR(100);
        ALTER TABLE crm_clients ADD COLUMN business_state VARCHAR(50);
        ALTER TABLE crm_clients ADD COLUMN business_postcode VARCHAR(20);
        ALTER TABLE crm_clients ADD COLUMN business_country VARCHAR(100) DEFAULT 'Australia';
    END IF;
END $$;


-- Trigger Function A: Onboarding Complete
-- When onboarding_completed transitions from false → true, add client to queue
CREATE OR REPLACE FUNCTION lodgeit_trigger_onboarding_complete()
RETURNS TRIGGER AS $$
BEGIN
    -- Only trigger when onboarding_completed changes from false to true
    IF (OLD.onboarding_completed IS FALSE OR OLD.onboarding_completed IS NULL) 
       AND NEW.onboarding_completed IS TRUE THEN
        
        -- Check if client is already in queue with pending status
        IF NOT EXISTS (
            SELECT 1 FROM lodgeit_export_queue 
            WHERE client_id = NEW.id AND status = 'pending'
        ) THEN
            INSERT INTO lodgeit_export_queue (client_id, status, trigger_reason, created_at, updated_at)
            VALUES (NEW.id, 'pending', 'onboarding_complete', NOW(), NOW());
        END IF;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- Trigger Function B: Address Change
-- When any address field changes, add client to queue
CREATE OR REPLACE FUNCTION lodgeit_trigger_address_change()
RETURNS TRIGGER AS $$
DECLARE
    address_changed BOOLEAN := FALSE;
BEGIN
    -- Check residential address changes
    IF (COALESCE(OLD.residential_address_line1, '') != COALESCE(NEW.residential_address_line1, '')) OR
       (COALESCE(OLD.residential_address_line2, '') != COALESCE(NEW.residential_address_line2, '')) OR
       (COALESCE(OLD.residential_suburb, '') != COALESCE(NEW.residential_suburb, '')) OR
       (COALESCE(OLD.residential_state, '') != COALESCE(NEW.residential_state, '')) OR
       (COALESCE(OLD.residential_postcode, '') != COALESCE(NEW.residential_postcode, '')) OR
       (COALESCE(OLD.residential_country, '') != COALESCE(NEW.residential_country, '')) THEN
        address_changed := TRUE;
    END IF;
    
    -- Check postal address changes
    IF (COALESCE(OLD.postal_address_line1, '') != COALESCE(NEW.postal_address_line1, '')) OR
       (COALESCE(OLD.postal_address_line2, '') != COALESCE(NEW.postal_address_line2, '')) OR
       (COALESCE(OLD.postal_suburb, '') != COALESCE(NEW.postal_suburb, '')) OR
       (COALESCE(OLD.postal_state, '') != COALESCE(NEW.postal_state, '')) OR
       (COALESCE(OLD.postal_postcode, '') != COALESCE(NEW.postal_postcode, '')) OR
       (COALESCE(OLD.postal_country, '') != COALESCE(NEW.postal_country, '')) THEN
        address_changed := TRUE;
    END IF;
    
    -- Check business address changes
    IF (COALESCE(OLD.business_address_line1, '') != COALESCE(NEW.business_address_line1, '')) OR
       (COALESCE(OLD.business_address_line2, '') != COALESCE(NEW.business_address_line2, '')) OR
       (COALESCE(OLD.business_suburb, '') != COALESCE(NEW.business_suburb, '')) OR
       (COALESCE(OLD.business_state, '') != COALESCE(NEW.business_state, '')) OR
       (COALESCE(OLD.business_postcode, '') != COALESCE(NEW.business_postcode, '')) OR
       (COALESCE(OLD.business_country, '') != COALESCE(NEW.business_country, '')) THEN
        address_changed := TRUE;
    END IF;
    
    -- If any address changed, add to queue
    IF address_changed THEN
        -- Check if client is already in queue with pending status
        IF NOT EXISTS (
            SELECT 1 FROM lodgeit_export_queue 
            WHERE client_id = NEW.id AND status = 'pending'
        ) THEN
            INSERT INTO lodgeit_export_queue (client_id, status, trigger_reason, created_at, updated_at)
            VALUES (NEW.id, 'pending', 'address_change', NOW(), NOW());
        END IF;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- Drop existing triggers if they exist (for clean re-run)
DROP TRIGGER IF EXISTS trg_lodgeit_onboarding_complete ON crm_clients;
DROP TRIGGER IF EXISTS trg_lodgeit_address_change ON crm_clients;

-- Create Trigger A: Onboarding Complete
CREATE TRIGGER trg_lodgeit_onboarding_complete
    AFTER UPDATE ON crm_clients
    FOR EACH ROW
    EXECUTE FUNCTION lodgeit_trigger_onboarding_complete();

-- Create Trigger B: Address Change
CREATE TRIGGER trg_lodgeit_address_change
    AFTER UPDATE ON crm_clients
    FOR EACH ROW
    EXECUTE FUNCTION lodgeit_trigger_address_change();


-- ==================== COMMENTS ====================

COMMENT ON TABLE lodgeit_export_queue IS 'Queue of clients pending export to LodgeIT practice management system';
COMMENT ON TABLE lodgeit_audit_log IS 'Audit log for all LodgeIT integration operations';

COMMENT ON COLUMN lodgeit_export_queue.trigger_reason IS 'Reason for queue entry: onboarding_complete, address_change, manual';
COMMENT ON COLUMN lodgeit_export_queue.status IS 'Queue status: pending, exported, failed';

COMMENT ON FUNCTION lodgeit_trigger_onboarding_complete() IS 'Trigger: Add client to LodgeIT queue when onboarding completes';
COMMENT ON FUNCTION lodgeit_trigger_address_change() IS 'Trigger: Add client to LodgeIT queue when address changes';


-- ==================== VERIFICATION ====================

-- Verify tables were created
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'lodgeit_export_queue') THEN
        RAISE EXCEPTION 'lodgeit_export_queue table was not created';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'lodgeit_audit_log') THEN
        RAISE EXCEPTION 'lodgeit_audit_log table was not created';
    END IF;
    
    RAISE NOTICE 'LodgeIT integration setup completed successfully';
END $$;
