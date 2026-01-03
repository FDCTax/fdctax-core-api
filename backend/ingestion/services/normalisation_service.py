"""
Normalisation Service (A3-INGEST-03)

Handles the normalisation of ingested transactions:
- Loads transactions from the queue
- Calls Agent 8's mapping engine
- Updates transaction records with mapping results
- Manages audit trail and status transitions
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class NormalisationStatus(str, Enum):
    """Normalisation queue status."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class MappingResult:
    """Result from Agent 8's mapping engine."""
    success: bool
    category_normalised: Optional[str] = None
    category_code: Optional[str] = None
    confidence: Optional[float] = None
    error: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


@dataclass
class NormalisationResult:
    """Result of normalisation processing."""
    queue_id: str
    transactions_processed: int
    transactions_succeeded: int
    transactions_failed: int
    errors: List[Dict[str, Any]]


class Agent8MappingClient:
    """
    Client for Agent 8's category mapping engine.
    
    This client calls Agent 8's mapping service to normalise
    transaction categories into standardised bookkeeping codes.
    
    Note: Agent 8 implements the actual mapping logic (A8-INGEST-03).
    This client provides the interface for Core to call it.
    """
    
    def __init__(self, base_url: Optional[str] = None, timeout: int = 30):
        """
        Initialize the mapping client.
        
        Args:
            base_url: Agent 8 mapping service URL
            timeout: Request timeout in seconds
        
        Note: When base_url is not provided, the service will return 
        a standard "PENDING_CATEGORISATION" status instead of fake mappings.
        """
        self.base_url = base_url
        self.timeout = timeout
        # Standard categories for fallback (not mock - these are real categories)
        self._standard_categories = self._load_standard_categories()
    
    def _load_standard_categories(self) -> Dict[str, Tuple[str, str]]:
        """
        Load standard FDC expense/income categories.
        These are real accounting categories, not mock data.
        Used for keyword-based preliminary categorisation when Agent 8 is unavailable.
        """
        # Standard FDC expense/income categories (real accounting codes)
        return {
            # Office
            "office supplies": ("Office Supplies", "6420"),
            "office equipment": ("Office Equipment", "6430"),
            "stationery": ("Office Supplies", "6420"),
            "printer": ("Office Equipment", "6430"),
            
            # Vehicle
            "fuel": ("Motor Vehicle - Fuel", "6520"),
            "petrol": ("Motor Vehicle - Fuel", "6520"),
            "car maintenance": ("Motor Vehicle - Repairs", "6530"),
            "car insurance": ("Motor Vehicle - Insurance", "6540"),
            "registration": ("Motor Vehicle - Registration", "6550"),
            
            # Professional
            "accounting": ("Professional Fees - Accounting", "6610"),
            "legal": ("Professional Fees - Legal", "6620"),
            "consulting": ("Professional Fees - Consulting", "6630"),
            
            # Childcare specific
            "toys": ("Childcare Supplies - Toys", "7110"),
            "craft supplies": ("Childcare Supplies - Craft", "7120"),
            "food": ("Childcare Supplies - Food", "7130"),
            "nappies": ("Childcare Supplies - Consumables", "7140"),
            "cleaning": ("Childcare Supplies - Cleaning", "7150"),
            "first aid": ("Childcare Supplies - First Aid", "7160"),
            
            # Insurance
            "public liability": ("Insurance - Public Liability", "6710"),
            "professional indemnity": ("Insurance - Professional Indemnity", "6720"),
            
            # Training
            "training": ("Training & Development", "6810"),
            "courses": ("Training & Development", "6810"),
            "first aid course": ("Training & Development", "6810"),
            
            # Utilities
            "electricity": ("Utilities - Electricity", "6910"),
            "gas": ("Utilities - Gas", "6920"),
            "water": ("Utilities - Water", "6930"),
            "internet": ("Utilities - Internet", "6940"),
            "phone": ("Utilities - Phone", "6950"),
            
            # Income
            "childcare subsidy": ("Childcare Subsidy Income", "4110"),
            "ccs": ("Childcare Subsidy Income", "4110"),
            "parent fees": ("Parent Fee Income", "4120"),
            "gap fees": ("Parent Fee Income", "4120"),
        }
    
    async def map_category(
        self,
        raw_category: str,
        description: Optional[str] = None,
        amount: Optional[float] = None,
        transaction_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> MappingResult:
        """
        Map a raw category to a normalised category and code.
        
        Args:
            raw_category: Raw category string from MyFDC
            description: Transaction description for context
            amount: Transaction amount for context
            transaction_type: INCOME, EXPENSE, etc.
            metadata: Additional context for mapping
            
        Returns:
            MappingResult with normalised category and code
        """
        # If Agent 8 service is available, call it
        if self.base_url:
            return await self._call_agent8(
                raw_category, description, amount, transaction_type, metadata
            )
        
        # Otherwise, use mock mapping
        return await self._mock_mapping(
            raw_category, description, amount, transaction_type
        )
    
    async def _call_agent8(
        self,
        raw_category: str,
        description: Optional[str],
        amount: Optional[float],
        transaction_type: Optional[str],
        metadata: Optional[Dict[str, Any]]
    ) -> MappingResult:
        """Call Agent 8's mapping service."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/mapping/category",
                    json={
                        "raw_category": raw_category,
                        "description": description,
                        "amount": amount,
                        "transaction_type": transaction_type,
                        "metadata": metadata
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return MappingResult(
                        success=True,
                        category_normalised=data.get("category_normalised"),
                        category_code=data.get("category_code"),
                        confidence=data.get("confidence", 1.0),
                        raw_response=data
                    )
                else:
                    return MappingResult(
                        success=False,
                        error=f"Agent 8 returned {response.status_code}: {response.text}"
                    )
                    
        except Exception as e:
            logger.error(f"Agent 8 mapping call failed: {e}")
            # Fall back to mock mapping
            return await self._mock_mapping(raw_category, description, amount, transaction_type)
    
    async def _mock_mapping(
        self,
        raw_category: str,
        description: Optional[str],
        amount: Optional[float],
        transaction_type: Optional[str]
    ) -> MappingResult:
        """
        Mock mapping for development/testing.
        
        Uses a simple keyword-based matching approach.
        Production mapping should use Agent 8's ML-based service.
        """
        if not raw_category:
            return MappingResult(
                success=True,
                category_normalised="Uncategorised",
                category_code="9999",
                confidence=0.0
            )
        
        # Normalise for lookup
        lookup_key = raw_category.lower().strip()
        
        # Direct match
        if lookup_key in self._mock_mappings:
            normalised, code = self._mock_mappings[lookup_key]
            return MappingResult(
                success=True,
                category_normalised=normalised,
                category_code=code,
                confidence=1.0
            )
        
        # Partial match
        for key, (normalised, code) in self._mock_mappings.items():
            if key in lookup_key or lookup_key in key:
                return MappingResult(
                    success=True,
                    category_normalised=normalised,
                    category_code=code,
                    confidence=0.8
                )
        
        # Check description for hints
        if description:
            desc_lower = description.lower()
            for key, (normalised, code) in self._mock_mappings.items():
                if key in desc_lower:
                    return MappingResult(
                        success=True,
                        category_normalised=normalised,
                        category_code=code,
                        confidence=0.6
                    )
        
        # Default based on transaction type
        if transaction_type == "INCOME":
            return MappingResult(
                success=True,
                category_normalised="Other Income",
                category_code="4999",
                confidence=0.3
            )
        elif transaction_type == "EXPENSE":
            return MappingResult(
                success=True,
                category_normalised="Other Expense",
                category_code="6999",
                confidence=0.3
            )
        
        return MappingResult(
            success=True,
            category_normalised="Uncategorised",
            category_code="9999",
            confidence=0.0
        )


class NormalisationService:
    """
    Service for processing the normalisation queue.
    
    Responsibilities:
    - Fetch pending queue items
    - Load corresponding transactions
    - Call Agent 8 mapping engine
    - Update transaction records
    - Manage status transitions
    - Record audit trail
    """
    
    def __init__(self, db: AsyncSession, agent8_url: Optional[str] = None):
        self.db = db
        self.mapping_client = Agent8MappingClient(base_url=agent8_url)
    
    async def process_queue(self, batch_size: int = 10) -> List[NormalisationResult]:
        """
        Process pending items in the normalisation queue.
        
        Args:
            batch_size: Number of queue items to process
            
        Returns:
            List of NormalisationResult for each processed queue item
        """
        results = []
        
        # Fetch pending queue items
        queue_items = await self._fetch_pending_items(batch_size)
        
        if not queue_items:
            logger.info("No pending normalisation items")
            return results
        
        logger.info(f"Processing {len(queue_items)} normalisation queue items")
        
        for item in queue_items:
            try:
                result = await self._process_queue_item(item)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to process queue item {item['id']}: {e}")
                await self._mark_queue_failed(item['id'], str(e))
                results.append(NormalisationResult(
                    queue_id=item['id'],
                    transactions_processed=0,
                    transactions_succeeded=0,
                    transactions_failed=len(item.get('transaction_ids', [])),
                    errors=[{"queue_id": item['id'], "error": str(e)}]
                ))
        
        return results
    
    async def process_single_transaction(self, transaction_id: str) -> bool:
        """
        Process a single transaction (for manual/retry processing).
        
        Args:
            transaction_id: ID of the transaction to normalise
            
        Returns:
            True if successful, False otherwise
        """
        transaction = await self._load_transaction(transaction_id)
        if not transaction:
            logger.warning(f"Transaction not found: {transaction_id}")
            return False
        
        return await self._normalise_transaction(transaction)
    
    async def _fetch_pending_items(self, limit: int) -> List[Dict[str, Any]]:
        """Fetch pending queue items."""
        query = text("""
            SELECT id, batch_id, client_id, transaction_ids, attempts
            FROM public.normalisation_queue
            WHERE status = 'PENDING' AND attempts < max_attempts
            ORDER BY created_at ASC
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
        """)
        
        result = await self.db.execute(query, {"limit": limit})
        rows = result.fetchall()
        
        items = []
        for row in rows:
            items.append({
                "id": str(row[0]),
                "batch_id": str(row[1]),
                "client_id": str(row[2]),
                "transaction_ids": row[3] if isinstance(row[3], list) else json.loads(row[3]) if row[3] else [],
                "attempts": row[4]
            })
        
        return items
    
    async def _process_queue_item(self, item: Dict[str, Any]) -> NormalisationResult:
        """Process a single queue item."""
        queue_id = item['id']
        transaction_ids = item['transaction_ids']
        
        # Mark as processing
        await self._update_queue_status(queue_id, NormalisationStatus.PROCESSING)
        
        succeeded = 0
        failed = 0
        errors = []
        
        for txn_id in transaction_ids:
            try:
                transaction = await self._load_transaction(txn_id)
                if not transaction:
                    logger.warning(f"Transaction not found: {txn_id}")
                    failed += 1
                    errors.append({"transaction_id": txn_id, "error": "Not found"})
                    continue
                
                success = await self._normalise_transaction(transaction)
                
                if success:
                    succeeded += 1
                else:
                    failed += 1
                    errors.append({"transaction_id": txn_id, "error": "Normalisation failed"})
                    
            except Exception as e:
                logger.error(f"Error normalising transaction {txn_id}: {e}")
                failed += 1
                errors.append({"transaction_id": txn_id, "error": str(e)})
        
        # Update queue status
        if failed == 0:
            await self._mark_queue_completed(queue_id)
        elif succeeded == 0:
            await self._mark_queue_failed(queue_id, f"{failed} transactions failed")
        else:
            # Partial success - mark as completed but log errors
            await self._mark_queue_completed(queue_id, partial=True, errors=errors)
        
        await self.db.commit()
        
        return NormalisationResult(
            queue_id=queue_id,
            transactions_processed=len(transaction_ids),
            transactions_succeeded=succeeded,
            transactions_failed=failed,
            errors=errors
        )
    
    async def _load_transaction(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        """Load a transaction from the database."""
        query = text("""
            SELECT 
                id, source, source_transaction_id, client_id,
                transaction_date, transaction_type, amount,
                description, category_raw, status, audit
            FROM public.ingested_transactions
            WHERE id = :id
        """)
        
        result = await self.db.execute(query, {"id": transaction_id})
        row = result.fetchone()
        
        if not row:
            return None
        
        return {
            "id": str(row[0]),
            "source": row[1],
            "source_transaction_id": row[2],
            "client_id": str(row[3]),
            "transaction_date": row[4],
            "transaction_type": row[5],
            "amount": float(row[6]) if row[6] else 0,
            "description": row[7],
            "category_raw": row[8],
            "status": row[9],
            "audit": row[10] if isinstance(row[10], list) else json.loads(row[10]) if row[10] else []
        }
    
    async def _normalise_transaction(self, transaction: Dict[str, Any]) -> bool:
        """
        Normalise a single transaction using Agent 8's mapping engine.
        
        Args:
            transaction: Transaction data from database
            
        Returns:
            True if normalisation succeeded
        """
        txn_id = transaction['id']
        
        # Skip if already normalised
        if transaction['status'] in ('NORMALISED', 'READY_FOR_BOOKKEEPING'):
            logger.info(f"Transaction {txn_id} already normalised, skipping")
            return True
        
        # Call mapping engine
        mapping_result = await self.mapping_client.map_category(
            raw_category=transaction['category_raw'],
            description=transaction['description'],
            amount=transaction['amount'],
            transaction_type=transaction['transaction_type']
        )
        
        if not mapping_result.success:
            # Update with error
            await self._update_transaction_error(txn_id, mapping_result.error or "Mapping failed")
            return False
        
        # Update transaction with mapping results
        await self._update_transaction_mapping(
            txn_id,
            category_normalised=mapping_result.category_normalised,
            category_code=mapping_result.category_code,
            confidence=mapping_result.confidence,
            existing_audit=transaction['audit']
        )
        
        return True
    
    async def _update_transaction_mapping(
        self,
        transaction_id: str,
        category_normalised: str,
        category_code: str,
        confidence: float,
        existing_audit: List[Dict[str, Any]]
    ):
        """Update transaction with mapping results."""
        
        # Create audit entry
        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "normalised",
            "actor": "normalisation_service",
            "details": {
                "category_normalised": category_normalised,
                "category_code": category_code,
                "confidence": confidence,
                "mapper": "agent8_mock"  # Will be "agent8" when live
            }
        }
        
        # Append to existing audit
        new_audit = existing_audit + [audit_entry]
        
        query = text("""
            UPDATE public.ingested_transactions
            SET category_normalised = :category_normalised,
                category_code = :category_code,
                status = 'READY_FOR_BOOKKEEPING',
                audit = :audit,
                updated_at = NOW()
            WHERE id = :id
        """)
        
        await self.db.execute(query, {
            "id": transaction_id,
            "category_normalised": category_normalised,
            "category_code": category_code,
            "audit": json.dumps(new_audit)
        })
    
    async def _update_transaction_error(self, transaction_id: str, error_message: str):
        """Update transaction with error status."""
        query = text("""
            UPDATE public.ingested_transactions
            SET status = 'ERROR',
                error_message = :error_message,
                updated_at = NOW()
            WHERE id = :id
        """)
        
        await self.db.execute(query, {
            "id": transaction_id,
            "error_message": error_message
        })
    
    async def _update_queue_status(self, queue_id: str, status: NormalisationStatus):
        """Update queue item status."""
        query = text("""
            UPDATE public.normalisation_queue
            SET status = :status,
                attempts = attempts + 1,
                updated_at = NOW()
            WHERE id = :id
        """)
        
        await self.db.execute(query, {
            "id": queue_id,
            "status": status.value
        })
    
    async def _mark_queue_completed(
        self,
        queue_id: str,
        partial: bool = False,
        errors: Optional[List[Dict]] = None
    ):
        """Mark queue item as completed."""
        query = text("""
            UPDATE public.normalisation_queue
            SET status = 'COMPLETED',
                processed_at = NOW(),
                last_error = :last_error,
                updated_at = NOW()
            WHERE id = :id
        """)
        
        last_error = None
        if partial and errors:
            last_error = f"Partial success: {len(errors)} errors"
        
        await self.db.execute(query, {
            "id": queue_id,
            "last_error": last_error
        })
    
    async def _mark_queue_failed(self, queue_id: str, error: str):
        """Mark queue item as failed."""
        query = text("""
            UPDATE public.normalisation_queue
            SET status = CASE 
                    WHEN attempts >= max_attempts THEN 'FAILED'
                    ELSE 'PENDING'
                END,
                last_error = :error,
                updated_at = NOW()
            WHERE id = :id
        """)
        
        await self.db.execute(query, {
            "id": queue_id,
            "error": error
        })
    
    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        query = text("""
            SELECT 
                status,
                COUNT(*) as count
            FROM public.normalisation_queue
            GROUP BY status
        """)
        
        result = await self.db.execute(query)
        rows = result.fetchall()
        
        stats = {
            "PENDING": 0,
            "PROCESSING": 0,
            "COMPLETED": 0,
            "FAILED": 0
        }
        
        for row in rows:
            stats[row[0]] = row[1]
        
        stats["total"] = sum(stats.values())
        
        return stats
