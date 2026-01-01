"""
Core Client API Router

Provides REST API endpoints for unified client management.
Critical for MyFDC beta - establishes Core as the canonical client authority.

Endpoints:
- POST /api/clients/link-or-create - Link or create a Core client
- POST /api/v1/clients/link-or-create - [V1] Versioned alias (Ticket A3-8)
- GET /api/clients/{client_id} - Get client by ID
- GET /api/clients - List all clients
- POST /api/clients/{client_id}/link-crm - Link CRM client ID

Security:
- All endpoints require internal service token authentication
- All operations logged for audit trail (client.linked, client.created events)
- No sensitive data (TFN, ABN) logged in plaintext
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field, EmailStr

from database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from middleware.internal_auth import get_internal_service, InternalService

from services.clients import CoreClientService, CoreClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clients", tags=["Core Clients"])

# V1 versioned router - alias for compatibility
v1_router = APIRouter(prefix="/v1/clients", tags=["Core Clients V1"])


# ==================== REQUEST/RESPONSE MODELS ====================

class LinkOrCreateRequest(BaseModel):
    """Request to link or create a Core client."""
    myfdc_user_id: str = Field(..., description="MyFDC user ID")
    email: EmailStr = Field(..., description="User email")
    name: str = Field(..., min_length=1, description="User name")
    abn: Optional[str] = Field(None, description="ABN (optional)")
    phone: Optional[str] = Field(None, description="Phone number (optional)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "myfdc_user_id": "usr_12345",
                "email": "client@example.com",
                "name": "John Smith",
                "abn": "51824753556",
                "phone": "0412345678"
            }
        }


class SimpleLinkOrCreateRequest(BaseModel):
    """
    Simplified request for link-or-create during MyFDC login.
    
    Ticket A3-8: Accept email + optional name for linking.
    """
    email: EmailStr = Field(..., description="User email address")
    name: Optional[str] = Field(None, description="User name (optional)")
    myfdc_user_id: Optional[str] = Field(None, description="MyFDC user ID (auto-generated if not provided)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "educator@example.com",
                "name": "Jane Smith"
            }
        }


class LinkOrCreateResponse(BaseModel):
    """Response from link-or-create operation."""
    client_id: str
    linked: bool
    created: bool
    match_type: Optional[str] = None


class ClientResponse(BaseModel):
    """Full client response."""
    client_id: str
    name: str
    email: str
    abn: Optional[str] = None
    myfdc_user_id: Optional[str] = None
    crm_client_id: Optional[str] = None
    status: str = "active"


class ClientListItem(BaseModel):
    """Client item for list responses."""
    client_id: str
    name: str
    email: str
    linked_to_myfdc: bool
    linked_to_crm: bool
    linked_to_bookkeeping: bool
    status: str


class LinkCRMRequest(BaseModel):
    """Request to link a CRM client ID."""
    crm_client_id: str = Field(..., description="CRM client ID")


# ==================== ENDPOINTS ====================

async def _execute_link_or_create(
    request: LinkOrCreateRequest,
    service: InternalService,
    db: AsyncSession
) -> LinkOrCreateResponse:
    """
    Internal implementation of link-or-create logic.
    Shared between base and v1 endpoints.
    """
    logger.info(f"Link-or-create request from {service.name} for MyFDC user {request.myfdc_user_id}")
    
    client_service = CoreClientService(db)
    
    try:
        result = await client_service.link_or_create(
            myfdc_user_id=request.myfdc_user_id,
            email=request.email,
            name=request.name,
            abn=request.abn,
            phone=request.phone,
            service_name=service.name
        )
        
        return LinkOrCreateResponse(
            client_id=result.client_id,
            linked=result.linked,
            created=result.created,
            match_type=result.match_type
        )
        
    except Exception as e:
        logger.error(f"Link-or-create failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to link or create client"
        )


@router.post("/link-or-create", response_model=LinkOrCreateResponse)
async def link_or_create_client(
    request: LinkOrCreateRequest,
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Link a MyFDC user to an existing Core client, or create a new one.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    **Deduplication Logic:**
    1. If email matches existing client → link
    2. If ABN matches existing client → link
    3. Otherwise → create new client
    
    **Returns:**
    - `client_id`: The Core client UUID
    - `linked`: True if linked to existing client
    - `created`: True if new client was created
    - `match_type`: 'email' or 'abn' if linked, null if created
    """
    return await _execute_link_or_create(request, service, db)


@v1_router.post("/link-or-create", response_model=LinkOrCreateResponse)
async def link_or_create_client_v1(
    request: LinkOrCreateRequest,
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    [V1] Link a MyFDC user to an existing Core client, or create a new one.
    
    **Ticket A3-8:** Versioned endpoint for MyFDC → Core client linking.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    **Deduplication Logic:**
    1. If email matches existing client → link
    2. If ABN matches existing client → link  
    3. Otherwise → create new client
    
    **Audit Events:**
    - `client.linked` - When existing client is linked (no PII logged)
    - `client.created` - When new client is created (no PII logged)
    
    **Returns:**
    - `client_id`: The Core client UUID
    - `linked`: True if linked to existing client
    - `created`: True if new client was created
    - `match_type`: 'email' or 'abn' if linked, null if created
    """
    # A3-04 Debug logging - CRITICAL for deployment verification
    logger.warning(f"[A3-04] V1 ENDPOINT HIT: /api/v1/clients/link-or-create | myfdc_user_id={request.myfdc_user_id} | email_domain={request.email.split('@')[-1]} | service={service.name}")
    return await _execute_link_or_create(request, service, db)


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: str,
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a Core client by ID.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    Returns the canonical Core client record including linked system IDs.
    """
    client_service = CoreClientService(db)
    
    client = await client_service.get_by_id(client_id, service_name=service.name)
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )
    
    return ClientResponse(
        client_id=client.client_id,
        name=client.name,
        email=client.email,
        abn=client.abn,
        myfdc_user_id=client.myfdc_user_id,
        crm_client_id=client.crm_client_id,
        status=client.status
    )


@router.get("", response_model=List[ClientListItem])
async def list_clients(
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    linked_to_myfdc: Optional[bool] = Query(None, description="Filter by MyFDC link"),
    linked_to_crm: Optional[bool] = Query(None, description="Filter by CRM link"),
    limit: int = Query(100, ge=1, le=1000, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset")
):
    """
    List all Core clients.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    Returns all clients for CRM integration. Supports filtering by link status.
    """
    client_service = CoreClientService(db)
    
    clients = await client_service.list_all(
        service_name=service.name,
        status=status_filter,
        linked_to_myfdc=linked_to_myfdc,
        linked_to_crm=linked_to_crm,
        limit=limit,
        offset=offset
    )
    
    return [
        ClientListItem(
            client_id=c.client_id,
            name=c.name,
            email=c.email,
            linked_to_myfdc=c.myfdc_user_id is not None,
            linked_to_crm=c.crm_client_id is not None,
            linked_to_bookkeeping=c.bookkeeping_id is not None,
            status=c.status
        )
        for c in clients
    ]


@router.post("/{client_id}/link-crm")
async def link_crm_client(
    client_id: str,
    request: LinkCRMRequest,
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Link a CRM client ID to a Core client.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    Used by CRM to establish bidirectional linking.
    """
    client_service = CoreClientService(db)
    
    # Verify client exists
    client = await client_service.get_by_id(client_id, service_name=service.name)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )
    
    success = await client_service.link_crm_client(
        client_id=client_id,
        crm_client_id=request.crm_client_id,
        service_name=service.name
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to link CRM client"
        )
    
    return {
        "success": True,
        "client_id": client_id,
        "crm_client_id": request.crm_client_id
    }


# ==================== GOLDEN TEST CLIENT ====================

@router.get("/golden/test-client")
async def get_golden_test_client(
    service: InternalService = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the Golden Test Client for development/testing.
    
    **Auth:** Internal Service Token (X-Internal-Api-Key header)
    
    Returns the canonical test client used for integration testing.
    """
    # Look for a client with Golden Test in the name or a specific test email
    query_text = """
        SELECT id, display_name, primary_contact_email, abn,
               myfdc_user_id, crm_client_id, client_status
        FROM public.client_profiles
        WHERE LOWER(display_name) LIKE '%golden%test%'
           OR LOWER(primary_contact_email) = 'golden@test.fdctax.com'
        LIMIT 1
    """
    
    from sqlalchemy import text
    result = await db.execute(text(query_text))
    row = result.fetchone()
    
    if not row:
        # Create the Golden Test Client if it doesn't exist
        from services.clients import CoreClientService
        client_service = CoreClientService(db)
        
        client_id = await client_service._create_client(
            myfdc_user_id="golden_test_user",
            email="golden@test.fdctax.com",
            name="Golden Test Client",
            abn=None,
            phone=None,
            created_by="system"
        )
        
        return {
            "client_id": client_id,
            "name": "Golden Test Client",
            "email": "golden@test.fdctax.com",
            "created": True,
            "message": "Golden Test Client created"
        }
    
    return {
        "client_id": str(row.id),
        "name": row.display_name,
        "email": row.primary_contact_email,
        "abn": row.abn,
        "myfdc_user_id": row.myfdc_user_id,
        "crm_client_id": row.crm_client_id,
        "status": row.client_status,
        "created": False
    }
