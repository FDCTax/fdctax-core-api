-- ============================================================================
-- LodgeIT Export Queue - TRIGGER TESTING SQL
-- ============================================================================
-- Version: 1.0.0
-- Created: 2025-01-01
-- 
-- This file contains SQL to test both triggers and verify idempotency
-- Run after lodgeit_triggers.sql has been executed
-- ============================================================================


-- ============================================================================
-- TEST SETUP: Clear queue and get a test client
-- ============================================================================

-- Clear queue for testing (only pending items)
DELETE FROM crm.lodgeit_export_queue WHERE status = 'pending';

-- Get a test client system_id (replace with actual ID)
-- SELECT system_id, onboarding_completed, 
--        residential_address_line_1, postal_address_line_1
-- FROM crm.clients LIMIT 5;


-- ============================================================================
-- TEST 1: TRIGGER A - ONBOARDING COMPLETE
-- ============================================================================
-- Expected: Client should be added to queue with trigger_reason = 'onboarding_complete'

-- Step 1: Ensure test client has onboarding_completed = false
UPDATE crm.clients 
SET onboarding_completed = false, updated_at = NOW()
WHERE system_id = 1;  -- Replace with actual system_id

-- Verify queue is empty for this client
SELECT * FROM crm.lodgeit_export_queue WHERE client_id = 1;
-- Expected: No rows

-- Step 2: Trigger onboarding complete
UPDATE crm.clients 
SET onboarding_completed = true, updated_at = NOW()
WHERE system_id = 1;  -- Replace with actual system_id

-- Verify client was added to queue
SELECT * FROM crm.lodgeit_export_queue WHERE client_id = 1;
-- Expected: 1 row with:
--   status = 'pending'
--   trigger_reason = 'onboarding_complete'


-- ============================================================================
-- TEST 2: IDEMPOTENCY - ONBOARDING (should NOT create duplicate)
-- ============================================================================
-- Expected: No new row should be created

-- Step 1: Reset onboarding and trigger again
UPDATE crm.clients 
SET onboarding_completed = false, updated_at = NOW()
WHERE system_id = 1;

UPDATE crm.clients 
SET onboarding_completed = true, updated_at = NOW()
WHERE system_id = 1;

-- Verify only 1 row exists (idempotency)
SELECT COUNT(*) as queue_count FROM crm.lodgeit_export_queue 
WHERE client_id = 1 AND status = 'pending';
-- Expected: 1 (not 2)


-- ============================================================================
-- TEST 3: TRIGGER B - ADDRESS CHANGE (Residential)
-- ============================================================================
-- First, clear the queue to test address trigger independently

-- Mark existing as exported to allow new pending entry
UPDATE crm.lodgeit_export_queue 
SET status = 'exported' 
WHERE client_id = 2;  -- Use a different client

-- Trigger address change
UPDATE crm.clients 
SET residential_address_line_1 = 'Test Address ' || NOW()::TEXT,
    updated_at = NOW()
WHERE system_id = 2;  -- Replace with actual system_id

-- Verify client was added to queue
SELECT * FROM crm.lodgeit_export_queue 
WHERE client_id = 2 AND trigger_reason = 'address_change';
-- Expected: 1 row with trigger_reason = 'address_change'


-- ============================================================================
-- TEST 4: TRIGGER B - ADDRESS CHANGE (Postal)
-- ============================================================================

-- Mark existing as exported
UPDATE crm.lodgeit_export_queue 
SET status = 'exported' 
WHERE client_id = 3;

-- Trigger postal address change
UPDATE crm.clients 
SET postal_address_postcode = '2000',
    updated_at = NOW()
WHERE system_id = 3;

-- Verify
SELECT * FROM crm.lodgeit_export_queue 
WHERE client_id = 3 AND trigger_reason = 'address_change';


-- ============================================================================
-- TEST 5: TRIGGER B - ADDRESS CHANGE (Business)
-- ============================================================================

-- Mark existing as exported
UPDATE crm.lodgeit_export_queue 
SET status = 'exported' 
WHERE client_id = 4;

-- Trigger business address change
UPDATE crm.clients 
SET business_address_state = 'NSW',
    updated_at = NOW()
WHERE system_id = 4;

-- Verify
SELECT * FROM crm.lodgeit_export_queue 
WHERE client_id = 4 AND trigger_reason = 'address_change';


-- ============================================================================
-- TEST 6: IDEMPOTENCY - ADDRESS (should NOT create duplicate)
-- ============================================================================

-- Count current pending for client 2
SELECT COUNT(*) FROM crm.lodgeit_export_queue 
WHERE client_id = 2 AND status = 'pending';

-- Trigger another address change (should be idempotent)
UPDATE crm.clients 
SET residential_address_line_2 = 'Suite 100',
    updated_at = NOW()
WHERE system_id = 2;

-- Verify still only 1 pending row
SELECT COUNT(*) as queue_count FROM crm.lodgeit_export_queue 
WHERE client_id = 2 AND status = 'pending';
-- Expected: 1 (not 2)


-- ============================================================================
-- TEST 7: NO TRIGGER ON NON-ADDRESS FIELDS
-- ============================================================================
-- Update a non-address field - should NOT trigger

-- Mark all as exported first
UPDATE crm.lodgeit_export_queue SET status = 'exported' WHERE client_id = 5;

-- Update non-address field
UPDATE crm.clients 
SET email = 'test_' || NOW()::TEXT || '@example.com',
    updated_at = NOW()
WHERE system_id = 5;

-- Verify NO new pending entry
SELECT COUNT(*) as queue_count FROM crm.lodgeit_export_queue 
WHERE client_id = 5 AND status = 'pending';
-- Expected: 0


-- ============================================================================
-- SUMMARY QUERY: View all queue entries
-- ============================================================================

SELECT 
    eq.id,
    eq.client_id,
    c.first_name || ' ' || c.last_name as client_name,
    eq.status,
    eq.trigger_reason,
    eq.created_at,
    eq.updated_at
FROM crm.lodgeit_export_queue eq
LEFT JOIN crm.clients c ON c.system_id = eq.client_id
ORDER BY eq.created_at DESC
LIMIT 20;


-- ============================================================================
-- VERIFICATION SUMMARY
-- ============================================================================
/*
TEST CHECKLIST:
[ ] Test 1: Onboarding complete triggers queue insertion
[ ] Test 2: Onboarding idempotency (no duplicate when already pending)
[ ] Test 3: Residential address change triggers queue insertion
[ ] Test 4: Postal address change triggers queue insertion
[ ] Test 5: Business address change triggers queue insertion
[ ] Test 6: Address idempotency (no duplicate when already pending)
[ ] Test 7: Non-address field changes do NOT trigger

EXPECTED RESULTS:
- Trigger A fires when onboarding_completed: false → true
- Trigger B fires when any address field changes
- Both triggers respect idempotency (no duplicates when status='pending')
- Non-address field updates do not trigger queue insertion
*/
