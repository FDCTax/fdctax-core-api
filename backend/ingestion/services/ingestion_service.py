"""
Ingestion Service (A3-INGEST-02)

Handles the core ingestion logic:
- Storing IngestedTransaction records
- Managing batch operations
- Queuing normalisation tasks for Agent 8
- Audit trail management
"""

import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ingestion.unified_schema import (
    IngestedTransaction,
    IngestionSource,
    IngestionStatus,
    IngestBatchResponse,
    IngestTransactionResponse
)
from ingestion.factories.myfdc_transformer import MyFDCTransformer

logger = logging.getLogger(__name__)


@dataclass
class IngestionBatchResult:
    """Result of a batch ingestion operation."""
    batch_id: str
    client_id: str
    source: str
    total_count: int
    ingested_count: int
    error_count: int
    transactions: List[IngestTransactionResponse]
    errors: List[Dict[str, Any]]


class IngestionAuditEvent:
    """Audit event types for ingestion operations."""
    BATCH_STARTED = "ingestion.batch_started"
    BATCH_COMPLETED = "ingestion.batch_completed"
    TRANSACTION_INGESTED = "ingestion.transaction_ingested"
    TRANSACTION_ERROR = "ingestion.transaction_error"
    NORMALISATION_QUEUED = "ingestion.normalisation_queued"


def log_ingestion_event(
    event_type: str,
    batch_id: str,
    client_id: str,
    details: Dict[str, Any],
    success: bool = True
):
    """Log ingestion event for audit trail."""
    log_entry = {
        "event": event_type,
        "batch_id": batch_id,
        "client_id": client_id,
        "details": details,
        "success": success,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    if success:
        logger.info(f"Ingestion event: {event_type} for batch {batch_id}", extra=log_entry)
    else:
        logger.warning(f"Ingestion event FAILED: {event_type} for batch {batch_id}", extra=log_entry)


class IngestionService:
    """
    Service for ingesting transactions into Core.
    
    Handles:
    - Single and batch ingestion
    - Database persistence
    - Normalisation queue management
    - Audit trail
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def ingest_myfdc_batch(
        self,
        client_id: str,
        payloads: List[Dict[str, Any]],
        user_id: str,
        user_email: Optional[str] = None
    ) -> IngestionBatchResult:
        """
        Ingest a batch of MyFDC transactions.
        
        Args:
            client_id: Core client ID
            payloads: List of raw MyFDC transaction payloads
            user_id: User performing the ingestion
            user_email: User's email for audit
            
        Returns:
            IngestionBatchResult with details of the operation
        """
        batch_id = str(uuid.uuid4())
        actor = f"user:{user_id}"
        
        # Log batch start
        log_ingestion_event(
            IngestionAuditEvent.BATCH_STARTED,
            batch_id,
            client_id,
            {"count": len(payloads), "user_id": user_id}
        )
        
        # Transform all payloads
        transformer_results = MyFDCTransformer.transform_batch(payloads, client_id, actor)
        
        # Store all transactions
        transactions_response = []
        errors = []
        ingested_count = 0
        error_count = 0
        
        for transaction, error in transformer_results:
            try:
                # Store the transaction
                await self._store_transaction(transaction)
                
                transactions_response.append(IngestTransactionResponse(
                    id=transaction.id,
                    source=transaction.source.value if hasattr(transaction.source, 'value') else str(transaction.source),
                    source_transaction_id=transaction.source_transaction_id,
                    status=transaction.status.value if hasattr(transaction.status, 'value') else str(transaction.status),
                    ingested_at=transaction.ingested_at
                ))
                
                if transaction.status == IngestionStatus.ERROR:
                    error_count += 1
                    errors.append({
                        "source_transaction_id": transaction.source_transaction_id,
                        "error": error or transaction.error_message
                    })
                else:
                    ingested_count += 1
                    
            except Exception as e:
                logger.error(f"Failed to store transaction: {e}")
                error_count += 1
                errors.append({
                    "source_transaction_id": transaction.source_transaction_id if transaction else "unknown",
                    "error": str(e)
                })
        
        # Commit the batch
        try:
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to commit batch: {e}")
            await self.db.rollback()
            raise
        
        # Queue normalisation for successful transactions
        successful_ids = [
            t.id for t in transactions_response 
            if t.status == IngestionStatus.INGESTED.value
        ]
        if successful_ids:
            await self._queue_normalisation(batch_id, client_id, successful_ids)
        
        # Log batch completion
        log_ingestion_event(
            IngestionAuditEvent.BATCH_COMPLETED,
            batch_id,
            client_id,
            {
                "total": len(payloads),
                "ingested": ingested_count,
                "errors": error_count
            }
        )
        
        return IngestionBatchResult(
            batch_id=batch_id,
            client_id=client_id,
            source="MYFDC",
            total_count=len(payloads),
            ingested_count=ingested_count,
            error_count=error_count,
            transactions=transactions_response,
            errors=errors if errors else []
        )
    
    async def _store_transaction(self, transaction: IngestedTransaction) -> str:
        """Store a single transaction in the database."""
        import json
        
        # Convert audit entries to JSON-serializable format
        audit_json = json.dumps([entry.to_dict() for entry in transaction.audit])
        
        # Convert attachments to JSON-serializable format
        attachments_json = json.dumps([att.to_dict() for att in transaction.attachments])
        
        # Serialize raw_payload and metadata
        raw_payload_json = json.dumps(transaction.raw_payload) if transaction.raw_payload else None
        metadata_json = json.dumps(transaction.metadata) if transaction.metadata else None
        
        query = text("""
            INSERT INTO public.ingested_transactions (
                id, source, source_transaction_id, client_id,
                ingested_at, transaction_date, transaction_type,
                amount, currency, gst_included, gst_amount,
                description, notes, category_raw, category_normalised, category_code,
                business_percentage, vendor, receipt_number,
                attachments, status, error_message, audit,
                raw_payload, metadata, bookkeeping_transaction_id,
                created_at, updated_at
            ) VALUES (
                :id, :source, :source_transaction_id, :client_id::uuid,
                :ingested_at, :transaction_date, :transaction_type,
                :amount, :currency, :gst_included, :gst_amount,
                :description, :notes, :category_raw, :category_normalised, :category_code,
                :business_percentage, :vendor, :receipt_number,
                COALESCE(:attachments, '[]')::jsonb, :status, :error_message, COALESCE(:audit, '[]')::jsonb,
                :raw_payload::jsonb, :metadata::jsonb, :bookkeeping_transaction_id,
                NOW(), NOW()
            )
            ON CONFLICT (source, source_transaction_id, client_id) 
            DO UPDATE SET
                transaction_date = EXCLUDED.transaction_date,
                transaction_type = EXCLUDED.transaction_type,
                amount = EXCLUDED.amount,
                gst_included = EXCLUDED.gst_included,
                gst_amount = EXCLUDED.gst_amount,
                description = EXCLUDED.description,
                notes = EXCLUDED.notes,
                category_raw = EXCLUDED.category_raw,
                business_percentage = EXCLUDED.business_percentage,
                vendor = EXCLUDED.vendor,
                receipt_number = EXCLUDED.receipt_number,
                attachments = EXCLUDED.attachments,
                status = CASE 
                    WHEN public.ingested_transactions.status IN ('NORMALISED', 'READY_FOR_BOOKKEEPING') 
                    THEN public.ingested_transactions.status 
                    ELSE EXCLUDED.status 
                END,
                error_message = EXCLUDED.error_message,
                audit = public.ingested_transactions.audit || EXCLUDED.audit,
                raw_payload = EXCLUDED.raw_payload,
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
            RETURNING id
        """)
        
        result = await self.db.execute(query, {
            'id': transaction.id,
            'source': transaction.source.value if hasattr(transaction.source, 'value') else str(transaction.source),
            'source_transaction_id': transaction.source_transaction_id,
            'client_id': transaction.client_id,
            'ingested_at': transaction.ingested_at,
            'transaction_date': transaction.transaction_date,
            'transaction_type': transaction.transaction_type.value if hasattr(transaction.transaction_type, 'value') else str(transaction.transaction_type),
            'amount': float(transaction.amount),
            'currency': transaction.currency,
            'gst_included': transaction.gst_included,
            'gst_amount': float(transaction.gst_amount) if transaction.gst_amount else None,
            'description': transaction.description,
            'notes': transaction.notes,
            'category_raw': transaction.category_raw,
            'category_normalised': transaction.category_normalised,
            'category_code': transaction.category_code,
            'business_percentage': transaction.business_percentage,
            'vendor': transaction.vendor,
            'receipt_number': transaction.receipt_number,
            'attachments': attachments_json,
            'status': transaction.status.value if hasattr(transaction.status, 'value') else str(transaction.status),
            'error_message': transaction.error_message,
            'audit': audit_json,
            'raw_payload': raw_payload_json,
            'metadata': metadata_json,
            'bookkeeping_transaction_id': transaction.bookkeeping_transaction_id
        })
        
        row = result.fetchone()
        return str(row[0]) if row else transaction.id
    
    async def _queue_normalisation(
        self,
        batch_id: str,
        client_id: str,
        transaction_ids: List[str]
    ):
        """
        Queue transactions for normalisation by Agent 8.
        
        This creates a task that Agent 8's ingestion mapping engine will pick up
        to perform category normalisation.
        """
        # For now, we'll create a normalisation queue entry
        # Agent 8 will implement the actual processing
        
        try:
            query = text("""
                INSERT INTO public.normalisation_queue (
                    id, batch_id, client_id, transaction_ids,
                    status, created_at
                ) VALUES (
                    :id, :batch_id, :client_id, :transaction_ids::jsonb,
                    'PENDING', NOW()
                )
            """)
            
            import json
            await self.db.execute(query, {
                'id': str(uuid.uuid4()),
                'batch_id': batch_id,
                'client_id': client_id,
                'transaction_ids': json.dumps(transaction_ids)
            })
            
            log_ingestion_event(
                IngestionAuditEvent.NORMALISATION_QUEUED,
                batch_id,
                client_id,
                {"transaction_count": len(transaction_ids)}
            )
            
        except Exception as e:
            # If queue table doesn't exist, just log
            # Agent 8 will create this table when implementing A8-INGEST-03
            logger.info(f"Normalisation queue not available yet (A8-INGEST-03 dependency): {e}")
    
    async def get_transactions_by_client(
        self,
        client_id: str,
        status: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get ingested transactions for a client."""
        
        conditions = ["client_id = :client_id"]
        params = {"client_id": client_id, "limit": limit, "offset": offset}
        
        if status:
            conditions.append("status = :status")
            params["status"] = status
        
        if source:
            conditions.append("source = :source")
            params["source"] = source
        
        where_clause = " AND ".join(conditions)
        
        query = text(f"""
            SELECT 
                id, source, source_transaction_id, client_id,
                ingested_at, transaction_date, transaction_type,
                amount, currency, gst_included, gst_amount,
                description, notes, category_raw, category_normalised, category_code,
                business_percentage, vendor, receipt_number,
                attachments, status, error_message, audit,
                raw_payload, metadata, bookkeeping_transaction_id,
                created_at, updated_at
            FROM public.ingested_transactions
            WHERE {where_clause}
            ORDER BY ingested_at DESC
            LIMIT :limit OFFSET :offset
        """)
        
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        transactions = []
        for row in rows:
            transactions.append({
                "id": str(row[0]),
                "source": row[1],
                "source_transaction_id": row[2],
                "client_id": str(row[3]),
                "ingested_at": row[4].isoformat() if row[4] else None,
                "transaction_date": row[5].isoformat() if row[5] else None,
                "transaction_type": row[6],
                "amount": str(row[7]),
                "currency": row[8],
                "gst_included": row[9],
                "gst_amount": str(row[10]) if row[10] else None,
                "description": row[11],
                "notes": row[12],
                "category_raw": row[13],
                "category_normalised": row[14],
                "category_code": row[15],
                "business_percentage": row[16],
                "vendor": row[17],
                "receipt_number": row[18],
                "attachments": row[19],
                "status": row[20],
                "error_message": row[21],
                "audit": row[22],
                "raw_payload": row[23],
                "metadata": row[24],
                "bookkeeping_transaction_id": str(row[25]) if row[25] else None,
                "created_at": row[26].isoformat() if row[26] else None,
                "updated_at": row[27].isoformat() if row[27] else None
            })
        
        return transactions
    
    async def get_transaction_by_id(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        """Get a single transaction by ID."""
        query = text("""
            SELECT 
                id, source, source_transaction_id, client_id,
                ingested_at, transaction_date, transaction_type,
                amount, currency, gst_included, gst_amount,
                description, notes, category_raw, category_normalised, category_code,
                business_percentage, vendor, receipt_number,
                attachments, status, error_message, audit,
                raw_payload, metadata, bookkeeping_transaction_id,
                created_at, updated_at
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
            "ingested_at": row[4].isoformat() if row[4] else None,
            "transaction_date": row[5].isoformat() if row[5] else None,
            "transaction_type": row[6],
            "amount": str(row[7]),
            "currency": row[8],
            "gst_included": row[9],
            "gst_amount": str(row[10]) if row[10] else None,
            "description": row[11],
            "notes": row[12],
            "category_raw": row[13],
            "category_normalised": row[14],
            "category_code": row[15],
            "business_percentage": row[16],
            "vendor": row[17],
            "receipt_number": row[18],
            "attachments": row[19],
            "status": row[20],
            "error_message": row[21],
            "audit": row[22],
            "raw_payload": row[23],
            "metadata": row[24],
            "bookkeeping_transaction_id": str(row[25]) if row[25] else None,
            "created_at": row[26].isoformat() if row[26] else None,
            "updated_at": row[27].isoformat() if row[27] else None
        }
