-- ============================================================================
-- LodgeIT Export Queue - Trigger SQL Migration
-- ============================================================================
-- Version: 1.0.0
-- Created: 2025-01-01
-- 
-- This migration creates:
-- 1. crm.lodgeit_export_queue table (if not exists)
-- 2. Trigger A: Onboarding Complete trigger
-- 3. Trigger B: Address Change trigger
-- 
-- Run with admin/doadmin credentials that have CREATE privileges on crm schema
-- ============================================================================

-- ============================================================================
-- SECTION A: CREATE EXPORT QUEUE TABLE IN CRM SCHEMA
-- ============================================================================

CREATE TABLE IF NOT EXISTS crm.lodgeit_export_queue (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    trigger_reason VARCHAR(100),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_exported_at TIMESTAMP WITH TIME ZONE,
    
    -- Constraint: status must be one of the allowed values
    CONSTRAINT lodgeit_queue_status_check CHECK (status IN ('pending', 'exported', 'failed', 'rolled_back'))
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_crm_lodgeit_queue_status ON crm.lodgeit_export_queue(status);
CREATE INDEX IF NOT EXISTS idx_crm_lodgeit_queue_client ON crm.lodgeit_export_queue(client_id);
CREATE INDEX IF NOT EXISTS idx_crm_lodgeit_queue_client_status ON crm.lodgeit_export_queue(client_id, status);
CREATE INDEX IF NOT EXISTS idx_crm_lodgeit_queue_created ON crm.lodgeit_export_queue(created_at);

-- Add comment
COMMENT ON TABLE crm.lodgeit_export_queue IS 'Queue of clients pending export to LodgeIT practice management system';


-- ============================================================================
-- SECTION B: TRIGGER FUNCTION A - ONBOARDING COMPLETE
-- ============================================================================
-- Fires when: onboarding_completed changes from false → true
-- Action: Insert into crm.lodgeit_export_queue using NEW.system_id
-- Idempotency: Do not insert if client already exists with status = 'pending'
-- ============================================================================

CREATE OR REPLACE FUNCTION crm.lodgeit_trigger_onboarding_complete()
RETURNS TRIGGER AS $$
BEGIN
    -- Only trigger when onboarding_completed changes from false/null to true
    IF (OLD.onboarding_completed IS DISTINCT FROM NEW.onboarding_completed)
       AND (OLD.onboarding_completed IS FALSE OR OLD.onboarding_completed IS NULL)
       AND (NEW.onboarding_completed IS TRUE) THEN
        
        -- Idempotency check: Do not insert if client already in queue with status = 'pending'
        IF NOT EXISTS (
            SELECT 1 FROM crm.lodgeit_export_queue 
            WHERE client_id = NEW.system_id 
            AND status = 'pending'
        ) THEN
            INSERT INTO crm.lodgeit_export_queue (
                client_id, 
                status, 
                trigger_reason, 
                created_at, 
                updated_at
            )
            VALUES (
                NEW.system_id, 
                'pending', 
                'onboarding_complete', 
                NOW(), 
                NOW()
            );
            
            RAISE NOTICE 'LodgeIT Queue: Added client % (onboarding_complete)', NEW.system_id;
        ELSE
            RAISE NOTICE 'LodgeIT Queue: Client % already pending, skipped', NEW.system_id;
        END IF;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION crm.lodgeit_trigger_onboarding_complete() IS 
    'Trigger function: Add client to LodgeIT queue when onboarding_completed changes from false to true';


-- ============================================================================
-- SECTION C: TRIGGER FUNCTION B - ADDRESS CHANGE
-- ============================================================================
-- Fires when: ANY address field changes (residential, postal, or business)
-- Action: Insert into crm.lodgeit_export_queue using NEW.system_id
-- Idempotency: Do not insert if client already exists with status = 'pending'
-- ============================================================================

CREATE OR REPLACE FUNCTION crm.lodgeit_trigger_address_change()
RETURNS TRIGGER AS $$
DECLARE
    address_changed BOOLEAN := FALSE;
BEGIN
    -- Check residential address changes
    IF (COALESCE(OLD.residential_address_line_1, '') IS DISTINCT FROM COALESCE(NEW.residential_address_line_1, '')) OR
       (COALESCE(OLD.residential_address_line_2, '') IS DISTINCT FROM COALESCE(NEW.residential_address_line_2, '')) OR
       (COALESCE(OLD.residential_address_location, '') IS DISTINCT FROM COALESCE(NEW.residential_address_location, '')) OR
       (COALESCE(OLD.residential_address_postcode, '') IS DISTINCT FROM COALESCE(NEW.residential_address_postcode, '')) OR
       (COALESCE(OLD.residential_address_state, '') IS DISTINCT FROM COALESCE(NEW.residential_address_state, '')) OR
       (COALESCE(OLD.residential_address_country, '') IS DISTINCT FROM COALESCE(NEW.residential_address_country, '')) THEN
        address_changed := TRUE;
    END IF;
    
    -- Check postal address changes
    IF (COALESCE(OLD.postal_address_line_1, '') IS DISTINCT FROM COALESCE(NEW.postal_address_line_1, '')) OR
       (COALESCE(OLD.postal_address_line_2, '') IS DISTINCT FROM COALESCE(NEW.postal_address_line_2, '')) OR
       (COALESCE(OLD.postal_address_location, '') IS DISTINCT FROM COALESCE(NEW.postal_address_location, '')) OR
       (COALESCE(OLD.postal_address_postcode, '') IS DISTINCT FROM COALESCE(NEW.postal_address_postcode, '')) OR
       (COALESCE(OLD.postal_address_state, '') IS DISTINCT FROM COALESCE(NEW.postal_address_state, '')) OR
       (COALESCE(OLD.postal_address_country, '') IS DISTINCT FROM COALESCE(NEW.postal_address_country, '')) THEN
        address_changed := TRUE;
    END IF;
    
    -- Check business address changes
    IF (COALESCE(OLD.business_address_line_1, '') IS DISTINCT FROM COALESCE(NEW.business_address_line_1, '')) OR
       (COALESCE(OLD.business_address_line_2, '') IS DISTINCT FROM COALESCE(NEW.business_address_line_2, '')) OR
       (COALESCE(OLD.business_address_location, '') IS DISTINCT FROM COALESCE(NEW.business_address_location, '')) OR
       (COALESCE(OLD.business_address_postcode, '') IS DISTINCT FROM COALESCE(NEW.business_address_postcode, '')) OR
       (COALESCE(OLD.business_address_state, '') IS DISTINCT FROM COALESCE(NEW.business_address_state, '')) OR
       (COALESCE(OLD.business_address_country, '') IS DISTINCT FROM COALESCE(NEW.business_address_country, '')) THEN
        address_changed := TRUE;
    END IF;
    
    -- If any address changed, add to queue
    IF address_changed THEN
        -- Idempotency check: Do not insert if client already in queue with status = 'pending'
        IF NOT EXISTS (
            SELECT 1 FROM crm.lodgeit_export_queue 
            WHERE client_id = NEW.system_id 
            AND status = 'pending'
        ) THEN
            INSERT INTO crm.lodgeit_export_queue (
                client_id, 
                status, 
                trigger_reason, 
                created_at, 
                updated_at
            )
            VALUES (
                NEW.system_id, 
                'pending', 
                'address_change', 
                NOW(), 
                NOW()
            );
            
            RAISE NOTICE 'LodgeIT Queue: Added client % (address_change)', NEW.system_id;
        ELSE
            RAISE NOTICE 'LodgeIT Queue: Client % already pending, skipped', NEW.system_id;
        END IF;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION crm.lodgeit_trigger_address_change() IS 
    'Trigger function: Add client to LodgeIT queue when any address field changes';


-- ============================================================================
-- SECTION D: CREATE TRIGGERS ON crm.clients
-- ============================================================================

-- Drop existing triggers if they exist (for clean re-run)
DROP TRIGGER IF EXISTS trg_lodgeit_onboarding_complete ON crm.clients;
DROP TRIGGER IF EXISTS trg_lodgeit_address_change ON crm.clients;

-- Trigger A: Onboarding Complete
CREATE TRIGGER trg_lodgeit_onboarding_complete
    AFTER UPDATE ON crm.clients
    FOR EACH ROW
    EXECUTE FUNCTION crm.lodgeit_trigger_onboarding_complete();

COMMENT ON TRIGGER trg_lodgeit_onboarding_complete ON crm.clients IS 
    'Fire when onboarding_completed changes from false to true';

-- Trigger B: Address Change
CREATE TRIGGER trg_lodgeit_address_change
    AFTER UPDATE ON crm.clients
    FOR EACH ROW
    EXECUTE FUNCTION crm.lodgeit_trigger_address_change();

COMMENT ON TRIGGER trg_lodgeit_address_change ON crm.clients IS 
    'Fire when any address field changes (residential, postal, or business)';


-- ============================================================================
-- SECTION E: VERIFICATION QUERIES
-- ============================================================================

-- Verify table exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'crm' 
        AND table_name = 'lodgeit_export_queue'
    ) THEN
        RAISE EXCEPTION 'ERROR: crm.lodgeit_export_queue table was not created';
    END IF;
    
    RAISE NOTICE 'VERIFIED: crm.lodgeit_export_queue table exists';
END $$;

-- Verify triggers exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.triggers 
        WHERE trigger_schema = 'crm' 
        AND event_object_table = 'clients'
        AND trigger_name = 'trg_lodgeit_onboarding_complete'
    ) THEN
        RAISE EXCEPTION 'ERROR: trg_lodgeit_onboarding_complete trigger was not created';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.triggers 
        WHERE trigger_schema = 'crm' 
        AND event_object_table = 'clients'
        AND trigger_name = 'trg_lodgeit_address_change'
    ) THEN
        RAISE EXCEPTION 'ERROR: trg_lodgeit_address_change trigger was not created';
    END IF;
    
    RAISE NOTICE 'VERIFIED: Both triggers exist on crm.clients';
END $$;

-- Print summary
DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'LodgeIT Trigger Migration Completed Successfully!';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Created:';
    RAISE NOTICE '  - Table: crm.lodgeit_export_queue';
    RAISE NOTICE '  - Function: crm.lodgeit_trigger_onboarding_complete()';
    RAISE NOTICE '  - Function: crm.lodgeit_trigger_address_change()';
    RAISE NOTICE '  - Trigger: trg_lodgeit_onboarding_complete ON crm.clients';
    RAISE NOTICE '  - Trigger: trg_lodgeit_address_change ON crm.clients';
    RAISE NOTICE '============================================================';
END $$;
