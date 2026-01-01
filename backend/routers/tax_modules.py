"""
FDC Core - Tax Module API Router

Provides REST API endpoints for tax calculations:
- POB (Place of Business / Home Office)
- Occupancy Expenses
- Depreciation (General Assets)
- Motor Vehicle

All endpoints return deterministic JSON responses.
Follows ATO guidelines and Ben's compliance specifications.
"""

import logging
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel, Field

from services.tax_modules import (
    # POB
    calculate_pob,
    POBCalculationInput,
    POBMethod,
    POB_FIXED_RATE_PER_HOUR,
    POB_EXPENSE_CATEGORIES,
    
    # Occupancy
    calculate_occupancy,
    OccupancyCalculationInput,
    OccupancyExpenseType,
    OCCUPANCY_GST_RULES,
    
    # Depreciation
    calculate_depreciation,
    AssetDepreciationInput,
    DepreciationMethod,
    EFFECTIVE_LIVES,
    INSTANT_WRITE_OFF_THRESHOLDS,
    
    # Motor Vehicle
    calculate_motor_vehicle_deduction,
    MotorVehicleCalculationInput,
    MVMethod,
    CENTS_PER_KM_RATE,
    CENTS_PER_KM_MAX_KM,
    CAR_DEPRECIATION_LIMIT,
    
    # Status
    get_tax_modules_status
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tax", tags=["Tax Modules"])


# ==================== REQUEST MODELS ====================

class POBCalculateRequest(BaseModel):
    """Request model for POB calculation."""
    method: str = Field(default="fixed_rate", description="Calculation method: fixed_rate, actual_cost, shortcut")
    hours_worked: float = Field(default=0, ge=0, description="Total hours worked from home")
    floor_area_office: float = Field(default=0, ge=0, description="Office floor area (sqm)")
    floor_area_total: float = Field(default=0, ge=0, description="Total home floor area (sqm)")
    expenses: Dict[str, float] = Field(default_factory=dict, description="Running expenses by category")
    dedicated_office: bool = Field(default=False, description="Is office space exclusively for work?")
    days_per_week: float = Field(default=5, description="Average days worked from home per week")
    
    class Config:
        json_schema_extra = {
            "example": {
                "method": "fixed_rate",
                "hours_worked": 1200,
                "dedicated_office": True
            }
        }


class OccupancyCalculateRequest(BaseModel):
    """Request model for occupancy calculation."""
    expenses: Dict[str, float] = Field(..., description="Expense amounts by type")
    floor_area_business: float = Field(default=0, ge=0, description="Business area (sqm)")
    floor_area_total: float = Field(default=0, ge=0, description="Total home area (sqm)")
    business_use_percentage: Optional[float] = Field(default=None, ge=0, le=100, description="Direct business use %")
    is_owner: bool = Field(default=True, description="Owner (not tenant)")
    principal_residence: bool = Field(default=True, description="Main residence")
    
    class Config:
        json_schema_extra = {
            "example": {
                "expenses": {
                    "mortgage_interest": 24000,
                    "council_rates": 2400,
                    "house_insurance": 1800
                },
                "floor_area_business": 15,
                "floor_area_total": 150,
                "is_owner": True,
                "principal_residence": True
            }
        }


class DepreciationCalculateRequest(BaseModel):
    """Request model for depreciation calculation."""
    asset_name: str = Field(..., description="Asset description")
    asset_type: str = Field(default="computer", description="Asset type for effective life lookup")
    purchase_date: str = Field(..., description="Purchase date (YYYY-MM-DD)")
    purchase_price: float = Field(..., gt=0, description="Purchase price")
    effective_life_years: Optional[int] = Field(default=None, ge=1, description="Override effective life")
    salvage_value: float = Field(default=0, ge=0, description="Expected salvage value")
    method: str = Field(default="diminishing_value", description="Depreciation method")
    business_use_percentage: float = Field(default=100, ge=0, le=100, description="Business use %")
    opening_written_down_value: Optional[float] = Field(default=None, description="Opening WDV for continuing depreciation")
    year_of_depreciation: int = Field(default=1, ge=1, description="Year of depreciation (1=first year)")
    is_small_business: bool = Field(default=False, description="Small business entity")
    days_held_in_year: int = Field(default=365, ge=1, le=366, description="Days held in FY")
    
    class Config:
        json_schema_extra = {
            "example": {
                "asset_name": "MacBook Pro",
                "asset_type": "laptop",
                "purchase_date": "2024-07-15",
                "purchase_price": 3499,
                "method": "diminishing_value",
                "business_use_percentage": 80,
                "days_held_in_year": 350
            }
        }


class MotorVehicleCalculateRequest(BaseModel):
    """Request model for motor vehicle calculation."""
    method: str = Field(default="cents_per_km", description="Calculation method: cents_per_km, logbook")
    business_km: float = Field(default=0, ge=0, description="Business kilometres (cents per km method)")
    logbook_business_percentage: float = Field(default=0, ge=0, le=100, description="Logbook business use %")
    total_expenses: Dict[str, float] = Field(default_factory=dict, description="Expenses by category (logbook method)")
    vehicle_cost: float = Field(default=0, ge=0, description="Vehicle purchase cost")
    is_car: bool = Field(default=True, description="Is vehicle a car (affects depreciation limit)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "method": "cents_per_km",
                "business_km": 4500
            }
        }


# ==================== STATUS ENDPOINT ====================

@router.get("/status")
async def get_status():
    """
    Get status of all tax calculation modules.
    
    Returns current rates, thresholds, and available methods.
    """
    return get_tax_modules_status()


# ==================== POB ENDPOINTS ====================

@router.get("/pob/info")
async def get_pob_info():
    """
    Get POB (Place of Business) module information.
    
    Returns available methods, rates, and expense categories.
    """
    return {
        "module": "pob",
        "name": "Place of Business (Home Office)",
        "methods": {
            "fixed_rate": {
                "description": "67 cents per hour - covers electricity, phone, internet, stationery",
                "rate": float(POB_FIXED_RATE_PER_HOUR),
                "requires": ["hours_worked"]
            },
            "actual_cost": {
                "description": "Calculate actual running expenses × business use %",
                "requires": ["floor_area_office", "floor_area_total", "expenses"]
            },
            "shortcut": {
                "description": "80 cents per hour (COVID only, ended 30 June 2022)",
                "rate": 0.80,
                "requires": ["hours_worked"],
                "note": "Historical method only"
            }
        },
        "expense_categories": POB_EXPENSE_CATEGORIES,
        "tax_year": "2024-25"
    }


@router.post("/pob/calculate")
async def calculate_pob_deduction(request: POBCalculateRequest):
    """
    Calculate Place of Business (Home Office) deduction.
    
    **Methods:**
    - `fixed_rate`: 67c per hour (current standard method)
    - `actual_cost`: Actual expenses × business use %
    - `shortcut`: 80c per hour (ended 30 June 2022)
    
    Returns deterministic JSON with deduction amount and breakdown.
    """
    try:
        input_data = POBCalculationInput(
            method=request.method,
            hours_worked=request.hours_worked,
            floor_area_office=request.floor_area_office,
            floor_area_total=request.floor_area_total,
            expenses=request.expenses,
            dedicated_office=request.dedicated_office,
            days_per_week=request.days_per_week
        )
        
        result = calculate_pob(input_data)
        
        return result.to_dict()
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== OCCUPANCY ENDPOINTS ====================

@router.get("/occupancy/info")
async def get_occupancy_info():
    """
    Get Occupancy module information.
    
    Returns expense types and GST rules.
    """
    return {
        "module": "occupancy",
        "name": "Occupancy Expenses",
        "description": "Deductions for home ownership/rental costs when using home for business",
        "expense_types": {
            exp.value: {
                "gst_claimable": rules["gst_claimable"],
                "note": rules.get("note", "")
            }
            for exp, rules in OCCUPANCY_GST_RULES.items()
        },
        "requirements": [
            "Dedicated area used exclusively for business",
            "Floor area measurements",
            "Receipts for all expenses"
        ],
        "cgt_warning": "Claiming occupancy expenses for principal residence may affect CGT main residence exemption",
        "tax_year": "2024-25"
    }


@router.post("/occupancy/calculate")
async def calculate_occupancy_deduction(request: OccupancyCalculateRequest):
    """
    Calculate Occupancy expense deduction.
    
    **Expense Types:**
    - `rent`, `mortgage_interest`, `council_rates`
    - `land_tax`, `house_insurance`, `water_rates`, `body_corporate`
    
    **WARNING:** Claiming occupancy for principal residence may affect CGT exemption.
    
    Returns deterministic JSON with deduction and CGT warning.
    """
    try:
        input_data = OccupancyCalculationInput(
            expenses=request.expenses,
            floor_area_business=request.floor_area_business,
            floor_area_total=request.floor_area_total,
            business_use_percentage=request.business_use_percentage,
            is_owner=request.is_owner,
            principal_residence=request.principal_residence
        )
        
        result = calculate_occupancy(input_data)
        
        return result.to_dict()
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== DEPRECIATION ENDPOINTS ====================

@router.get("/depreciation/info")
async def get_depreciation_info():
    """
    Get Depreciation module information.
    
    Returns methods, effective lives, and write-off thresholds.
    """
    return {
        "module": "depreciation",
        "name": "Asset Depreciation",
        "methods": {
            "diminishing_value": {
                "description": "Depreciation = base value × (days ÷ 365) × (200% ÷ effective life)",
                "note": "Higher deductions in early years"
            },
            "prime_cost": {
                "description": "Depreciation = cost × (days ÷ 365) × (100% ÷ effective life)",
                "note": "Equal deductions each year"
            },
            "instant_write_off": {
                "description": "Full deduction in year of purchase if under threshold",
                "thresholds": INSTANT_WRITE_OFF_THRESHOLDS.get("2024-25")
            },
            "pool": {
                "description": "Small business simplified depreciation pool",
                "rates": {"first_year": "15%", "subsequent": "30%"},
                "eligibility": "Small business entities only"
            }
        },
        "effective_lives": EFFECTIVE_LIVES,
        "tax_year": "2024-25"
    }


@router.get("/depreciation/effective-life/{asset_type}")
async def get_effective_life(asset_type: str):
    """
    Get ATO effective life for an asset type.
    
    **Common Types:** computer, laptop, monitor, printer, phone_mobile, 
    furniture_office, air_conditioner, camera, tools_power, vehicle_car
    """
    effective_life = EFFECTIVE_LIVES.get(asset_type)
    
    if effective_life is None:
        return {
            "asset_type": asset_type,
            "effective_life_years": None,
            "note": f"Unknown asset type. Use custom effective_life_years or refer to TR 2024/3.",
            "available_types": list(EFFECTIVE_LIVES.keys())
        }
    
    return {
        "asset_type": asset_type,
        "effective_life_years": effective_life,
        "diminishing_value_rate": round(200 / effective_life, 2),
        "prime_cost_rate": round(100 / effective_life, 2)
    }


@router.post("/depreciation/calculate")
async def calculate_depreciation_deduction(request: DepreciationCalculateRequest):
    """
    Calculate asset depreciation.
    
    **Methods:**
    - `diminishing_value`: Higher deductions early
    - `prime_cost`: Equal annual deductions
    - `instant_write_off`: Full deduction if under threshold
    - `pool`: Small business pool (15%/30%)
    
    Returns deterministic JSON with depreciation amount and WDV.
    """
    try:
        input_data = AssetDepreciationInput(
            asset_name=request.asset_name,
            asset_type=request.asset_type,
            purchase_date=request.purchase_date,
            purchase_price=request.purchase_price,
            effective_life_years=request.effective_life_years,
            salvage_value=request.salvage_value,
            method=request.method,
            business_use_percentage=request.business_use_percentage,
            opening_written_down_value=request.opening_written_down_value,
            year_of_depreciation=request.year_of_depreciation,
            is_small_business=request.is_small_business,
            days_held_in_year=request.days_held_in_year
        )
        
        result = calculate_depreciation(input_data)
        
        return result.to_dict()
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== MOTOR VEHICLE ENDPOINTS ====================

@router.get("/motor-vehicle/info")
async def get_motor_vehicle_info():
    """
    Get Motor Vehicle module information.
    
    Returns methods, rates, and limits.
    """
    return {
        "module": "motor_vehicle",
        "name": "Motor Vehicle Deductions",
        "methods": {
            "cents_per_km": {
                "description": "Claim a set rate per business kilometre",
                "rate": float(CENTS_PER_KM_RATE),
                "max_km": CENTS_PER_KM_MAX_KM,
                "max_deduction": float(CENTS_PER_KM_RATE * CENTS_PER_KM_MAX_KM),
                "requires": ["business_km"],
                "records": "Must show how km calculated, no receipts needed"
            },
            "logbook": {
                "description": "Claim actual expenses × business use %",
                "requires": ["logbook_business_percentage", "total_expenses"],
                "records": "12-week logbook + all expense receipts"
            }
        },
        "car_depreciation_limit": float(CAR_DEPRECIATION_LIMIT),
        "tax_year": "2024-25"
    }


@router.post("/motor-vehicle/calculate")
async def calculate_motor_vehicle(request: MotorVehicleCalculateRequest):
    """
    Calculate Motor Vehicle deduction.
    
    **Methods:**
    - `cents_per_km`: 85c × km (max 5,000 km = $4,250)
    - `logbook`: Actual expenses × business use %
    
    Returns deterministic JSON with deduction amount and breakdown.
    """
    try:
        input_data = MotorVehicleCalculationInput(
            method=request.method,
            business_km=request.business_km,
            logbook_business_percentage=request.logbook_business_percentage,
            total_expenses=request.total_expenses,
            vehicle_cost=request.vehicle_cost,
            is_car=request.is_car
        )
        
        result = calculate_motor_vehicle_deduction(input_data)
        
        return result.to_dict()
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== COMBINED CALCULATION ====================

class CombinedTaxCalculationRequest(BaseModel):
    """Request for calculating multiple modules at once."""
    pob: Optional[POBCalculateRequest] = None
    occupancy: Optional[OccupancyCalculateRequest] = None
    depreciation: Optional[List[DepreciationCalculateRequest]] = None
    motor_vehicle: Optional[MotorVehicleCalculateRequest] = None


@router.post("/calculate-all")
async def calculate_all_modules(request: CombinedTaxCalculationRequest):
    """
    Calculate deductions for multiple tax modules at once.
    
    Submit any combination of POB, Occupancy, Depreciation, and Motor Vehicle.
    Returns combined results with total deduction.
    """
    results = {}
    total_deduction = 0.0
    total_gst = 0.0
    all_warnings = []
    
    if request.pob:
        pob_input = POBCalculationInput(
            method=request.pob.method,
            hours_worked=request.pob.hours_worked,
            floor_area_office=request.pob.floor_area_office,
            floor_area_total=request.pob.floor_area_total,
            expenses=request.pob.expenses,
            dedicated_office=request.pob.dedicated_office
        )
        pob_result = calculate_pob(pob_input)
        results["pob"] = pob_result.to_dict()
        total_deduction += float(pob_result.deduction_amount)
        total_gst += float(pob_result.gst_claimable)
        all_warnings.extend([f"POB: {w}" for w in pob_result.compliance_warnings])
    
    if request.occupancy:
        occ_input = OccupancyCalculationInput(
            expenses=request.occupancy.expenses,
            floor_area_business=request.occupancy.floor_area_business,
            floor_area_total=request.occupancy.floor_area_total,
            business_use_percentage=request.occupancy.business_use_percentage,
            is_owner=request.occupancy.is_owner,
            principal_residence=request.occupancy.principal_residence
        )
        occ_result = calculate_occupancy(occ_input)
        results["occupancy"] = occ_result.to_dict()
        total_deduction += float(occ_result.total_deduction)
        total_gst += float(occ_result.gst_claimable)
        all_warnings.extend([f"Occupancy: {w}" for w in occ_result.compliance_warnings])
    
    if request.depreciation:
        dep_results = []
        for dep_req in request.depreciation:
            dep_input = AssetDepreciationInput(
                asset_name=dep_req.asset_name,
                asset_type=dep_req.asset_type,
                purchase_date=dep_req.purchase_date,
                purchase_price=dep_req.purchase_price,
                effective_life_years=dep_req.effective_life_years,
                salvage_value=dep_req.salvage_value,
                method=dep_req.method,
                business_use_percentage=dep_req.business_use_percentage,
                opening_written_down_value=dep_req.opening_written_down_value,
                year_of_depreciation=dep_req.year_of_depreciation,
                is_small_business=dep_req.is_small_business,
                days_held_in_year=dep_req.days_held_in_year
            )
            dep_result = calculate_depreciation(dep_input)
            dep_results.append({
                "asset_name": dep_req.asset_name,
                **dep_result.to_dict()
            })
            total_deduction += float(dep_result.business_portion)
            all_warnings.extend([f"Depreciation ({dep_req.asset_name}): {w}" for w in dep_result.compliance_warnings])
        
        results["depreciation"] = dep_results
    
    if request.motor_vehicle:
        mv_input = MotorVehicleCalculationInput(
            method=request.motor_vehicle.method,
            business_km=request.motor_vehicle.business_km,
            logbook_business_percentage=request.motor_vehicle.logbook_business_percentage,
            total_expenses=request.motor_vehicle.total_expenses,
            vehicle_cost=request.motor_vehicle.vehicle_cost,
            is_car=request.motor_vehicle.is_car
        )
        mv_result = calculate_motor_vehicle_deduction(mv_input)
        results["motor_vehicle"] = mv_result.to_dict()
        total_deduction += float(mv_result.deduction_amount)
        total_gst += float(mv_result.gst_claimable)
        all_warnings.extend([f"Motor Vehicle: {w}" for w in mv_result.compliance_warnings])
    
    return {
        "modules": results,
        "summary": {
            "total_deduction": round(total_deduction, 2),
            "total_gst_claimable": round(total_gst, 2),
            "modules_calculated": list(results.keys())
        },
        "compliance_warnings": all_warnings,
        "tax_year": "2024-25"
    }
