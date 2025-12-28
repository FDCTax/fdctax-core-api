"""
FDC Core - Transaction Engine Service Layer

Business logic for:
- Transaction CRUD operations
- History tracking
- Locking/unlocking
- MyFDC sync rules
- Bulk operations
- Permission enforcement
"""

from datetime import datetime, date, timezone
from typing import List, Optional, Dict, Any, Tuple
from decimal import Decimal
import logging
import json

from sqlalchemy import select, update, delete, and_, or_, func, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from database.transaction_models import (
    TransactionDB, TransactionHistoryDB, TransactionAttachmentDB,
    TransactionWorkpaperLinkDB,
    TransactionStatus, GSTCode, TransactionSource, ModuleRouting,
    HistoryActionType, STATUS_HIERARCHY
)

logger = logging.getLogger(__name__)


# ==================== PYDANTIC MODELS ====================

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class TransactionCreate(BaseModel):
    """Request to create a transaction"""
    client_id: str
    date: str  # YYYY-MM-DD
    amount: float
    payee_raw: Optional[str] = None
    description_raw: Optional[str] = None
    source: str = TransactionSource.MANUAL.value
    category_client: Optional[str] = None
    module_hint_client: Optional[str] = None
    notes_client: Optional[str] = None


class TransactionUpdate(BaseModel):
    """Request to update a transaction (bookkeeper)"""
    amount: Optional[float] = None
    date: Optional[str] = None
    payee_raw: Optional[str] = None
    description_raw: Optional[str] = None
    category_bookkeeper: Optional[str] = None
    gst_code_bookkeeper: Optional[str] = None
    notes_bookkeeper: Optional[str] = None
    status_bookkeeper: Optional[str] = None
    flags: Optional[Dict[str, bool]] = None
    module_routing: Optional[str] = None


class BulkUpdateRequest(BaseModel):
    """Request for bulk transaction update"""
    criteria: Dict[str, Any]  # Filter criteria
    updates: Dict[str, Any]   # Fields to update


class TransactionFilter(BaseModel):
    """Filter criteria for listing transactions"""
    client_id: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    source: Optional[str] = None
    flags: Optional[List[str]] = None  # ["late", "duplicate", "high_risk"]
    has_attachment: Optional[bool] = None
    module_routing: Optional[str] = None
    search: Optional[str] = None
    is_duplicate: Optional[bool] = None
    is_late_receipt: Optional[bool] = None


class Transaction(BaseModel):
    """Transaction response model"""
    id: str
    client_id: str
    date: str
    amount: float
    payee_raw: Optional[str] = None
    description_raw: Optional[str] = None
    source: str
    category_client: Optional[str] = None
    module_hint_client: Optional[str] = None
    notes_client: Optional[str] = None
    category_bookkeeper: Optional[str] = None
    gst_code_bookkeeper: Optional[str] = None
    notes_bookkeeper: Optional[str] = None
    status_bookkeeper: str
    flags: Optional[Dict[str, Any]] = None
    module_routing: Optional[str] = None
    is_duplicate: bool = False
    is_late_receipt: bool = False
    locked_at: Optional[str] = None
    locked_by_role: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    attachment_count: int = 0


class TransactionHistory(BaseModel):
    """Transaction history entry"""
    id: str
    transaction_id: str
    user_id: Optional[str] = None
    role: str
    action_type: str
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    timestamp: str
    comment: Optional[str] = None


class WorkpaperLockRequest(BaseModel):
    """Request to lock transactions for workpaper"""
    transaction_ids: List[str]
    workpaper_id: str
    module: str
    period: str


class PaginatedResult(BaseModel):
    """Paginated result with cursor"""
    items: List[Transaction]
    total: int
    cursor: Optional[str] = None
    has_more: bool = False


# ==================== HELPER FUNCTIONS ====================

def _parse_date(date_str: Optional[str]) -> Optional[date]:
    """Parse date string to date object"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def _format_date(d: Optional[date]) -> Optional[str]:
    """Format date object to string"""
    if not d:
        return None
    return d.isoformat()


def _format_datetime(dt: Optional[datetime]) -> Optional[str]:
    """Format datetime to ISO string"""
    if not dt:
        return None
    return dt.isoformat()


def _db_to_transaction(db_obj: TransactionDB, attachment_count: int = 0) -> Transaction:
    """Convert database model to Pydantic model"""
    return Transaction(
        id=db_obj.id,
        client_id=db_obj.client_id,
        date=_format_date(db_obj.date),
        amount=float(db_obj.amount) if db_obj.amount else 0,
        payee_raw=db_obj.payee_raw,
        description_raw=db_obj.description_raw,
        source=db_obj.source.value if db_obj.source else TransactionSource.MANUAL.value,
        category_client=db_obj.category_client,
        module_hint_client=db_obj.module_hint_client,
        notes_client=db_obj.notes_client,
        category_bookkeeper=db_obj.category_bookkeeper,
        gst_code_bookkeeper=db_obj.gst_code_bookkeeper.value if db_obj.gst_code_bookkeeper else None,
        notes_bookkeeper=db_obj.notes_bookkeeper,
        status_bookkeeper=db_obj.status_bookkeeper.value if db_obj.status_bookkeeper else TransactionStatus.NEW.value,
        flags=db_obj.flags,
        module_routing=db_obj.module_routing.value if db_obj.module_routing else None,
        is_duplicate=db_obj.is_duplicate or False,
        is_late_receipt=db_obj.is_late_receipt or False,
        locked_at=_format_datetime(db_obj.locked_at),
        locked_by_role=db_obj.locked_by_role,
        created_at=_format_datetime(db_obj.created_at),
        updated_at=_format_datetime(db_obj.updated_at),
        attachment_count=attachment_count,
    )


def _get_snapshot_fields(db_obj: TransactionDB) -> Dict[str, Any]:
    """Get bookkeeper fields for snapshot"""
    return {
        "id": db_obj.id,
        "amount": float(db_obj.amount) if db_obj.amount else 0,
        "date": _format_date(db_obj.date),
        "payee_raw": db_obj.payee_raw,
        "description_raw": db_obj.description_raw,
        "category_bookkeeper": db_obj.category_bookkeeper,
        "gst_code_bookkeeper": db_obj.gst_code_bookkeeper.value if db_obj.gst_code_bookkeeper else None,
        "notes_bookkeeper": db_obj.notes_bookkeeper,
        "module_routing": db_obj.module_routing.value if db_obj.module_routing else None,
        "flags": db_obj.flags,
        "locked_at": _format_datetime(db_obj.locked_at),
    }


# ==================== PERMISSION CHECKS ====================

class PermissionError(Exception):
    """Permission denied exception"""
    pass


class LockingError(Exception):
    """Locking rule violation"""
    pass


def check_bookkeeper_edit_permission(
    transaction: TransactionDB,
    user_role: str,
    fields_to_update: Dict[str, Any]
) -> None:
    """
    Check if user can edit the transaction.
    
    Rules:
    - If LOCKED: only notes + admin can edit
    - Bookkeeper: can edit until LOCKED
    - Tax Agent: read-only in Bookkeeper Tab
    - Admin: can edit any field
    """
    status = transaction.status_bookkeeper
    
    if user_role == "tax_agent":
        raise PermissionError("Tax agents have read-only access in Bookkeeper Tab")
    
    if status == TransactionStatus.LOCKED:
        if user_role != "admin":
            # Only notes_bookkeeper can be updated when locked (except by admin)
            allowed_when_locked = {"notes_bookkeeper"}
            requested_fields = set(fields_to_update.keys())
            disallowed = requested_fields - allowed_when_locked
            
            if disallowed:
                raise LockingError(
                    f"Transaction is LOCKED. Only notes can be edited. "
                    f"Disallowed fields: {disallowed}"
                )
    
    # Bookkeeper can only set status up to READY_FOR_WORKPAPER
    if "status_bookkeeper" in fields_to_update and user_role == "bookkeeper":
        new_status = fields_to_update["status_bookkeeper"]
        if new_status == TransactionStatus.LOCKED.value:
            raise PermissionError("Bookkeeper cannot set status to LOCKED directly")


def check_unlock_permission(user_role: str, comment: Optional[str]) -> None:
    """Check if user can unlock a transaction"""
    if user_role != "admin":
        raise PermissionError("Only admin can unlock transactions")
    
    if not comment or len(comment.strip()) < 10:
        raise LockingError("Unlock requires a comment (minimum 10 characters)")


# ==================== REPOSITORY CLASS ====================

class TransactionRepository:
    """Repository for transaction database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    # ==================== CREATE ====================
    
    async def create(
        self,
        data: TransactionCreate,
        user_id: Optional[str] = None,
        user_role: str = "system"
    ) -> Transaction:
        """Create a new transaction"""
        
        db_txn = TransactionDB(
            client_id=data.client_id,
            date=_parse_date(data.date),
            amount=Decimal(str(data.amount)),
            payee_raw=data.payee_raw,
            description_raw=data.description_raw,
            source=TransactionSource(data.source),
            category_client=data.category_client,
            module_hint_client=data.module_hint_client,
            notes_client=data.notes_client,
            status_bookkeeper=TransactionStatus.NEW,
        )
        
        self.session.add(db_txn)
        await self.session.flush()
        
        # Write history entry
        history = TransactionHistoryDB(
            transaction_id=db_txn.id,
            user_id=user_id,
            role=user_role,
            action_type=HistoryActionType.IMPORT if data.source != TransactionSource.MANUAL.value else HistoryActionType.MANUAL,
            before=None,
            after=_get_snapshot_fields(db_txn),
        )
        self.session.add(history)
        
        await self.session.commit()
        await self.session.refresh(db_txn)
        
        return _db_to_transaction(db_txn)
    
    # ==================== READ ====================
    
    async def get(self, transaction_id: str) -> Optional[Transaction]:
        """Get transaction by ID"""
        result = await self.session.execute(
            select(TransactionDB).where(TransactionDB.id == transaction_id)
        )
        db_txn = result.scalar_one_or_none()
        
        if not db_txn:
            return None
        
        # Get attachment count
        count_result = await self.session.execute(
            select(func.count(TransactionAttachmentDB.id))
            .where(TransactionAttachmentDB.transaction_id == transaction_id)
        )
        attachment_count = count_result.scalar() or 0
        
        return _db_to_transaction(db_txn, attachment_count)
    
    async def get_db(self, transaction_id: str) -> Optional[TransactionDB]:
        """Get raw database object"""
        result = await self.session.execute(
            select(TransactionDB).where(TransactionDB.id == transaction_id)
        )
        return result.scalar_one_or_none()
    
    async def list_transactions(
        self,
        filters: TransactionFilter,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> PaginatedResult:
        """List transactions with filters and cursor-based pagination"""
        
        query = select(TransactionDB)
        count_query = select(func.count(TransactionDB.id))
        
        # Build filter conditions
        conditions = []
        
        if filters.client_id:
            conditions.append(TransactionDB.client_id == filters.client_id)
        
        if filters.date_from:
            conditions.append(TransactionDB.date >= _parse_date(filters.date_from))
        
        if filters.date_to:
            conditions.append(TransactionDB.date <= _parse_date(filters.date_to))
        
        if filters.status:
            conditions.append(TransactionDB.status_bookkeeper == TransactionStatus(filters.status))
        
        if filters.category:
            conditions.append(TransactionDB.category_bookkeeper == filters.category)
        
        if filters.source:
            conditions.append(TransactionDB.source == TransactionSource(filters.source))
        
        if filters.module_routing:
            conditions.append(TransactionDB.module_routing == ModuleRouting(filters.module_routing))
        
        if filters.is_duplicate is not None:
            conditions.append(TransactionDB.is_duplicate == filters.is_duplicate)
        
        if filters.is_late_receipt is not None:
            conditions.append(TransactionDB.is_late_receipt == filters.is_late_receipt)
        
        # Flag filtering
        if filters.flags:
            for flag in filters.flags:
                conditions.append(
                    TransactionDB.flags[flag].astext.cast(Boolean) == True
                )
        
        # Attachment filter
        if filters.has_attachment is not None:
            subq = select(TransactionAttachmentDB.transaction_id).distinct()
            if filters.has_attachment:
                conditions.append(TransactionDB.id.in_(subq))
            else:
                conditions.append(~TransactionDB.id.in_(subq))
        
        # Search (payee, description, notes)
        if filters.search:
            search_term = f"%{filters.search}%"
            conditions.append(
                or_(
                    TransactionDB.payee_raw.ilike(search_term),
                    TransactionDB.description_raw.ilike(search_term),
                    TransactionDB.notes_client.ilike(search_term),
                    TransactionDB.notes_bookkeeper.ilike(search_term),
                )
            )
        
        # Apply conditions
        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))
        
        # Get total count
        total_result = await self.session.execute(count_query)
        total = total_result.scalar() or 0
        
        # Cursor-based pagination (using created_at + id)
        if cursor:
            # Cursor format: "created_at|id"
            cursor_parts = cursor.split("|")
            if len(cursor_parts) == 2:
                cursor_time = datetime.fromisoformat(cursor_parts[0])
                cursor_id = cursor_parts[1]
                query = query.where(
                    or_(
                        TransactionDB.created_at < cursor_time,
                        and_(
                            TransactionDB.created_at == cursor_time,
                            TransactionDB.id < cursor_id
                        )
                    )
                )
        
        # Order and limit
        query = query.order_by(
            TransactionDB.date.desc(),
            TransactionDB.created_at.desc(),
            TransactionDB.id.desc()
        ).limit(limit + 1)  # +1 to check if there are more
        
        result = await self.session.execute(query)
        db_items = result.scalars().all()
        
        # Check if there are more results
        has_more = len(db_items) > limit
        if has_more:
            db_items = db_items[:limit]
        
        # Get attachment counts
        if db_items:
            ids = [t.id for t in db_items]
            att_result = await self.session.execute(
                select(
                    TransactionAttachmentDB.transaction_id,
                    func.count(TransactionAttachmentDB.id).label("count")
                )
                .where(TransactionAttachmentDB.transaction_id.in_(ids))
                .group_by(TransactionAttachmentDB.transaction_id)
            )
            att_counts = {row[0]: row[1] for row in att_result}
        else:
            att_counts = {}
        
        # Build response
        items = [
            _db_to_transaction(t, att_counts.get(t.id, 0))
            for t in db_items
        ]
        
        # Generate next cursor
        next_cursor = None
        if has_more and db_items:
            last = db_items[-1]
            next_cursor = f"{last.created_at.isoformat()}|{last.id}"
        
        return PaginatedResult(
            items=items,
            total=total,
            cursor=next_cursor,
            has_more=has_more,
        )
    
    # ==================== UPDATE ====================
    
    async def update(
        self,
        transaction_id: str,
        data: TransactionUpdate,
        user_id: str,
        user_role: str,
    ) -> Transaction:
        """Update a transaction with history tracking"""
        
        # Get current state
        db_txn = await self.get_db(transaction_id)
        if not db_txn:
            raise ValueError("Transaction not found")
        
        # Prepare updates
        updates = data.model_dump(exclude_none=True)
        if not updates:
            return await self.get(transaction_id)
        
        # Permission check
        check_bookkeeper_edit_permission(db_txn, user_role, updates)
        
        # Get before state
        before = _get_snapshot_fields(db_txn)
        
        # Apply updates
        if "date" in updates:
            db_txn.date = _parse_date(updates["date"])
        if "amount" in updates:
            db_txn.amount = Decimal(str(updates["amount"]))
        if "payee_raw" in updates:
            db_txn.payee_raw = updates["payee_raw"]
        if "description_raw" in updates:
            db_txn.description_raw = updates["description_raw"]
        if "category_bookkeeper" in updates:
            db_txn.category_bookkeeper = updates["category_bookkeeper"]
        if "gst_code_bookkeeper" in updates:
            db_txn.gst_code_bookkeeper = GSTCode(updates["gst_code_bookkeeper"]) if updates["gst_code_bookkeeper"] else None
        if "notes_bookkeeper" in updates:
            db_txn.notes_bookkeeper = updates["notes_bookkeeper"]
        if "status_bookkeeper" in updates:
            db_txn.status_bookkeeper = TransactionStatus(updates["status_bookkeeper"])
        if "flags" in updates:
            db_txn.flags = updates["flags"]
            # Update convenience fields
            db_txn.is_duplicate = updates["flags"].get("duplicate", False)
            db_txn.is_late_receipt = updates["flags"].get("late", False)
        if "module_routing" in updates:
            db_txn.module_routing = ModuleRouting(updates["module_routing"]) if updates["module_routing"] else None
        
        db_txn.updated_at = datetime.now(timezone.utc)
        
        # Get after state
        after = _get_snapshot_fields(db_txn)
        
        # Write history
        history = TransactionHistoryDB(
            transaction_id=transaction_id,
            user_id=user_id,
            role=user_role,
            action_type=HistoryActionType.MANUAL,
            before=before,
            after=after,
        )
        self.session.add(history)
        
        await self.session.commit()
        await self.session.refresh(db_txn)
        
        return await self.get(transaction_id)
    
    # ==================== BULK UPDATE ====================
    
    async def bulk_update(
        self,
        criteria: Dict[str, Any],
        updates: Dict[str, Any],
        user_id: str,
        user_role: str,
    ) -> int:
        """
        Atomic bulk update with single history entry.
        
        Returns count of updated rows.
        """
        # Build filter conditions from criteria
        conditions = []
        
        if "client_id" in criteria:
            conditions.append(TransactionDB.client_id == criteria["client_id"])
        if "status" in criteria:
            conditions.append(TransactionDB.status_bookkeeper == TransactionStatus(criteria["status"]))
        if "category" in criteria:
            conditions.append(TransactionDB.category_bookkeeper == criteria["category"])
        if "transaction_ids" in criteria:
            conditions.append(TransactionDB.id.in_(criteria["transaction_ids"]))
        if "date_from" in criteria:
            conditions.append(TransactionDB.date >= _parse_date(criteria["date_from"]))
        if "date_to" in criteria:
            conditions.append(TransactionDB.date <= _parse_date(criteria["date_to"]))
        
        if not conditions:
            raise ValueError("Bulk update requires at least one filter criterion")
        
        # Get affected transactions (for history)
        query = select(TransactionDB).where(and_(*conditions))
        
        # Exclude locked transactions for non-admin
        if user_role != "admin":
            query = query.where(TransactionDB.status_bookkeeper != TransactionStatus.LOCKED)
        
        result = await self.session.execute(query)
        affected = result.scalars().all()
        
        if not affected:
            return 0
        
        # Record before states
        before_states = [_get_snapshot_fields(t) for t in affected]
        
        # Prepare update values
        update_values = {"updated_at": datetime.now(timezone.utc)}
        
        if "category_bookkeeper" in updates:
            update_values["category_bookkeeper"] = updates["category_bookkeeper"]
        if "gst_code_bookkeeper" in updates:
            update_values["gst_code_bookkeeper"] = GSTCode(updates["gst_code_bookkeeper"]) if updates["gst_code_bookkeeper"] else None
        if "status_bookkeeper" in updates:
            update_values["status_bookkeeper"] = TransactionStatus(updates["status_bookkeeper"])
        if "module_routing" in updates:
            update_values["module_routing"] = ModuleRouting(updates["module_routing"]) if updates["module_routing"] else None
        if "flags" in updates:
            update_values["flags"] = updates["flags"]
        
        # Apply bulk update
        affected_ids = [t.id for t in affected]
        await self.session.execute(
            update(TransactionDB)
            .where(TransactionDB.id.in_(affected_ids))
            .values(**update_values)
        )
        
        # Re-fetch to get after states
        result = await self.session.execute(
            select(TransactionDB).where(TransactionDB.id.in_(affected_ids))
        )
        updated = result.scalars().all()
        after_states = [_get_snapshot_fields(t) for t in updated]
        
        # Write single history entry for bulk operation
        history = TransactionHistoryDB(
            transaction_id=affected_ids[0],  # Primary reference
            user_id=user_id,
            role=user_role,
            action_type=HistoryActionType.BULK_RECODE,
            before={"count": len(before_states), "transactions": before_states},
            after={"count": len(after_states), "transactions": after_states, "updates": updates},
            comment=f"Bulk update of {len(affected_ids)} transactions",
        )
        self.session.add(history)
        
        await self.session.commit()
        
        return len(affected_ids)
    
    # ==================== HISTORY ====================
    
    async def get_history(self, transaction_id: str) -> List[TransactionHistory]:
        """Get full audit trail for a transaction"""
        result = await self.session.execute(
            select(TransactionHistoryDB)
            .where(TransactionHistoryDB.transaction_id == transaction_id)
            .order_by(TransactionHistoryDB.timestamp.desc())
        )
        
        return [
            TransactionHistory(
                id=h.id,
                transaction_id=h.transaction_id,
                user_id=h.user_id,
                role=h.role,
                action_type=h.action_type.value,
                before=h.before,
                after=h.after,
                timestamp=_format_datetime(h.timestamp),
                comment=h.comment,
            )
            for h in result.scalars().all()
        ]
    
    # ==================== LOCKING ====================
    
    async def lock_for_workpaper(
        self,
        request: WorkpaperLockRequest,
        user_id: str,
        user_role: str,
    ) -> int:
        """
        Lock transactions for workpaper with snapshot.
        
        Actions:
        1. Snapshot bookkeeper fields
        2. Insert into transaction_workpaper_links
        3. Set status = LOCKED
        4. Write history event
        """
        # Get transactions
        result = await self.session.execute(
            select(TransactionDB).where(TransactionDB.id.in_(request.transaction_ids))
        )
        transactions = result.scalars().all()
        
        if not transactions:
            return 0
        
        locked_count = 0
        
        for txn in transactions:
            # Skip if already locked
            if txn.status_bookkeeper == TransactionStatus.LOCKED:
                continue
            
            # Get snapshot
            snapshot = _get_snapshot_fields(txn)
            
            # Create workpaper link
            link = TransactionWorkpaperLinkDB(
                transaction_id=txn.id,
                workpaper_id=request.workpaper_id,
                module=ModuleRouting(request.module),
                period=request.period,
                snapshot=snapshot,
            )
            self.session.add(link)
            
            # Get before state
            before = _get_snapshot_fields(txn)
            
            # Lock transaction
            txn.status_bookkeeper = TransactionStatus.LOCKED
            txn.locked_at = datetime.now(timezone.utc)
            txn.locked_by_role = user_role
            txn.updated_at = datetime.now(timezone.utc)
            
            # Get after state
            after = _get_snapshot_fields(txn)
            
            # Write history
            history = TransactionHistoryDB(
                transaction_id=txn.id,
                user_id=user_id,
                role=user_role,
                action_type=HistoryActionType.LOCK,
                before=before,
                after=after,
                comment=f"Locked for workpaper {request.workpaper_id}, module {request.module}, period {request.period}",
            )
            self.session.add(history)
            
            locked_count += 1
        
        await self.session.commit()
        
        return locked_count
    
    async def unlock(
        self,
        transaction_id: str,
        user_id: str,
        user_role: str,
        comment: str,
    ) -> Transaction:
        """
        Admin unlock of a transaction.
        
        Requires comment.
        Status returns to REVIEWED.
        """
        # Permission check
        check_unlock_permission(user_role, comment)
        
        # Get transaction
        db_txn = await self.get_db(transaction_id)
        if not db_txn:
            raise ValueError("Transaction not found")
        
        if db_txn.status_bookkeeper != TransactionStatus.LOCKED:
            raise LockingError("Transaction is not locked")
        
        # Get before state
        before = _get_snapshot_fields(db_txn)
        
        # Unlock
        db_txn.status_bookkeeper = TransactionStatus.REVIEWED
        db_txn.locked_at = None
        db_txn.locked_by_role = None
        db_txn.updated_at = datetime.now(timezone.utc)
        
        # Get after state
        after = _get_snapshot_fields(db_txn)
        
        # Write history
        history = TransactionHistoryDB(
            transaction_id=transaction_id,
            user_id=user_id,
            role=user_role,
            action_type=HistoryActionType.UNLOCK,
            before=before,
            after=after,
            comment=comment,
        )
        self.session.add(history)
        
        await self.session.commit()
        await self.session.refresh(db_txn)
        
        return await self.get(transaction_id)


# ==================== MYFDC SYNC SERVICE ====================

class MyFDCSyncService:
    """
    Service for MyFDC → FDC Core synchronization.
    
    Rules:
    - On create: Insert with source=MYFDC, status=NEW
    - On edit:
      - If status = NEW or PENDING → update client fields
      - If status ≥ REVIEWED → do not overwrite bookkeeper fields
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = TransactionRepository(session)
    
    async def sync_create(
        self,
        client_id: str,
        data: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Transaction:
        """Create a transaction from MyFDC"""
        
        create_data = TransactionCreate(
            client_id=client_id,
            date=data.get("date"),
            amount=data.get("amount", 0),
            payee_raw=data.get("payee"),
            description_raw=data.get("description"),
            source=TransactionSource.MYFDC.value,
            category_client=data.get("category"),
            module_hint_client=data.get("module_hint"),
            notes_client=data.get("notes"),
        )
        
        # Create with MYFDC_CREATE action
        db_txn = TransactionDB(
            client_id=client_id,
            date=_parse_date(create_data.date),
            amount=Decimal(str(create_data.amount)),
            payee_raw=create_data.payee_raw,
            description_raw=create_data.description_raw,
            source=TransactionSource.MYFDC,
            category_client=create_data.category_client,
            module_hint_client=create_data.module_hint_client,
            notes_client=create_data.notes_client,
            status_bookkeeper=TransactionStatus.NEW,
        )
        
        self.session.add(db_txn)
        await self.session.flush()
        
        # Write history
        history = TransactionHistoryDB(
            transaction_id=db_txn.id,
            user_id=user_id,
            role="client",
            action_type=HistoryActionType.MYFDC_CREATE,
            before=None,
            after=_get_snapshot_fields(db_txn),
        )
        self.session.add(history)
        
        await self.session.commit()
        await self.session.refresh(db_txn)
        
        return _db_to_transaction(db_txn)
    
    async def sync_update(
        self,
        transaction_id: str,
        data: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Tuple[Transaction, bool]:
        """
        Update a transaction from MyFDC.
        
        Returns (transaction, was_updated).
        If status >= REVIEWED, client fields are NOT overwritten.
        """
        db_txn = await self.repo.get_db(transaction_id)
        if not db_txn:
            raise ValueError("Transaction not found")
        
        status = db_txn.status_bookkeeper
        status_level = STATUS_HIERARCHY.get(status, 0)
        
        # Check if we can update client fields
        if status_level >= STATUS_HIERARCHY[TransactionStatus.REVIEWED]:
            # Do not overwrite - just log that client attempted update
            history = TransactionHistoryDB(
                transaction_id=transaction_id,
                user_id=user_id,
                role="client",
                action_type=HistoryActionType.MYFDC_UPDATE,
                before=None,
                after=None,
                comment=f"Client update rejected - transaction status is {status.value}",
            )
            self.session.add(history)
            await self.session.commit()
            
            return await self.repo.get(transaction_id), False
        
        # Update client fields
        before = _get_snapshot_fields(db_txn)
        
        if "date" in data:
            db_txn.date = _parse_date(data["date"])
        if "amount" in data:
            db_txn.amount = Decimal(str(data["amount"]))
        if "payee" in data:
            db_txn.payee_raw = data["payee"]
        if "description" in data:
            db_txn.description_raw = data["description"]
        if "category" in data:
            db_txn.category_client = data["category"]
        if "module_hint" in data:
            db_txn.module_hint_client = data["module_hint"]
        if "notes" in data:
            db_txn.notes_client = data["notes"]
        
        db_txn.updated_at = datetime.now(timezone.utc)
        
        after = _get_snapshot_fields(db_txn)
        
        # Write history
        history = TransactionHistoryDB(
            transaction_id=transaction_id,
            user_id=user_id,
            role="client",
            action_type=HistoryActionType.MYFDC_UPDATE,
            before=before,
            after=after,
            comment="Client updated submission",
        )
        self.session.add(history)
        
        await self.session.commit()
        await self.session.refresh(db_txn)
        
        return _db_to_transaction(db_txn), True


# ==================== BANK/OCR IMPORT SERVICE ====================

class ImportService:
    """Service for Bank/OCR import handling"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = TransactionRepository(session)
    
    async def import_bank_transaction(
        self,
        client_id: str,
        data: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Transaction:
        """Import a bank transaction"""
        return await self._import_transaction(
            client_id=client_id,
            data=data,
            source=TransactionSource.BANK,
            user_id=user_id,
        )
    
    async def import_ocr_transaction(
        self,
        client_id: str,
        data: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Transaction:
        """Import an OCR-scanned transaction"""
        return await self._import_transaction(
            client_id=client_id,
            data=data,
            source=TransactionSource.OCR,
            user_id=user_id,
        )
    
    async def _import_transaction(
        self,
        client_id: str,
        data: Dict[str, Any],
        source: TransactionSource,
        user_id: Optional[str] = None,
    ) -> Transaction:
        """Internal import method"""
        
        db_txn = TransactionDB(
            client_id=client_id,
            date=_parse_date(data.get("date")),
            amount=Decimal(str(data.get("amount", 0))),
            payee_raw=data.get("payee"),
            description_raw=data.get("description"),
            source=source,
            status_bookkeeper=TransactionStatus.NEW,
        )
        
        self.session.add(db_txn)
        await self.session.flush()
        
        # Write history
        history = TransactionHistoryDB(
            transaction_id=db_txn.id,
            user_id=user_id,
            role="system",
            action_type=HistoryActionType.IMPORT,
            before=None,
            after=_get_snapshot_fields(db_txn),
            comment=f"Imported from {source.value}",
        )
        self.session.add(history)
        
        await self.session.commit()
        await self.session.refresh(db_txn)
        
        return _db_to_transaction(db_txn)
    
    async def bulk_import(
        self,
        client_id: str,
        transactions: List[Dict[str, Any]],
        source: TransactionSource,
        user_id: Optional[str] = None,
    ) -> int:
        """Bulk import transactions"""
        count = 0
        
        for data in transactions:
            await self._import_transaction(
                client_id=client_id,
                data=data,
                source=source,
                user_id=user_id,
            )
            count += 1
        
        return count
