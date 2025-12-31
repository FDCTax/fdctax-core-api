-- ============================================================
-- PHASE 3: Extended Client Profiles Schema
-- ============================================================
-- This migration creates the core.client_profiles table with
-- the full 86-field schema for comprehensive client data.
--
-- Run this migration manually with admin privileges.
-- ============================================================

-- Create core schema if not exists
CREATE SCHEMA IF NOT EXISTS core;

-- ============================================================
-- CLIENT PROFILES TABLE (86 fields)
-- ============================================================
CREATE TABLE IF NOT EXISTS core.client_profiles (
    -- Primary Key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- ==================== IDENTITY LINK ====================
    person_id UUID REFERENCES person(id) ON DELETE SET NULL,
    crm_client_id UUID REFERENCES crm_client_identity(id) ON DELETE SET NULL,
    legacy_client_id VARCHAR(50),  -- For migration from old systems
    
    -- ==================== BASIC INFO (10 fields) ====================
    client_code VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    legal_name VARCHAR(255),
    trading_name VARCHAR(255),
    entity_type VARCHAR(50) NOT NULL DEFAULT 'individual',  -- individual, sole_trader, company, trust, partnership, smsf
    client_status VARCHAR(30) NOT NULL DEFAULT 'active',    -- active, inactive, archived, prospect
    client_category VARCHAR(50),  -- small_business, corporate, individual, smsf
    client_tier VARCHAR(20),      -- bronze, silver, gold, platinum
    referral_source VARCHAR(100),
    
    -- ==================== CONTACT PERSON (8 fields) ====================
    primary_contact_first_name VARCHAR(100),
    primary_contact_last_name VARCHAR(100),
    primary_contact_title VARCHAR(50),
    primary_contact_email VARCHAR(255),
    primary_contact_phone VARCHAR(50),
    primary_contact_mobile VARCHAR(50),
    preferred_contact_method VARCHAR(20) DEFAULT 'email',  -- email, phone, sms
    preferred_contact_time VARCHAR(50),
    
    -- ==================== ADDRESS - PRIMARY (7 fields) ====================
    primary_address_line1 VARCHAR(255),
    primary_address_line2 VARCHAR(255),
    primary_suburb VARCHAR(100),
    primary_state VARCHAR(20),
    primary_postcode VARCHAR(10),
    primary_country VARCHAR(50) DEFAULT 'Australia',
    primary_address_type VARCHAR(20) DEFAULT 'business',  -- business, residential, postal
    
    -- ==================== ADDRESS - POSTAL (6 fields) ====================
    postal_address_line1 VARCHAR(255),
    postal_address_line2 VARCHAR(255),
    postal_suburb VARCHAR(100),
    postal_state VARCHAR(20),
    postal_postcode VARCHAR(10),
    postal_country VARCHAR(50) DEFAULT 'Australia',
    
    -- ==================== TAX IDENTIFIERS (8 fields) ====================
    abn VARCHAR(20),
    abn_status VARCHAR(30),           -- active, cancelled
    abn_registration_date DATE,
    acn VARCHAR(15),
    tfn_encrypted VARCHAR(512),       -- Encrypted TFN
    tfn_last_four VARCHAR(4),         -- Last 4 digits for display
    tax_file_number_status VARCHAR(30),
    withholding_payer_number VARCHAR(20),
    
    -- ==================== GST (6 fields) ====================
    gst_registered BOOLEAN DEFAULT FALSE,
    gst_registration_date DATE,
    gst_accounting_method VARCHAR(20) DEFAULT 'accrual',  -- cash, accrual
    gst_reporting_frequency VARCHAR(20) DEFAULT 'quarterly',  -- monthly, quarterly, annually
    gst_branch_number VARCHAR(10),
    gst_group_member BOOLEAN DEFAULT FALSE,
    
    -- ==================== BUSINESS DETAILS (8 fields) ====================
    industry_code VARCHAR(20),        -- ANZSIC code
    industry_description VARCHAR(255),
    business_description TEXT,
    date_established DATE,
    financial_year_end VARCHAR(10) DEFAULT '30-Jun',
    employees_count INTEGER,
    annual_turnover_range VARCHAR(50),
    registered_for_payg_withholding BOOLEAN DEFAULT FALSE,
    
    -- ==================== STAFF ASSIGNMENTS (4 fields) ====================
    assigned_partner_id UUID,
    assigned_manager_id UUID,
    assigned_accountant_id UUID,
    assigned_bookkeeper_id UUID,
    
    -- ==================== SERVICES & FEES (8 fields) ====================
    services_engaged JSONB DEFAULT '[]'::jsonb,  -- Array of service codes
    engagement_type VARCHAR(50),      -- full_service, bas_only, itr_only, bookkeeping
    fee_structure VARCHAR(50),        -- fixed, hourly, value_based
    standard_hourly_rate DECIMAL(10,2),
    monthly_retainer DECIMAL(10,2),
    billing_frequency VARCHAR(20) DEFAULT 'monthly',
    payment_terms INTEGER DEFAULT 14, -- Days
    credit_limit DECIMAL(10,2),
    
    -- ==================== INTEGRATIONS (6 fields) ====================
    xero_tenant_id VARCHAR(100),
    myob_company_file_id VARCHAR(100),
    quickbooks_realm_id VARCHAR(100),
    bank_feed_status VARCHAR(30),
    document_portal_enabled BOOLEAN DEFAULT TRUE,
    myfdc_linked BOOLEAN DEFAULT FALSE,
    
    -- ==================== COMPLIANCE (6 fields) ====================
    aml_kyc_verified BOOLEAN DEFAULT FALSE,
    aml_kyc_verified_date DATE,
    aml_risk_rating VARCHAR(20),      -- low, medium, high
    identity_verified BOOLEAN DEFAULT FALSE,
    identity_verified_date DATE,
    poa_on_file BOOLEAN DEFAULT FALSE, -- Power of Attorney
    
    -- ==================== NOTES & CUSTOM (4 fields) ====================
    internal_notes TEXT,
    client_notes TEXT,
    tags JSONB DEFAULT '[]'::jsonb,
    custom_fields JSONB DEFAULT '{}'::jsonb,
    
    -- ==================== METADATA (5 fields) ====================
    source_system VARCHAR(50),        -- myfdc, crm, manual, migration
    migrated_from VARCHAR(100),
    migration_date TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100)
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_client_profiles_person_id ON core.client_profiles(person_id);
CREATE INDEX IF NOT EXISTS idx_client_profiles_crm_client_id ON core.client_profiles(crm_client_id);
CREATE INDEX IF NOT EXISTS idx_client_profiles_client_code ON core.client_profiles(client_code);
CREATE INDEX IF NOT EXISTS idx_client_profiles_abn ON core.client_profiles(abn);
CREATE INDEX IF NOT EXISTS idx_client_profiles_status ON core.client_profiles(client_status);
CREATE INDEX IF NOT EXISTS idx_client_profiles_entity_type ON core.client_profiles(entity_type);
CREATE INDEX IF NOT EXISTS idx_client_profiles_assigned_partner ON core.client_profiles(assigned_partner_id);
CREATE INDEX IF NOT EXISTS idx_client_profiles_assigned_manager ON core.client_profiles(assigned_manager_id);
CREATE INDEX IF NOT EXISTS idx_client_profiles_created_at ON core.client_profiles(created_at);

-- Full-text search index on names
CREATE INDEX IF NOT EXISTS idx_client_profiles_names_search ON core.client_profiles 
    USING gin(to_tsvector('english', COALESCE(display_name, '') || ' ' || COALESCE(legal_name, '') || ' ' || COALESCE(trading_name, '')));

-- ============================================================
-- UPDATED_AT TRIGGER
-- ============================================================
CREATE OR REPLACE FUNCTION core.update_client_profiles_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_client_profiles_updated_at ON core.client_profiles;
CREATE TRIGGER trigger_client_profiles_updated_at
    BEFORE UPDATE ON core.client_profiles
    FOR EACH ROW
    EXECUTE FUNCTION core.update_client_profiles_timestamp();

-- ============================================================
-- COMMENTS
-- ============================================================
COMMENT ON TABLE core.client_profiles IS 'Extended client profiles with 86-field schema for comprehensive client data';
COMMENT ON COLUMN core.client_profiles.tfn_encrypted IS 'AES-256-GCM encrypted Tax File Number - use encryption utilities to read/write';
COMMENT ON COLUMN core.client_profiles.tfn_last_four IS 'Last 4 digits of TFN for display purposes only';
COMMENT ON COLUMN core.client_profiles.person_id IS 'Links to identity.person for unified identity';
COMMENT ON COLUMN core.client_profiles.services_engaged IS 'JSON array of service codes: ["BAS", "ITR", "BOOKKEEPING", "PAYROLL"]';

-- ============================================================
-- GRANT PERMISSIONS (adjust as needed)
-- ============================================================
-- GRANT SELECT, INSERT, UPDATE ON core.client_profiles TO fdccore;
-- GRANT USAGE ON SCHEMA core TO fdccore;
