import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from dotenv import load_dotenv
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Load environment variables
ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / '.env')

# Get database URL
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# CRITICAL FIX: Ensure asyncpg driver is used
# Production Secret Authority injects postgresql:// but we need postgresql+asyncpg://
# This conversion MUST happen before create_async_engine is called
original_url = DATABASE_URL
if DATABASE_URL.startswith('postgresql://') and '+asyncpg' not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)
    print(f"[DB] Converted postgresql:// to postgresql+asyncpg://")
elif DATABASE_URL.startswith('postgres://') and '+asyncpg' not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql+asyncpg://', 1)
    print(f"[DB] Converted postgres:// to postgresql+asyncpg://")

# Verify the URL has asyncpg driver
if '+asyncpg' not in DATABASE_URL:
    raise ValueError(f"DATABASE_URL must use asyncpg driver. Got: {DATABASE_URL[:50]}...")

print(f"[DB] Using async driver: {DATABASE_URL.split('@')[0].split('/')[-1] if '@' in DATABASE_URL else 'asyncpg'}")

# Create async engine with SSL
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args={
        "ssl": "require"
    }
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    """Dependency to get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Initialize database connection and verify tables exist"""
    try:
        async with engine.begin() as conn:
            # Test connection
            result = await conn.execute(text("SELECT 1"))
            logger.info("PostgreSQL connection successful")
            
            # Check if tables exist
            tables_query = text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)
            result = await conn.execute(tables_query)
            tables = [row[0] for row in result.fetchall()]
            logger.info(f"Available tables: {tables}")
            
            return True
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        raise
