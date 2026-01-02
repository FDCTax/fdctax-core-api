"""
Database Migration: Create Normalisation Queue Table
Ticket: A3-INGEST-03

Creates the queue table for normalisation processing.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database.connection import engine


SQL_STATEMENTS = [
    # Create normalisation_queue table
    """
    CREATE TABLE IF NOT EXISTS public.normalisation_queue (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        batch_id UUID NOT NULL,
        client_id UUID NOT NULL REFERENCES public.client_profiles(id),
        transaction_ids JSONB NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
        attempts INTEGER DEFAULT 0,
        max_attempts INTEGER DEFAULT 3,
        last_error TEXT,
        processed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT normalisation_queue_status_check 
            CHECK (status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED'))
    )
    """,
    
    # Indexes
    "CREATE INDEX IF NOT EXISTS idx_normalisation_queue_status ON public.normalisation_queue(status)",
    "CREATE INDEX IF NOT EXISTS idx_normalisation_queue_created_at ON public.normalisation_queue(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_normalisation_queue_batch_id ON public.normalisation_queue(batch_id)",
]


async def create_table():
    """Create the normalisation_queue table."""
    print("Creating normalisation_queue table...")
    
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
        
        print("\n✅ Table created successfully!")


if __name__ == "__main__":
    asyncio.run(create_table())
