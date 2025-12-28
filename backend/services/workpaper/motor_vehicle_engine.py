"""
FDC Core Workpaper Platform - Motor Vehicle Calculation Engine

Complete implementation of Motor Vehicle module calculations including:
- Multiple calculation methods (Cents/km, Logbook, Actual Expenses, Estimated Fuel)
- KM tracking and validation
- Depreciation calculations (Diminishing Value, Prime Cost)
- Balancing adjustments on sale
- GST rules for each expense type
- Override support at transaction and module level
"""

from datetime import datetime, date, timezone
from typing import List, Optional, Dict, Any, Tuple
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ==================== TAX CONSTANTS (2024-25) ====================

# ATO Cents per KM rate
CENTS_PER_KM_RATE = 0.85  # 85 cents per km
CENTS_PER_KM_MAX = 5000  # Maximum 5,000 km

# GST Rate
GST_RATE = Decimal("0.10")  # 10%
GST_DIVISOR = Decimal("11")  # To extract GST from GST-inclusive amount

# Depreciation
MOTOR_VEHICLE_EFFECTIVE_LIFE = 8  # years (ATO standard)
DIMINISHING_VALUE_RATE = Decimal("0.25")  # 200% / effective life = 25%
PRIME_COST_RATE = Decimal("0.125")  # 100% / effective life = 12.5%

# Car limit for depreciation (2024-25)
CAR_DEPRECIATION_LIMIT = Decimal("68108")  # Maximum cost base for cars

# ATO Fuel consumption benchmarks (L/100km)
ATO_FUEL_BENCHMARKS = {
    "small": 7.0,       # Up to 1.6L
    "medium": 9.0,      # 1.6L - 2.5L
    "large": 11.0,      # 2.5L - 3.5L
    "very_large": 13.0, # Over 3.5L
}

# Average fuel prices (updated periodically)
DEFAULT_FUEL_PRICES = {
    "petrol": 1.80,
    "diesel": 1.90,
    "lpg": 1.00,
    "electric": 0.30,  # per kWh equivalent
}


# ==================== ENUMS ====================

class MVMethod(str, Enum):
    """Motor Vehicle calculation methods"""
    CENTS_PER_KM = "cents_per_km"
    LOGBOOK = "logbook"
    ACTUAL_EXPENSES = "actual_expenses"
    ESTIMATED_FUEL = "estimated_fuel"


class DepreciationMethod(str, Enum):
    """Depreciation calculation methods"""
    DIMINISHING_VALUE = "diminishing_value"
    PRIME_COST = "prime_cost"


class ExpenseCategory(str, Enum):
    """Motor vehicle expense categories with GST rules"""
    FUEL = "vehicle_fuel"
    REGISTRATION = "vehicle_registration"
    INSURANCE = "vehicle_insurance"
    REPAIRS = "vehicle_repairs"
    LEASE = "vehicle_lease"
    INTEREST = "vehicle_interest"
    DEPRECIATION = "vehicle_depreciation"
    OTHER = "vehicle_other"


# GST rules by category
GST_RULES = {
    ExpenseCategory.FUEL: {"gst_claimable": True, "rate": GST_RATE},
    ExpenseCategory.REGISTRATION: {"gst_claimable": True, "rate": GST_RATE, "partial": True, "note": "GST only on vehicle registration component, not stamp duty"},
    ExpenseCategory.INSURANCE: {"gst_claimable": True, "rate": GST_RATE, "partial": True, "note": "GST only on premium, not stamp duty or levies"},
    ExpenseCategory.REPAIRS: {"gst_claimable": True, "rate": GST_RATE},
    ExpenseCategory.LEASE: {"gst_claimable": True, "rate": GST_RATE},
    ExpenseCategory.INTEREST: {"gst_claimable": False, "note": "No GST on interest"},
    ExpenseCategory.DEPRECIATION: {"gst_claimable": False, "note": "No GST on depreciation"},
    ExpenseCategory.OTHER: {"gst_claimable": True, "rate": GST_RATE},
}


# ==================== PYDANTIC MODELS ====================

class KMData(BaseModel):
    """Kilometre tracking data"""
    total_km: float = 0
    business_km: float = 0
    private_km: float = 0
    logbook_percentage: Optional[float] = None  # Calculated from logbook period
    
    @property
    def calculated_business_pct(self) -> float:
        if self.total_km == 0:
            return 0
        return round((self.business_km / self.total_km) * 100, 2)


class AssetPurchase(BaseModel):
    """Vehicle purchase details"""
    purchase_date: Optional[str] = None
    purchase_price: float = 0
    purchase_gst: Optional[float] = None
    gst_registered: bool = False
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    registration: Optional[str] = None
    
    @property
    def cost_base(self) -> float:
        """Calculate cost base for depreciation"""
        if self.gst_registered and self.purchase_gst:
            return self.purchase_price - self.purchase_gst
        return self.purchase_price


class AssetSale(BaseModel):
    """Vehicle sale details"""
    sale_date: Optional[str] = None
    sale_price: float = 0
    sale_gst: Optional[float] = None


class DepreciationData(BaseModel):
    """Depreciation calculation inputs and outputs"""
    method: str = DepreciationMethod.DIMINISHING_VALUE.value
    effective_life_years: float = MOTOR_VEHICLE_EFFECTIVE_LIFE
    opening_adjustable_value: float = 0
    days_held: int = 365
    depreciation_amount: float = 0
    closing_adjustable_value: float = 0
    balancing_adjustment: Optional[float] = None
    is_profit: Optional[bool] = None  # True if balancing adjustment is income


class FuelEstimate(BaseModel):
    """Fuel estimate for estimated fuel method"""
    fuel_type: str = "petrol"
    engine_size_litres: Optional[float] = None
    consumption_rate: float = 9.0  # L/100km
    fuel_price_per_litre: float = 1.80
    business_km: float = 0
    
    @property
    def estimated_litres(self) -> float:
        return (self.business_km / 100) * self.consumption_rate
    
    @property
    def estimated_cost(self) -> float:
        return self.estimated_litres * self.fuel_price_per_litre
    
    @property
    def estimated_gst(self) -> float:
        return round(self.estimated_cost / 11, 2)


class ExpenseBreakdown(BaseModel):
    """Breakdown of expenses by category"""
    category: str
    gross_amount: float = 0
    gst_amount: float = 0
    net_amount: float = 0
    transaction_count: int = 0
    business_amount: float = 0  # After applying business %
    business_gst: float = 0


class MVCalculationResult(BaseModel):
    """Complete Motor Vehicle calculation result"""
    # Method used
    method: str
    
    # KM Summary
    km_data: KMData = Field(default_factory=KMData)
    
    # Business percentage used
    business_percentage: float = 0
    
    # Expenses
    expense_breakdown: List[ExpenseBreakdown] = Field(default_factory=list)
    total_expenses: float = 0
    
    # Depreciation
    depreciation: Optional[DepreciationData] = None
    
    # Deduction calculation
    deduction_before_business_pct: float = 0
    deduction: float = 0
    
    # GST
    gst_claimable: float = 0
    
    # Fuel estimate (if applicable)
    fuel_estimate: Optional[FuelEstimate] = None
    
    # Balancing adjustment
    balancing_adjustment: Optional[float] = None
    is_balancing_profit: bool = False
    
    # Validation
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    is_valid: bool = True
    
    # Audit trail
    calculation_date: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    inputs_snapshot: Dict[str, Any] = Field(default_factory=dict)


class MVModuleConfig(BaseModel):
    """Motor Vehicle module configuration"""
    # Method selection
    method: str = MVMethod.CENTS_PER_KM.value
    
    # KM data
    business_km: float = 0
    total_km: float = 0
    private_km: float = 0
    logbook_pct: Optional[float] = None
    
    # Asset details
    purchase: Optional[AssetPurchase] = None
    sale: Optional[AssetSale] = None
    
    # Depreciation
    depreciation_method: str = DepreciationMethod.DIMINISHING_VALUE.value
    opening_adjustable_value: Optional[float] = None
    effective_life_years: float = MOTOR_VEHICLE_EFFECTIVE_LIFE
    
    # Fuel estimate
    fuel_estimate: Optional[FuelEstimate] = None
    
    # Override flags
    use_actual_fuel: bool = True
    override_business_pct: Optional[float] = None


# ==================== CALCULATION ENGINE ====================

class MotorVehicleCalculator:
    """
    Complete Motor Vehicle calculation engine.
    
    Supports:
    - Cents per km method
    - Logbook method
    - Actual expenses method
    - Estimated fuel method
    - Depreciation (diminishing value & prime cost)
    - Balancing adjustments
    - GST calculations
    """
    
    def __init__(
        self,
        config: MVModuleConfig,
        transactions: List[Dict[str, Any]],  # Effective transactions
        overrides: Optional[List[Dict[str, Any]]] = None,
        year_start: Optional[date] = None,
        year_end: Optional[date] = None,
    ):
        self.config = config
        self.transactions = transactions
        self.overrides = overrides or []
        self.year_start = year_start or date(2024, 7, 1)
        self.year_end = year_end or date(2025, 6, 30)
        
        self.result = MVCalculationResult(method=config.method)
        
    def calculate(self) -> MVCalculationResult:
        """Run the full calculation based on selected method"""
        try:
            # Validate inputs
            self._validate_inputs()
            
            # Store input snapshot for audit
            self.result.inputs_snapshot = {
                "config": self.config.model_dump(),
                "transaction_count": len(self.transactions),
                "year_start": str(self.year_start),
                "year_end": str(self.year_end),
            }
            
            # Calculate based on method
            method = self.config.method
            
            if method == MVMethod.CENTS_PER_KM.value:
                self._calculate_cents_per_km()
            elif method == MVMethod.LOGBOOK.value:
                self._calculate_logbook()
            elif method == MVMethod.ACTUAL_EXPENSES.value:
                self._calculate_actual_expenses()
            elif method == MVMethod.ESTIMATED_FUEL.value:
                self._calculate_estimated_fuel()
            else:
                self.result.errors.append(f"Unknown method: {method}")
                self.result.is_valid = False
            
            # Calculate depreciation if applicable
            if method in [MVMethod.LOGBOOK.value, MVMethod.ACTUAL_EXPENSES.value]:
                self._calculate_depreciation()
            
            # Calculate balancing adjustment if vehicle sold
            if self.config.sale and self.config.sale.sale_date:
                self._calculate_balancing_adjustment()
            
            # Final validation
            self._final_validation()
            
        except Exception as e:
            logger.error(f"Motor Vehicle calculation error: {e}")
            self.result.errors.append(f"Calculation error: {str(e)}")
            self.result.is_valid = False
        
        return self.result
    
    def _validate_inputs(self):
        """Validate input data"""
        # Check KM data
        if self.config.method == MVMethod.CENTS_PER_KM.value:
            if self.config.business_km <= 0:
                self.result.warnings.append("Business kilometres not provided")
        
        if self.config.method == MVMethod.LOGBOOK.value:
            if not self.config.logbook_pct and self.config.logbook_pct != 0:
                if self.config.total_km > 0 and self.config.business_km > 0:
                    # Calculate from KM data
                    self.config.logbook_pct = (self.config.business_km / self.config.total_km) * 100
                else:
                    self.result.warnings.append("Logbook percentage not provided")
        
        # Validate KM totals
        if self.config.total_km > 0:
            calculated_total = self.config.business_km + self.config.private_km
            if abs(calculated_total - self.config.total_km) > 1:
                self.result.warnings.append(
                    f"KM totals don't match: business ({self.config.business_km}) + "
                    f"private ({self.config.private_km}) = {calculated_total}, "
                    f"but total is {self.config.total_km}"
                )
    
    def _calculate_cents_per_km(self):
        """Calculate using cents per kilometre method"""
        business_km = self.config.business_km
        
        # Apply cap
        capped_km = min(business_km, CENTS_PER_KM_MAX)
        if business_km > CENTS_PER_KM_MAX:
            self.result.warnings.append(
                f"Business km ({business_km:,.0f}) exceeds cap ({CENTS_PER_KM_MAX:,}). "
                f"Using {CENTS_PER_KM_MAX:,} km."
            )
        
        # Calculate deduction
        deduction = capped_km * CENTS_PER_KM_RATE
        
        # GST credit (1/11 of deduction as per ATO)
        gst_credit = round(deduction / 11, 2)
        
        # Update result
        self.result.km_data = KMData(
            total_km=self.config.total_km,
            business_km=business_km,
            private_km=self.config.private_km,
        )
        self.result.business_percentage = 100  # Not applicable for c/km
        self.result.deduction_before_business_pct = deduction
        self.result.deduction = round(deduction, 2)
        self.result.gst_claimable = gst_credit
    
    def _calculate_logbook(self):
        """Calculate using logbook method"""
        # Get business percentage
        business_pct = self.config.override_business_pct or self.config.logbook_pct or 0
        
        if business_pct <= 0:
            self.result.warnings.append("Logbook percentage is 0 or not set")
        
        # Process transactions
        self._process_transactions(business_pct)
        
        # Update KM data
        self.result.km_data = KMData(
            total_km=self.config.total_km,
            business_km=self.config.business_km,
            private_km=self.config.private_km,
            logbook_percentage=business_pct,
        )
        self.result.business_percentage = business_pct
    
    def _calculate_actual_expenses(self):
        """Calculate using actual expenses method (100% business use)"""
        # For actual expenses, use 100% business if not overridden
        business_pct = self.config.override_business_pct or 100
        
        # Process transactions
        self._process_transactions(business_pct)
        
        # Update result
        self.result.km_data = KMData(
            total_km=self.config.total_km,
            business_km=self.config.business_km,
            private_km=self.config.private_km,
        )
        self.result.business_percentage = business_pct
    
    def _calculate_estimated_fuel(self):
        """Calculate using estimated fuel method (when no receipts)"""
        # Get or create fuel estimate
        if self.config.fuel_estimate:
            fuel = self.config.fuel_estimate
        else:
            # Use defaults
            fuel = FuelEstimate(
                business_km=self.config.business_km,
                consumption_rate=self._get_ato_benchmark_rate(),
                fuel_price_per_litre=DEFAULT_FUEL_PRICES.get("petrol", 1.80),
            )
        
        # Ensure business_km is set
        if fuel.business_km <= 0:
            fuel.business_km = self.config.business_km
        
        # Calculate
        estimated_cost = fuel.estimated_cost
        estimated_gst = fuel.estimated_gst
        
        self.result.fuel_estimate = fuel
        self.result.km_data = KMData(
            total_km=self.config.total_km,
            business_km=fuel.business_km,
            private_km=self.config.private_km,
        )
        self.result.business_percentage = 100  # Estimate already accounts for business use
        self.result.deduction_before_business_pct = round(estimated_cost, 2)
        self.result.deduction = round(estimated_cost, 2)
        self.result.gst_claimable = estimated_gst
        
        # Add fuel expense to breakdown
        self.result.expense_breakdown.append(ExpenseBreakdown(
            category=ExpenseCategory.FUEL.value,
            gross_amount=estimated_cost,
            gst_amount=estimated_gst,
            net_amount=round(estimated_cost - estimated_gst, 2),
            transaction_count=0,
            business_amount=estimated_cost,
            business_gst=estimated_gst,
        ))
        self.result.total_expenses = estimated_cost
        
        self.result.warnings.append(
            "Using estimated fuel costs. Retain documentation of km records."
        )
    
    def _process_transactions(self, business_pct: float):
        """Process transactions and calculate totals"""
        # Group by category
        by_category: Dict[str, ExpenseBreakdown] = {}
        
        for txn in self.transactions:
            category = txn.get("effective_category", txn.get("category", "vehicle_other"))
            
            # Skip non-vehicle categories
            if not category.startswith("vehicle_"):
                continue
            
            if category not in by_category:
                by_category[category] = ExpenseBreakdown(category=category)
            
            breakdown = by_category[category]
            
            # Get amounts
            amount = float(txn.get("effective_amount", txn.get("amount", 0)))
            gst = float(txn.get("effective_gst_amount") or txn.get("gst_amount") or 0)
            
            # Apply transaction-level business % if present
            txn_business_pct = float(txn.get("effective_business_pct", 100))
            
            # Gross and GST
            breakdown.gross_amount += amount
            breakdown.gst_amount += gst
            breakdown.net_amount += (amount - gst)
            breakdown.transaction_count += 1
            
            # Apply business percentage
            effective_pct = (business_pct / 100) * (txn_business_pct / 100)
            breakdown.business_amount += amount * effective_pct
            
            # GST claimable (check GST rules)
            gst_rule = GST_RULES.get(
                ExpenseCategory(category) if category in [e.value for e in ExpenseCategory] else ExpenseCategory.OTHER
            )
            if gst_rule and gst_rule.get("gst_claimable", True):
                breakdown.business_gst += gst * effective_pct
        
        # Store breakdown
        self.result.expense_breakdown = list(by_category.values())
        
        # Calculate totals
        total_business_amount = sum(b.business_amount for b in self.result.expense_breakdown)
        total_business_gst = sum(b.business_gst for b in self.result.expense_breakdown)
        total_expenses = sum(b.gross_amount for b in self.result.expense_breakdown)
        
        self.result.total_expenses = round(total_expenses, 2)
        self.result.deduction_before_business_pct = round(total_expenses, 2)
        self.result.deduction = round(total_business_amount, 2)
        self.result.gst_claimable = round(total_business_gst, 2)
    
    def _calculate_depreciation(self):
        """Calculate depreciation for vehicle asset"""
        if not self.config.purchase:
            return
        
        purchase = self.config.purchase
        
        # Determine cost base
        cost_base = Decimal(str(purchase.cost_base))
        
        # Apply car limit
        if cost_base > CAR_DEPRECIATION_LIMIT:
            self.result.warnings.append(
                f"Vehicle cost ${cost_base:,.2f} exceeds car limit ${CAR_DEPRECIATION_LIMIT:,.2f}. "
                f"Depreciation limited to car limit."
            )
            cost_base = CAR_DEPRECIATION_LIMIT
        
        # Get opening value
        if self.config.opening_adjustable_value:
            opening_value = Decimal(str(self.config.opening_adjustable_value))
        else:
            # First year - use cost base
            opening_value = cost_base
        
        # Calculate days held
        purchase_date = datetime.strptime(purchase.purchase_date, "%Y-%m-%d").date() if purchase.purchase_date else self.year_start
        
        if self.config.sale and self.config.sale.sale_date:
            end_date = datetime.strptime(self.config.sale.sale_date, "%Y-%m-%d").date()
        else:
            end_date = self.year_end
        
        # Adjust for year boundaries
        start_date = max(purchase_date, self.year_start)
        end_date = min(end_date, self.year_end)
        days_held = (end_date - start_date).days + 1
        days_in_year = (self.year_end - self.year_start).days + 1
        
        # Calculate depreciation
        if self.config.depreciation_method == DepreciationMethod.DIMINISHING_VALUE.value:
            annual_depreciation = opening_value * DIMINISHING_VALUE_RATE
        else:  # Prime cost
            annual_depreciation = cost_base * PRIME_COST_RATE
        
        # Pro-rata for days held
        depreciation_amount = annual_depreciation * Decimal(days_held) / Decimal(days_in_year)
        depreciation_amount = depreciation_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        # Calculate closing value
        closing_value = max(opening_value - depreciation_amount, Decimal("0"))
        
        # Store depreciation data
        self.result.depreciation = DepreciationData(
            method=self.config.depreciation_method,
            effective_life_years=self.config.effective_life_years,
            opening_adjustable_value=float(opening_value),
            days_held=days_held,
            depreciation_amount=float(depreciation_amount),
            closing_adjustable_value=float(closing_value),
        )
        
        # Add to deduction (depreciation is part of logbook/actual expenses)
        business_pct = self.result.business_percentage / 100
        business_depreciation = float(depreciation_amount) * business_pct
        
        self.result.expense_breakdown.append(ExpenseBreakdown(
            category=ExpenseCategory.DEPRECIATION.value,
            gross_amount=float(depreciation_amount),
            gst_amount=0,  # No GST on depreciation
            net_amount=float(depreciation_amount),
            transaction_count=0,
            business_amount=business_depreciation,
            business_gst=0,
        ))
        
        self.result.deduction += round(business_depreciation, 2)
    
    def _calculate_balancing_adjustment(self):
        """Calculate balancing adjustment on vehicle sale"""
        if not self.config.sale or not self.result.depreciation:
            return
        
        sale = self.config.sale
        
        # Termination value (sale proceeds)
        sale_price = Decimal(str(sale.sale_price))
        if sale.sale_gst:
            # Remove GST if applicable
            termination_value = sale_price - Decimal(str(sale.sale_gst))
        else:
            termination_value = sale_price
        
        # Adjustable value at time of sale
        adjustable_value = Decimal(str(self.result.depreciation.closing_adjustable_value))
        
        # Calculate balancing adjustment
        if termination_value > adjustable_value:
            # Profit - assessable income
            balancing = float(termination_value - adjustable_value)
            is_profit = True
        else:
            # Loss - additional deduction
            balancing = float(adjustable_value - termination_value)
            is_profit = False
        
        # Apply business percentage
        business_pct = self.result.business_percentage / 100
        business_balancing = balancing * business_pct
        
        self.result.balancing_adjustment = round(business_balancing, 2)
        self.result.is_balancing_profit = is_profit
        
        # Update depreciation data
        self.result.depreciation.balancing_adjustment = round(business_balancing, 2)
        self.result.depreciation.is_profit = is_profit
        
        if is_profit:
            self.result.warnings.append(
                f"Balancing adjustment: ${business_balancing:,.2f} profit on sale (assessable income)"
            )
        else:
            # Add to deduction
            self.result.deduction += round(business_balancing, 2)
            self.result.warnings.append(
                f"Balancing adjustment: ${business_balancing:,.2f} loss on sale (additional deduction)"
            )
    
    def _get_ato_benchmark_rate(self) -> float:
        """Get ATO benchmark fuel consumption rate based on engine size"""
        engine_size = self.config.fuel_estimate.engine_size_litres if self.config.fuel_estimate else None
        
        if not engine_size:
            return ATO_FUEL_BENCHMARKS["medium"]
        
        if engine_size <= 1.6:
            return ATO_FUEL_BENCHMARKS["small"]
        elif engine_size <= 2.5:
            return ATO_FUEL_BENCHMARKS["medium"]
        elif engine_size <= 3.5:
            return ATO_FUEL_BENCHMARKS["large"]
        else:
            return ATO_FUEL_BENCHMARKS["very_large"]
    
    def _final_validation(self):
        """Perform final validation checks"""
        if self.result.deduction < 0:
            self.result.errors.append("Deduction cannot be negative")
            self.result.is_valid = False
        
        if self.result.gst_claimable < 0:
            self.result.errors.append("GST claimable cannot be negative")
            self.result.is_valid = False
        
        if self.result.business_percentage > 100:
            self.result.errors.append("Business percentage cannot exceed 100%")
            self.result.is_valid = False
        
        # Check for missing data warnings
        if len(self.result.expense_breakdown) == 0 and self.config.method != MVMethod.CENTS_PER_KM.value:
            if self.config.method != MVMethod.ESTIMATED_FUEL.value:
                self.result.warnings.append("No vehicle expenses found")


# ==================== HELPER FUNCTIONS ====================

def calculate_motor_vehicle(
    config: Dict[str, Any],
    transactions: List[Dict[str, Any]],
    overrides: Optional[List[Dict[str, Any]]] = None,
    year_start: Optional[str] = None,
    year_end: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main entry point for Motor Vehicle calculations.
    
    Args:
        config: Module configuration dict
        transactions: List of effective transaction dicts
        overrides: Optional list of override records
        year_start: Tax year start date (YYYY-MM-DD)
        year_end: Tax year end date (YYYY-MM-DD)
    
    Returns:
        Calculation result as dict
    """
    # Parse config
    mv_config = MVModuleConfig(**config)
    
    # Parse dates
    start = datetime.strptime(year_start, "%Y-%m-%d").date() if year_start else None
    end = datetime.strptime(year_end, "%Y-%m-%d").date() if year_end else None
    
    # Run calculation
    calculator = MotorVehicleCalculator(
        config=mv_config,
        transactions=transactions,
        overrides=overrides,
        year_start=start,
        year_end=end,
    )
    
    result = calculator.calculate()
    return result.model_dump()


def get_gst_rules() -> Dict[str, Any]:
    """Return GST rules for each expense category"""
    return {cat.value: rule for cat, rule in GST_RULES.items()}


def get_ato_rates() -> Dict[str, Any]:
    """Return current ATO rates"""
    return {
        "cents_per_km_rate": CENTS_PER_KM_RATE,
        "cents_per_km_max": CENTS_PER_KM_MAX,
        "gst_rate": float(GST_RATE),
        "car_depreciation_limit": float(CAR_DEPRECIATION_LIMIT),
        "diminishing_value_rate": float(DIMINISHING_VALUE_RATE),
        "prime_cost_rate": float(PRIME_COST_RATE),
        "motor_vehicle_effective_life": MOTOR_VEHICLE_EFFECTIVE_LIFE,
        "fuel_benchmarks": ATO_FUEL_BENCHMARKS,
        "default_fuel_prices": DEFAULT_FUEL_PRICES,
    }
