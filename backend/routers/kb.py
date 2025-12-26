from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
import logging

from database import get_db
from models import KBEntryResponse, KBEntryCreate, KBEntryUpdate
from services.crm_sync import CRMSyncService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/kb", tags=["Knowledge Base"])


@router.get("/entries", response_model=List[KBEntryResponse])
async def list_kb_entries(
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search in question, tags, variations"),
    is_active: Optional[bool] = Query(True, description="Filter by active status"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db)
):
    """
    List knowledge base entries with optional filters
    Used by Luna for answering user questions
    """
    try:
        crm_service = CRMSyncService(db)
        entries = await crm_service.list_kb_entries(
            category=category,
            search=search,
            is_active=is_active,
            limit=limit,
            offset=offset
        )
        return entries
    except Exception as e:
        logger.error(f"Error listing KB entries: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entries/{entry_id}", response_model=KBEntryResponse)
async def get_kb_entry(
    entry_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get specific KB entry by ID
    """
    try:
        crm_service = CRMSyncService(db)
        entry = await crm_service.get_kb_entry(entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="KB entry not found")
        return entry
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching KB entry {entry_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search_kb(
    query: str = Query(..., description="Search query"),
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db)
):
    """
    Search KB for Luna responses
    Searches question, tags, variations, and answer content
    """
    try:
        crm_service = CRMSyncService(db)
        results = await crm_service.search_kb(query, limit)
        return {
            "query": query,
            "results": results,
            "count": len(results)
        }
    except Exception as e:
        logger.error(f"Error searching KB: {e}")
        raise HTTPException(status_code=500, detail=str(e))
