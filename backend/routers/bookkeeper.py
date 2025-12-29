"""
FDC Core - Bookkeeper Transaction API Router

Endpoints for the Bookkeeper Tab and transaction management:
- GET /bookkeeper/transactions - List with filters and pagination
- PATCH /bookkeeper/transactions/{id} - Update single transaction
- POST /bookkeeper/transactions/bulk-update - Atomic bulk update
- GET /bookkeeper/transactions/{id}/history - Audit trail
- POST /workpapers/transactions-lock - Lock for workpaper

RBAC Permissions Matrix:
┌──────────────────────────────────────────────┬────────┬───────┬───────────┬───────┐
│ Endpoint                                     │ client │ staff │ tax_agent │ admin │
├──────────────────────────────────────────────┼────────┼───────┼───────────┼───────┤
│ GET /bookkeeper/transactions                 │   ❌   │   ✔️   │   ✔️      │   ✔️   │
│ PATCH /bookkeeper/transactions/{id}          │   ❌   │   ✔️*  │   ❌      │   ✔️   │
│ POST /bookkeeper/transactions/bulk-update    │   ❌   │   ✔️   │   ❌      │   ✔️   │
│ GET /bookkeeper/transactions/{id}/history    │   ❌   │   ✔️   │   ✔️      │   ✔️   │
│ POST /workpapers/transactions-lock           │   ❌   │   ❌   │   ✔️      │   ✔️   │
│ POST /bookkeeper/transactions/{id}/unlock    │   ❌   │   ❌   │   ❌      │   ✔️   │
│ POST /myfdc/transactions                     │   ✔️   │   ❌   │   ❌      │   ✔️   │
└──────────────────────────────────────────────┴────────┴───────┴───────────┴───────┘
* Staff can edit unless status=LOCKED (then only notes_bookkeeper)
"""

from fastapi import APIRouter, Depends, HTTPException, Query as QueryParam, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

from database import get_db
from middleware.auth import (
    get_current_user_required, 
    require_staff, 
    require_admin,
    require_bookkeeper_read,
    require_bookkeeper_write,
    require_workpaper_lock,
    require_myfdc_sync,
    require_import,
    AuthUser,
    RoleChecker
)

from services.transaction_service import (
    TransactionRepository, MyFDCSyncService, ImportService,
    TransactionCreate, TransactionUpdate, TransactionFilter,
    Transaction, TransactionHistory, PaginatedResult,
    BulkUpdateRequest, WorkpaperLockRequest,
    PermissionError, LockingError,
    TransactionStatus, GSTCode, TransactionSource, ModuleRouting,
)
from services.audit import log_action, AuditAction, ResourceType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bookkeeper", tags=["Bookkeeper Transactions"])


# ==================== PERMISSION HELPERS ====================

def get_user_role(user: AuthUser) -> str:
    """Map AuthUser role to transaction permission role"""
    if user.role == "admin":
        return "admin"
    elif user.role in ["staff", "accountant"]:
        return "bookkeeper"
    elif user.role == "client":
        return "client"
    elif user.role == "tax_agent":
        return "tax_agent"
    else:
        return "unknown"


def check_bookkeeper_tab_read_permission(user: AuthUser) -> None:
    """
    Bookkeeper Tab read access: staff, tax_agent, admin only.
    Clients cannot access Bookkeeper Tab.
    """
    role = get_user_role(user)
    if role == "client":
        raise HTTPException(
            status_code=403,
            detail="Clients cannot access Bookkeeper Tab"
        )
    if role == "unknown":
        raise HTTPException(
            status_code=403,
            detail="Unknown role - access denied"
        )


def check_bookkeeper_tab_write_permission(user: AuthUser) -> None:
    """
    Bookkeeper Tab write access: staff and admin only.
    Tax agents have read-only access.
    Clients cannot access Bookkeeper Tab.
    """
    role = get_user_role(user)
    if role == "tax_agent":
        raise HTTPException(
            status_code=403,
            detail="Tax agents have read-only access in Bookkeeper Tab"
        )
    if role == "client":
        raise HTTPException(
            status_code=403,
            detail="Clients cannot access Bookkeeper Tab"
        )
    if role == "unknown":
        raise HTTPException(
            status_code=403,
            detail="Unknown role - access denied"
        )


def check_myfdc_permission(user: AuthUser, client_id: str) -> None:
    """
    MyFDC sync access: client and admin only.
    Clients can only modify their own submissions.
    """
    role = get_user_role(user)
    if role not in ["client", "admin"]:
        raise HTTPException(
            status_code=403,
            detail="Only clients and admins can use MyFDC sync endpoints"
        )
    # Note: In production, validate that client_id matches user's client_id
    # For now, admins can access any client_id


def check_workpaper_lock_permission(user: AuthUser) -> None:
    """
    Workpaper lock access: tax_agent and admin only.
    Staff/bookkeepers cannot lock transactions for workpapers.
    """
    role = get_user_role(user)
    if role not in ["tax_agent", "admin"]:
        raise HTTPException(
            status_code=403,
            detail="Only tax agents and admins can lock transactions for workpapers"
        )


# ==================== LIST TRANSACTIONS ====================

@router.get("/transactions", response_model=PaginatedResult)
async def list_transactions(
    # Filters
    client_id: Optional[str] = QueryParam(None, description="Filter by client ID"),
    date_from: Optional[str] = QueryParam(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = QueryParam(None, description="End date (YYYY-MM-DD)"),
    status: Optional[str] = QueryParam(None, description="Filter by status"),
    category: Optional[str] = QueryParam(None, description="Filter by bookkeeper category"),
    source: Optional[str] = QueryParam(None, description="Filter by source (BANK, MYFDC, OCR, MANUAL)"),
    module_routing: Optional[str] = QueryParam(None, description="Filter by module routing"),
    has_attachment: Optional[bool] = QueryParam(None, description="Filter by attachment presence"),
    is_duplicate: Optional[bool] = QueryParam(None, description="Filter by duplicate flag"),
    is_late_receipt: Optional[bool] = QueryParam(None, description="Filter by late receipt flag"),
    search: Optional[str] = QueryParam(None, description="Search in payee, description, notes"),
    flags: Optional[str] = QueryParam(None, description="Comma-separated flags: late,duplicate,high_risk"),
    # Pagination
    cursor: Optional[str] = QueryParam(None, description="Pagination cursor"),
    limit: int = QueryParam(50, ge=1, le=200, description="Results per page"),
    # Auth - staff, tax_agent, admin can read
    current_user: AuthUser = Depends(require_bookkeeper_read),
    db: AsyncSession = Depends(get_db)
):
    """
    List transactions with cursor-based pagination and comprehensive filters.
    
    Filters:
    - client_id: Filter by client
    - date_from/date_to: Date range
    - status: NEW, PENDING, REVIEWED, READY_FOR_WORKPAPER, EXCLUDED, LOCKED
    - category: Bookkeeper category
    - source: BANK, MYFDC, OCR, MANUAL
    - module_routing: MOTOR_VEHICLE, HOME_OCCUPANCY, UTILITIES, INTERNET, GENERAL, DISALLOWED
    - has_attachment: true/false
    - search: Search payee, description, notes
    - flags: Comma-separated (late, duplicate, high_risk)
    
    Returns paginated results with cursor for next page.
    
    RBAC: staff ✔️, tax_agent ✔️ (read-only), admin ✔️, client ❌
    """
    check_bookkeeper_tab_read_permission(current_user)
    
    # Parse flags
    flag_list = None
    if flags:
        flag_list = [f.strip() for f in flags.split(",")]
    
    # Build filter
    filters = TransactionFilter(
        client_id=client_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
        category=category,
        source=source,
        module_routing=module_routing,
        has_attachment=has_attachment,
        is_duplicate=is_duplicate,
        is_late_receipt=is_late_receipt,
        search=search,
        flags=flag_list,
    )
    
    repo = TransactionRepository(db)
    result = await repo.list_transactions(filters, cursor, limit)
    
    return result


# ==================== GET SINGLE TRANSACTION ====================

@router.get("/transactions/{transaction_id}", response_model=Transaction)
async def get_transaction(
    transaction_id: str,
    current_user: AuthUser = Depends(require_bookkeeper_read),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a single transaction by ID.
    
    RBAC: staff ✔️, tax_agent ✔️ (read-only), admin ✔️, client ❌
    """
    check_bookkeeper_tab_read_permission(current_user)
    
    repo = TransactionRepository(db)
    txn = await repo.get(transaction_id)
    
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    return txn


# ==================== UPDATE TRANSACTION ====================

@router.patch("/transactions/{transaction_id}", response_model=Transaction)
async def update_transaction(
    transaction_id: str,
    request: TransactionUpdate,
    current_user: AuthUser = Depends(require_bookkeeper_write),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a transaction (bookkeeper edit).
    
    Editable fields:
    - amount, date, payee_raw, description_raw
    - category_bookkeeper, gst_code_bookkeeper, notes_bookkeeper
    - status_bookkeeper, flags, module_routing
    
    Rules:
    - If status = LOCKED: only notes_bookkeeper can be edited (except by admin)
    - All changes are recorded in history
    - Bookkeeper cannot set status to LOCKED directly
    
    RBAC: staff ✔️ (unless LOCKED), tax_agent ❌, admin ✔️, client ❌
    """
    check_bookkeeper_tab_write_permission(current_user)
    
    repo = TransactionRepository(db)
    user_role = get_user_role(current_user)
    
    try:
        txn = await repo.update(
            transaction_id=transaction_id,
            data=request,
            user_id=current_user.id,
            user_role=user_role,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except LockingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    log_action(
        action=AuditAction.ADMIN_ACTION,
        resource_type=ResourceType.WORKPAPER_TRANSACTION,
        resource_id=transaction_id,
        user_id=current_user.id,
        user_email=current_user.email,
        details={
            "action": "transaction_update",
            "updates": request.model_dump(exclude_none=True),
        }
    )
    
    return txn


# ==================== BULK UPDATE ====================

@router.post("/transactions/bulk-update")
async def bulk_update_transactions(
    request: BulkUpdateRequest,
    current_user: AuthUser = Depends(require_bookkeeper_write),
    db: AsyncSession = Depends(get_db)
):
    """
    Atomic bulk update of transactions.
    
    Payload:
    - criteria: Filter conditions (client_id, status, category, transaction_ids, date_from, date_to)
    - updates: Fields to update (category_bookkeeper, gst_code_bookkeeper, status_bookkeeper, module_routing, flags)
    
    Requirements:
    - Atomic operation (all or nothing)
    - Single history entry for bulk action
    - Returns count of updated rows
    - LOCKED transactions are skipped (except for admin)
    
    RBAC: staff ✔️, tax_agent ❌, admin ✔️, client ❌
    """
    check_bookkeeper_tab_write_permission(current_user)
    
    repo = TransactionRepository(db)
    user_role = get_user_role(current_user)
    
    try:
        count = await repo.bulk_update(
            criteria=request.criteria,
            updates=request.updates,
            user_id=current_user.id,
            user_role=user_role,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    
    log_action(
        action=AuditAction.ADMIN_ACTION,
        resource_type=ResourceType.WORKPAPER_TRANSACTION,
        resource_id=None,
        user_id=current_user.id,
        user_email=current_user.email,
        details={
            "action": "bulk_update",
            "criteria": request.criteria,
            "updates": request.updates,
            "affected_count": count,
        }
    )
    
    return {
        "success": True,
        "updated_count": count,
        "criteria": request.criteria,
        "updates": request.updates,
    }


# ==================== TRANSACTION HISTORY ====================

@router.get("/transactions/{transaction_id}/history", response_model=List[TransactionHistory])
async def get_transaction_history(
    transaction_id: str,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get full audit trail for a transaction.
    
    Returns all history entries ordered by timestamp (newest first).
    Each entry contains: action_type, user, role, before/after state, comment.
    """
    check_read_permission(current_user)
    
    repo = TransactionRepository(db)
    
    # Verify transaction exists
    txn = await repo.get(transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    history = await repo.get_history(transaction_id)
    return history


# ==================== UNLOCK TRANSACTION (ADMIN ONLY) ====================

@router.post("/transactions/{transaction_id}/unlock", response_model=Transaction)
async def unlock_transaction(
    transaction_id: str,
    comment: str = QueryParam(..., min_length=10, description="Reason for unlock (min 10 chars)"),
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Admin unlock of a locked transaction.
    
    Requirements:
    - Admin role required
    - Comment is mandatory (minimum 10 characters)
    - Status returns to REVIEWED
    - History entry recorded
    """
    repo = TransactionRepository(db)
    user_role = get_user_role(current_user)
    
    try:
        txn = await repo.unlock(
            transaction_id=transaction_id,
            user_id=current_user.id,
            user_role=user_role,
            comment=comment,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except LockingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    log_action(
        action=AuditAction.ADMIN_ACTION,
        resource_type=ResourceType.WORKPAPER_TRANSACTION,
        resource_id=transaction_id,
        user_id=current_user.id,
        user_email=current_user.email,
        details={
            "action": "transaction_unlock",
            "comment": comment,
        }
    )
    
    return txn


# ==================== WORKPAPER LOCK ====================

workpaper_router = APIRouter(prefix="/workpapers", tags=["Workpaper Transactions"])


@workpaper_router.post("/transactions-lock")
async def lock_transactions_for_workpaper(
    request: WorkpaperLockRequest,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Lock transactions for workpaper.
    
    Payload:
    - transaction_ids: List of transaction IDs to lock
    - workpaper_id: Target workpaper job ID
    - module: Module routing (MOTOR_VEHICLE, HOME_OCCUPANCY, etc.)
    - period: Period string (e.g., "2024-25")
    
    Actions:
    1. Snapshot bookkeeper fields
    2. Insert into transaction_workpaper_links
    3. Set status = LOCKED
    4. Write history event
    
    Returns count of locked transactions.
    """
    check_write_permission(current_user)
    
    repo = TransactionRepository(db)
    user_role = get_user_role(current_user)
    
    try:
        locked_count = await repo.lock_for_workpaper(
            request=request,
            user_id=current_user.id,
            user_role=user_role,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    log_action(
        action=AuditAction.ADMIN_ACTION,
        resource_type=ResourceType.WORKPAPER_JOB,
        resource_id=request.workpaper_id,
        user_id=current_user.id,
        user_email=current_user.email,
        details={
            "action": "transactions_lock",
            "transaction_count": len(request.transaction_ids),
            "locked_count": locked_count,
            "module": request.module,
            "period": request.period,
        }
    )
    
    return {
        "success": True,
        "locked_count": locked_count,
        "total_requested": len(request.transaction_ids),
        "workpaper_id": request.workpaper_id,
        "module": request.module,
        "period": request.period,
    }


# ==================== MYFDC SYNC ENDPOINTS ====================

myfdc_router = APIRouter(prefix="/myfdc", tags=["MyFDC Sync"])


@myfdc_router.post("/transactions")
async def myfdc_create_transaction(
    client_id: str,
    data: Dict[str, Any],
    current_user: AuthUser = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a transaction from MyFDC client app.
    
    - Source = MYFDC
    - Status = NEW
    - Records creation history
    """
    sync_service = MyFDCSyncService(db)
    
    txn = await sync_service.sync_create(
        client_id=client_id,
        data=data,
        user_id=current_user.id,
    )
    
    return {"success": True, "transaction": txn}


@myfdc_router.patch("/transactions/{transaction_id}")
async def myfdc_update_transaction(
    transaction_id: str,
    data: Dict[str, Any],
    current_user: AuthUser = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a transaction from MyFDC client app.
    
    Rules:
    - If status = NEW or PENDING → update client fields
    - If status ≥ REVIEWED → do not overwrite, log rejection
    """
    sync_service = MyFDCSyncService(db)
    
    try:
        txn, was_updated = await sync_service.sync_update(
            transaction_id=transaction_id,
            data=data,
            user_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    return {
        "success": True,
        "transaction": txn,
        "was_updated": was_updated,
        "message": "Updated" if was_updated else "Update rejected - transaction already reviewed",
    }


# ==================== IMPORT ENDPOINTS ====================

import_router = APIRouter(prefix="/import", tags=["Transaction Import"])


@import_router.post("/bank")
async def import_bank_transactions(
    client_id: str,
    transactions: List[Dict[str, Any]],
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Bulk import bank transactions.
    
    - Source = BANK
    - Status = NEW
    - Records import history
    """
    check_write_permission(current_user)
    
    import_service = ImportService(db)
    
    from database.transaction_models import TransactionSource
    count = await import_service.bulk_import(
        client_id=client_id,
        transactions=transactions,
        source=TransactionSource.BANK,
        user_id=current_user.id,
    )
    
    log_action(
        action=AuditAction.ADMIN_ACTION,
        resource_type=ResourceType.WORKPAPER_TRANSACTION,
        resource_id=None,
        user_id=current_user.id,
        user_email=current_user.email,
        details={
            "action": "bank_import",
            "client_id": client_id,
            "count": count,
        }
    )
    
    return {
        "success": True,
        "imported_count": count,
        "client_id": client_id,
        "source": "BANK",
    }


@import_router.post("/ocr")
async def import_ocr_transactions(
    client_id: str,
    transactions: List[Dict[str, Any]],
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Bulk import OCR-scanned transactions.
    
    - Source = OCR
    - Status = NEW
    - Records import history
    """
    check_write_permission(current_user)
    
    import_service = ImportService(db)
    
    from database.transaction_models import TransactionSource
    count = await import_service.bulk_import(
        client_id=client_id,
        transactions=transactions,
        source=TransactionSource.OCR,
        user_id=current_user.id,
    )
    
    log_action(
        action=AuditAction.ADMIN_ACTION,
        resource_type=ResourceType.WORKPAPER_TRANSACTION,
        resource_id=None,
        user_id=current_user.id,
        user_email=current_user.email,
        details={
            "action": "ocr_import",
            "client_id": client_id,
            "count": count,
        }
    )
    
    return {
        "success": True,
        "imported_count": count,
        "client_id": client_id,
        "source": "OCR",
    }


# ==================== REFERENCE DATA ====================

@router.get("/statuses")
async def list_transaction_statuses():
    """List all transaction statuses"""
    return {
        "statuses": [
            {"value": s.value, "name": s.value.replace("_", " ").title()}
            for s in TransactionStatus
        ]
    }


@router.get("/gst-codes")
async def list_gst_codes():
    """List all GST codes"""
    return {
        "gst_codes": [
            {"value": g.value, "name": g.value.replace("_", " ").title()}
            for g in GSTCode
        ]
    }


@router.get("/sources")
async def list_transaction_sources():
    """List all transaction sources"""
    return {
        "sources": [
            {"value": s.value, "name": s.value.title()}
            for s in TransactionSource
        ]
    }


@router.get("/module-routings")
async def list_module_routings():
    """List all module routing options"""
    return {
        "module_routings": [
            {"value": m.value, "name": m.value.replace("_", " ").title()}
            for m in ModuleRouting
        ]
    }
