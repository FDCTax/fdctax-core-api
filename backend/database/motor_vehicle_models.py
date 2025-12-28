"""
FDC Core Workpaper Platform - Motor Vehicle Module Database Models

Stores MV-specific data:
- KM entries (odometer readings, trip logs)
- Asset purchase details
- Asset sale details
- Depreciation calculations
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, Float, Boolean, Integer, DateTime, 
    ForeignKey, Index, Date, JSON
)
from sqlalchemy.orm import relationship

from database.connection import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class VehicleAssetDB(Base):
    """
    Vehicle asset details for depreciation calculations.
    Linked to a module instance.
    """
    __tablename__ = "workpaper_vehicle_assets"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    module_instance_id = Column(String(36), ForeignKey("workpaper_modules.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Vehicle details
    make = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    year = Column(Integer, nullable=True)
    registration = Column(String(20), nullable=True)
    
    # Purchase details
    purchase_date = Column(Date, nullable=True)
    purchase_price = Column(Float, nullable=True)
    purchase_gst = Column(Float, nullable=True)  # GST included in purchase
    gst_registered_at_purchase = Column(Boolean, default=False)
    
    # For used vehicles - opening values
    opening_adjustable_value = Column(Float, nullable=True)
    opening_date = Column(Date, nullable=True)
    
    # Sale details (if sold during year)
    sale_date = Column(Date, nullable=True)
    sale_price = Column(Float, nullable=True)
    sale_gst = Column(Float, nullable=True)
    
    # Depreciation method
    depreciation_method = Column(String(50), default="diminishing_value")  # diminishing_value, prime_cost
    effective_life_years = Column(Float, default=8.0)  # ATO effective life for cars
    
    # Calculated fields (stored for audit)
    cost_base = Column(Float, nullable=True)  # Purchase price less GST (if registered)
    adjustable_value_start = Column(Float, nullable=True)  # Start of year
    adjustable_value_end = Column(Float, nullable=True)  # End of year
    depreciation_amount = Column(Float, nullable=True)
    balancing_adjustment = Column(Float, nullable=True)  # On sale
    
    # Metadata
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=utc_now)
    
    __table_args__ = (
        Index('ix_vehicle_assets_module', 'module_instance_id'),
    )


class VehicleKMEntryDB(Base):
    """
    Kilometre tracking entries.
    Can be odometer readings or trip logs.
    """
    __tablename__ = "workpaper_vehicle_km_entries"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    module_instance_id = Column(String(36), ForeignKey("workpaper_modules.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Entry type
    entry_type = Column(String(20), nullable=False)  # odometer, trip, summary
    
    # Date range for the entry
    date_from = Column(Date, nullable=True)
    date_to = Column(Date, nullable=True)
    
    # Odometer readings
    odometer_start = Column(Integer, nullable=True)
    odometer_end = Column(Integer, nullable=True)
    
    # KM values
    total_km = Column(Float, nullable=True)
    business_km = Column(Float, nullable=True)
    private_km = Column(Float, nullable=True)
    
    # Trip details (for individual trip entries)
    trip_purpose = Column(String(200), nullable=True)
    trip_from = Column(String(200), nullable=True)
    trip_to = Column(String(200), nullable=True)
    
    # Source of data
    source = Column(String(50), default="manual")  # manual, logbook_app, gps
    
    # Notes
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=utc_now)
    
    __table_args__ = (
        Index('ix_km_entries_module', 'module_instance_id'),
        Index('ix_km_entries_date', 'module_instance_id', 'date_from'),
    )


class VehicleLogbookPeriodDB(Base):
    """
    Logbook representative period.
    ATO requires a 12-week continuous period.
    """
    __tablename__ = "workpaper_vehicle_logbook_periods"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    module_instance_id = Column(String(36), ForeignKey("workpaper_modules.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Period dates
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    
    # Totals for the period
    total_km = Column(Float, nullable=False)
    business_km = Column(Float, nullable=False)
    private_km = Column(Float, nullable=False)
    
    # Calculated percentage
    business_percentage = Column(Float, nullable=False)
    
    # Status
    is_valid = Column(Boolean, default=False)  # True if meets 12-week requirement
    validation_notes = Column(Text, nullable=True)
    
    # Admin approval
    approved_by_admin_id = Column(String(36), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=utc_now)
    
    __table_args__ = (
        Index('ix_logbook_periods_module', 'module_instance_id'),
    )


class VehicleFuelEstimateDB(Base):
    """
    Fuel estimates when no receipts available.
    Uses ATO benchmark rates.
    """
    __tablename__ = "workpaper_vehicle_fuel_estimates"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    module_instance_id = Column(String(36), ForeignKey("workpaper_modules.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Vehicle fuel consumption
    fuel_type = Column(String(20), default="petrol")  # petrol, diesel, lpg, electric
    engine_size_litres = Column(Float, nullable=True)
    
    # Consumption rate (L/100km)
    consumption_rate = Column(Float, nullable=True)  # Can be user-entered or ATO benchmark
    consumption_source = Column(String(50), default="ato_benchmark")  # ato_benchmark, manufacturer, actual
    
    # Fuel price (average for period)
    fuel_price_per_litre = Column(Float, nullable=True)
    
    # Calculated estimates
    business_km = Column(Float, nullable=True)
    estimated_litres = Column(Float, nullable=True)
    estimated_fuel_cost = Column(Float, nullable=True)
    estimated_gst = Column(Float, nullable=True)
    
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=utc_now)
    
    __table_args__ = (
        Index('ix_fuel_estimates_module', 'module_instance_id'),
    )
