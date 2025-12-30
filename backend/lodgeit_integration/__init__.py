"""
LodgeIT Integration Module

This module provides integration with the LodgeIT Practice Management system.
It handles:
- Client data export to LodgeIT CSV format
- Client data import from LodgeIT CSV with safe overwrite rules
- ITR (Income Tax Return) JSON template generation
- Export queue management with automatic triggers

Usage:
    from lodgeit_integration import (
        export_clients,
        import_csv,
        generate_itr_template,
    )
"""

from .export_service import export_clients, LodgeITExportService
from .import_service import import_csv, LodgeITImportService
from .itr_export import generate_itr_template, ITRExportService
from .models import (
    LodgeITExportQueueDB,
    ExportQueueStatus,
    LodgeITAuditLogDB,
)

__all__ = [
    'export_clients',
    'import_csv',
    'generate_itr_template',
    'LodgeITExportService',
    'LodgeITImportService',
    'ITRExportService',
    'LodgeITExportQueueDB',
    'ExportQueueStatus',
    'LodgeITAuditLogDB',
]
