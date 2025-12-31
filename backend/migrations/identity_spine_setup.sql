-- Identity Spine v1 - Core Database Schema
-- This creates the unified identity model linking MyFDC and CRM
-- Run with admin privileges

-- =============================================================================
-- PERSON TABLE - Central Identity
-- The single source of truth for user identity
-- =============================================================================

CREATE TABLE IF NOT EXISTS person (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    mobile VARCHAR(50),
    phone VARCHAR(50),
    date_of_birth DATE,
    status VARCHAR(30) DEFAULT 'active',  -- active, inactive, suspended, deleted
    email_verified BOOLEAN DEFAULT FALSE,
    mobile_verified BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_person_email ON person(email);
CREATE INDEX IF NOT EXISTS idx_person_status ON person(status);
CREATE INDEX IF NOT EXISTS idx_person_mobile ON person(mobile);

-- =============================================================================
-- MYFDC_ACCOUNT TABLE - MyFDC User Accounts
-- Links to person for MyFDC-specific data
-- =============================================================================

CREATE TABLE IF NOT EXISTS myfdc_account (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    username VARCHAR(100),
    password_hash VARCHAR(255),
    auth_provider VARCHAR(50) DEFAULT 'local',  -- local, google, microsoft
    auth_provider_id VARCHAR(255),
    last_login_at TIMESTAMP WITH TIME ZONE,
    login_count INTEGER DEFAULT 0,
    settings JSONB DEFAULT '{}',
    preferences JSONB DEFAULT '{}',
    onboarding_completed BOOLEAN DEFAULT FALSE,
    onboarding_step INTEGER DEFAULT 0,
    status VARCHAR(30) DEFAULT 'active',  -- active, pending, suspended
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT unique_myfdc_person UNIQUE (person_id)
);

CREATE INDEX IF NOT EXISTS idx_myfdc_account_person ON myfdc_account(person_id);
CREATE INDEX IF NOT EXISTS idx_myfdc_account_status ON myfdc_account(status);

-- =============================================================================
-- CRM_CLIENT TABLE - CRM Client Records
-- Links to person for tax/accounting data
-- =============================================================================

CREATE TABLE IF NOT EXISTS crm_client_identity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    client_code VARCHAR(50) UNIQUE,  -- External client reference (e.g., CLIENT-001)
    abn VARCHAR(20),
    tfn_encrypted VARCHAR(255),  -- Encrypted TFN
    business_name VARCHAR(255),
    entity_type VARCHAR(50),  -- individual, sole_trader, company, trust, partnership
    gst_registered BOOLEAN DEFAULT FALSE,
    gst_registration_date DATE,
    tax_agent_id VARCHAR(50),
    assigned_staff_id UUID,
    source VARCHAR(50),  -- referral, website, walk-in, etc.
    notes TEXT,
    tags JSONB DEFAULT '[]',
    custom_fields JSONB DEFAULT '{}',
    status VARCHAR(30) DEFAULT 'active',  -- active, inactive, archived
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT unique_crm_person UNIQUE (person_id)
);

CREATE INDEX IF NOT EXISTS idx_crm_client_person ON crm_client_identity(person_id);
CREATE INDEX IF NOT EXISTS idx_crm_client_code ON crm_client_identity(client_code);
CREATE INDEX IF NOT EXISTS idx_crm_client_abn ON crm_client_identity(abn);
CREATE INDEX IF NOT EXISTS idx_crm_client_status ON crm_client_identity(status);

-- =============================================================================
-- ENGAGEMENT_PROFILE TABLE - Service Engagement Flags
-- Tracks what services each client is using
-- =============================================================================

CREATE TABLE IF NOT EXISTS engagement_profile (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    
    -- Account flags
    is_myfdc_user BOOLEAN DEFAULT FALSE,
    is_crm_client BOOLEAN DEFAULT FALSE,
    
    -- Self-service flags
    has_ocr BOOLEAN DEFAULT FALSE,
    is_diy_bas_user BOOLEAN DEFAULT FALSE,
    is_diy_itr_user BOOLEAN DEFAULT FALSE,
    
    -- Full-service flags
    is_full_service_bas_client BOOLEAN DEFAULT FALSE,
    is_full_service_itr_client BOOLEAN DEFAULT FALSE,
    is_bookkeeping_client BOOLEAN DEFAULT FALSE,
    is_payroll_client BOOLEAN DEFAULT FALSE,
    
    -- Subscription info
    subscription_tier VARCHAR(50),  -- free, basic, pro, enterprise
    subscription_start_date DATE,
    subscription_end_date DATE,
    
    -- Engagement metrics
    first_engagement_at TIMESTAMP WITH TIME ZONE,
    last_engagement_at TIMESTAMP WITH TIME ZONE,
    total_interactions INTEGER DEFAULT 0,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT unique_engagement_person UNIQUE (person_id)
);

CREATE INDEX IF NOT EXISTS idx_engagement_person ON engagement_profile(person_id);
CREATE INDEX IF NOT EXISTS idx_engagement_myfdc ON engagement_profile(is_myfdc_user);
CREATE INDEX IF NOT EXISTS idx_engagement_crm ON engagement_profile(is_crm_client);

-- =============================================================================
-- IDENTITY_LINK_LOG TABLE - Audit trail for identity operations
-- =============================================================================

CREATE TABLE IF NOT EXISTS identity_link_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES person(id),
    action VARCHAR(50) NOT NULL,  -- create, link, merge, unlink, update
    source_type VARCHAR(50),  -- myfdc, crm, admin, migration
    source_id VARCHAR(100),
    target_type VARCHAR(50),
    target_id VARCHAR(100),
    performed_by VARCHAR(100),
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_identity_log_person ON identity_link_log(person_id);
CREATE INDEX IF NOT EXISTS idx_identity_log_action ON identity_link_log(action);
CREATE INDEX IF NOT EXISTS idx_identity_log_created ON identity_link_log(created_at);

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create triggers for updated_at
DROP TRIGGER IF EXISTS update_person_updated_at ON person;
CREATE TRIGGER update_person_updated_at
    BEFORE UPDATE ON person
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_myfdc_account_updated_at ON myfdc_account;
CREATE TRIGGER update_myfdc_account_updated_at
    BEFORE UPDATE ON myfdc_account
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_crm_client_identity_updated_at ON crm_client_identity;
CREATE TRIGGER update_crm_client_identity_updated_at
    BEFORE UPDATE ON crm_client_identity
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_engagement_profile_updated_at ON engagement_profile;
CREATE TRIGGER update_engagement_profile_updated_at
    BEFORE UPDATE ON engagement_profile
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- VERIFICATION
-- =============================================================================

SELECT 'Identity Spine tables created successfully' AS status
WHERE EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'person')
  AND EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'myfdc_account')
  AND EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'crm_client_identity')
  AND EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'engagement_profile');
