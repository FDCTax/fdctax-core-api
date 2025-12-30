"""
LodgeIT Integration - Export Service

Provides functionality to export client data to LodgeIT CSV format.

LodgeIT CSV Format:
- Comma-separated values
- UTF-8 encoding
- Standard LodgeIT column headers
"""

import csv
import io
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, update
import logging

from .models import LodgeITExportQueueDB, ExportQueueStatus, LodgeITAuditLogDB, LodgeITAction

logger = logging.getLogger(__name__)


# LodgeIT CSV column headers (standard format)
LODGEIT_CSV_HEADERS = [
    "ClientID",
    "ClientType",
    "Title",
    "FirstName",
    "MiddleName",
    "LastName",
    "PreferredName",
    "DateOfBirth",
    "TaxFileNumber",
    "ABN",
    "ACN",
    "Email",
    "Phone",
    "Mobile",
    "Fax",
    "ResidentialAddress1",
    "ResidentialAddress2",
    "ResidentialSuburb",
    "ResidentialState",
    "ResidentialPostcode",
    "ResidentialCountry",
    "PostalAddress1",
    "PostalAddress2",
    "PostalSuburb",
    "PostalState",
    "PostalPostcode",
    "PostalCountry",
    "BusinessName",
    "BusinessAddress1",
    "BusinessAddress2",
    "BusinessSuburb",
    "BusinessState",
    "BusinessPostcode",
    "BusinessCountry",
    "GSTRegistered",
    "GSTStartDate",
    "AccountantName",
    "AccountantEmail",
    "Notes",
]


class LodgeITExportService:
    """
    Service class for exporting client data to LodgeIT format.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_client_data(self, client_ids: List[int]) -> List[Dict[str, Any]]:
        """
        Fetch client data from the database.
        
        Args:
            client_ids: List of client IDs to export
        
        Returns:
            List of client data dictionaries
        """
        if not client_ids:
            return []
        
        # Build query for crm_clients table
        placeholders = ', '.join([f':id_{i}' for i in range(len(client_ids))])
        query = text(f"""
            SELECT 
                id, name, email, phone, business_name, abn, gst_status,
                accountant_name, created_at, updated_at
            FROM crm_clients
            WHERE id IN ({placeholders})
        """)
        
        params = {f'id_{i}': cid for i, cid in enumerate(client_ids)}
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        clients = []
        for row in rows:
            clients.append({
                "id": row.id,
                "name": row.name,
                "email": row.email,
                "phone": row.phone,
                "business_name": row.business_name,
                "abn": row.abn,
                "gst_status": row.gst_status,
                "accountant_name": row.accountant_name,
            })
        
        return clients
    
    def map_client_to_lodgeit_row(self, client: Dict[str, Any]) -> Dict[str, str]:
        """
        Map internal client data to LodgeIT CSV format.
        
        Args:
            client: Client data dictionary
        
        Returns:
            Dictionary with LodgeIT column headers as keys
        """
        # Parse name into components
        name_parts = (client.get("name") or "").split(" ", 2)
        first_name = name_parts[0] if len(name_parts) > 0 else ""
        middle_name = name_parts[1] if len(name_parts) > 2 else ""
        last_name = name_parts[-1] if len(name_parts) > 1 else ""
        
        # Determine client type
        client_type = "Business" if client.get("business_name") else "Individual"
        
        # GST status
        gst_registered = "Yes" if client.get("gst_status") in ["registered", "yes", "true", "1"] else "No"
        
        return {
            "ClientID": str(client.get("id", "")),
            "ClientType": client_type,
            "Title": "",
            "FirstName": first_name,
            "MiddleName": middle_name,
            "LastName": last_name,
            "PreferredName": "",
            "DateOfBirth": "",
            "TaxFileNumber": "",
            "ABN": client.get("abn") or "",
            "ACN": "",
            "Email": client.get("email") or "",
            "Phone": client.get("phone") or "",
            "Mobile": "",
            "Fax": "",
            "ResidentialAddress1": "",
            "ResidentialAddress2": "",
            "ResidentialSuburb": "",
            "ResidentialState": "",
            "ResidentialPostcode": "",
            "ResidentialCountry": "Australia",
            "PostalAddress1": "",
            "PostalAddress2": "",
            "PostalSuburb": "",
            "PostalState": "",
            "PostalPostcode": "",
            "PostalCountry": "Australia",
            "BusinessName": client.get("business_name") or "",
            "BusinessAddress1": "",
            "BusinessAddress2": "",
            "BusinessSuburb": "",
            "BusinessState": "",
            "BusinessPostcode": "",
            "BusinessCountry": "Australia",
            "GSTRegistered": gst_registered,
            "GSTStartDate": "",
            "AccountantName": client.get("accountant_name") or "",
            "AccountantEmail": "",
            "Notes": "",
        }
    
    async def export_to_csv(self, client_ids: List[int]) -> str:
        """
        Export clients to LodgeIT CSV format.
        
        Args:
            client_ids: List of client IDs to export
        
        Returns:
            CSV string content
        """
        clients = await self.get_client_data(client_ids)
        
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=LODGEIT_CSV_HEADERS)
        writer.writeheader()
        
        for client in clients:
            row = self.map_client_to_lodgeit_row(client)
            writer.writerow(row)
        
        return output.getvalue()
    
    async def update_queue_status(
        self,
        client_ids: List[int],
        status: ExportQueueStatus,
        error_message: Optional[str] = None
    ):
        """
        Update the export queue status for the given clients.
        """
        for client_id in client_ids:
            query = text("""
                UPDATE lodgeit_export_queue
                SET status = :status,
                    updated_at = :now,
                    last_exported_at = CASE WHEN :status = 'exported' THEN :now ELSE last_exported_at END,
                    error_message = :error_message
                WHERE client_id = :client_id AND status = 'pending'
            """)
            await self.db.execute(query, {
                "status": status.value,
                "now": datetime.now(timezone.utc),
                "error_message": error_message,
                "client_id": client_id
            })
        
        await self.db.commit()


async def export_clients(
    db: AsyncSession,
    client_ids: List[int],
    user_id: str,
    user_email: Optional[str] = None
) -> Dict[str, Any]:
    """
    Export clients to LodgeIT CSV format.
    
    This is the main entry point for the export service.
    
    Args:
        db: Database session
        client_ids: List of client IDs to export
        user_id: ID of the user performing the export
        user_email: Email of the user (for audit log)
    
    Returns:
        Dictionary with:
        - success: bool
        - csv_content: str (if successful)
        - exported_count: int
        - error: str (if failed)
    """
    service = LodgeITExportService(db)
    
    try:
        # Generate CSV
        csv_content = await service.export_to_csv(client_ids)
        
        # Update queue status
        await service.update_queue_status(client_ids, ExportQueueStatus.EXPORTED)
        
        # Log success
        audit_log = LodgeITAuditLogDB(
            user_id=user_id,
            user_email=user_email,
            action=LodgeITAction.EXPORT,
            client_ids=client_ids,
            success=True,
            details={"exported_count": len(client_ids)}
        )
        db.add(audit_log)
        await db.commit()
        
        logger.info(f"LodgeIT export completed: {len(client_ids)} clients by user {user_id}")
        
        return {
            "success": True,
            "csv_content": csv_content,
            "exported_count": len(client_ids),
        }
        
    except Exception as e:
        logger.error(f"LodgeIT export failed: {e}")
        
        # Update queue status to failed
        await service.update_queue_status(client_ids, ExportQueueStatus.FAILED, str(e))
        
        # Log failure
        audit_log = LodgeITAuditLogDB(
            user_id=user_id,
            user_email=user_email,
            action=LodgeITAction.EXPORT,
            client_ids=client_ids,
            success=False,
            error_message=str(e)
        )
        db.add(audit_log)
        await db.commit()
        
        return {
            "success": False,
            "error": str(e),
            "exported_count": 0,
        }
