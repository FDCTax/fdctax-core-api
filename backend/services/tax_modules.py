"""
FDC Core - Tax Module Calculation Engines

Implements Australian tax compliance calculations for:
- POB (Place of Business / Home Office)
- Occupancy Expenses
- Depreciation (General Assets)
- Motor Vehicle (Enhanced)

All calculations follow ATO guidelines and Ben's compliance specifications.
Returns deterministic JSON responses.

Tax Year: 2024-25
Last Updated: January 2025
"""

import logging
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field, asdict

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ==================== COMMON TAX CONSTANTS (2024-25) ====================

GST_RATE = Decimal("0.10")  # 10%
GST_DIVISOR = Decimal("11")  # To extract GST from GST-inclusive amount


def _round_currency(amount: Decimal) -> Decimal:
    """Round to 2 decimal places for currency."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _round_percentage(value: float, decimals: int = 2) -> float:
    """Round percentage to specified decimal places."""
    return round(value, decimals)


# ==================== POB (PLACE OF BUSINESS / HOME OFFICE) ====================

class POBMethod(str, Enum):
    """Home office calculation methods per ATO rules."""
    FIXED_RATE = "fixed_rate"           # 67 cents per hour (from 1 July 2022)
    ACTUAL_COST = "actual_cost"         # Actual running expenses
    SHORTCUT = "shortcut"               # 80 cents per hour (COVID only, ended 30 June 2022)


# ATO Fixed Rate per hour (current)
POB_FIXED_RATE_PER_HOUR = Decimal("0.67")  # 67 cents per hour

# COVID Shortcut rate (historical, ended 30 June 2022)
POB_SHORTCUT_RATE_PER_HOUR = Decimal("0.80")  # 80 cents per hour

# Running expense categories for actual cost method
POB_EXPENSE_CATEGORIES = {
    "electricity": {"gst_claimable": True, "description": "Electricity for heating, cooling, lighting"},
    "gas": {"gst_claimable": True, "description": "Gas for heating"},
    "cleaning": {"gst_claimable": True, "description": "Cleaning costs for home office"},
    "phone": {"gst_claimable": True, "description": "Phone and internet (business portion)"},
    "internet": {"gst_claimable": True, "description": "Internet (business portion)"},
    "stationery": {"gst_claimable": True, "description": "Office supplies and stationery"},
    "computer_consumables": {"gst_claimable": True, "description": "Printer ink, etc."},
    "depreciation_furniture": {"gst_claimable": False, "description": "Depreciation of office furniture"},
    "depreciation_equipment": {"gst_claimable": False, "description": "Depreciation of office equipment"},
    "repairs": {"gst_claimable": True, "description": "Repairs to office equipment"},
}


@dataclass
class POBCalculationInput:
    """Input for POB calculation."""
    method: str = "fixed_rate"
    hours_worked: float = 0  # Total hours worked from home
    
    # For actual cost method
    floor_area_office: float = 0  # Square meters
    floor_area_total: float = 0  # Total home square meters
    
    # Running expenses (actual cost method)
    expenses: Dict[str, float] = field(default_factory=dict)
    
    # Period
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    
    # Additional info
    dedicated_office: bool = False  # Is the space exclusively for work?
    days_per_week: float = 5  # Average days worked from home


@dataclass
class POBCalculationResult:
    """Result of POB calculation."""
    method: str
    deduction_amount: Decimal
    gst_claimable: Decimal
    breakdown: Dict[str, Any]
    notes: List[str]
    compliance_warnings: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "deduction_amount": float(self.deduction_amount),
            "gst_claimable": float(self.gst_claimable),
            "breakdown": self.breakdown,
            "notes": self.notes,
            "compliance_warnings": self.compliance_warnings
        }


def calculate_pob(input_data: POBCalculationInput) -> POBCalculationResult:
    """
    Calculate Place of Business (Home Office) deduction.
    
    ATO Methods:
    1. Fixed Rate (67c/hour) - Covers electricity, phone, internet, stationery
    2. Actual Cost - Calculate actual running expenses × business use %
    3. Shortcut (80c/hour) - COVID only, ended 30 June 2022
    
    Returns deterministic JSON-serializable result.
    """
    notes = []
    warnings = []
    breakdown = {}
    gst_claimable = Decimal("0")
    
    method = POBMethod(input_data.method)
    
    if method == POBMethod.FIXED_RATE:
        # Fixed rate method: 67 cents per hour
        deduction = Decimal(str(input_data.hours_worked)) * POB_FIXED_RATE_PER_HOUR
        deduction = _round_currency(deduction)
        
        breakdown = {
            "hours_worked": input_data.hours_worked,
            "rate_per_hour": float(POB_FIXED_RATE_PER_HOUR),
            "calculation": f"{input_data.hours_worked} hours × $0.67 = ${float(deduction):.2f}"
        }
        
        notes.append("Fixed rate method covers electricity, phone, internet, stationery, and computer consumables")
        notes.append("You must keep records of hours worked from home (timesheet, diary, roster)")
        
        if input_data.hours_worked > 2000:
            warnings.append(f"High hours claimed ({input_data.hours_worked}). Ensure records support this.")
        
        # Fixed rate has no separate GST claim
        gst_claimable = Decimal("0")
        
    elif method == POBMethod.ACTUAL_COST:
        # Actual cost method: Calculate business use percentage of expenses
        if input_data.floor_area_total <= 0:
            warnings.append("Total floor area must be greater than 0 for actual cost method")
            business_use_pct = Decimal("0")
        else:
            business_use_pct = Decimal(str(input_data.floor_area_office)) / Decimal(str(input_data.floor_area_total))
        
        # If not dedicated office, may need to adjust for personal use
        if not input_data.dedicated_office:
            # Adjust for actual hours used (assume 8 hours work, 16 hours personal per day)
            hours_adjustment = Decimal("0.33")  # 8/24
            business_use_pct = business_use_pct * hours_adjustment
            notes.append("Business use percentage adjusted for non-dedicated office space")
        
        total_expenses = Decimal("0")
        expense_breakdown = {}
        
        for category, amount in input_data.expenses.items():
            if category in POB_EXPENSE_CATEGORIES:
                exp_amount = Decimal(str(amount))
                business_amount = _round_currency(exp_amount * business_use_pct)
                expense_breakdown[category] = {
                    "total": float(exp_amount),
                    "business_portion": float(business_amount),
                    "business_use_pct": float(business_use_pct * 100)
                }
                total_expenses += business_amount
                
                # Calculate GST component
                if POB_EXPENSE_CATEGORIES[category]["gst_claimable"]:
                    gst_component = _round_currency(business_amount / GST_DIVISOR)
                    gst_claimable += gst_component
        
        deduction = _round_currency(total_expenses)
        
        breakdown = {
            "floor_area_office_sqm": input_data.floor_area_office,
            "floor_area_total_sqm": input_data.floor_area_total,
            "business_use_percentage": _round_percentage(float(business_use_pct * 100)),
            "dedicated_office": input_data.dedicated_office,
            "expenses": expense_breakdown,
            "total_deduction": float(deduction)
        }
        
        notes.append("Actual cost method requires receipts and records of all expenses")
        notes.append("Business use percentage is based on floor area of dedicated work space")
        
    elif method == POBMethod.SHORTCUT:
        # Shortcut method: 80 cents per hour (COVID only, ended 30 June 2022)
        deduction = Decimal(str(input_data.hours_worked)) * POB_SHORTCUT_RATE_PER_HOUR
        deduction = _round_currency(deduction)
        
        warnings.append("Shortcut method ended 30 June 2022. Only use for prior year claims.")
        
        breakdown = {
            "hours_worked": input_data.hours_worked,
            "rate_per_hour": float(POB_SHORTCUT_RATE_PER_HOUR),
            "calculation": f"{input_data.hours_worked} hours × $0.80 = ${float(deduction):.2f}"
        }
        
        notes.append("Shortcut method covers ALL running expenses including depreciation")
        
        gst_claimable = Decimal("0")
    
    else:
        deduction = Decimal("0")
        warnings.append(f"Unknown method: {input_data.method}")
    
    return POBCalculationResult(
        method=input_data.method,
        deduction_amount=deduction,
        gst_claimable=gst_claimable,
        breakdown=breakdown,
        notes=notes,
        compliance_warnings=warnings
    )


# ==================== OCCUPANCY EXPENSES ====================

class OccupancyExpenseType(str, Enum):
    """Types of occupancy expenses."""
    RENT = "rent"
    MORTGAGE_INTEREST = "mortgage_interest"
    COUNCIL_RATES = "council_rates"
    LAND_TAX = "land_tax"
    HOUSE_INSURANCE = "house_insurance"
    WATER_RATES = "water_rates"
    BODY_CORPORATE = "body_corporate"


# Occupancy expense GST rules
OCCUPANCY_GST_RULES = {
    OccupancyExpenseType.RENT: {"gst_claimable": False, "note": "Residential rent is input-taxed (no GST)"},
    OccupancyExpenseType.MORTGAGE_INTEREST: {"gst_claimable": False, "note": "Interest is input-taxed"},
    OccupancyExpenseType.COUNCIL_RATES: {"gst_claimable": False, "note": "Government charges are GST-free"},
    OccupancyExpenseType.LAND_TAX: {"gst_claimable": False, "note": "Government charges are GST-free"},
    OccupancyExpenseType.HOUSE_INSURANCE: {"gst_claimable": True, "note": "GST on premium only, not stamp duty"},
    OccupancyExpenseType.WATER_RATES: {"gst_claimable": False, "note": "Water is GST-free"},
    OccupancyExpenseType.BODY_CORPORATE: {"gst_claimable": True, "note": "May contain GST on some components"},
}


@dataclass
class OccupancyCalculationInput:
    """Input for occupancy calculation."""
    expenses: Dict[str, float]  # expense_type -> annual amount
    
    # Business use calculation
    floor_area_business: float = 0  # Square meters for business
    floor_area_total: float = 0  # Total home square meters
    
    # Alternative: direct percentage
    business_use_percentage: Optional[float] = None
    
    # Period
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    days_in_period: int = 365
    
    # Owner or tenant
    is_owner: bool = True
    
    # CGT implications warning flag
    principal_residence: bool = True


@dataclass  
class OccupancyCalculationResult:
    """Result of occupancy calculation."""
    total_deduction: Decimal
    gst_claimable: Decimal
    business_use_percentage: float
    expense_breakdown: Dict[str, Any]
    notes: List[str]
    compliance_warnings: List[str]
    cgt_warning: Optional[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_deduction": float(self.total_deduction),
            "gst_claimable": float(self.gst_claimable),
            "business_use_percentage": self.business_use_percentage,
            "expense_breakdown": self.expense_breakdown,
            "notes": self.notes,
            "compliance_warnings": self.compliance_warnings,
            "cgt_warning": self.cgt_warning
        }


def calculate_occupancy(input_data: OccupancyCalculationInput) -> OccupancyCalculationResult:
    """
    Calculate occupancy expense deduction for home office.
    
    Occupancy expenses can only be claimed if you have a dedicated area
    set aside exclusively for business. Unlike running expenses, these
    relate to the cost of owning/renting the property itself.
    
    WARNING: Claiming occupancy expenses may affect CGT main residence exemption.
    
    Returns deterministic JSON-serializable result.
    """
    notes = []
    warnings = []
    expense_breakdown = {}
    gst_claimable = Decimal("0")
    
    # Calculate business use percentage
    if input_data.business_use_percentage is not None:
        business_use_pct = Decimal(str(input_data.business_use_percentage / 100))
    elif input_data.floor_area_total > 0:
        business_use_pct = Decimal(str(input_data.floor_area_business)) / Decimal(str(input_data.floor_area_total))
    else:
        business_use_pct = Decimal("0")
        warnings.append("Unable to calculate business use percentage - floor area required")
    
    total_deduction = Decimal("0")
    
    for expense_type, amount in input_data.expenses.items():
        try:
            exp_type = OccupancyExpenseType(expense_type)
        except ValueError:
            warnings.append(f"Unknown expense type: {expense_type}")
            continue
        
        exp_amount = Decimal(str(amount))
        business_portion = _round_currency(exp_amount * business_use_pct)
        
        expense_breakdown[expense_type] = {
            "total_amount": float(exp_amount),
            "business_portion": float(business_portion),
            "business_use_pct": _round_percentage(float(business_use_pct * 100))
        }
        
        total_deduction += business_portion
        
        # GST calculation
        gst_rules = OCCUPANCY_GST_RULES.get(exp_type, {"gst_claimable": False})
        if gst_rules.get("gst_claimable"):
            gst_component = _round_currency(business_portion / GST_DIVISOR)
            gst_claimable += gst_component
            expense_breakdown[expense_type]["gst_claimable"] = float(gst_component)
        else:
            expense_breakdown[expense_type]["gst_claimable"] = 0
            expense_breakdown[expense_type]["gst_note"] = gst_rules.get("note", "")
    
    total_deduction = _round_currency(total_deduction)
    
    # CGT warning for owner-occupiers
    cgt_warning = None
    if input_data.is_owner and input_data.principal_residence:
        cgt_warning = (
            "WARNING: Claiming occupancy expenses for your principal residence may "
            "affect your CGT main residence exemption. The portion of any capital gain "
            "relating to the business use period may be taxable. Consider seeking tax advice."
        )
        warnings.append("CGT main residence exemption may be affected")
    
    notes.append("Occupancy expenses require a dedicated area used exclusively for business")
    notes.append("Keep records of floor area measurements and expense receipts")
    
    if not input_data.is_owner:
        notes.append("As a tenant, you can claim the business portion of rent")
    
    return OccupancyCalculationResult(
        total_deduction=total_deduction,
        gst_claimable=gst_claimable,
        business_use_percentage=_round_percentage(float(business_use_pct * 100)),
        expense_breakdown=expense_breakdown,
        notes=notes,
        compliance_warnings=warnings,
        cgt_warning=cgt_warning
    )


# ==================== DEPRECIATION (GENERAL ASSETS) ====================

class DepreciationMethod(str, Enum):
    """Depreciation calculation methods."""
    DIMINISHING_VALUE = "diminishing_value"
    PRIME_COST = "prime_cost"
    INSTANT_ASSET_WRITE_OFF = "instant_write_off"
    POOL = "pool"  # Small business pool


# Instant Asset Write-off thresholds (historical)
INSTANT_WRITE_OFF_THRESHOLDS = {
    "2024-25": {"small_business": 20000, "general": 1000},
    "2023-24": {"small_business": 20000, "general": 1000},
    "2022-23": {"small_business": 150000, "general": 1000},  # COVID extension
    "2021-22": {"small_business": 150000, "general": 1000},
    "2020-21": {"small_business": 150000, "general": 1000},
}

# Small business pool depreciation rate
SMALL_BUSINESS_POOL_RATE = Decimal("0.15")  # First year
SMALL_BUSINESS_POOL_RATE_SUBSEQUENT = Decimal("0.30")  # Subsequent years

# Common effective lives (ATO TR 2024/3)
EFFECTIVE_LIVES = {
    "computer": 4,
    "laptop": 4,
    "monitor": 4,
    "printer": 5,
    "phone_mobile": 3,
    "phone_landline": 5,
    "furniture_office": 10,
    "furniture_other": 13,
    "air_conditioner": 10,
    "camera": 5,
    "tools_power": 5,
    "tools_hand": 5,
    "vehicle_car": 8,
    "vehicle_motorcycle": 8,
    "software": 4,
}


@dataclass
class AssetDepreciationInput:
    """Input for asset depreciation calculation."""
    asset_name: str
    asset_type: str  # Maps to EFFECTIVE_LIVES
    purchase_date: str  # YYYY-MM-DD
    purchase_price: float
    
    # Optional overrides
    effective_life_years: Optional[int] = None
    salvage_value: float = 0
    
    # Method selection
    method: str = "diminishing_value"
    
    # Business use
    business_use_percentage: float = 100
    
    # For continuing depreciation
    opening_written_down_value: Optional[float] = None
    year_of_depreciation: int = 1  # 1 = first year
    
    # Small business eligibility
    is_small_business: bool = False
    
    # Period
    days_held_in_year: int = 365


@dataclass
class DepreciationCalculationResult:
    """Result of depreciation calculation."""
    method: str
    depreciation_amount: Decimal
    opening_value: Decimal
    closing_written_down_value: Decimal
    effective_life_years: int
    rate: float
    business_portion: Decimal
    full_year_depreciation: Decimal
    notes: List[str]
    compliance_warnings: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "depreciation_amount": float(self.depreciation_amount),
            "opening_value": float(self.opening_value),
            "closing_written_down_value": float(self.closing_written_down_value),
            "effective_life_years": self.effective_life_years,
            "rate_percentage": self.rate,
            "business_portion": float(self.business_portion),
            "full_year_depreciation": float(self.full_year_depreciation),
            "notes": self.notes,
            "compliance_warnings": self.compliance_warnings
        }


def calculate_depreciation(input_data: AssetDepreciationInput) -> DepreciationCalculationResult:
    """
    Calculate asset depreciation.
    
    Methods:
    1. Diminishing Value: depreciation = base value × (days held ÷ 365) × (200% ÷ effective life)
    2. Prime Cost: depreciation = cost × (days held ÷ 365) × (100% ÷ effective life)
    3. Instant Write-off: Full deduction if under threshold
    4. Pool: Small business simplified depreciation pool
    
    Returns deterministic JSON-serializable result.
    """
    notes = []
    warnings = []
    
    # Determine effective life
    if input_data.effective_life_years:
        effective_life = input_data.effective_life_years
    else:
        effective_life = EFFECTIVE_LIVES.get(input_data.asset_type, 5)
        notes.append(f"Using ATO standard effective life of {effective_life} years for {input_data.asset_type}")
    
    purchase_price = Decimal(str(input_data.purchase_price))
    salvage_value = Decimal(str(input_data.salvage_value))
    depreciable_amount = purchase_price - salvage_value
    
    # Opening value
    if input_data.opening_written_down_value is not None:
        opening_value = Decimal(str(input_data.opening_written_down_value))
    else:
        opening_value = depreciable_amount
    
    # Days held factor
    days_factor = Decimal(str(input_data.days_held_in_year)) / Decimal("365")
    
    method = DepreciationMethod(input_data.method)
    
    if method == DepreciationMethod.INSTANT_ASSET_WRITE_OFF:
        # Check threshold
        threshold_key = "small_business" if input_data.is_small_business else "general"
        threshold = INSTANT_WRITE_OFF_THRESHOLDS.get("2024-25", {}).get(threshold_key, 1000)
        
        if purchase_price <= threshold:
            depreciation = opening_value
            rate = 100.0
            notes.append(f"Instant asset write-off: asset under ${threshold} threshold")
        else:
            warnings.append(f"Asset exceeds instant write-off threshold (${threshold}). Use another method.")
            depreciation = Decimal("0")
            rate = 0.0
        
        closing_value = Decimal("0")
        full_year_dep = depreciation
        
    elif method == DepreciationMethod.DIMINISHING_VALUE:
        # Rate = 200% / effective life
        rate = (200 / effective_life)
        rate_decimal = Decimal(str(rate / 100))
        
        full_year_dep = _round_currency(opening_value * rate_decimal)
        depreciation = _round_currency(full_year_dep * days_factor)
        
        # First year adjustment for new assets
        if input_data.year_of_depreciation == 1 and input_data.days_held_in_year < 365:
            notes.append(f"First year: pro-rata for {input_data.days_held_in_year} days")
        
        closing_value = opening_value - depreciation
        
    elif method == DepreciationMethod.PRIME_COST:
        # Rate = 100% / effective life
        rate = (100 / effective_life)
        rate_decimal = Decimal(str(rate / 100))
        
        full_year_dep = _round_currency(depreciable_amount * rate_decimal)
        depreciation = _round_currency(full_year_dep * days_factor)
        
        if input_data.year_of_depreciation == 1 and input_data.days_held_in_year < 365:
            notes.append(f"First year: pro-rata for {input_data.days_held_in_year} days")
        
        closing_value = opening_value - depreciation
        
    elif method == DepreciationMethod.POOL:
        # Small business pool
        if not input_data.is_small_business:
            warnings.append("Pool method is only for small businesses")
        
        if input_data.year_of_depreciation == 1:
            rate = float(SMALL_BUSINESS_POOL_RATE * 100)
            rate_decimal = SMALL_BUSINESS_POOL_RATE
        else:
            rate = float(SMALL_BUSINESS_POOL_RATE_SUBSEQUENT * 100)
            rate_decimal = SMALL_BUSINESS_POOL_RATE_SUBSEQUENT
        
        full_year_dep = _round_currency(opening_value * rate_decimal)
        depreciation = full_year_dep  # Pool is not pro-rated
        closing_value = opening_value - depreciation
        
        notes.append(f"Small business pool: {rate}% rate applied")
    
    else:
        depreciation = Decimal("0")
        closing_value = opening_value
        rate = 0.0
        full_year_dep = Decimal("0")
        warnings.append(f"Unknown depreciation method: {input_data.method}")
    
    # Apply business use percentage
    business_use_pct = Decimal(str(input_data.business_use_percentage / 100))
    business_portion = _round_currency(depreciation * business_use_pct)
    
    if input_data.business_use_percentage < 100:
        notes.append(f"Business use: {input_data.business_use_percentage}%")
    
    # Ensure closing value doesn't go negative
    if closing_value < 0:
        closing_value = Decimal("0")
    
    return DepreciationCalculationResult(
        method=input_data.method,
        depreciation_amount=depreciation,
        opening_value=opening_value,
        closing_written_down_value=closing_value,
        effective_life_years=effective_life,
        rate=_round_percentage(rate),
        business_portion=business_portion,
        full_year_depreciation=full_year_dep,
        notes=notes,
        compliance_warnings=warnings
    )


# ==================== MOTOR VEHICLE ENHANCEMENTS ====================

class MVMethod(str, Enum):
    """Motor Vehicle calculation methods."""
    CENTS_PER_KM = "cents_per_km"
    LOGBOOK = "logbook"


# Current ATO rates (2024-25)
CENTS_PER_KM_RATE = Decimal("0.85")  # 85 cents per km
CENTS_PER_KM_MAX_KM = 5000  # Maximum 5,000 km
CAR_DEPRECIATION_LIMIT = Decimal("68108")  # 2024-25 car limit


@dataclass
class MotorVehicleCalculationInput:
    """Input for motor vehicle deduction calculation."""
    method: str = "cents_per_km"
    
    # Cents per km method
    business_km: float = 0
    
    # Logbook method
    logbook_business_percentage: float = 0
    total_expenses: Dict[str, float] = field(default_factory=dict)
    
    # Vehicle details (for depreciation)
    vehicle_cost: float = 0
    is_car: bool = True  # Cars have depreciation limit
    purchase_date: Optional[str] = None
    depreciation_method: str = "diminishing_value"
    depreciation_year: int = 1


@dataclass
class MotorVehicleCalculationResult:
    """Result of motor vehicle calculation."""
    method: str
    deduction_amount: Decimal
    gst_claimable: Decimal
    breakdown: Dict[str, Any]
    notes: List[str]
    compliance_warnings: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "deduction_amount": float(self.deduction_amount),
            "gst_claimable": float(self.gst_claimable),
            "breakdown": self.breakdown,
            "notes": self.notes,
            "compliance_warnings": self.compliance_warnings
        }


def calculate_motor_vehicle_deduction(input_data: MotorVehicleCalculationInput) -> MotorVehicleCalculationResult:
    """
    Calculate motor vehicle deduction.
    
    Methods:
    1. Cents per km: 85c × business km (max 5,000 km = $4,250)
    2. Logbook: Actual expenses × business use %
    
    Returns deterministic JSON-serializable result.
    """
    notes = []
    warnings = []
    breakdown = {}
    gst_claimable = Decimal("0")
    
    method = MVMethod(input_data.method)
    
    if method == MVMethod.CENTS_PER_KM:
        km = min(input_data.business_km, CENTS_PER_KM_MAX_KM)
        
        if input_data.business_km > CENTS_PER_KM_MAX_KM:
            warnings.append(f"Business km ({input_data.business_km}) exceeds maximum ({CENTS_PER_KM_MAX_KM}). Capped at {CENTS_PER_KM_MAX_KM} km.")
            notes.append("Consider logbook method for higher km claims")
        
        deduction = _round_currency(Decimal(str(km)) * CENTS_PER_KM_RATE)
        
        breakdown = {
            "business_km_claimed": km,
            "business_km_actual": input_data.business_km,
            "rate_per_km": float(CENTS_PER_KM_RATE),
            "maximum_km": CENTS_PER_KM_MAX_KM,
            "calculation": f"{km} km × $0.85 = ${float(deduction):.2f}"
        }
        
        notes.append("Cents per km method: No receipts required, but must be able to show how km was calculated")
        notes.append("This rate covers all vehicle running costs including fuel, registration, insurance, depreciation")
        
        # No separate GST claim under cents per km
        gst_claimable = Decimal("0")
        
    elif method == MVMethod.LOGBOOK:
        business_pct = Decimal(str(input_data.logbook_business_percentage / 100))
        
        if input_data.logbook_business_percentage <= 0:
            warnings.append("Logbook business percentage must be greater than 0")
            deduction = Decimal("0")
        else:
            total_expenses = Decimal("0")
            expense_breakdown = {}
            
            for expense_type, amount in input_data.total_expenses.items():
                exp_amount = Decimal(str(amount))
                business_amount = _round_currency(exp_amount * business_pct)
                expense_breakdown[expense_type] = {
                    "total": float(exp_amount),
                    "business_portion": float(business_amount)
                }
                total_expenses += business_amount
                
                # GST calculation (varies by expense type)
                gst_applicable = expense_type not in ["insurance_stamp_duty", "interest", "depreciation", "registration_stamp_duty"]
                if gst_applicable:
                    gst_component = _round_currency(business_amount / GST_DIVISOR)
                    gst_claimable += gst_component
                    expense_breakdown[expense_type]["gst_claimable"] = float(gst_component)
            
            deduction = _round_currency(total_expenses)
            
            breakdown = {
                "logbook_business_percentage": input_data.logbook_business_percentage,
                "expenses": expense_breakdown,
                "total_deduction": float(deduction)
            }
            
            notes.append("Logbook must be kept for continuous 12-week period")
            notes.append("Logbook is valid for 5 years if circumstances haven't changed")
            notes.append("Keep all receipts for claimed expenses")
    
    else:
        deduction = Decimal("0")
        warnings.append(f"Unknown method: {input_data.method}")
    
    return MotorVehicleCalculationResult(
        method=input_data.method,
        deduction_amount=deduction,
        gst_claimable=gst_claimable,
        breakdown=breakdown,
        notes=notes,
        compliance_warnings=warnings
    )


# ==================== COMBINED MODULE STATUS ====================

def get_tax_modules_status() -> Dict[str, Any]:
    """Return status of all tax calculation modules."""
    return {
        "modules": {
            "pob": {
                "name": "Place of Business (Home Office)",
                "methods": [m.value for m in POBMethod],
                "current_rate": f"${float(POB_FIXED_RATE_PER_HOUR)}/hour (fixed rate)",
                "status": "active"
            },
            "occupancy": {
                "name": "Occupancy Expenses",
                "expense_types": [e.value for e in OccupancyExpenseType],
                "status": "active"
            },
            "depreciation": {
                "name": "Asset Depreciation",
                "methods": [m.value for m in DepreciationMethod],
                "instant_write_off_threshold": INSTANT_WRITE_OFF_THRESHOLDS.get("2024-25"),
                "status": "active"
            },
            "motor_vehicle": {
                "name": "Motor Vehicle",
                "methods": [m.value for m in MVMethod],
                "cents_per_km_rate": float(CENTS_PER_KM_RATE),
                "cents_per_km_max": CENTS_PER_KM_MAX_KM,
                "car_limit": float(CAR_DEPRECIATION_LIMIT),
                "status": "active"
            }
        },
        "tax_year": "2024-25",
        "last_updated": "2025-01",
        "compliance": "ATO guidelines"
    }
