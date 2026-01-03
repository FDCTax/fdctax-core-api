"""
MyFDC Data Tables Migration Script

Creates the database tables needed for MyFDC data intake:
- myfdc_educator_profiles
- myfdc_hours_worked
- myfdc_occupancy
- myfdc_diary_entries
- myfdc_expenses
- myfdc_attendance

Run: python create_myfdc_tables.py
"""

import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set")

# Ensure asyncpg driver is used (fix for sync driver injection)
if DATABASE_URL.startswith('postgresql://'):
    DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)
elif DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql+asyncpg://', 1)

engine = create_async_engine(DATABASE_URL, connect_args={'ssl': 'require'})


async def create_tables():
    """Create all MyFDC data tables."""
    
    async with engine.begin() as conn:
        # 1. Educator Profiles
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.myfdc_educator_profiles (
                id UUID PRIMARY KEY,
                client_id UUID NOT NULL,
                educator_name VARCHAR(255),
                phone VARCHAR(50),
                email VARCHAR(255),
                address_line1 VARCHAR(255),
                address_line2 VARCHAR(255),
                suburb VARCHAR(100),
                state VARCHAR(10),
                postcode VARCHAR(10),
                abn VARCHAR(20),
                service_approval_number VARCHAR(50),
                approval_start_date DATE,
                approval_expiry_date DATE,
                max_children INTEGER,
                qualifications JSONB DEFAULT '[]'::jsonb,
                first_aid_expiry DATE,
                wwcc_number VARCHAR(50),
                wwcc_expiry DATE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                created_by VARCHAR(100),
                updated_by VARCHAR(100),
                CONSTRAINT fk_educator_client FOREIGN KEY (client_id) 
                    REFERENCES public.client_profiles(id) ON DELETE CASCADE
            )
        """))
        print("✓ Created myfdc_educator_profiles")
        
        # 2. Hours Worked
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.myfdc_hours_worked (
                id UUID PRIMARY KEY,
                client_id UUID NOT NULL,
                work_date DATE NOT NULL,
                hours NUMERIC(4,2) NOT NULL,
                start_time VARCHAR(10),
                end_time VARCHAR(10),
                notes TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                created_by VARCHAR(100),
                CONSTRAINT fk_hours_client FOREIGN KEY (client_id) 
                    REFERENCES public.client_profiles(id) ON DELETE CASCADE
            )
        """))
        print("✓ Created myfdc_hours_worked")
        
        # 3. Occupancy
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.myfdc_occupancy (
                id UUID PRIMARY KEY,
                client_id UUID NOT NULL,
                occupancy_date DATE NOT NULL,
                number_of_children INTEGER NOT NULL,
                hours_per_day NUMERIC(4,2) NOT NULL,
                rooms_used JSONB DEFAULT '[]'::jsonb,
                room_details JSONB DEFAULT '[]'::jsonb,
                preschool_program BOOLEAN DEFAULT FALSE,
                notes TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                created_by VARCHAR(100),
                CONSTRAINT fk_occupancy_client FOREIGN KEY (client_id) 
                    REFERENCES public.client_profiles(id) ON DELETE CASCADE
            )
        """))
        print("✓ Created myfdc_occupancy")
        
        # 4. Diary Entries
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.myfdc_diary_entries (
                id UUID PRIMARY KEY,
                client_id UUID NOT NULL,
                entry_date DATE NOT NULL,
                description TEXT NOT NULL,
                category VARCHAR(50) DEFAULT 'activity',
                child_name VARCHAR(100),
                has_photos BOOLEAN DEFAULT FALSE,
                photo_count INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                created_by VARCHAR(100),
                CONSTRAINT fk_diary_client FOREIGN KEY (client_id) 
                    REFERENCES public.client_profiles(id) ON DELETE CASCADE
            )
        """))
        print("✓ Created myfdc_diary_entries")
        
        # 5. Expenses
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.myfdc_expenses (
                id UUID PRIMARY KEY,
                client_id UUID NOT NULL,
                expense_date DATE NOT NULL,
                amount NUMERIC(12,2) NOT NULL,
                category VARCHAR(50) NOT NULL,
                description TEXT,
                gst_included BOOLEAN DEFAULT TRUE,
                tax_deductible BOOLEAN DEFAULT TRUE,
                business_percentage NUMERIC(5,2) DEFAULT 100,
                receipt_number VARCHAR(100),
                vendor VARCHAR(255),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                created_by VARCHAR(100),
                CONSTRAINT fk_expense_client FOREIGN KEY (client_id) 
                    REFERENCES public.client_profiles(id) ON DELETE CASCADE
            )
        """))
        print("✓ Created myfdc_expenses")
        
        # 6. Attendance
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.myfdc_attendance (
                id UUID PRIMARY KEY,
                client_id UUID NOT NULL,
                child_name VARCHAR(100) NOT NULL,
                attendance_date DATE NOT NULL,
                hours NUMERIC(4,2) NOT NULL,
                arrival_time VARCHAR(10),
                departure_time VARCHAR(10),
                ccs_hours NUMERIC(4,2),
                notes TEXT,
                absent BOOLEAN DEFAULT FALSE,
                absence_reason TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                created_by VARCHAR(100),
                CONSTRAINT fk_attendance_client FOREIGN KEY (client_id) 
                    REFERENCES public.client_profiles(id) ON DELETE CASCADE
            )
        """))
        print("✓ Created myfdc_attendance")
        
        # Create indexes for performance
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_hours_client_date ON public.myfdc_hours_worked(client_id, work_date)",
            "CREATE INDEX IF NOT EXISTS idx_occupancy_client_date ON public.myfdc_occupancy(client_id, occupancy_date)",
            "CREATE INDEX IF NOT EXISTS idx_diary_client_date ON public.myfdc_diary_entries(client_id, entry_date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_client_date ON public.myfdc_expenses(client_id, expense_date)",
            "CREATE INDEX IF NOT EXISTS idx_attendance_client_date ON public.myfdc_attendance(client_id, attendance_date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_category ON public.myfdc_expenses(client_id, category)",
            "CREATE INDEX IF NOT EXISTS idx_educator_profile_client ON public.myfdc_educator_profiles(client_id)"
        ]
        
        for idx_sql in indexes:
            await conn.execute(text(idx_sql))
        
        print("✓ Created indexes")
        print("\n✅ All MyFDC tables created successfully!")


if __name__ == "__main__":
    asyncio.run(create_tables())
