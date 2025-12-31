"""
BAS Backend - Service Layer

Provides business logic for:
- Saving BAS snapshots
- Retrieving BAS history
- Change log persistence
- PDF generation (data endpoint)
"""

import uuid
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import List, Dict, Any, Optional
import logging
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, and_, or_, desc

from .models import (
    BASStatementDB, BASChangeLogDB,
    BASStatus, BASActionType, BASEntityType
)

logger = logging.getLogger(__name__)


# ==================== BAS STATEMENT SERVICE ====================

class BASStatementService:
    """Service for managing BAS statements"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def save_bas(
        self,
        client_id: str,
        period_from: date,
        period_to: date,
        summary: Dict[str, Any],
        user_id: str,
        user_email: Optional[str] = None,
        job_id: Optional[str] = None,
        notes: Optional[str] = None,
        status: str = "draft"
    ) -> Dict[str, Any]:
        """
        Save a BAS snapshot.
        
        If a BAS already exists for the same client/period, increment version.
        """
        # Check for existing BAS for this period
        existing = await self._get_latest_for_period(client_id, period_from, period_to)
        
        if existing:
            version = existing.version + 1
            logger.info(f"Creating new version {version} for client {client_id}")
        else:
            version = 1
        
        # Create BAS statement
        bas = BASStatementDB(
            client_id=client_id,
            job_id=job_id,
            period_from=period_from,
            period_to=period_to,
            
            # GST fields
            g1_total_income=Decimal(str(summary.get("g1_total_income", 0))),
            gst_on_income_1a=Decimal(str(summary.get("gst_on_income_1a", 0))),
            gst_on_expenses_1b=Decimal(str(summary.get("gst_on_expenses_1b", 0))),
            net_gst=Decimal(str(summary.get("net_gst", 0))),
            g2_export_sales=Decimal(str(summary.get("g2_export_sales", 0))),
            g3_gst_free_sales=Decimal(str(summary.get("g3_gst_free_sales", 0))),
            g10_capital_purchases=Decimal(str(summary.get("g10_capital_purchases", 0))),
            g11_non_capital_purchases=Decimal(str(summary.get("g11_non_capital_purchases", 0))),
            
            # PAYG
            payg_instalment=Decimal(str(summary.get("payg_instalment", 0))),
            
            # Totals
            total_payable=Decimal(str(summary.get("total_payable", 0))),
            
            # Notes
            notes=notes,
            
            # Sign-off (if completing)
            completed_by=user_id if status == "completed" else None,
            completed_by_email=user_email if status == "completed" else None,
            completed_at=datetime.now(timezone.utc) if status == "completed" else None,
            
            # Version and status
            version=version,
            status=status,
        )
        
        self.db.add(bas)
        await self.db.commit()
        await self.db.refresh(bas)
        
        # Log the action
        await self._log_change(
            bas_statement_id=bas.id,
            client_id=client_id,
            job_id=job_id,
            user_id=user_id,
            user_email=user_email,
            action_type=BASActionType.CREATE.value if version == 1 else BASActionType.UPDATE.value,
            entity_type=BASEntityType.BAS_SUMMARY.value,
            entity_id=str(bas.id),
            old_value=existing.to_dict() if existing else None,
            new_value=bas.to_dict(),
            reason=f"BAS {'created' if version == 1 else 'updated'} - version {version}"
        )
        
        logger.info(f"BAS saved: {bas.id} (version {version})")
        
        return bas.to_dict()
    
    async def get_bas(self, bas_id: str) -> Optional[Dict[str, Any]]:
        """Get a single BAS statement by ID"""
        result = await self.db.execute(
            select(BASStatementDB).where(BASStatementDB.id == uuid.UUID(bas_id))
        )
        bas = result.scalar_one_or_none()
        
        if not bas:
            return None
        
        # Get change log for this BAS
        log_result = await self.db.execute(
            select(BASChangeLogDB)
            .where(BASChangeLogDB.bas_statement_id == uuid.UUID(bas_id))
            .order_by(desc(BASChangeLogDB.timestamp))
        )
        change_logs = [log.to_dict() for log in log_result.scalars().all()]
        
        bas_dict = bas.to_dict()
        bas_dict["change_log"] = change_logs
        
        return bas_dict
    
    async def get_history(
        self,
        client_id: str,
        job_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get BAS history for a client"""
        query = select(BASStatementDB).where(BASStatementDB.client_id == client_id)
        
        if job_id:
            query = query.where(BASStatementDB.job_id == job_id)
        
        query = query.order_by(desc(BASStatementDB.period_to), desc(BASStatementDB.version))
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        statements = result.scalars().all()
        
        return [s.to_dict() for s in statements]
    
    async def sign_off(
        self,
        bas_id: str,
        user_id: str,
        user_email: Optional[str] = None,
        review_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Sign off on a BAS statement"""
        result = await self.db.execute(
            select(BASStatementDB).where(BASStatementDB.id == uuid.UUID(bas_id))
        )
        bas = result.scalar_one_or_none()
        
        if not bas:
            raise ValueError(f"BAS {bas_id} not found")
        
        old_value = bas.to_dict()
        
        # Update sign-off fields
        bas.completed_by = user_id
        bas.completed_by_email = user_email
        bas.completed_at = datetime.now(timezone.utc)
        bas.status = BASStatus.COMPLETED.value
        if review_notes:
            bas.review_notes = review_notes
        
        await self.db.commit()
        await self.db.refresh(bas)
        
        # Log the sign-off
        await self._log_change(
            bas_statement_id=bas.id,
            client_id=bas.client_id,
            job_id=bas.job_id,
            user_id=user_id,
            user_email=user_email,
            action_type=BASActionType.SIGN_OFF.value,
            entity_type=BASEntityType.BAS_SUMMARY.value,
            entity_id=str(bas.id),
            old_value=old_value,
            new_value=bas.to_dict(),
            reason=review_notes or "BAS signed off"
        )
        
        return bas.to_dict()
    
    async def generate_pdf_data(self, bas_id: str) -> Dict[str, Any]:
        """
        Generate PDF data for a BAS statement.
        Returns structured JSON for frontend PDF generation.
        """
        result = await self.db.execute(
            select(BASStatementDB).where(BASStatementDB.id == uuid.UUID(bas_id))
        )
        bas = result.scalar_one_or_none()
        
        if not bas:
            raise ValueError(f"BAS {bas_id} not found")
        
        # Structure for PDF generation
        pdf_data = {
            "document_type": "BAS",
            "document_title": "Business Activity Statement",
            "period": {
                "from": bas.period_from.isoformat() if bas.period_from else None,
                "to": bas.period_to.isoformat() if bas.period_to else None,
                "label": f"{bas.period_from.strftime('%d %b %Y')} to {bas.period_to.strftime('%d %b %Y')}" if bas.period_from and bas.period_to else None,
            },
            "client_id": bas.client_id,
            "job_id": bas.job_id,
            "version": bas.version,
            "status": bas.status,
            
            # GST Section
            "gst": {
                "g1_total_sales": float(bas.g1_total_income or 0),
                "g2_export_sales": float(bas.g2_export_sales or 0),
                "g3_gst_free_sales": float(bas.g3_gst_free_sales or 0),
                "1a_gst_on_sales": float(bas.gst_on_income_1a or 0),
                "1b_gst_on_purchases": float(bas.gst_on_expenses_1b or 0),
                "g10_capital_purchases": float(bas.g10_capital_purchases or 0),
                "g11_non_capital_purchases": float(bas.g11_non_capital_purchases or 0),
                "net_gst": float(bas.net_gst or 0),
            },
            
            # PAYG Section
            "payg": {
                "instalment": float(bas.payg_instalment or 0),
            },
            
            # Summary
            "summary": {
                "total_payable": float(bas.total_payable or 0),
                "notes": bas.notes,
            },
            
            # Sign-off
            "sign_off": {
                "completed_by": bas.completed_by,
                "completed_by_email": bas.completed_by_email,
                "completed_at": bas.completed_at.isoformat() if bas.completed_at else None,
                "review_notes": bas.review_notes,
            },
            
            # Metadata
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "bas_id": str(bas.id),
                "created_at": bas.created_at.isoformat() if bas.created_at else None,
            }
        }
        
        return pdf_data
    
    async def _get_latest_for_period(
        self,
        client_id: str,
        period_from: date,
        period_to: date
    ) -> Optional[BASStatementDB]:
        """Get the latest BAS for a specific period"""
        result = await self.db.execute(
            select(BASStatementDB)
            .where(and_(
                BASStatementDB.client_id == client_id,
                BASStatementDB.period_from == period_from,
                BASStatementDB.period_to == period_to
            ))
            .order_by(desc(BASStatementDB.version))
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    async def _log_change(
        self,
        client_id: str,
        user_id: str,
        action_type: str,
        entity_type: str,
        bas_statement_id: Optional[uuid.UUID] = None,
        job_id: Optional[str] = None,
        user_email: Optional[str] = None,
        entity_id: Optional[str] = None,
        old_value: Optional[Dict] = None,
        new_value: Optional[Dict] = None,
        reason: Optional[str] = None
    ):
        """Internal helper to log changes"""
        log = BASChangeLogDB(
            bas_statement_id=bas_statement_id,
            client_id=client_id,
            job_id=job_id,
            user_id=user_id,
            user_email=user_email,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            reason=reason
        )
        self.db.add(log)
        await self.db.commit()


# ==================== BAS CHANGE LOG SERVICE ====================

class BASChangeLogService:
    """Service for managing BAS change logs"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def log_change(
        self,
        client_id: str,
        user_id: str,
        action_type: str,
        entity_type: str,
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
        bas_statement_id: Optional[str] = None,
        job_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        old_value: Optional[Dict] = None,
        new_value: Optional[Dict] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Log a change to the BAS change log.
        """
        log = BASChangeLogDB(
            bas_statement_id=uuid.UUID(bas_statement_id) if bas_statement_id else None,
            client_id=client_id,
            job_id=job_id,
            user_id=user_id,
            user_email=user_email,
            user_role=user_role,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            reason=reason
        )
        
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        
        logger.info(f"Change logged: {action_type} on {entity_type} by {user_id}")
        
        return log.to_dict()
    
    async def get_change_log(
        self,
        client_id: Optional[str] = None,
        job_id: Optional[str] = None,
        bas_statement_id: Optional[str] = None,
        action_type: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Get change log entries with filters.
        """
        query = select(BASChangeLogDB)
        
        if client_id:
            query = query.where(BASChangeLogDB.client_id == client_id)
        if job_id:
            query = query.where(BASChangeLogDB.job_id == job_id)
        if bas_statement_id:
            query = query.where(BASChangeLogDB.bas_statement_id == uuid.UUID(bas_statement_id))
        if action_type:
            query = query.where(BASChangeLogDB.action_type == action_type)
        if entity_type:
            query = query.where(BASChangeLogDB.entity_type == entity_type)
        
        query = query.order_by(desc(BASChangeLogDB.timestamp))
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        logs = result.scalars().all()
        
        return [log.to_dict() for log in logs]
