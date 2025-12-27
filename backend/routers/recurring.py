from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import datetime
import logging

from database import get_db
from services.recurring_tasks import (
    RecurringTaskEngine,
    RecurringTaskStorage,
    RecurringTaskTemplate,
    RecurringTaskTemplateCreate,
    RecurringTaskTemplateUpdate,
    PREDEFINED_TEMPLATES,
    create_predefined_template,
    generate_recurrence_summary,
    get_next_occurrence
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recurring", tags=["Recurring Tasks"])


# ==================== TEMPLATE MANAGEMENT ====================

@router.get("/templates", response_model=List[RecurringTaskTemplate])
async def list_recurring_templates(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    active_only: bool = Query(False, description="Only return active templates"),
    db: AsyncSession = Depends(get_db)
):
    """
    List all recurring task templates.
    Optionally filter by user_id or active status.
    """
    try:
        storage = RecurringTaskStorage()
        templates = storage.list_templates(user_id=user_id, active_only=active_only)
        return templates
    except Exception as e:
        logger.error(f"Error listing templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/templates/{template_id}", response_model=RecurringTaskTemplate)
async def get_recurring_template(
    template_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific recurring task template by ID.
    """
    try:
        storage = RecurringTaskStorage()
        template = storage.get_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        return template
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting template {template_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/templates", response_model=RecurringTaskTemplate)
async def create_recurring_template(
    template_data: RecurringTaskTemplateCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new recurring task template.
    
    RRULE Examples:
    - FREQ=MONTHLY;BYMONTHDAY=28 -> Monthly on the 28th
    - FREQ=WEEKLY;BYDAY=MO,FR -> Weekly on Monday and Friday
    - FREQ=YEARLY;BYMONTH=6;BYMONTHDAY=30 -> Yearly on June 30
    """
    try:
        storage = RecurringTaskStorage()
        template = storage.create_template(template_data)
        return template
    except Exception as e:
        logger.error(f"Error creating template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/templates/{template_id}", response_model=RecurringTaskTemplate)
async def update_recurring_template(
    template_id: str,
    template_data: RecurringTaskTemplateUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Update a recurring task template.
    """
    try:
        storage = RecurringTaskStorage()
        template = storage.update_template(template_id, template_data)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        return template
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating template {template_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/templates/{template_id}")
async def delete_recurring_template(
    template_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a recurring task template.
    """
    try:
        storage = RecurringTaskStorage()
        success = storage.delete_template(template_id)
        if not success:
            raise HTTPException(status_code=404, detail="Template not found")
        return {"success": True, "message": "Template deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting template {template_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== PREDEFINED TEMPLATES ====================

@router.get("/predefined")
async def list_predefined_templates():
    """
    List all available predefined recurring task templates.
    These are common templates for FDC educators (BAS, income checks, etc.)
    """
    return {
        "templates": [
            {
                "key": key,
                **template,
                "next_occurrence": get_next_occurrence(template["recurrence_rule"]).isoformat() 
                    if get_next_occurrence(template["recurrence_rule"]) else None
            }
            for key, template in PREDEFINED_TEMPLATES.items()
        ]
    }


@router.post("/predefined/{template_key}")
async def apply_predefined_template(
    template_key: str,
    user_id: str = Query(..., description="User ID to apply template to"),
    db: AsyncSession = Depends(get_db)
):
    """
    Apply a predefined template to a user.
    Creates a new recurring task template from the predefined configuration.
    
    Available template keys:
    - monthly_bas_reminder
    - quarterly_bas_submission
    - weekly_income_check
    - monthly_expense_review
    - eofy_preparation
    - tax_return_reminder
    """
    try:
        if template_key not in PREDEFINED_TEMPLATES:
            raise HTTPException(
                status_code=404, 
                detail=f"Predefined template '{template_key}' not found. Available: {list(PREDEFINED_TEMPLATES.keys())}"
            )
        
        template = create_predefined_template(user_id, template_key)
        if not template:
            raise HTTPException(status_code=500, detail="Failed to create template")
        
        return {
            "success": True,
            "message": f"Applied predefined template '{template_key}'",
            "template": template
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error applying predefined template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== TASK GENERATION ====================

@router.post("/trigger")
async def trigger_recurring_task_generation(
    user_id: Optional[str] = Query(None, description="Process only this user's templates"),
    force: bool = Query(False, description="Force generation even if not due"),
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger the recurring task generation job.
    
    This endpoint processes all active recurring task templates and
    generates tasks for any that are due.
    
    In production, this would be called by a daily cron job.
    """
    try:
        engine = RecurringTaskEngine(db)
        results = await engine.process_recurring_tasks(user_id=user_id, force=force)
        return results
    except Exception as e:
        logger.error(f"Error triggering recurring tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== UTILITIES ====================

@router.post("/preview")
async def preview_recurrence(
    rule: str = Query(..., description="RRULE string (e.g., FREQ=MONTHLY;BYMONTHDAY=28)"),
    count: int = Query(5, description="Number of occurrences to preview", le=20)
):
    """
    Preview the next occurrences for a recurrence rule.
    Useful for testing rules before creating templates.
    
    Example rules:
    - FREQ=MONTHLY;BYMONTHDAY=28
    - FREQ=WEEKLY;BYDAY=MO,WE,FR
    - FREQ=YEARLY;BYMONTH=6;BYMONTHDAY=30
    - FREQ=DAILY;INTERVAL=2
    """
    try:
        from services.recurring_tasks import parse_rrule
        
        rrule_obj = parse_rrule(rule)
        occurrences = []
        now = datetime.now()
        
        for i, dt in enumerate(rrule_obj):
            if i >= count:
                break
            if dt > now:
                occurrences.append(dt.strftime("%Y-%m-%d %A"))
        
        summary = generate_recurrence_summary(rule)
        
        return {
            "rule": rule,
            "summary": summary,
            "next_occurrences": occurrences
        }
    except Exception as e:
        logger.error(f"Error previewing rule: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid RRULE: {str(e)}")


@router.get("/summary")
async def get_recurrence_summary(
    rule: str = Query(..., description="RRULE string")
):
    """
    Get a human-readable summary of a recurrence rule.
    """
    try:
        summary = generate_recurrence_summary(rule)
        next_date = get_next_occurrence(rule)
        
        return {
            "rule": rule,
            "summary": summary,
            "next_occurrence": next_date.isoformat() if next_date else None
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid RRULE: {str(e)}")
