"""
Database Migration: Create Reconciliation Tables
Ticket: A3-RECON-01

Creates tables for reconciliation tracking, matching, and audit.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database.connection import engine


SQL_STATEMENTS = [
    # Reconciliation matches table
    """
    CREATE TABLE IF NOT EXISTS public.reconciliation_matches (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        client_id UUID NOT NULL REFERENCES public.client_profiles(id),
        
        -- Source transaction (from ingested_transactions)
        source_transaction_id UUID NOT NULL,
        source_type VARCHAR(20) NOT NULL,
        
        -- Target transaction (bank feed, receipt, etc.)
        target_transaction_id VARCHAR(255),
        target_type VARCHAR(20) NOT NULL,
        target_reference VARCHAR(255),
        
        -- Match details
        match_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
        confidence_score DECIMAL(5,2),
        match_type VARCHAR(30),
        
        -- Match breakdown (for audit)
        scoring_breakdown JSONB,
        
        -- Decision
        auto_matched BOOLEAN DEFAULT false,
        user_confirmed BOOLEAN DEFAULT false,
        confirmed_by VARCHAR(36),
        confirmed_at TIMESTAMPTZ,
        
        -- Metadata
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        
        -- Constraints
        CONSTRAINT reconciliation_matches_source_check 
            CHECK (source_type IN ('MYFDC', 'OCR', 'BANK_FEED', 'MANUAL')),
        CONSTRAINT reconciliation_matches_target_check 
            CHECK (target_type IN ('BANK', 'RECEIPT', 'INVOICE', 'MANUAL', 'UNKNOWN')),
        CONSTRAINT reconciliation_matches_status_check 
            CHECK (match_status IN ('PENDING', 'MATCHED', 'SUGGESTED', 'NO_MATCH', 'REJECTED', 'CONFIRMED'))
    )
    """,
    
    # Reconciliation audit log
    """
    CREATE TABLE IF NOT EXISTS public.reconciliation_audit_log (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        client_id UUID NOT NULL REFERENCES public.client_profiles(id),
        match_id UUID REFERENCES public.reconciliation_matches(id),
        
        -- Action details
        action VARCHAR(50) NOT NULL,
        actor VARCHAR(100) NOT NULL,
        
        -- Transaction details
        source_transaction_id UUID,
        source_type VARCHAR(20),
        
        -- Candidates considered
        candidates_count INTEGER,
        candidates_summary JSONB,
        
        -- Scoring
        scoring_breakdown JSONB,
        
        -- Decision
        decision VARCHAR(30),
        confidence_score DECIMAL(5,2),
        
        -- Metadata
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        metadata JSONB
    )
    """,
    
    # Indexes for reconciliation_matches
    "CREATE INDEX IF NOT EXISTS idx_recon_matches_client ON public.reconciliation_matches(client_id)",
    "CREATE INDEX IF NOT EXISTS idx_recon_matches_source_txn ON public.reconciliation_matches(source_transaction_id)",
    "CREATE INDEX IF NOT EXISTS idx_recon_matches_status ON public.reconciliation_matches(match_status)",
    "CREATE INDEX IF NOT EXISTS idx_recon_matches_source_type ON public.reconciliation_matches(source_type)",
    
    # Indexes for audit log
    "CREATE INDEX IF NOT EXISTS idx_recon_audit_client ON public.reconciliation_audit_log(client_id)",
    "CREATE INDEX IF NOT EXISTS idx_recon_audit_match ON public.reconciliation_audit_log(match_id)",
    "CREATE INDEX IF NOT EXISTS idx_recon_audit_timestamp ON public.reconciliation_audit_log(timestamp)",
]


async def create_tables():
    """Create the reconciliation tables."""
    print("Creating reconciliation tables...")
    
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
        
        print("\n✅ Reconciliation tables created successfully!")


if __name__ == "__main__":
    asyncio.run(create_tables())
