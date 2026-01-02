"""
MyFDC Transformer Factory (A3-INGEST-02)

Transforms raw MyFDC payloads into the unified IngestedTransaction schema.
Handles validation, type conversion, and audit trail initialization.
"""

import uuid
import logging
from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, Optional, List, Tuple

from ingestion.unified_schema import (
    IngestedTransaction,
    IngestionSource,
    TransactionType,
    IngestionStatus,
    AttachmentRef,
    AuditEntry,
    OCRStatus
)

logger = logging.getLogger(__name__)


class MyFDCTransformError(Exception):
    """Raised when transformation fails."""
    def __init__(self, message: str, field: Optional[str] = None, raw_value: Any = None):
        self.message = message
        self.field = field
        self.raw_value = raw_value
        super().__init__(message)


class MyFDCTransformer:
    """
    Transforms raw MyFDC transaction data into IngestedTransaction objects.
    
    Handles:
    - Field mapping from MyFDC schema to unified schema
    - Type conversions (dates, decimals, enums)
    - Validation with detailed error messages
    - Audit trail initialization
    """
    
    # MyFDC transaction type mappings
    TYPE_MAPPING = {
        'expense': TransactionType.EXPENSE,
        'income': TransactionType.INCOME,
        'transfer': TransactionType.TRANSFER,
        'deduction': TransactionType.EXPENSE,  # Deductions are expenses
        'payment': TransactionType.INCOME,     # Payments received are income
    }
    
    @classmethod
    def transform(
        cls,
        raw_payload: Dict[str, Any],
        client_id: str,
        actor: str = "myfdc_ingestion"
    ) -> Tuple[Optional[IngestedTransaction], Optional[str]]:
        """
        Transform a single MyFDC payload into an IngestedTransaction.
        
        Args:
            raw_payload: Raw MyFDC transaction data
            client_id: Core client ID
            actor: Service/user performing ingestion
            
        Returns:
            Tuple of (IngestedTransaction or None, error_message or None)
        """
        try:
            # Extract and validate required fields
            source_transaction_id = cls._extract_source_id(raw_payload)
            transaction_date = cls._parse_date(raw_payload)
            transaction_type = cls._determine_type(raw_payload)
            amount = cls._parse_amount(raw_payload, transaction_type)
            gst_included, gst_amount = cls._parse_gst(raw_payload)
            
            # Extract optional fields
            description = cls._safe_string(raw_payload.get('description') or raw_payload.get('notes') or raw_payload.get('memo'))
            notes = cls._safe_string(raw_payload.get('educator_notes') or raw_payload.get('additional_notes'))
            category_raw = cls._safe_string(raw_payload.get('category') or raw_payload.get('expense_category') or raw_payload.get('type'))
            vendor = cls._safe_string(raw_payload.get('vendor') or raw_payload.get('payee') or raw_payload.get('merchant'))
            receipt_number = cls._safe_string(raw_payload.get('receipt_number') or raw_payload.get('invoice_number') or raw_payload.get('reference'))
            business_percentage = cls._parse_business_percentage(raw_payload)
            
            # Handle attachments
            attachments = cls._parse_attachments(raw_payload)
            
            # Create the ingested transaction
            transaction = IngestedTransaction(
                id=str(uuid.uuid4()),
                source=IngestionSource.MYFDC,
                source_transaction_id=source_transaction_id,
                client_id=client_id,
                ingested_at=datetime.now(timezone.utc),
                transaction_date=transaction_date,
                transaction_type=transaction_type,
                amount=amount,
                currency="AUD",
                gst_included=gst_included,
                gst_amount=gst_amount,
                description=description,
                notes=notes,
                category_raw=category_raw,
                category_normalised=None,  # Will be set by Agent 8
                category_code=None,
                business_percentage=business_percentage,
                vendor=vendor,
                receipt_number=receipt_number,
                attachments=attachments,
                status=IngestionStatus.INGESTED,
                error_message=None,
                audit=[],
                raw_payload=raw_payload,
                metadata=cls._extract_metadata(raw_payload),
                bookkeeping_transaction_id=None
            )
            
            # Add initial audit entry
            transaction.add_audit_entry(
                action="ingested",
                actor=actor,
                details={
                    "source": "MYFDC",
                    "source_transaction_id": source_transaction_id,
                    "raw_payload_keys": list(raw_payload.keys())
                }
            )
            
            return transaction, None
            
        except MyFDCTransformError as e:
            logger.warning(f"Transform error: {e.message} (field={e.field})")
            return cls._create_error_transaction(raw_payload, client_id, str(e.message), actor)
        except Exception as e:
            logger.error(f"Unexpected transform error: {e}")
            return cls._create_error_transaction(raw_payload, client_id, f"Unexpected error: {str(e)}", actor)
    
    @classmethod
    def transform_batch(
        cls,
        payloads: List[Dict[str, Any]],
        client_id: str,
        actor: str = "myfdc_ingestion"
    ) -> List[Tuple[IngestedTransaction, Optional[str]]]:
        """
        Transform a batch of MyFDC payloads.
        
        Returns list of (transaction, error_message) tuples.
        All items are processed - errors don't stop the batch.
        """
        results = []
        for payload in payloads:
            txn, error = cls.transform(payload, client_id, actor)
            if txn:
                results.append((txn, error))
            else:
                # Create error placeholder if transform returned None
                error_txn, _ = cls._create_error_transaction(
                    payload, client_id, error or "Unknown transform error", actor
                )
                results.append((error_txn, error))
        return results
    
    @classmethod
    def _extract_source_id(cls, payload: Dict[str, Any]) -> str:
        """Extract the source transaction ID from MyFDC payload."""
        source_id = (
            payload.get('id') or 
            payload.get('myfdc_id') or 
            payload.get('transaction_id') or
            payload.get('uid')
        )
        if not source_id:
            raise MyFDCTransformError("Missing source transaction ID", field="id")
        return str(source_id)
    
    @classmethod
    def _parse_date(cls, payload: Dict[str, Any]) -> date:
        """Parse transaction date from various formats."""
        date_value = (
            payload.get('transaction_date') or
            payload.get('date') or
            payload.get('expense_date') or
            payload.get('income_date') or
            payload.get('created_at')
        )
        
        if not date_value:
            raise MyFDCTransformError("Missing transaction date", field="date")
        
        # Handle various formats
        if isinstance(date_value, date):
            return date_value
        
        if isinstance(date_value, datetime):
            return date_value.date()
        
        if isinstance(date_value, str):
            # Try common formats
            formats = [
                '%Y-%m-%d',
                '%d/%m/%Y',
                '%d-%m-%Y',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%dT%H:%M:%S.%f',
                '%Y-%m-%dT%H:%M:%SZ',
                '%Y-%m-%dT%H:%M:%S.%fZ',
            ]
            for fmt in formats:
                try:
                    return datetime.strptime(date_value.split('+')[0].split('Z')[0], fmt).date()
                except ValueError:
                    continue
            
            raise MyFDCTransformError(f"Invalid date format: {date_value}", field="date", raw_value=date_value)
        
        raise MyFDCTransformError(f"Unsupported date type: {type(date_value)}", field="date", raw_value=date_value)
    
    @classmethod
    def _determine_type(cls, payload: Dict[str, Any]) -> TransactionType:
        """Determine transaction type from payload."""
        type_value = (
            payload.get('transaction_type') or
            payload.get('type') or
            payload.get('entry_type')
        )
        
        if type_value:
            type_lower = str(type_value).lower().strip()
            if type_lower in cls.TYPE_MAPPING:
                return cls.TYPE_MAPPING[type_lower]
        
        # Infer from amount sign or category
        amount = payload.get('amount', 0)
        if isinstance(amount, (int, float, Decimal)):
            if amount < 0:
                return TransactionType.EXPENSE
            elif amount > 0:
                return TransactionType.INCOME
        
        # Check for expense indicators
        if payload.get('expense_category') or payload.get('is_expense'):
            return TransactionType.EXPENSE
        
        # Default to unknown
        return TransactionType.UNKNOWN
    
    @classmethod
    def _parse_amount(cls, payload: Dict[str, Any], txn_type: TransactionType) -> Decimal:
        """Parse and sign the amount based on transaction type."""
        amount_value = (
            payload.get('amount') or
            payload.get('total') or
            payload.get('value') or
            0
        )
        
        try:
            amount = Decimal(str(amount_value))
        except (InvalidOperation, ValueError):
            raise MyFDCTransformError(f"Invalid amount: {amount_value}", field="amount", raw_value=amount_value)
        
        # Apply sign based on transaction type
        if txn_type == TransactionType.EXPENSE:
            return -abs(amount)
        elif txn_type == TransactionType.INCOME:
            return abs(amount)
        else:
            return amount
    
    @classmethod
    def _parse_gst(cls, payload: Dict[str, Any]) -> Tuple[bool, Optional[Decimal]]:
        """Parse GST information."""
        gst_included = payload.get('gst_included', True)
        if isinstance(gst_included, str):
            gst_included = gst_included.lower() in ('true', 'yes', '1', 'y')
        
        gst_amount = payload.get('gst_amount') or payload.get('gst')
        if gst_amount is not None:
            try:
                gst_amount = Decimal(str(gst_amount))
            except (InvalidOperation, ValueError):
                gst_amount = None
        
        return bool(gst_included), gst_amount
    
    @classmethod
    def _parse_business_percentage(cls, payload: Dict[str, Any]) -> int:
        """Parse business use percentage."""
        pct = payload.get('business_percentage') or payload.get('business_use_percentage') or payload.get('work_percentage')
        if pct is None:
            return 100
        
        try:
            pct = int(pct)
            return max(0, min(100, pct))  # Clamp to 0-100
        except (ValueError, TypeError):
            return 100
    
    @classmethod
    def _parse_attachments(cls, payload: Dict[str, Any]) -> List[AttachmentRef]:
        """Parse attachment references from payload."""
        attachments = []
        raw_attachments = payload.get('attachments') or payload.get('receipts') or payload.get('files') or []
        
        for att in raw_attachments:
            if isinstance(att, dict):
                try:
                    attachments.append(AttachmentRef(
                        id=str(att.get('id') or uuid.uuid4()),
                        file_name=att.get('file_name') or att.get('name') or 'unknown',
                        file_type=att.get('file_type') or att.get('mime_type') or 'application/octet-stream',
                        file_size=int(att.get('file_size') or att.get('size') or 0),
                        storage_path=att.get('storage_path') or att.get('url') or att.get('path') or '',
                        ocr_status=OCRStatus.PENDING,
                        ocr_result=None
                    ))
                except Exception as e:
                    logger.warning(f"Failed to parse attachment: {e}")
                    continue
        
        return attachments
    
    @classmethod
    def _extract_metadata(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extract additional metadata from payload."""
        metadata = {}
        
        # Preserve MyFDC-specific fields
        myfdc_fields = [
            'educator_id', 'child_id', 'service_id', 'claim_id',
            'period_start', 'period_end', 'hours_worked', 'occupancy_rate',
            'submission_id', 'batch_id'
        ]
        
        for field in myfdc_fields:
            if field in payload:
                metadata[field] = payload[field]
        
        return metadata if metadata else None
    
    @classmethod
    def _safe_string(cls, value: Any) -> Optional[str]:
        """Safely convert value to string or None."""
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None
    
    @classmethod
    def _create_error_transaction(
        cls,
        raw_payload: Dict[str, Any],
        client_id: str,
        error_message: str,
        actor: str
    ) -> Tuple[IngestedTransaction, str]:
        """Create an error transaction for failed transformations."""
        source_id = str(raw_payload.get('id') or raw_payload.get('myfdc_id') or uuid.uuid4())
        
        # Try to get at least a date, default to today
        try:
            txn_date = cls._parse_date(raw_payload)
        except:
            txn_date = date.today()
        
        transaction = IngestedTransaction(
            id=str(uuid.uuid4()),
            source=IngestionSource.MYFDC,
            source_transaction_id=source_id,
            client_id=client_id,
            ingested_at=datetime.now(timezone.utc),
            transaction_date=txn_date,
            transaction_type=TransactionType.UNKNOWN,
            amount=Decimal('0'),
            currency="AUD",
            gst_included=True,
            gst_amount=None,
            description=None,
            notes=None,
            category_raw=None,
            category_normalised=None,
            category_code=None,
            business_percentage=100,
            vendor=None,
            receipt_number=None,
            attachments=[],
            status=IngestionStatus.ERROR,
            error_message=error_message,
            audit=[],
            raw_payload=raw_payload,
            metadata=None,
            bookkeeping_transaction_id=None
        )
        
        transaction.add_audit_entry(
            action="ingestion_error",
            actor=actor,
            details={
                "error": error_message,
                "raw_payload_keys": list(raw_payload.keys()) if raw_payload else []
            }
        )
        
        return transaction, error_message
