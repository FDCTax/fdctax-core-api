"""
Database migration script for FDC Tax Core + CRM Sync
Creates all required tables in the PostgreSQL sandbox
"""
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

DATABASE_URL = os.environ.get('DATABASE_URL')

# Ensure asyncpg driver is used (fix for sync driver injection)
if DATABASE_URL:
    if DATABASE_URL.startswith('postgresql://'):
        DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)
        logger.info("Converted DATABASE_URL to use asyncpg driver")
    elif DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql+asyncpg://', 1)
        logger.info("Converted DATABASE_URL to use asyncpg driver")


async def create_tables():
    """Create all tables in the database"""
    
    engine = create_async_engine(
        DATABASE_URL,
        echo=True,
        connect_args={"ssl": "require"}
    )
    
    async with engine.begin() as conn:
        # Create ENUM types first
        logger.info("Creating ENUM types...")
        
        # User role enum
        await conn.execute(text("""
            DO $$ BEGIN
                CREATE TYPE user_role AS ENUM ('educator', 'admin', 'internal');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        
        # GST cycle enum
        await conn.execute(text("""
            DO $$ BEGIN
                CREATE TYPE gst_cycle AS ENUM ('quarterly', 'annual', 'none');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        
        # Task status enum
        await conn.execute(text("""
            DO $$ BEGIN
                CREATE TYPE task_status AS ENUM ('pending', 'in_progress', 'complete');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        
        # Task source enum
        await conn.execute(text("""
            DO $$ BEGIN
                CREATE TYPE task_source AS ENUM ('internal_crm', 'luna', 'system');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        
        # KB classification enum
        await conn.execute(text("""
            DO $$ BEGIN
                CREATE TYPE kb_classification AS ENUM ('Exclusive A', 'Exclusive B', 'Problem', 'Special');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        
        logger.info("Creating users table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email VARCHAR(255) UNIQUE NOT NULL,
                first_name VARCHAR(100) NOT NULL,
                last_name VARCHAR(100) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                role user_role DEFAULT 'educator'
            );
        """))
        
        logger.info("Creating user_profiles table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                fdc_percent INTEGER DEFAULT 0,
                gst_registered BOOLEAN DEFAULT FALSE,
                gst_cycle gst_cycle DEFAULT 'none',
                oscar_enabled BOOLEAN DEFAULT FALSE,
                levy_auto_enabled BOOLEAN DEFAULT FALSE,
                setup_state JSONB DEFAULT '{
                    "welcome_complete": false,
                    "fdc_percent_set": false,
                    "gst_status_set": false,
                    "oscar_intro_seen": false,
                    "levy_auto_enabled": false
                }'::jsonb,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE,
                UNIQUE(user_id)
            );
        """))
        
        logger.info("Creating tasks table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tasks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                due_date DATE,
                status task_status DEFAULT 'pending',
                source task_source DEFAULT 'system',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE
            );
        """))
        
        logger.info("Creating kb_entries table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS kb_entries (
                id SERIAL PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                tags VARCHAR(500),
                variations VARCHAR(500),
                answer TEXT NOT NULL,
                classification kb_classification NOT NULL,
                exclusive_note TEXT,
                ato_source VARCHAR(255),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE
            );
        """))
        
        # Create indexes
        logger.info("Creating indexes...")
        
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        """))
        
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
        """))
        
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_user_profiles_user_id ON user_profiles(user_id);
        """))
        
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id);
        """))
        
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        """))
        
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);
        """))
        
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_kb_entries_classification ON kb_entries(classification);
        """))
        
        # Full-text search index for KB
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_kb_entries_search 
            ON kb_entries USING gin(to_tsvector('english', title || ' ' || COALESCE(tags, '') || ' ' || COALESCE(variations, '')));
        """))
        
        logger.info("All tables and indexes created successfully!")
    
    await engine.dispose()


async def verify_tables():
    """Verify that all tables were created"""
    engine = create_async_engine(
        DATABASE_URL,
        connect_args={"ssl": "require"}
    )
    
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """))
        tables = [row[0] for row in result.fetchall()]
        
        logger.info(f"Tables in database: {tables}")
        
        expected_tables = ['kb_entries', 'tasks', 'user_profiles', 'users']
        for table in expected_tables:
            if table in tables:
                logger.info(f"  ✓ {table}")
            else:
                logger.error(f"  ✗ {table} - MISSING!")
    
    await engine.dispose()


async def seed_test_data():
    """Seed some test data for development"""
    engine = create_async_engine(
        DATABASE_URL,
        connect_args={"ssl": "require"}
    )
    
    async with engine.begin() as conn:
        # Check if test user exists
        result = await conn.execute(text(
            "SELECT id FROM users WHERE email = 'test@fdctax.com'"
        ))
        if result.fetchone():
            logger.info("Test data already exists, skipping seed")
            await engine.dispose()
            return
        
        logger.info("Seeding test data...")
        
        # Create test user
        result = await conn.execute(text("""
            INSERT INTO users (email, first_name, last_name, role)
            VALUES ('test@fdctax.com', 'Test', 'Educator', 'educator')
            RETURNING id;
        """))
        user_id = result.fetchone()[0]
        logger.info(f"Created test user: {user_id}")
        
        # Create profile for test user
        await conn.execute(text("""
            INSERT INTO user_profiles (user_id, fdc_percent, gst_registered, gst_cycle)
            VALUES (:user_id, 80, true, 'quarterly');
        """), {"user_id": user_id})
        logger.info("Created test user profile")
        
        # Create a test task
        await conn.execute(text("""
            INSERT INTO tasks (user_id, title, description, status, source)
            VALUES (:user_id, 'Review quarterly BAS', 'Please review your BAS before submission deadline', 'pending', 'internal_crm');
        """), {"user_id": user_id})
        logger.info("Created test task")
        
        # Create test KB entry
        await conn.execute(text("""
            INSERT INTO kb_entries (title, tags, variations, answer, classification)
            VALUES (
                'FDC Percentage Calculation',
                'fdc,percentage,calculation,rate',
                'how to calculate fdc, what is fdc rate, fdc percent',
                '<p>The FDC percentage is the proportion of your income that comes from Family Day Care services. This typically ranges from 70-90% for most educators.</p>',
                'Exclusive A'
            );
        """))
        logger.info("Created test KB entry")
        
        # Create admin user
        result = await conn.execute(text("""
            INSERT INTO users (email, first_name, last_name, role)
            VALUES ('admin@fdctax.com', 'Admin', 'User', 'admin')
            RETURNING id;
        """))
        admin_id = result.fetchone()[0]
        logger.info(f"Created admin user: {admin_id}")
        
        logger.info("Test data seeded successfully!")
    
    await engine.dispose()


async def main():
    """Run migrations"""
    logger.info("=" * 50)
    logger.info("FDC Tax Core - Database Migration")
    logger.info("=" * 50)
    
    await create_tables()
    await verify_tables()
    # NOTE: Test data seeding removed for production deployment
    # Use /api/auth/admin/register to create users manually
    
    logger.info("=" * 50)
    logger.info("Migration complete!")
    logger.info("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
