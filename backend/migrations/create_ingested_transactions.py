"""
Database Migration Script: Create Ingested Transactions Table
Ticket: A3-INGEST-01

Creates the unified ingestion schema table for all inbound transactions.

Run this script directly to create the table:
    cd /app/backend && python migrations/create_ingested_transactions.py
"""

import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database.connection import engine


CREATE_TABLE_SQL = """
-- ================================================================
-- Ingested Transactions Table (A3-INGEST-01)
-- Unified schema for all inbound transactions
-- ================================================================

CREATE TABLE IF NOT EXISTS public.ingested_transactions (
    -- Primary Key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Source Identification
    source VARCHAR(20) NOT NULL,  -- MYFDC, OCR, BANK_FEED, MANUAL
    source_transaction_id VARCHAR(255) NOT NULL,
    client_id UUID NOT NULL REFERENCES public.client_profiles(id),
    
    -- Timestamps
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    transaction_date DATE NOT NULL,
    
    -- Transaction Details
    transaction_type VARCHAR(20) NOT NULL,  -- INCOME, EXPENSE, TRANSFER, UNKNOWN
    amount DECIMAL(12, 2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'AUD',
    
    -- GST Details
    gst_included BOOLEAN NOT NULL DEFAULT true,
    gst_amount DECIMAL(12, 2),
    
    -- Description & Notes
    description TEXT,
    notes TEXT,
    
    -- Category Mapping
    category_raw VARCHAR(255),
    category_normalised VARCHAR(255),
    category_code VARCHAR(50),
    
    -- Business Use
    business_percentage INTEGER DEFAULT 100 CHECK (business_percentage >= 0 AND business_percentage <= 100),
    
    -- Vendor/Payee
    vendor VARCHAR(255),
    receipt_number VARCHAR(100),
    
    -- Attachments (JSONB array of AttachmentRef objects)
    attachments JSONB DEFAULT '[]'::jsonb,
    
    -- Lifecycle Status
    status VARCHAR(30) NOT NULL DEFAULT 'INGESTED',  -- INGESTED, NORMALISED, READY_FOR_BOOKKEEPING, ERROR
    error_message TEXT,
    
    -- Audit Trail (JSONB array of AuditEntry objects)
    audit JSONB NOT NULL DEFAULT '[]'::jsonb,
    
    -- Metadata
    raw_payload JSONB,
    metadata JSONB,
    
    -- Bookkeeping Link
    bookkeeping_transaction_id UUID,
    
    -- Record timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT ingested_transactions_source_check 
        CHECK (source IN ('MYFDC', 'OCR', 'BANK_FEED', 'MANUAL')),
    CONSTRAINT ingested_transactions_type_check 
        CHECK (transaction_type IN ('INCOME', 'EXPENSE', 'TRANSFER', 'UNKNOWN')),
    CONSTRAINT ingested_transactions_status_check 
        CHECK (status IN ('INGESTED', 'NORMALISED', 'READY_FOR_BOOKKEEPING', 'ERROR'))
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_ingested_transactions_client_id 
    ON public.ingested_transactions(client_id);

CREATE INDEX IF NOT EXISTS idx_ingested_transactions_source 
    ON public.ingested_transactions(source);

CREATE INDEX IF NOT EXISTS idx_ingested_transactions_status 
    ON public.ingested_transactions(status);

CREATE INDEX IF NOT EXISTS idx_ingested_transactions_transaction_date 
    ON public.ingested_transactions(transaction_date);

CREATE INDEX IF NOT EXISTS idx_ingested_transactions_ingested_at 
    ON public.ingested_transactions(ingested_at);

CREATE INDEX IF NOT EXISTS idx_ingested_transactions_source_txn_id 
    ON public.ingested_transactions(source, source_transaction_id);

-- Unique constraint to prevent duplicate ingestion from same source
CREATE UNIQUE INDEX IF NOT EXISTS idx_ingested_transactions_unique_source 
    ON public.ingested_transactions(source, source_transaction_id, client_id);

-- Comments
COMMENT ON TABLE public.ingested_transactions IS 
    'Unified ingestion schema for all inbound transactions (A3-INGEST-01)';

COMMENT ON COLUMN public.ingested_transactions.source IS 
    'Ingestion origin: MYFDC, OCR, BANK_FEED, MANUAL';

COMMENT ON COLUMN public.ingested_transactions.status IS 
    'Lifecycle state: INGESTED → NORMALISED → READY_FOR_BOOKKEEPING or ERROR';

COMMENT ON COLUMN public.ingested_transactions.audit IS 
    'Full audit trail of all transformations for ATO defensibility';

-- ================================================================
-- Attachments Reference Table (for file storage tracking)
-- ================================================================

CREATE TABLE IF NOT EXISTS public.ingestion_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Link to transaction (optional - can be standalone)
    transaction_id UUID REFERENCES public.ingested_transactions(id) ON DELETE SET NULL,
    client_id UUID NOT NULL REFERENCES public.client_profiles(id),
    
    -- File Information
    file_name VARCHAR(500) NOT NULL,
    file_type VARCHAR(100) NOT NULL,  -- MIME type
    file_size INTEGER NOT NULL,  -- bytes
    storage_path TEXT NOT NULL,  -- internal storage reference
    
    -- OCR Status
    ocr_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',  -- PENDING, PROCESSED, FAILED
    ocr_result JSONB,
    ocr_processed_at TIMESTAMPTZ,
    ocr_error TEXT,
    
    -- Metadata
    uploaded_by VARCHAR(36),
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB,
    
    -- Record timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT ingestion_attachments_ocr_status_check 
        CHECK (ocr_status IN ('PENDING', 'PROCESSED', 'FAILED'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_ingestion_attachments_transaction_id 
    ON public.ingestion_attachments(transaction_id);

CREATE INDEX IF NOT EXISTS idx_ingestion_attachments_client_id 
    ON public.ingestion_attachments(client_id);

CREATE INDEX IF NOT EXISTS idx_ingestion_attachments_ocr_status 
    ON public.ingestion_attachments(ocr_status);

-- Comment
COMMENT ON TABLE public.ingestion_attachments IS 
    'Attachment storage for ingested transactions, supports OCR enrichment';
"""


async def create_tables():
    """Create the ingested_transactions and ingestion_attachments tables."""
    print("Creating ingested_transactions and ingestion_attachments tables...")
    
    async with async_engine.begin() as conn:
        try:
            await conn.execute(text(CREATE_TABLE_SQL))
            print("✅ Tables created successfully!")
            
            # Verify tables exist
            result = await conn.execute(text("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name IN ('ingested_transactions', 'ingestion_attachments')
                ORDER BY table_name
            """))
            tables = [row[0] for row in result.fetchall()]
            print(f"✅ Verified tables: {tables}")
            
            # Show column count
            for table in tables:
                result = await conn.execute(text(f"""
                    SELECT COUNT(*) FROM information_schema.columns 
                    WHERE table_name = '{table}'
                """))
                col_count = result.scalar()
                print(f"   - {table}: {col_count} columns")
                
        except Exception as e:
            print(f"❌ Error creating tables: {e}")
            raise


async def drop_tables():
    """Drop the tables (for testing)."""
    print("Dropping tables...")
    async with async_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS public.ingestion_attachments CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS public.ingested_transactions CASCADE"))
        print("✅ Tables dropped")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Manage ingested_transactions table")
    parser.add_argument("--drop", action="store_true", help="Drop tables instead of create")
    args = parser.parse_args()
    
    if args.drop:
        asyncio.run(drop_tables())
    else:
        asyncio.run(create_tables())
