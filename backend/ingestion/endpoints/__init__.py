"""
Ingestion Endpoints Module
"""

from .myfdc_ingest import router as myfdc_ingestion_router

__all__ = ["myfdc_ingestion_router"]
