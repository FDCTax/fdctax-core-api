"""
FDC Core Workpaper Platform - Storage Layer

File-based storage for workpaper entities.
Can be migrated to PostgreSQL when permissions are available.
"""

import json
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, TypeVar, Generic
from pathlib import Path
import logging
import threading

from services.workpaper.models import (
    WorkpaperJob, ModuleInstance, Transaction, TransactionOverride,
    OverrideRecord, Query, QueryMessage, Task, FreezeSnapshot,
    EffectiveTransaction, JobStatus, ModuleType, QueryStatus,
    TaskStatus, TaskType
)

logger = logging.getLogger(__name__)

# Storage directory
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "workpaper"

# Thread lock for file writes
_write_lock = threading.Lock()

T = TypeVar('T')


class BaseStorage(Generic[T]):
    """Base class for file-based storage"""
    
    def __init__(self, file_name: str, model_class: type):
        self.file_path = DATA_DIR / file_name
        self.model_class = model_class
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._save_all([])
    
    def _load_all(self) -> List[Dict]:
        try:
            with open(self.file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {self.file_path}: {e}")
            return []
    
    def _save_all(self, items: List[Dict]):
        with _write_lock:
            with open(self.file_path, 'w') as f:
                json.dump(items, f, indent=2, default=str)
    
    def create(self, item: T) -> T:
        """Create a new item"""
        items = self._load_all()
        items.append(item.model_dump())
        self._save_all(items)
        return item
    
    def get(self, item_id: str) -> Optional[T]:
        """Get item by ID"""
        items = self._load_all()
        for item in items:
            if item.get('id') == item_id:
                return self.model_class(**item)
        return None
    
    def update(self, item_id: str, updates: Dict[str, Any]) -> Optional[T]:
        """Update an item"""
        items = self._load_all()
        for i, item in enumerate(items):
            if item.get('id') == item_id:
                updates['updated_at'] = datetime.now(timezone.utc).isoformat()
                items[i].update(updates)
                self._save_all(items)
                return self.model_class(**items[i])
        return None
    
    def delete(self, item_id: str) -> bool:
        """Delete an item"""
        items = self._load_all()
        original_len = len(items)
        items = [item for item in items if item.get('id') != item_id]
        if len(items) < original_len:
            self._save_all(items)
            return True
        return False
    
    def list_all(self) -> List[T]:
        """List all items"""
        items = self._load_all()
        return [self.model_class(**item) for item in items]
    
    def filter(self, **kwargs) -> List[T]:
        """Filter items by field values"""
        items = self._load_all()
        filtered = items
        for key, value in kwargs.items():
            filtered = [item for item in filtered if item.get(key) == value]
        return [self.model_class(**item) for item in filtered]


# ==================== SPECIFIC STORAGE CLASSES ====================

class WorkpaperJobStorage(BaseStorage[WorkpaperJob]):
    def __init__(self):
        super().__init__("jobs.json", WorkpaperJob)
    
    def get_by_client_year(self, client_id: str, year: str) -> Optional[WorkpaperJob]:
        """Get job by client and year"""
        items = self._load_all()
        for item in items:
            if item.get('client_id') == client_id and item.get('year') == year:
                return WorkpaperJob(**item)
        return None
    
    def list_by_client(self, client_id: str) -> List[WorkpaperJob]:
        """List all jobs for a client"""
        return self.filter(client_id=client_id)


class ModuleInstanceStorage(BaseStorage[ModuleInstance]):
    def __init__(self):
        super().__init__("modules.json", ModuleInstance)
    
    def list_by_job(self, job_id: str) -> List[ModuleInstance]:
        """List all modules for a job"""
        return self.filter(job_id=job_id)
    
    def get_by_job_and_type(self, job_id: str, module_type: str, label: Optional[str] = None) -> Optional[ModuleInstance]:
        """Get module by job and type (and optionally label)"""
        items = self._load_all()
        for item in items:
            if item.get('job_id') == job_id and item.get('module_type') == module_type:
                if label is None or item.get('label') == label:
                    return ModuleInstance(**item)
        return None


class TransactionStorage(BaseStorage[Transaction]):
    def __init__(self):
        super().__init__("transactions.json", Transaction)
    
    def list_by_client(self, client_id: str) -> List[Transaction]:
        """List all transactions for a client"""
        return self.filter(client_id=client_id)
    
    def list_by_job(self, job_id: str) -> List[Transaction]:
        """List all transactions for a job"""
        return self.filter(job_id=job_id)
    
    def list_by_module(self, module_instance_id: str) -> List[Transaction]:
        """List all transactions for a module"""
        return self.filter(module_instance_id=module_instance_id)
    
    def list_by_category(self, client_id: str, category: str) -> List[Transaction]:
        """List transactions by category"""
        items = self._load_all()
        filtered = [
            item for item in items 
            if item.get('client_id') == client_id and item.get('category') == category
        ]
        return [Transaction(**item) for item in filtered]


class TransactionOverrideStorage(BaseStorage[TransactionOverride]):
    def __init__(self):
        super().__init__("transaction_overrides.json", TransactionOverride)
    
    def get_by_transaction_job(self, transaction_id: str, job_id: str) -> Optional[TransactionOverride]:
        """Get override for a transaction in a specific job"""
        items = self._load_all()
        for item in items:
            if item.get('transaction_id') == transaction_id and item.get('job_id') == job_id:
                return TransactionOverride(**item)
        return None
    
    def list_by_job(self, job_id: str) -> List[TransactionOverride]:
        """List all overrides for a job"""
        return self.filter(job_id=job_id)


class OverrideRecordStorage(BaseStorage[OverrideRecord]):
    def __init__(self):
        super().__init__("module_overrides.json", OverrideRecord)
    
    def list_by_module(self, module_instance_id: str) -> List[OverrideRecord]:
        """List all overrides for a module"""
        return self.filter(module_instance_id=module_instance_id)
    
    def get_by_field(self, module_instance_id: str, field_key: str) -> Optional[OverrideRecord]:
        """Get override for a specific field"""
        items = self._load_all()
        for item in items:
            if item.get('module_instance_id') == module_instance_id and item.get('field_key') == field_key:
                return OverrideRecord(**item)
        return None


class QueryStorage(BaseStorage[Query]):
    def __init__(self):
        super().__init__("queries.json", Query)
    
    def list_by_job(self, job_id: str, status: Optional[str] = None) -> List[Query]:
        """List queries for a job, optionally filtered by status"""
        items = self._load_all()
        filtered = [item for item in items if item.get('job_id') == job_id]
        if status:
            filtered = [item for item in filtered if item.get('status') == status]
        return [Query(**item) for item in filtered]
    
    def list_by_module(self, module_instance_id: str) -> List[Query]:
        """List queries for a module"""
        return self.filter(module_instance_id=module_instance_id)
    
    def list_by_transaction(self, transaction_id: str) -> List[Query]:
        """List queries for a transaction"""
        return self.filter(transaction_id=transaction_id)
    
    def list_open_by_job(self, job_id: str) -> List[Query]:
        """List open queries for a job"""
        items = self._load_all()
        open_statuses = [QueryStatus.SENT_TO_CLIENT.value, QueryStatus.AWAITING_CLIENT.value, QueryStatus.CLIENT_RESPONDED.value]
        filtered = [
            item for item in items 
            if item.get('job_id') == job_id and item.get('status') in open_statuses
        ]
        return [Query(**item) for item in filtered]
    
    def count_open_by_job(self, job_id: str) -> int:
        """Count open queries for a job"""
        return len(self.list_open_by_job(job_id))
    
    def count_open_by_module(self, module_instance_id: str) -> int:
        """Count open queries for a module"""
        items = self._load_all()
        open_statuses = [QueryStatus.SENT_TO_CLIENT.value, QueryStatus.AWAITING_CLIENT.value, QueryStatus.CLIENT_RESPONDED.value]
        return len([
            item for item in items 
            if item.get('module_instance_id') == module_instance_id and item.get('status') in open_statuses
        ])


class QueryMessageStorage(BaseStorage[QueryMessage]):
    def __init__(self):
        super().__init__("query_messages.json", QueryMessage)
    
    def list_by_query(self, query_id: str) -> List[QueryMessage]:
        """List messages for a query, ordered by created_at"""
        messages = self.filter(query_id=query_id)
        messages.sort(key=lambda m: m.created_at)
        return messages


class TaskStorage(BaseStorage[Task]):
    def __init__(self):
        super().__init__("tasks.json", Task)
    
    def get_queries_task(self, client_id: str, job_id: str) -> Optional[Task]:
        """Get the QUERIES task for a job"""
        items = self._load_all()
        for item in items:
            if (item.get('client_id') == client_id and 
                item.get('job_id') == job_id and 
                item.get('task_type') == TaskType.QUERIES.value):
                return Task(**item)
        return None
    
    def list_by_client(self, client_id: str, status: Optional[str] = None) -> List[Task]:
        """List tasks for a client"""
        items = self._load_all()
        filtered = [item for item in items if item.get('client_id') == client_id]
        if status:
            filtered = [item for item in filtered if item.get('status') == status]
        return [Task(**item) for item in filtered]
    
    def list_by_job(self, job_id: str) -> List[Task]:
        """List tasks for a job"""
        return self.filter(job_id=job_id)


class FreezeSnapshotStorage(BaseStorage[FreezeSnapshot]):
    def __init__(self):
        super().__init__("freeze_snapshots.json", FreezeSnapshot)
    
    def list_by_job(self, job_id: str) -> List[FreezeSnapshot]:
        """List snapshots for a job"""
        return self.filter(job_id=job_id)
    
    def list_by_module(self, module_instance_id: str) -> List[FreezeSnapshot]:
        """List snapshots for a module"""
        return self.filter(module_instance_id=module_instance_id)
    
    def get_latest_by_job(self, job_id: str, snapshot_type: Optional[str] = None) -> Optional[FreezeSnapshot]:
        """Get the latest snapshot for a job"""
        snapshots = self.list_by_job(job_id)
        if snapshot_type:
            snapshots = [s for s in snapshots if s.snapshot_type == snapshot_type]
        if not snapshots:
            return None
        snapshots.sort(key=lambda s: s.created_at, reverse=True)
        return snapshots[0]


# ==================== EFFECTIVE TRANSACTION BUILDER ====================

class EffectiveTransactionBuilder:
    """
    Builds EffectiveTransaction views by combining transactions with overrides.
    """
    
    def __init__(self):
        self.transaction_storage = TransactionStorage()
        self.override_storage = TransactionOverrideStorage()
    
    def build(self, transaction: Transaction, job_id: str) -> EffectiveTransaction:
        """Build effective transaction for a specific job"""
        override = self.override_storage.get_by_transaction_job(transaction.id, job_id)
        
        # Determine effective values
        effective_amount = override.overridden_amount if override and override.overridden_amount is not None else transaction.amount
        effective_gst = override.overridden_gst_amount if override and override.overridden_gst_amount is not None else transaction.gst_amount
        effective_category = override.overridden_category if override and override.overridden_category else transaction.category
        effective_business_pct = override.overridden_business_pct if override and override.overridden_business_pct is not None else 100.0
        
        # Calculate business amounts
        business_amount = effective_amount * (effective_business_pct / 100.0)
        business_gst = effective_gst * (effective_business_pct / 100.0) if effective_gst else None
        
        return EffectiveTransaction(
            transaction_id=transaction.id,
            client_id=transaction.client_id,
            job_id=job_id,
            module_instance_id=transaction.module_instance_id,
            source=transaction.source,
            date=transaction.date,
            description=transaction.description,
            receipt_url=transaction.receipt_url,
            vendor=transaction.vendor,
            original_amount=transaction.amount,
            original_gst_amount=transaction.gst_amount,
            original_category=transaction.category,
            effective_amount=effective_amount,
            effective_gst_amount=effective_gst,
            effective_category=effective_category,
            effective_business_pct=effective_business_pct,
            has_override=override is not None,
            override_id=override.id if override else None,
            override_reason=override.reason if override else None,
            business_amount=business_amount,
            business_gst_amount=business_gst
        )
    
    def build_for_job(self, job_id: str, category: Optional[str] = None) -> List[EffectiveTransaction]:
        """Build all effective transactions for a job"""
        transactions = self.transaction_storage.list_by_job(job_id)
        if category:
            transactions = [t for t in transactions if t.category == category]
        return [self.build(t, job_id) for t in transactions]
    
    def build_for_module(self, module_instance_id: str, job_id: str) -> List[EffectiveTransaction]:
        """Build effective transactions for a module"""
        transactions = self.transaction_storage.list_by_module(module_instance_id)
        return [self.build(t, job_id) for t in transactions]
    
    def build_for_categories(self, job_id: str, categories: List[str]) -> List[EffectiveTransaction]:
        """Build effective transactions for multiple categories"""
        items = self.transaction_storage._load_all()
        transactions = [
            Transaction(**item) for item in items 
            if item.get('job_id') == job_id and item.get('category') in categories
        ]
        return [self.build(t, job_id) for t in transactions]


# ==================== SINGLETON INSTANCES ====================

# Initialize storage instances
job_storage = WorkpaperJobStorage()
module_storage = ModuleInstanceStorage()
transaction_storage = TransactionStorage()
override_storage = TransactionOverrideStorage()
module_override_storage = OverrideRecordStorage()
query_storage = QueryStorage()
message_storage = QueryMessageStorage()
task_storage = TaskStorage()
snapshot_storage = FreezeSnapshotStorage()
effective_builder = EffectiveTransactionBuilder()
