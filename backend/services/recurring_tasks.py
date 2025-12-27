"""
Recurring Task Engine for FDC Tax CRM

Handles automatic generation of recurring tasks (e.g., BAS, income prompts)
based on iCal RRULE format recurrence rules.

Since sandbox DB has restricted permissions, this implementation uses:
1. A JSON file for recurring task templates (can be migrated to DB later)
2. Generates tasks into myfdc.user_tasks table

RRULE Examples:
- FREQ=MONTHLY;BYMONTHDAY=28 -> Monthly on the 28th
- FREQ=QUARTERLY;BYMONTH=1,4,7,10;BYMONTHDAY=28 -> Quarterly BAS reminder
- FREQ=WEEKLY;BYDAY=MO -> Every Monday
- FREQ=YEARLY;BYMONTH=6;BYMONTHDAY=30 -> Yearly on June 30
"""

import json
import os
import uuid
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from pathlib import Path
import logging
from dateutil.rrule import rrulestr, rrule, DAILY, WEEKLY, MONTHLY, YEARLY
from dateutil.parser import parse as parse_date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel, Field

# Import centralized audit service
from services.audit import log_action, AuditAction, ResourceType

logger = logging.getLogger(__name__)

# Path to recurring templates storage
TEMPLATES_FILE = Path(__file__).parent.parent / "data" / "recurring_templates.json"


# ==================== MODELS ====================

class RecurringTaskTemplate(BaseModel):
    """Template for a recurring task"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str  # UUID of the user
    title: str
    description: Optional[str] = None
    priority: str = "normal"
    category: Optional[str] = None
    task_type: str = "recurring"
    recurrence_rule: str  # iCal RRULE format
    recurrence_summary: Optional[str] = None  # Human-readable summary
    is_active: bool = True
    last_generated_at: Optional[str] = None  # ISO datetime
    next_due_date: Optional[str] = None  # ISO date
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: Optional[str] = None


class RecurringTaskTemplateCreate(BaseModel):
    """Create a recurring task template"""
    user_id: str
    title: str
    description: Optional[str] = None
    priority: str = "normal"
    category: Optional[str] = None
    recurrence_rule: str
    recurrence_summary: Optional[str] = None


class RecurringTaskTemplateUpdate(BaseModel):
    """Update a recurring task template"""
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    recurrence_rule: Optional[str] = None
    recurrence_summary: Optional[str] = None
    is_active: Optional[bool] = None


class GeneratedTaskResult(BaseModel):
    """Result of generating a task from template"""
    template_id: str
    task_id: str
    user_id: str
    title: str
    due_date: str
    status: str = "generated"


# ==================== RRULE UTILITIES ====================

def parse_rrule(rule_string: str, dtstart: datetime = None) -> rrule:
    """Parse an RRULE string into a dateutil rrule object"""
    if dtstart is None:
        dtstart = datetime.now()
    
    # Handle both full RRULE and just the rule part
    if not rule_string.startswith("DTSTART"):
        rule_string = f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%S')}\nRRULE:{rule_string}"
    
    return rrulestr(rule_string)


def get_next_occurrence(rule_string: str, after: datetime = None) -> Optional[date]:
    """Get the next occurrence date for an RRULE"""
    if after is None:
        after = datetime.now()
    
    try:
        rule = parse_rrule(rule_string, after)
        next_dt = rule.after(after, inc=False)
        if next_dt:
            return next_dt.date()
    except Exception as e:
        logger.error(f"Error parsing RRULE '{rule_string}': {e}")
    
    return None


def generate_recurrence_summary(rule_string: str) -> str:
    """Generate a human-readable summary of the recurrence rule"""
    try:
        parts = rule_string.upper().split(";")
        freq = None
        interval = 1
        bymonthday = None
        byday = None
        bymonth = None
        
        for part in parts:
            if part.startswith("FREQ="):
                freq = part.split("=")[1]
            elif part.startswith("INTERVAL="):
                interval = int(part.split("=")[1])
            elif part.startswith("BYMONTHDAY="):
                bymonthday = part.split("=")[1]
            elif part.startswith("BYDAY="):
                byday = part.split("=")[1]
            elif part.startswith("BYMONTH="):
                bymonth = part.split("=")[1]
        
        day_names = {
            "MO": "Monday", "TU": "Tuesday", "WE": "Wednesday",
            "TH": "Thursday", "FR": "Friday", "SA": "Saturday", "SU": "Sunday"
        }
        
        month_names = {
            "1": "Jan", "2": "Feb", "3": "Mar", "4": "Apr",
            "5": "May", "6": "Jun", "7": "Jul", "8": "Aug",
            "9": "Sep", "10": "Oct", "11": "Nov", "12": "Dec"
        }
        
        if freq == "DAILY":
            if interval == 1:
                return "Daily"
            return f"Every {interval} days"
        
        elif freq == "WEEKLY":
            if byday:
                days = [day_names.get(d, d) for d in byday.split(",")]
                return f"Weekly on {', '.join(days)}"
            if interval == 1:
                return "Weekly"
            return f"Every {interval} weeks"
        
        elif freq == "MONTHLY":
            if bymonthday:
                day = bymonthday
                suffix = "th" if 11 <= int(day) <= 13 else {"1": "st", "2": "nd", "3": "rd"}.get(day[-1], "th")
                return f"Monthly on the {day}{suffix}"
            if interval == 1:
                return "Monthly"
            return f"Every {interval} months"
        
        elif freq == "YEARLY":
            if bymonth and bymonthday:
                months = [month_names.get(m, m) for m in bymonth.split(",")]
                return f"Yearly on {months[0]} {bymonthday}"
            return "Yearly"
        
        # Quarterly pattern
        if bymonth and len(bymonth.split(",")) == 4:
            if bymonthday:
                return f"Quarterly on the {bymonthday}th"
            return "Quarterly"
        
        return rule_string  # Fallback to raw rule
        
    except Exception as e:
        logger.warning(f"Could not generate summary for rule: {e}")
        return rule_string


# ==================== TEMPLATE STORAGE ====================

class RecurringTaskStorage:
    """File-based storage for recurring task templates"""
    
    def __init__(self, file_path: Path = TEMPLATES_FILE):
        self.file_path = file_path
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        """Ensure the data directory and file exist"""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._save_templates([])
    
    def _load_templates(self) -> List[Dict]:
        """Load templates from file"""
        try:
            with open(self.file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading templates: {e}")
            return []
    
    def _save_templates(self, templates: List[Dict]):
        """Save templates to file"""
        with open(self.file_path, 'w') as f:
            json.dump(templates, f, indent=2, default=str)
    
    def list_templates(self, user_id: Optional[str] = None, active_only: bool = False) -> List[RecurringTaskTemplate]:
        """List all templates, optionally filtered"""
        templates = self._load_templates()
        
        if user_id:
            templates = [t for t in templates if t.get('user_id') == user_id]
        
        if active_only:
            templates = [t for t in templates if t.get('is_active', True)]
        
        return [RecurringTaskTemplate(**t) for t in templates]
    
    def get_template(self, template_id: str) -> Optional[RecurringTaskTemplate]:
        """Get a specific template by ID"""
        templates = self._load_templates()
        for t in templates:
            if t.get('id') == template_id:
                return RecurringTaskTemplate(**t)
        return None
    
    def create_template(self, data: RecurringTaskTemplateCreate, created_by: Optional[str] = None) -> RecurringTaskTemplate:
        """Create a new recurring task template"""
        templates = self._load_templates()
        
        # Generate summary if not provided
        summary = data.recurrence_summary or generate_recurrence_summary(data.recurrence_rule)
        
        # Calculate next due date
        next_due = get_next_occurrence(data.recurrence_rule)
        
        template = RecurringTaskTemplate(
            user_id=data.user_id,
            title=data.title,
            description=data.description,
            priority=data.priority,
            category=data.category,
            recurrence_rule=data.recurrence_rule,
            recurrence_summary=summary,
            next_due_date=next_due.isoformat() if next_due else None
        )
        
        templates.append(template.model_dump())
        self._save_templates(templates)
        
        # Log template creation
        log_action(
            action=AuditAction.RECURRING_TEMPLATE_CREATE,
            resource_type=ResourceType.RECURRING_TEMPLATE,
            resource_id=template.id,
            user_id=created_by or data.user_id,
            details={
                "title": data.title,
                "recurrence_rule": data.recurrence_rule,
                "recurrence_summary": summary,
                "for_user": data.user_id
            }
        )
        
        return template
    
    def update_template(self, template_id: str, data: RecurringTaskTemplateUpdate, updated_by: Optional[str] = None) -> Optional[RecurringTaskTemplate]:
        """Update a recurring task template"""
        templates = self._load_templates()
        
        for i, t in enumerate(templates):
            if t.get('id') == template_id:
                update_data = data.model_dump(exclude_none=True)
                
                # Update summary if rule changed
                if 'recurrence_rule' in update_data and 'recurrence_summary' not in update_data:
                    update_data['recurrence_summary'] = generate_recurrence_summary(update_data['recurrence_rule'])
                
                # Recalculate next due date if rule changed
                if 'recurrence_rule' in update_data:
                    next_due = get_next_occurrence(update_data['recurrence_rule'])
                    update_data['next_due_date'] = next_due.isoformat() if next_due else None
                
                update_data['updated_at'] = datetime.now().isoformat()
                
                templates[i].update(update_data)
                self._save_templates(templates)
                
                # Log template update
                log_action(
                    action=AuditAction.RECURRING_TEMPLATE_UPDATE,
                    resource_type=ResourceType.RECURRING_TEMPLATE,
                    resource_id=template_id,
                    user_id=updated_by,
                    details={
                        "title": templates[i].get('title'),
                        "changes": update_data
                    }
                )
                
                return RecurringTaskTemplate(**templates[i])
        
        return None
    
    def delete_template(self, template_id: str, deleted_by: Optional[str] = None) -> bool:
        """Delete a recurring task template"""
        templates = self._load_templates()
        original_len = len(templates)
        
        # Find template info for audit before deletion
        template_info = next((t for t in templates if t.get('id') == template_id), None)
        
        templates = [t for t in templates if t.get('id') != template_id]
        
        if len(templates) < original_len:
            self._save_templates(templates)
            
            # Log template deletion
            if template_info:
                log_action(
                    action=AuditAction.RECURRING_TEMPLATE_DELETE,
                    resource_type=ResourceType.RECURRING_TEMPLATE,
                    resource_id=template_id,
                    user_id=deleted_by,
                    details={
                        "title": template_info.get('title'),
                        "for_user": template_info.get('user_id')
                    }
                )
            
            return True
        
        return False
    
    def update_last_generated(self, template_id: str, generated_at: datetime, next_due: date):
        """Update the last_generated_at and next_due_date for a template"""
        templates = self._load_templates()
        
        for i, t in enumerate(templates):
            if t.get('id') == template_id:
                templates[i]['last_generated_at'] = generated_at.isoformat()
                templates[i]['next_due_date'] = next_due.isoformat() if next_due else None
                templates[i]['updated_at'] = datetime.now().isoformat()
                self._save_templates(templates)
                break


# ==================== RECURRING TASK ENGINE ====================

class RecurringTaskEngine:
    """
    Engine for generating recurring tasks based on templates.
    
    Usage:
        engine = RecurringTaskEngine(db_session)
        results = await engine.process_recurring_tasks()
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.storage = RecurringTaskStorage()
    
    async def process_recurring_tasks(
        self,
        user_id: Optional[str] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Process all recurring task templates and generate tasks where due.
        
        Args:
            user_id: Optional user ID to process only their templates
            force: If True, generate tasks even if not yet due
        
        Returns:
            Summary of processed templates and generated tasks
        """
        logger.info(f"Processing recurring tasks (user_id={user_id}, force={force})")
        
        templates = self.storage.list_templates(user_id=user_id, active_only=True)
        
        results = {
            "processed_at": datetime.now().isoformat(),
            "templates_checked": len(templates),
            "tasks_generated": 0,
            "errors": 0,
            "generated_tasks": [],
            "skipped": []
        }
        
        today = date.today()
        
        for template in templates:
            try:
                # Check if task should be generated
                should_generate = force
                
                if not force:
                    if template.next_due_date:
                        next_due = date.fromisoformat(template.next_due_date)
                        should_generate = next_due <= today
                    else:
                        # No next_due_date calculated, generate one
                        next_due = get_next_occurrence(template.recurrence_rule)
                        if next_due and next_due <= today:
                            should_generate = True
                
                if should_generate:
                    # Generate the task
                    task_result = await self._generate_task_from_template(template)
                    
                    if task_result:
                        results["tasks_generated"] += 1
                        results["generated_tasks"].append(task_result.model_dump())
                        
                        # Calculate and update next due date
                        next_due = get_next_occurrence(
                            template.recurrence_rule,
                            datetime.now()
                        )
                        self.storage.update_last_generated(
                            template.id,
                            datetime.now(),
                            next_due
                        )
                else:
                    results["skipped"].append({
                        "template_id": template.id,
                        "title": template.title,
                        "next_due_date": template.next_due_date,
                        "reason": "Not yet due"
                    })
                    
            except Exception as e:
                logger.error(f"Error processing template {template.id}: {e}")
                results["errors"] += 1
        
        logger.info(f"Recurring task processing complete: {results['tasks_generated']} tasks generated")
        return results
    
    async def _generate_task_from_template(self, template: RecurringTaskTemplate) -> Optional[GeneratedTaskResult]:
        """
        Generate a single task from a template.
        """
        try:
            # Calculate due date based on recurrence rule
            due_date = get_next_occurrence(template.recurrence_rule)
            if not due_date:
                due_date = date.today() + timedelta(days=7)  # Fallback
            
            # Create task in myfdc.user_tasks
            task_id = str(uuid.uuid4())
            
            query = text("""
                INSERT INTO myfdc.user_tasks 
                (id, user_id, task_name, description, due_date, status, priority, category, task_type, created_at)
                VALUES (CAST(:id AS uuid), CAST(:user_id AS uuid), :task_name, :description, :due_date, :status, :priority, :category, :task_type, :created_at)
                RETURNING id, user_id, task_name, due_date, status
            """)
            
            # Add recurrence info to description
            description = template.description or ""
            description += f"\n\n[Auto-generated from recurring template: {template.recurrence_summary}]"
            
            params = {
                "id": task_id,
                "user_id": template.user_id,
                "task_name": template.title,
                "description": description.strip(),
                "due_date": due_date,
                "status": "pending",
                "priority": template.priority,
                "category": template.category or "recurring",
                "task_type": "recurring",
                "created_at": datetime.now()
            }
            
            result = await self.db.execute(query, params)
            await self.db.commit()
            row = result.fetchone()
            
            if row:
                logger.info(f"Generated task {task_id} from template {template.id}")
                return GeneratedTaskResult(
                    template_id=template.id,
                    task_id=str(row.id),
                    user_id=str(row.user_id),
                    title=row.task_name,
                    due_date=str(row.due_date)
                )
            
        except Exception as e:
            logger.error(f"Failed to generate task from template {template.id}: {e}")
            raise
        
        return None
    
    async def preview_next_occurrences(
        self,
        rule_string: str,
        count: int = 5,
        after: datetime = None
    ) -> List[str]:
        """
        Preview the next N occurrences for a recurrence rule.
        Useful for UI to show upcoming dates.
        """
        if after is None:
            after = datetime.now()
        
        try:
            rule = parse_rrule(rule_string, after)
            occurrences = []
            
            for i, dt in enumerate(rule):
                if i >= count:
                    break
                if dt > after:
                    occurrences.append(dt.date().isoformat())
            
            return occurrences
        except Exception as e:
            logger.error(f"Error previewing occurrences: {e}")
            return []


# ==================== PREDEFINED TEMPLATES ====================

# Common recurring task templates for FDC educators
PREDEFINED_TEMPLATES = {
    "monthly_bas_reminder": {
        "title": "Monthly BAS Reminder",
        "description": "Review and prepare your monthly BAS statement. Check income records and expense claims.",
        "priority": "high",
        "category": "compliance",
        "recurrence_rule": "FREQ=MONTHLY;BYMONTHDAY=21",
        "recurrence_summary": "Monthly on the 21st"
    },
    "quarterly_bas_submission": {
        "title": "Quarterly BAS Due",
        "description": "Your quarterly BAS is due soon. Ensure all income and expenses are recorded.",
        "priority": "high",
        "category": "compliance",
        "recurrence_rule": "FREQ=MONTHLY;BYMONTH=1,4,7,10;BYMONTHDAY=28",
        "recurrence_summary": "Quarterly on the 28th (Jan, Apr, Jul, Oct)"
    },
    "weekly_income_check": {
        "title": "Weekly Income Check",
        "description": "Review this week's income entries. Reconcile parent payments and CCS deposits.",
        "priority": "normal",
        "category": "income",
        "recurrence_rule": "FREQ=WEEKLY;BYDAY=FR",
        "recurrence_summary": "Weekly on Friday"
    },
    "monthly_expense_review": {
        "title": "Monthly Expense Review",
        "description": "Review and categorize all business expenses from the past month.",
        "priority": "normal",
        "category": "expenses",
        "recurrence_rule": "FREQ=MONTHLY;BYMONTHDAY=-1",
        "recurrence_summary": "Monthly on the last day"
    },
    "eofy_preparation": {
        "title": "End of Financial Year Preparation",
        "description": "Start preparing for EOFY. Review all income, expenses, and deductions.",
        "priority": "high",
        "category": "compliance",
        "recurrence_rule": "FREQ=YEARLY;BYMONTH=6;BYMONTHDAY=1",
        "recurrence_summary": "Yearly on June 1st"
    },
    "tax_return_reminder": {
        "title": "Tax Return Reminder",
        "description": "Tax returns are due soon. Ensure all documentation is ready.",
        "priority": "high",
        "category": "compliance",
        "recurrence_rule": "FREQ=YEARLY;BYMONTH=10;BYMONTHDAY=1",
        "recurrence_summary": "Yearly on October 1st"
    }
}


def create_predefined_template(user_id: str, template_key: str) -> Optional[RecurringTaskTemplate]:
    """Create a recurring task from a predefined template"""
    if template_key not in PREDEFINED_TEMPLATES:
        return None
    
    template_data = PREDEFINED_TEMPLATES[template_key].copy()
    
    storage = RecurringTaskStorage()
    return storage.create_template(RecurringTaskTemplateCreate(
        user_id=user_id,
        **template_data
    ))
