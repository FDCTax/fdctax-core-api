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

# Import logging and error tracking
from logging_config import setup_logging, get_logger
from sentry_integration import init_sentry, capture_exception, set_user, set_tag

# Import database and routers
from database import init_db, get_db
from routers import (
    user_router, admin_router, kb_router, recurring_router, 
    documents_router, auth_router, audit_router, luna_router,
    integrations_router, appointments_router, workpaper_router
)

# Get settings
settings = get_settings()

# Configure structured logging
# Use JSON format in production, plain text in development
setup_logging(
    level=settings.LOG_LEVEL,
    json_format=settings.is_production,
    service_name="fdc-core"
)
logger = get_logger(__name__)

# Initialize Sentry error tracking
if settings.SENTRY_DSN:
    init_sentry(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=0.1 if settings.is_production else 0.0,
    )


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
    version=settings.API_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug_enabled else None,
    redoc_url="/api/redoc" if settings.debug_enabled else None,
)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# ==================== HEALTH CHECK ENDPOINTS ====================

@api_router.get("/", tags=["Health"])
async def root():
    """Basic health check - returns 200 if service is running"""
    return {
        "message": "FDC Tax Core + CRM Sync API",
        "status": "healthy",
        "version": settings.API_VERSION,
        "environment": settings.ENVIRONMENT,
    }


@api_router.get("/health", tags=["Health"])
async def health_check():
    """
    Detailed health check for load balancers and uptime monitors.
    
    Returns:
    - 200: All systems operational
    - 503: Database or critical service unavailable
    
    Used by:
    - Kubernetes liveness/readiness probes
    - Load balancer health checks
    - Uptime monitoring services
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": settings.API_VERSION,
        "environment": settings.ENVIRONMENT,
        "checks": {}
    }
    
    # Check PostgreSQL connection
    try:
        from database import engine
        from sqlalchemy import text
        
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.fetchone()
        
        health_status["checks"]["database"] = {
            "status": "connected",
            "type": "postgresql"
        }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        health_status["status"] = "unhealthy"
        health_status["checks"]["database"] = {
            "status": "disconnected",
            "error": str(e)
        }
    
    # Check MongoDB connection (legacy)
    try:
        from database import mongo_client
        if mongo_client:
            await mongo_client.admin.command('ping')
            health_status["checks"]["mongodb"] = {
                "status": "connected",
                "type": "mongodb"
            }
    except Exception as e:
        # MongoDB is optional, just log warning
        health_status["checks"]["mongodb"] = {
            "status": "unavailable",
            "note": "Legacy service - migration in progress"
        }
    
    # Check configuration
    env_status = validate_environment()
    health_status["checks"]["configuration"] = {
        "status": "valid" if env_status["valid"] else "invalid",
        "warnings": len(env_status.get("warnings", [])),
        "errors": len(env_status.get("errors", []))
    }
    
    # Return appropriate status code
    if health_status["status"] == "unhealthy":
        raise HTTPException(status_code=503, detail=health_status)
    
    return health_status


@api_router.get("/health/ready", tags=["Health"])
async def readiness_check():
    """
    Kubernetes readiness probe.
    Returns 200 only when the service can accept traffic.
    """
    try:
        from database import engine
        from sqlalchemy import text
        
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        
        return {"status": "ready", "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "error": str(e)})


@api_router.get("/health/live", tags=["Health"])
async def liveness_check():
    """
    Kubernetes liveness probe.
    Returns 200 if the process is running (doesn't check dependencies).
    """
    return {"status": "alive", "timestamp": datetime.now(timezone.utc).isoformat()}


@api_router.get("/config/status", tags=["Health"])
async def config_status():
    """
    Configuration status check (non-sensitive).
    Useful for debugging deployment issues.
    """
    env_status = validate_environment()
    
    return {
        "environment": settings.ENVIRONMENT,
        "debug": settings.debug_enabled,
        "cors_origins_count": len(settings.cors_origins_list),
        "configuration_valid": env_status["valid"],
        "warnings": env_status.get("warnings", []),
        "variables": env_status.get("variables", {}),
        # Don't expose actual errors in production
        "errors": env_status.get("errors", []) if not settings.is_production else ["Hidden in production"]
    }


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

# LodgeIT Integration
from routers.lodgeit import router as lodgeit_router
api_router.include_router(lodgeit_router)  # LodgeIT export/import

# Bookkeeping Ingestion
from routers.ingestion import router as ingestion_router
api_router.include_router(ingestion_router)  # File upload/import pipeline

# MyFDC Unified Ingestion (A3-INGEST-02)
from ingestion.endpoints.myfdc_ingest import router as myfdc_ingestion_router
api_router.include_router(myfdc_ingestion_router)  # MyFDC → Core ingestion pipeline

# Bookkeeping-Ready Transactions (A3-BOOK-01)
from ingestion.endpoints.bookkeeping_ready import router as bookkeeping_ready_router
api_router.include_router(bookkeeping_ready_router)  # Bookkeeping-ready transaction API

# BAS Backend
from routers.bas import router as bas_router
api_router.include_router(bas_router)  # BAS history, PDF, sign-off

# VXT Phone System Integration
from routers.vxt import router as vxt_router
api_router.include_router(vxt_router)  # VXT webhooks, calls, recordings

# SMS Integration (Phase 0 - Stub)
from routers.sms import router as sms_router
api_router.include_router(sms_router)  # SMS sending (stub in Phase 0)

# Email Integration (Phase 0 - Stub)
from email_integration.email_router import router as email_router
api_router.include_router(email_router)  # Email sending (stub in Phase 0)

# Identity Spine Module
from identity.router import router as identity_router
api_router.include_router(identity_router)  # Unified identity management

# Core Module (Client Profiles & Luna Migration)
from core.router import router as core_router
api_router.include_router(core_router)  # Client profiles, migration endpoints

# Tax Modules (POB, Occupancy, Depreciation, Motor Vehicle)
from routers.tax_modules import router as tax_modules_router
api_router.include_router(tax_modules_router)  # Tax calculation endpoints

# Core Client API (MyFDC, CRM, Bookkeeping, Workpapers integration)
from routers.clients import router as clients_router, v1_router as clients_v1_router
api_router.include_router(clients_router)  # Unified client management
api_router.include_router(clients_v1_router)  # V1 versioned endpoints (Ticket A3-8)

# MyFDC Data Intake API (Ticket A3-2)
from routers.myfdc_intake import router as myfdc_intake_router
api_router.include_router(myfdc_intake_router)  # MyFDC data intake endpoints

# CRM Bookkeeping Data Access API (Ticket A3-3.3)
from routers.bookkeeping_access import router as bookkeeping_access_router
api_router.include_router(bookkeeping_access_router)  # CRM Bookkeeping read endpoints

# Webhook Notification System (Ticket A3-4)
from routers.webhooks import router as webhooks_router
api_router.include_router(webhooks_router)  # Webhook management endpoints

# SMS Proxy (Ticket A3-7) - Core → Agent 5 forwarding
from routers.sms_proxy import router as sms_proxy_router
api_router.include_router(sms_proxy_router)  # SMS proxy endpoints

# Reconciliation Engine (A3-RECON-01)
from reconciliation.endpoints.reconciliation_api import router as reconciliation_router
api_router.include_router(reconciliation_router)  # Reconciliation engine endpoints

# OCR Module (A3-OCR-01)
from ocr.endpoints.ocr_api import router as ocr_router
api_router.include_router(ocr_router)  # OCR receipt processing endpoints

# CRM Integration Endpoints (additional endpoints for CRM → Core)
from routers.crm_integration import router as crm_integration_router
api_router.include_router(crm_integration_router)  # CRM-specific endpoints with internal API auth

# ==================== SECRET AUTHORITY VERIFICATION ROUTES ====================
# These routes are mounted under /api for Secret Authority access
# Paths: /api/sa/status, /api/sa/email/status, /api/sa/tfn/*, /api/sa/internal/status
from routers.secret_authority import router as secret_authority_router
api_router.include_router(secret_authority_router, prefix="/sa")  # Secret Authority endpoints

# Include the main API router in the app
app.include_router(api_router)

# ==================== MIDDLEWARE ====================

# CORS middleware with production-safe configuration
cors_config = get_cors_config()
app.add_middleware(
    CORSMiddleware,
    **cors_config
)


# Request logging middleware (useful for debugging)
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests with timing information"""
    import time
    start_time = time.time()
    
    # Generate request ID
    request_id = request.headers.get("X-Request-ID", f"req-{int(start_time * 1000)}")
    
    # Log request
    if settings.debug_enabled:
        logger.debug(f"[{request_id}] {request.method} {request.url.path}")
    
    try:
        response = await call_next(request)
        
        # Calculate processing time
        process_time = time.time() - start_time
        
        # Add headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(round(process_time * 1000, 2))
        
        # Log response
        if settings.debug_enabled or response.status_code >= 400:
            logger.info(f"[{request_id}] {request.method} {request.url.path} -> {response.status_code} ({process_time:.3f}s)")
        
        return response
    except Exception as e:
        logger.error(f"[{request_id}] Request failed: {str(e)}")
        raise


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions"""
    logger.error(f"Unhandled exception: {exc}")
    if settings.debug_enabled:
        logger.error(traceback.format_exc())
    
    # Capture to Sentry
    capture_exception(exc, request_path=str(request.url.path), request_method=request.method)
    
    # Don't expose internal errors in production
    if settings.is_production:
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )
    else:
        return JSONResponse(
            status_code=500,
            content={
                "detail": str(exc),
                "type": type(exc).__name__,
                "traceback": traceback.format_exc() if settings.debug_enabled else None
            }
        )
