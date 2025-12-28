from .connection import get_db, engine, AsyncSessionLocal, init_db, Base

# Import workpaper models to ensure they are registered with Base
from .workpaper_models import (
    WorkpaperJobDB, ModuleInstanceDB, TransactionDB, TransactionOverrideDB,
    OverrideRecordDB, QueryDB, QueryMessageDB, TaskDB,
    FreezeSnapshotDB, WorkpaperAuditLogDB
)

# Import motor vehicle models
from .motor_vehicle_models import (
    VehicleAssetDB, VehicleKMEntryDB, VehicleLogbookPeriodDB, VehicleFuelEstimateDB
)

# Import transaction engine models (Bookkeeper layer)
from .transaction_models import (
    BookkeeperTransactionDB,
    TransactionHistoryDB, TransactionAttachmentDB, TransactionWorkpaperLinkDB,
    TransactionStatus, GSTCode, TransactionSource, ModuleRouting, HistoryActionType
)

__all__ = [
    'get_db', 'engine', 'AsyncSessionLocal', 'init_db', 'Base',
    # Workpaper models
    'WorkpaperJobDB', 'ModuleInstanceDB', 'TransactionDB', 'TransactionOverrideDB',
    'OverrideRecordDB', 'QueryDB', 'QueryMessageDB', 'TaskDB',
    'FreezeSnapshotDB', 'WorkpaperAuditLogDB',
    # Motor Vehicle models
    'VehicleAssetDB', 'VehicleKMEntryDB', 'VehicleLogbookPeriodDB', 'VehicleFuelEstimateDB',
    # Transaction Engine models (Bookkeeper layer)
    'BookkeeperTransactionDB', 'TransactionHistoryDB', 'TransactionAttachmentDB',
    'TransactionWorkpaperLinkDB', 'TransactionStatus', 'GSTCode', 'TransactionSource',
    'ModuleRouting', 'HistoryActionType',
]
