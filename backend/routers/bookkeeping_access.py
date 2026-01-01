"""
CRM Bookkeeping Data Access Router

API endpoints for CRM Bookkeeping to retrieve all MyFDC-submitted data.
Powers the CRM Bookkeeping UI and Workpapers.

All endpoints require Internal Service Token authentication.

Endpoints:
- GET /api/bookkeeping/{client_id}/hours - Hours worked records
- GET /api/bookkeeping/{client_id}/occupancy - Occupancy records
- GET /api/bookkeeping/{client_id}/diary - Diary entries
- GET /api/bookkeeping/{client_id}/expenses - Expense records
- GET /api/bookkeeping/{client_id}/attendance - Attendance records
- GET /api/bookkeeping/{client_id}/summary - Combined summary for dashboard
"""

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Depends, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.internal_auth import get_internal_service, InternalService
from services.bookkeeping_access import BookkeepingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bookkeeping", tags=["CRM Bookkeeping"])


# ==================== HOURS WORKED ====================

@router.get("/{client_id}/hours")
async def get_hours_worked(
    client_id: str = Path(..., description="Client UUID"),
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Get hours worked records for a client.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    **Returns:**
    - List of hours worked records
    - Summary with total hours, days worked, average
    
    **Query Params:**
    - `start_date`: Filter from date (optional)
    - `end_date`: Filter to date (optional)
    """
    logger.info(f"Hours access from {service.name} for client {client_id}")
    
    bookkeeping = BookkeepingService(db)
    
    if not await bookkeeping.verify_client_exists(client_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found in Core"
        )
    
    try:
        return await bookkeeping.get_hours_worked(
            client_id=client_id,
            start_date=start_date,
            end_date=end_date,
            service_name=service.name
        )
    except Exception as e:
        logger.error(f"Hours retrieval failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve hours data"
        )


# ==================== OCCUPANCY ====================

@router.get("/{client_id}/occupancy")
async def get_occupancy(
    client_id: str = Path(..., description="Client UUID"),
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Get occupancy records for a client.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    **Returns:**
    - List of daily occupancy records
    - Room usage breakdown
    - Child count summaries
    
    **Query Params:**
    - `start_date`: Filter from date (optional)
    - `end_date`: Filter to date (optional)
    """
    logger.info(f"Occupancy access from {service.name} for client {client_id}")
    
    bookkeeping = BookkeepingService(db)
    
    if not await bookkeeping.verify_client_exists(client_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found in Core"
        )
    
    try:
        return await bookkeeping.get_occupancy(
            client_id=client_id,
            start_date=start_date,
            end_date=end_date,
            service_name=service.name
        )
    except Exception as e:
        logger.error(f"Occupancy retrieval failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve occupancy data"
        )


# ==================== DIARY ENTRIES ====================

@router.get("/{client_id}/diary")
async def get_diary_entries(
    client_id: str = Path(..., description="Client UUID"),
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    category: Optional[str] = Query(None, description="Filter by category"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Get diary entries for a client.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    **Returns:**
    - List of diary entries
    - Category breakdown
    - Photo counts
    
    **Query Params:**
    - `start_date`: Filter from date (optional)
    - `end_date`: Filter to date (optional)
    - `category`: Filter by category (activity, observation, etc.)
    """
    logger.info(f"Diary access from {service.name} for client {client_id}")
    
    bookkeeping = BookkeepingService(db)
    
    if not await bookkeeping.verify_client_exists(client_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found in Core"
        )
    
    try:
        return await bookkeeping.get_diary_entries(
            client_id=client_id,
            start_date=start_date,
            end_date=end_date,
            category=category,
            service_name=service.name
        )
    except Exception as e:
        logger.error(f"Diary retrieval failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve diary data"
        )


# ==================== EXPENSES ====================

@router.get("/{client_id}/expenses")
async def get_expenses(
    client_id: str = Path(..., description="Client UUID"),
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    category: Optional[str] = Query(None, description="Filter by category"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Get expense records for a client.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    **Returns:**
    - List of expenses with GST flags, business %
    - Category breakdown with totals
    - Tax deductible amounts
    
    **Query Params:**
    - `start_date`: Filter from date (optional)
    - `end_date`: Filter to date (optional)
    - `category`: Filter by category (food, equipment, etc.)
    """
    logger.info(f"Expenses access from {service.name} for client {client_id}")
    
    bookkeeping = BookkeepingService(db)
    
    if not await bookkeeping.verify_client_exists(client_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found in Core"
        )
    
    try:
        return await bookkeeping.get_expenses(
            client_id=client_id,
            start_date=start_date,
            end_date=end_date,
            category=category,
            service_name=service.name
        )
    except Exception as e:
        logger.error(f"Expenses retrieval failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve expenses data"
        )


# ==================== ATTENDANCE ====================

@router.get("/{client_id}/attendance")
async def get_attendance(
    client_id: str = Path(..., description="Client UUID"),
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    child_name: Optional[str] = Query(None, description="Filter by child name"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Get attendance records for a client.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    **Returns:**
    - List of child attendance records
    - CCS hours tracking
    - Daily totals
    - Per-child breakdown
    
    **Query Params:**
    - `start_date`: Filter from date (optional)
    - `end_date`: Filter to date (optional)
    - `child_name`: Filter by child name (partial match)
    """
    logger.info(f"Attendance access from {service.name} for client {client_id}")
    
    bookkeeping = BookkeepingService(db)
    
    if not await bookkeeping.verify_client_exists(client_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found in Core"
        )
    
    try:
        return await bookkeeping.get_attendance(
            client_id=client_id,
            start_date=start_date,
            end_date=end_date,
            child_name=child_name,
            service_name=service.name
        )
    except Exception as e:
        logger.error(f"Attendance retrieval failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve attendance data"
        )


# ==================== COMBINED SUMMARY ====================

@router.get("/{client_id}/summary")
async def get_bookkeeping_summary(
    client_id: str = Path(..., description="Client UUID"),
    start_date: Optional[date] = Query(None, description="Start date (defaults to 30 days ago)"),
    end_date: Optional[date] = Query(None, description="End date (defaults to today)"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Get combined bookkeeping summary for CRM dashboard.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    **Returns:**
    - Educator profile status
    - Hours worked summary
    - Occupancy summary
    - Expense summary
    - Diary entry count
    - Attendance summary
    - Data completeness indicators
    
    **Query Params:**
    - `start_date`: Period start (defaults to 30 days ago)
    - `end_date`: Period end (defaults to today)
    """
    logger.info(f"Summary access from {service.name} for client {client_id}")
    
    bookkeeping = BookkeepingService(db)
    
    if not await bookkeeping.verify_client_exists(client_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found in Core"
        )
    
    try:
        return await bookkeeping.get_bookkeeping_summary(
            client_id=client_id,
            start_date=start_date,
            end_date=end_date,
            service_name=service.name
        )
    except Exception as e:
        logger.error(f"Summary retrieval failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve summary data"
        )


# ==================== STATUS ENDPOINT ====================

@router.get("/status")
async def get_bookkeeping_status(
    service: InternalService = Depends(get_internal_service)
):
    """
    Get CRM Bookkeeping module status.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    """
    return {
        "module": "crm_bookkeeping",
        "status": "operational",
        "version": "1.0.0",
        "endpoints": [
            "GET /api/bookkeeping/{client_id}/hours",
            "GET /api/bookkeeping/{client_id}/occupancy",
            "GET /api/bookkeeping/{client_id}/diary",
            "GET /api/bookkeeping/{client_id}/expenses",
            "GET /api/bookkeeping/{client_id}/attendance",
            "GET /api/bookkeeping/{client_id}/summary"
        ],
        "authentication": "Internal Service Token (X-Internal-Api-Key)",
        "data_source": "MyFDC Data (via Core)"
    }
