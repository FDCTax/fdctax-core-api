"""
BAS Backend Module

Provides BAS lifecycle management:
- BAS snapshots and history
- Sign-off persistence
- Change log / audit trail
- PDF data generation
- GST calculation (stub - Phase 1)

Module Structure:
- models.py: SQLAlchemy database models
- service.py: Business logic layer
- bas_calculator.py: GST/BAS calculation engine (stub)
- bas_schema.py: Schema definitions & Pydantic models
"""

from .models import BASStatementDB, BASChangeLogDB, BASStatus, BASActionType, BASEntityType
from .service import BASStatementService, BASChangeLogService
from .bas_calculator import BASCalculator, BASFields, GSTCode

__all__ = [
    # Database models
    "BASStatementDB",
    "BASChangeLogDB",
    "BASStatus",
    "BASActionType",
    "BASEntityType",
    # Services
    "BASStatementService",
    "BASChangeLogService",
    # Calculator (stub)
    "BASCalculator",
    "BASFields",
    "GSTCode",
]
