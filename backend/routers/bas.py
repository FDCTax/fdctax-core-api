"""
BAS Backend - API Router

Provides REST API endpoints for BAS lifecycle:
- POST /api/bas/save - Save BAS snapshot
- GET /api/bas/history - Retrieve BAS history
- GET /api/bas/{id} - Retrieve single BAS statement
- POST /api/bas/{id}/sign-off - Sign off on BAS
- POST /api/bas/{id}/pdf - Generate PDF data
- POST /api/bas/change-log - Save change log entry
- GET /api/bas/change-log - Get change log entries
- Workflow endpoints (initialize, complete, reject, assign)
- History endpoints (grouped, compare)

Permissions:
- admin: full access
- staff: full access (bookkeepers)
- tax_agent: full access (accountants)
- client: read-only (view own BAS)
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import date
import logging

from database import get_db
from middleware.auth import RoleChecker, AuthUser

from bas.service import BASStatementService, BASChangeLogService, BASWorkflowService, BASHistoryService

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/bas", tags=["BAS - Business Activity Statement"])

# Permission checkers
require_bas_write = RoleChecker(["admin", "staff", "tax_agent"])
require_bas_read = RoleChecker(["admin", "staff", "tax_agent", "client"])
require_admin = RoleChecker(["admin"])


# ==================== REQUEST/RESPONSE MODELS ====================

class BASSummary(BaseModel):
    """BAS summary fields"""
    g1_total_income: float = Field(0, description="G1 - Total sales")
    gst_on_income_1a: float = Field(0, description="1A - GST on sales")
    gst_on_expenses_1b: float = Field(0, description="1B - GST on purchases")
    net_gst: float = Field(0, description="Net GST amount")
    g2_export_sales: float = Field(0, description="G2 - Export sales")
    g3_gst_free_sales: float = Field(0, description="G3 - GST-free sales")
    g10_capital_purchases: float = Field(0, description="G10 - Capital purchases")
    g11_non_capital_purchases: float = Field(0, description="G11 - Non-capital purchases")
    payg_instalment: float = Field(0, description="PAYG instalment")
    total_payable: float = Field(0, description="Total amount payable")


class SaveBASRequest(BaseModel):
    """Request to save BAS snapshot"""
    client_id: str = Field(..., description="Client ID")
    job_id: Optional[str] = Field(None, description="Job ID")
    period_from: date = Field(..., description="Period start date")
    period_to: date = Field(..., description="Period end date")
    summary: BASSummary = Field(..., description="BAS summary data")
    notes: Optional[str] = Field(None, description="Notes")
    status: str = Field("draft", description="Status: draft, completed")


class SignOffRequest(BaseModel):
    """Request to sign off on BAS"""
    review_notes: Optional[str] = Field(None, description="Review notes")


class ChangeLogRequest(BaseModel):
    """Request to log a change"""
    client_id: str = Field(..., description="Client ID")
    job_id: Optional[str] = Field(None, description="Job ID")
    bas_statement_id: Optional[str] = Field(None, description="BAS statement ID")
    action_type: str = Field(..., description="Action type")
    entity_type: str = Field(..., description="Entity type")
    entity_id: Optional[str] = Field(None, description="Entity ID")
    old_value: Optional[Dict[str, Any]] = Field(None, description="Old value (JSON)")
    new_value: Optional[Dict[str, Any]] = Field(None, description="New value (JSON)")
    reason: Optional[str] = Field(None, description="Reason for change")


# ==================== ENDPOINTS ====================

@router.get("/status")
async def get_bas_status():
    """
    Get BAS module status.
    
    Returns module version and feature availability.
    No authentication required.
    """
    return {
        "status": "ok",
        "module": "bas",
        "version": "0.0.1",
        "features": {
            "save_snapshot": True,
            "history": True,
            "sign_off": True,
            "pdf_generation": True,
            "change_log": True,
            "calculate": False,  # Stub - Phase 1
            "validate": False,   # Stub - Phase 1
            "lodgeit_export": False  # Future
        }
    }


@router.post("/validate")
async def validate_bas(
    current_user: AuthUser = Depends(require_bas_write)
):
    """
    Validate transactions for BAS calculation.
    
    **Phase 0 Status:** This endpoint is a stub and will return `not_implemented`.
    Validation logic will be added in Phase 1.
    
    **Permissions:** staff, tax_agent, admin
    """
    return {
        "status": "not_implemented",
        "message": "BAS validation is not implemented yet. This is Phase 0 scaffolding."
    }


@router.post("/calculate")
async def calculate_bas(
    current_user: AuthUser = Depends(require_bas_write)
):
    """
    Calculate BAS from transactions.
    
    **Phase 0 Status:** This endpoint is a stub and will return `not_implemented`.
    Calculation logic will be added in Phase 1.
    
    **Permissions:** staff, tax_agent, admin
    """
    return {
        "status": "not_implemented",
        "message": "BAS calculation is not implemented yet. This is Phase 0 scaffolding."
    }


@router.post("/save")
async def save_bas(
    request: SaveBASRequest,
    current_user: AuthUser = Depends(require_bas_write),
    db: AsyncSession = Depends(get_db)
):
    """
    Save a BAS snapshot.
    
    Creates a new BAS record. If a BAS exists for the same client/period,
    a new version is created.
    
    **Permissions:** staff, tax_agent, admin
    """
    service = BASStatementService(db)
    
    try:
        result = await service.save_bas(
            client_id=request.client_id,
            job_id=request.job_id,
            period_from=request.period_from,
            period_to=request.period_to,
            summary=request.summary.model_dump(),
            notes=request.notes,
            status=request.status,
            user_id=current_user.id,
            user_email=current_user.email
        )
        
        return {
            "success": True,
            "message": "BAS saved successfully",
            "bas_statement": result
        }
    except Exception as e:
        logger.error(f"Failed to save BAS: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_bas_history(
    client_id: str = Query(..., description="Client ID"),
    job_id: Optional[str] = Query(None, description="Job ID filter"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: AuthUser = Depends(require_bas_read),
    db: AsyncSession = Depends(get_db)
):
    """
    Get BAS history for a client.
    
    Returns list of BAS statements with versions, sorted by period.
    
    **Permissions:** staff, tax_agent, admin, client (own records)
    """
    service = BASStatementService(db)
    
    statements = await service.get_history(
        client_id=client_id,
        job_id=job_id,
        limit=limit,
        offset=offset
    )
    
    return statements


@router.get("/{bas_id}")
async def get_bas(
    bas_id: str,
    current_user: AuthUser = Depends(require_bas_read),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a single BAS statement by ID.
    
    Returns full BAS data including change log entries.
    
    **Permissions:** staff, tax_agent, admin, client (own records)
    """
    service = BASStatementService(db)
    
    result = await service.get_bas(bas_id)
    
    if not result:
        raise HTTPException(status_code=404, detail=f"BAS {bas_id} not found")
    
    return result


@router.post("/{bas_id}/sign-off")
async def sign_off_bas(
    bas_id: str,
    request: SignOffRequest,
    current_user: AuthUser = Depends(require_bas_write),
    db: AsyncSession = Depends(get_db)
):
    """
    Sign off on a BAS statement.
    
    Marks the BAS as completed and records the sign-off user.
    
    **Permissions:** staff, tax_agent, admin
    """
    service = BASStatementService(db)
    
    try:
        result = await service.sign_off(
            bas_id=bas_id,
            user_id=current_user.id,
            user_email=current_user.email,
            review_notes=request.review_notes
        )
        
        return {
            "success": True,
            "message": "BAS signed off successfully",
            "bas_statement": result
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to sign off BAS: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{bas_id}/pdf")
async def generate_pdf(
    bas_id: str,
    current_user: AuthUser = Depends(require_bas_read),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate PDF data for a BAS statement.
    
    Returns structured JSON that can be used for frontend PDF generation.
    
    **Permissions:** staff, tax_agent, admin, client (own records)
    """
    service = BASStatementService(db)
    
    try:
        pdf_data = await service.generate_pdf_data(bas_id)
        
        return {
            "success": True,
            "pdf_data": pdf_data
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to generate PDF data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/change-log")
async def save_change_log(
    request: ChangeLogRequest,
    current_user: AuthUser = Depends(require_bas_write),
    db: AsyncSession = Depends(get_db)
):
    """
    Save a change log entry.
    
    Records audit trail for BAS-related actions.
    
    **Permissions:** staff, tax_agent, admin
    """
    service = BASChangeLogService(db)
    
    try:
        result = await service.log_change(
            client_id=request.client_id,
            job_id=request.job_id,
            bas_statement_id=request.bas_statement_id,
            user_id=current_user.id,
            user_email=current_user.email,
            user_role=current_user.role,
            action_type=request.action_type,
            entity_type=request.entity_type,
            entity_id=request.entity_id,
            old_value=request.old_value,
            new_value=request.new_value,
            reason=request.reason
        )
        
        return {
            "success": True,
            "message": "Change logged successfully",
            "change_log": result
        }
    except Exception as e:
        logger.error(f"Failed to log change: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/change-log/entries")
async def get_change_log(
    client_id: Optional[str] = Query(None, description="Client ID filter"),
    job_id: Optional[str] = Query(None, description="Job ID filter"),
    bas_statement_id: Optional[str] = Query(None, description="BAS statement ID filter"),
    action_type: Optional[str] = Query(None, description="Action type filter"),
    entity_type: Optional[str] = Query(None, description="Entity type filter"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: AuthUser = Depends(require_bas_read),
    db: AsyncSession = Depends(get_db)
):
    """
    Get change log entries with filters.
    
    **Permissions:** staff, tax_agent, admin, client (own records)
    """
    service = BASChangeLogService(db)
    
    logs = await service.get_change_log(
        client_id=client_id,
        job_id=job_id,
        bas_statement_id=bas_statement_id,
        action_type=action_type,
        entity_type=entity_type,
        limit=limit,
        offset=offset
    )
    
    return logs


# ==================== WORKFLOW ENDPOINTS ====================

class InitWorkflowRequest(BaseModel):
    """Request to initialize workflow"""
    bas_statement_id: str = Field(..., description="BAS statement ID")
    client_id: str = Field(..., description="Client ID")
    skip_client_approval: bool = Field(False, description="Skip client approval step")


class CompleteStepRequest(BaseModel):
    """Request to complete a workflow step"""
    notes: Optional[str] = Field(None, description="Completion notes")


class RejectStepRequest(BaseModel):
    """Request to reject a workflow step"""
    rejection_reason: Optional[str] = Field(None, description="Reason for rejection")


class AssignStepRequest(BaseModel):
    """Request to assign a workflow step"""
    assigned_to: str = Field(..., description="User ID to assign")
    assigned_to_email: Optional[str] = Field(None, description="Assignee email")
    assigned_to_role: Optional[str] = Field(None, description="Assignee role")
    due_date: Optional[str] = Field(None, description="Due date (ISO format)")


@router.post("/workflow/initialize")
async def initialize_workflow(
    request: InitWorkflowRequest,
    current_user: AuthUser = Depends(require_bas_write),
    db: AsyncSession = Depends(get_db)
):
    """
    Initialize workflow for a BAS statement.
    
    Creates workflow steps: PREPARE → REVIEW → APPROVE → LODGE
    
    **Permissions:** staff, tax_agent, admin
    """
    service = BASWorkflowService(db)
    
    try:
        steps = await service.initialize_workflow(
            bas_statement_id=uuid.UUID(request.bas_statement_id),
            client_id=request.client_id,
            skip_client_approval=request.skip_client_approval
        )
        
        return {
            "success": True,
            "message": "Workflow initialized",
            "steps": steps
        }
    except Exception as e:
        logger.error(f"Failed to initialize workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workflow/{bas_id}")
async def get_workflow_status(
    bas_id: str,
    current_user: AuthUser = Depends(require_bas_read),
    db: AsyncSession = Depends(get_db)
):
    """
    Get workflow status for a BAS statement.
    
    Returns all workflow steps and progress.
    
    **Permissions:** staff, tax_agent, admin, client
    """
    service = BASWorkflowService(db)
    
    status = await service.get_workflow_status(uuid.UUID(bas_id))
    return status


@router.post("/workflow/{bas_id}/step/{step_type}/complete")
async def complete_workflow_step(
    bas_id: str,
    step_type: str,
    request: CompleteStepRequest,
    current_user: AuthUser = Depends(require_bas_write),
    db: AsyncSession = Depends(get_db)
):
    """
    Complete a workflow step.
    
    Marks the step as completed and advances to next step.
    
    **Permissions:** staff, tax_agent, admin
    """
    service = BASWorkflowService(db)
    
    try:
        result = await service.complete_step(
            bas_statement_id=uuid.UUID(bas_id),
            step_type=step_type,
            user_id=current_user.id,
            user_email=current_user.email,
            notes=request.notes
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to complete step: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workflow/{bas_id}/step/{step_type}/reject")
async def reject_workflow_step(
    bas_id: str,
    step_type: str,
    request: RejectStepRequest,
    current_user: AuthUser = Depends(require_bas_write),
    db: AsyncSession = Depends(get_db)
):
    """
    Reject a workflow step.
    
    Marks the step as rejected and returns to previous step.
    
    **Permissions:** staff, tax_agent, admin
    """
    service = BASWorkflowService(db)
    
    try:
        result = await service.reject_step(
            bas_statement_id=uuid.UUID(bas_id),
            step_type=step_type,
            user_id=current_user.id,
            user_email=current_user.email,
            rejection_reason=request.rejection_reason
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to reject step: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workflow/{bas_id}/step/{step_type}/assign")
async def assign_workflow_step(
    bas_id: str,
    step_type: str,
    request: AssignStepRequest,
    current_user: AuthUser = Depends(require_bas_write),
    db: AsyncSession = Depends(get_db)
):
    """
    Assign a workflow step to a user.
    
    **Permissions:** staff, tax_agent, admin
    """
    service = BASWorkflowService(db)
    
    try:
        due_date = None
        if request.due_date:
            from datetime import datetime
            due_date = datetime.fromisoformat(request.due_date.replace('Z', '+00:00'))
        
        result = await service.assign_step(
            bas_statement_id=uuid.UUID(bas_id),
            step_type=step_type,
            assigned_to=request.assigned_to,
            assigned_to_email=request.assigned_to_email,
            assigned_to_role=request.assigned_to_role,
            due_date=due_date
        )
        return {"success": True, "step": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to assign step: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workflow/pending/me")
async def get_my_pending_steps(
    current_user: AuthUser = Depends(require_bas_read),
    db: AsyncSession = Depends(get_db)
):
    """
    Get pending workflow steps for current user.
    
    Returns steps assigned to user or matching user's role.
    
    **Permissions:** staff, tax_agent, admin, client
    """
    service = BASWorkflowService(db)
    
    steps = await service.get_pending_steps_for_user(
        user_id=current_user.id,
        user_role=current_user.role
    )
    
    return {"pending_steps": steps, "count": len(steps)}


# ==================== HISTORY ENDPOINTS ====================

@router.get("/history/grouped")
async def get_grouped_history(
    client_id: str = Query(..., description="Client ID"),
    group_by: str = Query("quarter", description="Group by: quarter, month, year"),
    year: Optional[int] = Query(None, description="Filter by year"),
    include_drafts: bool = Query(False, description="Include draft statements"),
    current_user: AuthUser = Depends(require_bas_read),
    db: AsyncSession = Depends(get_db)
):
    """
    Get BAS history grouped by period with summaries.
    
    **Permissions:** staff, tax_agent, admin, client
    """
    service = BASHistoryService(db)
    
    return await service.get_grouped_history(
        client_id=client_id,
        group_by=group_by,
        year=year,
        include_drafts=include_drafts
    )


@router.get("/history/compare")
async def compare_periods(
    client_id: str = Query(..., description="Client ID"),
    period_from: date = Query(..., description="Current period start"),
    period_to: date = Query(..., description="Current period end"),
    compare_with: str = Query("previous", description="Comparison type: previous, same_last_year"),
    current_user: AuthUser = Depends(require_bas_read),
    db: AsyncSession = Depends(get_db)
):
    """
    Compare BAS for a period with another period.
    
    **Permissions:** staff, tax_agent, admin, client
    """
    service = BASHistoryService(db)
    
    return await service.get_period_comparison(
        client_id=client_id,
        period_from=period_from,
        period_to=period_to,
        compare_with=compare_with
    )

