"""
FDC Core Workpaper Platform - Motor Vehicle Module API Router

Complete API for Motor Vehicle module including:
- Module configuration and detail
- KM tracking endpoints
- Asset purchase/sale management
- Calculation endpoint
- Freeze with comprehensive snapshot
"""

from fastapi import APIRouter, Depends, HTTPException, Query as QueryParam
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, date
from pydantic import BaseModel, Field
import logging

from database import get_db
from database.motor_vehicle_models import (
    VehicleAssetDB, VehicleKMEntryDB, VehicleLogbookPeriodDB, VehicleFuelEstimateDB
)
from middleware.auth import require_staff, require_admin, AuthUser

from services.workpaper import (
    JobStatus, ModuleType,
    WorkpaperJobRepository, ModuleInstanceRepository, TransactionRepository,
    OverrideRecordRepository, FreezeSnapshotRepository,
    EffectiveTransactionBuilder,
)
from services.workpaper.motor_vehicle_engine import (
    calculate_motor_vehicle, get_gst_rules, get_ato_rates,
    MVMethod, DepreciationMethod, CENTS_PER_KM_RATE, CENTS_PER_KM_MAX
)
from services.audit import log_action, AuditAction, ResourceType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workpaper/mv", tags=["Motor Vehicle Module"])


# ==================== PYDANTIC MODELS ====================

class KMEntryCreate(BaseModel):
    """Request to create a KM entry"""
    entry_type: str = "trip"  # odometer, trip, summary
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    odometer_start: Optional[int] = None
    odometer_end: Optional[int] = None
    total_km: Optional[float] = None
    business_km: Optional[float] = None
    private_km: Optional[float] = None
    trip_purpose: Optional[str] = None
    trip_from: Optional[str] = None
    trip_to: Optional[str] = None
    source: str = "manual"
    notes: Optional[str] = None


class KMEntry(BaseModel):
    """KM entry response"""
    id: str
    module_instance_id: str
    entry_type: str
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    odometer_start: Optional[int] = None
    odometer_end: Optional[int] = None
    total_km: Optional[float] = None
    business_km: Optional[float] = None
    private_km: Optional[float] = None
    trip_purpose: Optional[str] = None
    trip_from: Optional[str] = None
    trip_to: Optional[str] = None
    source: str
    notes: Optional[str] = None
    created_at: Optional[str] = None


class KMSummary(BaseModel):
    """KM summary for module"""
    total_km: float = 0
    business_km: float = 0
    private_km: float = 0
    business_percentage: float = 0
    entry_count: int = 0
    has_odometer_readings: bool = False
    has_trip_logs: bool = False


class AssetPurchaseCreate(BaseModel):
    """Request to create/update vehicle purchase"""
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    registration: Optional[str] = None
    purchase_date: str
    purchase_price: float
    purchase_gst: Optional[float] = None
    gst_registered_at_purchase: bool = False
    depreciation_method: str = "diminishing_value"
    effective_life_years: float = 8.0
    opening_adjustable_value: Optional[float] = None
    notes: Optional[str] = None


class AssetSaleCreate(BaseModel):
    """Request to record vehicle sale"""
    sale_date: str
    sale_price: float
    sale_gst: Optional[float] = None


class VehicleAsset(BaseModel):
    """Vehicle asset response"""
    id: str
    module_instance_id: str
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    registration: Optional[str] = None
    purchase_date: Optional[str] = None
    purchase_price: Optional[float] = None
    purchase_gst: Optional[float] = None
    gst_registered_at_purchase: bool = False
    sale_date: Optional[str] = None
    sale_price: Optional[float] = None
    sale_gst: Optional[float] = None
    depreciation_method: str
    effective_life_years: float
    cost_base: Optional[float] = None
    adjustable_value_start: Optional[float] = None
    adjustable_value_end: Optional[float] = None
    depreciation_amount: Optional[float] = None
    balancing_adjustment: Optional[float] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None


class FuelEstimateCreate(BaseModel):
    """Request to create fuel estimate"""
    fuel_type: str = "petrol"
    engine_size_litres: Optional[float] = None
    consumption_rate: Optional[float] = None
    fuel_price_per_litre: Optional[float] = None
    business_km: float
    notes: Optional[str] = None


class FuelEstimate(BaseModel):
    """Fuel estimate response"""
    id: str
    module_instance_id: str
    fuel_type: str
    engine_size_litres: Optional[float] = None
    consumption_rate: Optional[float] = None
    fuel_price_per_litre: Optional[float] = None
    business_km: Optional[float] = None
    estimated_litres: Optional[float] = None
    estimated_fuel_cost: Optional[float] = None
    estimated_gst: Optional[float] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None


class MVConfigUpdate(BaseModel):
    """Request to update MV module config"""
    method: Optional[str] = None
    business_km: Optional[float] = None
    total_km: Optional[float] = None
    private_km: Optional[float] = None
    logbook_pct: Optional[float] = None
    depreciation_method: Optional[str] = None
    opening_adjustable_value: Optional[float] = None
    effective_life_years: Optional[float] = None
    use_actual_fuel: Optional[bool] = None
    override_business_pct: Optional[float] = None


class LogbookPeriodCreate(BaseModel):
    """Request to create logbook period"""
    period_start: str
    period_end: str
    total_km: float
    business_km: float
    private_km: float
    notes: Optional[str] = None


class LogbookPeriod(BaseModel):
    """Logbook period response"""
    id: str
    module_instance_id: str
    period_start: str
    period_end: str
    total_km: float
    business_km: float
    private_km: float
    business_percentage: float
    is_valid: bool
    validation_notes: Optional[str] = None
    approved_by_admin_id: Optional[str] = None
    approved_at: Optional[str] = None
    created_at: Optional[str] = None


class MVModuleDetail(BaseModel):
    """Complete Motor Vehicle module detail"""
    module_id: str
    module_type: str
    label: str
    status: str
    config: Dict[str, Any]
    
    # KM data
    km_summary: KMSummary
    km_entries: List[KMEntry] = Field(default_factory=list)
    
    # Asset
    asset: Optional[VehicleAsset] = None
    
    # Fuel estimate
    fuel_estimate: Optional[FuelEstimate] = None
    
    # Logbook
    logbook_period: Optional[LogbookPeriod] = None
    
    # Transactions
    effective_transactions: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Calculation output (if calculated)
    output_summary: Optional[Dict[str, Any]] = None
    
    # Method options
    available_methods: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Frozen status
    frozen_at: Optional[str] = None


# ==================== HELPER FUNCTIONS ====================

def _parse_date(date_str: Optional[str]) -> Optional[date]:
    """Parse date string to date object"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def _format_date(d: Optional[date]) -> Optional[str]:
    """Format date object to string"""
    if not d:
        return None
    return d.isoformat()


async def _get_km_summary(db: AsyncSession, module_id: str) -> KMSummary:
    """Calculate KM summary from entries"""
    result = await db.execute(
        select(VehicleKMEntryDB).where(VehicleKMEntryDB.module_instance_id == module_id)
    )
    entries = result.scalars().all()
    
    total_km = 0.0
    business_km = 0.0
    private_km = 0.0
    has_odometer = False
    has_trips = False
    
    for entry in entries:
        if entry.entry_type == "odometer":
            has_odometer = True
            if entry.odometer_start and entry.odometer_end:
                total_km += entry.odometer_end - entry.odometer_start
        elif entry.entry_type == "trip":
            has_trips = True
        
        if entry.total_km:
            total_km = max(total_km, entry.total_km)
        if entry.business_km:
            business_km += entry.business_km
        if entry.private_km:
            private_km += entry.private_km
    
    business_pct = (business_km / total_km * 100) if total_km > 0 else 0
    
    return KMSummary(
        total_km=round(total_km, 1),
        business_km=round(business_km, 1),
        private_km=round(private_km, 1),
        business_percentage=round(business_pct, 2),
        entry_count=len(entries),
        has_odometer_readings=has_odometer,
        has_trip_logs=has_trips,
    )


# ==================== ENDPOINTS ====================

@router.get("/modules/{module_id}", response_model=MVModuleDetail)
async def get_mv_module_detail(
    module_id: str,
    include_transactions: bool = QueryParam(True),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get complete Motor Vehicle module detail.
    
    Returns:
    - Module config and status
    - KM summary and entries
    - Asset purchase/sale details
    - Fuel estimate (if using estimated fuel method)
    - Logbook period (if using logbook method)
    - Effective transactions (if include_transactions=True)
    - Calculation output (if calculated)
    """
    module_repo = ModuleInstanceRepository(db)
    job_repo = WorkpaperJobRepository(db)
    
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.module_type != ModuleType.MOTOR_VEHICLE.value:
        raise HTTPException(status_code=400, detail="Not a Motor Vehicle module")
    
    job = await job_repo.get(module.job_id)
    
    # Get KM summary and entries
    km_summary = await _get_km_summary(db, module_id)
    
    km_result = await db.execute(
        select(VehicleKMEntryDB)
        .where(VehicleKMEntryDB.module_instance_id == module_id)
        .order_by(VehicleKMEntryDB.date_from.desc())
    )
    km_entries = [
        KMEntry(
            id=e.id,
            module_instance_id=e.module_instance_id,
            entry_type=e.entry_type,
            date_from=_format_date(e.date_from),
            date_to=_format_date(e.date_to),
            odometer_start=e.odometer_start,
            odometer_end=e.odometer_end,
            total_km=e.total_km,
            business_km=e.business_km,
            private_km=e.private_km,
            trip_purpose=e.trip_purpose,
            trip_from=e.trip_from,
            trip_to=e.trip_to,
            source=e.source,
            notes=e.notes,
            created_at=e.created_at.isoformat() if e.created_at else None,
        )
        for e in km_result.scalars().all()
    ]
    
    # Get asset
    asset_result = await db.execute(
        select(VehicleAssetDB).where(VehicleAssetDB.module_instance_id == module_id)
    )
    asset_db = asset_result.scalar_one_or_none()
    asset = None
    if asset_db:
        asset = VehicleAsset(
            id=asset_db.id,
            module_instance_id=asset_db.module_instance_id,
            make=asset_db.make,
            model=asset_db.model,
            year=asset_db.year,
            registration=asset_db.registration,
            purchase_date=_format_date(asset_db.purchase_date),
            purchase_price=asset_db.purchase_price,
            purchase_gst=asset_db.purchase_gst,
            gst_registered_at_purchase=asset_db.gst_registered_at_purchase,
            sale_date=_format_date(asset_db.sale_date),
            sale_price=asset_db.sale_price,
            sale_gst=asset_db.sale_gst,
            depreciation_method=asset_db.depreciation_method,
            effective_life_years=asset_db.effective_life_years,
            cost_base=asset_db.cost_base,
            adjustable_value_start=asset_db.adjustable_value_start,
            adjustable_value_end=asset_db.adjustable_value_end,
            depreciation_amount=asset_db.depreciation_amount,
            balancing_adjustment=asset_db.balancing_adjustment,
            notes=asset_db.notes,
            created_at=asset_db.created_at.isoformat() if asset_db.created_at else None,
        )
    
    # Get fuel estimate
    fuel_result = await db.execute(
        select(VehicleFuelEstimateDB).where(VehicleFuelEstimateDB.module_instance_id == module_id)
    )
    fuel_db = fuel_result.scalar_one_or_none()
    fuel_estimate = None
    if fuel_db:
        fuel_estimate = FuelEstimate(
            id=fuel_db.id,
            module_instance_id=fuel_db.module_instance_id,
            fuel_type=fuel_db.fuel_type,
            engine_size_litres=fuel_db.engine_size_litres,
            consumption_rate=fuel_db.consumption_rate,
            fuel_price_per_litre=fuel_db.fuel_price_per_litre,
            business_km=fuel_db.business_km,
            estimated_litres=fuel_db.estimated_litres,
            estimated_fuel_cost=fuel_db.estimated_fuel_cost,
            estimated_gst=fuel_db.estimated_gst,
            notes=fuel_db.notes,
            created_at=fuel_db.created_at.isoformat() if fuel_db.created_at else None,
        )
    
    # Get logbook period
    logbook_result = await db.execute(
        select(VehicleLogbookPeriodDB)
        .where(VehicleLogbookPeriodDB.module_instance_id == module_id)
        .order_by(VehicleLogbookPeriodDB.period_start.desc())
        .limit(1)
    )
    logbook_db = logbook_result.scalar_one_or_none()
    logbook_period = None
    if logbook_db:
        logbook_period = LogbookPeriod(
            id=logbook_db.id,
            module_instance_id=logbook_db.module_instance_id,
            period_start=_format_date(logbook_db.period_start),
            period_end=_format_date(logbook_db.period_end),
            total_km=logbook_db.total_km,
            business_km=logbook_db.business_km,
            private_km=logbook_db.private_km,
            business_percentage=logbook_db.business_percentage,
            is_valid=logbook_db.is_valid,
            validation_notes=logbook_db.validation_notes,
            approved_by_admin_id=logbook_db.approved_by_admin_id,
            approved_at=logbook_db.approved_at.isoformat() if logbook_db.approved_at else None,
            created_at=logbook_db.created_at.isoformat() if logbook_db.created_at else None,
        )
    
    # Get effective transactions
    effective_txns = []
    if include_transactions and job:
        builder = EffectiveTransactionBuilder(db)
        txns = await builder.build_for_module(module_id, job.id)
        effective_txns = [t.model_dump() for t in txns]
    
    # Method options
    available_methods = [
        {
            "method": MVMethod.CENTS_PER_KM.value,
            "name": "Cents per Kilometre",
            "description": f"Claim {CENTS_PER_KM_RATE*100:.0f} cents per business km (max {CENTS_PER_KM_MAX:,} km)",
            "requires": ["business_km"],
        },
        {
            "method": MVMethod.LOGBOOK.value,
            "name": "Logbook Method",
            "description": "Claim actual expenses based on logbook business percentage",
            "requires": ["logbook_period", "expenses"],
        },
        {
            "method": MVMethod.ACTUAL_EXPENSES.value,
            "name": "Actual Expenses",
            "description": "Claim actual expenses for 100% business use vehicle",
            "requires": ["expenses"],
        },
        {
            "method": MVMethod.ESTIMATED_FUEL.value,
            "name": "Estimated Fuel",
            "description": "Estimate fuel costs using ATO benchmark rates (when no receipts)",
            "requires": ["business_km", "vehicle_details"],
        },
    ]
    
    return MVModuleDetail(
        module_id=module.id,
        module_type=module.module_type,
        label=module.label,
        status=module.status,
        config=module.config or {},
        km_summary=km_summary,
        km_entries=km_entries,
        asset=asset,
        fuel_estimate=fuel_estimate,
        logbook_period=logbook_period,
        effective_transactions=effective_txns,
        output_summary=module.output_summary,
        available_methods=available_methods,
        frozen_at=module.frozen_at,
    )


@router.patch("/modules/{module_id}/config")
async def update_mv_config(
    module_id: str,
    request: MVConfigUpdate,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Update Motor Vehicle module configuration.
    
    Fields:
    - method: Calculation method (cents_per_km, logbook, actual_expenses, estimated_fuel)
    - business_km, total_km, private_km: KM values
    - logbook_pct: Logbook business percentage
    - depreciation_method: diminishing_value or prime_cost
    - override_business_pct: Admin override for business percentage
    """
    module_repo = ModuleInstanceRepository(db)
    
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot update frozen module")
    
    # Merge config
    current_config = module.config or {}
    updates = request.model_dump(exclude_none=True)
    new_config = {**current_config, **updates}
    
    # Validate method
    if "method" in updates:
        valid_methods = [m.value for m in MVMethod]
        if updates["method"] not in valid_methods:
            raise HTTPException(status_code=400, detail=f"Invalid method. Must be one of: {valid_methods}")
    
    # Update module
    module = await module_repo.update(module_id, {"config": new_config})
    
    log_action(
        action=AuditAction.WORKPAPER_MODULE_UPDATE,
        resource_type=ResourceType.WORKPAPER_MODULE,
        resource_id=module_id,
        user_id=current_user.id,
        details={"config_updates": updates}
    )
    
    return {"success": True, "module_id": module_id, "config": new_config}


# ==================== KM ENDPOINTS ====================

@router.post("/modules/{module_id}/km", response_model=KMEntry)
async def create_km_entry(
    module_id: str,
    request: KMEntryCreate,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Create a new KM entry (trip log, odometer reading, or summary)"""
    module_repo = ModuleInstanceRepository(db)
    
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot add KM entries to frozen module")
    
    # Create entry
    entry = VehicleKMEntryDB(
        module_instance_id=module_id,
        entry_type=request.entry_type,
        date_from=_parse_date(request.date_from),
        date_to=_parse_date(request.date_to),
        odometer_start=request.odometer_start,
        odometer_end=request.odometer_end,
        total_km=request.total_km,
        business_km=request.business_km,
        private_km=request.private_km,
        trip_purpose=request.trip_purpose,
        trip_from=request.trip_from,
        trip_to=request.trip_to,
        source=request.source,
        notes=request.notes,
    )
    
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    
    log_action(
        action=AuditAction.WORKPAPER_MODULE_UPDATE,
        resource_type=ResourceType.WORKPAPER_MODULE,
        resource_id=module_id,
        user_id=current_user.id,
        details={"action": "km_entry_create", "entry_type": request.entry_type, "business_km": request.business_km}
    )
    
    return KMEntry(
        id=entry.id,
        module_instance_id=entry.module_instance_id,
        entry_type=entry.entry_type,
        date_from=_format_date(entry.date_from),
        date_to=_format_date(entry.date_to),
        odometer_start=entry.odometer_start,
        odometer_end=entry.odometer_end,
        total_km=entry.total_km,
        business_km=entry.business_km,
        private_km=entry.private_km,
        trip_purpose=entry.trip_purpose,
        trip_from=entry.trip_from,
        trip_to=entry.trip_to,
        source=entry.source,
        notes=entry.notes,
        created_at=entry.created_at.isoformat() if entry.created_at else None,
    )


@router.get("/modules/{module_id}/km", response_model=List[KMEntry])
async def list_km_entries(
    module_id: str,
    entry_type: Optional[str] = None,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """List all KM entries for a module"""
    query = select(VehicleKMEntryDB).where(VehicleKMEntryDB.module_instance_id == module_id)
    if entry_type:
        query = query.where(VehicleKMEntryDB.entry_type == entry_type)
    query = query.order_by(VehicleKMEntryDB.date_from.desc())
    
    result = await db.execute(query)
    entries = result.scalars().all()
    
    return [
        KMEntry(
            id=e.id,
            module_instance_id=e.module_instance_id,
            entry_type=e.entry_type,
            date_from=_format_date(e.date_from),
            date_to=_format_date(e.date_to),
            odometer_start=e.odometer_start,
            odometer_end=e.odometer_end,
            total_km=e.total_km,
            business_km=e.business_km,
            private_km=e.private_km,
            trip_purpose=e.trip_purpose,
            trip_from=e.trip_from,
            trip_to=e.trip_to,
            source=e.source,
            notes=e.notes,
            created_at=e.created_at.isoformat() if e.created_at else None,
        )
        for e in entries
    ]


@router.delete("/modules/{module_id}/km/{entry_id}")
async def delete_km_entry(
    module_id: str,
    entry_id: str,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Delete a KM entry"""
    module_repo = ModuleInstanceRepository(db)
    
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot delete KM entries from frozen module")
    
    result = await db.execute(
        delete(VehicleKMEntryDB).where(
            VehicleKMEntryDB.id == entry_id,
            VehicleKMEntryDB.module_instance_id == module_id
        )
    )
    await db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="KM entry not found")
    
    return {"success": True, "deleted_id": entry_id}


@router.get("/modules/{module_id}/km/summary", response_model=KMSummary)
async def get_km_summary(
    module_id: str,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Get KM summary for a module"""
    return await _get_km_summary(db, module_id)


# ==================== ASSET ENDPOINTS ====================

@router.post("/modules/{module_id}/purchase", response_model=VehicleAsset)
async def create_or_update_purchase(
    module_id: str,
    request: AssetPurchaseCreate,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Create or update vehicle purchase details"""
    module_repo = ModuleInstanceRepository(db)
    
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot update frozen module")
    
    # Check for existing asset
    result = await db.execute(
        select(VehicleAssetDB).where(VehicleAssetDB.module_instance_id == module_id)
    )
    existing = result.scalar_one_or_none()
    
    # Calculate cost base
    cost_base = request.purchase_price
    if request.gst_registered_at_purchase and request.purchase_gst:
        cost_base = request.purchase_price - request.purchase_gst
    
    if existing:
        # Update existing
        existing.make = request.make
        existing.model = request.model
        existing.year = request.year
        existing.registration = request.registration
        existing.purchase_date = _parse_date(request.purchase_date)
        existing.purchase_price = request.purchase_price
        existing.purchase_gst = request.purchase_gst
        existing.gst_registered_at_purchase = request.gst_registered_at_purchase
        existing.depreciation_method = request.depreciation_method
        existing.effective_life_years = request.effective_life_years
        existing.opening_adjustable_value = request.opening_adjustable_value
        existing.cost_base = cost_base
        existing.notes = request.notes
        existing.updated_at = datetime.now(timezone.utc)
        
        await db.commit()
        await db.refresh(existing)
        asset = existing
    else:
        # Create new
        asset = VehicleAssetDB(
            module_instance_id=module_id,
            make=request.make,
            model=request.model,
            year=request.year,
            registration=request.registration,
            purchase_date=_parse_date(request.purchase_date),
            purchase_price=request.purchase_price,
            purchase_gst=request.purchase_gst,
            gst_registered_at_purchase=request.gst_registered_at_purchase,
            depreciation_method=request.depreciation_method,
            effective_life_years=request.effective_life_years,
            opening_adjustable_value=request.opening_adjustable_value,
            cost_base=cost_base,
            notes=request.notes,
        )
        db.add(asset)
        await db.commit()
        await db.refresh(asset)
    
    log_action(
        action=AuditAction.WORKPAPER_MODULE_UPDATE,
        resource_type=ResourceType.WORKPAPER_MODULE,
        resource_id=module_id,
        user_id=current_user.id,
        details={"action": "asset_purchase", "purchase_price": request.purchase_price, "cost_base": cost_base}
    )
    
    return VehicleAsset(
        id=asset.id,
        module_instance_id=asset.module_instance_id,
        make=asset.make,
        model=asset.model,
        year=asset.year,
        registration=asset.registration,
        purchase_date=_format_date(asset.purchase_date),
        purchase_price=asset.purchase_price,
        purchase_gst=asset.purchase_gst,
        gst_registered_at_purchase=asset.gst_registered_at_purchase,
        sale_date=_format_date(asset.sale_date),
        sale_price=asset.sale_price,
        sale_gst=asset.sale_gst,
        depreciation_method=asset.depreciation_method,
        effective_life_years=asset.effective_life_years,
        cost_base=asset.cost_base,
        adjustable_value_start=asset.adjustable_value_start,
        adjustable_value_end=asset.adjustable_value_end,
        depreciation_amount=asset.depreciation_amount,
        balancing_adjustment=asset.balancing_adjustment,
        notes=asset.notes,
        created_at=asset.created_at.isoformat() if asset.created_at else None,
    )


@router.post("/modules/{module_id}/sale", response_model=VehicleAsset)
async def record_vehicle_sale(
    module_id: str,
    request: AssetSaleCreate,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Record vehicle sale details (for balancing adjustment calculation)"""
    module_repo = ModuleInstanceRepository(db)
    
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot update frozen module")
    
    # Get existing asset
    result = await db.execute(
        select(VehicleAssetDB).where(VehicleAssetDB.module_instance_id == module_id)
    )
    asset = result.scalar_one_or_none()
    
    if not asset:
        raise HTTPException(status_code=400, detail="No vehicle asset found. Add purchase details first.")
    
    # Update with sale details
    asset.sale_date = _parse_date(request.sale_date)
    asset.sale_price = request.sale_price
    asset.sale_gst = request.sale_gst
    asset.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(asset)
    
    log_action(
        action=AuditAction.WORKPAPER_MODULE_UPDATE,
        resource_type=ResourceType.WORKPAPER_MODULE,
        resource_id=module_id,
        user_id=current_user.id,
        details={"action": "asset_sale", "sale_price": request.sale_price, "sale_date": request.sale_date}
    )
    
    return VehicleAsset(
        id=asset.id,
        module_instance_id=asset.module_instance_id,
        make=asset.make,
        model=asset.model,
        year=asset.year,
        registration=asset.registration,
        purchase_date=_format_date(asset.purchase_date),
        purchase_price=asset.purchase_price,
        purchase_gst=asset.purchase_gst,
        gst_registered_at_purchase=asset.gst_registered_at_purchase,
        sale_date=_format_date(asset.sale_date),
        sale_price=asset.sale_price,
        sale_gst=asset.sale_gst,
        depreciation_method=asset.depreciation_method,
        effective_life_years=asset.effective_life_years,
        cost_base=asset.cost_base,
        adjustable_value_start=asset.adjustable_value_start,
        adjustable_value_end=asset.adjustable_value_end,
        depreciation_amount=asset.depreciation_amount,
        balancing_adjustment=asset.balancing_adjustment,
        notes=asset.notes,
        created_at=asset.created_at.isoformat() if asset.created_at else None,
    )


@router.get("/modules/{module_id}/asset", response_model=Optional[VehicleAsset])
async def get_vehicle_asset(
    module_id: str,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Get vehicle asset details"""
    result = await db.execute(
        select(VehicleAssetDB).where(VehicleAssetDB.module_instance_id == module_id)
    )
    asset = result.scalar_one_or_none()
    
    if not asset:
        return None
    
    return VehicleAsset(
        id=asset.id,
        module_instance_id=asset.module_instance_id,
        make=asset.make,
        model=asset.model,
        year=asset.year,
        registration=asset.registration,
        purchase_date=_format_date(asset.purchase_date),
        purchase_price=asset.purchase_price,
        purchase_gst=asset.purchase_gst,
        gst_registered_at_purchase=asset.gst_registered_at_purchase,
        sale_date=_format_date(asset.sale_date),
        sale_price=asset.sale_price,
        sale_gst=asset.sale_gst,
        depreciation_method=asset.depreciation_method,
        effective_life_years=asset.effective_life_years,
        cost_base=asset.cost_base,
        adjustable_value_start=asset.adjustable_value_start,
        adjustable_value_end=asset.adjustable_value_end,
        depreciation_amount=asset.depreciation_amount,
        balancing_adjustment=asset.balancing_adjustment,
        notes=asset.notes,
        created_at=asset.created_at.isoformat() if asset.created_at else None,
    )


# ==================== CALCULATION ENDPOINT ====================

@router.post("/modules/{module_id}/calculate")
async def calculate_mv_module(
    module_id: str,
    year_start: str = QueryParam("2024-07-01", description="Tax year start (YYYY-MM-DD)"),
    year_end: str = QueryParam("2025-06-30", description="Tax year end (YYYY-MM-DD)"),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Calculate Motor Vehicle deduction.
    
    Returns:
    - deduction: Total deductible amount
    - gst_claimable: GST credit amount
    - business_percentage: Business use percentage
    - method: Calculation method used
    - depreciation: Depreciation details (if applicable)
    - balancing_adjustment: Balancing adjustment on sale (if applicable)
    - expense_breakdown: Breakdown by category
    - km_summary: KM totals
    - warnings: Any warnings
    - errors: Any errors
    """
    module_repo = ModuleInstanceRepository(db)
    job_repo = WorkpaperJobRepository(db)
    
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot calculate frozen module")
    
    job = await job_repo.get(module.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Get config
    config = module.config or {}
    
    # Get KM summary to supplement config
    km_summary = await _get_km_summary(db, module_id)
    if "business_km" not in config or config.get("business_km", 0) == 0:
        config["business_km"] = km_summary.business_km
    if "total_km" not in config or config.get("total_km", 0) == 0:
        config["total_km"] = km_summary.total_km
    if "private_km" not in config or config.get("private_km", 0) == 0:
        config["private_km"] = km_summary.private_km
    if "logbook_pct" not in config and km_summary.business_percentage > 0:
        config["logbook_pct"] = km_summary.business_percentage
    
    # Get asset details
    asset_result = await db.execute(
        select(VehicleAssetDB).where(VehicleAssetDB.module_instance_id == module_id)
    )
    asset = asset_result.scalar_one_or_none()
    
    if asset:
        config["purchase"] = {
            "purchase_date": _format_date(asset.purchase_date),
            "purchase_price": asset.purchase_price,
            "purchase_gst": asset.purchase_gst,
            "gst_registered": asset.gst_registered_at_purchase,
            "make": asset.make,
            "model": asset.model,
            "year": asset.year,
            "registration": asset.registration,
        }
        if asset.sale_date:
            config["sale"] = {
                "sale_date": _format_date(asset.sale_date),
                "sale_price": asset.sale_price,
                "sale_gst": asset.sale_gst,
            }
        if asset.opening_adjustable_value:
            config["opening_adjustable_value"] = asset.opening_adjustable_value
        config["depreciation_method"] = asset.depreciation_method
        config["effective_life_years"] = asset.effective_life_years
    
    # Get fuel estimate
    fuel_result = await db.execute(
        select(VehicleFuelEstimateDB).where(VehicleFuelEstimateDB.module_instance_id == module_id)
    )
    fuel = fuel_result.scalar_one_or_none()
    
    if fuel:
        config["fuel_estimate"] = {
            "fuel_type": fuel.fuel_type,
            "engine_size_litres": fuel.engine_size_litres,
            "consumption_rate": fuel.consumption_rate,
            "fuel_price_per_litre": fuel.fuel_price_per_litre,
            "business_km": fuel.business_km or config.get("business_km", 0),
        }
    
    # Get effective transactions
    builder = EffectiveTransactionBuilder(db)
    effective_txns = await builder.build_for_module(module_id, job.id)
    transactions = [t.model_dump() for t in effective_txns]
    
    # Get overrides
    override_repo = OverrideRecordRepository(db)
    overrides = await override_repo.list_by_module(module_id)
    override_dicts = [o.model_dump() for o in overrides]
    
    # Apply method override if present
    for o in overrides:
        if o.field_key == "method":
            config["method"] = o.effective_value
        elif o.field_key == "business_pct":
            config["override_business_pct"] = o.effective_value
        elif o.field_key == "logbook_pct":
            config["logbook_pct"] = o.effective_value
    
    # Set default method if not set
    if "method" not in config:
        config["method"] = MVMethod.CENTS_PER_KM.value
    
    # Run calculation
    try:
        result = calculate_motor_vehicle(
            config=config,
            transactions=transactions,
            overrides=override_dicts,
            year_start=year_start,
            year_end=year_end,
        )
    except Exception as e:
        logger.error(f"MV calculation error: {e}")
        raise HTTPException(status_code=500, detail=f"Calculation error: {str(e)}")
    
    # Store output in module
    await module_repo.update(module_id, {"output_summary": result})
    
    # Update asset with depreciation values if calculated
    if asset and result.get("depreciation"):
        dep = result["depreciation"]
        asset.adjustable_value_start = dep.get("opening_adjustable_value")
        asset.adjustable_value_end = dep.get("closing_adjustable_value")
        asset.depreciation_amount = dep.get("depreciation_amount")
        asset.balancing_adjustment = dep.get("balancing_adjustment")
        await db.commit()
    
    log_action(
        action=AuditAction.WORKPAPER_CALCULATE,
        resource_type=ResourceType.WORKPAPER_MODULE,
        resource_id=module_id,
        user_id=current_user.id,
        details={
            "method": result.get("method"),
            "deduction": result.get("deduction"),
            "gst_claimable": result.get("gst_claimable"),
            "business_percentage": result.get("business_percentage"),
        }
    )
    
    return {
        "success": True,
        "module_id": module_id,
        "result": result,
    }


# ==================== LOGBOOK PERIOD ====================

@router.post("/modules/{module_id}/logbook-period", response_model=LogbookPeriod)
async def create_logbook_period(
    module_id: str,
    request: LogbookPeriodCreate,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Create a logbook representative period"""
    module_repo = ModuleInstanceRepository(db)
    
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot add logbook period to frozen module")
    
    # Parse dates and calculate
    start = _parse_date(request.period_start)
    end = _parse_date(request.period_end)
    
    if not start or not end:
        raise HTTPException(status_code=400, detail="Invalid date format")
    
    # Calculate days
    days = (end - start).days + 1
    is_valid = days >= 84  # 12 weeks = 84 days
    
    validation_notes = None
    if not is_valid:
        validation_notes = f"Period is {days} days. ATO requires minimum 84 days (12 weeks)."
    
    # Calculate business percentage
    business_pct = (request.business_km / request.total_km * 100) if request.total_km > 0 else 0
    
    # Create period
    period = VehicleLogbookPeriodDB(
        module_instance_id=module_id,
        period_start=start,
        period_end=end,
        total_km=request.total_km,
        business_km=request.business_km,
        private_km=request.private_km,
        business_percentage=round(business_pct, 2),
        is_valid=is_valid,
        validation_notes=validation_notes or request.notes,
    )
    
    db.add(period)
    await db.commit()
    await db.refresh(period)
    
    # Update module config with logbook percentage
    config = module.config or {}
    config["logbook_pct"] = round(business_pct, 2)
    await module_repo.update(module_id, {"config": config})
    
    log_action(
        action=AuditAction.WORKPAPER_MODULE_UPDATE,
        resource_type=ResourceType.WORKPAPER_MODULE,
        resource_id=module_id,
        user_id=current_user.id,
        details={"action": "logbook_period_create", "business_pct": round(business_pct, 2), "is_valid": is_valid}
    )
    
    return LogbookPeriod(
        id=period.id,
        module_instance_id=period.module_instance_id,
        period_start=_format_date(period.period_start),
        period_end=_format_date(period.period_end),
        total_km=period.total_km,
        business_km=period.business_km,
        private_km=period.private_km,
        business_percentage=period.business_percentage,
        is_valid=period.is_valid,
        validation_notes=period.validation_notes,
        approved_by_admin_id=period.approved_by_admin_id,
        approved_at=period.approved_at.isoformat() if period.approved_at else None,
        created_at=period.created_at.isoformat() if period.created_at else None,
    )


@router.post("/modules/{module_id}/logbook-period/{period_id}/approve")
async def approve_logbook_period(
    module_id: str,
    period_id: str,
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Approve a logbook period (admin only)"""
    result = await db.execute(
        select(VehicleLogbookPeriodDB).where(
            VehicleLogbookPeriodDB.id == period_id,
            VehicleLogbookPeriodDB.module_instance_id == module_id
        )
    )
    period = result.scalar_one_or_none()
    
    if not period:
        raise HTTPException(status_code=404, detail="Logbook period not found")
    
    period.approved_by_admin_id = current_user.id
    period.approved_at = datetime.now(timezone.utc)
    
    await db.commit()
    
    return {"success": True, "period_id": period_id, "approved_at": period.approved_at.isoformat()}


# ==================== FUEL ESTIMATE ====================

@router.post("/modules/{module_id}/fuel-estimate", response_model=FuelEstimate)
async def create_fuel_estimate(
    module_id: str,
    request: FuelEstimateCreate,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Create or update fuel estimate (for estimated fuel method)"""
    module_repo = ModuleInstanceRepository(db)
    
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Cannot update frozen module")
    
    # Check for existing estimate
    result = await db.execute(
        select(VehicleFuelEstimateDB).where(VehicleFuelEstimateDB.module_instance_id == module_id)
    )
    existing = result.scalar_one_or_none()
    
    # Calculate estimates
    consumption_rate = request.consumption_rate or 9.0
    fuel_price = request.fuel_price_per_litre or 1.80
    business_km = request.business_km
    
    estimated_litres = (business_km / 100) * consumption_rate
    estimated_cost = estimated_litres * fuel_price
    estimated_gst = round(estimated_cost / 11, 2)
    
    if existing:
        existing.fuel_type = request.fuel_type
        existing.engine_size_litres = request.engine_size_litres
        existing.consumption_rate = consumption_rate
        existing.fuel_price_per_litre = fuel_price
        existing.business_km = business_km
        existing.estimated_litres = round(estimated_litres, 2)
        existing.estimated_fuel_cost = round(estimated_cost, 2)
        existing.estimated_gst = estimated_gst
        existing.notes = request.notes
        existing.updated_at = datetime.now(timezone.utc)
        
        await db.commit()
        await db.refresh(existing)
        estimate = existing
    else:
        estimate = VehicleFuelEstimateDB(
            module_instance_id=module_id,
            fuel_type=request.fuel_type,
            engine_size_litres=request.engine_size_litres,
            consumption_rate=consumption_rate,
            fuel_price_per_litre=fuel_price,
            business_km=business_km,
            estimated_litres=round(estimated_litres, 2),
            estimated_fuel_cost=round(estimated_cost, 2),
            estimated_gst=estimated_gst,
            notes=request.notes,
        )
        db.add(estimate)
        await db.commit()
        await db.refresh(estimate)
    
    return FuelEstimate(
        id=estimate.id,
        module_instance_id=estimate.module_instance_id,
        fuel_type=estimate.fuel_type,
        engine_size_litres=estimate.engine_size_litres,
        consumption_rate=estimate.consumption_rate,
        fuel_price_per_litre=estimate.fuel_price_per_litre,
        business_km=estimate.business_km,
        estimated_litres=estimate.estimated_litres,
        estimated_fuel_cost=estimate.estimated_fuel_cost,
        estimated_gst=estimate.estimated_gst,
        notes=estimate.notes,
        created_at=estimate.created_at.isoformat() if estimate.created_at else None,
    )


# ==================== FREEZE ====================

@router.post("/modules/{module_id}/freeze")
async def freeze_mv_module(
    module_id: str,
    reason: Optional[str] = None,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Freeze Motor Vehicle module with comprehensive snapshot.
    
    Snapshot includes:
    - Module config and output
    - All KM entries
    - Asset details (purchase/sale/depreciation)
    - Fuel estimate
    - Logbook period
    - All effective transactions
    - All overrides
    """
    module_repo = ModuleInstanceRepository(db)
    job_repo = WorkpaperJobRepository(db)
    override_repo = OverrideRecordRepository(db)
    snapshot_repo = FreezeSnapshotRepository(db)
    
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    if module.status == JobStatus.FROZEN.value:
        raise HTTPException(status_code=400, detail="Module already frozen")
    
    job = await job_repo.get(module.job_id)
    
    # Gather all data for snapshot
    
    # KM entries
    km_result = await db.execute(
        select(VehicleKMEntryDB).where(VehicleKMEntryDB.module_instance_id == module_id)
    )
    km_entries = [
        {
            "id": e.id,
            "entry_type": e.entry_type,
            "date_from": _format_date(e.date_from),
            "date_to": _format_date(e.date_to),
            "odometer_start": e.odometer_start,
            "odometer_end": e.odometer_end,
            "total_km": e.total_km,
            "business_km": e.business_km,
            "private_km": e.private_km,
            "trip_purpose": e.trip_purpose,
        }
        for e in km_result.scalars().all()
    ]
    
    # Asset
    asset_result = await db.execute(
        select(VehicleAssetDB).where(VehicleAssetDB.module_instance_id == module_id)
    )
    asset = asset_result.scalar_one_or_none()
    asset_data = None
    if asset:
        asset_data = {
            "make": asset.make,
            "model": asset.model,
            "year": asset.year,
            "registration": asset.registration,
            "purchase_date": _format_date(asset.purchase_date),
            "purchase_price": asset.purchase_price,
            "purchase_gst": asset.purchase_gst,
            "cost_base": asset.cost_base,
            "sale_date": _format_date(asset.sale_date),
            "sale_price": asset.sale_price,
            "depreciation_method": asset.depreciation_method,
            "adjustable_value_start": asset.adjustable_value_start,
            "adjustable_value_end": asset.adjustable_value_end,
            "depreciation_amount": asset.depreciation_amount,
            "balancing_adjustment": asset.balancing_adjustment,
        }
    
    # Fuel estimate
    fuel_result = await db.execute(
        select(VehicleFuelEstimateDB).where(VehicleFuelEstimateDB.module_instance_id == module_id)
    )
    fuel = fuel_result.scalar_one_or_none()
    fuel_data = None
    if fuel:
        fuel_data = {
            "fuel_type": fuel.fuel_type,
            "engine_size_litres": fuel.engine_size_litres,
            "consumption_rate": fuel.consumption_rate,
            "fuel_price_per_litre": fuel.fuel_price_per_litre,
            "business_km": fuel.business_km,
            "estimated_fuel_cost": fuel.estimated_fuel_cost,
            "estimated_gst": fuel.estimated_gst,
        }
    
    # Logbook period
    logbook_result = await db.execute(
        select(VehicleLogbookPeriodDB).where(VehicleLogbookPeriodDB.module_instance_id == module_id)
    )
    logbook = logbook_result.scalar_one_or_none()
    logbook_data = None
    if logbook:
        logbook_data = {
            "period_start": _format_date(logbook.period_start),
            "period_end": _format_date(logbook.period_end),
            "total_km": logbook.total_km,
            "business_km": logbook.business_km,
            "business_percentage": logbook.business_percentage,
            "is_valid": logbook.is_valid,
        }
    
    # Overrides
    overrides = await override_repo.list_by_module(module_id)
    override_data = [o.model_dump() for o in overrides]
    
    # Effective transactions
    builder = EffectiveTransactionBuilder(db)
    effective_txns = await builder.build_for_module(module_id, job.id) if job else []
    txn_data = [t.model_dump() for t in effective_txns]
    
    # KM Summary
    km_summary = await _get_km_summary(db, module_id)
    
    # Create snapshot
    from services.workpaper.models import FreezeSnapshot
    
    snapshot = FreezeSnapshot(
        job_id=module.job_id,
        module_instance_id=module_id,
        snapshot_type="module",
        data={
            "module": {
                "id": module.id,
                "module_type": module.module_type,
                "label": module.label,
                "config": module.config,
                "output_summary": module.output_summary,
            },
            "km_entries": km_entries,
            "km_summary": km_summary.model_dump(),
            "asset": asset_data,
            "fuel_estimate": fuel_data,
            "logbook_period": logbook_data,
            "overrides": override_data,
            "transactions": txn_data,
        },
        summary={
            "output": module.output_summary,
            "method": module.config.get("method") if module.config else None,
            "deduction": module.output_summary.get("deduction") if module.output_summary else None,
            "gst_claimable": module.output_summary.get("gst_claimable") if module.output_summary else None,
            "business_percentage": module.output_summary.get("business_percentage") if module.output_summary else None,
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "frozen_by": current_user.id,
            "reason": reason,
        },
        created_by_admin_id=current_user.id,
        created_by_admin_email=current_user.email,
    )
    
    snapshot = await snapshot_repo.create(snapshot)
    
    # Update module status
    await module_repo.update(module_id, {
        "status": JobStatus.FROZEN.value,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
    })
    
    log_action(
        action=AuditAction.WORKPAPER_MODULE_FREEZE,
        resource_type=ResourceType.WORKPAPER_MODULE,
        resource_id=module_id,
        user_id=current_user.id,
        details={
            "snapshot_id": snapshot.id,
            "reason": reason,
            "deduction": module.output_summary.get("deduction") if module.output_summary else None,
        }
    )
    
    return {
        "success": True,
        "module_id": module_id,
        "snapshot_id": snapshot.id,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
    }


# ==================== REFERENCE DATA ====================

@router.get("/gst-rules")
async def get_mv_gst_rules():
    """Get GST rules for Motor Vehicle expenses"""
    return get_gst_rules()


@router.get("/ato-rates")
async def get_mv_ato_rates():
    """Get current ATO rates for Motor Vehicle calculations"""
    return get_ato_rates()


@router.get("/methods")
async def list_mv_methods():
    """List available calculation methods"""
    return {
        "methods": [
            {
                "value": MVMethod.CENTS_PER_KM.value,
                "name": "Cents per Kilometre",
                "description": f"Claim {CENTS_PER_KM_RATE*100:.0f} cents per business km (max {CENTS_PER_KM_MAX:,} km)",
                "best_for": "Low business use, simple record keeping",
            },
            {
                "value": MVMethod.LOGBOOK.value,
                "name": "Logbook Method",
                "description": "Claim actual expenses based on logbook business percentage",
                "best_for": "High business use with good records",
            },
            {
                "value": MVMethod.ACTUAL_EXPENSES.value,
                "name": "Actual Expenses",
                "description": "Claim 100% of actual expenses for business-only vehicle",
                "best_for": "100% business use vehicles",
            },
            {
                "value": MVMethod.ESTIMATED_FUEL.value,
                "name": "Estimated Fuel",
                "description": "Estimate fuel costs using ATO benchmark rates",
                "best_for": "When fuel receipts not available",
            },
        ]
    }
