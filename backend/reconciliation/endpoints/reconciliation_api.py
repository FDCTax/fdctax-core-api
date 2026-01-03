"""
Reconciliation API Endpoints (A3-RECON-01)

REST API for the reconciliation engine:
- POST /api/reconciliation/match - Run reconciliation for a client
- GET /api/reconciliation/candidates/{client_id} - Get match candidates
- GET /api/reconciliation/matches/{client_id} - Get matches for a client
- GET /api/reconciliation/match/{match_id} - Get a single match
- POST /api/reconciliation/match/{match_id}/confirm - Confirm a match
- POST /api/reconciliation/match/{match_id}/reject - Reject a match
- GET /api/reconciliation/stats/{client_id} - Get reconciliation stats
- GET /api/reconciliation/sources - List supported sources
- GET /api/reconciliation/status - Module status
"""

import logging
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from reconciliation.source_registry import (
    ReconciliationSource,
    TargetType,
    MatchStatus,
    source_registry
)
from reconciliation.services.reconciliation_service import ReconciliationService
from utils.validation_errors import validate_required_uuid, validate_optional_uuid, raise_invalid_parameter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])


# ==================== Request/Response Models ====================

class RunReconciliationRequest(BaseModel):
    """Request to run reconciliation."""
    client_id: str = Field(..., description="Core client ID")
    source_type: str = Field(default="MYFDC", description="Source type (MYFDC, OCR, BANK_FEED, MANUAL)")
    target_type: str = Field(default="BANK", description="Target type (BANK, RECEIPT, INVOICE, MANUAL)")
    transaction_ids: Optional[List[str]] = Field(default=None, description="Specific transaction IDs to reconcile")
    auto_match: bool = Field(default=True, description="Auto-match high confidence matches")


class ConfirmMatchRequest(BaseModel):
    """Request to confirm a match."""
    pass  # Empty body, user_id comes from auth


class RejectMatchRequest(BaseModel):
    """Request to reject a match."""
    reason: Optional[str] = Field(default=None, description="Rejection reason")


class FindCandidatesRequest(BaseModel):
    """Request to find match candidates."""
    source_transaction_id: str = Field(..., description="Source transaction ID")
    target_type: Optional[str] = Field(default=None, description="Filter by target type")


class ReconciliationMatchResponse(BaseModel):
    """Response for a reconciliation match."""
    id: str
    client_id: str
    source_transaction_id: str
    source_type: str
    target_transaction_id: Optional[str]
    target_type: str
    target_reference: Optional[str]
    match_status: str
    confidence_score: float
    match_type: Optional[str]
    scoring_breakdown: Optional[dict]
    auto_matched: bool
    user_confirmed: bool
    confirmed_by: Optional[str]
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str


class ReconciliationRunResponse(BaseModel):
    """Response for a reconciliation run."""
    run_id: str
    client_id: str
    source_type: str
    total_transactions: int
    auto_matched: int
    suggested: int
    no_match: int
    matches: List[dict]


class ReconciliationStatsResponse(BaseModel):
    """Response for reconciliation statistics."""
    client_id: str
    total_matches: int
    by_status: dict
    reconciliation_rate: float


class SourceConfigResponse(BaseModel):
    """Response for source configuration."""
    source: str
    display_name: str
    priority: int
    enabled: bool
    match_targets: List[str]
    auto_match_threshold: float
    suggest_match_threshold: float


# ==================== Authentication ====================

import os

def get_internal_api_keys() -> List[str]:
    """Get list of valid internal API keys."""
    primary_key = os.environ.get('INTERNAL_API_KEY', '')
    legacy_keys = os.environ.get('INTERNAL_API_KEYS', '')
    
    keys = []
    if primary_key:
        keys.append(primary_key)
    if legacy_keys:
        keys.extend([k.strip() for k in legacy_keys.split(',') if k.strip()])
    
    return keys


def verify_internal_auth(x_internal_api_key: Optional[str] = Header(None, alias="X-Internal-Api-Key")):
    """Verify internal API key authentication."""
    valid_keys = get_internal_api_keys()
    
    if not valid_keys:
        logger.warning("No internal API keys configured")
        raise HTTPException(status_code=503, detail="Internal authentication not configured")
    
    if not x_internal_api_key:
        raise HTTPException(status_code=401, detail="Missing X-Internal-Api-Key header")
    
    if x_internal_api_key not in valid_keys:
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    return True


# ==================== Endpoints ====================

@router.get("/status", summary="Module status")
async def get_module_status():
    """
    Get reconciliation module status.
    
    Returns configuration and availability information.
    """
    return {
        "module": "reconciliation",
        "status": "operational",
        "version": "1.0.0",
        "features": {
            "myfdc_matching": True,
            "ocr_matching": True,
            "bank_feed_matching": True,
            "auto_matching": True
        },
        "sources_enabled": [s.value for s in source_registry.get_enabled_sources()],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/sources", summary="List supported sources")
async def list_sources():
    """
    List all supported reconciliation sources.
    
    Returns configuration for each source including thresholds.
    """
    configs = source_registry.get_all_configs()
    return {
        "sources": [cfg.to_dict() for cfg in configs],
        "enabled_count": len(source_registry.get_enabled_sources())
    }


@router.post("/match", response_model=ReconciliationRunResponse, summary="Run reconciliation")
async def run_reconciliation(
    request: RunReconciliationRequest,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    Run reconciliation for a client's transactions.
    
    This will:
    1. Find unreconciled transactions from the specified source
    2. Match them against target transactions (e.g., bank feeds)
    3. Auto-match high confidence matches (if enabled)
    4. Create suggested matches for review
    5. Record no-match for transactions without candidates
    
    Requires internal API key authentication.
    """
    try:
        # Validate source type
        try:
            source_type = ReconciliationSource(request.source_type)
        except ValueError:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid source_type. Valid values: {[s.value for s in ReconciliationSource]}"
            )
        
        # Validate target type
        try:
            target_type = TargetType(request.target_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid target_type. Valid values: {[t.value for t in TargetType]}"
            )
        
        service = ReconciliationService(db)
        result = await service.run_reconciliation(
            client_id=request.client_id,
            source_type=source_type,
            target_type=target_type,
            transaction_ids=request.transaction_ids,
            auto_match=request.auto_match
        )
        
        return ReconciliationRunResponse(
            run_id=result.run_id,
            client_id=result.client_id,
            source_type=result.source_type,
            total_transactions=result.total_transactions,
            auto_matched=result.auto_matched,
            suggested=result.suggested,
            no_match=result.no_match,
            matches=result.matches
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Reconciliation run failed: {e}")
        raise HTTPException(status_code=500, detail="Reconciliation run failed")


@router.post("/candidates/{client_id}", summary="Find match candidates")
async def find_candidates(
    client_id: str,
    request: FindCandidatesRequest,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    Find match candidates for a specific transaction.
    
    Returns scored candidates without creating matches.
    Useful for preview/review workflows.
    
    Requires internal API key authentication.
    """
    # Validate client_id is a valid UUID
    validated_client_id = validate_required_uuid(client_id, "client_id")
    
    # Validate source_transaction_id is a valid UUID
    validated_source_id = validate_required_uuid(request.source_transaction_id, "source_transaction_id")
    
    try:
        # Parse target type if provided
        target_type = None
        if request.target_type:
            try:
                target_type = TargetType(request.target_type)
            except ValueError:
                raise_invalid_parameter(
                    "target_type",
                    f"Invalid target_type. Valid values: {[t.value for t in TargetType]}",
                    request.target_type
                )
        
        service = ReconciliationService(db)
        result = await service.find_candidates(
            client_id=validated_client_id,
            source_transaction_id=validated_source_id,
            target_type=target_type
        )
        
        return result.to_dict()
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to find candidates: {e}")
        raise HTTPException(status_code=500, detail="Failed to find candidates")


@router.get("/matches/{client_id}", summary="Get matches for client")
async def get_matches(
    client_id: str,
    status: Optional[str] = Query(default=None, description="Filter by status"),
    source_type: Optional[str] = Query(default=None, description="Filter by source type"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    Get reconciliation matches for a client.
    
    Supports filtering by status and source type.
    
    Requires internal API key authentication.
    """
    # Validate client_id is a valid UUID
    validated_client_id = validate_required_uuid(client_id, "client_id")
    
    try:
        # Validate status if provided
        if status:
            try:
                MatchStatus(status)
            except ValueError:
                raise_invalid_parameter(
                    "status",
                    f"Invalid status. Valid values: {[s.value for s in MatchStatus]}",
                    status
                )
        
        service = ReconciliationService(db)
        matches = await service.get_matches_by_client(
            client_id=validated_client_id,
            status=status,
            source_type=source_type,
            limit=limit,
            offset=offset
        )
        
        return {
            "client_id": validated_client_id,
            "matches": matches,
            "count": len(matches),
            "limit": limit,
            "offset": offset
        }
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get matches: {e}")
        raise HTTPException(status_code=500, detail="Failed to get matches")


@router.get("/suggested/{client_id}", summary="Get suggested matches")
async def get_suggested_matches(
    client_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    Get pending suggested matches for review.
    
    Returns matches with SUGGESTED status that need user confirmation.
    
    Requires internal API key authentication.
    """
    try:
        service = ReconciliationService(db)
        matches = await service.get_suggested_matches(
            client_id=client_id,
            limit=limit
        )
        
        return {
            "client_id": client_id,
            "suggested_matches": matches,
            "count": len(matches)
        }
        
    except Exception as e:
        logger.error(f"Failed to get suggested matches: {e}")
        raise HTTPException(status_code=500, detail="Failed to get suggested matches")


@router.get("/match/{match_id}", summary="Get single match")
async def get_match(
    match_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    Get a single reconciliation match by ID.
    
    Requires internal API key authentication.
    """
    try:
        service = ReconciliationService(db)
        match = await service.get_match(match_id)
        
        if not match:
            raise HTTPException(status_code=404, detail="Match not found")
        
        return match
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get match: {e}")
        raise HTTPException(status_code=500, detail="Failed to get match")


@router.post("/match/{match_id}/confirm", summary="Confirm match")
async def confirm_match(
    match_id: str,
    db: AsyncSession = Depends(get_db),
    x_user_id: Optional[str] = Header(default="system", alias="X-User-Id"),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    Confirm a suggested match.
    
    Changes status from SUGGESTED to CONFIRMED.
    
    Requires internal API key authentication.
    """
    try:
        service = ReconciliationService(db)
        result = await service.confirm_match(
            match_id=match_id,
            user_id=x_user_id
        )
        
        return {
            "success": True,
            "message": "Match confirmed",
            "match": result
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to confirm match: {e}")
        raise HTTPException(status_code=500, detail="Failed to confirm match")


@router.post("/match/{match_id}/reject", summary="Reject match")
async def reject_match(
    match_id: str,
    request: RejectMatchRequest,
    db: AsyncSession = Depends(get_db),
    x_user_id: Optional[str] = Header(default="system", alias="X-User-Id"),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    Reject a suggested match.
    
    Changes status from SUGGESTED to REJECTED.
    
    Requires internal API key authentication.
    """
    try:
        service = ReconciliationService(db)
        result = await service.reject_match(
            match_id=match_id,
            user_id=x_user_id,
            reason=request.reason
        )
        
        return {
            "success": True,
            "message": "Match rejected",
            "match": result
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to reject match: {e}")
        raise HTTPException(status_code=500, detail="Failed to reject match")


@router.get("/stats/{client_id}", response_model=ReconciliationStatsResponse, summary="Get stats")
async def get_stats(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_internal_auth)
):
    """
    Get reconciliation statistics for a client.
    
    Returns counts by status and overall reconciliation rate.
    
    Requires internal API key authentication.
    """
    try:
        service = ReconciliationService(db)
        stats = await service.get_reconciliation_stats(client_id)
        
        return ReconciliationStatsResponse(**stats)
        
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get statistics")
