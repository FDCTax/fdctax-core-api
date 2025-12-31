"""
Identity Spine - API Router

Provides REST API endpoints for identity management:
- POST /api/identity/myfdc-signup - MyFDC user signup
- POST /api/identity/crm-client-create - Create CRM client
- POST /api/identity/link-existing - Link existing records
- POST /api/identity/merge - Merge duplicate persons
- GET /api/identity/orphaned - List orphaned records
- GET /api/identity/person/{id} - Get person by ID
- GET /api/identity/person/by-email - Get person by email

Permissions:
- signup: public
- client-create: admin, staff
- link/merge: admin
- orphaned: admin
"""

import logging
import uuid
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, EmailStr, field_validator

from database import get_db
from middleware.auth import RoleChecker, AuthUser

from .service import IdentityService

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/identity", tags=["Identity Spine"])

# Permission checkers
require_admin = RoleChecker(["admin"])
require_staff = RoleChecker(["admin", "staff"])


# ==================== REQUEST/RESPONSE MODELS ====================

class MyFDCSignupRequest(BaseModel):
    """Request model for MyFDC signup"""
    email: EmailStr = Field(..., description="User email address")
    password_hash: Optional[str] = Field(None, description="Hashed password (for local auth)")
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    mobile: Optional[str] = Field(None, max_length=50)
    auth_provider: str = Field("local", description="Auth provider: local, google, etc.")
    auth_provider_id: Optional[str] = Field(None, description="Provider-specific ID")
    settings: Optional[dict] = Field(None, description="Initial settings")


class CRMClientCreateRequest(BaseModel):
    """Request model for CRM client creation"""
    email: EmailStr = Field(..., description="Client email address")
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    mobile: Optional[str] = Field(None, max_length=50)
    client_code: Optional[str] = Field(None, max_length=50, description="External client reference")
    abn: Optional[str] = Field(None, max_length=20)
    business_name: Optional[str] = Field(None, max_length=255)
    entity_type: Optional[str] = Field(None, description="individual, sole_trader, company, trust, partnership")
    gst_registered: bool = Field(False)
    source: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = Field(None)
    tags: Optional[List[str]] = Field(None)
    custom_fields: Optional[dict] = Field(None)


class LinkExistingRequest(BaseModel):
    """Request model for linking existing records"""
    source_type: str = Field(..., description="myfdc or crm")
    source_email: EmailStr = Field(..., description="Email of source record")
    target_type: str = Field(..., description="myfdc or crm")
    target_email: EmailStr = Field(..., description="Email of target record")
    
    @field_validator('source_type', 'target_type')
    @classmethod
    def validate_type(cls, v):
        if v not in ('myfdc', 'crm'):
            raise ValueError('Must be "myfdc" or "crm"')
        return v


class MergePersonsRequest(BaseModel):
    """Request model for merging persons"""
    primary_id: str = Field(..., description="ID of person to keep")
    secondary_id: str = Field(..., description="ID of person to merge into primary")


class UpdateEngagementRequest(BaseModel):
    """Request model for updating engagement profile"""
    person_id: str = Field(..., description="Person ID")
    is_myfdc_user: Optional[bool] = None
    is_crm_client: Optional[bool] = None
    has_ocr: Optional[bool] = None
    is_diy_bas_user: Optional[bool] = None
    is_diy_itr_user: Optional[bool] = None
    is_full_service_bas_client: Optional[bool] = None
    is_full_service_itr_client: Optional[bool] = None
    is_bookkeeping_client: Optional[bool] = None
    is_payroll_client: Optional[bool] = None
    subscription_tier: Optional[str] = None


# ==================== ENDPOINTS ====================

@router.get("/status")
async def get_identity_status():
    """
    Get Identity Spine module status.
    No authentication required.
    """
    return {
        "status": "ok",
        "module": "identity_spine",
        "version": "1.0.0",
        "features": {
            "myfdc_signup": True,
            "crm_client_create": True,
            "link_existing": True,
            "merge_persons": True,
            "orphan_detection": True
        }
    }


@router.post("/myfdc-signup")
async def myfdc_signup(
    request: MyFDCSignupRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle MyFDC user signup.
    
    **Rules:**
    - If email exists, links to existing person
    - If person already has MyFDC account, returns error
    - Never creates duplicate persons
    
    **No authentication required** (public endpoint)
    """
    service = IdentityService(db)
    
    try:
        result = await service.myfdc_signup(
            email=request.email,
            password_hash=request.password_hash,
            first_name=request.first_name,
            last_name=request.last_name,
            mobile=request.mobile,
            auth_provider=request.auth_provider,
            auth_provider_id=request.auth_provider_id,
            settings=request.settings,
            performed_by="myfdc_signup"
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=result.get("error", "Signup failed")
            )
        
        return result
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/crm-client-create")
async def crm_client_create(
    request: CRMClientCreateRequest,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Create CRM client record.
    
    **Rules:**
    - If email exists, links to existing person
    - If person already has CRM client, returns error
    - Never creates duplicate persons
    
    **Permissions:** admin, staff
    """
    service = IdentityService(db)
    
    try:
        result = await service.crm_client_create(
            email=request.email,
            first_name=request.first_name,
            last_name=request.last_name,
            mobile=request.mobile,
            client_code=request.client_code,
            abn=request.abn,
            business_name=request.business_name,
            entity_type=request.entity_type,
            gst_registered=request.gst_registered,
            source=request.source,
            notes=request.notes,
            tags=request.tags,
            custom_fields=request.custom_fields,
            performed_by=current_user.email
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=result.get("error", "Client creation failed")
            )
        
        return result
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/link-existing")
async def link_existing(
    request: LinkExistingRequest,
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Link existing MyFDC and CRM records.
    
    If emails are different, merges the persons and links accounts.
    
    **Permissions:** admin
    """
    service = IdentityService(db)
    
    result = await service.link_existing(
        source_type=request.source_type,
        source_email=request.source_email,
        target_type=request.target_type,
        target_email=request.target_email,
        performed_by=current_user.email
    )
    
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Linking failed")
        )
    
    return result


@router.post("/merge")
async def merge_persons(
    request: MergePersonsRequest,
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Merge two person records into one.
    
    The primary person is kept, secondary's linked records are moved.
    
    **Permissions:** admin
    """
    service = IdentityService(db)
    
    try:
        primary_id = uuid.UUID(request.primary_id)
        secondary_id = uuid.UUID(request.secondary_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid UUID format"
        )
    
    result = await service.merge_persons(
        primary_id=primary_id,
        secondary_id=secondary_id,
        performed_by=current_user.email
    )
    
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Merge failed")
        )
    
    return result


@router.get("/orphaned")
async def list_orphaned_records(
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    List orphaned MyFDC accounts and CRM clients.
    
    Orphaned = records without valid person link.
    
    **Permissions:** admin
    """
    service = IdentityService(db)
    return await service.list_orphaned_records()


@router.get("/duplicates")
async def find_duplicate_emails(
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Find potential duplicate persons based on email.
    
    **Permissions:** admin
    """
    service = IdentityService(db)
    duplicates = await service.find_duplicate_emails()
    return {"duplicates": duplicates, "count": len(duplicates)}


@router.get("/person/{person_id}")
async def get_person_by_id(
    person_id: str,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get person by ID with linked accounts.
    
    **Permissions:** admin, staff
    """
    service = IdentityService(db)
    
    try:
        pid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid UUID format"
        )
    
    person = await service.get_person_by_id(pid)
    if not person:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Person not found"
        )
    
    result = person.to_dict()
    if person.myfdc_account:
        result["myfdc_account"] = person.myfdc_account.to_dict()
    if person.crm_client:
        result["crm_client"] = person.crm_client.to_dict()
    if person.engagement_profile:
        result["engagement_profile"] = person.engagement_profile.to_dict()
    
    return result


@router.get("/person/by-email")
async def get_person_by_email(
    email: str = Query(..., description="Email address to search"),
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Get person by email with linked accounts.
    
    **Permissions:** admin, staff
    """
    service = IdentityService(db)
    
    person = await service.get_person_by_email(email)
    if not person:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Person not found"
        )
    
    result = person.to_dict()
    if person.myfdc_account:
        result["myfdc_account"] = person.myfdc_account.to_dict()
    if person.crm_client:
        result["crm_client"] = person.crm_client.to_dict()
    if person.engagement_profile:
        result["engagement_profile"] = person.engagement_profile.to_dict()
    
    return result


@router.put("/engagement/{person_id}")
async def update_engagement_profile(
    person_id: str,
    request: UpdateEngagementRequest,
    current_user: AuthUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Update engagement profile flags.
    
    **Permissions:** admin, staff
    """
    service = IdentityService(db)
    
    try:
        pid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid UUID format"
        )
    
    # Build flags dict from non-None values
    flags = {}
    for field in [
        'is_myfdc_user', 'is_crm_client', 'has_ocr',
        'is_diy_bas_user', 'is_diy_itr_user',
        'is_full_service_bas_client', 'is_full_service_itr_client',
        'is_bookkeeping_client', 'is_payroll_client',
        'subscription_tier'
    ]:
        value = getattr(request, field, None)
        if value is not None:
            flags[field] = value
    
    profile = await service.update_engagement_profile(pid, **flags)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Engagement profile not found"
        )
    
    return profile.to_dict()


@router.get("/stats")
async def get_identity_stats(
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get identity system statistics.
    
    **Permissions:** admin
    """
    from sqlalchemy import text
    
    stats_query = text("""
        SELECT 
            (SELECT COUNT(*) FROM person) as total_persons,
            (SELECT COUNT(*) FROM person WHERE status = 'active') as active_persons,
            (SELECT COUNT(*) FROM myfdc_account) as myfdc_accounts,
            (SELECT COUNT(*) FROM crm_client_identity) as crm_clients,
            (SELECT COUNT(*) FROM person p 
             WHERE EXISTS (SELECT 1 FROM myfdc_account m WHERE m.person_id = p.id)
               AND EXISTS (SELECT 1 FROM crm_client_identity c WHERE c.person_id = p.id)
            ) as linked_both,
            (SELECT COUNT(*) FROM engagement_profile WHERE is_myfdc_user = true) as myfdc_users,
            (SELECT COUNT(*) FROM engagement_profile WHERE is_crm_client = true) as crm_clients_engaged,
            (SELECT COUNT(*) FROM engagement_profile WHERE is_diy_bas_user = true) as diy_bas_users,
            (SELECT COUNT(*) FROM engagement_profile WHERE is_full_service_itr_client = true) as full_service_itr
    """)
    
    result = await db.execute(stats_query)
    row = result.fetchone()
    
    return {
        "total_persons": row[0] or 0,
        "active_persons": row[1] or 0,
        "myfdc_accounts": row[2] or 0,
        "crm_clients": row[3] or 0,
        "linked_both": row[4] or 0,
        "engagement": {
            "myfdc_users": row[5] or 0,
            "crm_clients": row[6] or 0,
            "diy_bas_users": row[7] or 0,
            "full_service_itr": row[8] or 0
        }
    }
