"""
MyFDC Data Intake Service

Handles storage of all MyFDC-generated data in the Core database.
Data flows: MyFDC → Core → CRM → Bookkeeping → Workpapers

Data Types:
- Educator Profile
- Hours Worked
- Occupancy
- Diary Entries
- Expenses
- Attendance

All data is stored under a unified client_id.
"""

import uuid
import json
import logging
from datetime import datetime, timezone, date
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


# ==================== AUDIT EVENTS ====================

class MyFDCAuditEvent:
    """Audit event types for MyFDC data intake."""
    DATA_RECEIVED = "myfdc_data_received"
    PROFILE_UPDATE = "myfdc_profile_update"
    HOURS_LOGGED = "myfdc_hours_logged"
    OCCUPANCY_LOGGED = "myfdc_occupancy_logged"
    DIARY_CREATED = "myfdc_diary_created"
    EXPENSE_LOGGED = "myfdc_expense_logged"
    ATTENDANCE_LOGGED = "myfdc_attendance_logged"


def log_myfdc_event(
    event_type: str,
    client_id: str,
    record_id: str,
    service_name: str,
    data_summary: Dict[str, Any],
    success: bool = True
):
    """
    Log MyFDC data intake event for audit trail.
    
    SECURITY: Removes sensitive fields before logging.
    """
    # Sanitize - remove sensitive fields
    safe_summary = {k: v for k, v in data_summary.items() 
                    if k not in ('abn', 'tfn', 'bank_account', 'wwcc_number')}
    
    # Mask ABN if present
    if 'abn' in data_summary and data_summary['abn']:
        safe_summary['abn_masked'] = f"***{str(data_summary['abn'])[-4:]}"
    
    log_entry = {
        "event": event_type,
        "client_id": client_id,
        "record_id": record_id,
        "service": service_name,
        "summary": safe_summary,
        "success": success,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    if success:
        logger.info(f"MyFDC: {event_type} for client {client_id}", extra=log_entry)
    else:
        logger.warning(f"MyFDC FAILED: {event_type} for client {client_id}", extra=log_entry)


# ==================== DATA INTAKE SERVICE ====================

class MyFDCIntakeService:
    """
    Service for receiving and storing MyFDC data.
    
    All data is stored in a unified structure that can be queried
    by CRM, Bookkeeping, and Workpapers.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def verify_client_exists(self, client_id: str) -> bool:
        """Verify that a client exists in Core."""
        query = text("""
            SELECT id FROM public.client_profiles 
            WHERE id = :client_id
        """)
        result = await self.db.execute(query, {'client_id': client_id})
        return result.fetchone() is not None
    
    # ==================== EDUCATOR PROFILE ====================
    
    async def update_educator_profile(
        self,
        client_id: str,
        profile_data: Dict[str, Any],
        service_name: str = "myfdc"
    ) -> Dict[str, Any]:
        """
        Update educator profile for a client.
        
        Creates or updates the educator profile linked to the client.
        """
        record_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Check if profile exists
        existing = await self._get_educator_profile(client_id)
        
        if existing:
            # Update existing profile
            query = text("""
                UPDATE public.myfdc_educator_profiles SET
                    educator_name = :educator_name,
                    phone = :phone,
                    email = :email,
                    address_line1 = :address_line1,
                    address_line2 = :address_line2,
                    suburb = :suburb,
                    state = :state,
                    postcode = :postcode,
                    abn = :abn,
                    service_approval_number = :service_approval_number,
                    approval_start_date = :approval_start_date,
                    approval_expiry_date = :approval_expiry_date,
                    max_children = :max_children,
                    qualifications = :qualifications,
                    first_aid_expiry = :first_aid_expiry,
                    wwcc_number = :wwcc_number,
                    wwcc_expiry = :wwcc_expiry,
                    updated_at = :updated_at,
                    updated_by = :updated_by
                WHERE client_id = :client_id
                RETURNING id
            """)
            record_id = existing['id']
        else:
            # Create new profile
            query = text("""
                INSERT INTO public.myfdc_educator_profiles (
                    id, client_id, educator_name, phone, email,
                    address_line1, address_line2, suburb, state, postcode,
                    abn, service_approval_number, approval_start_date,
                    approval_expiry_date, max_children, qualifications,
                    first_aid_expiry, wwcc_number, wwcc_expiry,
                    created_at, updated_at, created_by, updated_by
                ) VALUES (
                    :id, :client_id, :educator_name, :phone, :email,
                    :address_line1, :address_line2, :suburb, :state, :postcode,
                    :abn, :service_approval_number, :approval_start_date,
                    :approval_expiry_date, :max_children, :qualifications,
                    :first_aid_expiry, :wwcc_number, :wwcc_expiry,
                    :created_at, :updated_at, :created_by, :updated_by
                )
            """)
        
        params = {
            'id': record_id,
            'client_id': client_id,
            'educator_name': profile_data.get('educator_name'),
            'phone': profile_data.get('phone'),
            'email': profile_data.get('email'),
            'address_line1': profile_data.get('address_line1'),
            'address_line2': profile_data.get('address_line2'),
            'suburb': profile_data.get('suburb'),
            'state': profile_data.get('state'),
            'postcode': profile_data.get('postcode'),
            'abn': profile_data.get('abn'),
            'service_approval_number': profile_data.get('service_approval_number'),
            'approval_start_date': profile_data.get('approval_start_date'),
            'approval_expiry_date': profile_data.get('approval_expiry_date'),
            'max_children': profile_data.get('max_children'),
            'qualifications': json.dumps(profile_data.get('qualifications', [])),
            'first_aid_expiry': profile_data.get('first_aid_expiry'),
            'wwcc_number': profile_data.get('wwcc_number'),
            'wwcc_expiry': profile_data.get('wwcc_expiry'),
            'created_at': now,
            'updated_at': now,
            'created_by': service_name,
            'updated_by': service_name
        }
        
        try:
            await self.db.execute(query, params)
            await self.db.commit()
            
            log_myfdc_event(
                MyFDCAuditEvent.PROFILE_UPDATE,
                client_id, record_id, service_name,
                {"educator_name": profile_data.get('educator_name'), "action": "update" if existing else "create"}
            )
            
            return {
                "success": True,
                "record_id": record_id,
                "client_id": client_id,
                "data_type": "educator_profile",
                "message": "Educator profile updated successfully"
            }
            
        except Exception as e:
            logger.error(f"Failed to update educator profile: {e}")
            await self.db.rollback()
            raise
    
    async def _get_educator_profile(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Get existing educator profile."""
        query = text("""
            SELECT id FROM public.myfdc_educator_profiles
            WHERE client_id = :client_id
        """)
        result = await self.db.execute(query, {'client_id': client_id})
        row = result.fetchone()
        return {'id': str(row.id)} if row else None
    
    # ==================== HOURS WORKED ====================
    
    async def log_hours_worked(
        self,
        client_id: str,
        hours_data: Dict[str, Any],
        service_name: str = "myfdc"
    ) -> Dict[str, Any]:
        """Log hours worked for an educator."""
        record_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        query = text("""
            INSERT INTO public.myfdc_hours_worked (
                id, client_id, work_date, hours, start_time, end_time,
                notes, created_at, created_by
            ) VALUES (
                :id, :client_id, :work_date, :hours, :start_time, :end_time,
                :notes, :created_at, :created_by
            )
        """)
        
        try:
            await self.db.execute(query, {
                'id': record_id,
                'client_id': client_id,
                'work_date': hours_data.get('date'),
                'hours': hours_data.get('hours'),
                'start_time': hours_data.get('start_time'),
                'end_time': hours_data.get('end_time'),
                'notes': hours_data.get('notes'),
                'created_at': now,
                'created_by': service_name
            })
            await self.db.commit()
            
            log_myfdc_event(
                MyFDCAuditEvent.HOURS_LOGGED,
                client_id, record_id, service_name,
                {"date": str(hours_data.get('date')), "hours": hours_data.get('hours')}
            )
            
            return {
                "success": True,
                "record_id": record_id,
                "client_id": client_id,
                "data_type": "hours_worked",
                "message": "Hours logged successfully"
            }
            
        except Exception as e:
            logger.error(f"Failed to log hours: {e}")
            await self.db.rollback()
            raise
    
    # ==================== OCCUPANCY ====================
    
    async def log_occupancy(
        self,
        client_id: str,
        occupancy_data: Dict[str, Any],
        service_name: str = "myfdc"
    ) -> Dict[str, Any]:
        """Log occupancy data for an educator."""
        record_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        query = text("""
            INSERT INTO public.myfdc_occupancy (
                id, client_id, occupancy_date, number_of_children,
                hours_per_day, rooms_used, room_details,
                preschool_program, notes, created_at, created_by
            ) VALUES (
                :id, :client_id, :occupancy_date, :number_of_children,
                :hours_per_day, :rooms_used, :room_details,
                :preschool_program, :notes, :created_at, :created_by
            )
        """)
        
        try:
            await self.db.execute(query, {
                'id': record_id,
                'client_id': client_id,
                'occupancy_date': occupancy_data.get('date'),
                'number_of_children': occupancy_data.get('number_of_children'),
                'hours_per_day': occupancy_data.get('hours_per_day'),
                'rooms_used': json.dumps(occupancy_data.get('rooms_used', [])),
                'room_details': json.dumps(occupancy_data.get('room_details', [])),
                'preschool_program': occupancy_data.get('preschool_program', False),
                'notes': occupancy_data.get('notes'),
                'created_at': now,
                'created_by': service_name
            })
            await self.db.commit()
            
            log_myfdc_event(
                MyFDCAuditEvent.OCCUPANCY_LOGGED,
                client_id, record_id, service_name,
                {"date": str(occupancy_data.get('date')), "children": occupancy_data.get('number_of_children')}
            )
            
            return {
                "success": True,
                "record_id": record_id,
                "client_id": client_id,
                "data_type": "occupancy",
                "message": "Occupancy logged successfully"
            }
            
        except Exception as e:
            logger.error(f"Failed to log occupancy: {e}")
            await self.db.rollback()
            raise
    
    # ==================== DIARY ENTRIES ====================
    
    async def create_diary_entry(
        self,
        client_id: str,
        diary_data: Dict[str, Any],
        service_name: str = "myfdc"
    ) -> Dict[str, Any]:
        """Create a diary entry."""
        record_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        query = text("""
            INSERT INTO public.myfdc_diary_entries (
                id, client_id, entry_date, description, category,
                child_name, has_photos, photo_count,
                created_at, created_by
            ) VALUES (
                :id, :client_id, :entry_date, :description, :category,
                :child_name, :has_photos, :photo_count,
                :created_at, :created_by
            )
        """)
        
        try:
            await self.db.execute(query, {
                'id': record_id,
                'client_id': client_id,
                'entry_date': diary_data.get('date'),
                'description': diary_data.get('description'),
                'category': diary_data.get('category', 'activity'),
                'child_name': diary_data.get('child_name'),
                'has_photos': diary_data.get('has_photos', False),
                'photo_count': diary_data.get('photo_count', 0),
                'created_at': now,
                'created_by': service_name
            })
            await self.db.commit()
            
            log_myfdc_event(
                MyFDCAuditEvent.DIARY_CREATED,
                client_id, record_id, service_name,
                {"date": str(diary_data.get('date')), "category": diary_data.get('category')}
            )
            
            return {
                "success": True,
                "record_id": record_id,
                "client_id": client_id,
                "data_type": "diary_entry",
                "message": "Diary entry created successfully"
            }
            
        except Exception as e:
            logger.error(f"Failed to create diary entry: {e}")
            await self.db.rollback()
            raise
    
    # ==================== EXPENSES ====================
    
    async def log_expense(
        self,
        client_id: str,
        expense_data: Dict[str, Any],
        service_name: str = "myfdc"
    ) -> Dict[str, Any]:
        """Log an expense."""
        record_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        query = text("""
            INSERT INTO public.myfdc_expenses (
                id, client_id, expense_date, amount, category,
                description, gst_included, tax_deductible,
                business_percentage, receipt_number, vendor,
                created_at, created_by
            ) VALUES (
                :id, :client_id, :expense_date, :amount, :category,
                :description, :gst_included, :tax_deductible,
                :business_percentage, :receipt_number, :vendor,
                :created_at, :created_by
            )
        """)
        
        try:
            await self.db.execute(query, {
                'id': record_id,
                'client_id': client_id,
                'expense_date': expense_data.get('date'),
                'amount': expense_data.get('amount'),
                'category': expense_data.get('category'),
                'description': expense_data.get('description'),
                'gst_included': expense_data.get('gst_included', True),
                'tax_deductible': expense_data.get('tax_deductible', True),
                'business_percentage': expense_data.get('business_percentage', 100),
                'receipt_number': expense_data.get('receipt_number'),
                'vendor': expense_data.get('vendor'),
                'created_at': now,
                'created_by': service_name
            })
            await self.db.commit()
            
            log_myfdc_event(
                MyFDCAuditEvent.EXPENSE_LOGGED,
                client_id, record_id, service_name,
                {"date": str(expense_data.get('date')), "amount": expense_data.get('amount'), "category": expense_data.get('category')}
            )
            
            return {
                "success": True,
                "record_id": record_id,
                "client_id": client_id,
                "data_type": "expense",
                "message": "Expense logged successfully"
            }
            
        except Exception as e:
            logger.error(f"Failed to log expense: {e}")
            await self.db.rollback()
            raise
    
    # ==================== ATTENDANCE ====================
    
    async def log_attendance(
        self,
        client_id: str,
        attendance_data: Dict[str, Any],
        service_name: str = "myfdc"
    ) -> Dict[str, Any]:
        """Log child attendance."""
        record_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        query = text("""
            INSERT INTO public.myfdc_attendance (
                id, client_id, child_name, attendance_date, hours,
                arrival_time, departure_time, ccs_hours,
                notes, absent, absence_reason,
                created_at, created_by
            ) VALUES (
                :id, :client_id, :child_name, :attendance_date, :hours,
                :arrival_time, :departure_time, :ccs_hours,
                :notes, :absent, :absence_reason,
                :created_at, :created_by
            )
        """)
        
        try:
            await self.db.execute(query, {
                'id': record_id,
                'client_id': client_id,
                'child_name': attendance_data.get('child_name'),
                'attendance_date': attendance_data.get('date'),
                'hours': attendance_data.get('hours'),
                'arrival_time': attendance_data.get('arrival_time'),
                'departure_time': attendance_data.get('departure_time'),
                'ccs_hours': attendance_data.get('ccs_hours'),
                'notes': attendance_data.get('notes'),
                'absent': attendance_data.get('absent', False),
                'absence_reason': attendance_data.get('absence_reason'),
                'created_at': now,
                'created_by': service_name
            })
            await self.db.commit()
            
            log_myfdc_event(
                MyFDCAuditEvent.ATTENDANCE_LOGGED,
                client_id, record_id, service_name,
                {"date": str(attendance_data.get('date')), "child": attendance_data.get('child_name'), "hours": attendance_data.get('hours')}
            )
            
            return {
                "success": True,
                "record_id": record_id,
                "client_id": client_id,
                "data_type": "attendance",
                "message": "Attendance logged successfully"
            }
            
        except Exception as e:
            logger.error(f"Failed to log attendance: {e}")
            await self.db.rollback()
            raise
    
    # ==================== QUERY METHODS (for CRM) ====================
    
    async def get_hours_summary(
        self,
        client_id: str,
        start_date: date,
        end_date: date
    ) -> Dict[str, Any]:
        """Get hours worked summary for a date range."""
        query = text("""
            SELECT 
                COUNT(*) as days_worked,
                SUM(hours) as total_hours,
                AVG(hours) as avg_hours_per_day
            FROM public.myfdc_hours_worked
            WHERE client_id = :client_id
            AND work_date >= :start_date
            AND work_date <= :end_date
        """)
        
        result = await self.db.execute(query, {
            'client_id': client_id,
            'start_date': start_date,
            'end_date': end_date
        })
        row = result.fetchone()
        
        return {
            "client_id": client_id,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "days_worked": row.days_worked or 0,
            "total_hours": float(row.total_hours or 0),
            "avg_hours_per_day": round(float(row.avg_hours_per_day or 0), 2)
        }
    
    async def get_expenses_summary(
        self,
        client_id: str,
        start_date: date,
        end_date: date
    ) -> Dict[str, Any]:
        """Get expenses summary for a date range."""
        query = text("""
            SELECT 
                category,
                COUNT(*) as count,
                SUM(amount) as total,
                SUM(amount * business_percentage / 100) as business_total
            FROM public.myfdc_expenses
            WHERE client_id = :client_id
            AND expense_date >= :start_date
            AND expense_date <= :end_date
            GROUP BY category
        """)
        
        result = await self.db.execute(query, {
            'client_id': client_id,
            'start_date': start_date,
            'end_date': end_date
        })
        rows = result.fetchall()
        
        by_category = {
            row.category: {
                "count": row.count,
                "total": float(row.total),
                "business_total": float(row.business_total)
            }
            for row in rows
        }
        
        total = sum(c['total'] for c in by_category.values())
        business_total = sum(c['business_total'] for c in by_category.values())
        
        return {
            "client_id": client_id,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "by_category": by_category,
            "total": round(total, 2),
            "business_total": round(business_total, 2)
        }
