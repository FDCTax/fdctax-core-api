"""
FDC Core Workpaper Platform - Domain Models

Core entities for the workpaper system:
- WorkpaperJob: Tax job for a client for a given year
- ModuleInstance: A specific workpaper module under a job
- Transaction: Source financial data
- TransactionOverride: Admin adjustments per transaction
- OverrideRecord: Module-level overrides
- Query + QueryMessage: Structured communication
- Task: Client-facing task bundling
- FreezeSnapshot: Frozen state audit records

Storage: File-based JSON (can migrate to PostgreSQL when permissions available)
"""

import uuid
from datetime import datetime, date, timezone
from typing import List, Optional, Dict, Any, Union
from enum import Enum
from pydantic import BaseModel, Field


# ==================== ENUMS ====================

class JobStatus(str, Enum):
    """Status for WorkpaperJob and ModuleInstance"""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    AWAITING_CLIENT = "awaiting_client"
    READY_FOR_REVIEW = "ready_for_review"
    READY_FOR_FINAL_REVIEW = "ready_for_final_review"
    COMPLETED = "completed"
    FROZEN = "frozen"
    NA = "na"  # For non-applicable modules


# Status priority for deriving job status (lowest = worst)
STATUS_PRIORITY = {
    JobStatus.NOT_STARTED: 1,
    JobStatus.IN_PROGRESS: 2,
    JobStatus.AWAITING_CLIENT: 3,
    JobStatus.READY_FOR_REVIEW: 4,
    JobStatus.READY_FOR_FINAL_REVIEW: 5,
    JobStatus.COMPLETED: 6,
    JobStatus.FROZEN: 7,
    JobStatus.NA: 100,  # NA doesn't affect job status
}


class ModuleType(str, Enum):
    """Available workpaper module types"""
    MOTOR_VEHICLE = "motor_vehicle"
    FDC_INCOME = "fdc_income"
    INTERNET = "internet"
    MOBILE = "mobile"
    HOME_OFFICE = "home_office"
    FOOD_GST = "food_gst"
    FDC_INSURANCE = "fdc_insurance"
    DEPRECIATION = "depreciation"
    SUMMARY = "summary"


class TransactionSource(str, Enum):
    """Source of transaction data"""
    MYFDC = "myfdc"
    MANUAL = "manual"
    IMPORT = "import"


class TransactionCategory(str, Enum):
    """Transaction categories"""
    # Motor Vehicle
    VEHICLE_FUEL = "vehicle_fuel"
    VEHICLE_REGISTRATION = "vehicle_registration"
    VEHICLE_INSURANCE = "vehicle_insurance"
    VEHICLE_REPAIRS = "vehicle_repairs"
    VEHICLE_LEASE = "vehicle_lease"
    VEHICLE_INTEREST = "vehicle_interest"
    VEHICLE_OTHER = "vehicle_other"
    
    # Home Office
    HOME_ELECTRICITY = "home_electricity"
    HOME_GAS = "home_gas"
    HOME_CLEANING = "home_cleaning"
    HOME_REPAIRS = "home_repairs"
    HOME_OTHER = "home_other"
    
    # Communications
    INTERNET = "internet"
    MOBILE = "mobile"
    LANDLINE = "landline"
    
    # FDC Specific
    FDC_INCOME = "fdc_income"
    FDC_FOOD = "fdc_food"
    FDC_INSURANCE = "fdc_insurance"
    FDC_EQUIPMENT = "fdc_equipment"
    FDC_SUPPLIES = "fdc_supplies"
    
    # General
    DEPRECIATION = "depreciation"
    OTHER = "other"
    UNCATEGORIZED = "uncategorized"


class QueryStatus(str, Enum):
    """Status for queries"""
    DRAFT = "draft"
    SENT_TO_CLIENT = "sent_to_client"
    AWAITING_CLIENT = "awaiting_client"
    CLIENT_RESPONDED = "client_responded"
    RESOLVED = "resolved"
    CLOSED = "closed"


class QueryType(str, Enum):
    """Type of query/request"""
    TEXT = "text"
    REQUEST_UPLOAD = "request_upload"
    REQUEST_NUMBER = "request_number"
    REQUEST_PERCENTAGE = "request_percentage"
    REQUEST_CONFIRMATION = "request_confirmation"
    REQUEST_SELECTION = "request_selection"


class SenderType(str, Enum):
    """Message sender type"""
    ADMIN = "admin"
    CLIENT = "client"
    SYSTEM = "system"


class TaskType(str, Enum):
    """Client task types"""
    QUERIES = "queries"
    DOCUMENT_REQUEST = "document_request"
    REVIEW_REQUIRED = "review_required"


class TaskStatus(str, Enum):
    """Task status"""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class SnapshotType(str, Enum):
    """Freeze snapshot types"""
    MODULE = "module"
    BAS = "bas"
    ITR = "itr"
    SUMMARY = "summary"


class CalculationMethod(str, Enum):
    """Calculation methods (module-specific)"""
    # Motor Vehicle
    CENTS_PER_KM = "cents_per_km"
    LOGBOOK = "logbook"
    
    # Home Office
    ACTUAL = "actual"
    RATE_PER_HOUR = "rate_per_hour"
    FIXED_RATE = "fixed_rate"
    
    # Internet/Mobile
    DIARY = "diary"
    ESTIMATE = "estimate"
    PRIOR_YEAR = "prior_year"
    MAPPING = "mapping"
    CHECKLIST = "checklist"


# ==================== CORE MODELS ====================

class WorkpaperJob(BaseModel):
    """
    Represents one tax year per client.
    Status is derived from its modules (lowest/least-complete status).
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_id: str  # References myfdc.users.id
    year: str  # e.g., "2024-25"
    status: str = JobStatus.NOT_STARTED.value
    frozen_at: Optional[str] = None
    notes: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: Optional[str] = None
    
    def derive_status_from_modules(self, modules: List['ModuleInstance']) -> str:
        """Derive job status from its modules (lowest priority wins)"""
        if not modules:
            return JobStatus.NOT_STARTED.value
        
        applicable_modules = [m for m in modules if m.status != JobStatus.NA.value]
        if not applicable_modules:
            return JobStatus.NOT_STARTED.value
        
        # Find the lowest priority status
        min_priority = min(STATUS_PRIORITY.get(JobStatus(m.status), 1) for m in applicable_modules)
        
        for status, priority in STATUS_PRIORITY.items():
            if priority == min_priority:
                return status.value
        
        return JobStatus.NOT_STARTED.value


class ModuleInstance(BaseModel):
    """
    A module within a job (e.g., Vehicle 1, Internet, FDC Income).
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    module_type: str  # ModuleType enum value
    label: str  # e.g., "Vehicle 1", "Primary Internet"
    status: str = JobStatus.NOT_STARTED.value
    
    # Module-specific configuration (method selections, etc.)
    config: Dict[str, Any] = Field(default_factory=dict)
    
    # Key results (deduction, income, percentages, etc.)
    output_summary: Dict[str, Any] = Field(default_factory=dict)
    
    # Calculation inputs (populated by engine)
    calculation_inputs: Dict[str, Any] = Field(default_factory=dict)
    
    frozen_at: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: Optional[str] = None


class Transaction(BaseModel):
    """
    Immutable client data (from MyFDC or manual).
    Original transactions are never mutated by admin.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_id: str
    job_id: Optional[str] = None  # Can be linked to a specific job
    module_instance_id: Optional[str] = None  # Can be linked to a module
    
    source: str = TransactionSource.MANUAL.value
    date: str  # ISO date
    amount: float
    gst_amount: Optional[float] = None  # Original GST as entered
    category: str = TransactionCategory.UNCATEGORIZED.value
    description: Optional[str] = None
    
    # Supporting documentation
    receipt_url: Optional[str] = None
    document_id: Optional[str] = None
    
    # Additional metadata
    vendor: Optional[str] = None
    reference: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Note: No updated_at - transactions are immutable


class TransactionOverride(BaseModel):
    """
    Admin adjustments per transaction.
    Overrides can be job-specific.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    transaction_id: str
    job_id: str  # So overrides can be job-specific
    
    # Overridden values (nullable - only set if overridden)
    overridden_category: Optional[str] = None
    overridden_amount: Optional[float] = None
    overridden_gst_amount: Optional[float] = None
    overridden_business_pct: Optional[float] = None  # 0-100
    
    # Audit fields
    reason: str  # Required for any override
    admin_user_id: str
    admin_email: Optional[str] = None
    
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: Optional[str] = None


class EffectiveTransaction(BaseModel):
    """
    Computed view: Transaction + TransactionOverride.
    All calculations should use EffectiveTransaction data.
    """
    # Original transaction fields
    transaction_id: str
    client_id: str
    job_id: Optional[str] = None
    module_instance_id: Optional[str] = None
    source: str
    date: str
    description: Optional[str] = None
    receipt_url: Optional[str] = None
    vendor: Optional[str] = None
    
    # Original values
    original_amount: float
    original_gst_amount: Optional[float] = None
    original_category: str
    
    # Effective values (from override if present, else original)
    effective_amount: float
    effective_gst_amount: Optional[float] = None
    effective_category: str
    effective_business_pct: float = 100.0  # Default 100% business
    
    # Override info
    has_override: bool = False
    override_id: Optional[str] = None
    override_reason: Optional[str] = None
    
    # Calculated fields
    business_amount: float = 0.0  # effective_amount * business_pct
    business_gst_amount: Optional[float] = None


class OverrideRecord(BaseModel):
    """
    Module-level overrides for values not tied to a single transaction.
    E.g., internet %, logbook %, chosen method.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    module_instance_id: str
    
    field_key: str  # e.g., "effective_pct", "method", "business_km"
    original_value: Any  # JSON-serializable
    effective_value: Any  # JSON-serializable
    
    reason: str  # Required
    admin_user_id: str
    admin_email: Optional[str] = None
    
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Query(BaseModel):
    """
    Structured question/interaction between admin and client.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_id: str
    job_id: str
    module_instance_id: Optional[str] = None  # Nullable for job-level
    transaction_id: Optional[str] = None  # Nullable for transaction-level
    
    status: str = QueryStatus.DRAFT.value
    title: str
    query_type: str = QueryType.TEXT.value
    
    # For structured requests
    request_config: Dict[str, Any] = Field(default_factory=dict)
    # e.g., {"options": ["Yes", "No"]} for REQUEST_SELECTION
    # e.g., {"min": 0, "max": 100} for REQUEST_PERCENTAGE
    
    # Response data (populated when client responds)
    response_data: Optional[Dict[str, Any]] = None
    
    created_by_admin_id: str
    created_by_admin_email: Optional[str] = None
    resolved_by_admin_id: Optional[str] = None
    resolved_at: Optional[str] = None
    
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: Optional[str] = None


class QueryMessage(BaseModel):
    """
    Message within a query thread.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    query_id: str
    
    sender_type: str  # SenderType enum
    sender_id: str
    sender_email: Optional[str] = None
    
    message_text: str
    attachment_url: Optional[str] = None
    attachment_name: Optional[str] = None
    
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Task(BaseModel):
    """
    Client-facing abstract task (e.g., "You have queries").
    A single QUERIES task per job bundles all open queries.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_id: str
    job_id: str
    
    task_type: str = TaskType.QUERIES.value
    status: str = TaskStatus.OPEN.value
    
    title: str
    description: Optional[str] = None
    
    # Metadata for task-specific info
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # e.g., {"query_count": 5, "query_ids": [...]}
    
    due_date: Optional[str] = None
    completed_at: Optional[str] = None
    
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: Optional[str] = None


class FreezeSnapshot(BaseModel):
    """
    Store frozen state for audit.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    module_instance_id: Optional[str] = None  # Nullable for job-level snapshot
    
    snapshot_type: str  # SnapshotType enum
    
    # Full calculation outputs, key inputs, overrides
    data: Dict[str, Any] = Field(default_factory=dict)
    
    # Summary for quick reference
    summary: Dict[str, Any] = Field(default_factory=dict)
    
    created_by_admin_id: str
    created_by_admin_email: Optional[str] = None
    
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ==================== METHOD SELECTION ====================

class MethodOption(BaseModel):
    """Configuration for a calculation method"""
    method: str  # CalculationMethod enum value
    name: str
    description: str
    is_default: bool = False
    requires_inputs: List[str] = Field(default_factory=list)
    produces_outputs: List[str] = Field(default_factory=list)


class ModuleMethodConfig(BaseModel):
    """Method selection configuration for a module type"""
    module_type: str
    available_methods: List[MethodOption]
    default_method: str
    
    # Rules for method selection
    can_admin_override: bool = True
    requires_reason_for_lower_result: bool = True


# Pre-defined method configurations for each module type
MODULE_METHOD_CONFIGS: Dict[str, ModuleMethodConfig] = {
    ModuleType.MOTOR_VEHICLE.value: ModuleMethodConfig(
        module_type=ModuleType.MOTOR_VEHICLE.value,
        available_methods=[
            MethodOption(
                method=CalculationMethod.CENTS_PER_KM.value,
                name="Cents per Kilometre",
                description="Claim 85 cents per business kilometre (max 5,000 km)",
                is_default=True,
                requires_inputs=["business_km"],
                produces_outputs=["deduction", "gst_credit"]
            ),
            MethodOption(
                method=CalculationMethod.LOGBOOK.value,
                name="Logbook Method",
                description="Claim actual expenses based on logbook percentage",
                requires_inputs=["logbook_pct", "total_expenses"],
                produces_outputs=["deduction", "gst_credit", "depreciation"]
            )
        ],
        default_method=CalculationMethod.CENTS_PER_KM.value
    ),
    ModuleType.HOME_OFFICE.value: ModuleMethodConfig(
        module_type=ModuleType.HOME_OFFICE.value,
        available_methods=[
            MethodOption(
                method=CalculationMethod.FIXED_RATE.value,
                name="Fixed Rate Method",
                description="Claim 67 cents per hour worked from home",
                is_default=True,
                requires_inputs=["hours_worked"],
                produces_outputs=["deduction"]
            ),
            MethodOption(
                method=CalculationMethod.ACTUAL.value,
                name="Actual Expenses Method",
                description="Claim actual running expenses based on floor area",
                requires_inputs=["floor_area_pct", "running_expenses"],
                produces_outputs=["deduction", "gst_credit"]
            )
        ],
        default_method=CalculationMethod.FIXED_RATE.value
    ),
    ModuleType.INTERNET.value: ModuleMethodConfig(
        module_type=ModuleType.INTERNET.value,
        available_methods=[
            MethodOption(
                method=CalculationMethod.DIARY.value,
                name="Diary Method",
                description="Based on recorded usage diary",
                requires_inputs=["diary_entries"],
                produces_outputs=["business_pct", "deduction"]
            ),
            MethodOption(
                method=CalculationMethod.ESTIMATE.value,
                name="Reasonable Estimate",
                description="Based on reasonable estimate of business use",
                is_default=True,
                requires_inputs=["estimated_pct"],
                produces_outputs=["business_pct", "deduction"]
            )
        ],
        default_method=CalculationMethod.ESTIMATE.value
    ),
    ModuleType.MOBILE.value: ModuleMethodConfig(
        module_type=ModuleType.MOBILE.value,
        available_methods=[
            MethodOption(
                method=CalculationMethod.ESTIMATE.value,
                name="Reasonable Estimate",
                description="Based on reasonable estimate of business use",
                is_default=True,
                requires_inputs=["estimated_pct"],
                produces_outputs=["business_pct", "deduction"]
            ),
            MethodOption(
                method=CalculationMethod.DIARY.value,
                name="Call Log Analysis",
                description="Based on actual call log analysis",
                requires_inputs=["call_log_data"],
                produces_outputs=["business_pct", "deduction"]
            )
        ],
        default_method=CalculationMethod.ESTIMATE.value
    )
}


# ==================== API MODELS ====================

class CreateJobRequest(BaseModel):
    """Request to create a new workpaper job"""
    client_id: str
    year: str
    notes: Optional[str] = None
    auto_create_modules: bool = True  # Auto-create standard modules


class UpdateJobRequest(BaseModel):
    """Request to update a workpaper job"""
    status: Optional[str] = None
    notes: Optional[str] = None


class CreateModuleRequest(BaseModel):
    """Request to create a module instance"""
    job_id: str
    module_type: str
    label: str
    config: Optional[Dict[str, Any]] = None


class UpdateModuleRequest(BaseModel):
    """Request to update a module instance"""
    label: Optional[str] = None
    status: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class CreateTransactionRequest(BaseModel):
    """Request to create a transaction"""
    client_id: str
    job_id: Optional[str] = None
    module_instance_id: Optional[str] = None
    source: str = TransactionSource.MANUAL.value
    date: str
    amount: float
    gst_amount: Optional[float] = None
    category: str
    description: Optional[str] = None
    vendor: Optional[str] = None
    receipt_url: Optional[str] = None


class CreateOverrideRequest(BaseModel):
    """Request to create a transaction override"""
    transaction_id: str
    job_id: str
    overridden_category: Optional[str] = None
    overridden_amount: Optional[float] = None
    overridden_gst_amount: Optional[float] = None
    overridden_business_pct: Optional[float] = None
    reason: str  # Required


class CreateModuleOverrideRequest(BaseModel):
    """Request to create a module-level override"""
    module_instance_id: str
    field_key: str
    original_value: Any
    effective_value: Any
    reason: str  # Required


class CreateQueryRequest(BaseModel):
    """Request to create a query"""
    client_id: str
    job_id: str
    module_instance_id: Optional[str] = None
    transaction_id: Optional[str] = None
    title: str
    query_type: str = QueryType.TEXT.value
    request_config: Optional[Dict[str, Any]] = None
    initial_message: Optional[str] = None


class SendQueryRequest(BaseModel):
    """Request to send a query to client"""
    message: Optional[str] = None


class AddMessageRequest(BaseModel):
    """Request to add a message to a query"""
    message_text: str
    attachment_url: Optional[str] = None
    attachment_name: Optional[str] = None


class RespondToQueryRequest(BaseModel):
    """Client response to a query"""
    message_text: Optional[str] = None
    response_data: Optional[Dict[str, Any]] = None
    attachment_url: Optional[str] = None


class FreezeModuleRequest(BaseModel):
    """Request to freeze a module"""
    reason: Optional[str] = None


class FreezeJobRequest(BaseModel):
    """Request to freeze a job"""
    snapshot_type: str  # ITR, BAS, SUMMARY
    reason: Optional[str] = None


# ==================== RESPONSE MODELS ====================

class ModuleSummary(BaseModel):
    """Summary of a module for dashboard"""
    id: str
    module_type: str
    label: str
    status: str
    has_open_queries: bool = False
    open_query_count: int = 0
    output_summary: Dict[str, Any] = Field(default_factory=dict)
    frozen_at: Optional[str] = None


class JobDashboard(BaseModel):
    """Dashboard view of a job with all modules"""
    job: WorkpaperJob
    modules: List[ModuleSummary]
    total_deduction: float = 0.0
    total_income: float = 0.0
    open_queries: int = 0
    has_tasks: bool = False


class ModuleDetail(BaseModel):
    """Detailed view of a module"""
    module: ModuleInstance
    config_options: Optional[ModuleMethodConfig] = None
    overrides: List[OverrideRecord] = Field(default_factory=list)
    queries: List[Query] = Field(default_factory=list)
    effective_transactions: List[EffectiveTransaction] = Field(default_factory=list)
