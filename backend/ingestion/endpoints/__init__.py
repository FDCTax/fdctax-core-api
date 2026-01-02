"""
Ingestion Endpoints Module
"""

from .myfdc_ingest import router as myfdc_ingestion_router
from .bookkeeping_ready import router as bookkeeping_ready_router

__all__ = ["myfdc_ingestion_router", "bookkeeping_ready_router"]
