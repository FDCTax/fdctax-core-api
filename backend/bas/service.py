"""
BAS Backend - Service Layer

Provides business logic for:
- Saving BAS snapshots
- Retrieving BAS history (with grouping)
- Change log persistence
- PDF generation (data endpoint)
- Multi-step sign-off workflow (prepare → review → approve → lodge)
"""

import uuid
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import List, Dict, Any, Optional
import logging
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, and_, or_, desc, func

from .models import (
    BASStatementDB, BASChangeLogDB, BASWorkflowStepDB,
    BASStatus, BASActionType, BASEntityType,
    WorkflowStepType, WorkflowStepStatus
)

logger = logging.getLogger(__name__)


# Workflow step configuration
WORKFLOW_STEPS = [
    {"type": WorkflowStepType.PREPARE.value, "order": 1, "role": "staff", "name": "Preparation"},
    {"type": WorkflowStepType.REVIEW.value, "order": 2, "role": "tax_agent", "name": "Review"},
    {"type": WorkflowStepType.APPROVE.value, "order": 3, "role": "client", "name": "Approval"},
    {"type": WorkflowStepType.LODGE.value, "order": 4, "role": "tax_agent", "name": "Lodgement"},
]


# ==================== BAS STATEMENT SERVICE ====================

class BASStatementService:
    """Service for managing BAS statements"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def save_bas(
        self,
        client_id: str,
        period_from: date,
        period_to: date,
        summary: Dict[str, Any],
        user_id: str,
        user_email: Optional[str] = None,
        job_id: Optional[str] = None,
        notes: Optional[str] = None,
        status: str = "draft"
    ) -> Dict[str, Any]:
        """
        Save a BAS snapshot.
        
        If a BAS already exists for the same client/period, increment version.
        """
        # Check for existing BAS for this period
        existing = await self._get_latest_for_period(client_id, period_from, period_to)
        
        if existing:
            version = existing.version + 1
            logger.info(f"Creating new version {version} for client {client_id}")
        else:
            version = 1
        
        # Create BAS statement
        bas = BASStatementDB(
            client_id=client_id,
            job_id=job_id,
            period_from=period_from,
            period_to=period_to,
            
            # GST fields
            g1_total_income=Decimal(str(summary.get("g1_total_income", 0))),
            gst_on_income_1a=Decimal(str(summary.get("gst_on_income_1a", 0))),
            gst_on_expenses_1b=Decimal(str(summary.get("gst_on_expenses_1b", 0))),
            net_gst=Decimal(str(summary.get("net_gst", 0))),
            g2_export_sales=Decimal(str(summary.get("g2_export_sales", 0))),
            g3_gst_free_sales=Decimal(str(summary.get("g3_gst_free_sales", 0))),
            g10_capital_purchases=Decimal(str(summary.get("g10_capital_purchases", 0))),
            g11_non_capital_purchases=Decimal(str(summary.get("g11_non_capital_purchases", 0))),
            
            # PAYG
            payg_instalment=Decimal(str(summary.get("payg_instalment", 0))),
            
            # Totals
            total_payable=Decimal(str(summary.get("total_payable", 0))),
            
            # Notes
            notes=notes,
            
            # Sign-off (if completing)
            completed_by=user_id if status == "completed" else None,
            completed_by_email=user_email if status == "completed" else None,
            completed_at=datetime.now(timezone.utc) if status == "completed" else None,
            
            # Version and status
            version=version,
            status=status,
        )
        
        self.db.add(bas)
        await self.db.commit()
        await self.db.refresh(bas)
        
        # Log the action
        await self._log_change(
            bas_statement_id=bas.id,
            client_id=client_id,
            job_id=job_id,
            user_id=user_id,
            user_email=user_email,
            action_type=BASActionType.CREATE.value if version == 1 else BASActionType.UPDATE.value,
            entity_type=BASEntityType.BAS_SUMMARY.value,
            entity_id=str(bas.id),
            old_value=existing.to_dict() if existing else None,
            new_value=bas.to_dict(),
            reason=f"BAS {'created' if version == 1 else 'updated'} - version {version}"
        )
        
        logger.info(f"BAS saved: {bas.id} (version {version})")
        
        return bas.to_dict()
    
    async def get_bas(self, bas_id: str) -> Optional[Dict[str, Any]]:
        """Get a single BAS statement by ID"""
        result = await self.db.execute(
            select(BASStatementDB).where(BASStatementDB.id == uuid.UUID(bas_id))
        )
        bas = result.scalar_one_or_none()
        
        if not bas:
            return None
        
        # Get change log for this BAS
        log_result = await self.db.execute(
            select(BASChangeLogDB)
            .where(BASChangeLogDB.bas_statement_id == uuid.UUID(bas_id))
            .order_by(desc(BASChangeLogDB.timestamp))
        )
        change_logs = [log.to_dict() for log in log_result.scalars().all()]
        
        bas_dict = bas.to_dict()
        bas_dict["change_log"] = change_logs
        
        return bas_dict
    
    async def get_history(
        self,
        client_id: str,
        job_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get BAS history for a client"""
        query = select(BASStatementDB).where(BASStatementDB.client_id == client_id)
        
        if job_id:
            query = query.where(BASStatementDB.job_id == job_id)
        
        query = query.order_by(desc(BASStatementDB.period_to), desc(BASStatementDB.version))
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        statements = result.scalars().all()
        
        return [s.to_dict() for s in statements]
    
    async def sign_off(
        self,
        bas_id: str,
        user_id: str,
        user_email: Optional[str] = None,
        review_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Sign off on a BAS statement"""
        result = await self.db.execute(
            select(BASStatementDB).where(BASStatementDB.id == uuid.UUID(bas_id))
        )
        bas = result.scalar_one_or_none()
        
        if not bas:
            raise ValueError(f"BAS {bas_id} not found")
        
        old_value = bas.to_dict()
        
        # Update sign-off fields
        bas.completed_by = user_id
        bas.completed_by_email = user_email
        bas.completed_at = datetime.now(timezone.utc)
        bas.status = BASStatus.COMPLETED.value
        if review_notes:
            bas.review_notes = review_notes
        
        await self.db.commit()
        await self.db.refresh(bas)
        
        # Log the sign-off
        await self._log_change(
            bas_statement_id=bas.id,
            client_id=bas.client_id,
            job_id=bas.job_id,
            user_id=user_id,
            user_email=user_email,
            action_type=BASActionType.SIGN_OFF.value,
            entity_type=BASEntityType.BAS_SUMMARY.value,
            entity_id=str(bas.id),
            old_value=old_value,
            new_value=bas.to_dict(),
            reason=review_notes or "BAS signed off"
        )
        
        return bas.to_dict()
    
    async def generate_pdf_data(self, bas_id: str) -> Dict[str, Any]:
        """
        Generate PDF data for a BAS statement.
        Returns structured JSON for frontend PDF generation.
        """
        result = await self.db.execute(
            select(BASStatementDB).where(BASStatementDB.id == uuid.UUID(bas_id))
        )
        bas = result.scalar_one_or_none()
        
        if not bas:
            raise ValueError(f"BAS {bas_id} not found")
        
        # Structure for PDF generation
        pdf_data = {
            "document_type": "BAS",
            "document_title": "Business Activity Statement",
            "period": {
                "from": bas.period_from.isoformat() if bas.period_from else None,
                "to": bas.period_to.isoformat() if bas.period_to else None,
                "label": f"{bas.period_from.strftime('%d %b %Y')} to {bas.period_to.strftime('%d %b %Y')}" if bas.period_from and bas.period_to else None,
            },
            "client_id": bas.client_id,
            "job_id": bas.job_id,
            "version": bas.version,
            "status": bas.status,
            
            # GST Section
            "gst": {
                "g1_total_sales": float(bas.g1_total_income or 0),
                "g2_export_sales": float(bas.g2_export_sales or 0),
                "g3_gst_free_sales": float(bas.g3_gst_free_sales or 0),
                "1a_gst_on_sales": float(bas.gst_on_income_1a or 0),
                "1b_gst_on_purchases": float(bas.gst_on_expenses_1b or 0),
                "g10_capital_purchases": float(bas.g10_capital_purchases or 0),
                "g11_non_capital_purchases": float(bas.g11_non_capital_purchases or 0),
                "net_gst": float(bas.net_gst or 0),
            },
            
            # PAYG Section
            "payg": {
                "instalment": float(bas.payg_instalment or 0),
            },
            
            # Summary
            "summary": {
                "total_payable": float(bas.total_payable or 0),
                "notes": bas.notes,
            },
            
            # Sign-off
            "sign_off": {
                "completed_by": bas.completed_by,
                "completed_by_email": bas.completed_by_email,
                "completed_at": bas.completed_at.isoformat() if bas.completed_at else None,
                "review_notes": bas.review_notes,
            },
            
            # Metadata
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "bas_id": str(bas.id),
                "created_at": bas.created_at.isoformat() if bas.created_at else None,
            }
        }
        
        return pdf_data
    
    async def _get_latest_for_period(
        self,
        client_id: str,
        period_from: date,
        period_to: date
    ) -> Optional[BASStatementDB]:
        """Get the latest BAS for a specific period"""
        result = await self.db.execute(
            select(BASStatementDB)
            .where(and_(
                BASStatementDB.client_id == client_id,
                BASStatementDB.period_from == period_from,
                BASStatementDB.period_to == period_to
            ))
            .order_by(desc(BASStatementDB.version))
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    async def _log_change(
        self,
        client_id: str,
        user_id: str,
        action_type: str,
        entity_type: str,
        bas_statement_id: Optional[uuid.UUID] = None,
        job_id: Optional[str] = None,
        user_email: Optional[str] = None,
        entity_id: Optional[str] = None,
        old_value: Optional[Dict] = None,
        new_value: Optional[Dict] = None,
        reason: Optional[str] = None
    ):
        """Internal helper to log changes"""
        log = BASChangeLogDB(
            bas_statement_id=bas_statement_id,
            client_id=client_id,
            job_id=job_id,
            user_id=user_id,
            user_email=user_email,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            reason=reason
        )
        self.db.add(log)
        await self.db.commit()


# ==================== BAS CHANGE LOG SERVICE ====================

class BASChangeLogService:
    """Service for managing BAS change logs"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def log_change(
        self,
        client_id: str,
        user_id: str,
        action_type: str,
        entity_type: str,
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
        bas_statement_id: Optional[str] = None,
        job_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        old_value: Optional[Dict] = None,
        new_value: Optional[Dict] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Log a change to the BAS change log.
        """
        log = BASChangeLogDB(
            bas_statement_id=uuid.UUID(bas_statement_id) if bas_statement_id else None,
            client_id=client_id,
            job_id=job_id,
            user_id=user_id,
            user_email=user_email,
            user_role=user_role,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            reason=reason
        )
        
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        
        logger.info(f"Change logged: {action_type} on {entity_type} by {user_id}")
        
        return log.to_dict()
    
    async def get_change_log(
        self,
        client_id: Optional[str] = None,
        job_id: Optional[str] = None,
        bas_statement_id: Optional[str] = None,
        action_type: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Get change log entries with filters.
        """
        query = select(BASChangeLogDB)
        
        if client_id:
            query = query.where(BASChangeLogDB.client_id == client_id)
        if job_id:
            query = query.where(BASChangeLogDB.job_id == job_id)
        if bas_statement_id:
            query = query.where(BASChangeLogDB.bas_statement_id == uuid.UUID(bas_statement_id))
        if action_type:
            query = query.where(BASChangeLogDB.action_type == action_type)
        if entity_type:
            query = query.where(BASChangeLogDB.entity_type == entity_type)
        
        query = query.order_by(desc(BASChangeLogDB.timestamp))
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        logs = result.scalars().all()
        
        return [log.to_dict() for log in logs]


# ==================== BAS WORKFLOW SERVICE ====================

class BASWorkflowService:
    """Service for managing BAS multi-step sign-off workflow"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def initialize_workflow(
        self,
        bas_statement_id: uuid.UUID,
        client_id: str,
        skip_client_approval: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Initialize workflow steps for a BAS statement.
        
        Creates all workflow steps in pending status.
        """
        steps = []
        
        for step_config in WORKFLOW_STEPS:
            # Skip client approval if not required
            if skip_client_approval and step_config["type"] == WorkflowStepType.APPROVE.value:
                status = WorkflowStepStatus.SKIPPED.value
            else:
                status = WorkflowStepStatus.PENDING.value
            
            step = BASWorkflowStepDB(
                bas_statement_id=bas_statement_id,
                client_id=client_id,
                step_type=step_config["type"],
                step_order=step_config["order"],
                status=status
            )
            self.db.add(step)
            steps.append(step)
        
        # Set first step to in_progress
        if steps:
            steps[0].status = WorkflowStepStatus.IN_PROGRESS.value
        
        await self.db.commit()
        
        for step in steps:
            await self.db.refresh(step)
        
        logger.info(f"Initialized workflow for BAS {bas_statement_id}")
        
        return [s.to_dict() for s in steps]
    
    async def get_workflow_status(
        self,
        bas_statement_id: uuid.UUID
    ) -> Dict[str, Any]:
        """
        Get current workflow status for a BAS statement.
        """
        result = await self.db.execute(
            select(BASWorkflowStepDB)
            .where(BASWorkflowStepDB.bas_statement_id == bas_statement_id)
            .order_by(BASWorkflowStepDB.step_order)
        )
        steps = result.scalars().all()
        
        if not steps:
            return {
                "has_workflow": False,
                "steps": [],
                "current_step": None,
                "progress_percent": 0,
                "is_complete": False
            }
        
        # Find current step
        current_step = None
        for step in steps:
            if step.status == WorkflowStepStatus.IN_PROGRESS.value:
                current_step = step
                break
        
        # Calculate progress
        completed_count = sum(1 for s in steps if s.status in [
            WorkflowStepStatus.COMPLETED.value,
            WorkflowStepStatus.SKIPPED.value
        ])
        total_count = len(steps)
        progress = int((completed_count / total_count) * 100) if total_count > 0 else 0
        
        # Check if complete
        is_complete = all(
            s.status in [WorkflowStepStatus.COMPLETED.value, WorkflowStepStatus.SKIPPED.value]
            for s in steps
        )
        
        return {
            "has_workflow": True,
            "steps": [s.to_dict() for s in steps],
            "current_step": current_step.to_dict() if current_step else None,
            "progress_percent": progress,
            "is_complete": is_complete,
            "completed_count": completed_count,
            "total_count": total_count
        }
    
    async def complete_step(
        self,
        bas_statement_id: uuid.UUID,
        step_type: str,
        user_id: str,
        user_email: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Complete a workflow step and advance to next.
        """
        # Get the step
        result = await self.db.execute(
            select(BASWorkflowStepDB)
            .where(and_(
                BASWorkflowStepDB.bas_statement_id == bas_statement_id,
                BASWorkflowStepDB.step_type == step_type
            ))
        )
        step = result.scalar_one_or_none()
        
        if not step:
            raise ValueError(f"Workflow step '{step_type}' not found for BAS {bas_statement_id}")
        
        if step.status == WorkflowStepStatus.COMPLETED.value:
            raise ValueError(f"Step '{step_type}' is already completed")
        
        if step.status not in [WorkflowStepStatus.IN_PROGRESS.value, WorkflowStepStatus.PENDING.value]:
            raise ValueError(f"Step '{step_type}' cannot be completed (status: {step.status})")
        
        # Complete the step
        step.status = WorkflowStepStatus.COMPLETED.value
        step.completed_by = user_id
        step.completed_by_email = user_email
        step.completed_at = datetime.now(timezone.utc)
        if notes:
            step.notes = notes
        
        # Find and activate next step
        next_result = await self.db.execute(
            select(BASWorkflowStepDB)
            .where(and_(
                BASWorkflowStepDB.bas_statement_id == bas_statement_id,
                BASWorkflowStepDB.step_order > step.step_order,
                BASWorkflowStepDB.status == WorkflowStepStatus.PENDING.value
            ))
            .order_by(BASWorkflowStepDB.step_order)
            .limit(1)
        )
        next_step = next_result.scalar_one_or_none()
        
        if next_step:
            next_step.status = WorkflowStepStatus.IN_PROGRESS.value
        
        await self.db.commit()
        await self.db.refresh(step)
        
        # Get updated workflow status
        workflow_status = await self.get_workflow_status(bas_statement_id)
        
        logger.info(f"Completed workflow step '{step_type}' for BAS {bas_statement_id}")
        
        return {
            "success": True,
            "completed_step": step.to_dict(),
            "next_step": next_step.to_dict() if next_step else None,
            "workflow_status": workflow_status
        }
    
    async def reject_step(
        self,
        bas_statement_id: uuid.UUID,
        step_type: str,
        user_id: str,
        user_email: Optional[str] = None,
        rejection_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Reject a workflow step, returning to previous step.
        """
        # Get the step
        result = await self.db.execute(
            select(BASWorkflowStepDB)
            .where(and_(
                BASWorkflowStepDB.bas_statement_id == bas_statement_id,
                BASWorkflowStepDB.step_type == step_type
            ))
        )
        step = result.scalar_one_or_none()
        
        if not step:
            raise ValueError(f"Workflow step '{step_type}' not found")
        
        # Reject the step
        step.status = WorkflowStepStatus.REJECTED.value
        step.rejected_by = user_id
        step.rejected_by_email = user_email
        step.rejected_at = datetime.now(timezone.utc)
        step.rejection_reason = rejection_reason
        
        # Find and reactivate previous step
        prev_result = await self.db.execute(
            select(BASWorkflowStepDB)
            .where(and_(
                BASWorkflowStepDB.bas_statement_id == bas_statement_id,
                BASWorkflowStepDB.step_order < step.step_order
            ))
            .order_by(desc(BASWorkflowStepDB.step_order))
            .limit(1)
        )
        prev_step = prev_result.scalar_one_or_none()
        
        if prev_step:
            prev_step.status = WorkflowStepStatus.IN_PROGRESS.value
            prev_step.completed_at = None
            prev_step.completed_by = None
            prev_step.completed_by_email = None
        
        await self.db.commit()
        await self.db.refresh(step)
        
        logger.info(f"Rejected workflow step '{step_type}' for BAS {bas_statement_id}")
        
        return {
            "success": True,
            "rejected_step": step.to_dict(),
            "returned_to_step": prev_step.to_dict() if prev_step else None
        }
    
    async def assign_step(
        self,
        bas_statement_id: uuid.UUID,
        step_type: str,
        assigned_to: str,
        assigned_to_email: Optional[str] = None,
        assigned_to_role: Optional[str] = None,
        due_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Assign a workflow step to a user.
        """
        result = await self.db.execute(
            select(BASWorkflowStepDB)
            .where(and_(
                BASWorkflowStepDB.bas_statement_id == bas_statement_id,
                BASWorkflowStepDB.step_type == step_type
            ))
        )
        step = result.scalar_one_or_none()
        
        if not step:
            raise ValueError(f"Workflow step '{step_type}' not found")
        
        step.assigned_to = assigned_to
        step.assigned_to_email = assigned_to_email
        step.assigned_to_role = assigned_to_role
        step.assigned_at = datetime.now(timezone.utc)
        if due_date:
            step.due_date = due_date
        
        await self.db.commit()
        await self.db.refresh(step)
        
        logger.info(f"Assigned step '{step_type}' to {assigned_to_email} for BAS {bas_statement_id}")
        
        return step.to_dict()
    
    async def get_pending_steps_for_user(
        self,
        user_id: str,
        user_role: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all pending workflow steps assigned to or appropriate for a user.
        """
        query = select(BASWorkflowStepDB).where(
            BASWorkflowStepDB.status == WorkflowStepStatus.IN_PROGRESS.value
        )
        
        # Filter by assignment or role
        if user_role:
            # Get steps matching user's role
            role_step_types = [
                s["type"] for s in WORKFLOW_STEPS if s["role"] == user_role
            ]
            query = query.where(
                or_(
                    BASWorkflowStepDB.assigned_to == user_id,
                    and_(
                        BASWorkflowStepDB.assigned_to.is_(None),
                        BASWorkflowStepDB.step_type.in_(role_step_types)
                    )
                )
            )
        else:
            query = query.where(BASWorkflowStepDB.assigned_to == user_id)
        
        query = query.order_by(BASWorkflowStepDB.due_date.asc().nullslast())
        
        result = await self.db.execute(query)
        steps = result.scalars().all()
        
        return [s.to_dict() for s in steps]


# ==================== BAS HISTORY SERVICE (ENHANCED) ====================

class BASHistoryService:
    """Service for enhanced BAS history with grouping and summaries"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_grouped_history(
        self,
        client_id: str,
        group_by: str = "quarter",  # quarter, month, year
        year: Optional[int] = None,
        include_drafts: bool = False
    ) -> Dict[str, Any]:
        """
        Get BAS history grouped by period with summaries.
        """
        query = select(BASStatementDB).where(BASStatementDB.client_id == client_id)
        
        if not include_drafts:
            query = query.where(BASStatementDB.status != BASStatus.DRAFT.value)
        
        if year:
            query = query.where(
                func.extract('year', BASStatementDB.period_to) == year
            )
        
        query = query.order_by(desc(BASStatementDB.period_to), desc(BASStatementDB.version))
        
        result = await self.db.execute(query)
        statements = result.scalars().all()
        
        # Group by period
        grouped = {}
        for stmt in statements:
            if group_by == "quarter":
                quarter = (stmt.period_to.month - 1) // 3 + 1
                key = f"{stmt.period_to.year}-Q{quarter}"
            elif group_by == "month":
                key = f"{stmt.period_to.year}-{stmt.period_to.month:02d}"
            else:  # year
                key = str(stmt.period_to.year)
            
            if key not in grouped:
                grouped[key] = {
                    "period_key": key,
                    "statements": [],
                    "summary": {
                        "total_gst_payable": 0,
                        "total_payg": 0,
                        "total_payable": 0,
                        "statement_count": 0,
                        "latest_version": 0
                    }
                }
            
            grouped[key]["statements"].append(stmt.to_dict())
            
            # Only count latest version in summary
            if stmt.version > grouped[key]["summary"]["latest_version"]:
                grouped[key]["summary"]["total_gst_payable"] = float(stmt.net_gst or 0)
                grouped[key]["summary"]["total_payg"] = float(stmt.payg_instalment or 0)
                grouped[key]["summary"]["total_payable"] = float(stmt.total_payable or 0)
                grouped[key]["summary"]["latest_version"] = stmt.version
            
            grouped[key]["summary"]["statement_count"] += 1
        
        # Convert to list sorted by period
        periods = sorted(grouped.values(), key=lambda x: x["period_key"], reverse=True)
        
        # Calculate overall summary
        overall_summary = {
            "total_periods": len(periods),
            "total_statements": len(statements),
            "total_gst_payable": sum(p["summary"]["total_gst_payable"] for p in periods),
            "total_payg": sum(p["summary"]["total_payg"] for p in periods),
            "total_payable": sum(p["summary"]["total_payable"] for p in periods)
        }
        
        return {
            "client_id": client_id,
            "group_by": group_by,
            "year_filter": year,
            "periods": periods,
            "summary": overall_summary
        }
    
    async def get_period_comparison(
        self,
        client_id: str,
        period_from: date,
        period_to: date,
        compare_with: str = "previous"  # previous, same_last_year
    ) -> Dict[str, Any]:
        """
        Compare BAS for a period with another period.
        """
        # Get current period BAS
        current_result = await self.db.execute(
            select(BASStatementDB)
            .where(and_(
                BASStatementDB.client_id == client_id,
                BASStatementDB.period_from == period_from,
                BASStatementDB.period_to == period_to
            ))
            .order_by(desc(BASStatementDB.version))
            .limit(1)
        )
        current = current_result.scalar_one_or_none()
        
        if not current:
            return {"error": "No BAS found for the specified period"}
        
        # Determine comparison period
        if compare_with == "previous":
            # Get previous quarter
            if period_from.month > 3:
                comp_from = date(period_from.year, period_from.month - 3, period_from.day)
                comp_to = date(period_to.year, period_to.month - 3, period_to.day)
            else:
                comp_from = date(period_from.year - 1, period_from.month + 9, period_from.day)
                comp_to = date(period_to.year - 1, period_to.month + 9, period_to.day)
        else:  # same_last_year
            comp_from = date(period_from.year - 1, period_from.month, period_from.day)
            comp_to = date(period_to.year - 1, period_to.month, period_to.day)
        
        # Get comparison period BAS
        comp_result = await self.db.execute(
            select(BASStatementDB)
            .where(and_(
                BASStatementDB.client_id == client_id,
                BASStatementDB.period_from == comp_from,
                BASStatementDB.period_to == comp_to
            ))
            .order_by(desc(BASStatementDB.version))
            .limit(1)
        )
        comparison = comp_result.scalar_one_or_none()
        
        # Calculate variances
        def calc_variance(current_val, comp_val):
            if comp_val and comp_val != 0:
                pct = ((current_val - comp_val) / abs(comp_val)) * 100
                return {
                    "current": float(current_val or 0),
                    "comparison": float(comp_val or 0),
                    "variance": float(current_val or 0) - float(comp_val or 0),
                    "variance_percent": round(pct, 2)
                }
            return {
                "current": float(current_val or 0),
                "comparison": float(comp_val or 0) if comp_val else None,
                "variance": None,
                "variance_percent": None
            }
        
        comp_data = comparison if comparison else None
        
        return {
            "current_period": {
                "from": period_from.isoformat(),
                "to": period_to.isoformat(),
                "bas": current.to_dict()
            },
            "comparison_period": {
                "from": comp_from.isoformat(),
                "to": comp_to.isoformat(),
                "bas": comp_data.to_dict() if comp_data else None
            },
            "comparison_type": compare_with,
            "variances": {
                "g1_total_income": calc_variance(current.g1_total_income, comp_data.g1_total_income if comp_data else 0),
                "net_gst": calc_variance(current.net_gst, comp_data.net_gst if comp_data else 0),
                "payg_instalment": calc_variance(current.payg_instalment, comp_data.payg_instalment if comp_data else 0),
                "total_payable": calc_variance(current.total_payable, comp_data.total_payable if comp_data else 0)
            }
        }

