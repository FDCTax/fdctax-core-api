from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

# Load environment variables first
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Import database and routers
from database import init_db, get_db
from routers import (
    user_router, admin_router, kb_router, recurring_router, 
    documents_router, auth_router, audit_router, luna_router,
    integrations_router, appointments_router
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    # Startup
    logger.info("Starting FDC Tax Core + CRM Sync API...")
    try:
        await init_db()
        logger.info("PostgreSQL connection established")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down FDC Tax Core API...")


# Create the main app
app = FastAPI(
    title="FDC Tax Core + CRM Sync API",
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
