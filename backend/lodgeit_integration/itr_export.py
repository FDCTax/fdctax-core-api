"""
LodgeIT Integration - ITR Export Service

Generates Income Tax Return (ITR) JSON templates for LodgeIT.

The ITR template follows the Australian Tax Office (ATO) format
as required by LodgeIT for lodgement.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone, date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import logging

from .models import LodgeITAuditLogDB, LodgeITAction

logger = logging.getLogger(__name__)


# Current financial year
def get_current_fy() -> str:
    """Get current financial year in format '2024-25'"""
    today = date.today()
    if today.month >= 7:  # July onwards = new FY
        return f"{today.year}-{str(today.year + 1)[-2:]}"
    else:
        return f"{today.year - 1}-{str(today.year)[-2:]}"


class ITRExportService:
    """
    Service class for generating ITR JSON templates.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_client_data(self, client_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch client data for ITR generation.
        """
        query = text("""
            SELECT 
                id, name, email, phone, business_name, abn, gst_status,
                accountant_name, created_at, updated_at
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
    
    async def get_transaction_summary(self, client_id: int) -> Dict[str, Any]:
        """
        Get transaction summary for the client from the Transaction Engine.
        """
        # Query transactions for this client
        query = text("""
            SELECT 
                COUNT(*) as total_count,
                COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) as total_income,
                COALESCE(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 0) as total_expenses,
                COALESCE(SUM(amount), 0) as net_amount
            FROM transactions
            WHERE client_id = :client_id
        """)
        
        result = await self.db.execute(query, {"client_id": str(client_id)})
        row = result.fetchone()
        
        if row:
            return {
                "transaction_count": row.total_count,
                "total_income": float(row.total_income),
                "total_expenses": float(row.total_expenses),
                "net_amount": float(row.net_amount)
            }
        
        return {
            "transaction_count": 0,
            "total_income": 0.0,
            "total_expenses": 0.0,
            "net_amount": 0.0
        }
    
    def generate_template(self, client: Dict[str, Any], transactions: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate ITR JSON template.
        
        Args:
            client: Client data
            transactions: Transaction summary
        
        Returns:
            ITR JSON template
        """
        # Parse name
        name_parts = (client.get("name") or "").split(" ", 2)
        first_name = name_parts[0] if len(name_parts) > 0 else ""
        surname = name_parts[-1] if len(name_parts) > 1 else ""
        
        # Determine entity type
        entity_type = "IND"  # Individual
        if client.get("business_name") and client.get("abn"):
            entity_type = "BUS"  # Business
        
        fy = get_current_fy()
        
        return {
            "_meta": {
                "format": "LodgeIT_ITR_v2",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "financial_year": fy,
                "source_system": "FDC_Core"
            },
            "taxpayer": {
                "client_id": client.get("id"),
                "entity_type": entity_type,
                "title": "",
                "given_names": first_name,
                "surname": surname,
                "date_of_birth": None,
                "tfn": None,  # Not stored for security
                "abn": client.get("abn"),
                "business_name": client.get("business_name"),
            },
            "contact": {
                "email": client.get("email"),
                "phone": client.get("phone"),
                "mobile": None,
                "postal_address": {
                    "line1": "",
                    "line2": "",
                    "suburb": "",
                    "state": "",
                    "postcode": "",
                    "country": "AUS"
                }
            },
            "agent": {
                "name": client.get("accountant_name"),
                "abn": "",
                "contact_name": "",
                "email": "",
                "phone": ""
            },
            "income": {
                "salary_wages": [],
                "interest": [],
                "dividends": [],
                "partnerships_trusts": [],
                "rental_income": [],
                "business_income": [
                    {
                        "source": "FDC Transaction Engine",
                        "gross_income": transactions.get("total_income", 0),
                        "expenses": transactions.get("total_expenses", 0),
                        "net_income": transactions.get("net_amount", 0)
                    }
                ] if entity_type == "BUS" else [],
                "capital_gains": [],
                "other_income": []
            },
            "deductions": {
                "work_related": [],
                "self_education": [],
                "motor_vehicle": [],
                "travel": [],
                "home_office": [],
                "donations": [],
                "income_protection": [],
                "accounting_fees": [],
                "other_deductions": []
            },
            "offsets": {
                "private_health": None,
                "spouse": None,
                "seniors": None,
                "other": []
            },
            "medicare": {
                "levy_exemption": None,
                "surcharge_exemption": None
            },
            "gst": {
                "registered": client.get("gst_status") == "registered",
                "bas_lodgement_method": None,
                "reporting_method": None
            },
            "summary": {
                "total_income": transactions.get("total_income", 0),
                "total_deductions": transactions.get("total_expenses", 0),
                "taxable_income": transactions.get("net_amount", 0),
                "tax_payable": None,  # Calculated by LodgeIT
                "tax_offsets": 0,
                "medicare_levy": None,
                "net_tax_payable": None
            },
            "lodgement": {
                "type": "electronic",
                "due_date": None,
                "extension_granted": False,
                "status": "draft"
            }
        }


async def generate_itr_template(
    db: AsyncSession,
    client_id: int,
    user_id: str,
    user_email: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate ITR JSON template for a client.
    
    Args:
        db: Database session
        client_id: Client ID
        user_id: ID of the user performing the export
        user_email: Email of the user (for audit log)
    
    Returns:
        Dictionary with:
        - success: bool
        - template: dict (if successful)
        - error: str (if failed)
    """
    service = ITRExportService(db)
    
    try:
        # Get client data
        client = await service.get_client_data(client_id)
        
        if not client:
            return {
                "success": False,
                "error": f"Client {client_id} not found"
            }
        
        # Get transaction summary
        transactions = await service.get_transaction_summary(client_id)
        
        # Generate template
        template = service.generate_template(client, transactions)
        
        # Log success
        audit_log = LodgeITAuditLogDB(
            user_id=user_id,
            user_email=user_email,
            action=LodgeITAction.ITR_EXPORT.value,
            client_ids=[client_id],
            success=True,
            details={"financial_year": template["_meta"]["financial_year"]}
        )
        db.add(audit_log)
        await db.commit()
        
        logger.info(f"ITR template generated for client {client_id} by user {user_id}")
        
        return {
            "success": True,
            "template": template,
            "client_id": client_id
        }
        
    except Exception as e:
        logger.error(f"ITR template generation failed: {e}")
        
        # Log failure
        audit_log = LodgeITAuditLogDB(
            user_id=user_id,
            user_email=user_email,
            action=LodgeITAction.ITR_EXPORT.value,
            client_ids=[client_id],
            success=False,
            error_message=str(e)
        )
        db.add(audit_log)
        await db.commit()
        
        return {
            "success": False,
            "error": str(e)
        }
