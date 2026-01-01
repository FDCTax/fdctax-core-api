"""
Unit Tests for Tax Modules

Tests POB, Occupancy, Depreciation, and Motor Vehicle calculations.

Run with: pytest tests/test_tax_modules.py -v
"""

import pytest
from decimal import Decimal

from services.tax_modules import (
    # POB
    calculate_pob,
    POBCalculationInput,
    POB_FIXED_RATE_PER_HOUR,
    
    # Occupancy
    calculate_occupancy,
    OccupancyCalculationInput,
    
    # Depreciation
    calculate_depreciation,
    AssetDepreciationInput,
    EFFECTIVE_LIVES,
    
    # Motor Vehicle
    calculate_motor_vehicle_deduction,
    MotorVehicleCalculationInput,
    CENTS_PER_KM_RATE,
    CENTS_PER_KM_MAX_KM,
    
    # Status
    get_tax_modules_status
)


class TestPOBCalculations:
    """Test Place of Business (Home Office) calculations."""
    
    def test_fixed_rate_calculation(self):
        """Test fixed rate method (67c/hour)."""
        input_data = POBCalculationInput(
            method="fixed_rate",
            hours_worked=1000
        )
        
        result = calculate_pob(input_data)
        
        # 1000 hours × $0.67 = $670
        assert result.deduction_amount == Decimal("670.00")
        assert result.method == "fixed_rate"
        assert result.gst_claimable == Decimal("0")
        assert len(result.compliance_warnings) == 0
    
    def test_fixed_rate_high_hours_warning(self):
        """Test warning for high hours claimed."""
        input_data = POBCalculationInput(
            method="fixed_rate",
            hours_worked=2500  # Over 2000 hours
        )
        
        result = calculate_pob(input_data)
        
        # Should have warning about high hours
        assert len(result.compliance_warnings) > 0
        assert "High hours" in result.compliance_warnings[0]
    
    def test_actual_cost_method(self):
        """Test actual cost method with expenses."""
        input_data = POBCalculationInput(
            method="actual_cost",
            floor_area_office=10,
            floor_area_total=100,  # 10% business use
            expenses={
                "electricity": 2000,
                "internet": 1200
            },
            dedicated_office=True
        )
        
        result = calculate_pob(input_data)
        
        # 10% of ($2000 + $1200) = $320
        assert result.deduction_amount == Decimal("320.00")
        assert result.gst_claimable > 0  # Should have GST component
    
    def test_actual_cost_non_dedicated_office(self):
        """Test actual cost with non-dedicated office (reduced claim)."""
        input_data = POBCalculationInput(
            method="actual_cost",
            floor_area_office=10,
            floor_area_total=100,
            expenses={"electricity": 3000},
            dedicated_office=False  # Not exclusive use
        )
        
        result = calculate_pob(input_data)
        
        # Non-dedicated reduces claim further
        # 10% × 33% (hours adjustment) × $3000 ≈ $99
        assert result.deduction_amount < Decimal("300")
        assert "adjusted" in " ".join(result.notes).lower()
    
    def test_shortcut_method_warning(self):
        """Test shortcut method shows ended warning."""
        input_data = POBCalculationInput(
            method="shortcut",
            hours_worked=500
        )
        
        result = calculate_pob(input_data)
        
        # Should warn about method ending
        assert len(result.compliance_warnings) > 0
        assert "ended" in result.compliance_warnings[0].lower()


class TestOccupancyCalculations:
    """Test Occupancy expense calculations."""
    
    def test_basic_occupancy_calculation(self):
        """Test basic occupancy calculation."""
        input_data = OccupancyCalculationInput(
            expenses={
                "mortgage_interest": 20000,
                "council_rates": 2000
            },
            floor_area_business=15,
            floor_area_total=150  # 10% business use
        )
        
        result = calculate_occupancy(input_data)
        
        # 10% of $22,000 = $2,200
        assert result.total_deduction == Decimal("2200.00")
        assert result.business_use_percentage == 10.0
    
    def test_occupancy_cgt_warning(self):
        """Test CGT warning for owner-occupiers."""
        input_data = OccupancyCalculationInput(
            expenses={"mortgage_interest": 10000},
            floor_area_business=10,
            floor_area_total=100,
            is_owner=True,
            principal_residence=True
        )
        
        result = calculate_occupancy(input_data)
        
        # Should have CGT warning
        assert result.cgt_warning is not None
        assert "CGT" in result.cgt_warning
        assert len(result.compliance_warnings) > 0
    
    def test_occupancy_tenant_no_cgt_warning(self):
        """Test no CGT warning for tenants."""
        input_data = OccupancyCalculationInput(
            expenses={"rent": 24000},
            floor_area_business=10,
            floor_area_total=100,
            is_owner=False
        )
        
        result = calculate_occupancy(input_data)
        
        assert result.cgt_warning is None
    
    def test_occupancy_gst_rules(self):
        """Test GST rules are applied correctly."""
        input_data = OccupancyCalculationInput(
            expenses={
                "mortgage_interest": 10000,  # No GST
                "house_insurance": 1100  # Has GST
            },
            business_use_percentage=10
        )
        
        result = calculate_occupancy(input_data)
        
        # Only insurance has GST
        assert result.gst_claimable > 0
        assert result.expense_breakdown["mortgage_interest"]["gst_claimable"] == 0
        assert result.expense_breakdown["house_insurance"]["gst_claimable"] > 0


class TestDepreciationCalculations:
    """Test Depreciation calculations."""
    
    def test_diminishing_value_first_year(self):
        """Test diminishing value method - first year."""
        input_data = AssetDepreciationInput(
            asset_name="Test Laptop",
            asset_type="laptop",
            purchase_date="2024-07-01",
            purchase_price=2000,
            method="diminishing_value",
            days_held_in_year=365
        )
        
        result = calculate_depreciation(input_data)
        
        # Effective life = 4 years, rate = 50%
        # $2000 × 50% = $1000
        assert result.depreciation_amount == Decimal("1000.00")
        assert result.effective_life_years == 4
        assert result.rate == 50.0
        assert result.closing_written_down_value == Decimal("1000.00")
    
    def test_diminishing_value_pro_rata(self):
        """Test pro-rata calculation for partial year."""
        input_data = AssetDepreciationInput(
            asset_name="Test Laptop",
            asset_type="laptop",
            purchase_date="2025-01-01",
            purchase_price=2000,
            method="diminishing_value",
            days_held_in_year=182  # ~6 months
        )
        
        result = calculate_depreciation(input_data)
        
        # $2000 × 50% × (182/365) ≈ $498.63
        assert result.depreciation_amount < Decimal("1000")
        assert "pro-rata" in " ".join(result.notes).lower()
    
    def test_prime_cost_method(self):
        """Test prime cost method."""
        input_data = AssetDepreciationInput(
            asset_name="Test Furniture",
            asset_type="furniture_office",
            purchase_date="2024-07-01",
            purchase_price=5000,
            method="prime_cost",
            days_held_in_year=365
        )
        
        result = calculate_depreciation(input_data)
        
        # Effective life = 10 years, rate = 10%
        # $5000 × 10% = $500
        assert result.depreciation_amount == Decimal("500.00")
        assert result.rate == 10.0
    
    def test_instant_write_off_under_threshold(self):
        """Test instant write-off for small assets."""
        input_data = AssetDepreciationInput(
            asset_name="Small Tool",
            asset_type="tools_hand",
            purchase_date="2024-07-01",
            purchase_price=500,  # Under $1000 threshold
            method="instant_write_off",
            is_small_business=False
        )
        
        result = calculate_depreciation(input_data)
        
        # Full write-off
        assert result.depreciation_amount == Decimal("500.00")
        assert result.closing_written_down_value == Decimal("0")
    
    def test_instant_write_off_small_business(self):
        """Test instant write-off for small business (higher threshold)."""
        input_data = AssetDepreciationInput(
            asset_name="Equipment",
            asset_type="computer",
            purchase_date="2024-07-01",
            purchase_price=15000,  # Under $20,000 SB threshold
            method="instant_write_off",
            is_small_business=True
        )
        
        result = calculate_depreciation(input_data)
        
        # Full write-off for small business
        assert result.depreciation_amount == Decimal("15000.00")
    
    def test_depreciation_business_use_percentage(self):
        """Test business use percentage is applied."""
        input_data = AssetDepreciationInput(
            asset_name="Test Asset",
            asset_type="computer",
            purchase_date="2024-07-01",
            purchase_price=2000,
            method="diminishing_value",
            business_use_percentage=60,
            days_held_in_year=365
        )
        
        result = calculate_depreciation(input_data)
        
        # Full depreciation = $1000, business portion = 60%
        assert result.depreciation_amount == Decimal("1000.00")
        assert result.business_portion == Decimal("600.00")
    
    def test_effective_life_lookup(self):
        """Test effective life is looked up correctly."""
        for asset_type, expected_life in EFFECTIVE_LIVES.items():
            input_data = AssetDepreciationInput(
                asset_name=f"Test {asset_type}",
                asset_type=asset_type,
                purchase_date="2024-07-01",
                purchase_price=1000,
                method="diminishing_value"
            )
            
            result = calculate_depreciation(input_data)
            
            assert result.effective_life_years == expected_life


class TestMotorVehicleCalculations:
    """Test Motor Vehicle calculations."""
    
    def test_cents_per_km_basic(self):
        """Test cents per km method - basic calculation."""
        input_data = MotorVehicleCalculationInput(
            method="cents_per_km",
            business_km=3000
        )
        
        result = calculate_motor_vehicle_deduction(input_data)
        
        # 3000 km × $0.85 = $2,550
        assert result.deduction_amount == Decimal("2550.00")
        assert result.method == "cents_per_km"
        assert result.gst_claimable == Decimal("0")
    
    def test_cents_per_km_maximum(self):
        """Test cents per km caps at 5000km."""
        input_data = MotorVehicleCalculationInput(
            method="cents_per_km",
            business_km=7000  # Over 5000 max
        )
        
        result = calculate_motor_vehicle_deduction(input_data)
        
        # Capped at 5000 km × $0.85 = $4,250
        assert result.deduction_amount == Decimal("4250.00")
        assert result.breakdown["business_km_claimed"] == 5000
        assert result.breakdown["business_km_actual"] == 7000
        assert len(result.compliance_warnings) > 0  # Should warn about cap
    
    def test_logbook_method(self):
        """Test logbook method calculation."""
        input_data = MotorVehicleCalculationInput(
            method="logbook",
            logbook_business_percentage=60,
            total_expenses={
                "fuel": 3000,
                "registration": 800,
                "insurance": 1200
            }
        )
        
        result = calculate_motor_vehicle_deduction(input_data)
        
        # 60% of $5000 = $3000
        assert result.deduction_amount == Decimal("3000.00")
        assert result.gst_claimable > 0  # Should have GST component
    
    def test_logbook_zero_percentage_warning(self):
        """Test warning for zero logbook percentage."""
        input_data = MotorVehicleCalculationInput(
            method="logbook",
            logbook_business_percentage=0,
            total_expenses={"fuel": 1000}
        )
        
        result = calculate_motor_vehicle_deduction(input_data)
        
        assert result.deduction_amount == Decimal("0")
        assert len(result.compliance_warnings) > 0


class TestTaxModulesStatus:
    """Test tax modules status endpoint."""
    
    def test_status_returns_all_modules(self):
        """Test status returns info for all modules."""
        status = get_tax_modules_status()
        
        assert "modules" in status
        assert "pob" in status["modules"]
        assert "occupancy" in status["modules"]
        assert "depreciation" in status["modules"]
        assert "motor_vehicle" in status["modules"]
    
    def test_status_has_tax_year(self):
        """Test status includes tax year."""
        status = get_tax_modules_status()
        
        assert "tax_year" in status
        assert status["tax_year"] == "2024-25"
    
    def test_status_has_current_rates(self):
        """Test status includes current rates."""
        status = get_tax_modules_status()
        
        mv_status = status["modules"]["motor_vehicle"]
        assert mv_status["cents_per_km_rate"] == float(CENTS_PER_KM_RATE)
        assert mv_status["cents_per_km_max"] == CENTS_PER_KM_MAX_KM


class TestDeterministicResults:
    """Test that all calculations return deterministic results."""
    
    def test_pob_deterministic(self):
        """Test POB returns same result for same input."""
        input_data = POBCalculationInput(
            method="fixed_rate",
            hours_worked=1000
        )
        
        result1 = calculate_pob(input_data)
        result2 = calculate_pob(input_data)
        
        assert result1.deduction_amount == result2.deduction_amount
        assert result1.to_dict() == result2.to_dict()
    
    def test_depreciation_deterministic(self):
        """Test depreciation returns same result for same input."""
        input_data = AssetDepreciationInput(
            asset_name="Test",
            asset_type="laptop",
            purchase_date="2024-07-01",
            purchase_price=2000,
            method="diminishing_value"
        )
        
        result1 = calculate_depreciation(input_data)
        result2 = calculate_depreciation(input_data)
        
        assert result1.depreciation_amount == result2.depreciation_amount
        assert result1.to_dict() == result2.to_dict()
    
    def test_motor_vehicle_deterministic(self):
        """Test motor vehicle returns same result for same input."""
        input_data = MotorVehicleCalculationInput(
            method="cents_per_km",
            business_km=3500
        )
        
        result1 = calculate_motor_vehicle_deduction(input_data)
        result2 = calculate_motor_vehicle_deduction(input_data)
        
        assert result1.deduction_amount == result2.deduction_amount
        assert result1.to_dict() == result2.to_dict()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
