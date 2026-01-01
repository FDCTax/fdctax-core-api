"""
CRM Bookkeeping Data Access Service

Provides read-only access to MyFDC data stored in Core for CRM Bookkeeping.
Powers the CRM Bookkeeping UI and Workpapers.

Data Types Retrieved:
- Hours Worked
- Occupancy
- Diary Entries
- Expenses
- Attendance

All data is grouped by client_id with support for date range filtering
and aggregation summaries.
"""

import json
import logging
from datetime import datetime, timezone, date, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


# ==================== AUDIT EVENTS ====================

class BookkeepingAuditEvent:
    """Audit event types for CRM bookkeeping data access."""
    HOURS_ACCESS = "crm_bookkeeping_hours_access"
    OCCUPANCY_ACCESS = "crm_bookkeeping_occupancy_access"
    DIARY_ACCESS = "crm_bookkeeping_diary_access"
    EXPENSES_ACCESS = "crm_bookkeeping_expenses_access"
    ATTENDANCE_ACCESS = "crm_bookkeeping_attendance_access"
    SUMMARY_ACCESS = "crm_bookkeeping_summary_access"


def log_bookkeeping_access(
    event_type: str,
    client_id: str,
    service_name: str,
    query_params: Dict[str, Any],
    record_count: int,
    success: bool = True
):
    """
    Log CRM bookkeeping data access for audit trail.
    
    SECURITY: No sensitive educator data logged.
    """
    log_entry = {
        "event": event_type,
        "client_id": client_id,
        "service": service_name,
        "query_params": {k: str(v) for k, v in query_params.items() if v is not None},
        "record_count": record_count,
        "success": success,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    if success:
        logger.info(f"CRM Bookkeeping: {event_type} for client {client_id}, {record_count} records", extra=log_entry)
    else:
        logger.warning(f"CRM Bookkeeping FAILED: {event_type} for client {client_id}", extra=log_entry)


# ==================== RESPONSE MODELS ====================

@dataclass
class HoursRecord:
    """Hours worked record."""
    id: str
    work_date: str
    hours: float
    start_time: Optional[str]
    end_time: Optional[str]
    notes: Optional[str]
    created_at: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OccupancyRecord:
    """Occupancy record."""
    id: str
    occupancy_date: str
    number_of_children: int
    hours_per_day: float
    rooms_used: List[str]
    preschool_program: bool
    notes: Optional[str]
    created_at: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DiaryRecord:
    """Diary entry record."""
    id: str
    entry_date: str
    description: str
    category: str
    child_name: Optional[str]
    has_photos: bool
    photo_count: int
    created_at: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExpenseRecord:
    """Expense record."""
    id: str
    expense_date: str
    amount: float
    category: str
    description: Optional[str]
    gst_included: bool
    tax_deductible: bool
    business_percentage: float
    business_amount: float
    receipt_number: Optional[str]
    vendor: Optional[str]
    created_at: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AttendanceRecord:
    """Attendance record."""
    id: str
    child_name: str
    attendance_date: str
    hours: float
    arrival_time: Optional[str]
    departure_time: Optional[str]
    ccs_hours: Optional[float]
    absent: bool
    absence_reason: Optional[str]
    notes: Optional[str]
    created_at: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ==================== BOOKKEEPING SERVICE ====================

class BookkeepingService:
    """
    CRM Bookkeeping Data Access Service.
    
    Provides read-only access to all MyFDC data stored in Core.
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
    
    # ==================== HOURS WORKED ====================
    
    async def get_hours_worked(
        self,
        client_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        service_name: str = "crm"
    ) -> Dict[str, Any]:
        """
        Get hours worked records for a client.
        
        Returns list of records plus aggregated totals.
        """
        # Build query with optional date filters
        query_parts = ["""
            SELECT id, work_date, hours, start_time, end_time, notes, created_at
            FROM public.myfdc_hours_worked
            WHERE client_id = :client_id
        """]
        params = {'client_id': client_id}
        
        if start_date:
            query_parts.append("AND work_date >= :start_date")
            params['start_date'] = start_date
        if end_date:
            query_parts.append("AND work_date <= :end_date")
            params['end_date'] = end_date
        
        query_parts.append("ORDER BY work_date DESC")
        
        query = text(" ".join(query_parts))
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        records = [
            HoursRecord(
                id=str(row.id),
                work_date=str(row.work_date),
                hours=float(row.hours),
                start_time=row.start_time,
                end_time=row.end_time,
                notes=row.notes,
                created_at=row.created_at.isoformat() if row.created_at else None
            ).to_dict()
            for row in rows
        ]
        
        # Calculate aggregates
        total_hours = sum(r['hours'] for r in records)
        days_worked = len(records)
        avg_hours = round(total_hours / days_worked, 2) if days_worked > 0 else 0
        
        log_bookkeeping_access(
            BookkeepingAuditEvent.HOURS_ACCESS,
            client_id, service_name,
            {'start_date': start_date, 'end_date': end_date},
            len(records)
        )
        
        return {
            "client_id": client_id,
            "records": records,
            "summary": {
                "total_hours": round(total_hours, 2),
                "days_worked": days_worked,
                "avg_hours_per_day": avg_hours
            },
            "filters": {
                "start_date": str(start_date) if start_date else None,
                "end_date": str(end_date) if end_date else None
            }
        }
    
    # ==================== OCCUPANCY ====================
    
    async def get_occupancy(
        self,
        client_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        service_name: str = "crm"
    ) -> Dict[str, Any]:
        """
        Get occupancy records for a client.
        
        Returns list of records plus weekly/monthly summaries.
        """
        query_parts = ["""
            SELECT id, occupancy_date, number_of_children, hours_per_day,
                   rooms_used, preschool_program, notes, created_at
            FROM public.myfdc_occupancy
            WHERE client_id = :client_id
        """]
        params = {'client_id': client_id}
        
        if start_date:
            query_parts.append("AND occupancy_date >= :start_date")
            params['start_date'] = start_date
        if end_date:
            query_parts.append("AND occupancy_date <= :end_date")
            params['end_date'] = end_date
        
        query_parts.append("ORDER BY occupancy_date DESC")
        
        query = text(" ".join(query_parts))
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        records = [
            OccupancyRecord(
                id=str(row.id),
                occupancy_date=str(row.occupancy_date),
                number_of_children=row.number_of_children,
                hours_per_day=float(row.hours_per_day),
                rooms_used=json.loads(row.rooms_used) if row.rooms_used else [],
                preschool_program=row.preschool_program or False,
                notes=row.notes,
                created_at=row.created_at.isoformat() if row.created_at else None
            ).to_dict()
            for row in rows
        ]
        
        # Calculate summaries
        total_child_days = sum(r['number_of_children'] for r in records)
        total_hours = sum(r['hours_per_day'] for r in records)
        days_with_preschool = sum(1 for r in records if r['preschool_program'])
        avg_children = round(total_child_days / len(records), 1) if records else 0
        
        # Room usage breakdown
        room_usage = {}
        for r in records:
            for room in r['rooms_used']:
                room_usage[room] = room_usage.get(room, 0) + 1
        
        log_bookkeeping_access(
            BookkeepingAuditEvent.OCCUPANCY_ACCESS,
            client_id, service_name,
            {'start_date': start_date, 'end_date': end_date},
            len(records)
        )
        
        return {
            "client_id": client_id,
            "records": records,
            "summary": {
                "total_days": len(records),
                "total_child_days": total_child_days,
                "total_care_hours": round(total_hours, 2),
                "avg_children_per_day": avg_children,
                "days_with_preschool_program": days_with_preschool,
                "room_usage_count": room_usage
            },
            "filters": {
                "start_date": str(start_date) if start_date else None,
                "end_date": str(end_date) if end_date else None
            }
        }
    
    # ==================== DIARY ENTRIES ====================
    
    async def get_diary_entries(
        self,
        client_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        category: Optional[str] = None,
        service_name: str = "crm"
    ) -> Dict[str, Any]:
        """
        Get diary entries for a client.
        
        Supports filtering by date range and category.
        """
        query_parts = ["""
            SELECT id, entry_date, description, category, child_name,
                   has_photos, photo_count, created_at
            FROM public.myfdc_diary_entries
            WHERE client_id = :client_id
        """]
        params = {'client_id': client_id}
        
        if start_date:
            query_parts.append("AND entry_date >= :start_date")
            params['start_date'] = start_date
        if end_date:
            query_parts.append("AND entry_date <= :end_date")
            params['end_date'] = end_date
        if category:
            query_parts.append("AND category = :category")
            params['category'] = category
        
        query_parts.append("ORDER BY entry_date DESC, created_at DESC")
        
        query = text(" ".join(query_parts))
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        records = [
            DiaryRecord(
                id=str(row.id),
                entry_date=str(row.entry_date),
                description=row.description,
                category=row.category or 'activity',
                child_name=row.child_name,
                has_photos=row.has_photos or False,
                photo_count=row.photo_count or 0,
                created_at=row.created_at.isoformat() if row.created_at else None
            ).to_dict()
            for row in rows
        ]
        
        # Category breakdown
        category_counts = {}
        total_photos = 0
        for r in records:
            cat = r['category']
            category_counts[cat] = category_counts.get(cat, 0) + 1
            total_photos += r['photo_count']
        
        log_bookkeeping_access(
            BookkeepingAuditEvent.DIARY_ACCESS,
            client_id, service_name,
            {'start_date': start_date, 'end_date': end_date, 'category': category},
            len(records)
        )
        
        return {
            "client_id": client_id,
            "records": records,
            "summary": {
                "total_entries": len(records),
                "entries_with_photos": sum(1 for r in records if r['has_photos']),
                "total_photos": total_photos,
                "by_category": category_counts
            },
            "filters": {
                "start_date": str(start_date) if start_date else None,
                "end_date": str(end_date) if end_date else None,
                "category": category
            }
        }
    
    # ==================== EXPENSES ====================
    
    async def get_expenses(
        self,
        client_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        category: Optional[str] = None,
        service_name: str = "crm"
    ) -> Dict[str, Any]:
        """
        Get expense records for a client.
        
        Returns list of expenses with GST flags, business %, and category breakdown.
        """
        query_parts = ["""
            SELECT id, expense_date, amount, category, description,
                   gst_included, tax_deductible, business_percentage,
                   receipt_number, vendor, created_at
            FROM public.myfdc_expenses
            WHERE client_id = :client_id
        """]
        params = {'client_id': client_id}
        
        if start_date:
            query_parts.append("AND expense_date >= :start_date")
            params['start_date'] = start_date
        if end_date:
            query_parts.append("AND expense_date <= :end_date")
            params['end_date'] = end_date
        if category:
            query_parts.append("AND category = :category")
            params['category'] = category
        
        query_parts.append("ORDER BY expense_date DESC")
        
        query = text(" ".join(query_parts))
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        records = []
        for row in rows:
            amount = float(row.amount)
            business_pct = float(row.business_percentage or 100)
            business_amount = round(amount * business_pct / 100, 2)
            
            records.append(ExpenseRecord(
                id=str(row.id),
                expense_date=str(row.expense_date),
                amount=amount,
                category=row.category,
                description=row.description,
                gst_included=row.gst_included if row.gst_included is not None else True,
                tax_deductible=row.tax_deductible if row.tax_deductible is not None else True,
                business_percentage=business_pct,
                business_amount=business_amount,
                receipt_number=row.receipt_number,
                vendor=row.vendor,
                created_at=row.created_at.isoformat() if row.created_at else None
            ).to_dict())
        
        # Calculate totals and category breakdown
        total_amount = sum(r['amount'] for r in records)
        total_business = sum(r['business_amount'] for r in records)
        total_with_gst = sum(r['amount'] for r in records if r['gst_included'])
        total_deductible = sum(r['business_amount'] for r in records if r['tax_deductible'])
        
        by_category = {}
        for r in records:
            cat = r['category']
            if cat not in by_category:
                by_category[cat] = {'count': 0, 'total': 0, 'business_total': 0}
            by_category[cat]['count'] += 1
            by_category[cat]['total'] = round(by_category[cat]['total'] + r['amount'], 2)
            by_category[cat]['business_total'] = round(by_category[cat]['business_total'] + r['business_amount'], 2)
        
        log_bookkeeping_access(
            BookkeepingAuditEvent.EXPENSES_ACCESS,
            client_id, service_name,
            {'start_date': start_date, 'end_date': end_date, 'category': category},
            len(records)
        )
        
        return {
            "client_id": client_id,
            "records": records,
            "summary": {
                "total_expenses": len(records),
                "total_amount": round(total_amount, 2),
                "total_business_amount": round(total_business, 2),
                "total_with_gst": round(total_with_gst, 2),
                "total_tax_deductible": round(total_deductible, 2),
                "by_category": by_category
            },
            "filters": {
                "start_date": str(start_date) if start_date else None,
                "end_date": str(end_date) if end_date else None,
                "category": category
            }
        }
    
    # ==================== ATTENDANCE ====================
    
    async def get_attendance(
        self,
        client_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        child_name: Optional[str] = None,
        service_name: str = "crm"
    ) -> Dict[str, Any]:
        """
        Get attendance records for a client.
        
        Returns child attendance with CCS hours and daily totals.
        """
        query_parts = ["""
            SELECT id, child_name, attendance_date, hours, arrival_time,
                   departure_time, ccs_hours, notes, absent, absence_reason, created_at
            FROM public.myfdc_attendance
            WHERE client_id = :client_id
        """]
        params = {'client_id': client_id}
        
        if start_date:
            query_parts.append("AND attendance_date >= :start_date")
            params['start_date'] = start_date
        if end_date:
            query_parts.append("AND attendance_date <= :end_date")
            params['end_date'] = end_date
        if child_name:
            query_parts.append("AND child_name ILIKE :child_name")
            params['child_name'] = f"%{child_name}%"
        
        query_parts.append("ORDER BY attendance_date DESC, child_name")
        
        query = text(" ".join(query_parts))
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        records = [
            AttendanceRecord(
                id=str(row.id),
                child_name=row.child_name,
                attendance_date=str(row.attendance_date),
                hours=float(row.hours),
                arrival_time=row.arrival_time,
                departure_time=row.departure_time,
                ccs_hours=float(row.ccs_hours) if row.ccs_hours else None,
                absent=row.absent or False,
                absence_reason=row.absence_reason,
                notes=row.notes,
                created_at=row.created_at.isoformat() if row.created_at else None
            ).to_dict()
            for row in rows
        ]
        
        # Calculate summaries
        total_hours = sum(r['hours'] for r in records)
        total_ccs_hours = sum(r['ccs_hours'] or 0 for r in records)
        absences = sum(1 for r in records if r['absent'])
        
        # Per-child breakdown
        by_child = {}
        for r in records:
            name = r['child_name']
            if name not in by_child:
                by_child[name] = {'days': 0, 'total_hours': 0, 'ccs_hours': 0, 'absences': 0}
            by_child[name]['days'] += 1
            by_child[name]['total_hours'] = round(by_child[name]['total_hours'] + r['hours'], 2)
            by_child[name]['ccs_hours'] = round(by_child[name]['ccs_hours'] + (r['ccs_hours'] or 0), 2)
            if r['absent']:
                by_child[name]['absences'] += 1
        
        # Daily totals
        daily_totals = {}
        for r in records:
            d = r['attendance_date']
            if d not in daily_totals:
                daily_totals[d] = {'children': 0, 'total_hours': 0}
            daily_totals[d]['children'] += 1
            daily_totals[d]['total_hours'] = round(daily_totals[d]['total_hours'] + r['hours'], 2)
        
        log_bookkeeping_access(
            BookkeepingAuditEvent.ATTENDANCE_ACCESS,
            client_id, service_name,
            {'start_date': start_date, 'end_date': end_date, 'child_name': child_name},
            len(records)
        )
        
        return {
            "client_id": client_id,
            "records": records,
            "summary": {
                "total_records": len(records),
                "total_hours": round(total_hours, 2),
                "total_ccs_hours": round(total_ccs_hours, 2),
                "total_absences": absences,
                "unique_children": len(by_child),
                "by_child": by_child
            },
            "daily_totals": daily_totals,
            "filters": {
                "start_date": str(start_date) if start_date else None,
                "end_date": str(end_date) if end_date else None,
                "child_name": child_name
            }
        }
    
    # ==================== COMBINED SUMMARY ====================
    
    async def get_bookkeeping_summary(
        self,
        client_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        service_name: str = "crm"
    ) -> Dict[str, Any]:
        """
        Get combined bookkeeping summary for CRM dashboard.
        
        Aggregates all MyFDC data types into a single response.
        """
        # Set default date range if not provided (last 30 days)
        if not end_date:
            end_date = date.today()
        if not start_date:
            start_date = end_date - timedelta(days=30)
        
        # Get hours summary
        hours_query = text("""
            SELECT COUNT(*) as days, COALESCE(SUM(hours), 0) as total_hours
            FROM public.myfdc_hours_worked
            WHERE client_id = :client_id
            AND work_date >= :start_date AND work_date <= :end_date
        """)
        hours_result = await self.db.execute(hours_query, {
            'client_id': client_id, 'start_date': start_date, 'end_date': end_date
        })
        hours_row = hours_result.fetchone()
        
        # Get occupancy summary
        occupancy_query = text("""
            SELECT COUNT(*) as days, 
                   COALESCE(SUM(number_of_children), 0) as total_child_days,
                   COALESCE(SUM(hours_per_day), 0) as total_care_hours
            FROM public.myfdc_occupancy
            WHERE client_id = :client_id
            AND occupancy_date >= :start_date AND occupancy_date <= :end_date
        """)
        occupancy_result = await self.db.execute(occupancy_query, {
            'client_id': client_id, 'start_date': start_date, 'end_date': end_date
        })
        occupancy_row = occupancy_result.fetchone()
        
        # Get expense summary
        expense_query = text("""
            SELECT COUNT(*) as count, 
                   COALESCE(SUM(amount), 0) as total,
                   COALESCE(SUM(amount * business_percentage / 100), 0) as business_total
            FROM public.myfdc_expenses
            WHERE client_id = :client_id
            AND expense_date >= :start_date AND expense_date <= :end_date
        """)
        expense_result = await self.db.execute(expense_query, {
            'client_id': client_id, 'start_date': start_date, 'end_date': end_date
        })
        expense_row = expense_result.fetchone()
        
        # Get diary count
        diary_query = text("""
            SELECT COUNT(*) as count
            FROM public.myfdc_diary_entries
            WHERE client_id = :client_id
            AND entry_date >= :start_date AND entry_date <= :end_date
        """)
        diary_result = await self.db.execute(diary_query, {
            'client_id': client_id, 'start_date': start_date, 'end_date': end_date
        })
        diary_row = diary_result.fetchone()
        
        # Get attendance summary
        attendance_query = text("""
            SELECT COUNT(*) as records,
                   COUNT(DISTINCT child_name) as unique_children,
                   COALESCE(SUM(hours), 0) as total_hours,
                   COALESCE(SUM(ccs_hours), 0) as total_ccs_hours,
                   SUM(CASE WHEN absent THEN 1 ELSE 0 END) as absences
            FROM public.myfdc_attendance
            WHERE client_id = :client_id
            AND attendance_date >= :start_date AND attendance_date <= :end_date
        """)
        attendance_result = await self.db.execute(attendance_query, {
            'client_id': client_id, 'start_date': start_date, 'end_date': end_date
        })
        attendance_row = attendance_result.fetchone()
        
        # Get educator profile status
        profile_query = text("""
            SELECT educator_name, service_approval_number, max_children
            FROM public.myfdc_educator_profiles
            WHERE client_id = :client_id
        """)
        profile_result = await self.db.execute(profile_query, {'client_id': client_id})
        profile_row = profile_result.fetchone()
        
        summary = {
            "client_id": client_id,
            "period": {
                "start_date": str(start_date),
                "end_date": str(end_date)
            },
            "educator_profile": {
                "has_profile": profile_row is not None,
                "educator_name": profile_row.educator_name if profile_row else None,
                "service_approval": profile_row.service_approval_number if profile_row else None,
                "max_children": profile_row.max_children if profile_row else None
            },
            "hours_worked": {
                "days_worked": hours_row.days or 0,
                "total_hours": round(float(hours_row.total_hours or 0), 2)
            },
            "occupancy": {
                "days_recorded": occupancy_row.days or 0,
                "total_child_days": occupancy_row.total_child_days or 0,
                "total_care_hours": round(float(occupancy_row.total_care_hours or 0), 2)
            },
            "expenses": {
                "count": expense_row.count or 0,
                "total_amount": round(float(expense_row.total or 0), 2),
                "business_amount": round(float(expense_row.business_total or 0), 2)
            },
            "diary": {
                "entry_count": diary_row.count or 0
            },
            "attendance": {
                "total_records": attendance_row.records or 0,
                "unique_children": attendance_row.unique_children or 0,
                "total_hours": round(float(attendance_row.total_hours or 0), 2),
                "total_ccs_hours": round(float(attendance_row.total_ccs_hours or 0), 2),
                "absences": attendance_row.absences or 0
            },
            "data_completeness": {
                "has_hours": (hours_row.days or 0) > 0,
                "has_occupancy": (occupancy_row.days or 0) > 0,
                "has_expenses": (expense_row.count or 0) > 0,
                "has_diary": (diary_row.count or 0) > 0,
                "has_attendance": (attendance_row.records or 0) > 0
            }
        }
        
        log_bookkeeping_access(
            BookkeepingAuditEvent.SUMMARY_ACCESS,
            client_id, service_name,
            {'start_date': start_date, 'end_date': end_date},
            1
        )
        
        return summary
