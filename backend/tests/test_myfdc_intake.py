"""
Unit Tests for MyFDC Data Intake API (Ticket A3-2)

Tests all endpoints for receiving MyFDC data:
- POST /api/myfdc/profile - Update educator profile
- POST /api/myfdc/hours - Log hours worked
- POST /api/myfdc/occupancy - Log occupancy data
- POST /api/myfdc/diary - Create diary entry
- POST /api/myfdc/expense - Log expense
- POST /api/myfdc/attendance - Log child attendance
- GET /api/myfdc/summary/hours - Get hours summary
- GET /api/myfdc/summary/expenses - Get expenses summary

Run with: pytest tests/test_myfdc_intake.py -v
"""

import pytest
import uuid
from datetime import date as DateType, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal

from services.myfdc_intake import (
    MyFDCIntakeService,
    MyFDCAuditEvent,
    log_myfdc_event
)
from models.myfdc_data import (
    EducatorProfileRequest,
    HoursWorkedRequest,
    OccupancyRequest,
    DiaryEntryRequest,
    ExpenseRequest,
    AttendanceRequest,
    DataIntakeResponse,
    BulkIntakeResponse,
    ExpenseCategory,
    DiaryCategory
)


class TestMyFDCIntakeService:
    """Test MyFDCIntakeService functionality."""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        return db
    
    @pytest.fixture
    def service(self, mock_db):
        """Create service with mocked database."""
        return MyFDCIntakeService(mock_db)
    
    @pytest.fixture
    def client_id(self):
        """Generate a test client ID."""
        return str(uuid.uuid4())
    
    # ==================== CLIENT VERIFICATION TESTS ====================
    
    @pytest.mark.asyncio
    async def test_verify_client_exists_returns_true(self, service, mock_db, client_id):
        """Test client verification when client exists."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(id=client_id)
        mock_db.execute.return_value = mock_result
        
        exists = await service.verify_client_exists(client_id)
        
        assert exists is True
    
    @pytest.mark.asyncio
    async def test_verify_client_exists_returns_false(self, service, mock_db, client_id):
        """Test client verification when client does not exist."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result
        
        exists = await service.verify_client_exists(client_id)
        
        assert exists is False
    
    # ==================== EDUCATOR PROFILE TESTS ====================
    
    @pytest.mark.asyncio
    async def test_update_educator_profile_creates_new(self, service, mock_db, client_id):
        """Test creating a new educator profile."""
        # Mock: no existing profile
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result
        
        profile_data = {
            "educator_name": "Jane Smith",
            "phone": "0412345678",
            "email": "jane@example.com",
            "suburb": "Sydney",
            "state": "NSW",
            "max_children": 7
        }
        
        result = await service.update_educator_profile(
            client_id=client_id,
            profile_data=profile_data,
            service_name="myfdc_test"
        )
        
        assert result["success"] is True
        assert result["data_type"] == "educator_profile"
        assert result["client_id"] == client_id
        assert "record_id" in result
    
    @pytest.mark.asyncio
    async def test_update_educator_profile_updates_existing(self, service, mock_db, client_id):
        """Test updating an existing educator profile."""
        existing_id = str(uuid.uuid4())
        
        # Mock: existing profile found
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(id=existing_id)
        mock_db.execute.return_value = mock_result
        
        profile_data = {
            "educator_name": "Jane Smith Updated",
            "phone": "0412345679"
        }
        
        result = await service.update_educator_profile(
            client_id=client_id,
            profile_data=profile_data,
            service_name="myfdc_test"
        )
        
        assert result["success"] is True
        assert result["record_id"] == existing_id
    
    # ==================== HOURS WORKED TESTS ====================
    
    @pytest.mark.asyncio
    async def test_log_hours_worked_success(self, service, mock_db, client_id):
        """Test logging hours worked."""
        hours_data = {
            "date": DateType(2025, 1, 1),
            "hours": 8.5,
            "start_time": "07:00",
            "end_time": "15:30",
            "notes": "Regular day"
        }
        
        result = await service.log_hours_worked(
            client_id=client_id,
            hours_data=hours_data,
            service_name="myfdc_test"
        )
        
        assert result["success"] is True
        assert result["data_type"] == "hours_worked"
        assert result["client_id"] == client_id
        mock_db.execute.assert_called()
        mock_db.commit.assert_called()
    
    @pytest.mark.asyncio
    async def test_log_hours_worked_minimal_data(self, service, mock_db, client_id):
        """Test logging hours with minimal required data."""
        hours_data = {
            "date": DateType(2025, 1, 2),
            "hours": 6.0
        }
        
        result = await service.log_hours_worked(
            client_id=client_id,
            hours_data=hours_data,
            service_name="myfdc_test"
        )
        
        assert result["success"] is True
    
    # ==================== OCCUPANCY TESTS ====================
    
    @pytest.mark.asyncio
    async def test_log_occupancy_success(self, service, mock_db, client_id):
        """Test logging occupancy data."""
        occupancy_data = {
            "date": DateType(2025, 1, 1),
            "number_of_children": 5,
            "hours_per_day": 9.5,
            "rooms_used": ["playroom", "outdoor"],
            "preschool_program": True
        }
        
        result = await service.log_occupancy(
            client_id=client_id,
            occupancy_data=occupancy_data,
            service_name="myfdc_test"
        )
        
        assert result["success"] is True
        assert result["data_type"] == "occupancy"
    
    @pytest.mark.asyncio
    async def test_log_occupancy_with_room_details(self, service, mock_db, client_id):
        """Test logging occupancy with detailed room usage."""
        occupancy_data = {
            "date": DateType(2025, 1, 1),
            "number_of_children": 4,
            "hours_per_day": 8.0,
            "room_details": [
                {"room": "playroom", "hours": 4.0},
                {"room": "outdoor", "hours": 3.0},
                {"room": "kitchen", "hours": 1.0}
            ]
        }
        
        result = await service.log_occupancy(
            client_id=client_id,
            occupancy_data=occupancy_data,
            service_name="myfdc_test"
        )
        
        assert result["success"] is True
    
    # ==================== DIARY ENTRY TESTS ====================
    
    @pytest.mark.asyncio
    async def test_create_diary_entry_success(self, service, mock_db, client_id):
        """Test creating a diary entry."""
        diary_data = {
            "date": DateType(2025, 1, 1),
            "description": "Today we explored nature in the backyard.",
            "category": "activity",
            "has_photos": True,
            "photo_count": 3
        }
        
        result = await service.create_diary_entry(
            client_id=client_id,
            diary_data=diary_data,
            service_name="myfdc_test"
        )
        
        assert result["success"] is True
        assert result["data_type"] == "diary_entry"
    
    @pytest.mark.asyncio
    async def test_create_diary_entry_with_child_name(self, service, mock_db, client_id):
        """Test creating a diary entry for a specific child."""
        diary_data = {
            "date": DateType(2025, 1, 1),
            "description": "Emma reached a milestone - counting to 10!",
            "category": "milestone",
            "child_name": "Emma Johnson"
        }
        
        result = await service.create_diary_entry(
            client_id=client_id,
            diary_data=diary_data,
            service_name="myfdc_test"
        )
        
        assert result["success"] is True
    
    # ==================== EXPENSE TESTS ====================
    
    @pytest.mark.asyncio
    async def test_log_expense_success(self, service, mock_db, client_id):
        """Test logging an expense."""
        expense_data = {
            "date": DateType(2025, 1, 1),
            "amount": 125.50,
            "category": "food",
            "description": "Weekly groceries",
            "gst_included": True,
            "tax_deductible": True,
            "business_percentage": 80,
            "vendor": "Woolworths"
        }
        
        result = await service.log_expense(
            client_id=client_id,
            expense_data=expense_data,
            service_name="myfdc_test"
        )
        
        assert result["success"] is True
        assert result["data_type"] == "expense"
    
    @pytest.mark.asyncio
    async def test_log_expense_different_categories(self, service, mock_db, client_id):
        """Test logging expenses with different categories."""
        categories = ["food", "equipment", "supplies", "cleaning", "transport"]
        
        for category in categories:
            expense_data = {
                "date": DateType(2025, 1, 1),
                "amount": 50.00,
                "category": category
            }
            
            result = await service.log_expense(
                client_id=client_id,
                expense_data=expense_data,
                service_name="myfdc_test"
            )
            
            assert result["success"] is True
    
    # ==================== ATTENDANCE TESTS ====================
    
    @pytest.mark.asyncio
    async def test_log_attendance_success(self, service, mock_db, client_id):
        """Test logging child attendance."""
        attendance_data = {
            "child_name": "Emma Johnson",
            "date": DateType(2025, 1, 1),
            "hours": 9.5,
            "arrival_time": "07:30",
            "departure_time": "17:00",
            "ccs_hours": 9.5,
            "absent": False
        }
        
        result = await service.log_attendance(
            client_id=client_id,
            attendance_data=attendance_data,
            service_name="myfdc_test"
        )
        
        assert result["success"] is True
        assert result["data_type"] == "attendance"
    
    @pytest.mark.asyncio
    async def test_log_attendance_absent(self, service, mock_db, client_id):
        """Test logging an absence."""
        attendance_data = {
            "child_name": "Tom Smith",
            "date": DateType(2025, 1, 1),
            "hours": 0,
            "absent": True,
            "absence_reason": "Sick - flu"
        }
        
        result = await service.log_attendance(
            client_id=client_id,
            attendance_data=attendance_data,
            service_name="myfdc_test"
        )
        
        assert result["success"] is True
    
    # ==================== SUMMARY TESTS ====================
    
    @pytest.mark.asyncio
    async def test_get_hours_summary(self, service, mock_db, client_id):
        """Test getting hours summary."""
        mock_row = MagicMock()
        mock_row.days_worked = 20
        mock_row.total_hours = 160.5
        mock_row.avg_hours_per_day = 8.025
        
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_db.execute.return_value = mock_result
        
        result = await service.get_hours_summary(
            client_id=client_id,
            start_date=DateType(2025, 1, 1),
            end_date=DateType(2025, 1, 31)
        )
        
        assert result["client_id"] == client_id
        assert result["days_worked"] == 20
        assert result["total_hours"] == 160.5
        assert result["avg_hours_per_day"] == 8.03  # Rounded
    
    @pytest.mark.asyncio
    async def test_get_hours_summary_empty_period(self, service, mock_db, client_id):
        """Test getting hours summary for period with no data."""
        mock_row = MagicMock()
        mock_row.days_worked = None
        mock_row.total_hours = None
        mock_row.avg_hours_per_day = None
        
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_db.execute.return_value = mock_result
        
        result = await service.get_hours_summary(
            client_id=client_id,
            start_date=DateType(2025, 2, 1),
            end_date=DateType(2025, 2, 28)
        )
        
        assert result["days_worked"] == 0
        assert result["total_hours"] == 0
        assert result["avg_hours_per_day"] == 0
    
    @pytest.mark.asyncio
    async def test_get_expenses_summary(self, service, mock_db, client_id):
        """Test getting expenses summary."""
        mock_rows = [
            MagicMock(category="food", count=10, total=500.00, business_total=400.00),
            MagicMock(category="supplies", count=5, total=200.00, business_total=200.00)
        ]
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = mock_rows
        mock_db.execute.return_value = mock_result
        
        result = await service.get_expenses_summary(
            client_id=client_id,
            start_date=DateType(2025, 1, 1),
            end_date=DateType(2025, 1, 31)
        )
        
        assert result["client_id"] == client_id
        assert "by_category" in result
        assert "food" in result["by_category"]
        assert result["total"] == 700.00
        assert result["business_total"] == 600.00


class TestMyFDCPydanticModels:
    """Test Pydantic request/response models."""
    
    def test_educator_profile_request_valid(self):
        """Test valid educator profile request."""
        data = {
            "educator_name": "Jane Smith",
            "phone": "0412345678",
            "email": "jane@example.com",
            "suburb": "Sydney",
            "state": "NSW",
            "postcode": "2000",
            "max_children": 7
        }
        
        request = EducatorProfileRequest(**data)
        
        assert request.educator_name == "Jane Smith"
        assert request.max_children == 7
    
    def test_educator_profile_request_minimal(self):
        """Test educator profile with minimal data."""
        request = EducatorProfileRequest(educator_name="John Doe")
        
        assert request.educator_name == "John Doe"
        assert request.phone is None
        assert request.max_children is None
    
    def test_hours_worked_request_valid(self):
        """Test valid hours worked request."""
        data = {
            "date": "2025-01-01",
            "hours": 8.5,
            "start_time": "07:00",
            "end_time": "15:30"
        }
        
        request = HoursWorkedRequest(**data)
        
        assert request.hours == 8.5
        assert request.date == DateType(2025, 1, 1)
    
    def test_hours_worked_request_invalid_hours(self):
        """Test hours worked request with invalid hours."""
        with pytest.raises(ValueError):
            HoursWorkedRequest(date="2025-01-01", hours=25)  # > 24 hours
    
    def test_occupancy_request_valid(self):
        """Test valid occupancy request."""
        data = {
            "date": "2025-01-01",
            "number_of_children": 5,
            "hours_per_day": 9.5,
            "rooms_used": ["playroom", "outdoor"]
        }
        
        request = OccupancyRequest(**data)
        
        assert request.number_of_children == 5
        assert request.preschool_program is False  # Default
    
    def test_expense_request_defaults(self):
        """Test expense request default values."""
        request = ExpenseRequest(
            date="2025-01-01",
            amount=100.00,
            category="food"
        )
        
        assert request.gst_included is True
        assert request.tax_deductible is True
        assert request.business_percentage == 100
    
    def test_attendance_request_absent(self):
        """Test attendance request for absence."""
        data = {
            "child_name": "Emma",
            "date": "2025-01-01",
            "hours": 0.1,  # Minimal hours for validation (booking was made)
            "absent": True,
            "absence_reason": "Sick"
        }
        
        request = AttendanceRequest(**data)
        
        assert request.absent is True
        assert request.absence_reason == "Sick"
    
    def test_data_intake_response(self):
        """Test DataIntakeResponse model."""
        response = DataIntakeResponse(
            success=True,
            record_id="rec_123",
            client_id="client_456",
            data_type="hours_worked",
            message="Hours logged"
        )
        
        assert response.success is True
        assert response.data_type == "hours_worked"


class TestMyFDCAuditLogging:
    """Test audit logging for MyFDC operations."""
    
    def test_log_myfdc_event_sanitizes_abn(self, caplog):
        """Test that ABN is masked in logs."""
        import logging
        caplog.set_level(logging.INFO)
        
        log_myfdc_event(
            MyFDCAuditEvent.PROFILE_UPDATE,
            "client-123",
            "rec-456",
            "test-service",
            {"abn": "51824753556", "educator_name": "Jane"}
        )
        
        # ABN should be masked
        for record in caplog.records:
            assert "51824753556" not in str(record.message)
    
    def test_log_myfdc_event_excludes_sensitive_fields(self, caplog):
        """Test that sensitive fields are excluded from logs."""
        import logging
        caplog.set_level(logging.INFO)
        
        log_myfdc_event(
            MyFDCAuditEvent.PROFILE_UPDATE,
            "client-123",
            "rec-456",
            "test-service",
            {"tfn": "123456789", "wwcc_number": "WWC123", "bank_account": "123456"}
        )
        
        # Sensitive fields should not appear
        for record in caplog.records:
            msg = str(record.message)
            assert "123456789" not in msg
            assert "WWC123" not in msg
            assert "123456" not in msg


class TestExpenseCategories:
    """Test expense category enumeration."""
    
    def test_all_categories_valid(self):
        """Test all expense categories are defined."""
        expected_categories = [
            "food", "equipment", "supplies", "cleaning",
            "utilities", "insurance", "training", "transport",
            "maintenance", "other"
        ]
        
        for cat in expected_categories:
            assert cat in [e.value for e in ExpenseCategory]
    
    def test_category_values(self):
        """Test category enum values."""
        assert ExpenseCategory.FOOD.value == "food"
        assert ExpenseCategory.EQUIPMENT.value == "equipment"
        assert ExpenseCategory.OTHER.value == "other"


class TestDiaryCategories:
    """Test diary category enumeration."""
    
    def test_all_diary_categories_valid(self):
        """Test all diary categories are defined."""
        expected_categories = [
            "activity", "observation", "incident", "milestone",
            "communication", "planning", "reflection", "other"
        ]
        
        for cat in expected_categories:
            assert cat in [e.value for e in DiaryCategory]


class TestDeterministicResponses:
    """Test that service responses are deterministic."""
    
    def test_intake_response_deterministic(self):
        """Test DataIntakeResponse produces consistent output."""
        response1 = DataIntakeResponse(
            success=True,
            record_id="rec-123",
            client_id="client-456",
            data_type="hours",
            message="Done"
        )
        response2 = DataIntakeResponse(
            success=True,
            record_id="rec-123",
            client_id="client-456",
            data_type="hours",
            message="Done"
        )
        
        assert response1.model_dump() == response2.model_dump()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
