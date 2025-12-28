"""
FDC Core Workpaper Platform - Package Init

Exports all workpaper components for use by routers and other services.
"""

from services.workpaper.models import (
    # Enums
    JobStatus,
    ModuleType,
    TransactionSource,
    TransactionCategory,
    QueryStatus,
    QueryType,
    SenderType,
    TaskType,
    TaskStatus,
    SnapshotType,
    CalculationMethod,
    STATUS_PRIORITY,
    MODULE_METHOD_CONFIGS,
    
    # Core Models
    WorkpaperJob,
    ModuleInstance,
    Transaction,
    TransactionOverride,
    EffectiveTransaction,
    OverrideRecord,
    Query,
    QueryMessage,
    Task,
    FreezeSnapshot,
    
    # API Models
    CreateJobRequest,
    UpdateJobRequest,
    CreateModuleRequest,
    UpdateModuleRequest,
    CreateTransactionRequest,
    CreateOverrideRequest,
    CreateModuleOverrideRequest,
    CreateQueryRequest,
    SendQueryRequest,
    AddMessageRequest,
    RespondToQueryRequest,
    FreezeModuleRequest,
    FreezeJobRequest,
    
    # Response Models
    ModuleSummary,
    JobDashboard,
    ModuleDetail,
)

# Database-backed storage repositories (NEW - PostgreSQL)
from services.workpaper.db_storage import (
    WorkpaperJobRepository,
    ModuleInstanceRepository,
    TransactionRepository,
    TransactionOverrideRepository,
    OverrideRecordRepository,
    QueryRepository,
    QueryMessageRepository,
    TaskRepository,
    FreezeSnapshotRepository,
    WorkpaperAuditLogRepository,
    EffectiveTransactionBuilder,
)

# Legacy file-based storage (deprecated - kept for reference)
from services.workpaper.storage import (
    job_storage,
    module_storage,
    transaction_storage,
    override_storage,
    module_override_storage,
    query_storage,
    message_storage,
    task_storage,
    snapshot_storage,
    effective_builder,
)

from services.workpaper.engine import (
    get_calculation_engine,
    calculate_module,
    calculate_all_modules,
    CENTS_PER_KM_RATE,
    CENTS_PER_KM_MAX_KM,
    HOME_OFFICE_FIXED_RATE,
    GST_RATE,
)

from services.workpaper.query_engine import query_engine

from services.workpaper.freeze_engine import freeze_engine


__all__ = [
    # Enums
    'JobStatus',
    'ModuleType',
    'TransactionSource',
    'TransactionCategory',
    'QueryStatus',
    'QueryType',
    'SenderType',
    'TaskType',
    'TaskStatus',
    'SnapshotType',
    'CalculationMethod',
    'STATUS_PRIORITY',
    'MODULE_METHOD_CONFIGS',
    
    # Core Models
    'WorkpaperJob',
    'ModuleInstance',
    'Transaction',
    'TransactionOverride',
    'EffectiveTransaction',
    'OverrideRecord',
    'Query',
    'QueryMessage',
    'Task',
    'FreezeSnapshot',
    
    # API Models
    'CreateJobRequest',
    'UpdateJobRequest',
    'CreateModuleRequest',
    'UpdateModuleRequest',
    'CreateTransactionRequest',
    'CreateOverrideRequest',
    'CreateModuleOverrideRequest',
    'CreateQueryRequest',
    'SendQueryRequest',
    'AddMessageRequest',
    'RespondToQueryRequest',
    'FreezeModuleRequest',
    'FreezeJobRequest',
    
    # Response Models
    'ModuleSummary',
    'JobDashboard',
    'ModuleDetail',
    
    # Database Repositories (NEW)
    'WorkpaperJobRepository',
    'ModuleInstanceRepository',
    'TransactionRepository',
    'TransactionOverrideRepository',
    'OverrideRecordRepository',
    'QueryRepository',
    'QueryMessageRepository',
    'TaskRepository',
    'FreezeSnapshotRepository',
    'WorkpaperAuditLogRepository',
    'EffectiveTransactionBuilder',
    
    # Legacy Storage (deprecated)
    'job_storage',
    'module_storage',
    'transaction_storage',
    'override_storage',
    'module_override_storage',
    'query_storage',
    'message_storage',
    'task_storage',
    'snapshot_storage',
    'effective_builder',
    
    # Engines
    'get_calculation_engine',
    'calculate_module',
    'calculate_all_modules',
    'query_engine',
    'freeze_engine',
    
    # Constants
    'CENTS_PER_KM_RATE',
    'CENTS_PER_KM_MAX_KM',
    'HOME_OFFICE_FIXED_RATE',
    'GST_RATE',
]
