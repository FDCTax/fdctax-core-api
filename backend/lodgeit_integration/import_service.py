"""
LodgeIT Integration - Import Service

Provides functionality to import client data from LodgeIT CSV format.
Implements safe overwrite rules to prevent data loss.

Safe Overwrite Rules:
1. Only update fields that are empty in the target record
2. Never overwrite existing data unless explicitly flagged
3. Create new records for unknown client IDs
4. Log all changes for audit compliance
"""

import csv
import io
from typing import List, Dict, Any, Optional, BinaryIO
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import logging

from .models import LodgeITAuditLogDB, LodgeITAction
from .export_service import LODGEIT_CSV_HEADERS

logger = logging.getLogger(__name__)


class LodgeITImportService:
    """
    Service class for importing client data from LodgeIT format.
    Implements safe overwrite rules.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    def parse_csv(self, file_content: str) -> List[Dict[str, str]]:
        """
        Parse LodgeIT CSV content into list of dictionaries.
        
        Args:
            file_content: CSV string content
        
        Returns:
            List of row dictionaries
        """
        reader = csv.DictReader(io.StringIO(file_content))
        return list(reader)
    
    def map_lodgeit_to_client(self, row: Dict[str, str]) -> Dict[str, Any]:
        """
        Map LodgeIT CSV row to internal client format.
        
        Args:
            row: CSV row dictionary
        
        Returns:
            Client data dictionary
        """
        # Combine name parts
        name_parts = [
            row.get("FirstName", "").strip(),
            row.get("MiddleName", "").strip(),
            row.get("LastName", "").strip()
        ]
        full_name = " ".join(part for part in name_parts if part)
        
        # Parse GST status
        gst_registered = row.get("GSTRegistered", "").lower()
        gst_status = "registered" if gst_registered in ["yes", "true", "1"] else "not_registered"
        
        return {
            "lodgeit_id": row.get("ClientID", "").strip(),
            "name": full_name or row.get("BusinessName", "").strip(),
            "email": row.get("Email", "").strip(),
            "phone": row.get("Phone", "").strip() or row.get("Mobile", "").strip(),
            "business_name": row.get("BusinessName", "").strip(),
            "abn": row.get("ABN", "").strip(),
            "gst_status": gst_status,
            "accountant_name": row.get("AccountantName", "").strip(),
        }
    
    async def get_existing_client(self, client_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch existing client by ID.
        """
        query = text("""
            SELECT id, name, email, phone, business_name, abn, gst_status, accountant_name
            FROM crm_clients
            WHERE id = :client_id
        """)
        result = await self.db.execute(query, {"client_id": client_id})
        row = result.fetchone()
        
        if not row:
            return None
        
        return {
            "id": row.id,
            "name": row.name,
            "email": row.email,
            "phone": row.phone,
            "business_name": row.business_name,
            "abn": row.abn,
            "gst_status": row.gst_status,
            "accountant_name": row.accountant_name,
        }
    
    def apply_safe_overwrite(self, existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply safe overwrite rules.
        Only update fields that are empty in the existing record.
        
        Args:
            existing: Current client data
            incoming: Incoming LodgeIT data
        
        Returns:
            Merged data dictionary with changes applied
        """
        changes = {}
        merged = dict(existing)
        
        # Fields that can be safely updated
        updateable_fields = ["name", "email", "phone", "business_name", "abn", "gst_status", "accountant_name"]
        
        for field in updateable_fields:
            existing_value = existing.get(field)
            incoming_value = incoming.get(field)
            
            # Only update if existing is empty/None and incoming has value
            if not existing_value and incoming_value:
                merged[field] = incoming_value
                changes[field] = {
                    "old": existing_value,
                    "new": incoming_value
                }
        
        return {
            "data": merged,
            "changes": changes,
            "has_changes": len(changes) > 0
        }
    
    async def update_client(self, client_id: int, data: Dict[str, Any]) -> bool:
        """
        Update client record in database.
        """
        query = text("""
            UPDATE crm_clients
            SET name = :name,
                email = :email,
                phone = :phone,
                business_name = :business_name,
                abn = :abn,
                gst_status = :gst_status,
                accountant_name = :accountant_name,
                updated_at = :updated_at
            WHERE id = :id
        """)
        
        await self.db.execute(query, {
            "id": client_id,
            "name": data.get("name"),
            "email": data.get("email"),
            "phone": data.get("phone"),
            "business_name": data.get("business_name"),
            "abn": data.get("abn"),
            "gst_status": data.get("gst_status"),
            "accountant_name": data.get("accountant_name"),
            "updated_at": datetime.now(timezone.utc)
        })
        
        return True
    
    async def create_client(self, data: Dict[str, Any]) -> int:
        """
        Create new client record.
        """
        query = text("""
            INSERT INTO crm_clients (name, email, phone, business_name, abn, gst_status, accountant_name, created_at, updated_at)
            VALUES (:name, :email, :phone, :business_name, :abn, :gst_status, :accountant_name, :created_at, :updated_at)
            RETURNING id
        """)
        
        result = await self.db.execute(query, {
            "name": data.get("name"),
            "email": data.get("email"),
            "phone": data.get("phone"),
            "business_name": data.get("business_name"),
            "abn": data.get("abn"),
            "gst_status": data.get("gst_status"),
            "accountant_name": data.get("accountant_name"),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        })
        
        row = result.fetchone()
        return row.id if row else None


async def import_csv(
    db: AsyncSession,
    file_content: str,
    user_id: str,
    user_email: Optional[str] = None,
    force_overwrite: bool = False
) -> Dict[str, Any]:
    """
    Import clients from LodgeIT CSV with safe overwrite rules.
    
    Args:
        db: Database session
        file_content: CSV string content
        user_id: ID of the user performing the import
        user_email: Email of the user (for audit log)
        force_overwrite: If True, overwrite existing data (admin only)
    
    Returns:
        Dictionary with:
        - success: bool
        - created_count: int
        - updated_count: int
        - skipped_count: int
        - errors: list of error messages
    """
    service = LodgeITImportService(db)
    
    results = {
        "created": [],
        "updated": [],
        "skipped": [],
        "errors": []
    }
    
    try:
        # Parse CSV
        rows = service.parse_csv(file_content)
        
        for row in rows:
            try:
                # Map to internal format
                client_data = service.map_lodgeit_to_client(row)
                lodgeit_id = client_data.get("lodgeit_id", "")
                
                # Try to find existing client by LodgeIT ID
                existing_client = None
                if lodgeit_id.isdigit():
                    existing_client = await service.get_existing_client(int(lodgeit_id))
                
                if existing_client:
                    # Apply safe overwrite
                    merge_result = service.apply_safe_overwrite(existing_client, client_data)
                    
                    if merge_result["has_changes"] or force_overwrite:
                        await service.update_client(existing_client["id"], merge_result["data"])
                        results["updated"].append({
                            "client_id": existing_client["id"],
                            "changes": merge_result["changes"]
                        })
                    else:
                        results["skipped"].append({
                            "client_id": existing_client["id"],
                            "reason": "no_changes"
                        })
                else:
                    # Create new client
                    new_id = await service.create_client(client_data)
                    if new_id:
                        results["created"].append({
                            "client_id": new_id,
                            "lodgeit_id": lodgeit_id
                        })
                    
            except Exception as e:
                results["errors"].append({
                    "row": row.get("ClientID", "unknown"),
                    "error": str(e)
                })
        
        await db.commit()
        
        # Create audit log
        affected_ids = (
            [r["client_id"] for r in results["created"]] +
            [r["client_id"] for r in results["updated"]]
        )
        
        audit_log = LodgeITAuditLogDB(
            user_id=user_id,
            user_email=user_email,
            action=LodgeITAction.IMPORT.value,
            client_ids=affected_ids,
            success=True,
            details={
                "created_count": len(results["created"]),
                "updated_count": len(results["updated"]),
                "skipped_count": len(results["skipped"]),
                "error_count": len(results["errors"]),
                "force_overwrite": force_overwrite
            }
        )
        db.add(audit_log)
        await db.commit()
        
        logger.info(f"LodgeIT import completed: {len(results['created'])} created, {len(results['updated'])} updated by user {user_id}")
        
        return {
            "success": True,
            "created_count": len(results["created"]),
            "updated_count": len(results["updated"]),
            "skipped_count": len(results["skipped"]),
            "created": results["created"],
            "updated": results["updated"],
            "skipped": results["skipped"],
            "errors": results["errors"]
        }
        
    except Exception as e:
        logger.error(f"LodgeIT import failed: {e}")
        
        # Log failure
        audit_log = LodgeITAuditLogDB(
            user_id=user_id,
            user_email=user_email,
            action=LodgeITAction.IMPORT.value,
            client_ids=[],
            success=False,
            error_message=str(e)
        )
        db.add(audit_log)
        await db.commit()
        
        return {
            "success": False,
            "error": str(e),
            "created_count": 0,
            "updated_count": 0,
            "skipped_count": 0,
            "errors": [str(e)]
        }
