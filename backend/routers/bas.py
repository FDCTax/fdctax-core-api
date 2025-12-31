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

Permissions:
- admin: full access
- staff: full access (bookkeepers)
- tax_agent: full access (accountants)
- client: read-only (view own BAS)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import date
import logging

from database import get_db
from middleware.auth import RoleChecker, AuthUser

from bas.service import BASStatementService, BASChangeLogService

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/bas", tags=["BAS - Business Activity Statement"])

# Permission checkers
require_bas_write = RoleChecker(["admin", "staff", "tax_agent"])
require_bas_read = RoleChecker(["admin", "staff", "tax_agent", "client"])


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
