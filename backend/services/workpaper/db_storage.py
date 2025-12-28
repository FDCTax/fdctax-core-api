"""
FDC Core Workpaper Platform - Database Storage Layer

PostgreSQL-backed storage replacing file-based JSON storage.
Uses SQLAlchemy async sessions for all database operations.
"""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, TypeVar, Generic, Type
import logging

from sqlalchemy import select, update, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from database.workpaper_models import (
    WorkpaperJobDB, ModuleInstanceDB, TransactionDB, TransactionOverrideDB,
    OverrideRecordDB, QueryDB, QueryMessageDB, TaskDB,
    FreezeSnapshotDB, WorkpaperAuditLogDB
)
from services.workpaper.models import (
    WorkpaperJob, ModuleInstance, Transaction, TransactionOverride,
    OverrideRecord, Query, QueryMessage, Task, FreezeSnapshot,
    EffectiveTransaction, JobStatus, QueryStatus, TaskStatus, TaskType
)

logger = logging.getLogger(__name__)

T = TypeVar('T')
DBT = TypeVar('DBT')


# ==================== CONVERSION HELPERS ====================

def db_to_pydantic_job(db_obj: WorkpaperJobDB) -> WorkpaperJob:
    """Convert database model to Pydantic model"""
    return WorkpaperJob(
        id=db_obj.id,
        client_id=db_obj.client_id,
        year=db_obj.year,
        status=db_obj.status,
        frozen_at=db_obj.frozen_at.isoformat() if db_obj.frozen_at else None,
        notes=db_obj.notes,
        created_at=db_obj.created_at.isoformat() if db_obj.created_at else None,
        updated_at=db_obj.updated_at.isoformat() if db_obj.updated_at else None,
    )


def db_to_pydantic_module(db_obj: ModuleInstanceDB) -> ModuleInstance:
    """Convert database model to Pydantic model"""
    return ModuleInstance(
        id=db_obj.id,
        job_id=db_obj.job_id,
        module_type=db_obj.module_type,
        label=db_obj.label,
        status=db_obj.status,
        config=db_obj.config or {},
        output_summary=db_obj.output_summary or {},
        calculation_inputs=db_obj.calculation_inputs or {},
        frozen_at=db_obj.frozen_at.isoformat() if db_obj.frozen_at else None,
        created_at=db_obj.created_at.isoformat() if db_obj.created_at else None,
        updated_at=db_obj.updated_at.isoformat() if db_obj.updated_at else None,
    )


def db_to_pydantic_transaction(db_obj: TransactionDB) -> Transaction:
    """Convert database model to Pydantic model"""
    return Transaction(
        id=db_obj.id,
        client_id=db_obj.client_id,
        job_id=db_obj.job_id,
        module_instance_id=db_obj.module_instance_id,
        source=db_obj.source,
        date=db_obj.date,
        amount=db_obj.amount,
        gst_amount=db_obj.gst_amount,
        category=db_obj.category,
        description=db_obj.description,
        receipt_url=db_obj.receipt_url,
        document_id=db_obj.document_id,
        vendor=db_obj.vendor,
        reference=db_obj.reference,
        metadata=db_obj.extra_data or {},
        created_at=db_obj.created_at.isoformat() if db_obj.created_at else None,
    )


def db_to_pydantic_tx_override(db_obj: TransactionOverrideDB) -> TransactionOverride:
    """Convert database model to Pydantic model"""
    return TransactionOverride(
        id=db_obj.id,
        transaction_id=db_obj.transaction_id,
        job_id=db_obj.job_id,
        overridden_category=db_obj.overridden_category,
        overridden_amount=db_obj.overridden_amount,
        overridden_gst_amount=db_obj.overridden_gst_amount,
        overridden_business_pct=db_obj.overridden_business_pct,
        reason=db_obj.reason,
        admin_user_id=db_obj.admin_user_id,
        admin_email=db_obj.admin_email,
        created_at=db_obj.created_at.isoformat() if db_obj.created_at else None,
        updated_at=db_obj.updated_at.isoformat() if db_obj.updated_at else None,
    )


def db_to_pydantic_override_record(db_obj: OverrideRecordDB) -> OverrideRecord:
    """Convert database model to Pydantic model"""
    return OverrideRecord(
        id=db_obj.id,
        module_instance_id=db_obj.module_instance_id,
        field_key=db_obj.field_key,
        original_value=db_obj.original_value,
        effective_value=db_obj.effective_value,
        reason=db_obj.reason,
        admin_user_id=db_obj.admin_user_id,
        admin_email=db_obj.admin_email,
        created_at=db_obj.created_at.isoformat() if db_obj.created_at else None,
    )


def db_to_pydantic_query(db_obj: QueryDB) -> Query:
    """Convert database model to Pydantic model"""
    return Query(
        id=db_obj.id,
        client_id=db_obj.client_id,
        job_id=db_obj.job_id,
        module_instance_id=db_obj.module_instance_id,
        transaction_id=db_obj.transaction_id,
        status=db_obj.status,
        title=db_obj.title,
        query_type=db_obj.query_type,
        request_config=db_obj.request_config or {},
        response_data=db_obj.response_data,
        created_by_admin_id=db_obj.created_by_admin_id,
        created_by_admin_email=db_obj.created_by_admin_email,
        resolved_by_admin_id=db_obj.resolved_by_admin_id,
        resolved_at=db_obj.resolved_at.isoformat() if db_obj.resolved_at else None,
        created_at=db_obj.created_at.isoformat() if db_obj.created_at else None,
        updated_at=db_obj.updated_at.isoformat() if db_obj.updated_at else None,
    )


def db_to_pydantic_message(db_obj: QueryMessageDB) -> QueryMessage:
    """Convert database model to Pydantic model"""
    return QueryMessage(
        id=db_obj.id,
        query_id=db_obj.query_id,
        sender_type=db_obj.sender_type,
        sender_id=db_obj.sender_id,
        sender_email=db_obj.sender_email,
        message_text=db_obj.message_text,
        attachment_url=db_obj.attachment_url,
        attachment_name=db_obj.attachment_name,
        created_at=db_obj.created_at.isoformat() if db_obj.created_at else None,
    )


def db_to_pydantic_task(db_obj: TaskDB) -> Task:
    """Convert database model to Pydantic model"""
    return Task(
        id=db_obj.id,
        client_id=db_obj.client_id,
        job_id=db_obj.job_id,
        task_type=db_obj.task_type,
        status=db_obj.status,
        title=db_obj.title,
        description=db_obj.description,
        metadata=db_obj.task_data or {},
        due_date=db_obj.due_date.isoformat() if db_obj.due_date else None,
        completed_at=db_obj.completed_at.isoformat() if db_obj.completed_at else None,
        created_at=db_obj.created_at.isoformat() if db_obj.created_at else None,
        updated_at=db_obj.updated_at.isoformat() if db_obj.updated_at else None,
    )


def db_to_pydantic_snapshot(db_obj: FreezeSnapshotDB) -> FreezeSnapshot:
    """Convert database model to Pydantic model"""
    return FreezeSnapshot(
        id=db_obj.id,
        job_id=db_obj.job_id,
        module_instance_id=db_obj.module_instance_id,
        snapshot_type=db_obj.snapshot_type,
        data=db_obj.data or {},
        summary=db_obj.summary or {},
        created_by_admin_id=db_obj.created_by_admin_id,
        created_by_admin_email=db_obj.created_by_admin_email,
        created_at=db_obj.created_at.isoformat() if db_obj.created_at else None,
    )


# ==================== REPOSITORY CLASSES ====================

class WorkpaperJobRepository:
    """Repository for WorkpaperJob database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, job: WorkpaperJob) -> WorkpaperJob:
        """Create a new job"""
        db_job = WorkpaperJobDB(
            id=job.id,
            client_id=job.client_id,
            year=job.year,
            status=job.status,
            notes=job.notes,
        )
        self.session.add(db_job)
        await self.session.commit()
        await self.session.refresh(db_job)
        return db_to_pydantic_job(db_job)
    
    async def get(self, job_id: str) -> Optional[WorkpaperJob]:
        """Get job by ID"""
        result = await self.session.execute(
            select(WorkpaperJobDB).where(WorkpaperJobDB.id == job_id)
        )
        db_job = result.scalar_one_or_none()
        return db_to_pydantic_job(db_job) if db_job else None
    
    async def get_by_client_year(self, client_id: str, year: str) -> Optional[WorkpaperJob]:
        """Get job by client and year"""
        result = await self.session.execute(
            select(WorkpaperJobDB).where(
                and_(
                    WorkpaperJobDB.client_id == client_id,
                    WorkpaperJobDB.year == year
                )
            )
        )
        db_job = result.scalar_one_or_none()
        return db_to_pydantic_job(db_job) if db_job else None
    
    async def list_by_client(self, client_id: str) -> List[WorkpaperJob]:
        """List all jobs for a client"""
        result = await self.session.execute(
            select(WorkpaperJobDB)
            .where(WorkpaperJobDB.client_id == client_id)
            .order_by(WorkpaperJobDB.year.desc())
        )
        return [db_to_pydantic_job(db_job) for db_job in result.scalars().all()]
    
    async def update(self, job_id: str, updates: Dict[str, Any]) -> Optional[WorkpaperJob]:
        """Update a job"""
        updates['updated_at'] = datetime.now(timezone.utc)
        
        # Handle frozen_at conversion
        if 'frozen_at' in updates and isinstance(updates['frozen_at'], str):
            updates['frozen_at'] = datetime.fromisoformat(updates['frozen_at'].replace('Z', '+00:00'))
        
        await self.session.execute(
            update(WorkpaperJobDB)
            .where(WorkpaperJobDB.id == job_id)
            .values(**updates)
        )
        await self.session.commit()
        return await self.get(job_id)
    
    async def delete(self, job_id: str) -> bool:
        """Delete a job"""
        result = await self.session.execute(
            delete(WorkpaperJobDB).where(WorkpaperJobDB.id == job_id)
        )
        await self.session.commit()
        return result.rowcount > 0


class ModuleInstanceRepository:
    """Repository for ModuleInstance database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, module: ModuleInstance) -> ModuleInstance:
        """Create a new module"""
        db_module = ModuleInstanceDB(
            id=module.id,
            job_id=module.job_id,
            module_type=module.module_type,
            label=module.label,
            status=module.status,
            config=module.config,
            output_summary=module.output_summary,
            calculation_inputs=module.calculation_inputs,
        )
        self.session.add(db_module)
        await self.session.commit()
        await self.session.refresh(db_module)
        return db_to_pydantic_module(db_module)
    
    async def get(self, module_id: str) -> Optional[ModuleInstance]:
        """Get module by ID"""
        result = await self.session.execute(
            select(ModuleInstanceDB).where(ModuleInstanceDB.id == module_id)
        )
        db_module = result.scalar_one_or_none()
        return db_to_pydantic_module(db_module) if db_module else None
    
    async def list_by_job(self, job_id: str) -> List[ModuleInstance]:
        """List all modules for a job"""
        result = await self.session.execute(
            select(ModuleInstanceDB)
            .where(ModuleInstanceDB.job_id == job_id)
            .order_by(ModuleInstanceDB.module_type)
        )
        return [db_to_pydantic_module(db_module) for db_module in result.scalars().all()]
    
    async def get_by_job_and_type(
        self, job_id: str, module_type: str, label: Optional[str] = None
    ) -> Optional[ModuleInstance]:
        """Get module by job and type"""
        query = select(ModuleInstanceDB).where(
            and_(
                ModuleInstanceDB.job_id == job_id,
                ModuleInstanceDB.module_type == module_type
            )
        )
        if label:
            query = query.where(ModuleInstanceDB.label == label)
        
        result = await self.session.execute(query)
        db_module = result.scalar_one_or_none()
        return db_to_pydantic_module(db_module) if db_module else None
    
    async def update(self, module_id: str, updates: Dict[str, Any]) -> Optional[ModuleInstance]:
        """Update a module"""
        updates['updated_at'] = datetime.now(timezone.utc)
        
        # Handle frozen_at conversion
        if 'frozen_at' in updates and isinstance(updates['frozen_at'], str):
            updates['frozen_at'] = datetime.fromisoformat(updates['frozen_at'].replace('Z', '+00:00'))
        elif 'frozen_at' in updates and updates['frozen_at'] is None:
            pass  # Keep None as is
        
        await self.session.execute(
            update(ModuleInstanceDB)
            .where(ModuleInstanceDB.id == module_id)
            .values(**updates)
        )
        await self.session.commit()
        return await self.get(module_id)
    
    async def delete(self, module_id: str) -> bool:
        """Delete a module"""
        result = await self.session.execute(
            delete(ModuleInstanceDB).where(ModuleInstanceDB.id == module_id)
        )
        await self.session.commit()
        return result.rowcount > 0


class TransactionRepository:
    """Repository for Transaction database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, transaction: Transaction) -> Transaction:
        """Create a new transaction"""
        db_tx = TransactionDB(
            id=transaction.id,
            client_id=transaction.client_id,
            job_id=transaction.job_id,
            module_instance_id=transaction.module_instance_id,
            source=transaction.source,
            date=transaction.date,
            amount=transaction.amount,
            gst_amount=transaction.gst_amount,
            category=transaction.category,
            description=transaction.description,
            receipt_url=transaction.receipt_url,
            document_id=transaction.document_id,
            vendor=transaction.vendor,
            reference=transaction.reference,
            extra_data=transaction.metadata,
        )
        self.session.add(db_tx)
        await self.session.commit()
        await self.session.refresh(db_tx)
        return db_to_pydantic_transaction(db_tx)
    
    async def get(self, transaction_id: str) -> Optional[Transaction]:
        """Get transaction by ID"""
        result = await self.session.execute(
            select(TransactionDB).where(TransactionDB.id == transaction_id)
        )
        db_tx = result.scalar_one_or_none()
        return db_to_pydantic_transaction(db_tx) if db_tx else None
    
    async def list_by_client(self, client_id: str) -> List[Transaction]:
        """List all transactions for a client"""
        result = await self.session.execute(
            select(TransactionDB)
            .where(TransactionDB.client_id == client_id)
            .order_by(TransactionDB.date.desc())
        )
        return [db_to_pydantic_transaction(db_tx) for db_tx in result.scalars().all()]
    
    async def list_by_job(self, job_id: str) -> List[Transaction]:
        """List all transactions for a job"""
        result = await self.session.execute(
            select(TransactionDB)
            .where(TransactionDB.job_id == job_id)
            .order_by(TransactionDB.date.desc())
        )
        return [db_to_pydantic_transaction(db_tx) for db_tx in result.scalars().all()]
    
    async def list_by_module(self, module_instance_id: str) -> List[Transaction]:
        """List all transactions for a module"""
        result = await self.session.execute(
            select(TransactionDB)
            .where(TransactionDB.module_instance_id == module_instance_id)
            .order_by(TransactionDB.date.desc())
        )
        return [db_to_pydantic_transaction(db_tx) for db_tx in result.scalars().all()]
    
    async def list_by_categories(self, job_id: str, categories: List[str]) -> List[Transaction]:
        """List transactions by categories for a job"""
        result = await self.session.execute(
            select(TransactionDB)
            .where(
                and_(
                    TransactionDB.job_id == job_id,
                    TransactionDB.category.in_(categories)
                )
            )
            .order_by(TransactionDB.date.desc())
        )
        return [db_to_pydantic_transaction(db_tx) for db_tx in result.scalars().all()]
    
    async def delete(self, transaction_id: str) -> bool:
        """Delete a transaction"""
        result = await self.session.execute(
            delete(TransactionDB).where(TransactionDB.id == transaction_id)
        )
        await self.session.commit()
        return result.rowcount > 0


class TransactionOverrideRepository:
    """Repository for TransactionOverride database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, override: TransactionOverride) -> TransactionOverride:
        """Create a new override"""
        db_override = TransactionOverrideDB(
            id=override.id,
            transaction_id=override.transaction_id,
            job_id=override.job_id,
            overridden_category=override.overridden_category,
            overridden_amount=override.overridden_amount,
            overridden_gst_amount=override.overridden_gst_amount,
            overridden_business_pct=override.overridden_business_pct,
            reason=override.reason,
            admin_user_id=override.admin_user_id,
            admin_email=override.admin_email,
        )
        self.session.add(db_override)
        await self.session.commit()
        await self.session.refresh(db_override)
        return db_to_pydantic_tx_override(db_override)
    
    async def get(self, override_id: str) -> Optional[TransactionOverride]:
        """Get override by ID"""
        result = await self.session.execute(
            select(TransactionOverrideDB).where(TransactionOverrideDB.id == override_id)
        )
        db_override = result.scalar_one_or_none()
        return db_to_pydantic_tx_override(db_override) if db_override else None
    
    async def get_by_transaction_job(
        self, transaction_id: str, job_id: str
    ) -> Optional[TransactionOverride]:
        """Get override for a transaction in a specific job"""
        result = await self.session.execute(
            select(TransactionOverrideDB).where(
                and_(
                    TransactionOverrideDB.transaction_id == transaction_id,
                    TransactionOverrideDB.job_id == job_id
                )
            )
        )
        db_override = result.scalar_one_or_none()
        return db_to_pydantic_tx_override(db_override) if db_override else None
    
    async def list_by_job(self, job_id: str) -> List[TransactionOverride]:
        """List all overrides for a job"""
        result = await self.session.execute(
            select(TransactionOverrideDB)
            .where(TransactionOverrideDB.job_id == job_id)
        )
        return [db_to_pydantic_tx_override(db_o) for db_o in result.scalars().all()]
    
    async def update(self, override_id: str, updates: Dict[str, Any]) -> Optional[TransactionOverride]:
        """Update an override"""
        updates['updated_at'] = datetime.now(timezone.utc)
        await self.session.execute(
            update(TransactionOverrideDB)
            .where(TransactionOverrideDB.id == override_id)
            .values(**updates)
        )
        await self.session.commit()
        return await self.get(override_id)
    
    async def delete(self, override_id: str) -> bool:
        """Delete an override"""
        result = await self.session.execute(
            delete(TransactionOverrideDB).where(TransactionOverrideDB.id == override_id)
        )
        await self.session.commit()
        return result.rowcount > 0


class OverrideRecordRepository:
    """Repository for OverrideRecord (module-level overrides) database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, record: OverrideRecord) -> OverrideRecord:
        """Create a new override record"""
        db_record = OverrideRecordDB(
            id=record.id,
            module_instance_id=record.module_instance_id,
            field_key=record.field_key,
            original_value=record.original_value,
            effective_value=record.effective_value,
            reason=record.reason,
            admin_user_id=record.admin_user_id,
            admin_email=record.admin_email,
        )
        self.session.add(db_record)
        await self.session.commit()
        await self.session.refresh(db_record)
        return db_to_pydantic_override_record(db_record)
    
    async def get(self, record_id: str) -> Optional[OverrideRecord]:
        """Get override record by ID"""
        result = await self.session.execute(
            select(OverrideRecordDB).where(OverrideRecordDB.id == record_id)
        )
        db_record = result.scalar_one_or_none()
        return db_to_pydantic_override_record(db_record) if db_record else None
    
    async def list_by_module(self, module_instance_id: str) -> List[OverrideRecord]:
        """List all override records for a module"""
        result = await self.session.execute(
            select(OverrideRecordDB)
            .where(OverrideRecordDB.module_instance_id == module_instance_id)
        )
        return [db_to_pydantic_override_record(db_r) for db_r in result.scalars().all()]
    
    async def get_by_field(
        self, module_instance_id: str, field_key: str
    ) -> Optional[OverrideRecord]:
        """Get override for a specific field"""
        result = await self.session.execute(
            select(OverrideRecordDB).where(
                and_(
                    OverrideRecordDB.module_instance_id == module_instance_id,
                    OverrideRecordDB.field_key == field_key
                )
            )
        )
        db_record = result.scalar_one_or_none()
        return db_to_pydantic_override_record(db_record) if db_record else None
    
    async def update(self, record_id: str, updates: Dict[str, Any]) -> Optional[OverrideRecord]:
        """Update an override record"""
        await self.session.execute(
            update(OverrideRecordDB)
            .where(OverrideRecordDB.id == record_id)
            .values(**updates)
        )
        await self.session.commit()
        return await self.get(record_id)
    
    async def delete(self, record_id: str) -> bool:
        """Delete an override record"""
        result = await self.session.execute(
            delete(OverrideRecordDB).where(OverrideRecordDB.id == record_id)
        )
        await self.session.commit()
        return result.rowcount > 0


class QueryRepository:
    """Repository for Query database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, query: Query) -> Query:
        """Create a new query"""
        db_query = QueryDB(
            id=query.id,
            client_id=query.client_id,
            job_id=query.job_id,
            module_instance_id=query.module_instance_id,
            transaction_id=query.transaction_id,
            status=query.status,
            title=query.title,
            query_type=query.query_type,
            request_config=query.request_config,
            response_data=query.response_data,
            created_by_admin_id=query.created_by_admin_id,
            created_by_admin_email=query.created_by_admin_email,
        )
        self.session.add(db_query)
        await self.session.commit()
        await self.session.refresh(db_query)
        return db_to_pydantic_query(db_query)
    
    async def get(self, query_id: str) -> Optional[Query]:
        """Get query by ID"""
        result = await self.session.execute(
            select(QueryDB).where(QueryDB.id == query_id)
        )
        db_query = result.scalar_one_or_none()
        return db_to_pydantic_query(db_query) if db_query else None
    
    async def list_by_job(self, job_id: str, status: Optional[str] = None) -> List[Query]:
        """List queries for a job"""
        query = select(QueryDB).where(QueryDB.job_id == job_id)
        if status:
            query = query.where(QueryDB.status == status)
        query = query.order_by(QueryDB.created_at.desc())
        
        result = await self.session.execute(query)
        return [db_to_pydantic_query(db_q) for db_q in result.scalars().all()]
    
    async def list_by_module(self, module_instance_id: str) -> List[Query]:
        """List queries for a module"""
        result = await self.session.execute(
            select(QueryDB)
            .where(QueryDB.module_instance_id == module_instance_id)
            .order_by(QueryDB.created_at.desc())
        )
        return [db_to_pydantic_query(db_q) for db_q in result.scalars().all()]
    
    async def list_by_transaction(self, transaction_id: str) -> List[Query]:
        """List queries for a transaction"""
        result = await self.session.execute(
            select(QueryDB)
            .where(QueryDB.transaction_id == transaction_id)
            .order_by(QueryDB.created_at.desc())
        )
        return [db_to_pydantic_query(db_q) for db_q in result.scalars().all()]
    
    async def list_open_by_job(self, job_id: str) -> List[Query]:
        """List open queries for a job"""
        open_statuses = [
            QueryStatus.SENT_TO_CLIENT.value,
            QueryStatus.AWAITING_CLIENT.value,
            QueryStatus.CLIENT_RESPONDED.value
        ]
        result = await self.session.execute(
            select(QueryDB)
            .where(
                and_(
                    QueryDB.job_id == job_id,
                    QueryDB.status.in_(open_statuses)
                )
            )
            .order_by(QueryDB.created_at.desc())
        )
        return [db_to_pydantic_query(db_q) for db_q in result.scalars().all()]
    
    async def count_open_by_job(self, job_id: str) -> int:
        """Count open queries for a job"""
        return len(await self.list_open_by_job(job_id))
    
    async def count_open_by_module(self, module_instance_id: str) -> int:
        """Count open queries for a module"""
        open_statuses = [
            QueryStatus.SENT_TO_CLIENT.value,
            QueryStatus.AWAITING_CLIENT.value,
            QueryStatus.CLIENT_RESPONDED.value
        ]
        result = await self.session.execute(
            select(QueryDB)
            .where(
                and_(
                    QueryDB.module_instance_id == module_instance_id,
                    QueryDB.status.in_(open_statuses)
                )
            )
        )
        return len(result.scalars().all())
    
    async def update(self, query_id: str, updates: Dict[str, Any]) -> Optional[Query]:
        """Update a query"""
        updates['updated_at'] = datetime.now(timezone.utc)
        
        # Handle resolved_at conversion
        if 'resolved_at' in updates and isinstance(updates['resolved_at'], str):
            updates['resolved_at'] = datetime.fromisoformat(updates['resolved_at'].replace('Z', '+00:00'))
        
        await self.session.execute(
            update(QueryDB)
            .where(QueryDB.id == query_id)
            .values(**updates)
        )
        await self.session.commit()
        return await self.get(query_id)
    
    async def delete(self, query_id: str) -> bool:
        """Delete a query"""
        result = await self.session.execute(
            delete(QueryDB).where(QueryDB.id == query_id)
        )
        await self.session.commit()
        return result.rowcount > 0


class QueryMessageRepository:
    """Repository for QueryMessage database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, message: QueryMessage) -> QueryMessage:
        """Create a new message"""
        db_message = QueryMessageDB(
            id=message.id,
            query_id=message.query_id,
            sender_type=message.sender_type,
            sender_id=message.sender_id,
            sender_email=message.sender_email,
            message_text=message.message_text,
            attachment_url=message.attachment_url,
            attachment_name=message.attachment_name,
        )
        self.session.add(db_message)
        await self.session.commit()
        await self.session.refresh(db_message)
        return db_to_pydantic_message(db_message)
    
    async def list_by_query(self, query_id: str) -> List[QueryMessage]:
        """List messages for a query, ordered by created_at"""
        result = await self.session.execute(
            select(QueryMessageDB)
            .where(QueryMessageDB.query_id == query_id)
            .order_by(QueryMessageDB.created_at.asc())
        )
        return [db_to_pydantic_message(db_m) for db_m in result.scalars().all()]


class TaskRepository:
    """Repository for Task database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, task: Task) -> Task:
        """Create a new task"""
        db_task = TaskDB(
            id=task.id,
            client_id=task.client_id,
            job_id=task.job_id,
            task_type=task.task_type,
            status=task.status,
            title=task.title,
            description=task.description,
            task_data=task.metadata,
        )
        self.session.add(db_task)
        await self.session.commit()
        await self.session.refresh(db_task)
        return db_to_pydantic_task(db_task)
    
    async def get(self, task_id: str) -> Optional[Task]:
        """Get task by ID"""
        result = await self.session.execute(
            select(TaskDB).where(TaskDB.id == task_id)
        )
        db_task = result.scalar_one_or_none()
        return db_to_pydantic_task(db_task) if db_task else None
    
    async def get_queries_task(self, client_id: str, job_id: str) -> Optional[Task]:
        """Get the QUERIES task for a job"""
        result = await self.session.execute(
            select(TaskDB).where(
                and_(
                    TaskDB.client_id == client_id,
                    TaskDB.job_id == job_id,
                    TaskDB.task_type == TaskType.QUERIES.value
                )
            )
        )
        db_task = result.scalar_one_or_none()
        return db_to_pydantic_task(db_task) if db_task else None
    
    async def list_by_client(self, client_id: str, status: Optional[str] = None) -> List[Task]:
        """List tasks for a client"""
        query = select(TaskDB).where(TaskDB.client_id == client_id)
        if status:
            query = query.where(TaskDB.status == status)
        query = query.order_by(TaskDB.created_at.desc())
        
        result = await self.session.execute(query)
        return [db_to_pydantic_task(db_t) for db_t in result.scalars().all()]
    
    async def list_by_job(self, job_id: str) -> List[Task]:
        """List tasks for a job"""
        result = await self.session.execute(
            select(TaskDB)
            .where(TaskDB.job_id == job_id)
            .order_by(TaskDB.created_at.desc())
        )
        return [db_to_pydantic_task(db_t) for db_t in result.scalars().all()]
    
    async def update(self, task_id: str, updates: Dict[str, Any]) -> Optional[Task]:
        """Update a task"""
        updates['updated_at'] = datetime.now(timezone.utc)
        
        # Handle completed_at conversion
        if 'completed_at' in updates and isinstance(updates['completed_at'], str):
            updates['completed_at'] = datetime.fromisoformat(updates['completed_at'].replace('Z', '+00:00'))
        
        # Handle metadata -> task_data rename
        if 'metadata' in updates:
            updates['task_data'] = updates.pop('metadata')
        
        await self.session.execute(
            update(TaskDB)
            .where(TaskDB.id == task_id)
            .values(**updates)
        )
        await self.session.commit()
        return await self.get(task_id)
    
    async def delete(self, task_id: str) -> bool:
        """Delete a task"""
        result = await self.session.execute(
            delete(TaskDB).where(TaskDB.id == task_id)
        )
        await self.session.commit()
        return result.rowcount > 0


class FreezeSnapshotRepository:
    """Repository for FreezeSnapshot database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, snapshot: FreezeSnapshot) -> FreezeSnapshot:
        """Create a new snapshot"""
        db_snapshot = FreezeSnapshotDB(
            id=snapshot.id,
            job_id=snapshot.job_id,
            module_instance_id=snapshot.module_instance_id,
            snapshot_type=snapshot.snapshot_type,
            data=snapshot.data,
            summary=snapshot.summary,
            created_by_admin_id=snapshot.created_by_admin_id,
            created_by_admin_email=snapshot.created_by_admin_email,
        )
        self.session.add(db_snapshot)
        await self.session.commit()
        await self.session.refresh(db_snapshot)
        return db_to_pydantic_snapshot(db_snapshot)
    
    async def get(self, snapshot_id: str) -> Optional[FreezeSnapshot]:
        """Get snapshot by ID"""
        result = await self.session.execute(
            select(FreezeSnapshotDB).where(FreezeSnapshotDB.id == snapshot_id)
        )
        db_snapshot = result.scalar_one_or_none()
        return db_to_pydantic_snapshot(db_snapshot) if db_snapshot else None
    
    async def list_by_job(self, job_id: str) -> List[FreezeSnapshot]:
        """List snapshots for a job"""
        result = await self.session.execute(
            select(FreezeSnapshotDB)
            .where(FreezeSnapshotDB.job_id == job_id)
            .order_by(FreezeSnapshotDB.created_at.desc())
        )
        return [db_to_pydantic_snapshot(db_s) for db_s in result.scalars().all()]
    
    async def list_by_module(self, module_instance_id: str) -> List[FreezeSnapshot]:
        """List snapshots for a module"""
        result = await self.session.execute(
            select(FreezeSnapshotDB)
            .where(FreezeSnapshotDB.module_instance_id == module_instance_id)
            .order_by(FreezeSnapshotDB.created_at.desc())
        )
        return [db_to_pydantic_snapshot(db_s) for db_s in result.scalars().all()]
    
    async def get_latest_by_job(
        self, job_id: str, snapshot_type: Optional[str] = None
    ) -> Optional[FreezeSnapshot]:
        """Get the latest snapshot for a job"""
        query = select(FreezeSnapshotDB).where(FreezeSnapshotDB.job_id == job_id)
        if snapshot_type:
            query = query.where(FreezeSnapshotDB.snapshot_type == snapshot_type)
        query = query.order_by(FreezeSnapshotDB.created_at.desc()).limit(1)
        
        result = await self.session.execute(query)
        db_snapshot = result.scalar_one_or_none()
        return db_to_pydantic_snapshot(db_snapshot) if db_snapshot else None


class WorkpaperAuditLogRepository:
    """Repository for WorkpaperAuditLog database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(
        self,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
        job_id: Optional[str] = None,
        module_id: Optional[str] = None,
        client_id: Optional[str] = None,
        details: Optional[Dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> WorkpaperAuditLogDB:
        """Create a new audit log entry"""
        db_log = WorkpaperAuditLogDB(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            user_email=user_email,
            user_role=user_role,
            job_id=job_id,
            module_id=module_id,
            client_id=client_id,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            error_message=error_message,
        )
        self.session.add(db_log)
        await self.session.commit()
        return db_log
    
    async def list_by_job(
        self, job_id: str, limit: int = 100
    ) -> List[WorkpaperAuditLogDB]:
        """List audit logs for a job"""
        result = await self.session.execute(
            select(WorkpaperAuditLogDB)
            .where(WorkpaperAuditLogDB.job_id == job_id)
            .order_by(WorkpaperAuditLogDB.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
    
    async def list_by_user(
        self, user_id: str, limit: int = 100
    ) -> List[WorkpaperAuditLogDB]:
        """List audit logs for a user"""
        result = await self.session.execute(
            select(WorkpaperAuditLogDB)
            .where(WorkpaperAuditLogDB.user_id == user_id)
            .order_by(WorkpaperAuditLogDB.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


# ==================== EFFECTIVE TRANSACTION BUILDER ====================

class EffectiveTransactionBuilder:
    """
    Builds EffectiveTransaction views by combining transactions with overrides.
    Database-backed version.
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.transaction_repo = TransactionRepository(session)
        self.override_repo = TransactionOverrideRepository(session)
    
    async def build(self, transaction: Transaction, job_id: str) -> EffectiveTransaction:
        """Build effective transaction for a specific job"""
        override = await self.override_repo.get_by_transaction_job(transaction.id, job_id)
        
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
    
    async def build_for_job(
        self, job_id: str, category: Optional[str] = None
    ) -> List[EffectiveTransaction]:
        """Build all effective transactions for a job"""
        transactions = await self.transaction_repo.list_by_job(job_id)
        if category:
            transactions = [t for t in transactions if t.category == category]
        
        result = []
        for t in transactions:
            result.append(await self.build(t, job_id))
        return result
    
    async def build_for_module(
        self, module_instance_id: str, job_id: str
    ) -> List[EffectiveTransaction]:
        """Build effective transactions for a module"""
        transactions = await self.transaction_repo.list_by_module(module_instance_id)
        
        result = []
        for t in transactions:
            result.append(await self.build(t, job_id))
        return result
    
    async def build_for_categories(
        self, job_id: str, categories: List[str]
    ) -> List[EffectiveTransaction]:
        """Build effective transactions for multiple categories"""
        transactions = await self.transaction_repo.list_by_categories(job_id, categories)
        
        result = []
        for t in transactions:
            result.append(await self.build(t, job_id))
        return result
