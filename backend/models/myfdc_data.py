"""
MyFDC Data Models

Pydantic models for MyFDC data intake:
- Educator Profile
- Hours Worked
- Occupancy
- Diary Entries
- Expenses
- Attendance

All data is stored under a unified client_id in Core.
"""

from datetime import date, datetime
from typing import Optional, List
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, EmailStr


# ==================== ENUMS ====================

class ExpenseCategory(str, Enum):
    """Categories for MyFDC expenses."""
    FOOD = "food"
    EQUIPMENT = "equipment"
    SUPPLIES = "supplies"
    CLEANING = "cleaning"
    UTILITIES = "utilities"
    INSURANCE = "insurance"
    TRAINING = "training"
    TRANSPORT = "transport"
    MAINTENANCE = "maintenance"
    OTHER = "other"


class DiaryCategory(str, Enum):
    """Categories for diary entries."""
    ACTIVITY = "activity"
    OBSERVATION = "observation"
    INCIDENT = "incident"
    MILESTONE = "milestone"
    COMMUNICATION = "communication"
    PLANNING = "planning"
    REFLECTION = "reflection"
    OTHER = "other"


class RoomType(str, Enum):
    """Room types for occupancy tracking."""
    PLAYROOM = "playroom"
    BEDROOM = "bedroom"
    OUTDOOR = "outdoor"
    KITCHEN = "kitchen"
    BATHROOM = "bathroom"
    OFFICE = "office"
    OTHER = "other"


# ==================== REQUEST MODELS ====================

class EducatorProfileRequest(BaseModel):
    """Request to update educator profile."""
    educator_name: str = Field(..., min_length=1, description="Educator's full name")
    phone: Optional[str] = Field(None, description="Contact phone number")
    email: Optional[EmailStr] = Field(None, description="Contact email")
    
    # Address
    address_line1: Optional[str] = Field(None, description="Street address")
    address_line2: Optional[str] = Field(None)
    suburb: Optional[str] = Field(None)
    state: Optional[str] = Field(None)
    postcode: Optional[str] = Field(None)
    
    # Business details
    abn: Optional[str] = Field(None, description="Australian Business Number")
    
    # Service approval details
    service_approval_number: Optional[str] = Field(None, description="FDC service approval number")
    approval_start_date: Optional[date] = Field(None)
    approval_expiry_date: Optional[date] = Field(None)
    max_children: Optional[int] = Field(None, ge=0, description="Maximum children approved")
    
    # Qualifications
    qualifications: Optional[List[str]] = Field(default_factory=list)
    first_aid_expiry: Optional[date] = Field(None)
    wwcc_number: Optional[str] = Field(None, description="Working With Children Check number")
    wwcc_expiry: Optional[date] = Field(None)
    
    class Config:
        json_schema_extra = {
            "example": {
                "educator_name": "Jane Smith",
                "phone": "0412345678",
                "email": "jane@example.com",
                "address_line1": "123 Main St",
                "suburb": "Sydney",
                "state": "NSW",
                "postcode": "2000",
                "abn": "51824753556",
                "service_approval_number": "SE-12345",
                "max_children": 7
            }
        }


class HoursWorkedRequest(BaseModel):
    """Request to log hours worked."""
    date: date = Field(..., description="Date of work")
    hours: float = Field(..., gt=0, le=24, description="Hours worked")
    start_time: Optional[str] = Field(None, description="Start time (HH:MM)")
    end_time: Optional[str] = Field(None, description="End time (HH:MM)")
    notes: Optional[str] = Field(None, max_length=500)
    
    class Config:
        json_schema_extra = {
            "example": {
                "date": "2025-01-01",
                "hours": 8.5,
                "start_time": "07:00",
                "end_time": "15:30",
                "notes": "Regular day, 4 children attended"
            }
        }


class OccupancyRequest(BaseModel):
    """Request to log occupancy data."""
    date: date = Field(..., description="Date of occupancy")
    number_of_children: int = Field(..., ge=0, description="Number of children present")
    hours_per_day: float = Field(..., gt=0, le=24, description="Total hours of care")
    
    # Room usage
    rooms_used: Optional[List[str]] = Field(default_factory=list, description="Rooms used for care")
    room_details: Optional[List[dict]] = Field(default_factory=list, description="Detailed room usage")
    
    # Additional info
    preschool_program: bool = Field(default=False, description="Preschool program offered")
    notes: Optional[str] = Field(None, max_length=500)
    
    class Config:
        json_schema_extra = {
            "example": {
                "date": "2025-01-01",
                "number_of_children": 5,
                "hours_per_day": 9.5,
                "rooms_used": ["playroom", "outdoor", "kitchen"],
                "preschool_program": True,
                "notes": "Full capacity day"
            }
        }


class DiaryEntryRequest(BaseModel):
    """Request to create a diary entry."""
    date: date = Field(..., description="Date of entry")
    description: str = Field(..., min_length=1, max_length=2000, description="Entry description")
    category: str = Field(default="activity", description="Entry category")
    
    # Optional child reference
    child_name: Optional[str] = Field(None, description="Child's name if specific to one child")
    
    # Attachments
    has_photos: bool = Field(default=False)
    photo_count: int = Field(default=0, ge=0)
    
    class Config:
        json_schema_extra = {
            "example": {
                "date": "2025-01-01",
                "description": "Today we explored nature in the backyard. Children collected leaves and identified different shapes.",
                "category": "activity",
                "has_photos": True,
                "photo_count": 3
            }
        }


class ExpenseRequest(BaseModel):
    """Request to log an expense."""
    date: date = Field(..., description="Date of expense")
    amount: float = Field(..., gt=0, description="Expense amount")
    category: str = Field(..., description="Expense category")
    description: Optional[str] = Field(None, max_length=500, description="Expense description")
    
    # Tax relevance
    gst_included: bool = Field(default=True, description="GST included in amount")
    tax_deductible: bool = Field(default=True, description="Is tax deductible")
    business_percentage: float = Field(default=100, ge=0, le=100, description="Business use percentage")
    
    # Receipt info
    receipt_number: Optional[str] = Field(None)
    vendor: Optional[str] = Field(None, description="Vendor/supplier name")
    
    class Config:
        json_schema_extra = {
            "example": {
                "date": "2025-01-01",
                "amount": 125.50,
                "category": "food",
                "description": "Weekly groceries for children's meals",
                "gst_included": True,
                "tax_deductible": True,
                "business_percentage": 80,
                "vendor": "Woolworths"
            }
        }


class AttendanceRequest(BaseModel):
    """Request to log child attendance."""
    child_name: str = Field(..., min_length=1, description="Child's name")
    date: date = Field(..., description="Date of attendance")
    hours: float = Field(..., gt=0, le=24, description="Hours attended")
    
    # Times
    arrival_time: Optional[str] = Field(None, description="Arrival time (HH:MM)")
    departure_time: Optional[str] = Field(None, description="Departure time (HH:MM)")
    
    # CCS info
    ccs_hours: Optional[float] = Field(None, ge=0, description="CCS subsidised hours")
    
    # Notes
    notes: Optional[str] = Field(None, max_length=500)
    absent: bool = Field(default=False, description="Was child absent (booked but didn't attend)")
    absence_reason: Optional[str] = Field(None, description="Reason for absence")
    
    class Config:
        json_schema_extra = {
            "example": {
                "child_name": "Emma Johnson",
                "date": "2025-01-01",
                "hours": 9.5,
                "arrival_time": "07:30",
                "departure_time": "17:00",
                "ccs_hours": 9.5,
                "absent": False
            }
        }


# ==================== RESPONSE MODELS ====================

class DataIntakeResponse(BaseModel):
    """Standard response for data intake operations."""
    success: bool
    record_id: str
    client_id: str
    data_type: str
    message: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "record_id": "rec_12345",
                "client_id": "client_uuid",
                "data_type": "hours_worked",
                "message": "Hours logged successfully"
            }
        }


class BulkIntakeResponse(BaseModel):
    """Response for bulk data intake operations."""
    success: bool
    records_created: int
    records_failed: int
    client_id: str
    data_type: str
    errors: Optional[List[str]] = None


# ==================== QUERY MODELS ====================

class DateRangeQuery(BaseModel):
    """Query parameters for date range queries."""
    start_date: date
    end_date: date
    
    class Config:
        json_schema_extra = {
            "example": {
                "start_date": "2025-01-01",
                "end_date": "2025-01-31"
            }
        }
