-- ============================================================================
-- LodgeIT Export Queue - ROLLBACK SQL
-- ============================================================================
-- Version: 1.0.0
-- Created: 2025-01-01
-- 
-- This rollback script removes:
-- 1. Triggers on crm.clients
-- 2. Trigger functions
-- 3. crm.lodgeit_export_queue table (OPTIONAL - commented out)
-- 
-- Run with admin/doadmin credentials
-- ============================================================================

-- ============================================================================
-- SECTION A: DROP TRIGGERS
-- ============================================================================

DROP TRIGGER IF EXISTS trg_lodgeit_onboarding_complete ON crm.clients;
DROP TRIGGER IF EXISTS trg_lodgeit_address_change ON crm.clients;

RAISE NOTICE 'Dropped triggers: trg_lodgeit_onboarding_complete, trg_lodgeit_address_change';


-- ============================================================================
-- SECTION B: DROP TRIGGER FUNCTIONS
-- ============================================================================

DROP FUNCTION IF EXISTS crm.lodgeit_trigger_onboarding_complete();
DROP FUNCTION IF EXISTS crm.lodgeit_trigger_address_change();

RAISE NOTICE 'Dropped functions: lodgeit_trigger_onboarding_complete, lodgeit_trigger_address_change';


-- ============================================================================
-- SECTION C: DROP TABLE (OPTIONAL - COMMENTED OUT BY DEFAULT)
-- ============================================================================
-- WARNING: This will delete all queue data!
-- Uncomment only if you want to completely remove the LodgeIT queue system.

-- DROP TABLE IF EXISTS crm.lodgeit_export_queue CASCADE;
-- RAISE NOTICE 'Dropped table: crm.lodgeit_export_queue';


-- ============================================================================
-- SECTION D: VERIFICATION
-- ============================================================================

DO $$
BEGIN
    -- Verify triggers are gone
    IF EXISTS (
        SELECT 1 FROM information_schema.triggers 
        WHERE trigger_schema = 'crm' 
        AND event_object_table = 'clients'
        AND trigger_name IN ('trg_lodgeit_onboarding_complete', 'trg_lodgeit_address_change')
    ) THEN
        RAISE EXCEPTION 'ERROR: Triggers still exist after rollback';
    END IF;
    
    -- Verify functions are gone
    IF EXISTS (
        SELECT 1 FROM information_schema.routines 
        WHERE routine_schema = 'crm' 
        AND routine_name IN ('lodgeit_trigger_onboarding_complete', 'lodgeit_trigger_address_change')
    ) THEN
        RAISE EXCEPTION 'ERROR: Functions still exist after rollback';
    END IF;
    
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'LodgeIT Trigger Rollback Completed Successfully!';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Removed:';
    RAISE NOTICE '  - Trigger: trg_lodgeit_onboarding_complete';
    RAISE NOTICE '  - Trigger: trg_lodgeit_address_change';
    RAISE NOTICE '  - Function: crm.lodgeit_trigger_onboarding_complete()';
    RAISE NOTICE '  - Function: crm.lodgeit_trigger_address_change()';
    RAISE NOTICE '';
    RAISE NOTICE 'NOTE: crm.lodgeit_export_queue table was preserved.';
    RAISE NOTICE 'Uncomment DROP TABLE statement if you want to remove it.';
    RAISE NOTICE '============================================================';
END $$;
