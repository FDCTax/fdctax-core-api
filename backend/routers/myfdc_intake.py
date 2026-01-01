"""
MyFDC Data Intake Router

API endpoints for receiving data from MyFDC application.
All endpoints require Internal Service Token authentication.

Endpoints:
- POST /api/myfdc/profile - Update educator profile
- POST /api/myfdc/hours - Log hours worked
- POST /api/myfdc/occupancy - Log occupancy data
- POST /api/myfdc/diary - Create diary entry
- POST /api/myfdc/expense - Log expense
- POST /api/myfdc/attendance - Log child attendance
- GET /api/myfdc/summary/hours - Get hours summary
- GET /api/myfdc/summary/expenses - Get expenses summary
"""

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.internal_auth import get_internal_service, InternalService
from services.myfdc_intake import MyFDCIntakeService
from models.myfdc_data import (
    EducatorProfileRequest,
    HoursWorkedRequest,
    OccupancyRequest,
    DiaryEntryRequest,
    ExpenseRequest,
    AttendanceRequest,
    DataIntakeResponse
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/myfdc", tags=["MyFDC Data Intake"])


# ==================== EDUCATOR PROFILE ====================

@router.post("/profile", response_model=DataIntakeResponse)
async def update_educator_profile(
    client_id: str,
    request: EducatorProfileRequest,
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Update educator profile for a client.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    Creates or updates the FDC educator profile data.
    """
    logger.info(f"Profile update from {service.name} for client {client_id}")
    
    intake_service = MyFDCIntakeService(db)
    
    # Verify client exists
    if not await intake_service.verify_client_exists(client_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found in Core"
        )
    
    try:
        result = await intake_service.update_educator_profile(
            client_id=client_id,
            profile_data=request.model_dump(),
            service_name=service.name
        )
        return DataIntakeResponse(**result)
    except Exception as e:
        logger.error(f"Profile update failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update educator profile"
        )


# ==================== HOURS WORKED ====================

@router.post("/hours", response_model=DataIntakeResponse)
async def log_hours_worked(
    client_id: str,
    request: HoursWorkedRequest,
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Log hours worked for an educator.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    """
    logger.info(f"Hours log from {service.name} for client {client_id}")
    
    intake_service = MyFDCIntakeService(db)
    
    if not await intake_service.verify_client_exists(client_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found in Core"
        )
    
    try:
        result = await intake_service.log_hours_worked(
            client_id=client_id,
            hours_data=request.model_dump(),
            service_name=service.name
        )
        return DataIntakeResponse(**result)
    except Exception as e:
        logger.error(f"Hours log failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to log hours worked"
        )


# ==================== OCCUPANCY ====================

@router.post("/occupancy", response_model=DataIntakeResponse)
async def log_occupancy(
    client_id: str,
    request: OccupancyRequest,
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Log occupancy data for an educator.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    """
    logger.info(f"Occupancy log from {service.name} for client {client_id}")
    
    intake_service = MyFDCIntakeService(db)
    
    if not await intake_service.verify_client_exists(client_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found in Core"
        )
    
    try:
        result = await intake_service.log_occupancy(
            client_id=client_id,
            occupancy_data=request.model_dump(),
            service_name=service.name
        )
        return DataIntakeResponse(**result)
    except Exception as e:
        logger.error(f"Occupancy log failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to log occupancy"
        )


# ==================== DIARY ENTRIES ====================

@router.post("/diary", response_model=DataIntakeResponse)
async def create_diary_entry(
    client_id: str,
    request: DiaryEntryRequest,
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a diary entry for an educator.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    """
    logger.info(f"Diary entry from {service.name} for client {client_id}")
    
    intake_service = MyFDCIntakeService(db)
    
    if not await intake_service.verify_client_exists(client_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found in Core"
        )
    
    try:
        result = await intake_service.create_diary_entry(
            client_id=client_id,
            diary_data=request.model_dump(),
            service_name=service.name
        )
        return DataIntakeResponse(**result)
    except Exception as e:
        logger.error(f"Diary entry failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create diary entry"
        )


# ==================== EXPENSES ====================

@router.post("/expense", response_model=DataIntakeResponse)
async def log_expense(
    client_id: str,
    request: ExpenseRequest,
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Log an expense for an educator.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    """
    logger.info(f"Expense log from {service.name} for client {client_id}")
    
    intake_service = MyFDCIntakeService(db)
    
    if not await intake_service.verify_client_exists(client_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found in Core"
        )
    
    try:
        result = await intake_service.log_expense(
            client_id=client_id,
            expense_data=request.model_dump(),
            service_name=service.name
        )
        return DataIntakeResponse(**result)
    except Exception as e:
        logger.error(f"Expense log failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to log expense"
        )


# ==================== ATTENDANCE ====================

@router.post("/attendance", response_model=DataIntakeResponse)
async def log_attendance(
    client_id: str,
    request: AttendanceRequest,
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Log child attendance for an educator.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    """
    logger.info(f"Attendance log from {service.name} for client {client_id}")
    
    intake_service = MyFDCIntakeService(db)
    
    if not await intake_service.verify_client_exists(client_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found in Core"
        )
    
    try:
        result = await intake_service.log_attendance(
            client_id=client_id,
            attendance_data=request.model_dump(),
            service_name=service.name
        )
        return DataIntakeResponse(**result)
    except Exception as e:
        logger.error(f"Attendance log failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to log attendance"
        )


# ==================== SUMMARY ENDPOINTS (for CRM) ====================

@router.get("/summary/hours")
async def get_hours_summary(
    client_id: str,
    start_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD)"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Get hours worked summary for a date range.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    Returns aggregated hours data for CRM reporting.
    """
    intake_service = MyFDCIntakeService(db)
    
    if not await intake_service.verify_client_exists(client_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found in Core"
        )
    
    try:
        return await intake_service.get_hours_summary(
            client_id=client_id,
            start_date=start_date,
            end_date=end_date
        )
    except Exception as e:
        logger.error(f"Hours summary failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get hours summary"
        )


@router.get("/summary/expenses")
async def get_expenses_summary(
    client_id: str,
    start_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD)"),
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Get expenses summary for a date range.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    Returns aggregated expense data by category for CRM reporting.
    """
    intake_service = MyFDCIntakeService(db)
    
    if not await intake_service.verify_client_exists(client_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found in Core"
        )
    
    try:
        return await intake_service.get_expenses_summary(
            client_id=client_id,
            start_date=start_date,
            end_date=end_date
        )
    except Exception as e:
        logger.error(f"Expenses summary failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get expenses summary"
        )


# ==================== STATUS ENDPOINT ====================

@router.get("/status")
async def get_myfdc_intake_status(
    service: InternalService = Depends(get_internal_service)
):
    """
    Get MyFDC data intake module status.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    """
    return {
        "module": "myfdc_intake",
        "status": "operational",
        "version": "1.0.0",
        "endpoints": [
            "POST /api/myfdc/profile",
            "POST /api/myfdc/hours",
            "POST /api/myfdc/occupancy",
            "POST /api/myfdc/diary",
            "POST /api/myfdc/expense",
            "POST /api/myfdc/attendance",
            "GET /api/myfdc/summary/hours",
            "GET /api/myfdc/summary/expenses"
        ],
        "authentication": "Internal Service Token (X-Internal-Api-Key)"
    }
