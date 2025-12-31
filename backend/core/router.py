"""
Core Module - API Router

Provides REST API endpoints for:
- Client Profile CRUD operations
- Luna migration endpoints
- Internal service endpoints

Permissions:
- /client-profiles: staff, tax_agent, admin (RBAC)
- /migration: internal services (API key auth)
"""

import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import RoleChecker, AuthUser
from middleware.internal_auth import (
    get_internal_service, InternalService,
    InternalOrUserAuth,
    is_internal_auth_configured
)
from core.client_profiles import ClientProfileService, ClientProfile
from core.migration import LunaMigrationService
from utils.encryption import is_encryption_configured

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/core", tags=["Core - Client Profiles & Migration"])

# Permission checkers
require_profile_read = RoleChecker(["admin", "staff", "tax_agent"])
require_profile_write = RoleChecker(["admin", "staff"])
require_admin = RoleChecker(["admin"])


# ==================== REQUEST/RESPONSE MODELS ====================

class ClientProfileCreate(BaseModel):
    """Request model for creating a client profile"""
    client_code: str = Field(..., description="Unique client code")
    display_name: str = Field(..., description="Display name")
    legal_name: Optional[str] = None
    trading_name: Optional[str] = None
    entity_type: str = Field("individual", description="Entity type")
    client_status: str = Field("active", description="Client status")
    
    # Contact
    primary_contact_first_name: Optional[str] = None
    primary_contact_last_name: Optional[str] = None
    primary_contact_email: Optional[str] = None
    primary_contact_phone: Optional[str] = None
    primary_contact_mobile: Optional[str] = None
    
    # Address
    primary_address_line1: Optional[str] = None
    primary_suburb: Optional[str] = None
    primary_state: Optional[str] = None
    primary_postcode: Optional[str] = None
    
    # Tax
    abn: Optional[str] = None
    tfn: Optional[str] = Field(None, description="Tax File Number (will be encrypted)")
    gst_registered: bool = False
    
    # Business
    industry_code: Optional[str] = None
    industry_description: Optional[str] = None
    
    # Staff
    assigned_partner_id: Optional[str] = None
    assigned_manager_id: Optional[str] = None
    
    # Services
    services_engaged: List[str] = Field(default_factory=list)
    engagement_type: Optional[str] = None
    
    # Notes
    internal_notes: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    custom_fields: Dict[str, Any] = Field(default_factory=dict)


class ClientProfileUpdate(BaseModel):
    """Request model for updating a client profile"""
    display_name: Optional[str] = None
    legal_name: Optional[str] = None
    trading_name: Optional[str] = None
    client_status: Optional[str] = None
    
    primary_contact_email: Optional[str] = None
    primary_contact_phone: Optional[str] = None
    primary_contact_mobile: Optional[str] = None
    
    abn: Optional[str] = None
    tfn: Optional[str] = Field(None, description="Tax File Number (will be encrypted)")
    gst_registered: Optional[bool] = None
    
    internal_notes: Optional[str] = None
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None


class MigrateSingleRequest(BaseModel):
    """Request model for single client migration"""
    client_code: Optional[str] = None
    code: Optional[str] = None
    display_name: Optional[str] = None
    name: Optional[str] = None
    luna_id: Optional[str] = None
    
    # All other fields are optional and will be mapped
    legal_name: Optional[str] = None
    trading_name: Optional[str] = None
    entity_type: Optional[str] = None
    status: Optional[str] = None
    
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    
    street: Optional[str] = None
    address_line1: Optional[str] = None
    suburb: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postcode: Optional[str] = None
    
    abn: Optional[str] = None
    acn: Optional[str] = None
    tfn: Optional[str] = None
    gst_registered: Optional[bool] = None
    
    services: Optional[List[str]] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    
    class Config:
        extra = "allow"  # Allow additional fields from Luna


class MigrateBatchRequest(BaseModel):
    """Request model for batch client migration"""
    clients: List[Dict[str, Any]] = Field(..., description="List of client records to migrate")


# ==================== STATUS ENDPOINT ====================

@router.get("/status")
async def get_core_status():
    """
    Get Core module status.
    
    Returns module health, encryption status, and configuration.
    """
    return {
        "status": "ok",
        "module": "core",
        "version": "1.0.0",
        "features": {
            "client_profiles": True,
            "luna_migration": True,
            "tfn_encryption": is_encryption_configured(),
            "internal_auth": is_internal_auth_configured()
        },
        "encryption_configured": is_encryption_configured(),
        "internal_auth_configured": is_internal_auth_configured()
    }


# ==================== CLIENT PROFILE ENDPOINTS ====================

@router.post("/client-profiles")
async def create_client_profile(
    request: ClientProfileCreate,
    current_user: AuthUser = Depends(require_profile_write),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new client profile.
    
    **Permissions:** admin, staff
    
    Creates a client profile with the 86-field schema.
    TFN is automatically encrypted if provided.
    """
    service = ClientProfileService(db)
    
    # Check if client code already exists
    existing = await service.get_by_client_code(request.client_code)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Client code already exists: {request.client_code}"
        )
    
    # Create profile
    profile = ClientProfile(
        client_code=request.client_code,
        display_name=request.display_name,
        legal_name=request.legal_name,
        trading_name=request.trading_name,
        entity_type=request.entity_type,
        client_status=request.client_status,
        primary_contact_first_name=request.primary_contact_first_name,
        primary_contact_last_name=request.primary_contact_last_name,
        primary_contact_email=request.primary_contact_email,
        primary_contact_phone=request.primary_contact_phone,
        primary_contact_mobile=request.primary_contact_mobile,
        primary_address_line1=request.primary_address_line1,
        primary_suburb=request.primary_suburb,
        primary_state=request.primary_state,
        primary_postcode=request.primary_postcode,
        abn=request.abn,
        tfn=request.tfn,
        gst_registered=request.gst_registered,
        industry_code=request.industry_code,
        industry_description=request.industry_description,
        assigned_partner_id=request.assigned_partner_id,
        assigned_manager_id=request.assigned_manager_id,
        services_engaged=request.services_engaged,
        engagement_type=request.engagement_type,
        internal_notes=request.internal_notes,
        tags=request.tags,
        custom_fields=request.custom_fields,
        source_system="core"
    )
    
    try:
        created = await service.create(profile, created_by=current_user.email)
        return {"success": True, "profile": created}
    except Exception as e:
        logger.error(f"Failed to create profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/client-profiles")
async def list_client_profiles(
    query: Optional[str] = Query(None, description="Search term"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    client_status: Optional[str] = Query(None, description="Filter by status"),
    assigned_to: Optional[str] = Query(None, description="Filter by assigned staff"),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    current_user: AuthUser = Depends(require_profile_read),
    db: AsyncSession = Depends(get_db)
):
    """
    List/search client profiles.
    
    **Permissions:** admin, staff, tax_agent
    """
    service = ClientProfileService(db)
    
    profiles = await service.search(
        query_str=query,
        entity_type=entity_type,
        client_status=client_status,
        assigned_to=assigned_to,
        limit=limit,
        offset=offset
    )
    
    return {"profiles": profiles, "count": len(profiles)}


@router.get("/client-profiles/{profile_id}")
async def get_client_profile(
    profile_id: str,
    include_tfn: bool = Query(False, description="Include decrypted TFN (requires admin)"),
    current_user: AuthUser = Depends(require_profile_read),
    db: AsyncSession = Depends(get_db)
):
    """
    Get client profile by ID.
    
    **Permissions:** admin, staff, tax_agent
    
    TFN is masked by default. Set include_tfn=true (admin only) to decrypt.
    """
    # Only admin can view decrypted TFN
    if include_tfn and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can view decrypted TFN"
        )
    
    service = ClientProfileService(db)
    
    profile = await service.get_by_id(
        profile_id,
        include_tfn=include_tfn,
        user_id=current_user.id if include_tfn else None
    )
    
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client profile not found"
        )
    
    return profile


@router.get("/client-profiles/by-code/{client_code}")
async def get_client_profile_by_code(
    client_code: str,
    include_tfn: bool = Query(False, description="Include decrypted TFN (requires admin)"),
    current_user: AuthUser = Depends(require_profile_read),
    db: AsyncSession = Depends(get_db)
):
    """
    Get client profile by client code.
    
    **Permissions:** admin, staff, tax_agent
    """
    if include_tfn and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can view decrypted TFN"
        )
    
    service = ClientProfileService(db)
    
    profile = await service.get_by_client_code(
        client_code,
        include_tfn=include_tfn,
        user_id=current_user.id if include_tfn else None
    )
    
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client profile not found"
        )
    
    return profile


@router.patch("/client-profiles/{profile_id}")
async def update_client_profile(
    profile_id: str,
    request: ClientProfileUpdate,
    current_user: AuthUser = Depends(require_profile_write),
    db: AsyncSession = Depends(get_db)
):
    """
    Update client profile.
    
    **Permissions:** admin, staff
    """
    service = ClientProfileService(db)
    
    # Check profile exists
    existing = await service.get_by_id(profile_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client profile not found"
        )
    
    # Build updates from non-None fields
    updates = {k: v for k, v in request.dict().items() if v is not None}
    
    if not updates:
        return {"success": True, "profile": existing, "message": "No updates provided"}
    
    try:
        updated = await service.update(profile_id, updates, updated_by=current_user.email)
        return {"success": True, "profile": updated}
    except Exception as e:
        logger.error(f"Failed to update profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/client-profiles/{profile_id}")
async def delete_client_profile(
    profile_id: str,
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete (archive) client profile.
    
    **Permissions:** admin only
    
    Performs soft delete by setting status to 'archived'.
    """
    service = ClientProfileService(db)
    
    success = await service.delete(profile_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client profile not found"
        )
    
    return {"success": True, "message": "Client profile archived"}


# ==================== MIGRATION ENDPOINTS (Internal Service Auth) ====================

@router.post("/migration/client")
async def migrate_single_client(
    request: MigrateSingleRequest,
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Migrate a single client from Luna to Core.
    
    **Auth:** Internal API Key (X-Internal-Api-Key header)
    
    Called by Luna CRM during migration.
    """
    logger.info(f"Migration request from service: {service.name}")
    
    migration_service = LunaMigrationService(db)
    
    result = await migration_service.migrate_client(
        luna_data=request.dict(exclude_none=True),
        migrated_by=service.name
    )
    
    return result.to_dict()


@router.post("/migration/batch")
async def migrate_batch_clients(
    request: MigrateBatchRequest,
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Migrate multiple clients from Luna to Core in a batch.
    
    **Auth:** Internal API Key (X-Internal-Api-Key header)
    
    Called by Luna CRM for bulk migration.
    """
    logger.info(f"Batch migration request from service: {service.name} with {len(request.clients)} clients")
    
    migration_service = LunaMigrationService(db)
    
    result = await migration_service.migrate_batch(
        clients=request.clients,
        migrated_by=service.name
    )
    
    return result.to_dict()


@router.post("/migration/sync")
async def sync_client(
    client_code: str = Query(..., description="Client code to sync"),
    request: MigrateSingleRequest = None,
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Sync/update an existing client from Luna.
    
    **Auth:** Internal API Key (X-Internal-Api-Key header)
    
    Used for ongoing sync after initial migration.
    """
    migration_service = LunaMigrationService(db)
    
    result = await migration_service.sync_client(
        client_code=client_code,
        luna_data=request.dict(exclude_none=True) if request else {},
        synced_by=service.name
    )
    
    return result.to_dict()


@router.get("/migration/status")
async def get_migration_status(
    batch_id: Optional[str] = Query(None, description="Specific batch ID"),
    auth: dict = Depends(InternalOrUserAuth(allowed_roles=["admin"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Get migration status.
    
    **Auth:** Internal API Key OR Admin JWT
    
    Returns overall stats or specific batch status.
    """
    migration_service = LunaMigrationService(db)
    
    status = await migration_service.get_migration_status(batch_id)
    status["requested_by"] = auth.get("service_name") or auth.get("email")
    
    return status


@router.post("/migration/rollback/{batch_id}")
async def rollback_migration(
    batch_id: str,
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Rollback a migration batch.
    
    **Permissions:** admin only
    
    Archives all profiles created in the specified batch.
    """
    migration_service = LunaMigrationService(db)
    
    result = await migration_service.rollback_migration(
        batch_id=batch_id,
        performed_by=current_user.email
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    
    return result
