"""
Bookkeeping Ingestion - Service Layer

Provides business logic for:
- File upload and storage
- CSV/XLSX parsing and column detection
- Duplicate detection
- Transaction import
- Batch rollback
"""

import csv
import io
import os
import re
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Optional, Tuple
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, update, delete

from .models import ImportBatchDB, ImportAuditLogDB, ImportBatchStatus

logger = logging.getLogger(__name__)


# ==================== CONSTANTS ====================

# Standard column mappings for auto-detection
COLUMN_MAPPINGS = {
    "date": ["date", "transaction_date", "txn_date", "trans_date", "posting_date", "value_date"],
    "amount": ["amount", "value", "debit", "credit", "transaction_amount", "total"],
    "description": ["description", "narrative", "details", "memo", "reference", "particulars", "transaction_description"],
    "payee": ["payee", "merchant", "vendor", "counterparty", "name", "payee_name"],
    "category": ["category", "type", "transaction_type", "code"],
}

# Common bank export formats (ANZ, CBA, Westpac patterns)
BANK_FORMATS = {
    "anz": {
        "date_format": "%d/%m/%Y",
        "columns": ["Date", "Amount", "Details"],
    },
    "cba": {
        "date_format": "%d/%m/%Y",
        "columns": ["Date", "Amount", "Description", "Balance"],
    },
    "westpac": {
        "date_format": "%d/%m/%Y",
        "columns": ["Date", "Narrative", "Debit Amount", "Credit Amount", "Balance"],
    },
}

# Supported date formats for parsing
DATE_FORMATS = [
    "%Y-%m-%d",        # ISO format
    "%d/%m/%Y",        # Australian format
    "%d-%m-%Y",
    "%m/%d/%Y",        # US format
    "%Y/%m/%d",
    "%d %b %Y",        # 15 Jan 2025
    "%d %B %Y",        # 15 January 2025
]


# ==================== UPLOAD SERVICE ====================

class UploadService:
    """Handles file upload and storage"""
    
    UPLOAD_DIR = "/app/backend/uploads/ingestion"
    
    def __init__(self, db: AsyncSession):
        self.db = db
        # Ensure upload directory exists
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)
    
    async def upload_file(
        self,
        file_content: bytes,
        file_name: str,
        file_type: str,
        client_id: str,
        job_id: Optional[str],
        user_id: str,
        user_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Upload and store a file, create import batch record.
        
        Returns: {batch_id, file_path, file_url}
        """
        # Generate unique file name
        batch_id = uuid.uuid4()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'[^\w\-.]', '_', file_name)
        stored_name = f"{batch_id}_{timestamp}_{safe_name}"
        file_path = os.path.join(self.UPLOAD_DIR, stored_name)
        
        # Store file
        try:
            with open(file_path, 'wb') as f:
                f.write(file_content)
            logger.info(f"Stored file: {file_path}")
        except Exception as e:
            logger.error(f"Failed to store file: {e}")
            raise ValueError(f"Failed to store file: {e}")
        
        # Create import batch record
        batch = ImportBatchDB(
            id=batch_id,
            client_id=client_id,
            job_id=job_id,
            file_name=file_name,
            file_type=file_type.lower(),
            file_path=file_path,
            uploaded_by=user_id,
            uploaded_by_email=user_email,
            uploaded_at=datetime.now(timezone.utc),
            status=ImportBatchStatus.PENDING.value,
        )
        
        self.db.add(batch)
        
        # Create audit log
        audit = ImportAuditLogDB(
            batch_id=batch_id,
            user_id=user_id,
            user_email=user_email,
            action="upload",
            details={"file_name": file_name, "file_type": file_type}
        )
        self.db.add(audit)
        
        await self.db.commit()
        
        return {
            "batch_id": str(batch_id),
            "file_path": file_path,
            "file_url": f"/uploads/ingestion/{stored_name}",
            "file_name": file_name,
            "file_type": file_type,
        }


# ==================== PARSE SERVICE ====================

class ParseService:
    """Handles file parsing and column detection"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def parse_file(
        self,
        batch_id: str,
        user_id: str,
        user_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Parse file and return preview with column mapping suggestions.
        
        Returns: {
            columns: [],
            preview: [],  # First 20 rows
            row_count: int,
            mapping_suggestions: {},
            detected_format: str
        }
        """
        # Get batch record
        result = await self.db.execute(
            select(ImportBatchDB).where(ImportBatchDB.id == uuid.UUID(batch_id))
        )
        batch = result.scalar_one_or_none()
        
        if not batch:
            raise ValueError(f"Batch {batch_id} not found")
        
        if not batch.file_path or not os.path.exists(batch.file_path):
            raise ValueError(f"File not found for batch {batch_id}")
        
        # Parse based on file type
        if batch.file_type == 'csv':
            parse_result = await self._parse_csv(batch.file_path)
        elif batch.file_type in ['xlsx', 'xls']:
            parse_result = await self._parse_excel(batch.file_path)
        else:
            raise ValueError(f"Unsupported file type: {batch.file_type}")
        
        # Update batch with row count
        batch.row_count = parse_result["row_count"]
        batch.status = ImportBatchStatus.PENDING.value
        
        # Create audit log
        audit = ImportAuditLogDB(
            batch_id=uuid.UUID(batch_id),
            user_id=user_id,
            user_email=user_email,
            action="parse",
            details={
                "row_count": parse_result["row_count"],
                "columns": parse_result["columns"]
            }
        )
        self.db.add(audit)
        
        await self.db.commit()
        
        return parse_result
    
    async def _parse_csv(self, file_path: str) -> Dict[str, Any]:
        """Parse CSV file"""
        rows = []
        columns = []
        
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            # Try to detect delimiter
            sample = f.read(4096)
            f.seek(0)
            
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
            except csv.Error:
                dialect = csv.excel
            
            reader = csv.DictReader(f, dialect=dialect)
            columns = reader.fieldnames or []
            
            for i, row in enumerate(reader):
                rows.append(row)
        
        # Generate mapping suggestions
        suggestions = self._suggest_mappings(columns)
        
        # Detect bank format
        detected_format = self._detect_bank_format(columns)
        
        return {
            "columns": columns,
            "preview": rows[:20],
            "row_count": len(rows),
            "mapping_suggestions": suggestions,
            "detected_format": detected_format,
            "all_rows": rows,  # Keep for import
        }
    
    async def _parse_excel(self, file_path: str) -> Dict[str, Any]:
        """Parse Excel file"""
        try:
            import openpyxl
        except ImportError:
            raise ValueError("Excel support requires openpyxl. Install with: pip install openpyxl")
        
        wb = openpyxl.load_workbook(file_path, read_only=True)
        sheet = wb.active
        
        rows = []
        columns = []
        
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            if i == 0:
                columns = [str(c) if c else f"Column_{j}" for j, c in enumerate(row)]
            else:
                row_dict = {columns[j]: cell for j, cell in enumerate(row) if j < len(columns)}
                rows.append(row_dict)
        
        wb.close()
        
        suggestions = self._suggest_mappings(columns)
        detected_format = self._detect_bank_format(columns)
        
        return {
            "columns": columns,
            "preview": rows[:20],
            "row_count": len(rows),
            "mapping_suggestions": suggestions,
            "detected_format": detected_format,
            "all_rows": rows,
        }
    
    def _suggest_mappings(self, columns: List[str]) -> Dict[str, str]:
        """Auto-detect column mappings based on column names"""
        suggestions = {}
        normalized_cols = {col.lower().strip().replace(' ', '_'): col for col in columns}
        
        for field, patterns in COLUMN_MAPPINGS.items():
            for pattern in patterns:
                for norm_col, orig_col in normalized_cols.items():
                    if pattern in norm_col or norm_col in pattern:
                        suggestions[field] = orig_col
                        break
                if field in suggestions:
                    break
        
        return suggestions
    
    def _detect_bank_format(self, columns: List[str]) -> Optional[str]:
        """Detect if columns match a known bank export format"""
        normalized = [c.lower().strip() for c in columns]
        
        for bank, config in BANK_FORMATS.items():
            bank_cols = [c.lower().strip() for c in config["columns"]]
            if all(bc in normalized or any(bc in nc for nc in normalized) for bc in bank_cols[:2]):
                return bank
        
        return None


# ==================== IMPORT SERVICE ====================

class ImportService:
    """Handles transaction import with duplicate detection"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def import_transactions(
        self,
        batch_id: str,
        column_mapping: Dict[str, str],
        user_id: str,
        user_email: Optional[str] = None,
        skip_duplicates: bool = True
    ) -> Dict[str, Any]:
        """
        Import transactions from a parsed batch.
        
        Args:
            batch_id: Import batch ID
            column_mapping: Map of transaction fields to file columns
            user_id: User performing import
            user_email: User email for audit
            skip_duplicates: If True, skip duplicate transactions
        
        Returns: {
            success: bool,
            imported_count: int,
            skipped_duplicates: int,
            errors: []
        }
        """
        # Get batch record
        result = await self.db.execute(
            select(ImportBatchDB).where(ImportBatchDB.id == uuid.UUID(batch_id))
        )
        batch = result.scalar_one_or_none()
        
        if not batch:
            raise ValueError(f"Batch {batch_id} not found")
        
        # Update status to processing
        batch.status = ImportBatchStatus.PROCESSING.value
        batch.column_mapping = column_mapping
        await self.db.commit()
        
        # Re-parse file to get all rows
        parse_service = ParseService(self.db)
        if batch.file_type == 'csv':
            parse_result = await parse_service._parse_csv(batch.file_path)
        else:
            parse_result = await parse_service._parse_excel(batch.file_path)
        
        all_rows = parse_result.get("all_rows", [])
        
        # Import stats
        imported_count = 0
        skipped_count = 0
        errors = []
        
        for row_num, row in enumerate(all_rows, start=2):  # Start at 2 (header is row 1)
            try:
                # Extract values using mapping
                txn_data = self._extract_transaction_data(row, column_mapping, row_num)
                
                if not txn_data:
                    errors.append({"row": row_num, "error": "Failed to extract required fields"})
                    continue
                
                # Check for duplicates
                if skip_duplicates:
                    is_dup, existing_id = await self._check_duplicate(
                        batch.client_id,
                        batch.job_id,
                        txn_data["date"],
                        txn_data["amount"],
                        txn_data.get("description", "")
                    )
                    
                    if is_dup:
                        skipped_count += 1
                        continue
                
                # Insert transaction
                await self._insert_transaction(
                    batch_id=batch_id,
                    client_id=batch.client_id,
                    txn_data=txn_data
                )
                imported_count += 1
                
            except Exception as e:
                errors.append({"row": row_num, "error": str(e)})
        
        # Update batch with results
        batch.status = ImportBatchStatus.COMPLETED.value if not errors else ImportBatchStatus.COMPLETED.value
        batch.imported_count = imported_count
        batch.skipped_count = skipped_count
        batch.error_count = len(errors)
        batch.errors = errors[:100]  # Limit stored errors
        
        # Create audit log
        audit = ImportAuditLogDB(
            batch_id=uuid.UUID(batch_id),
            user_id=user_id,
            user_email=user_email,
            action="import",
            details={
                "imported_count": imported_count,
                "skipped_count": skipped_count,
                "error_count": len(errors),
            }
        )
        self.db.add(audit)
        
        await self.db.commit()
        
        logger.info(f"Import completed: {imported_count} imported, {skipped_count} skipped, {len(errors)} errors")
        
        return {
            "success": True,
            "batch_id": batch_id,
            "imported_count": imported_count,
            "skipped_duplicates": skipped_count,
            "error_count": len(errors),
            "errors": errors[:20],  # Return first 20 errors
        }
    
    def _extract_transaction_data(
        self,
        row: Dict[str, Any],
        mapping: Dict[str, str],
        row_num: int
    ) -> Optional[Dict[str, Any]]:
        """Extract transaction data from row using column mapping"""
        try:
            # Required: date and amount
            date_col = mapping.get("date")
            amount_col = mapping.get("amount")
            
            if not date_col or not amount_col:
                return None
            
            date_val = row.get(date_col)
            amount_val = row.get(amount_col)
            
            if not date_val or amount_val is None:
                return None
            
            # Parse date
            parsed_date = self._parse_date(date_val)
            if not parsed_date:
                raise ValueError(f"Invalid date format: {date_val}")
            
            # Parse amount
            parsed_amount = self._parse_amount(amount_val)
            if parsed_amount is None:
                raise ValueError(f"Invalid amount: {amount_val}")
            
            # Optional fields
            description = row.get(mapping.get("description", ""), "") or ""
            payee = row.get(mapping.get("payee", ""), "") or ""
            category = row.get(mapping.get("category", ""), "") or ""
            
            return {
                "date": parsed_date,
                "amount": parsed_amount,
                "description": str(description).strip(),
                "payee": str(payee).strip(),
                "category": str(category).strip(),
            }
            
        except Exception as e:
            logger.warning(f"Row {row_num}: {e}")
            raise
    
    def _parse_date(self, value: Any) -> Optional[date]:
        """Parse date from various formats"""
        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        
        if not value:
            return None
        
        value_str = str(value).strip()
        
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(value_str, fmt).date()
            except ValueError:
                continue
        
        return None
    
    def _parse_amount(self, value: Any) -> Optional[Decimal]:
        """Parse amount from various formats"""
        if isinstance(value, (int, float, Decimal)):
            return Decimal(str(value))
        
        if not value:
            return None
        
        # Clean string: remove currency symbols, spaces, commas
        value_str = str(value).strip()
        value_str = re.sub(r'[$€£¥₹\s]', '', value_str)
        value_str = value_str.replace(',', '')
        
        # Handle parentheses as negative
        if value_str.startswith('(') and value_str.endswith(')'):
            value_str = '-' + value_str[1:-1]
        
        # Handle CR/DR suffixes
        if value_str.upper().endswith('CR'):
            value_str = value_str[:-2]
        elif value_str.upper().endswith('DR'):
            value_str = '-' + value_str[:-2]
        
        try:
            return Decimal(value_str)
        except InvalidOperation:
            return None
    
    async def _check_duplicate(
        self,
        client_id: str,
        job_id: Optional[str],
        txn_date: date,
        amount: Decimal,
        description: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if transaction is a duplicate.
        
        Duplicate rule: same client_id + date + amount + normalized description
        """
        # Normalize description
        norm_desc = re.sub(r'\s+', ' ', description.lower().strip())
        
        query = text("""
            SELECT id FROM transactions
            WHERE client_id = :client_id
              AND date = :date
              AND amount = :amount
              AND LOWER(TRIM(REGEXP_REPLACE(COALESCE(description_raw, ''), '\s+', ' ', 'g'))) = :description
            LIMIT 1
        """)
        
        result = await self.db.execute(query, {
            "client_id": client_id,
            "date": txn_date,
            "amount": float(amount),
            "description": norm_desc
        })
        
        row = result.fetchone()
        if row:
            return True, row[0]
        return False, None
    
    async def _insert_transaction(
        self,
        batch_id: str,
        client_id: str,
        txn_data: Dict[str, Any]
    ):
        """Insert a new transaction"""
        txn_id = str(uuid.uuid4())
        
        # Note: import_batch_id requires the ALTER TABLE migration to be run
        # For now, we'll skip it if the column doesn't exist
        query = text("""
            INSERT INTO transactions (
                id, client_id, date, amount, payee_raw, description_raw,
                source, category_client, status_bookkeeper, created_at, updated_at
            ) VALUES (
                :id, :client_id, :date, :amount, :payee, :description,
                'BANK', :category, 'NEW', NOW(), NOW()
            )
        """)
        
        await self.db.execute(query, {
            "id": txn_id,
            "client_id": client_id,
            "date": txn_data["date"],
            "amount": float(txn_data["amount"]),
            "payee": txn_data.get("payee", ""),
            "description": txn_data.get("description", ""),
            "category": txn_data.get("category", ""),
        })


# ==================== ROLLBACK SERVICE ====================

class RollbackService:
    """Handles batch rollback operations"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def rollback_batch(
        self,
        batch_id: str,
        user_id: str,
        user_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Rollback all transactions from a batch.
        
        Note: This requires import_batch_id column in transactions table.
        If column doesn't exist, returns error.
        """
        # Get batch record
        result = await self.db.execute(
            select(ImportBatchDB).where(ImportBatchDB.id == uuid.UUID(batch_id))
        )
        batch = result.scalar_one_or_none()
        
        if not batch:
            raise ValueError(f"Batch {batch_id} not found")
        
        if batch.status == ImportBatchStatus.ROLLED_BACK.value:
            raise ValueError(f"Batch {batch_id} already rolled back")
        
        # Check if import_batch_id column exists
        column_check = await self.db.execute(text("""
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'transactions' AND column_name = 'import_batch_id'
        """))
        
        if not column_check.fetchone():
            # Fallback: Cannot rollback without import_batch_id column
            raise ValueError(
                "Rollback not available: import_batch_id column not found in transactions table. "
                "Run the migration: migrations/ingestion_setup.sql"
            )
        
        # Delete transactions with this batch_id
        delete_result = await self.db.execute(text("""
            DELETE FROM transactions WHERE import_batch_id = :batch_id
        """), {"batch_id": batch_id})
        
        deleted_count = delete_result.rowcount
        
        # Update batch status
        batch.status = ImportBatchStatus.ROLLED_BACK.value
        
        # Create audit log
        audit = ImportAuditLogDB(
            batch_id=uuid.UUID(batch_id),
            user_id=user_id,
            user_email=user_email,
            action="rollback",
            details={"deleted_count": deleted_count}
        )
        self.db.add(audit)
        
        await self.db.commit()
        
        logger.info(f"Rollback completed: {deleted_count} transactions deleted from batch {batch_id}")
        
        return {
            "success": True,
            "batch_id": batch_id,
            "deleted_count": deleted_count,
        }


# ==================== BATCH SERVICE ====================

class BatchService:
    """Handles batch queries and management"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get batch by ID"""
        result = await self.db.execute(
            select(ImportBatchDB).where(ImportBatchDB.id == uuid.UUID(batch_id))
        )
        batch = result.scalar_one_or_none()
        return batch.to_dict() if batch else None
    
    async def list_batches(
        self,
        client_id: Optional[str] = None,
        job_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List batches with optional filters"""
        query = select(ImportBatchDB)
        
        if client_id:
            query = query.where(ImportBatchDB.client_id == client_id)
        if job_id:
            query = query.where(ImportBatchDB.job_id == job_id)
        if status:
            query = query.where(ImportBatchDB.status == status)
        
        query = query.order_by(ImportBatchDB.uploaded_at.desc()).limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        batches = result.scalars().all()
        
        return [b.to_dict() for b in batches]
    
    async def get_batch_audit_log(self, batch_id: str) -> List[Dict[str, Any]]:
        """Get audit log for a batch"""
        result = await self.db.execute(
            select(ImportAuditLogDB)
            .where(ImportAuditLogDB.batch_id == uuid.UUID(batch_id))
            .order_by(ImportAuditLogDB.timestamp.desc())
        )
        logs = result.scalars().all()
        return [log.to_dict() for log in logs]
