"""
FDC Core Workpaper Platform - Calculation Engine

Two-layer calculation model:
- Layer 1: Transaction layer - clean & correct transactions, compute EffectiveTransactions
- Layer 2: Workpaper layer - apply module-specific logic, produce outputs

All calculations use EffectiveTransaction data.
"""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
import logging

from services.workpaper.models import (
    WorkpaperJob, ModuleInstance, Transaction, EffectiveTransaction,
    OverrideRecord, ModuleType, CalculationMethod, JobStatus,
    TransactionCategory, MODULE_METHOD_CONFIGS
)
from services.workpaper.storage import (
    job_storage, module_storage, transaction_storage,
    module_override_storage, effective_builder
)

logger = logging.getLogger(__name__)


# ==================== TAX CONSTANTS ====================

# ATO rates for 2024-25
CENTS_PER_KM_RATE = 0.85  # 85 cents per km
CENTS_PER_KM_MAX_KM = 5000  # Maximum 5,000 km

HOME_OFFICE_FIXED_RATE = 0.67  # 67 cents per hour

# GST rate
GST_RATE = 0.10  # 10%

# Depreciation rates (simplified)
DEPRECIATION_RATES = {
    "motor_vehicle": 0.25,  # 25% diminishing value
    "computer": 0.50,       # 50% diminishing value
    "furniture": 0.20,      # 20% diminishing value
    "equipment": 0.30,      # 30% diminishing value
}


# ==================== BASE ENGINE ====================

class BaseCalculationEngine:
    """Base class for module calculation engines"""
    
    def __init__(self, module: ModuleInstance, job: WorkpaperJob):
        self.module = module
        self.job = job
        self.config = module.config or {}
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    def get_method(self) -> str:
        """Get the calculation method for this module"""
        method_config = MODULE_METHOD_CONFIGS.get(self.module.module_type)
        if not method_config:
            return "default"
        
        # Check for admin override
        override = module_override_storage.get_by_field(self.module.id, "method")
        if override:
            return override.effective_value
        
        # Check config
        if "method" in self.config:
            return self.config["method"]
        
        # Use default
        return method_config.default_method
    
    def get_effective_value(self, field_key: str, default: Any = None) -> Any:
        """Get effective value for a field (checking for override)"""
        override = module_override_storage.get_by_field(self.module.id, field_key)
        if override:
            return override.effective_value
        
        # Check config
        if field_key in self.config:
            return self.config[field_key]
        
        return default
    
    def get_transactions(self, categories: Optional[List[str]] = None) -> List[EffectiveTransaction]:
        """Get effective transactions for this module"""
        if self.module.module_instance_id:
            return effective_builder.build_for_module(self.module.id, self.job.id)
        
        if categories:
            return effective_builder.build_for_categories(self.job.id, categories)
        
        return effective_builder.build_for_job(self.job.id)
    
    def calculate(self) -> Dict[str, Any]:
        """Override in subclass - perform calculation"""
        raise NotImplementedError
    
    def validate(self) -> Tuple[bool, List[str]]:
        """Validate inputs for calculation"""
        return True, []


# ==================== MOTOR VEHICLE ENGINE ====================

class MotorVehicleEngine(BaseCalculationEngine):
    """Calculation engine for Motor Vehicle module"""
    
    VEHICLE_CATEGORIES = [
        TransactionCategory.VEHICLE_FUEL.value,
        TransactionCategory.VEHICLE_REGISTRATION.value,
        TransactionCategory.VEHICLE_INSURANCE.value,
        TransactionCategory.VEHICLE_REPAIRS.value,
        TransactionCategory.VEHICLE_LEASE.value,
        TransactionCategory.VEHICLE_INTEREST.value,
        TransactionCategory.VEHICLE_OTHER.value,
    ]
    
    def calculate(self) -> Dict[str, Any]:
        """Calculate motor vehicle deduction"""
        method = self.get_method()
        
        if method == CalculationMethod.CENTS_PER_KM.value:
            return self._calculate_cents_per_km()
        elif method == CalculationMethod.LOGBOOK.value:
            return self._calculate_logbook()
        else:
            self.errors.append(f"Unknown method: {method}")
            return {"error": "Unknown calculation method"}
    
    def _calculate_cents_per_km(self) -> Dict[str, Any]:
        """Cents per kilometre method"""
        business_km = self.get_effective_value("business_km", 0)
        
        # Cap at maximum
        capped_km = min(business_km, CENTS_PER_KM_MAX_KM)
        if business_km > CENTS_PER_KM_MAX_KM:
            self.warnings.append(f"Business km ({business_km}) capped at {CENTS_PER_KM_MAX_KM}")
        
        deduction = capped_km * CENTS_PER_KM_RATE
        
        # GST credit for c/km method (simplified - based on fuel portion estimate)
        # ATO allows 1/11 of deduction as GST credit
        gst_credit = deduction / 11
        
        return {
            "method": CalculationMethod.CENTS_PER_KM.value,
            "business_km": business_km,
            "capped_km": capped_km,
            "rate_per_km": CENTS_PER_KM_RATE,
            "deduction": round(deduction, 2),
            "gst_credit": round(gst_credit, 2),
            "warnings": self.warnings,
            "errors": self.errors,
        }
    
    def _calculate_logbook(self) -> Dict[str, Any]:
        """Logbook method"""
        logbook_pct = self.get_effective_value("logbook_pct", 0)
        
        # Get vehicle expenses
        transactions = self.get_transactions(self.VEHICLE_CATEGORIES)
        
        # Sum expenses
        total_expenses = sum(t.effective_amount for t in transactions)
        total_gst = sum(t.effective_gst_amount or 0 for t in transactions)
        
        # Apply logbook percentage
        deduction = total_expenses * (logbook_pct / 100)
        gst_credit = total_gst * (logbook_pct / 100)
        
        # Breakdown by category
        by_category = {}
        for t in transactions:
            cat = t.effective_category
            if cat not in by_category:
                by_category[cat] = {"amount": 0, "gst": 0, "count": 0}
            by_category[cat]["amount"] += t.effective_amount
            by_category[cat]["gst"] += t.effective_gst_amount or 0
            by_category[cat]["count"] += 1
        
        return {
            "method": CalculationMethod.LOGBOOK.value,
            "logbook_pct": logbook_pct,
            "total_expenses": round(total_expenses, 2),
            "total_gst": round(total_gst, 2),
            "deduction": round(deduction, 2),
            "gst_credit": round(gst_credit, 2),
            "transaction_count": len(transactions),
            "by_category": by_category,
            "warnings": self.warnings,
            "errors": self.errors,
        }


# ==================== HOME OFFICE ENGINE ====================

class HomeOfficeEngine(BaseCalculationEngine):
    """Calculation engine for Home Office module"""
    
    HOME_CATEGORIES = [
        TransactionCategory.HOME_ELECTRICITY.value,
        TransactionCategory.HOME_GAS.value,
        TransactionCategory.HOME_CLEANING.value,
        TransactionCategory.HOME_REPAIRS.value,
        TransactionCategory.HOME_OTHER.value,
    ]
    
    def calculate(self) -> Dict[str, Any]:
        """Calculate home office deduction"""
        method = self.get_method()
        
        if method == CalculationMethod.FIXED_RATE.value:
            return self._calculate_fixed_rate()
        elif method == CalculationMethod.ACTUAL.value:
            return self._calculate_actual()
        else:
            return self._calculate_fixed_rate()  # Default
    
    def _calculate_fixed_rate(self) -> Dict[str, Any]:
        """Fixed rate method (67c per hour)"""
        hours_worked = self.get_effective_value("hours_worked", 0)
        
        deduction = hours_worked * HOME_OFFICE_FIXED_RATE
        
        return {
            "method": CalculationMethod.FIXED_RATE.value,
            "hours_worked": hours_worked,
            "rate_per_hour": HOME_OFFICE_FIXED_RATE,
            "deduction": round(deduction, 2),
            "gst_credit": 0,  # No GST credit for fixed rate
            "warnings": self.warnings,
            "errors": self.errors,
        }
    
    def _calculate_actual(self) -> Dict[str, Any]:
        """Actual expenses method"""
        floor_area_pct = self.get_effective_value("floor_area_pct", 0)
        business_use_pct = self.get_effective_value("business_use_pct", 100)
        
        # Get home office expenses
        transactions = self.get_transactions(self.HOME_CATEGORIES)
        
        total_expenses = sum(t.effective_amount for t in transactions)
        total_gst = sum(t.effective_gst_amount or 0 for t in transactions)
        
        # Apply percentages
        effective_pct = (floor_area_pct / 100) * (business_use_pct / 100)
        deduction = total_expenses * effective_pct
        gst_credit = total_gst * effective_pct
        
        return {
            "method": CalculationMethod.ACTUAL.value,
            "floor_area_pct": floor_area_pct,
            "business_use_pct": business_use_pct,
            "effective_pct": round(effective_pct * 100, 2),
            "total_expenses": round(total_expenses, 2),
            "deduction": round(deduction, 2),
            "gst_credit": round(gst_credit, 2),
            "transaction_count": len(transactions),
            "warnings": self.warnings,
            "errors": self.errors,
        }


# ==================== INTERNET/MOBILE ENGINE ====================

class CommunicationsEngine(BaseCalculationEngine):
    """Calculation engine for Internet/Mobile modules"""
    
    def calculate(self) -> Dict[str, Any]:
        """Calculate communications deduction"""
        # Determine category based on module type
        if self.module.module_type == ModuleType.INTERNET.value:
            category = TransactionCategory.INTERNET.value
        elif self.module.module_type == ModuleType.MOBILE.value:
            category = TransactionCategory.MOBILE.value
        else:
            category = TransactionCategory.INTERNET.value
        
        business_pct = self.get_effective_value("business_pct", 50)
        
        # Get transactions
        transactions = self.get_transactions([category])
        
        total_expenses = sum(t.effective_amount for t in transactions)
        total_gst = sum(t.effective_gst_amount or 0 for t in transactions)
        
        # Apply business percentage
        deduction = total_expenses * (business_pct / 100)
        gst_credit = total_gst * (business_pct / 100)
        
        return {
            "method": self.get_method(),
            "category": category,
            "business_pct": business_pct,
            "total_expenses": round(total_expenses, 2),
            "deduction": round(deduction, 2),
            "gst_credit": round(gst_credit, 2),
            "transaction_count": len(transactions),
            "warnings": self.warnings,
            "errors": self.errors,
        }


# ==================== FDC INCOME ENGINE ====================

class FDCIncomeEngine(BaseCalculationEngine):
    """Calculation engine for FDC Income module"""
    
    def calculate(self) -> Dict[str, Any]:
        """Calculate FDC income summary"""
        # Get FDC income transactions
        transactions = self.get_transactions([TransactionCategory.FDC_INCOME.value])
        
        total_income = sum(t.effective_amount for t in transactions)
        total_gst = sum(t.effective_gst_amount or 0 for t in transactions)
        
        # Check GST registration
        gst_registered = self.get_effective_value("gst_registered", False)
        
        # Calculate net income
        if gst_registered:
            net_income = total_income - total_gst
        else:
            net_income = total_income
        
        return {
            "total_income": round(total_income, 2),
            "total_gst_collected": round(total_gst, 2),
            "net_income": round(net_income, 2),
            "gst_registered": gst_registered,
            "transaction_count": len(transactions),
            "warnings": self.warnings,
            "errors": self.errors,
        }


# ==================== FOOD GST ENGINE ====================

class FoodGSTEngine(BaseCalculationEngine):
    """Calculation engine for Food/GST module"""
    
    def calculate(self) -> Dict[str, Any]:
        """Calculate food expenses and GST"""
        transactions = self.get_transactions([TransactionCategory.FDC_FOOD.value])
        
        total_food = sum(t.effective_amount for t in transactions)
        total_gst = sum(t.effective_gst_amount or 0 for t in transactions)
        
        # FDC percentage for food
        fdc_pct = self.get_effective_value("fdc_pct", 0)
        
        deduction = total_food * (fdc_pct / 100)
        gst_credit = total_gst * (fdc_pct / 100)
        
        return {
            "total_food_expenses": round(total_food, 2),
            "fdc_pct": fdc_pct,
            "deduction": round(deduction, 2),
            "gst_credit": round(gst_credit, 2),
            "transaction_count": len(transactions),
            "warnings": self.warnings,
            "errors": self.errors,
        }


# ==================== SUMMARY ENGINE ====================

class SummaryEngine(BaseCalculationEngine):
    """Calculation engine for Summary module - aggregates all modules"""
    
    def calculate(self) -> Dict[str, Any]:
        """Calculate overall summary"""
        modules = module_storage.list_by_job(self.job.id)
        
        total_deductions = 0
        total_gst_credits = 0
        total_income = 0
        module_summaries = {}
        
        for module in modules:
            if module.module_type == ModuleType.SUMMARY.value:
                continue
            
            if module.output_summary:
                summary = module.output_summary
                
                # Accumulate deductions
                if "deduction" in summary:
                    total_deductions += summary["deduction"]
                
                # Accumulate GST credits
                if "gst_credit" in summary:
                    total_gst_credits += summary["gst_credit"]
                
                # Track income
                if "net_income" in summary:
                    total_income += summary["net_income"]
                
                module_summaries[module.module_type] = {
                    "label": module.label,
                    "deduction": summary.get("deduction", 0),
                    "gst_credit": summary.get("gst_credit", 0),
                    "income": summary.get("net_income", 0),
                    "status": module.status,
                }
        
        # Calculate net position
        net_taxable = total_income - total_deductions
        
        return {
            "total_income": round(total_income, 2),
            "total_deductions": round(total_deductions, 2),
            "net_taxable": round(net_taxable, 2),
            "total_gst_credits": round(total_gst_credits, 2),
            "module_count": len(modules) - 1,  # Exclude summary
            "by_module": module_summaries,
            "warnings": self.warnings,
            "errors": self.errors,
        }


# ==================== ENGINE FACTORY ====================

def get_calculation_engine(module: ModuleInstance, job: WorkpaperJob) -> BaseCalculationEngine:
    """Factory function to get the appropriate calculation engine"""
    engines = {
        ModuleType.MOTOR_VEHICLE.value: MotorVehicleEngine,
        ModuleType.HOME_OFFICE.value: HomeOfficeEngine,
        ModuleType.INTERNET.value: CommunicationsEngine,
        ModuleType.MOBILE.value: CommunicationsEngine,
        ModuleType.FDC_INCOME.value: FDCIncomeEngine,
        ModuleType.FOOD_GST.value: FoodGSTEngine,
        ModuleType.SUMMARY.value: SummaryEngine,
    }
    
    engine_class = engines.get(module.module_type, BaseCalculationEngine)
    return engine_class(module, job)


def calculate_module(module_id: str) -> Dict[str, Any]:
    """Calculate outputs for a module and store in output_summary"""
    module = module_storage.get(module_id)
    if not module:
        raise ValueError(f"Module not found: {module_id}")
    
    job = job_storage.get(module.job_id)
    if not job:
        raise ValueError(f"Job not found: {module.job_id}")
    
    # Check if frozen
    if module.status == JobStatus.FROZEN.value:
        raise ValueError("Cannot calculate frozen module")
    
    # Get engine and calculate
    engine = get_calculation_engine(module, job)
    output = engine.calculate()
    
    # Store output
    module_storage.update(module_id, {"output_summary": output})
    
    logger.info(f"Calculated module {module_id}: {output.get('deduction', output.get('net_income', 'N/A'))}")
    
    return output


def calculate_all_modules(job_id: str) -> Dict[str, Any]:
    """Calculate all modules for a job"""
    modules = module_storage.list_by_job(job_id)
    job = job_storage.get(job_id)
    
    if not job:
        raise ValueError(f"Job not found: {job_id}")
    
    results = {}
    
    # Calculate non-summary modules first
    for module in modules:
        if module.module_type != ModuleType.SUMMARY.value:
            try:
                results[module.id] = calculate_module(module.id)
            except Exception as e:
                logger.error(f"Error calculating module {module.id}: {e}")
                results[module.id] = {"error": str(e)}
    
    # Calculate summary last
    summary_module = next((m for m in modules if m.module_type == ModuleType.SUMMARY.value), None)
    if summary_module:
        try:
            results[summary_module.id] = calculate_module(summary_module.id)
        except Exception as e:
            logger.error(f"Error calculating summary: {e}")
            results[summary_module.id] = {"error": str(e)}
    
    return results
