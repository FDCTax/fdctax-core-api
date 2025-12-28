"""
FDC Core Workpaper Platform - Database-Backed API Router

PostgreSQL-backed API for the workpaper platform including:
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
    QueryType, SenderType, TaskType, TaskStatus,
    MODULE_METHOD_CONFIGS,
    
    # Models
    WorkpaperJob, ModuleInstance, Transaction, TransactionOverride,
    EffectiveTransaction, OverrideRecord, Query, QueryMessage, Task,
    FreezeSnapshot, ModuleSummary, JobDashboard, ModuleDetail,
    
    # Request Models
    CreateJobRequest, UpdateJobRequest, CreateModuleRequest, UpdateModuleRequest,
    CreateTransactionRequest, CreateOverrideRequest, CreateModuleOverrideRequest,
    CreateQueryRequest, SendQueryRequest, AddMessageRequest, RespondToQueryRequest,
    
    # Database Repositories
    WorkpaperJobRepository, ModuleInstanceRepository, TransactionRepository,
    TransactionOverrideRepository, OverrideRecordRepository, QueryRepository,
    QueryMessageRepository, TaskRepository, FreezeSnapshotRepository,
    WorkpaperAuditLogRepository, EffectiveTransactionBuilder,
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
    job_repo = WorkpaperJobRepository(db)
    module_repo = ModuleInstanceRepository(db)
    
    # Check for existing job
    existing = await job_repo.get_by_client_year(request.client_id, request.year)
    if existing:
        raise HTTPException(status_code=400, detail=f"Job already exists for {request.year}")
    
    # Create job
    job = WorkpaperJob(
        client_id=request.client_id,
        year=request.year,
        notes=request.notes,
        status=JobStatus.NOT_STARTED.value,
    )
    job = await job_repo.create(job)
    
    # Auto-create modules
    if request.auto_create_modules:
        for module_type in ModuleType:
            label = module_type.value.replace("_", " ").title()
            if module_type == ModuleType.MOTOR_VEHICLE:
                label = "Vehicle 1"
            
            module = ModuleInstance(
                job_id=job.id,
                module_type=module_type.value,
                label=label,
                status=JobStatus.NOT_STARTED.value,
            )
            await module_repo.create(module)
    
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
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Get a workpaper job by ID"""
    job_repo = WorkpaperJobRepository(db)
    job = await job_repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.patch("/jobs/{job_id}", response_model=WorkpaperJob)
async def update_job(
    job_id: str,
    request: UpdateJobRequest,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Update a workpaper job"""
    job_repo = WorkpaperJobRepository(db)
    job = await job_repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot update frozen job")
    
    updates = request.model_dump(exclude_none=True)
    job = await job_repo.update(job_id, updates)
    
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
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """List all jobs for a client"""
    job_repo = WorkpaperJobRepository(db)
    return await job_repo.list_by_client(client_id)


@router.get("/clients/{client_id}/jobs/{year}", response_model=WorkpaperJob)
async def get_client_job_by_year(
    client_id: str,
    year: str,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Get a client's job for a specific year"""
    job_repo = WorkpaperJobRepository(db)
    job = await job_repo.get_by_client_year(client_id, year)
    if not job:
        raise HTTPException(status_code=404, detail=f"No job found for {year}")
    return job


# ==================== DASHBOARD ====================

@router.get("/clients/{client_id}/jobs/{year}/modules", response_model=List[ModuleSummary])
async def get_job_modules_dashboard(
    client_id: str,
    year: str,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Dashboard data: Get all modules for a job with status and outputs."""
    job_repo = WorkpaperJobRepository(db)
    module_repo = ModuleInstanceRepository(db)
    query_repo = QueryRepository(db)
    
    job = await job_repo.get_by_client_year(client_id, year)
    if not job:
        raise HTTPException(status_code=404, detail=f"No job found for {year}")
    
    modules = await module_repo.list_by_job(job.id)
    
    summaries = []
    for module in modules:
        open_queries = await query_repo.count_open_by_module(module.id)
        
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
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Full dashboard data: Job with all modules, totals, and query status."""
    job_repo = WorkpaperJobRepository(db)
    module_repo = ModuleInstanceRepository(db)
    query_repo = QueryRepository(db)
    task_repo = TaskRepository(db)
    
    job = await job_repo.get_by_client_year(client_id, year)
    if not job:
        raise HTTPException(status_code=404, detail=f"No job found for {year}")
    
    modules = await module_repo.list_by_job(job.id)
    
    total_deduction = 0
    total_income = 0
    open_queries = 0
    
    module_summaries = []
    for module in modules:
        module_queries = await query_repo.count_open_by_module(module.id)
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
    
    tasks = await task_repo.list_by_job(job.id)
    
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
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Create a new module instance"""
    job_repo = WorkpaperJobRepository(db)
    module_repo = ModuleInstanceRepository(db)
    
    job = await job_repo.get(request.job_id)
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
    
    module = await module_repo.create(module)
    
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
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Get full module details including config, overrides, queries, and transactions."""
    module_repo = ModuleInstanceRepository(db)
    job_repo = WorkpaperJobRepository(db)
    override_repo = OverrideRecordRepository(db)
    query_repo = QueryRepository(db)
    
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    job = await job_repo.get(module.job_id)
    
    # Get method config
    config_options = MODULE_METHOD_CONFIGS.get(module.module_type)
    
    # Get overrides
    overrides = await override_repo.list_by_module(module_id)
    
    # Get queries
    queries = await query_repo.list_by_module(module_id)
    
    # Get effective transactions
    effective_txns = []
    if include_transactions and job:
        effective_builder = EffectiveTransactionBuilder(db)
        effective_txns = await effective_builder.build_for_module(module_id, job.id)
    
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
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Update a module instance"""
    module_repo = ModuleInstanceRepository(db)
    
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot update frozen module")
    
    updates = request.model_dump(exclude_none=True)
    
    # Merge config if provided
    if "config" in updates and module.config:
        updates["config"] = {**module.config, **updates["config"]}
    
    module = await module_repo.update(module_id, updates)
    
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
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Get effective transactions for a module."""
    module_repo = ModuleInstanceRepository(db)
    job_repo = WorkpaperJobRepository(db)
    
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    job = await job_repo.get(module.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    effective_builder = EffectiveTransactionBuilder(db)
    txns = await effective_builder.build_for_module(module_id, job.id)
    
    if category:
        txns = [t for t in txns if t.effective_category == category]
    
    return txns


# ==================== TRANSACTIONS ====================

@router.post("/transactions", response_model=Transaction)
async def create_transaction(
    request: CreateTransactionRequest,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Create a new transaction"""
    tx_repo = TransactionRepository(db)
    
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
    
    transaction = await tx_repo.create(transaction)
    
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
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """List transactions with filters"""
    tx_repo = TransactionRepository(db)
    
    if module_instance_id:
        txns = await tx_repo.list_by_module(module_instance_id)
    elif job_id:
        txns = await tx_repo.list_by_job(job_id)
    elif client_id:
        txns = await tx_repo.list_by_client(client_id)
    else:
        raise HTTPException(status_code=400, detail="Must provide client_id, job_id, or module_instance_id")
    
    if category:
        txns = [t for t in txns if t.category == category]
    
    return txns[:limit]


# ==================== OVERRIDES ====================

@router.post("/overrides/transaction", response_model=TransactionOverride)
async def create_transaction_override(
    request: CreateOverrideRequest,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Create a transaction override"""
    tx_repo = TransactionRepository(db)
    job_repo = WorkpaperJobRepository(db)
    override_repo = TransactionOverrideRepository(db)
    
    # Check transaction exists
    txn = await tx_repo.get(request.transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Check job exists
    job = await job_repo.get(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot add overrides to frozen job")
    
    # Check for existing override
    existing = await override_repo.get_by_transaction_job(request.transaction_id, request.job_id)
    if existing:
        # Update existing
        updates = request.model_dump(exclude={"transaction_id", "job_id"})
        updates["admin_user_id"] = current_user.id
        updates["admin_email"] = current_user.email
        override = await override_repo.update(existing.id, updates)
        
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
        override = await override_repo.create(override)
        
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
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Create a module-level override"""
    module_repo = ModuleInstanceRepository(db)
    override_repo = OverrideRecordRepository(db)
    
    module = await module_repo.get(request.module_instance_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot add overrides to frozen module")
    
    # Check for existing override for this field
    existing = await override_repo.get_by_field(request.module_instance_id, request.field_key)
    if existing:
        # Update existing
        updates = {
            "effective_value": request.effective_value,
            "reason": request.reason,
            "admin_user_id": current_user.id,
            "admin_email": current_user.email,
        }
        override = await override_repo.update(existing.id, updates)
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
        override = await override_repo.create(override)
    
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
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Create a query at job level"""
    job_repo = WorkpaperJobRepository(db)
    query_repo = QueryRepository(db)
    message_repo = QueryMessageRepository(db)
    
    job = await job_repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    query = Query(
        client_id=job.client_id,
        job_id=job_id,
        title=title,
        query_type=query_type,
        status=QueryStatus.DRAFT.value,
        created_by_admin_id=current_user.id,
        created_by_admin_email=current_user.email,
    )
    
    query = await query_repo.create(query)
    
    if initial_message:
        message = QueryMessage(
            query_id=query.id,
            sender_type=SenderType.ADMIN.value,
            sender_id=current_user.id,
            sender_email=current_user.email,
            message_text=initial_message,
        )
        await message_repo.create(message)
    
    log_action(
        action=AuditAction.WORKPAPER_QUERY_CREATE,
        resource_type=ResourceType.WORKPAPER_QUERY,
        resource_id=query.id,
        user_id=current_user.id,
        details={"job_id": job_id, "title": title, "query_type": query_type}
    )
    
    return query


@router.post("/modules/{module_instance_id}/queries", response_model=Query)
async def create_module_query(
    module_instance_id: str,
    title: str = QueryParam(...),
    query_type: str = QueryParam("text"),
    initial_message: Optional[str] = None,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Create a query at module level"""
    module_repo = ModuleInstanceRepository(db)
    job_repo = WorkpaperJobRepository(db)
    query_repo = QueryRepository(db)
    message_repo = QueryMessageRepository(db)
    
    module = await module_repo.get(module_instance_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    job = await job_repo.get(module.job_id)
    
    query = Query(
        client_id=job.client_id,
        job_id=module.job_id,
        module_instance_id=module_instance_id,
        title=title,
        query_type=query_type,
        status=QueryStatus.DRAFT.value,
        created_by_admin_id=current_user.id,
        created_by_admin_email=current_user.email,
    )
    
    query = await query_repo.create(query)
    
    if initial_message:
        message = QueryMessage(
            query_id=query.id,
            sender_type=SenderType.ADMIN.value,
            sender_id=current_user.id,
            sender_email=current_user.email,
            message_text=initial_message,
        )
        await message_repo.create(message)
    
    return query


@router.get("/jobs/{job_id}/queries", response_model=List[Query])
async def list_job_queries(
    job_id: str,
    status: Optional[str] = None,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """List queries for a job"""
    query_repo = QueryRepository(db)
    return await query_repo.list_by_job(job_id, status)


@router.post("/queries/{query_id}/send", response_model=Query)
async def send_query(
    query_id: str,
    message: Optional[str] = None,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Send a draft query to the client"""
    query_repo = QueryRepository(db)
    message_repo = QueryMessageRepository(db)
    
    query = await query_repo.get(query_id)
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")
    
    if query.status != QueryStatus.DRAFT.value:
        raise HTTPException(status_code=400, detail=f"Can only send queries in DRAFT status. Current: {query.status}")
    
    if message:
        msg = QueryMessage(
            query_id=query_id,
            sender_type=SenderType.ADMIN.value,
            sender_id=current_user.id,
            sender_email=current_user.email,
            message_text=message,
        )
        await message_repo.create(msg)
    
    query = await query_repo.update(query_id, {"status": QueryStatus.SENT_TO_CLIENT.value})
    
    # Update or create task
    await _update_queries_task(db, query.client_id, query.job_id)
    
    log_action(
        action=AuditAction.WORKPAPER_QUERY_SEND,
        resource_type=ResourceType.WORKPAPER_QUERY,
        resource_id=query_id,
        user_id=current_user.id,
        details={"status": QueryStatus.SENT_TO_CLIENT.value}
    )
    
    return query


@router.post("/queries/{query_id}/messages", response_model=QueryMessage)
async def add_query_message(
    query_id: str,
    request: AddMessageRequest,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Add a message to a query (admin)"""
    query_repo = QueryRepository(db)
    message_repo = QueryMessageRepository(db)
    
    query = await query_repo.get(query_id)
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")
    
    message = QueryMessage(
        query_id=query_id,
        sender_type=SenderType.ADMIN.value,
        sender_id=current_user.id,
        sender_email=current_user.email,
        message_text=request.message_text,
        attachment_url=request.attachment_url,
        attachment_name=request.attachment_name,
    )
    
    message = await message_repo.create(message)
    
    # Update query status if client had responded
    if query.status == QueryStatus.CLIENT_RESPONDED.value:
        await query_repo.update(query_id, {"status": QueryStatus.AWAITING_CLIENT.value})
    
    return message


@router.get("/queries/{query_id}/messages", response_model=List[QueryMessage])
async def get_query_messages(
    query_id: str,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Get all messages for a query"""
    message_repo = QueryMessageRepository(db)
    return await message_repo.list_by_query(query_id)


@router.post("/queries/{query_id}/resolve", response_model=Query)
async def resolve_query(
    query_id: str,
    resolution_message: Optional[str] = None,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Mark a query as resolved"""
    query_repo = QueryRepository(db)
    message_repo = QueryMessageRepository(db)
    
    query = await query_repo.get(query_id)
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")
    
    if query.status in [QueryStatus.RESOLVED.value, QueryStatus.CLOSED.value]:
        raise HTTPException(status_code=400, detail="Query already resolved/closed")
    
    if resolution_message:
        msg = QueryMessage(
            query_id=query_id,
            sender_type=SenderType.ADMIN.value,
            sender_id=current_user.id,
            sender_email=current_user.email,
            message_text=resolution_message,
        )
        await message_repo.create(msg)
    
    query = await query_repo.update(query_id, {
        "status": QueryStatus.RESOLVED.value,
        "resolved_by_admin_id": current_user.id,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    })
    
    # Update task
    await _update_queries_task(db, query.client_id, query.job_id)
    
    log_action(
        action=AuditAction.WORKPAPER_QUERY_RESOLVE,
        resource_type=ResourceType.WORKPAPER_QUERY,
        resource_id=query_id,
        user_id=current_user.id,
        details={"resolved": True}
    )
    
    return query


# ==================== CLIENT ENDPOINTS ====================

@router.get("/clients/{client_id}/jobs/{job_id}/tasks", response_model=List[Task])
async def get_client_tasks(
    client_id: str,
    job_id: str,
    current_user: AuthUser = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Get tasks for a client's job"""
    if current_user.role == "client" and current_user.id != client_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    task_repo = TaskRepository(db)
    return await task_repo.list_by_job(job_id)


@router.post("/queries/{query_id}/client-respond")
async def client_respond_to_query(
    query_id: str,
    request: RespondToQueryRequest,
    current_user: AuthUser = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Client response to a query"""
    query_repo = QueryRepository(db)
    message_repo = QueryMessageRepository(db)
    
    query = await query_repo.get(query_id)
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")
    
    if current_user.role == "client" and current_user.id != query.client_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if query.status not in [QueryStatus.SENT_TO_CLIENT.value, QueryStatus.AWAITING_CLIENT.value]:
        raise HTTPException(status_code=400, detail=f"Cannot respond to query in status: {query.status}")
    
    if request.message_text:
        msg = QueryMessage(
            query_id=query_id,
            sender_type=SenderType.CLIENT.value,
            sender_id=current_user.id,
            sender_email=current_user.email,
            message_text=request.message_text,
            attachment_url=request.attachment_url,
        )
        await message_repo.create(msg)
    
    updates = {"status": QueryStatus.CLIENT_RESPONDED.value}
    if request.response_data:
        updates["response_data"] = request.response_data
    
    query = await query_repo.update(query_id, updates)
    
    await _update_queries_task(db, query.client_id, query.job_id)
    
    log_action(
        action=AuditAction.WORKPAPER_QUERY_RESPOND,
        resource_type=ResourceType.WORKPAPER_QUERY,
        resource_id=query_id,
        user_id=current_user.id,
        details={
            "has_response_data": request.response_data is not None,
            "has_attachment": request.attachment_url is not None,
        }
    )
    
    return query


# ==================== FREEZE ====================

@router.post("/modules/{module_id}/freeze", response_model=FreezeSnapshot)
async def freeze_module_endpoint(
    module_id: str,
    reason: Optional[str] = None,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Freeze a module"""
    module_repo = ModuleInstanceRepository(db)
    snapshot_repo = FreezeSnapshotRepository(db)
    override_repo = OverrideRecordRepository(db)
    
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Module already frozen")
    
    # Get overrides for snapshot
    overrides = await override_repo.list_by_module(module_id)
    
    # Create snapshot
    snapshot = FreezeSnapshot(
        job_id=module.job_id,
        module_instance_id=module_id,
        snapshot_type="module",
        data={
            "module": module.model_dump(),
            "overrides": [o.model_dump() for o in overrides],
        },
        summary={
            "output": module.output_summary,
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        },
        created_by_admin_id=current_user.id,
        created_by_admin_email=current_user.email,
    )
    snapshot = await snapshot_repo.create(snapshot)
    
    # Update module status
    await module_repo.update(module_id, {
        "status": JobStatus.FROZEN.value,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
    })
    
    log_action(
        action=AuditAction.WORKPAPER_MODULE_FREEZE,
        resource_type=ResourceType.WORKPAPER_MODULE,
        resource_id=module_id,
        user_id=current_user.id,
        details={"reason": reason, "snapshot_id": snapshot.id}
    )
    
    return snapshot


@router.post("/modules/{module_id}/reopen", response_model=ModuleInstance)
async def reopen_module_endpoint(
    module_id: str,
    reason: str = QueryParam(..., min_length=10, description="Reason for reopening (min 10 chars)"),
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Reopen a frozen module (admin only)"""
    module_repo = ModuleInstanceRepository(db)
    
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status != JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Module is not frozen")
    
    module = await module_repo.update(module_id, {
        "status": JobStatus.IN_PROGRESS.value,
        "frozen_at": None,
    })
    
    log_action(
        action=AuditAction.WORKPAPER_MODULE_REOPEN,
        resource_type=ResourceType.WORKPAPER_MODULE,
        resource_id=module_id,
        user_id=current_user.id,
        details={"reason": reason}
    )
    
    return module


@router.get("/jobs/{job_id}/snapshots", response_model=List[FreezeSnapshot])
async def list_job_snapshots(
    job_id: str,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """List all snapshots for a job"""
    snapshot_repo = FreezeSnapshotRepository(db)
    return await snapshot_repo.list_by_job(job_id)


@router.get("/snapshots/{snapshot_id}", response_model=FreezeSnapshot)
async def get_snapshot(
    snapshot_id: str,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific snapshot"""
    snapshot_repo = FreezeSnapshotRepository(db)
    snapshot = await snapshot_repo.get(snapshot_id)
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


# ==================== HELPER FUNCTIONS ====================

async def _update_queries_task(db: AsyncSession, client_id: str, job_id: str):
    """Update or create the QUERIES task for a job"""
    query_repo = QueryRepository(db)
    task_repo = TaskRepository(db)
    
    open_queries = await query_repo.list_open_by_job(job_id)
    open_count = len(open_queries)
    
    task = await task_repo.get_queries_task(client_id, job_id)
    
    if open_count > 0:
        query_ids = [q.id for q in open_queries]
        
        if task:
            await task_repo.update(task.id, {
                "status": TaskStatus.OPEN.value,
                "metadata": {"query_count": open_count, "query_ids": query_ids},
                "title": f"You have {open_count} open {'query' if open_count == 1 else 'queries'}",
            })
        else:
            new_task = Task(
                client_id=client_id,
                job_id=job_id,
                task_type=TaskType.QUERIES.value,
                status=TaskStatus.OPEN.value,
                title=f"You have {open_count} open {'query' if open_count == 1 else 'queries'}",
                metadata={"query_count": open_count, "query_ids": query_ids},
            )
            await task_repo.create(new_task)
    else:
        if task and task.status != TaskStatus.COMPLETED.value:
            await task_repo.update(task.id, {
                "status": TaskStatus.COMPLETED.value,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {"query_count": 0, "query_ids": []},
            })
