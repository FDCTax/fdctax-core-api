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


# Split into individual statements
SQL_STATEMENTS = [
    # Create ingested_transactions table
    """
    CREATE TABLE IF NOT EXISTS public.ingested_transactions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        source VARCHAR(20) NOT NULL,
        source_transaction_id VARCHAR(255) NOT NULL,
        client_id UUID NOT NULL REFERENCES public.client_profiles(id),
        ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        transaction_date DATE NOT NULL,
        transaction_type VARCHAR(20) NOT NULL,
        amount DECIMAL(12, 2) NOT NULL,
        currency VARCHAR(3) DEFAULT 'AUD',
        gst_included BOOLEAN NOT NULL DEFAULT true,
        gst_amount DECIMAL(12, 2),
        description TEXT,
        notes TEXT,
        category_raw VARCHAR(255),
        category_normalised VARCHAR(255),
        category_code VARCHAR(50),
        business_percentage INTEGER DEFAULT 100 CHECK (business_percentage >= 0 AND business_percentage <= 100),
        vendor VARCHAR(255),
        receipt_number VARCHAR(100),
        attachments JSONB DEFAULT '[]'::jsonb,
        status VARCHAR(30) NOT NULL DEFAULT 'INGESTED',
        error_message TEXT,
        audit JSONB NOT NULL DEFAULT '[]'::jsonb,
        raw_payload JSONB,
        metadata JSONB,
        bookkeeping_transaction_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ingested_transactions_source_check 
            CHECK (source IN ('MYFDC', 'OCR', 'BANK_FEED', 'MANUAL')),
        CONSTRAINT ingested_transactions_type_check 
            CHECK (transaction_type IN ('INCOME', 'EXPENSE', 'TRANSFER', 'UNKNOWN')),
        CONSTRAINT ingested_transactions_status_check 
            CHECK (status IN ('INGESTED', 'NORMALISED', 'READY_FOR_BOOKKEEPING', 'ERROR'))
    )
    """,
    
    # Indexes
    "CREATE INDEX IF NOT EXISTS idx_ingested_transactions_client_id ON public.ingested_transactions(client_id)",
    "CREATE INDEX IF NOT EXISTS idx_ingested_transactions_source ON public.ingested_transactions(source)",
    "CREATE INDEX IF NOT EXISTS idx_ingested_transactions_status ON public.ingested_transactions(status)",
    "CREATE INDEX IF NOT EXISTS idx_ingested_transactions_transaction_date ON public.ingested_transactions(transaction_date)",
    "CREATE INDEX IF NOT EXISTS idx_ingested_transactions_ingested_at ON public.ingested_transactions(ingested_at)",
    "CREATE INDEX IF NOT EXISTS idx_ingested_transactions_source_txn_id ON public.ingested_transactions(source, source_transaction_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_ingested_transactions_unique_source ON public.ingested_transactions(source, source_transaction_id, client_id)",
    
    # Create ingestion_attachments table
    """
    CREATE TABLE IF NOT EXISTS public.ingestion_attachments (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        transaction_id UUID REFERENCES public.ingested_transactions(id) ON DELETE SET NULL,
        client_id UUID NOT NULL REFERENCES public.client_profiles(id),
        file_name VARCHAR(500) NOT NULL,
        file_type VARCHAR(100) NOT NULL,
        file_size INTEGER NOT NULL,
        storage_path TEXT NOT NULL,
        ocr_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
        ocr_result JSONB,
        ocr_processed_at TIMESTAMPTZ,
        ocr_error TEXT,
        uploaded_by VARCHAR(36),
        uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        metadata JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ingestion_attachments_ocr_status_check 
            CHECK (ocr_status IN ('PENDING', 'PROCESSED', 'FAILED'))
    )
    """,
    
    # Attachment indexes
    "CREATE INDEX IF NOT EXISTS idx_ingestion_attachments_transaction_id ON public.ingestion_attachments(transaction_id)",
    "CREATE INDEX IF NOT EXISTS idx_ingestion_attachments_client_id ON public.ingestion_attachments(client_id)",
    "CREATE INDEX IF NOT EXISTS idx_ingestion_attachments_ocr_status ON public.ingestion_attachments(ocr_status)",
]


async def create_tables():
    """Create the ingested_transactions and ingestion_attachments tables."""
    print("Creating ingested_transactions and ingestion_attachments tables...")
    
    async with engine.begin() as conn:
        for i, sql in enumerate(SQL_STATEMENTS):
            try:
                await conn.execute(text(sql))
                print(f"  ✓ Statement {i+1}/{len(SQL_STATEMENTS)} executed")
            except Exception as e:
                if "already exists" in str(e).lower():
                    print(f"  ✓ Statement {i+1}/{len(SQL_STATEMENTS)} (already exists)")
                else:
                    print(f"  ✗ Statement {i+1}/{len(SQL_STATEMENTS)} failed: {e}")
                    raise
        
        print("\n✅ Tables created successfully!")
        
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


async def drop_tables():
    """Drop the tables (for testing)."""
    print("Dropping tables...")
    async with engine.begin() as conn:
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
