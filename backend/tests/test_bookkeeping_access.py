"""
Unit Tests for CRM Bookkeeping Data Access API (Ticket A3-3.3)

Tests all endpoints for CRM Bookkeeping to retrieve MyFDC data:
- GET /api/bookkeeping/{client_id}/hours
- GET /api/bookkeeping/{client_id}/occupancy
- GET /api/bookkeeping/{client_id}/diary
- GET /api/bookkeeping/{client_id}/expenses
- GET /api/bookkeeping/{client_id}/attendance
- GET /api/bookkeeping/{client_id}/summary

Run with: pytest tests/test_bookkeeping_access.py -v
"""

import pytest
import uuid
from datetime import date as DateType, datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal

from services.bookkeeping_access import (
    BookkeepingService,
    BookkeepingAuditEvent,
    log_bookkeeping_access,
    HoursRecord,
    OccupancyRecord,
    DiaryRecord,
    ExpenseRecord,
    AttendanceRecord
)


class TestBookkeepingService:
    """Test BookkeepingService functionality."""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        return db
    
    @pytest.fixture
    def service(self, mock_db):
        """Create service with mocked database."""
        return BookkeepingService(mock_db)
    
    @pytest.fixture
    def client_id(self):
        """Generate a test client ID."""
        return str(uuid.uuid4())
    
    # ==================== CLIENT VERIFICATION TESTS ====================
    
    @pytest.mark.asyncio
    async def test_verify_client_exists_true(self, service, mock_db, client_id):
        """Test client verification when client exists."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(id=client_id)
        mock_db.execute.return_value = mock_result
        
        exists = await service.verify_client_exists(client_id)
        
        assert exists is True
    
    @pytest.mark.asyncio
    async def test_verify_client_exists_false(self, service, mock_db, client_id):
        """Test client verification when client does not exist."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result
        
        exists = await service.verify_client_exists(client_id)
        
        assert exists is False
    
    # ==================== HOURS WORKED TESTS ====================
    
    @pytest.mark.asyncio
    async def test_get_hours_worked_returns_records(self, service, mock_db, client_id):
        """Test retrieving hours worked records."""
        mock_rows = [
            MagicMock(
                id=uuid.uuid4(),
                work_date=DateType(2025, 1, 15),
                hours=Decimal('8.5'),
                start_time='07:00',
                end_time='15:30',
                notes='Regular day',
                created_at=datetime.now(timezone.utc)
            ),
            MagicMock(
                id=uuid.uuid4(),
                work_date=DateType(2025, 1, 14),
                hours=Decimal('7.0'),
                start_time='08:00',
                end_time='15:00',
                notes=None,
                created_at=datetime.now(timezone.utc)
            )
        ]
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = mock_rows
        mock_db.execute.return_value = mock_result
        
        result = await service.get_hours_worked(client_id)
        
        assert result['client_id'] == client_id
        assert len(result['records']) == 2
        assert result['summary']['total_hours'] == 15.5
        assert result['summary']['days_worked'] == 2
        assert result['summary']['avg_hours_per_day'] == 7.75
    
    @pytest.mark.asyncio
    async def test_get_hours_worked_with_date_filter(self, service, mock_db, client_id):
        """Test retrieving hours with date filters."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result
        
        result = await service.get_hours_worked(
            client_id,
            start_date=DateType(2025, 1, 1),
            end_date=DateType(2025, 1, 31)
        )
        
        assert result['filters']['start_date'] == '2025-01-01'
        assert result['filters']['end_date'] == '2025-01-31'
    
    @pytest.mark.asyncio
    async def test_get_hours_worked_empty(self, service, mock_db, client_id):
        """Test retrieving hours when no records exist."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result
        
        result = await service.get_hours_worked(client_id)
        
        assert len(result['records']) == 0
        assert result['summary']['total_hours'] == 0
        assert result['summary']['avg_hours_per_day'] == 0
    
    # ==================== OCCUPANCY TESTS ====================
    
    @pytest.mark.asyncio
    async def test_get_occupancy_returns_records(self, service, mock_db, client_id):
        """Test retrieving occupancy records."""
        mock_rows = [
            MagicMock(
                id=uuid.uuid4(),
                occupancy_date=DateType(2025, 1, 15),
                number_of_children=5,
                hours_per_day=Decimal('9.5'),
                rooms_used='["playroom", "outdoor"]',
                preschool_program=True,
                notes='Full day',
                created_at=datetime.now(timezone.utc)
            )
        ]
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = mock_rows
        mock_db.execute.return_value = mock_result
        
        result = await service.get_occupancy(client_id)
        
        assert result['client_id'] == client_id
        assert len(result['records']) == 1
        assert result['summary']['total_child_days'] == 5
        assert result['summary']['days_with_preschool_program'] == 1
        assert 'playroom' in result['summary']['room_usage_count']
    
    @pytest.mark.asyncio
    async def test_get_occupancy_room_usage_aggregation(self, service, mock_db, client_id):
        """Test room usage aggregation."""
        mock_rows = [
            MagicMock(
                id=uuid.uuid4(), occupancy_date=DateType(2025, 1, 15),
                number_of_children=3, hours_per_day=Decimal('8'),
                rooms_used='["playroom", "outdoor"]', preschool_program=False,
                notes=None, created_at=datetime.now(timezone.utc)
            ),
            MagicMock(
                id=uuid.uuid4(), occupancy_date=DateType(2025, 1, 14),
                number_of_children=4, hours_per_day=Decimal('9'),
                rooms_used='["playroom", "kitchen"]', preschool_program=True,
                notes=None, created_at=datetime.now(timezone.utc)
            )
        ]
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = mock_rows
        mock_db.execute.return_value = mock_result
        
        result = await service.get_occupancy(client_id)
        
        assert result['summary']['room_usage_count']['playroom'] == 2
        assert result['summary']['room_usage_count']['outdoor'] == 1
        assert result['summary']['room_usage_count']['kitchen'] == 1
    
    # ==================== DIARY TESTS ====================
    
    @pytest.mark.asyncio
    async def test_get_diary_entries_returns_records(self, service, mock_db, client_id):
        """Test retrieving diary entries."""
        mock_rows = [
            MagicMock(
                id=uuid.uuid4(),
                entry_date=DateType(2025, 1, 15),
                description='Nature exploration activity',
                category='activity',
                child_name=None,
                has_photos=True,
                photo_count=3,
                created_at=datetime.now(timezone.utc)
            )
        ]
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = mock_rows
        mock_db.execute.return_value = mock_result
        
        result = await service.get_diary_entries(client_id)
        
        assert len(result['records']) == 1
        assert result['summary']['entries_with_photos'] == 1
        assert result['summary']['total_photos'] == 3
        assert result['summary']['by_category']['activity'] == 1
    
    @pytest.mark.asyncio
    async def test_get_diary_entries_with_category_filter(self, service, mock_db, client_id):
        """Test diary entries with category filter."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result
        
        result = await service.get_diary_entries(client_id, category='milestone')
        
        assert result['filters']['category'] == 'milestone'
    
    # ==================== EXPENSES TESTS ====================
    
    @pytest.mark.asyncio
    async def test_get_expenses_returns_records(self, service, mock_db, client_id):
        """Test retrieving expense records."""
        mock_rows = [
            MagicMock(
                id=uuid.uuid4(),
                expense_date=DateType(2025, 1, 15),
                amount=Decimal('125.50'),
                category='food',
                description='Weekly groceries',
                gst_included=True,
                tax_deductible=True,
                business_percentage=Decimal('80'),
                receipt_number='REC-001',
                vendor='Woolworths',
                created_at=datetime.now(timezone.utc)
            )
        ]
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = mock_rows
        mock_db.execute.return_value = mock_result
        
        result = await service.get_expenses(client_id)
        
        assert len(result['records']) == 1
        assert result['records'][0]['amount'] == 125.50
        assert result['records'][0]['business_amount'] == 100.40
        assert result['summary']['total_amount'] == 125.50
        assert result['summary']['total_business_amount'] == 100.40
    
    @pytest.mark.asyncio
    async def test_get_expenses_category_breakdown(self, service, mock_db, client_id):
        """Test expense category breakdown."""
        mock_rows = [
            MagicMock(
                id=uuid.uuid4(), expense_date=DateType(2025, 1, 15),
                amount=Decimal('100'), category='food', description=None,
                gst_included=True, tax_deductible=True,
                business_percentage=Decimal('100'), receipt_number=None,
                vendor=None, created_at=datetime.now(timezone.utc)
            ),
            MagicMock(
                id=uuid.uuid4(), expense_date=DateType(2025, 1, 14),
                amount=Decimal('50'), category='food', description=None,
                gst_included=True, tax_deductible=True,
                business_percentage=Decimal('100'), receipt_number=None,
                vendor=None, created_at=datetime.now(timezone.utc)
            ),
            MagicMock(
                id=uuid.uuid4(), expense_date=DateType(2025, 1, 13),
                amount=Decimal('200'), category='equipment', description=None,
                gst_included=True, tax_deductible=True,
                business_percentage=Decimal('100'), receipt_number=None,
                vendor=None, created_at=datetime.now(timezone.utc)
            )
        ]
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = mock_rows
        mock_db.execute.return_value = mock_result
        
        result = await service.get_expenses(client_id)
        
        assert result['summary']['by_category']['food']['count'] == 2
        assert result['summary']['by_category']['food']['total'] == 150.0
        assert result['summary']['by_category']['equipment']['count'] == 1
        assert result['summary']['total_amount'] == 350.0
    
    # ==================== ATTENDANCE TESTS ====================
    
    @pytest.mark.asyncio
    async def test_get_attendance_returns_records(self, service, mock_db, client_id):
        """Test retrieving attendance records."""
        mock_rows = [
            MagicMock(
                id=uuid.uuid4(),
                child_name='Emma Johnson',
                attendance_date=DateType(2025, 1, 15),
                hours=Decimal('9.5'),
                arrival_time='07:30',
                departure_time='17:00',
                ccs_hours=Decimal('9.5'),
                notes=None,
                absent=False,
                absence_reason=None,
                created_at=datetime.now(timezone.utc)
            )
        ]
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = mock_rows
        mock_db.execute.return_value = mock_result
        
        result = await service.get_attendance(client_id)
        
        assert len(result['records']) == 1
        assert result['summary']['total_hours'] == 9.5
        assert result['summary']['total_ccs_hours'] == 9.5
        assert result['summary']['unique_children'] == 1
        assert 'Emma Johnson' in result['summary']['by_child']
    
    @pytest.mark.asyncio
    async def test_get_attendance_daily_totals(self, service, mock_db, client_id):
        """Test attendance daily totals calculation."""
        mock_rows = [
            MagicMock(
                id=uuid.uuid4(), child_name='Emma', attendance_date=DateType(2025, 1, 15),
                hours=Decimal('8'), arrival_time='08:00', departure_time='16:00',
                ccs_hours=Decimal('8'), notes=None, absent=False, absence_reason=None,
                created_at=datetime.now(timezone.utc)
            ),
            MagicMock(
                id=uuid.uuid4(), child_name='Tom', attendance_date=DateType(2025, 1, 15),
                hours=Decimal('9'), arrival_time='07:00', departure_time='16:00',
                ccs_hours=Decimal('9'), notes=None, absent=False, absence_reason=None,
                created_at=datetime.now(timezone.utc)
            )
        ]
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = mock_rows
        mock_db.execute.return_value = mock_result
        
        result = await service.get_attendance(client_id)
        
        assert '2025-01-15' in result['daily_totals']
        assert result['daily_totals']['2025-01-15']['children'] == 2
        assert result['daily_totals']['2025-01-15']['total_hours'] == 17.0
    
    @pytest.mark.asyncio
    async def test_get_attendance_tracks_absences(self, service, mock_db, client_id):
        """Test attendance tracking absences."""
        mock_rows = [
            MagicMock(
                id=uuid.uuid4(), child_name='Emma', attendance_date=DateType(2025, 1, 15),
                hours=Decimal('0.1'), arrival_time=None, departure_time=None,
                ccs_hours=None, notes=None, absent=True, absence_reason='Sick',
                created_at=datetime.now(timezone.utc)
            )
        ]
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = mock_rows
        mock_db.execute.return_value = mock_result
        
        result = await service.get_attendance(client_id)
        
        assert result['summary']['total_absences'] == 1
        assert result['summary']['by_child']['Emma']['absences'] == 1


class TestBookkeepingSummary:
    """Test combined bookkeeping summary functionality."""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        return db
    
    @pytest.fixture
    def service(self, mock_db):
        """Create service with mocked database."""
        return BookkeepingService(mock_db)
    
    @pytest.fixture
    def client_id(self):
        return str(uuid.uuid4())
    
    @pytest.mark.asyncio
    async def test_get_bookkeeping_summary(self, service, mock_db, client_id):
        """Test combined summary aggregation."""
        # Mock all the individual queries
        mock_hours = MagicMock(days=10, total_hours=Decimal('85'))
        mock_occupancy = MagicMock(days=10, total_child_days=45, total_care_hours=Decimal('95'))
        mock_expense = MagicMock(count=15, total=Decimal('1500'), business_total=Decimal('1200'))
        mock_diary = MagicMock(count=8)
        mock_attendance = MagicMock(
            records=50, unique_children=5, total_hours=Decimal('400'),
            total_ccs_hours=Decimal('380'), absences=2
        )
        mock_profile = MagicMock(
            educator_name='Jane Smith',
            service_approval_number='SE-12345',
            max_children=7
        )
        
        # Set up mock to return different results for each query
        mock_results = [
            MagicMock(fetchone=MagicMock(return_value=mock_hours)),
            MagicMock(fetchone=MagicMock(return_value=mock_occupancy)),
            MagicMock(fetchone=MagicMock(return_value=mock_expense)),
            MagicMock(fetchone=MagicMock(return_value=mock_diary)),
            MagicMock(fetchone=MagicMock(return_value=mock_attendance)),
            MagicMock(fetchone=MagicMock(return_value=mock_profile))
        ]
        mock_db.execute.side_effect = mock_results
        
        result = await service.get_bookkeeping_summary(client_id)
        
        assert result['client_id'] == client_id
        assert result['educator_profile']['has_profile'] is True
        assert result['educator_profile']['educator_name'] == 'Jane Smith'
        assert result['hours_worked']['days_worked'] == 10
        assert result['occupancy']['total_child_days'] == 45
        assert result['expenses']['count'] == 15
        assert result['diary']['entry_count'] == 8
        assert result['attendance']['unique_children'] == 5
    
    @pytest.mark.asyncio
    async def test_summary_data_completeness_flags(self, service, mock_db, client_id):
        """Test data completeness indicators in summary."""
        # Mock with some empty data
        mock_hours = MagicMock(days=5, total_hours=Decimal('40'))
        mock_occupancy = MagicMock(days=0, total_child_days=0, total_care_hours=Decimal('0'))
        mock_expense = MagicMock(count=0, total=Decimal('0'), business_total=Decimal('0'))
        mock_diary = MagicMock(count=3)
        mock_attendance = MagicMock(
            records=10, unique_children=2, total_hours=Decimal('80'),
            total_ccs_hours=Decimal('75'), absences=0
        )
        mock_profile = None
        
        mock_results = [
            MagicMock(fetchone=MagicMock(return_value=mock_hours)),
            MagicMock(fetchone=MagicMock(return_value=mock_occupancy)),
            MagicMock(fetchone=MagicMock(return_value=mock_expense)),
            MagicMock(fetchone=MagicMock(return_value=mock_diary)),
            MagicMock(fetchone=MagicMock(return_value=mock_attendance)),
            MagicMock(fetchone=MagicMock(return_value=mock_profile))
        ]
        mock_db.execute.side_effect = mock_results
        
        result = await service.get_bookkeeping_summary(client_id)
        
        assert result['data_completeness']['has_hours'] is True
        assert result['data_completeness']['has_occupancy'] is False
        assert result['data_completeness']['has_expenses'] is False
        assert result['data_completeness']['has_diary'] is True
        assert result['data_completeness']['has_attendance'] is True
        assert result['educator_profile']['has_profile'] is False


class TestDataModels:
    """Test data record models."""
    
    def test_hours_record_to_dict(self):
        """Test HoursRecord conversion."""
        record = HoursRecord(
            id='rec-123',
            work_date='2025-01-15',
            hours=8.5,
            start_time='07:00',
            end_time='15:30',
            notes='Test',
            created_at='2025-01-15T10:00:00Z'
        )
        
        d = record.to_dict()
        
        assert d['id'] == 'rec-123'
        assert d['hours'] == 8.5
    
    def test_expense_record_business_amount(self):
        """Test ExpenseRecord with business amount."""
        record = ExpenseRecord(
            id='exp-123',
            expense_date='2025-01-15',
            amount=100.0,
            category='food',
            description='Test',
            gst_included=True,
            tax_deductible=True,
            business_percentage=80.0,
            business_amount=80.0,
            receipt_number=None,
            vendor='Test',
            created_at='2025-01-15T10:00:00Z'
        )
        
        d = record.to_dict()
        
        assert d['amount'] == 100.0
        assert d['business_amount'] == 80.0
        assert d['business_percentage'] == 80.0
    
    def test_attendance_record_absent(self):
        """Test AttendanceRecord for absence."""
        record = AttendanceRecord(
            id='att-123',
            child_name='Emma',
            attendance_date='2025-01-15',
            hours=0.1,
            arrival_time=None,
            departure_time=None,
            ccs_hours=None,
            absent=True,
            absence_reason='Sick',
            notes=None,
            created_at='2025-01-15T10:00:00Z'
        )
        
        d = record.to_dict()
        
        assert d['absent'] is True
        assert d['absence_reason'] == 'Sick'


class TestAuditLogging:
    """Test audit logging for bookkeeping access."""
    
    def test_log_bookkeeping_access_success(self, caplog):
        """Test successful access logging."""
        import logging
        caplog.set_level(logging.INFO)
        
        log_bookkeeping_access(
            BookkeepingAuditEvent.HOURS_ACCESS,
            'client-123',
            'crm-service',
            {'start_date': DateType(2025, 1, 1), 'end_date': DateType(2025, 1, 31)},
            10,
            success=True
        )
        
        assert 'CRM Bookkeeping' in caplog.text
        assert 'client-123' in caplog.text
    
    def test_log_bookkeeping_access_failure(self, caplog):
        """Test failed access logging."""
        import logging
        caplog.set_level(logging.WARNING)
        
        log_bookkeeping_access(
            BookkeepingAuditEvent.EXPENSES_ACCESS,
            'client-456',
            'crm-service',
            {},
            0,
            success=False
        )
        
        assert 'FAILED' in caplog.text


class TestDeterministicResponses:
    """Test that responses are deterministic."""
    
    def test_hours_record_deterministic(self):
        """Test HoursRecord produces consistent output."""
        record1 = HoursRecord('id-1', '2025-01-15', 8.0, '08:00', '16:00', None, '2025-01-15T10:00:00Z')
        record2 = HoursRecord('id-1', '2025-01-15', 8.0, '08:00', '16:00', None, '2025-01-15T10:00:00Z')
        
        assert record1.to_dict() == record2.to_dict()
    
    def test_expense_record_deterministic(self):
        """Test ExpenseRecord produces consistent output."""
        record1 = ExpenseRecord(
            'exp-1', '2025-01-15', 100.0, 'food', 'Test',
            True, True, 80.0, 80.0, None, 'Vendor', '2025-01-15T10:00:00Z'
        )
        record2 = ExpenseRecord(
            'exp-1', '2025-01-15', 100.0, 'food', 'Test',
            True, True, 80.0, 80.0, None, 'Vendor', '2025-01-15T10:00:00Z'
        )
        
        assert record1.to_dict() == record2.to_dict()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
