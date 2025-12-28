"""
FDC Core Workpaper Platform - Freeze Engine

Handles freezing of modules and jobs with snapshot creation.
Frozen entities cannot be modified unless explicitly reopened.
"""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import logging

from services.workpaper.models import (
    WorkpaperJob, ModuleInstance, FreezeSnapshot, JobStatus,
    SnapshotType, ModuleType, FreezeModuleRequest, FreezeJobRequest
)
from services.workpaper.storage import (
    job_storage, module_storage, snapshot_storage,
    transaction_storage, override_storage, module_override_storage,
    effective_builder, query_storage
)
from services.workpaper.engine import calculate_module, calculate_all_modules
from services.audit import log_action, AuditAction, ResourceType

logger = logging.getLogger(__name__)


# ==================== FREEZE ENGINE ====================

class FreezeEngine:
    """
    Manages freezing of modules and jobs.
    Creates snapshots for audit trail.
    """
    
    def __init__(self):
        pass
    
    # ==================== MODULE FREEZE ====================
    
    def freeze_module(
        self,
        module_id: str,
        admin_id: str,
        admin_email: Optional[str] = None,
        reason: Optional[str] = None
    ) -> FreezeSnapshot:
        """
        Freeze a module.
        
        1. Compute module output summary (if not already)
        2. Create FreezeSnapshot with module data
        3. Set module status = FROZEN
        4. Block further changes
        """
        module = module_storage.get(module_id)
        if not module:
            raise ValueError(f"Module not found: {module_id}")
        
        if module.status == JobStatus.FROZEN.value:
            raise ValueError("Module is already frozen")
        
        job = job_storage.get(module.job_id)
        if not job:
            raise ValueError(f"Job not found: {module.job_id}")
        
        # Calculate if not already calculated
        if not module.output_summary:
            calculate_module(module_id)
            module = module_storage.get(module_id)
        
        # Gather snapshot data
        snapshot_data = self._gather_module_snapshot_data(module, job)
        
        # Create snapshot
        snapshot = FreezeSnapshot(
            job_id=job.id,
            module_instance_id=module_id,
            snapshot_type=SnapshotType.MODULE.value,
            data=snapshot_data,
            summary=module.output_summary or {},
            created_by_admin_id=admin_id,
            created_by_admin_email=admin_email,
        )
        
        snapshot = snapshot_storage.create(snapshot)
        
        # Freeze module
        module_storage.update(module_id, {
            "status": JobStatus.FROZEN.value,
            "frozen_at": datetime.now(timezone.utc).isoformat(),
        })
        
        # Update job status
        self._update_job_status(job.id)
        
        # Audit log
        log_action(
            action=AuditAction.WORKPAPER_MODULE_FREEZE,
            resource_type=ResourceType.WORKPAPER_MODULE,
            resource_id=module_id,
            user_id=admin_id,
            user_email=admin_email,
            details={
                "module_type": module.module_type,
                "label": module.label,
                "snapshot_id": snapshot.id,
                "reason": reason,
            }
        )
        
        logger.info(f"Module frozen: {module_id}, snapshot: {snapshot.id}")
        return snapshot
    
    def _gather_module_snapshot_data(
        self,
        module: ModuleInstance,
        job: WorkpaperJob
    ) -> Dict[str, Any]:
        """Gather all data for a module snapshot"""
        # Get effective transactions
        effective_txns = effective_builder.build_for_module(module.id, job.id)
        
        # Get overrides
        module_overrides = module_override_storage.list_by_module(module.id)
        
        # Get queries
        queries = query_storage.list_by_module(module.id)
        
        return {
            "module": module.model_dump(),
            "config": module.config,
            "output_summary": module.output_summary,
            "calculation_inputs": module.calculation_inputs,
            "effective_transactions": [t.model_dump() for t in effective_txns],
            "module_overrides": [o.model_dump() for o in module_overrides],
            "queries": [q.model_dump() for q in queries],
            "job": {
                "id": job.id,
                "year": job.year,
                "client_id": job.client_id,
            },
            "frozen_at": datetime.now(timezone.utc).isoformat(),
        }
    
    # ==================== JOB FREEZE ====================
    
    def freeze_job(
        self,
        job_id: str,
        snapshot_type: str,  # ITR, BAS, SUMMARY
        admin_id: str,
        admin_email: Optional[str] = None,
        reason: Optional[str] = None,
        require_all_completed: bool = True
    ) -> FreezeSnapshot:
        """
        Freeze a job.
        
        1. Ensure all required modules are COMPLETED or FROZEN
        2. Calculate final summary
        3. Create FreezeSnapshot at job level
        4. Set job status = FROZEN
        """
        job = job_storage.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        
        if job.status == JobStatus.FROZEN.value:
            raise ValueError("Job is already frozen")
        
        modules = module_storage.list_by_job(job_id)
        
        # Check module statuses
        if require_all_completed:
            incomplete = [
                m for m in modules 
                if m.status not in [JobStatus.COMPLETED.value, JobStatus.FROZEN.value, JobStatus.NA.value]
            ]
            if incomplete:
                raise ValueError(
                    f"Cannot freeze job. {len(incomplete)} modules not completed: "
                    f"{[m.label for m in incomplete]}"
                )
        
        # Calculate all modules to ensure outputs are current
        calculate_all_modules(job_id)
        
        # Reload modules after calculation
        modules = module_storage.list_by_job(job_id)
        
        # Gather snapshot data
        snapshot_data = self._gather_job_snapshot_data(job, modules, snapshot_type)
        
        # Create summary
        summary = self._calculate_job_summary(modules)
        
        # Create snapshot
        snapshot = FreezeSnapshot(
            job_id=job_id,
            module_instance_id=None,
            snapshot_type=snapshot_type,
            data=snapshot_data,
            summary=summary,
            created_by_admin_id=admin_id,
            created_by_admin_email=admin_email,
        )
        
        snapshot = snapshot_storage.create(snapshot)
        
        # Freeze all modules that aren't already frozen
        for module in modules:
            if module.status != JobStatus.FROZEN.value and module.status != JobStatus.NA.value:
                module_storage.update(module.id, {
                    "status": JobStatus.FROZEN.value,
                    "frozen_at": datetime.now(timezone.utc).isoformat(),
                })
        
        # Freeze job
        job_storage.update(job_id, {
            "status": JobStatus.FROZEN.value,
            "frozen_at": datetime.now(timezone.utc).isoformat(),
        })
        
        # Audit log
        log_action(
            action=AuditAction.WORKPAPER_JOB_FREEZE,
            resource_type=ResourceType.WORKPAPER_JOB,
            resource_id=job_id,
            user_id=admin_id,
            user_email=admin_email,
            details={
                "snapshot_type": snapshot_type,
                "snapshot_id": snapshot.id,
                "total_deductions": summary.get("total_deductions"),
                "total_income": summary.get("total_income"),
                "reason": reason,
            }
        )
        
        logger.info(f"Job frozen: {job_id}, snapshot: {snapshot.id}")
        return snapshot
    
    def _gather_job_snapshot_data(
        self,
        job: WorkpaperJob,
        modules: List[ModuleInstance],
        snapshot_type: str
    ) -> Dict[str, Any]:
        """Gather all data for a job snapshot"""
        module_data = []
        for module in modules:
            effective_txns = effective_builder.build_for_module(module.id, job.id)
            module_overrides = module_override_storage.list_by_module(module.id)
            
            module_data.append({
                "module": module.model_dump(),
                "effective_transactions": [t.model_dump() for t in effective_txns],
                "overrides": [o.model_dump() for o in module_overrides],
            })
        
        # Get job-level transaction overrides
        job_overrides = override_storage.list_by_job(job.id)
        
        return {
            "job": job.model_dump(),
            "snapshot_type": snapshot_type,
            "modules": module_data,
            "transaction_overrides": [o.model_dump() for o in job_overrides],
            "frozen_at": datetime.now(timezone.utc).isoformat(),
        }
    
    def _calculate_job_summary(self, modules: List[ModuleInstance]) -> Dict[str, Any]:
        """Calculate final job summary from modules"""
        total_deductions = 0
        total_gst_credits = 0
        total_income = 0
        
        by_module = {}
        
        for module in modules:
            if module.module_type == ModuleType.SUMMARY.value:
                continue
            
            summary = module.output_summary or {}
            
            deduction = summary.get("deduction", 0)
            gst_credit = summary.get("gst_credit", 0)
            income = summary.get("net_income", 0)
            
            total_deductions += deduction
            total_gst_credits += gst_credit
            total_income += income
            
            by_module[module.module_type] = {
                "label": module.label,
                "deduction": deduction,
                "gst_credit": gst_credit,
                "income": income,
                "status": module.status,
            }
        
        return {
            "total_income": round(total_income, 2),
            "total_deductions": round(total_deductions, 2),
            "net_taxable": round(total_income - total_deductions, 2),
            "total_gst_credits": round(total_gst_credits, 2),
            "by_module": by_module,
            "module_count": len(modules),
        }
    
    # ==================== STATUS MANAGEMENT ====================
    
    def _update_job_status(self, job_id: str):
        """Update job status based on module statuses"""
        job = job_storage.get(job_id)
        modules = module_storage.list_by_job(job_id)
        
        if job and modules:
            derived_status = job.derive_status_from_modules(modules)
            if derived_status != job.status:
                job_storage.update(job_id, {"status": derived_status})
    
    # ==================== QUERIES ====================
    
    def get_snapshot(self, snapshot_id: str) -> Optional[FreezeSnapshot]:
        """Get a snapshot by ID"""
        return snapshot_storage.get(snapshot_id)
    
    def list_job_snapshots(self, job_id: str) -> List[FreezeSnapshot]:
        """List all snapshots for a job"""
        return snapshot_storage.list_by_job(job_id)
    
    def list_module_snapshots(self, module_id: str) -> List[FreezeSnapshot]:
        """List all snapshots for a module"""
        return snapshot_storage.list_by_module(module_id)
    
    def get_latest_snapshot(
        self,
        job_id: str,
        snapshot_type: Optional[str] = None
    ) -> Optional[FreezeSnapshot]:
        """Get the latest snapshot for a job"""
        return snapshot_storage.get_latest_by_job(job_id, snapshot_type)
    
    # ==================== REOPEN (OPTIONAL) ====================
    
    def reopen_module(
        self,
        module_id: str,
        admin_id: str,
        admin_email: Optional[str] = None,
        reason: str = ""
    ) -> ModuleInstance:
        """
        Reopen a frozen module for editing.
        Requires explicit reason.
        """
        module = module_storage.get(module_id)
        if not module:
            raise ValueError(f"Module not found: {module_id}")
        
        if module.status != JobStatus.FROZEN.value:
            raise ValueError("Module is not frozen")
        
        if not reason:
            raise ValueError("Reason required to reopen frozen module")
        
        # Update status
        module = module_storage.update(module_id, {
            "status": JobStatus.IN_PROGRESS.value,
            "frozen_at": None,
        })
        
        # Update job status
        job = job_storage.get(module.job_id)
        if job and job.status == JobStatus.FROZEN.value:
            job_storage.update(job.id, {
                "status": JobStatus.IN_PROGRESS.value,
                "frozen_at": None,
            })
        
        # Audit log
        log_action(
            action=AuditAction.WORKPAPER_MODULE_REOPEN,
            resource_type=ResourceType.WORKPAPER_MODULE,
            resource_id=module_id,
            user_id=admin_id,
            user_email=admin_email,
            details={
                "module_type": module.module_type,
                "label": module.label,
                "reason": reason,
            }
        )
        
        logger.info(f"Module reopened: {module_id}, reason: {reason}")
        return module


# Singleton instance
freeze_engine = FreezeEngine()
