"""
FDC Core Workpaper Platform - API Router

Comprehensive API for the workpaper platform including:
- Jobs management
- Module instances
- Transactions and overrides
- Query engine
- Freeze engine
- Dashboard data
"""

from fastapi import APIRouter, Depends, HTTPException, Query as QueryParam, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import logging

from database import get_db
from middleware.auth import get_current_user, get_current_user_required, require_staff, require_admin, AuthUser

from services.workpaper import (
    # Enums
    JobStatus, ModuleType, TransactionCategory, QueryStatus, SnapshotType,
    MODULE_METHOD_CONFIGS,
    
    # Models
    WorkpaperJob, ModuleInstance, Transaction, TransactionOverride,
    EffectiveTransaction, OverrideRecord, Query, QueryMessage, Task,
    FreezeSnapshot, ModuleSummary, JobDashboard, ModuleDetail,
    
    # Request Models
    CreateJobRequest, UpdateJobRequest, CreateModuleRequest, UpdateModuleRequest,
    CreateTransactionRequest, CreateOverrideRequest, CreateModuleOverrideRequest,
    CreateQueryRequest, SendQueryRequest, AddMessageRequest, RespondToQueryRequest,
    
    # Storage
    job_storage, module_storage, transaction_storage, override_storage,
    module_override_storage, query_storage, message_storage, task_storage,
    snapshot_storage, effective_builder,
    
    # Engines
    calculate_module, calculate_all_modules, query_engine, freeze_engine,
)

from services.audit import log_action, AuditAction, ResourceType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workpaper", tags=["Workpaper Platform"])


# ==================== JOBS ====================

@router.post("/jobs", response_model=WorkpaperJob)
async def create_job(
    request: CreateJobRequest,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new workpaper job for a client.
    
    Auto-creates standard modules if auto_create_modules is True.
    """
    # Check for existing job
    existing = job_storage.get_by_client_year(request.client_id, request.year)
    if existing:
        raise HTTPException(status_code=400, detail=f"Job already exists for {request.year}")
    
    # Create job
    job = WorkpaperJob(
        client_id=request.client_id,
        year=request.year,
        notes=request.notes,
        status=JobStatus.NOT_STARTED.value,
    )
    job = job_storage.create(job)
    
    # Auto-create modules
    if request.auto_create_modules:
        for module_type in ModuleType:
            label = module_type.value.replace("_", " ").title()
            if module_type == ModuleType.MOTOR_VEHICLE:
                label = "Vehicle 1"  # Default label for first vehicle
            
            module = ModuleInstance(
                job_id=job.id,
                module_type=module_type.value,
                label=label,
                status=JobStatus.NOT_STARTED.value,
            )
            module_storage.create(module)
    
    # Audit log
    log_action(
        action=AuditAction.WORKPAPER_JOB_CREATE,
        resource_type=ResourceType.WORKPAPER_JOB,
        resource_id=job.id,
        user_id=current_user.id,
        user_email=current_user.email,
        details={
            "client_id": request.client_id,
            "year": request.year,
            "auto_created_modules": request.auto_create_modules,
        }
    )
    
    return job


@router.get("/jobs/{job_id}", response_model=WorkpaperJob)
async def get_job(
    job_id: str,
    current_user: AuthUser = Depends(require_staff)
):
    """Get a workpaper job by ID"""
    job = job_storage.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.patch("/jobs/{job_id}", response_model=WorkpaperJob)
async def update_job(
    job_id: str,
    request: UpdateJobRequest,
    current_user: AuthUser = Depends(require_staff)
):
    """Update a workpaper job"""
    job = job_storage.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot update frozen job")
    
    updates = request.model_dump(exclude_none=True)
    job = job_storage.update(job_id, updates)
    
    # Audit log
    log_action(
        action=AuditAction.WORKPAPER_JOB_UPDATE,
        resource_type=ResourceType.WORKPAPER_JOB,
        resource_id=job_id,
        user_id=current_user.id,
        details=updates
    )
    
    return job


@router.get("/clients/{client_id}/jobs", response_model=List[WorkpaperJob])
async def list_client_jobs(
    client_id: str,
    current_user: AuthUser = Depends(require_staff)
):
    """List all jobs for a client"""
    return job_storage.list_by_client(client_id)


@router.get("/clients/{client_id}/jobs/{year}", response_model=WorkpaperJob)
async def get_client_job_by_year(
    client_id: str,
    year: str,
    current_user: AuthUser = Depends(require_staff)
):
    """Get a client's job for a specific year"""
    job = job_storage.get_by_client_year(client_id, year)
    if not job:
        raise HTTPException(status_code=404, detail=f"No job found for {year}")
    return job


# ==================== DASHBOARD ====================

@router.get("/clients/{client_id}/jobs/{year}/modules", response_model=List[ModuleSummary])
async def get_job_modules_dashboard(
    client_id: str,
    year: str,
    current_user: AuthUser = Depends(require_staff)
):
    """
    Dashboard data: Get all modules for a job with status and outputs.
    """
    job = job_storage.get_by_client_year(client_id, year)
    if not job:
        raise HTTPException(status_code=404, detail=f"No job found for {year}")
    
    modules = module_storage.list_by_job(job.id)
    
    summaries = []
    for module in modules:
        open_queries = query_storage.count_open_by_module(module.id)
        
        summaries.append(ModuleSummary(
            id=module.id,
            module_type=module.module_type,
            label=module.label,
            status=module.status,
            has_open_queries=open_queries > 0,
            open_query_count=open_queries,
            output_summary=module.output_summary or {},
            frozen_at=module.frozen_at,
        ))
    
    return summaries


@router.get("/clients/{client_id}/jobs/{year}/dashboard", response_model=JobDashboard)
async def get_full_dashboard(
    client_id: str,
    year: str,
    current_user: AuthUser = Depends(require_staff)
):
    """
    Full dashboard data: Job with all modules, totals, and query status.
    """
    job = job_storage.get_by_client_year(client_id, year)
    if not job:
        raise HTTPException(status_code=404, detail=f"No job found for {year}")
    
    modules = module_storage.list_by_job(job.id)
    
    total_deduction = 0
    total_income = 0
    open_queries = 0
    
    module_summaries = []
    for module in modules:
        module_queries = query_storage.count_open_by_module(module.id)
        open_queries += module_queries
        
        if module.output_summary:
            total_deduction += module.output_summary.get("deduction", 0)
            total_income += module.output_summary.get("net_income", 0)
        
        module_summaries.append(ModuleSummary(
            id=module.id,
            module_type=module.module_type,
            label=module.label,
            status=module.status,
            has_open_queries=module_queries > 0,
            open_query_count=module_queries,
            output_summary=module.output_summary or {},
            frozen_at=module.frozen_at,
        ))
    
    tasks = task_storage.list_by_job(job.id)
    
    return JobDashboard(
        job=job,
        modules=module_summaries,
        total_deduction=round(total_deduction, 2),
        total_income=round(total_income, 2),
        open_queries=open_queries,
        has_tasks=len([t for t in tasks if t.status != "completed"]) > 0,
    )


# ==================== MODULES ====================

@router.post("/modules", response_model=ModuleInstance)
async def create_module(
    request: CreateModuleRequest,
    current_user: AuthUser = Depends(require_staff)
):
    """Create a new module instance"""
    job = job_storage.get(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot add modules to frozen job")
    
    module = ModuleInstance(
        job_id=request.job_id,
        module_type=request.module_type,
        label=request.label,
        config=request.config or {},
        status=JobStatus.NOT_STARTED.value,
    )
    
    module = module_storage.create(module)
    
    # Audit log
    log_action(
        action=AuditAction.WORKPAPER_MODULE_CREATE,
        resource_type=ResourceType.WORKPAPER_MODULE,
        resource_id=module.id,
        user_id=current_user.id,
        details={
            "job_id": request.job_id,
            "module_type": request.module_type,
            "label": request.label,
        }
    )
    
    return module


@router.get("/modules/{module_id}", response_model=ModuleDetail)
async def get_module_detail(
    module_id: str,
    include_transactions: bool = QueryParam(True),
    current_user: AuthUser = Depends(require_staff)
):
    """
    Get full module details including config, overrides, queries, and transactions.
    """
    module = module_storage.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    job = job_storage.get(module.job_id)
    
    # Get method config
    config_options = MODULE_METHOD_CONFIGS.get(module.module_type)
    
    # Get overrides
    overrides = module_override_storage.list_by_module(module_id)
    
    # Get queries
    queries = query_storage.list_by_module(module_id)
    
    # Get effective transactions
    effective_txns = []
    if include_transactions and job:
        effective_txns = effective_builder.build_for_module(module_id, job.id)
    
    return ModuleDetail(
        module=module,
        config_options=config_options,
        overrides=overrides,
        queries=queries,
        effective_transactions=effective_txns,
    )


@router.patch("/modules/{module_id}", response_model=ModuleInstance)
async def update_module(
    module_id: str,
    request: UpdateModuleRequest,
    current_user: AuthUser = Depends(require_staff)
):
    """Update a module instance"""
    module = module_storage.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot update frozen module")
    
    updates = request.model_dump(exclude_none=True)
    
    # Merge config if provided
    if "config" in updates and module.config:
        updates["config"] = {**module.config, **updates["config"]}
    
    module = module_storage.update(module_id, updates)
    
    # Audit log
    log_action(
        action=AuditAction.WORKPAPER_MODULE_UPDATE,
        resource_type=ResourceType.WORKPAPER_MODULE,
        resource_id=module_id,
        user_id=current_user.id,
        details=updates
    )
    
    return module


@router.get("/modules/{module_id}/effective-transactions", response_model=List[EffectiveTransaction])
async def get_module_effective_transactions(
    module_id: str,
    category: Optional[str] = None,
    current_user: AuthUser = Depends(require_staff)
):
    """
    Get effective transactions for a module.
    Returns transactions with overrides applied.
    """
    module = module_storage.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    job = job_storage.get(module.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    txns = effective_builder.build_for_module(module_id, job.id)
    
    if category:
        txns = [t for t in txns if t.effective_category == category]
    
    return txns


# ==================== CALCULATION ====================

@router.post("/modules/{module_id}/calculate")
async def calculate_module_endpoint(
    module_id: str,
    current_user: AuthUser = Depends(require_staff)
):
    """Calculate outputs for a module"""
    module = module_storage.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot calculate frozen module")
    
    try:
        output = calculate_module(module_id)
        
        # Audit log
        log_action(
            action=AuditAction.WORKPAPER_CALCULATE,
            resource_type=ResourceType.WORKPAPER_MODULE,
            resource_id=module_id,
            user_id=current_user.id,
            details={
                "module_type": module.module_type,
                "deduction": output.get("deduction"),
                "method": output.get("method"),
            }
        )
        
        return {
            "success": True,
            "module_id": module_id,
            "output": output,
        }
    except Exception as e:
        logger.error(f"Calculation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/{job_id}/calculate-all")
async def calculate_all_modules_endpoint(
    job_id: str,
    current_user: AuthUser = Depends(require_staff)
):
    """Calculate all modules for a job"""
    job = job_storage.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot calculate frozen job")
    
    try:
        results = calculate_all_modules(job_id)
        return {
            "success": True,
            "job_id": job_id,
            "results": results,
        }
    except Exception as e:
        logger.error(f"Calculation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== TRANSACTIONS ====================

@router.post("/transactions", response_model=Transaction)
async def create_transaction(
    request: CreateTransactionRequest,
    current_user: AuthUser = Depends(require_staff)
):
    """Create a new transaction"""
    transaction = Transaction(
        client_id=request.client_id,
        job_id=request.job_id,
        module_instance_id=request.module_instance_id,
        source=request.source,
        date=request.date,
        amount=request.amount,
        gst_amount=request.gst_amount,
        category=request.category,
        description=request.description,
        vendor=request.vendor,
        receipt_url=request.receipt_url,
    )
    
    transaction = transaction_storage.create(transaction)
    
    # Audit log
    log_action(
        action=AuditAction.WORKPAPER_TRANSACTION_CREATE,
        resource_type=ResourceType.WORKPAPER_TRANSACTION,
        resource_id=transaction.id,
        user_id=current_user.id,
        details={
            "amount": request.amount,
            "category": request.category,
            "source": request.source,
        }
    )
    
    return transaction


@router.get("/transactions", response_model=List[Transaction])
async def list_transactions(
    client_id: Optional[str] = None,
    job_id: Optional[str] = None,
    module_instance_id: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = QueryParam(100, le=500),
    current_user: AuthUser = Depends(require_staff)
):
    """List transactions with filters"""
    if module_instance_id:
        txns = transaction_storage.list_by_module(module_instance_id)
    elif job_id:
        txns = transaction_storage.list_by_job(job_id)
    elif client_id:
        txns = transaction_storage.list_by_client(client_id)
    else:
        txns = transaction_storage.list_all()
    
    if category:
        txns = [t for t in txns if t.category == category]
    
    return txns[:limit]


# ==================== OVERRIDES ====================

@router.post("/overrides/transaction", response_model=TransactionOverride)
async def create_transaction_override(
    request: CreateOverrideRequest,
    current_user: AuthUser = Depends(require_staff)
):
    """Create a transaction override"""
    # Check transaction exists
    txn = transaction_storage.get(request.transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Check job exists
    job = job_storage.get(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot add overrides to frozen job")
    
    # Check for existing override
    existing = override_storage.get_by_transaction_job(request.transaction_id, request.job_id)
    if existing:
        # Update existing
        updates = request.model_dump(exclude={"transaction_id", "job_id"})
        updates["admin_user_id"] = current_user.id
        updates["admin_email"] = current_user.email
        override = override_storage.update(existing.id, updates)
        
        log_action(
            action=AuditAction.WORKPAPER_OVERRIDE_UPDATE,
            resource_type=ResourceType.WORKPAPER_OVERRIDE,
            resource_id=existing.id,
            user_id=current_user.id,
            details=updates
        )
    else:
        # Create new
        override = TransactionOverride(
            transaction_id=request.transaction_id,
            job_id=request.job_id,
            overridden_category=request.overridden_category,
            overridden_amount=request.overridden_amount,
            overridden_gst_amount=request.overridden_gst_amount,
            overridden_business_pct=request.overridden_business_pct,
            reason=request.reason,
            admin_user_id=current_user.id,
            admin_email=current_user.email,
        )
        override = override_storage.create(override)
        
        log_action(
            action=AuditAction.WORKPAPER_OVERRIDE_CREATE,
            resource_type=ResourceType.WORKPAPER_OVERRIDE,
            resource_id=override.id,
            user_id=current_user.id,
            details={
                "transaction_id": request.transaction_id,
                "reason": request.reason,
            }
        )
    
    return override


@router.post("/overrides/module", response_model=OverrideRecord)
async def create_module_override(
    request: CreateModuleOverrideRequest,
    current_user: AuthUser = Depends(require_staff)
):
    """Create a module-level override"""
    module = module_storage.get(request.module_instance_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot add overrides to frozen module")
    
    # Check for existing override for this field
    existing = module_override_storage.get_by_field(request.module_instance_id, request.field_key)
    if existing:
        # Update config instead
        updates = {
            "effective_value": request.effective_value,
            "reason": request.reason,
            "admin_user_id": current_user.id,
            "admin_email": current_user.email,
        }
        override = module_override_storage.update(existing.id, updates)
    else:
        override = OverrideRecord(
            module_instance_id=request.module_instance_id,
            field_key=request.field_key,
            original_value=request.original_value,
            effective_value=request.effective_value,
            reason=request.reason,
            admin_user_id=current_user.id,
            admin_email=current_user.email,
        )
        override = module_override_storage.create(override)
    
    # Audit log
    log_action(
        action=AuditAction.WORKPAPER_OVERRIDE_CREATE,
        resource_type=ResourceType.WORKPAPER_OVERRIDE,
        resource_id=override.id,
        user_id=current_user.id,
        details={
            "field_key": request.field_key,
            "original": request.original_value,
            "effective": request.effective_value,
            "reason": request.reason,
        }
    )
    
    return override


# ==================== QUERIES ====================

@router.post("/jobs/{job_id}/queries", response_model=Query)
async def create_job_query(
    job_id: str,
    title: str = QueryParam(...),
    query_type: str = QueryParam("text"),
    initial_message: Optional[str] = None,
    current_user: AuthUser = Depends(require_staff)
):
    """Create a query at job level"""
    job = job_storage.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    request = CreateQueryRequest(
        client_id=job.client_id,
        job_id=job_id,
        title=title,
        query_type=query_type,
        initial_message=initial_message,
    )
    
    return query_engine.create_query(request, current_user.id, current_user.email)


@router.post("/modules/{module_instance_id}/queries", response_model=Query)
async def create_module_query(
    module_instance_id: str,
    title: str = QueryParam(...),
    query_type: str = QueryParam("text"),
    initial_message: Optional[str] = None,
    current_user: AuthUser = Depends(require_staff)
):
    """Create a query at module level"""
    module = module_storage.get(module_instance_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    job = job_storage.get(module.job_id)
    
    request = CreateQueryRequest(
        client_id=job.client_id,
        job_id=module.job_id,
        module_instance_id=module_instance_id,
        title=title,
        query_type=query_type,
        initial_message=initial_message,
    )
    
    return query_engine.create_query(request, current_user.id, current_user.email)


@router.post("/transactions/{transaction_id}/queries", response_model=Query)
async def create_transaction_query(
    transaction_id: str,
    title: str = QueryParam(...),
    query_type: str = QueryParam("text"),
    initial_message: Optional[str] = None,
    current_user: AuthUser = Depends(require_staff)
):
    """Create a query at transaction level"""
    txn = transaction_storage.get(transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    request = CreateQueryRequest(
        client_id=txn.client_id,
        job_id=txn.job_id,
        transaction_id=transaction_id,
        title=title,
        query_type=query_type,
        initial_message=initial_message,
    )
    
    return query_engine.create_query(request, current_user.id, current_user.email)


@router.get("/jobs/{job_id}/queries", response_model=List[Query])
async def list_job_queries(
    job_id: str,
    status: Optional[str] = None,
    current_user: AuthUser = Depends(require_staff)
):
    """List queries for a job"""
    return query_engine.list_queries_by_job(job_id, status)


@router.post("/queries/{query_id}/send", response_model=Query)
async def send_query(
    query_id: str,
    message: Optional[str] = None,
    current_user: AuthUser = Depends(require_staff)
):
    """Send a draft query to the client"""
    request = SendQueryRequest(message=message) if message else None
    return query_engine.send_query(query_id, request, current_user.id, current_user.email)


@router.post("/queries/send-bulk")
async def send_bulk_queries(
    query_ids: List[str],
    current_user: AuthUser = Depends(require_staff)
):
    """Send multiple queries at once"""
    sent = query_engine.send_bulk_queries(query_ids, current_user.id, current_user.email)
    return {
        "success": True,
        "sent_count": len(sent),
        "sent_ids": [q.id for q in sent],
    }


@router.post("/queries/{query_id}/messages", response_model=QueryMessage)
async def add_query_message(
    query_id: str,
    request: AddMessageRequest,
    current_user: AuthUser = Depends(require_staff)
):
    """Add a message to a query (admin)"""
    return query_engine.add_message(
        query_id,
        request,
        sender_type="admin",
        sender_id=current_user.id,
        sender_email=current_user.email
    )


@router.get("/queries/{query_id}/messages", response_model=List[QueryMessage])
async def get_query_messages(
    query_id: str,
    current_user: AuthUser = Depends(require_staff)
):
    """Get all messages for a query"""
    return query_engine.get_messages(query_id)


@router.post("/queries/{query_id}/resolve", response_model=Query)
async def resolve_query(
    query_id: str,
    resolution_message: Optional[str] = None,
    current_user: AuthUser = Depends(require_staff)
):
    """Mark a query as resolved"""
    return query_engine.resolve_query(
        query_id,
        current_user.id,
        current_user.email,
        resolution_message
    )


# ==================== CLIENT ENDPOINTS ====================

@router.get("/clients/{client_id}/jobs/{job_id}/tasks", response_model=List[Task])
async def get_client_tasks(
    client_id: str,
    job_id: str,
    current_user: AuthUser = Depends(get_current_user_required)
):
    """Get tasks for a client's job"""
    # Verify client access
    if current_user.role == "client" and current_user.id != client_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return query_engine.get_client_tasks(client_id, job_id)


@router.post("/queries/{query_id}/client-respond")
async def client_respond_to_query(
    query_id: str,
    request: RespondToQueryRequest,
    current_user: AuthUser = Depends(get_current_user_required)
):
    """Client response to a query"""
    query = query_storage.get(query_id)
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")
    
    # Verify client access
    if current_user.role == "client" and current_user.id != query.client_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return query_engine.client_respond(
        query_id,
        request,
        current_user.id,
        current_user.email
    )


# ==================== FREEZE ====================

@router.post("/modules/{module_id}/freeze", response_model=FreezeSnapshot)
async def freeze_module_endpoint(
    module_id: str,
    reason: Optional[str] = None,
    current_user: AuthUser = Depends(require_staff)
):
    """Freeze a module"""
    return freeze_engine.freeze_module(
        module_id,
        current_user.id,
        current_user.email,
        reason
    )


@router.post("/jobs/{job_id}/freeze", response_model=FreezeSnapshot)
async def freeze_job_endpoint(
    job_id: str,
    snapshot_type: str = QueryParam(..., description="ITR, BAS, or SUMMARY"),
    reason: Optional[str] = None,
    require_all_completed: bool = True,
    current_user: AuthUser = Depends(require_staff)
):
    """Freeze a job"""
    if snapshot_type not in [SnapshotType.ITR.value, SnapshotType.BAS.value, SnapshotType.SUMMARY.value]:
        raise HTTPException(status_code=400, detail=f"Invalid snapshot type: {snapshot_type}")
    
    return freeze_engine.freeze_job(
        job_id,
        snapshot_type,
        current_user.id,
        current_user.email,
        reason,
        require_all_completed
    )


@router.post("/modules/{module_id}/reopen", response_model=ModuleInstance)
async def reopen_module_endpoint(
    module_id: str,
    reason: str = QueryParam(..., min_length=10, description="Reason for reopening (min 10 chars)"),
    current_user: AuthUser = Depends(require_admin)
):
    """Reopen a frozen module (admin only)"""
    return freeze_engine.reopen_module(
        module_id,
        current_user.id,
        current_user.email,
        reason
    )


@router.get("/jobs/{job_id}/snapshots", response_model=List[FreezeSnapshot])
async def list_job_snapshots(
    job_id: str,
    current_user: AuthUser = Depends(require_staff)
):
    """List all snapshots for a job"""
    return freeze_engine.list_job_snapshots(job_id)


@router.get("/snapshots/{snapshot_id}", response_model=FreezeSnapshot)
async def get_snapshot(
    snapshot_id: str,
    current_user: AuthUser = Depends(require_staff)
):
    """Get a specific snapshot"""
    snapshot = freeze_engine.get_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snapshot


# ==================== REFERENCE DATA ====================

@router.get("/module-types")
async def list_module_types():
    """List all available module types"""
    return {
        "module_types": [
            {
                "type": mt.value,
                "name": mt.value.replace("_", " ").title(),
                "has_method_config": mt.value in MODULE_METHOD_CONFIGS,
            }
            for mt in ModuleType
        ]
    }


@router.get("/transaction-categories")
async def list_transaction_categories():
    """List all transaction categories"""
    return {
        "categories": [
            {"value": tc.value, "name": tc.value.replace("_", " ").title()}
            for tc in TransactionCategory
        ]
    }


@router.get("/job-statuses")
async def list_job_statuses():
    """List all job statuses"""
    return {
        "statuses": [
            {"value": js.value, "name": js.value.replace("_", " ").title()}
            for js in JobStatus
        ]
    }


@router.get("/method-configs/{module_type}")
async def get_method_config(module_type: str):
    """Get method configuration for a module type"""
    config = MODULE_METHOD_CONFIGS.get(module_type)
    if not config:
        raise HTTPException(status_code=404, detail=f"No method config for {module_type}")
    return config
