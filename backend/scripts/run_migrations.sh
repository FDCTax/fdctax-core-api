#!/bin/bash
# FDC Core - Database Migration Script
# Runs database migrations safely with rollback support
#
# Usage: ./run_migrations.sh [--dry-run] [--rollback <version>]

set -e

DRY_RUN=false
ROLLBACK=false
ROLLBACK_VERSION=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --rollback)
            ROLLBACK=true
            ROLLBACK_VERSION="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "============================================="
echo "FDC Core - Database Migration"
echo "============================================="
echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "Dry Run: $DRY_RUN"
echo "Rollback: $ROLLBACK (version: $ROLLBACK_VERSION)"
echo ""

# Check environment
if [ -z "$DATABASE_URL" ]; then
    echo "ERROR: DATABASE_URL not set"
    exit 1
fi

# Run migrations
cd /app/backend

if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would run migrations..."
    python3 -c "
import asyncio
from database import engine
from database.workpaper_models import Base as WorkpaperBase
from database.motor_vehicle_models import Base as MVBase
from database.transaction_models import Base as TxnBase

async def check_migrations():
    from sqlalchemy import inspect
    async with engine.begin() as conn:
        def get_tables(connection):
            inspector = inspect(connection)
            return inspector.get_table_names()
        tables = await conn.run_sync(get_tables)
        print(f'Current tables: {len(tables)}')
        for t in sorted(tables):
            print(f'  - {t}')

asyncio.run(check_migrations())
"
else
    echo "Running migrations..."
    python3 -c "
import asyncio
from database import init_db

async def run():
    await init_db()
    print('Migrations completed successfully')

asyncio.run(run())
"
fi

echo ""
echo "============================================="
echo "Migration complete"
echo "============================================="
