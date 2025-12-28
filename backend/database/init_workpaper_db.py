"""
FDC Core Workpaper Platform - Database Initialization

Creates all workpaper tables in the PostgreSQL database.
Run this script to set up the database schema.
"""

import asyncio
import logging
from pathlib import Path

from sqlalchemy import text
from dotenv import load_dotenv

# Load environment variables
ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / '.env')

from database.connection import engine, Base
from database.workpaper_models import (
    WorkpaperJobDB, ModuleInstanceDB, TransactionDB, TransactionOverrideDB,
    OverrideRecordDB, QueryDB, QueryMessageDB, TaskDB,
    FreezeSnapshotDB, WorkpaperAuditLogDB
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_tables():
    """Create all workpaper tables"""
    logger.info("Creating workpaper database tables...")
    
    async with engine.begin() as conn:
        # Create all tables defined in Base
        await conn.run_sync(Base.metadata.create_all)
        
        # Verify tables were created
        result = await conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name LIKE 'workpaper_%'
            ORDER BY table_name
        """))
        tables = [row[0] for row in result.fetchall()]
        
        logger.info(f"Created workpaper tables: {tables}")
        return tables


async def drop_tables():
    """Drop all workpaper tables (use with caution!)"""
    logger.info("Dropping workpaper database tables...")
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        logger.info("All workpaper tables dropped")


async def check_tables():
    """Check which tables exist"""
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """))
        tables = [row[0] for row in result.fetchall()]
        return tables


async def main():
    """Main initialization function"""
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "drop":
            await drop_tables()
        elif command == "check":
            tables = await check_tables()
            print(f"Existing tables: {tables}")
        elif command == "create":
            tables = await create_tables()
            print(f"Created tables: {tables}")
        else:
            print(f"Unknown command: {command}")
            print("Usage: python init_workpaper_db.py [create|drop|check]")
    else:
        # Default: create tables
        tables = await create_tables()
        print(f"Created tables: {tables}")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
