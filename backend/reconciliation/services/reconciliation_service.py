"""
Reconciliation Service (A3-RECON-01)

Core business logic for the reconciliation engine:
- Finding match candidates
- Auto-matching with high confidence
- Suggesting matches for review
- Confirming/rejecting matches
- Audit logging

The reconciliation engine recognizes MyFDC as a valid source
for matching against bank feeds and other financial data.
"""

import uuid
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from reconciliation.source_registry import (
    ReconciliationSource,
    TargetType,
    MatchStatus,
    MatchType,
    source_registry
)
from reconciliation.matching_rules.myfdc_rules import (
    MyFDCMatchingRules,
    MatchResult,
    MatchCandidate,
    myfdc_rules
)

logger = logging.getLogger(__name__)


@dataclass
class ReconciliationRunResult:
    """Result of a reconciliation run."""
    run_id: str
    client_id: str
    source_type: str
    total_transactions: int
    auto_matched: int
    suggested: int
    no_match: int
    matches: List[Dict[str, Any]]


class ReconciliationAuditEvent:
    """Audit event types for reconciliation operations."""
    RUN_STARTED = "reconciliation.run_started"
    RUN_COMPLETED = "reconciliation.run_completed"
    MATCH_CREATED = "reconciliation.match_created"
    MATCH_CONFIRMED = "reconciliation.match_confirmed"
    MATCH_REJECTED = "reconciliation.match_rejected"
    CANDIDATES_FOUND = "reconciliation.candidates_found"


def log_reconciliation_event(
    event_type: str,
    client_id: str,
    details: Dict[str, Any],
    match_id: Optional[str] = None,
    actor: str = "system"
):
    """Log reconciliation event for audit trail."""
    log_entry = {
        "event": event_type,
        "client_id": client_id,
        "match_id": match_id,
        "details": details,
        "actor": actor,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    logger.info(f"Reconciliation event: {event_type}", extra=log_entry)


class ReconciliationService:
    """
    Service for reconciling transactions from various sources.
    
    Primary use case: Match MyFDC transactions against bank feeds
    to verify expenses and income.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.myfdc_rules = myfdc_rules
    
    async def find_candidates(
        self,
        client_id: str,
        source_transaction_id: str,
        target_type: Optional[TargetType] = None
    ) -> MatchResult:
        """
        Find reconciliation candidates for a single source transaction.
        
        Args:
            client_id: Core client ID
            source_transaction_id: ID of the source transaction
            target_type: Optional filter for target type
            
        Returns:
            MatchResult with candidates and scoring
        """
        # Get the source transaction
        source_txn = await self._get_ingested_transaction(source_transaction_id)
        if not source_txn:
            raise ValueError(f"Source transaction {source_transaction_id} not found")
        
        if source_txn['client_id'] != client_id:
            raise ValueError(f"Transaction does not belong to client {client_id}")
        
        # Get target transactions (bank feeds, etc.)
        target_transactions = await self._get_target_transactions(
            client_id,
            source_txn,
            target_type
        )
        
        # Determine source type and use appropriate rules engine
        source_type = ReconciliationSource(source_txn.get('source', 'MYFDC'))
        
        if source_type == ReconciliationSource.MYFDC:
            result = self.myfdc_rules.find_matches(
                source_txn,
                target_transactions,
                target_type or TargetType.BANK
            )
        else:
            # Default to MYFDC rules for now
            result = self.myfdc_rules.find_matches(
                source_txn,
                target_transactions,
                target_type or TargetType.BANK
            )
        
        # Log the candidate search
        log_reconciliation_event(
            ReconciliationAuditEvent.CANDIDATES_FOUND,
            client_id,
            {
                "source_transaction_id": source_transaction_id,
                "candidates_count": len(result.candidates),
                "auto_matched": result.auto_matched,
                "suggested_match": result.suggested_match
            }
        )
        
        return result
    
    async def run_reconciliation(
        self,
        client_id: str,
        source_type: ReconciliationSource = ReconciliationSource.MYFDC,
        target_type: TargetType = TargetType.BANK,
        transaction_ids: Optional[List[str]] = None,
        auto_match: bool = True
    ) -> ReconciliationRunResult:
        """
        Run reconciliation for a client's transactions.
        
        Args:
            client_id: Core client ID
            source_type: Type of source transactions to reconcile
            target_type: Type of targets to match against
            transaction_ids: Optional list of specific transaction IDs
            auto_match: Whether to auto-match high confidence matches
            
        Returns:
            ReconciliationRunResult with match statistics
        """
        run_id = str(uuid.uuid4())
        
        # Log run start
        log_reconciliation_event(
            ReconciliationAuditEvent.RUN_STARTED,
            client_id,
            {
                "run_id": run_id,
                "source_type": source_type.value,
                "target_type": target_type.value,
                "auto_match": auto_match
            }
        )
        
        # Get source transactions to reconcile
        source_transactions = await self._get_unreconciled_transactions(
            client_id,
            source_type,
            transaction_ids
        )
        
        # Get target transactions
        all_targets = await self._get_all_target_transactions(client_id, target_type)
        
        # Process each transaction
        matches = []
        auto_matched_count = 0
        suggested_count = 0
        no_match_count = 0
        
        for source_txn in source_transactions:
            # Find candidates
            if source_type == ReconciliationSource.MYFDC:
                result = self.myfdc_rules.find_matches(
                    source_txn,
                    all_targets,
                    target_type
                )
            else:
                result = self.myfdc_rules.find_matches(
                    source_txn,
                    all_targets,
                    target_type
                )
            
            # Determine status
            if result.auto_matched and auto_match:
                status = MatchStatus.MATCHED
                auto_matched_count += 1
            elif result.suggested_match:
                status = MatchStatus.SUGGESTED
                suggested_count += 1
            else:
                status = MatchStatus.NO_MATCH
                no_match_count += 1
            
            # Store match result
            if result.best_match:
                match_id = await self._store_match(
                    client_id,
                    source_txn,
                    result.best_match,
                    source_type,
                    status,
                    result.auto_matched and auto_match
                )
                
                matches.append({
                    "match_id": match_id,
                    "source_transaction_id": source_txn['id'],
                    "target_id": result.best_match.target_id,
                    "confidence_score": result.best_match.confidence_score,
                    "status": status.value,
                    "auto_matched": result.auto_matched and auto_match
                })
            else:
                # Store no-match record
                match_id = await self._store_no_match(
                    client_id,
                    source_txn,
                    source_type,
                    result.candidates
                )
                
                matches.append({
                    "match_id": match_id,
                    "source_transaction_id": source_txn['id'],
                    "target_id": None,
                    "confidence_score": 0,
                    "status": status.value,
                    "auto_matched": False
                })
        
        # Commit all matches
        try:
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to commit reconciliation run: {e}")
            await self.db.rollback()
            raise
        
        # Log run completion
        log_reconciliation_event(
            ReconciliationAuditEvent.RUN_COMPLETED,
            client_id,
            {
                "run_id": run_id,
                "total": len(source_transactions),
                "auto_matched": auto_matched_count,
                "suggested": suggested_count,
                "no_match": no_match_count
            }
        )
        
        # Store audit log entry
        await self._store_audit_log(
            client_id,
            ReconciliationAuditEvent.RUN_COMPLETED,
            "system",
            {
                "run_id": run_id,
                "source_type": source_type.value,
                "target_type": target_type.value,
                "total_transactions": len(source_transactions),
                "auto_matched": auto_matched_count,
                "suggested": suggested_count,
                "no_match": no_match_count
            }
        )
        
        return ReconciliationRunResult(
            run_id=run_id,
            client_id=client_id,
            source_type=source_type.value,
            total_transactions=len(source_transactions),
            auto_matched=auto_matched_count,
            suggested=suggested_count,
            no_match=no_match_count,
            matches=matches
        )
    
    async def confirm_match(
        self,
        match_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """
        Confirm a suggested match.
        
        Args:
            match_id: ID of the match to confirm
            user_id: ID of the user confirming
            
        Returns:
            Updated match record
        """
        query = text("""
            UPDATE public.reconciliation_matches
            SET 
                match_status = 'CONFIRMED',
                user_confirmed = true,
                confirmed_by = :user_id,
                confirmed_at = NOW(),
                updated_at = NOW()
            WHERE id = :match_id
            RETURNING id, client_id, source_transaction_id, target_transaction_id, match_status
        """)
        
        result = await self.db.execute(query, {
            "match_id": match_id,
            "user_id": user_id
        })
        row = result.fetchone()
        
        if not row:
            raise ValueError(f"Match {match_id} not found")
        
        await self.db.commit()
        
        # Log confirmation
        log_reconciliation_event(
            ReconciliationAuditEvent.MATCH_CONFIRMED,
            str(row[1]),
            {
                "source_transaction_id": str(row[2]),
                "target_transaction_id": row[3]
            },
            match_id=match_id,
            actor=user_id
        )
        
        # Store audit log
        await self._store_audit_log(
            str(row[1]),
            ReconciliationAuditEvent.MATCH_CONFIRMED,
            user_id,
            {
                "source_transaction_id": str(row[2]),
                "target_transaction_id": row[3]
            },
            match_id=match_id
        )
        
        return {
            "match_id": str(row[0]),
            "client_id": str(row[1]),
            "source_transaction_id": str(row[2]),
            "target_transaction_id": row[3],
            "status": row[4]
        }
    
    async def reject_match(
        self,
        match_id: str,
        user_id: str,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Reject a suggested match.
        
        Args:
            match_id: ID of the match to reject
            user_id: ID of the user rejecting
            reason: Optional rejection reason
            
        Returns:
            Updated match record
        """
        # Get current scoring breakdown to append rejection reason
        get_query = text("""
            SELECT scoring_breakdown FROM public.reconciliation_matches
            WHERE id = :match_id
        """)
        current = await self.db.execute(get_query, {"match_id": match_id})
        current_row = current.fetchone()
        
        scoring_breakdown = current_row[0] if current_row and current_row[0] else {}
        if isinstance(scoring_breakdown, str):
            scoring_breakdown = json.loads(scoring_breakdown)
        scoring_breakdown['rejection_reason'] = reason
        
        query = text("""
            UPDATE public.reconciliation_matches
            SET 
                match_status = 'REJECTED',
                user_confirmed = false,
                confirmed_by = :user_id,
                confirmed_at = NOW(),
                scoring_breakdown = :scoring_breakdown,
                updated_at = NOW()
            WHERE id = :match_id
            RETURNING id, client_id, source_transaction_id, target_transaction_id, match_status
        """)
        
        result = await self.db.execute(query, {
            "match_id": match_id,
            "user_id": user_id,
            "scoring_breakdown": json.dumps(scoring_breakdown)
        })
        row = result.fetchone()
        
        if not row:
            raise ValueError(f"Match {match_id} not found")
        
        await self.db.commit()
        
        # Log rejection
        log_reconciliation_event(
            ReconciliationAuditEvent.MATCH_REJECTED,
            str(row[1]),
            {
                "source_transaction_id": str(row[2]),
                "target_transaction_id": row[3],
                "reason": reason
            },
            match_id=match_id,
            actor=user_id
        )
        
        # Store audit log
        await self._store_audit_log(
            str(row[1]),
            ReconciliationAuditEvent.MATCH_REJECTED,
            user_id,
            {
                "source_transaction_id": str(row[2]),
                "target_transaction_id": row[3],
                "reason": reason
            },
            match_id=match_id
        )
        
        return {
            "match_id": str(row[0]),
            "client_id": str(row[1]),
            "source_transaction_id": str(row[2]),
            "target_transaction_id": row[3],
            "status": row[4]
        }
    
    async def get_match(self, match_id: str) -> Optional[Dict[str, Any]]:
        """Get a single match by ID."""
        query = text("""
            SELECT 
                id, client_id, source_transaction_id, source_type,
                target_transaction_id, target_type, target_reference,
                match_status, confidence_score, match_type,
                scoring_breakdown, auto_matched, user_confirmed,
                confirmed_by, confirmed_at, created_at, updated_at
            FROM public.reconciliation_matches
            WHERE id = :match_id
        """)
        
        result = await self.db.execute(query, {"match_id": match_id})
        row = result.fetchone()
        
        if not row:
            return None
        
        return self._row_to_match_dict(row)
    
    async def get_matches_by_client(
        self,
        client_id: str,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get matches for a client with optional filters."""
        conditions = ["client_id = :client_id"]
        params = {"client_id": client_id, "limit": limit, "offset": offset}
        
        if status:
            conditions.append("match_status = :status")
            params["status"] = status
        
        if source_type:
            conditions.append("source_type = :source_type")
            params["source_type"] = source_type
        
        where_clause = " AND ".join(conditions)
        
        query = text(f"""
            SELECT 
                id, client_id, source_transaction_id, source_type,
                target_transaction_id, target_type, target_reference,
                match_status, confidence_score, match_type,
                scoring_breakdown, auto_matched, user_confirmed,
                confirmed_by, confirmed_at, created_at, updated_at
            FROM public.reconciliation_matches
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """)
        
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        return [self._row_to_match_dict(row) for row in rows]
    
    async def get_suggested_matches(
        self,
        client_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get pending suggested matches for review."""
        return await self.get_matches_by_client(
            client_id,
            status=MatchStatus.SUGGESTED.value,
            limit=limit
        )
    
    async def get_reconciliation_stats(self, client_id: str) -> Dict[str, Any]:
        """Get reconciliation statistics for a client."""
        query = text("""
            SELECT 
                match_status,
                COUNT(*) as count
            FROM public.reconciliation_matches
            WHERE client_id = :client_id
            GROUP BY match_status
        """)
        
        result = await self.db.execute(query, {"client_id": client_id})
        rows = result.fetchall()
        
        stats = {status.value: 0 for status in MatchStatus}
        for row in rows:
            stats[row[0]] = row[1]
        
        total = sum(stats.values())
        
        return {
            "client_id": client_id,
            "total_matches": total,
            "by_status": stats,
            "reconciliation_rate": round(
                (stats.get('MATCHED', 0) + stats.get('CONFIRMED', 0)) / total * 100, 2
            ) if total > 0 else 0
        }
    
    # ==================== Private Methods ====================
    
    async def _get_ingested_transaction(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        """Get a single ingested transaction by ID."""
        query = text("""
            SELECT 
                id, source, source_transaction_id, client_id,
                transaction_date, transaction_type, amount,
                gst_included, gst_amount, description, category_code,
                category_raw, category_normalised, vendor, receipt_number,
                attachments, status
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
            "transaction_date": row[4].isoformat() if row[4] else None,
            "transaction_type": row[5],
            "amount": str(row[6]) if row[6] else "0",
            "gst_included": row[7],
            "gst_amount": str(row[8]) if row[8] else None,
            "description": row[9],
            "category_code": row[10],
            "category_raw": row[11],
            "category_normalised": row[12],
            "vendor": row[13],
            "receipt_number": row[14],
            "attachments": row[15] if row[15] else [],
            "status": row[16]
        }
    
    async def _get_unreconciled_transactions(
        self,
        client_id: str,
        source_type: ReconciliationSource,
        transaction_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Get transactions that haven't been reconciled yet."""
        conditions = [
            "it.client_id = :client_id",
            "it.source = :source_type",
            "it.status = 'READY_FOR_BOOKKEEPING'"
        ]
        params = {
            "client_id": client_id,
            "source_type": source_type.value
        }
        
        if transaction_ids:
            conditions.append("it.id = ANY(:transaction_ids)")
            params["transaction_ids"] = transaction_ids
        
        where_clause = " AND ".join(conditions)
        
        # Exclude already matched transactions
        query = text(f"""
            SELECT 
                it.id, it.source, it.source_transaction_id, it.client_id,
                it.transaction_date, it.transaction_type, it.amount,
                it.gst_included, it.gst_amount, it.description, it.category_code,
                it.category_raw, it.category_normalised, it.vendor, it.receipt_number,
                it.attachments, it.status
            FROM public.ingested_transactions it
            LEFT JOIN public.reconciliation_matches rm 
                ON rm.source_transaction_id = it.id 
                AND rm.match_status IN ('MATCHED', 'CONFIRMED')
            WHERE {where_clause}
            AND rm.id IS NULL
            ORDER BY it.transaction_date DESC
            LIMIT 500
        """)
        
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        return [
            {
                "id": str(row[0]),
                "source": row[1],
                "source_transaction_id": row[2],
                "client_id": str(row[3]),
                "transaction_date": row[4].isoformat() if row[4] else None,
                "transaction_type": row[5],
                "amount": str(row[6]) if row[6] else "0",
                "gst_included": row[7],
                "gst_amount": str(row[8]) if row[8] else None,
                "description": row[9],
                "category_code": row[10],
                "category_raw": row[11],
                "category_normalised": row[12],
                "vendor": row[13],
                "receipt_number": row[14],
                "attachments": row[15] if row[15] else [],
                "status": row[16]
            }
            for row in rows
        ]
    
    async def _get_target_transactions(
        self,
        client_id: str,
        source_txn: Dict[str, Any],
        target_type: Optional[TargetType] = None
    ) -> List[Dict[str, Any]]:
        """
        Get potential target transactions for matching.
        
        For now, uses bank_transactions table as the primary target.
        Can be extended to support other target types.
        """
        # Get transactions from a reasonable date window
        txn_date = source_txn.get('transaction_date')
        
        # Use workpaper_transactions as bank feed source
        # TODO: Add dedicated bank_feed table when available
        query = text("""
            SELECT 
                id::text, 'BANK' as target_type,
                date as date, amount, description,
                category as category_code, NULL as memo,
                gst_amount, true as gst_included, NULL as attachments,
                reference as reference
            FROM public.workpaper_transactions
            WHERE client_id = :client_id
            AND date BETWEEN :start_date AND :end_date
            ORDER BY date DESC
            LIMIT 200
        """)
        
        # Date window: 14 days before and after
        from datetime import date, timedelta
        if isinstance(txn_date, str):
            txn_date = date.fromisoformat(txn_date)
        
        start_date = txn_date - timedelta(days=14) if txn_date else date.today() - timedelta(days=30)
        end_date = txn_date + timedelta(days=14) if txn_date else date.today()
        
        # Convert dates to ISO strings for asyncpg
        result = await self.db.execute(query, {
            "client_id": client_id,
            "start_date": str(start_date),
            "end_date": str(end_date)
        })
        rows = result.fetchall()
        
        return [
            {
                "id": str(row[0]),
                "target_type": row[1],
                "date": row[2].isoformat() if row[2] else None,
                "transaction_date": row[2].isoformat() if row[2] else None,
                "amount": str(row[3]) if row[3] else "0",
                "description": row[4],
                "category_code": row[5],
                "memo": row[6],
                "gst_amount": str(row[7]) if row[7] else None,
                "gst_included": row[8],
                "attachments": row[9] if row[9] else [],
                "reference": row[10]
            }
            for row in rows
        ]
    
    async def _get_all_target_transactions(
        self,
        client_id: str,
        target_type: TargetType
    ) -> List[Dict[str, Any]]:
        """Get all unmatched target transactions for a client."""
        query = text("""
            SELECT 
                wt.id::text, 'BANK' as target_type,
                wt.date as date, wt.amount, wt.description,
                wt.category as category_code, NULL as memo,
                wt.gst_amount, true as gst_included, NULL as attachments,
                wt.reference as reference
            FROM public.workpaper_transactions wt
            LEFT JOIN public.reconciliation_matches rm 
                ON rm.target_transaction_id = CAST(wt.id AS TEXT)
                AND rm.match_status IN ('MATCHED', 'CONFIRMED')
            WHERE wt.client_id = :client_id
            AND rm.id IS NULL
            ORDER BY wt.date DESC
            LIMIT 500
        """)
        
        result = await self.db.execute(query, {"client_id": client_id})
        rows = result.fetchall()
        
        return [
            {
                "id": str(row[0]),
                "target_type": row[1],
                "date": row[2].isoformat() if row[2] else None,
                "transaction_date": row[2].isoformat() if row[2] else None,
                "amount": str(row[3]) if row[3] else "0",
                "description": row[4],
                "category_code": row[5],
                "memo": row[6],
                "gst_amount": str(row[7]) if row[7] else None,
                "gst_included": row[8],
                "attachments": row[9] if row[9] else [],
                "reference": row[10]
            }
            for row in rows
        ]
    
    async def _store_match(
        self,
        client_id: str,
        source_txn: Dict[str, Any],
        match: MatchCandidate,
        source_type: ReconciliationSource,
        status: MatchStatus,
        auto_matched: bool
    ) -> str:
        """Store a reconciliation match in the database."""
        match_id = str(uuid.uuid4())
        
        query = text("""
            INSERT INTO public.reconciliation_matches (
                id, client_id, source_transaction_id, source_type,
                target_transaction_id, target_type, target_reference,
                match_status, confidence_score, match_type,
                scoring_breakdown, auto_matched, user_confirmed,
                created_at, updated_at
            ) VALUES (
                :id, :client_id, :source_txn_id, :source_type,
                :target_txn_id, :target_type, :target_reference,
                :status, :confidence_score, :match_type,
                :scoring_breakdown, :auto_matched, false,
                NOW(), NOW()
            )
            RETURNING id
        """)
        
        result = await self.db.execute(query, {
            "id": match_id,
            "client_id": client_id,
            "source_txn_id": source_txn['id'],
            "source_type": source_type.value,
            "target_txn_id": match.target_id,
            "target_type": match.target_type.value,
            "target_reference": match.target_reference,
            "status": status.value,
            "confidence_score": match.confidence_score,
            "match_type": match.match_type.value,
            "scoring_breakdown": json.dumps(match.scoring_breakdown),
            "auto_matched": auto_matched
        })
        
        row = result.fetchone()
        
        # Log match creation
        log_reconciliation_event(
            ReconciliationAuditEvent.MATCH_CREATED,
            client_id,
            {
                "source_transaction_id": source_txn['id'],
                "target_id": match.target_id,
                "confidence_score": match.confidence_score,
                "status": status.value,
                "auto_matched": auto_matched
            },
            match_id=match_id
        )
        
        return str(row[0]) if row else match_id
    
    async def _store_no_match(
        self,
        client_id: str,
        source_txn: Dict[str, Any],
        source_type: ReconciliationSource,
        candidates: List[MatchCandidate]
    ) -> str:
        """Store a no-match record for audit purposes."""
        match_id = str(uuid.uuid4())
        
        # Store summary of candidates that were considered
        candidates_summary = [
            {
                "target_id": c.target_id,
                "confidence_score": c.confidence_score,
                "match_type": c.match_type.value
            }
            for c in candidates[:5]  # Top 5 candidates
        ]
        
        query = text("""
            INSERT INTO public.reconciliation_matches (
                id, client_id, source_transaction_id, source_type,
                target_transaction_id, target_type, target_reference,
                match_status, confidence_score, match_type,
                scoring_breakdown, auto_matched, user_confirmed,
                created_at, updated_at
            ) VALUES (
                :id, :client_id, :source_txn_id, :source_type,
                NULL, 'UNKNOWN', NULL,
                'NO_MATCH', 0, NULL,
                :scoring_breakdown, false, false,
                NOW(), NOW()
            )
            RETURNING id
        """)
        
        result = await self.db.execute(query, {
            "id": match_id,
            "client_id": client_id,
            "source_txn_id": source_txn['id'],
            "source_type": source_type.value,
            "scoring_breakdown": json.dumps({
                "candidates_considered": len(candidates),
                "top_candidates": candidates_summary
            })
        })
        
        row = result.fetchone()
        return str(row[0]) if row else match_id
    
    async def _store_audit_log(
        self,
        client_id: str,
        action: str,
        actor: str,
        details: Dict[str, Any],
        match_id: Optional[str] = None,
        source_transaction_id: Optional[str] = None
    ):
        """Store an entry in the reconciliation audit log."""
        try:
            log_id = str(uuid.uuid4())
            
            query = text("""
                INSERT INTO public.reconciliation_audit_log (
                    id, client_id, match_id, action, actor,
                    source_transaction_id, source_type,
                    candidates_count, scoring_breakdown,
                    decision, confidence_score,
                    timestamp, metadata
                ) VALUES (
                    :id, :client_id, :match_id, :action, :actor,
                    :source_txn_id, :source_type,
                    :candidates_count, :scoring_breakdown,
                    :decision, :confidence_score,
                    NOW(), :metadata
                )
            """)
            
            await self.db.execute(query, {
                "id": log_id,
                "client_id": client_id,
                "match_id": match_id,
                "action": action,
                "actor": actor,
                "source_txn_id": details.get('source_transaction_id') or source_transaction_id,
                "source_type": details.get('source_type'),
                "candidates_count": details.get('candidates_count'),
                "scoring_breakdown": json.dumps(details) if details else None,
                "decision": details.get('status') or details.get('decision'),
                "confidence_score": details.get('confidence_score'),
                "metadata": json.dumps(details)
            })
            
            await self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to store audit log: {e}")
    
    def _row_to_match_dict(self, row) -> Dict[str, Any]:
        """Convert a database row to a match dictionary."""
        scoring_breakdown = row[10]
        if isinstance(scoring_breakdown, str):
            scoring_breakdown = json.loads(scoring_breakdown)
        
        return {
            "id": str(row[0]),
            "client_id": str(row[1]),
            "source_transaction_id": str(row[2]),
            "source_type": row[3],
            "target_transaction_id": row[4],
            "target_type": row[5],
            "target_reference": row[6],
            "match_status": row[7],
            "confidence_score": float(row[8]) if row[8] else 0,
            "match_type": row[9],
            "scoring_breakdown": scoring_breakdown,
            "auto_matched": row[11],
            "user_confirmed": row[12],
            "confirmed_by": row[13],
            "confirmed_at": row[14].isoformat() if row[14] else None,
            "created_at": row[15].isoformat() if row[15] else None,
            "updated_at": row[16].isoformat() if row[16] else None
        }
