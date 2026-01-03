"""
Create Jobs Table Migration

Creates a general-purpose jobs table for CRM integration.
Different from workpaper_jobs which is year-based.
"""

import asyncio
from sqlalchemy import text
from database.connection import engine


async def create_jobs_table():
    """Create jobs table for CRM integration."""
    
    statements = [
        # Create job status enum type if not exists
        """
        DO $$ BEGIN
            CREATE TYPE job_status AS ENUM (
                'draft', 'pending', 'in_progress', 'review', 
                'completed', 'cancelled', 'on_hold'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """,
        
        # Create job type enum if not exists
        """
        DO $$ BEGIN
            CREATE TYPE job_type AS ENUM (
                'tax_return', 'bas', 'financial_statement', 
                'audit', 'bookkeeping', 'advisory', 'other'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """,
        
        # Create jobs table
        """
        CREATE TABLE IF NOT EXISTS public.jobs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            client_id UUID NOT NULL,
            
            -- Job identification
            name VARCHAR(255) NOT NULL,
            description TEXT,
            job_type VARCHAR(50) DEFAULT 'other',
            
            -- Period (flexible)
            period_start DATE,
            period_end DATE,
            financial_year VARCHAR(20),  -- e.g., "2025", "FY2025"
            
            -- Status tracking
            status VARCHAR(50) DEFAULT 'draft',
            priority VARCHAR(20) DEFAULT 'normal',  -- low, normal, high, urgent
            
            -- Assignment
            assigned_to UUID,  -- User ID
            assigned_team VARCHAR(100),
            
            -- Dates
            due_date TIMESTAMP WITH TIME ZONE,
            started_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE,
            
            -- Configuration (flexible JSON)
            config JSONB DEFAULT '{}',
            metadata JSONB DEFAULT '{}',
            
            -- Audit
            created_by UUID,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            
            -- References
            parent_job_id UUID REFERENCES public.jobs(id),
            workpaper_job_id VARCHAR(255),  -- Link to workpaper_jobs if applicable
            
            -- Soft delete
            is_deleted BOOLEAN DEFAULT FALSE,
            deleted_at TIMESTAMP WITH TIME ZONE
        );
        """,
        
        # Create indexes
        """
        CREATE INDEX IF NOT EXISTS idx_jobs_client_id ON public.jobs(client_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON public.jobs(status);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_jobs_type ON public.jobs(job_type);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_jobs_assigned_to ON public.jobs(assigned_to);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_jobs_due_date ON public.jobs(due_date);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON public.jobs(created_at);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_jobs_financial_year ON public.jobs(financial_year);
        """,
        
        # Add comment
        """
        COMMENT ON TABLE public.jobs IS 'General job management table for CRM integration';
        """
    ]
    
    async with engine.begin() as conn:
        print("Creating jobs table...")
        for i, stmt in enumerate(statements):
            try:
                await conn.execute(text(stmt))
                print(f"  ✓ Statement {i+1}/{len(statements)} executed")
            except Exception as e:
                print(f"  ⚠ Statement {i+1} warning: {e}")
        
        print("\n✅ Jobs table created successfully!")


if __name__ == "__main__":
    asyncio.run(create_jobs_table())
