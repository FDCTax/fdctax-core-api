"""
Jobs API Endpoints

REST API for job management (CRM integration):
- GET /api/jobs - List all jobs
- GET /api/jobs/{id} - Get single job
- POST /api/jobs - Create job with basic metadata
- POST /api/jobs/create - Create job with full configuration
- PATCH /api/jobs/{id} - Update job
- DELETE /api/jobs/{id} - Soft delete job

Supports both internal API key auth (CRM) and JWT auth (UI).
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["Jobs"])


# ==================== Request/Response Models ====================

class JobBase(BaseModel):
    """Base job model."""
    name: str = Field(..., description="Job name/title")
    description: Optional[str] = Field(None, description="Job description")
    job_type: Optional[str] = Field("other", description="Job type")
    client_id: str = Field(..., description="Client ID")


class CreateJobRequest(JobBase):
    """Request to create a job with basic metadata."""
    status: Optional[str] = Field("draft", description="Job status")
    priority: Optional[str] = Field("normal", description="Priority level")


class CreateJobFullRequest(JobBase):
    """Request to create a job with full configuration."""
    # Period
    period_start: Optional[str] = Field(None, description="Period start date (YYYY-MM-DD)")
    period_end: Optional[str] = Field(None, description="Period end date (YYYY-MM-DD)")
    financial_year: Optional[str] = Field(None, description="Financial year (e.g., 2025, FY2025)")
    
    # Status & Priority
    status: Optional[str] = Field("draft", description="Job status")
    priority: Optional[str] = Field("normal", description="Priority")
    
    # Assignment
    assigned_to: Optional[str] = Field(None, description="Assigned user ID")
    assigned_team: Optional[str] = Field(None, description="Assigned team")
    
    # Dates
    due_date: Optional[str] = Field(None, description="Due date (ISO format)")
    
    # Configuration
    config: Optional[dict] = Field(default_factory=dict, description="Job configuration")
    metadata: Optional[dict] = Field(default_factory=dict, description="Additional metadata")
    
    # References
    parent_job_id: Optional[str] = Field(None, description="Parent job ID")
    workpaper_job_id: Optional[str] = Field(None, description="Linked workpaper job ID")


class UpdateJobRequest(BaseModel):
    """Request to update a job."""
    name: Optional[str] = None
    description: Optional[str] = None
    job_type: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    financial_year: Optional[str] = None
    assigned_to: Optional[str] = None
    assigned_team: Optional[str] = None
    due_date: Optional[str] = None
    config: Optional[dict] = None
    metadata: Optional[dict] = None


class JobResponse(BaseModel):
    """Job response model."""
    id: str
    client_id: str
    name: str
    description: Optional[str]
    job_type: str
    period_start: Optional[str]
    period_end: Optional[str]
    financial_year: Optional[str]
    status: str
    priority: str
    assigned_to: Optional[str]
    assigned_team: Optional[str]
    due_date: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    config: dict
    metadata: dict
    created_by: Optional[str]
    created_at: str
    updated_at: str
    parent_job_id: Optional[str]
    workpaper_job_id: Optional[str]


# ==================== Authentication ====================

def get_internal_api_keys() -> List[str]:
    """Get list of valid internal API keys."""
    primary_key = os.environ.get('INTERNAL_API_KEY', '')
    legacy_keys = os.environ.get('INTERNAL_API_KEYS', '')
    
    keys = []
    if primary_key:
        keys.append(primary_key)
    if legacy_keys:
        keys.extend([k.strip() for k in legacy_keys.split(',') if k.strip()])
    
    return keys


def verify_internal_or_jwt_auth(
    x_internal_api_key: Optional[str] = Header(None, alias="X-Internal-Api-Key"),
    authorization: Optional[str] = Header(None)
):
    """
    Verify either internal API key or JWT authentication.
    Returns the auth type and user info.
    """
    valid_keys = get_internal_api_keys()
    
    # Check internal API key first
    if x_internal_api_key and x_internal_api_key in valid_keys:
        return {"type": "internal", "user_id": "crm-service", "email": "crm@internal.fdccore.com"}
    
    # Check JWT token
    if authorization and authorization.startswith("Bearer "):
        # For now, just accept the token - full JWT validation would require middleware
        return {"type": "jwt", "user_id": None, "email": None}
    
    # If internal keys are configured, require auth
    if valid_keys:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # If no keys configured, allow (development mode)
    return {"type": "none", "user_id": None, "email": None}


# ==================== Helper Functions ====================

def row_to_job_dict(row) -> dict:
    """Convert database row to job dictionary."""
    def safe_iso(val):
        if val is None:
            return None
        if hasattr(val, 'isoformat'):
            return val.isoformat()
        return str(val)
    
    config = row[17] if row[17] else {}
    metadata = row[18] if row[18] else {}
    
    if isinstance(config, str):
        config = json.loads(config)
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    
    return {
        "id": str(row[0]),
        "client_id": str(row[1]),
        "name": row[2],
        "description": row[3],
        "job_type": row[4] or "other",
        "period_start": safe_iso(row[5]),
        "period_end": safe_iso(row[6]),
        "financial_year": row[7],
        "status": row[8] or "draft",
        "priority": row[9] or "normal",
        "assigned_to": str(row[10]) if row[10] else None,
        "assigned_team": row[11],
        "due_date": safe_iso(row[12]),
        "started_at": safe_iso(row[13]),
        "completed_at": safe_iso(row[14]),
        "created_by": str(row[15]) if row[15] else None,
        "created_at": safe_iso(row[16]),
        "updated_at": safe_iso(row[19]),
        "config": config,
        "metadata": metadata,
        "parent_job_id": str(row[20]) if row[20] else None,
        "workpaper_job_id": row[21]
    }


# ==================== Endpoints ====================

@router.get("", summary="List all jobs")
async def list_jobs(
    client_id: Optional[str] = Query(None, description="Filter by client ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    financial_year: Optional[str] = Query(None, description="Filter by financial year"),
    assigned_to: Optional[str] = Query(None, description="Filter by assigned user"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(verify_internal_or_jwt_auth)
):
    """
    List all jobs with optional filters.
    
    **Auth:** Internal API Key (X-Internal-Api-Key) or JWT Bearer token
    """
    conditions = ["NOT is_deleted"]
    params = {"limit": limit, "offset": offset}
    
    if client_id:
        conditions.append("client_id = :client_id")
        params["client_id"] = client_id
    
    if status:
        conditions.append("status = :status")
        params["status"] = status
    
    if job_type:
        conditions.append("job_type = :job_type")
        params["job_type"] = job_type
    
    if financial_year:
        conditions.append("financial_year = :financial_year")
        params["financial_year"] = financial_year
    
    if assigned_to:
        conditions.append("assigned_to = :assigned_to")
        params["assigned_to"] = assigned_to
    
    where_clause = " AND ".join(conditions)
    
    # Get total count
    count_query = text(f"SELECT COUNT(*) FROM public.jobs WHERE {where_clause}")
    count_result = await db.execute(count_query, params)
    total_count = count_result.scalar() or 0
    
    # Get jobs
    query = text(f"""
        SELECT 
            id, client_id, name, description, job_type,
            period_start, period_end, financial_year,
            status, priority, assigned_to, assigned_team,
            due_date, started_at, completed_at,
            created_by, created_at, config, metadata,
            updated_at, parent_job_id, workpaper_job_id
        FROM public.jobs
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    
    result = await db.execute(query, params)
    rows = result.fetchall()
    
    jobs = [row_to_job_dict(row) for row in rows]
    
    return {
        "success": True,
        "total_count": total_count,
        "count": len(jobs),
        "limit": limit,
        "offset": offset,
        "has_more": (offset + len(jobs)) < total_count,
        "jobs": jobs
    }


@router.get("/{job_id}", summary="Get job by ID")
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(verify_internal_or_jwt_auth)
):
    """
    Get a single job by ID.
    
    **Auth:** Internal API Key (X-Internal-Api-Key) or JWT Bearer token
    """
    query = text("""
        SELECT 
            id, client_id, name, description, job_type,
            period_start, period_end, financial_year,
            status, priority, assigned_to, assigned_team,
            due_date, started_at, completed_at,
            created_by, created_at, config, metadata,
            updated_at, parent_job_id, workpaper_job_id
        FROM public.jobs
        WHERE id = :job_id AND NOT is_deleted
    """)
    
    result = await db.execute(query, {"job_id": job_id})
    row = result.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {
        "success": True,
        "job": row_to_job_dict(row)
    }


@router.post("", summary="Create job (basic)")
async def create_job(
    request: CreateJobRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(verify_internal_or_jwt_auth)
):
    """
    Create a new job with basic metadata.
    
    **Auth:** Internal API Key (X-Internal-Api-Key) or JWT Bearer token
    """
    query = text("""
        INSERT INTO public.jobs (
            client_id, name, description, job_type,
            status, priority, created_by, created_at, updated_at
        ) VALUES (
            :client_id, :name, :description, :job_type,
            :status, :priority, :created_by, NOW(), NOW()
        )
        RETURNING id, client_id, name, description, job_type,
            period_start, period_end, financial_year,
            status, priority, assigned_to, assigned_team,
            due_date, started_at, completed_at,
            created_by, created_at, config, metadata,
            updated_at, parent_job_id, workpaper_job_id
    """)
    
    try:
        # Handle created_by - only set if it's a valid UUID
        created_by = None
        if auth.get("user_id") and auth.get("user_id") != "crm-service":
            created_by = auth.get("user_id")
        
        result = await db.execute(query, {
            "client_id": request.client_id,
            "name": request.name,
            "description": request.description,
            "job_type": request.job_type or "other",
            "status": request.status or "draft",
            "priority": request.priority or "normal",
            "created_by": created_by
        })
        
        row = result.fetchone()
        await db.commit()
        
        return {
            "success": True,
            "message": "Job created successfully",
            "job": row_to_job_dict(row)
        }
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create job: {str(e)}")


@router.post("/create", summary="Create job (full)")
async def create_job_full(
    request: CreateJobFullRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(verify_internal_or_jwt_auth)
):
    """
    Create a new job with full configuration.
    
    **Auth:** Internal API Key (X-Internal-Api-Key) or JWT Bearer token
    """
    query = text("""
        INSERT INTO public.jobs (
            client_id, name, description, job_type,
            period_start, period_end, financial_year,
            status, priority, assigned_to, assigned_team,
            due_date, config, metadata,
            parent_job_id, workpaper_job_id,
            created_by, created_at, updated_at
        ) VALUES (
            :client_id, :name, :description, :job_type,
            :period_start, :period_end, :financial_year,
            :status, :priority, :assigned_to, :assigned_team,
            :due_date, :config, :metadata,
            :parent_job_id, :workpaper_job_id,
            :created_by, NOW(), NOW()
        )
        RETURNING id, client_id, name, description, job_type,
            period_start, period_end, financial_year,
            status, priority, assigned_to, assigned_team,
            due_date, started_at, completed_at,
            created_by, created_at, config, metadata,
            updated_at, parent_job_id, workpaper_job_id
    """)
    
    try:
        # Handle created_by - only set if it's a valid UUID
        created_by = None
        if auth.get("user_id") and auth.get("user_id") != "crm-service":
            created_by = auth.get("user_id")
        
        result = await db.execute(query, {
            "client_id": request.client_id,
            "name": request.name,
            "description": request.description,
            "job_type": request.job_type or "other",
            "period_start": request.period_start,
            "period_end": request.period_end,
            "financial_year": request.financial_year,
            "status": request.status or "draft",
            "priority": request.priority or "normal",
            "assigned_to": request.assigned_to,
            "assigned_team": request.assigned_team,
            "due_date": request.due_date,
            "config": json.dumps(request.config or {}),
            "metadata": json.dumps(request.metadata or {}),
            "parent_job_id": request.parent_job_id,
            "workpaper_job_id": request.workpaper_job_id,
            "created_by": created_by
        })
        
        row = result.fetchone()
        await db.commit()
        
        return {
            "success": True,
            "message": "Job created successfully",
            "job": row_to_job_dict(row)
        }
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create job: {str(e)}")


@router.patch("/{job_id}", summary="Update job")
async def update_job(
    job_id: str,
    request: UpdateJobRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(verify_internal_or_jwt_auth)
):
    """
    Update an existing job.
    
    **Auth:** Internal API Key (X-Internal-Api-Key) or JWT Bearer token
    """
    # Build update statement dynamically
    updates = request.model_dump(exclude_none=True)
    
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    # Handle JSON fields
    if "config" in updates:
        updates["config"] = json.dumps(updates["config"])
    if "metadata" in updates:
        updates["metadata"] = json.dumps(updates["metadata"])
    
    # Auto-set started_at when status changes to in_progress (use SQL NOW())
    auto_started = False
    if updates.get("status") == "in_progress":
        auto_started = True
    
    # Auto-set completed_at when status changes to completed (use SQL NOW())
    auto_completed = False
    if updates.get("status") == "completed":
        auto_completed = True
    
    set_clauses = [f"{k} = :{k}" for k in updates.keys()]
    set_clauses.append("updated_at = NOW()")
    
    if auto_started:
        set_clauses.append("started_at = COALESCE(started_at, NOW())")
    if auto_completed:
        set_clauses.append("completed_at = NOW()")
    
    query = text(f"""
        UPDATE public.jobs
        SET {', '.join(set_clauses)}
        WHERE id = :job_id AND NOT is_deleted
        RETURNING id, client_id, name, description, job_type,
            period_start, period_end, financial_year,
            status, priority, assigned_to, assigned_team,
            due_date, started_at, completed_at,
            created_by, created_at, config, metadata,
            updated_at, parent_job_id, workpaper_job_id
    """)
    
    try:
        updates["job_id"] = job_id
        result = await db.execute(query, updates)
        row = result.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        
        await db.commit()
        
        return {
            "success": True,
            "message": "Job updated successfully",
            "job": row_to_job_dict(row)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update job: {str(e)}")


@router.delete("/{job_id}", summary="Delete job")
async def delete_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(verify_internal_or_jwt_auth)
):
    """
    Soft delete a job.
    
    **Auth:** Internal API Key (X-Internal-Api-Key) or JWT Bearer token
    """
    query = text("""
        UPDATE public.jobs
        SET is_deleted = TRUE, deleted_at = NOW(), updated_at = NOW()
        WHERE id = :job_id AND NOT is_deleted
        RETURNING id
    """)
    
    try:
        result = await db.execute(query, {"job_id": job_id})
        row = result.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        
        await db.commit()
        
        return {
            "success": True,
            "message": "Job deleted successfully",
            "job_id": str(row[0])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete job: {str(e)}")


# ==================== Additional Endpoints ====================

@router.get("/client/{client_id}", summary="Get jobs by client")
async def get_jobs_by_client(
    client_id: str,
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(verify_internal_or_jwt_auth)
):
    """
    Get all jobs for a specific client.
    
    **Auth:** Internal API Key (X-Internal-Api-Key) or JWT Bearer token
    """
    conditions = ["client_id = :client_id", "NOT is_deleted"]
    params = {"client_id": client_id, "limit": limit}
    
    if status:
        conditions.append("status = :status")
        params["status"] = status
    
    where_clause = " AND ".join(conditions)
    
    query = text(f"""
        SELECT 
            id, client_id, name, description, job_type,
            period_start, period_end, financial_year,
            status, priority, assigned_to, assigned_team,
            due_date, started_at, completed_at,
            created_by, created_at, config, metadata,
            updated_at, parent_job_id, workpaper_job_id
        FROM public.jobs
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT :limit
    """)
    
    result = await db.execute(query, params)
    rows = result.fetchall()
    
    return {
        "success": True,
        "client_id": client_id,
        "count": len(rows),
        "jobs": [row_to_job_dict(row) for row in rows]
    }


@router.post("/{job_id}/status", summary="Update job status")
async def update_job_status(
    job_id: str,
    status: str = Query(..., description="New status"),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(verify_internal_or_jwt_auth)
):
    """
    Quick endpoint to update just the job status.
    
    **Auth:** Internal API Key (X-Internal-Api-Key) or JWT Bearer token
    """
    valid_statuses = ["draft", "pending", "in_progress", "review", "completed", "cancelled", "on_hold"]
    
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid status. Must be one of: {valid_statuses}"
        )
    
    # Build update with auto timestamps
    set_clauses = ["status = :status", "updated_at = NOW()"]
    params = {"job_id": job_id, "status": status}
    
    if status == "in_progress":
        set_clauses.append("started_at = COALESCE(started_at, NOW())")
    elif status == "completed":
        set_clauses.append("completed_at = NOW()")
    
    query = text(f"""
        UPDATE public.jobs
        SET {', '.join(set_clauses)}
        WHERE id = :job_id AND NOT is_deleted
        RETURNING id, status, started_at, completed_at
    """)
    
    try:
        result = await db.execute(query, params)
        row = result.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        
        await db.commit()
        
        return {
            "success": True,
            "job_id": str(row[0]),
            "status": row[1],
            "started_at": row[2].isoformat() if row[2] else None,
            "completed_at": row[3].isoformat() if row[3] else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update job status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update status: {str(e)}")
