from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import traceback

# Load environment variables first
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Import configuration
from config import get_settings, get_cors_config, validate_environment

# Import database and routers
from database import init_db, get_db
from routers import (
    user_router, admin_router, kb_router, recurring_router, 
    documents_router, auth_router, audit_router, luna_router,
    integrations_router, appointments_router, workpaper_router
)

# Get settings
settings = get_settings()

# Configure logging based on environment
log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    # Startup
    logger.info("=" * 60)
    logger.info("Starting FDC Tax Core + CRM Sync API...")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Debug Mode: {settings.debug_enabled}")
    logger.info("=" * 60)
    
    # Validate environment
    env_status = validate_environment()
    if not env_status["valid"]:
        for error in env_status["errors"]:
            logger.error(f"Configuration Error: {error}")
        if settings.is_production:
            raise RuntimeError("Cannot start in production with invalid configuration")
    
    for warning in env_status.get("warnings", []):
        logger.warning(f"Configuration Warning: {warning}")
    
    # Initialize database
    try:
        await init_db()
        logger.info("PostgreSQL connection established")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    
    logger.info("FDC Tax Core API started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down FDC Tax Core API...")


# Create the main app
app = FastAPI(
    title=settings.API_TITLE,
    description="""
    Backend API for FDC Tax CRM sync, user onboarding state, and Meet Oscar wizard integration.
    
    ## Features
    
    ### User Endpoints (/api/user)
    - GET /tasks - Fetch tasks for logged-in user
    - GET/POST /profile - User profile + setup state
    - POST /oscar - Toggle Oscar preprocessing
    - PATCH /onboarding - Update setup_state flags
    
    ### Admin/White-Glove Endpoints (/api/admin)
    - User management (CRUD)
    - Profile review and override
    - Task assignment and management
    - Luna escalation triggers
    - CRM sync operations
    
    ### Knowledge Base Endpoints (/api/kb)
    - KB entry CRUD
    - Search for Luna responses
    
    ### Recurring Tasks (/api/recurring)
    - Template management for recurring tasks
    - Automatic task generation based on RRULE
    - Predefined templates (BAS, income checks)
    
    ### Document Requests (/api/documents)
    - Request documents from clients
    - Secure file uploads
    - Audit logging
    
    ### Authentication (/api/auth)
    - JWT-based authentication
    - Role-based access control (admin, staff, client)
    - Token refresh
    
    ### Audit Logs (/api/audit)
    - Centralized audit logging
    - Track all user and system actions
    - Query logs by user, action, resource, date range
    - Statistics and activity reports
    
    ### Luna Escalations (/api/luna)
    - Escalate complex queries to FDC Tax team
    - Create tasks with full context
    - Filter by confidence, tags, priority
    - Track escalation resolution
    
    ### Appointments (/api/appointments)
    - Calendly webhook integration
    - Appointment visibility and management
    - CRM task creation for appointments
    - Client appointment history
    
    ### Integrations (/api/integrations)
    - Calendly webhooks
    - Integration status checks
    
    ### Workpaper Platform (/api/workpaper)
    - Jobs: Tax jobs per client per year
    - Modules: Motor Vehicle, FDC Income, Internet, Home Office, etc.
    - Transactions: Financial data with overrides
    - Queries: Structured communication engine
    - Freeze: Period-based locking with snapshots
    - Dashboard: Single-screen workpaper view
    """,
    version="1.0.0",
    lifespan=lifespan
)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# Health check endpoint
@api_router.get("/", tags=["Health"])
async def root():
    return {
        "message": "FDC Tax Core + CRM Sync API",
        "status": "healthy",
        "version": "1.0.0"
    }


@api_router.get("/health", tags=["Health"])
async def health_check():
    """Detailed health check"""
    try:
        from database import engine
        from sqlalchemy import text
        
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        
        return {
            "status": "healthy",
            "database": "connected",
            "service": "FDC Tax Core + CRM Sync"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)}")


# Include all routers
api_router.include_router(auth_router)  # Auth first for visibility
api_router.include_router(user_router)
api_router.include_router(admin_router)
api_router.include_router(kb_router)
api_router.include_router(recurring_router)
api_router.include_router(documents_router)
api_router.include_router(audit_router)  # Audit logs
api_router.include_router(luna_router)  # Luna escalations
api_router.include_router(integrations_router)  # Calendly webhooks
api_router.include_router(appointments_router)  # Appointment management
api_router.include_router(workpaper_router)  # Workpaper platform

# Motor Vehicle module
from routers.motor_vehicle import router as mv_router
api_router.include_router(mv_router)  # Motor Vehicle module

# Transaction Engine / Bookkeeper Layer
from routers.bookkeeper import router as bookkeeper_router
from routers.bookkeeper import workpaper_router as workpaper_txn_router
from routers.bookkeeper import myfdc_router, import_router
api_router.include_router(bookkeeper_router)  # Bookkeeper transactions
api_router.include_router(workpaper_txn_router)  # Workpaper transaction lock
api_router.include_router(myfdc_router)  # MyFDC sync
api_router.include_router(import_router)  # Bank/OCR import

# Include the main router in the app
app.include_router(api_router)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)
