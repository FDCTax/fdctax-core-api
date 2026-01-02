"""
Core Client Service

Provides unified client management for MyFDC, CRM, Bookkeeping, and Workpapers.
Establishes Core as the canonical client authority.

Key Features:
- Link or create clients from MyFDC
- Deduplicate by email or ABN
- Audit logging for all client operations
- No sensitive data (TFN, ABN) in logs

Security:
- Internal service token authentication required
- All operations logged for audit trail
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from utils.encryption import EncryptionService, log_sensitive_access

logger = logging.getLogger(__name__)


# ==================== AUDIT EVENTS ====================

class ClientAuditEvent:
    """
    Audit event types for client operations.
    
    Ticket A3-8: Uses dot notation format for event types.
    """
    CLIENT_LINKED = "client.linked"
    CLIENT_CREATED = "client.created"
    CLIENT_LOOKUP = "client.lookup"
    CLIENT_LIST = "client.list"
    CLIENT_UPDATED = "client.updated"
    CRM_LINKED = "client.crm_linked"
    MERGE_PERFORMED = "merge.performed"  # A3-12: Client merge operation


def log_client_event(
    event_type: str,
    client_id: Optional[str],
    service_name: str,
    details: Dict[str, Any],
    success: bool = True
):
    """
    Log client operation for audit trail.
    
    SECURITY (Ticket A3-8): Never logs plaintext TFN, ABN, email, phone, or bank details.
    Only logs:
    - client_id (UUID)
    - myfdc_user_id (external ID)
    - match_type (email/abn, not actual values)
    - operation metadata
    """
    # Sanitize details - remove ALL sensitive PII fields
    pii_fields = ('tfn', 'bank_account', 'bank_bsb', 'email', 'phone', 
                  'name', 'address', 'date_of_birth', 'full_email')
    safe_details = {k: v for k, v in details.items() if k not in pii_fields}
    
    # Mask ABN if present (show last 4 only)
    if 'abn' in safe_details and safe_details['abn']:
        abn = str(safe_details['abn'])
        safe_details['abn'] = f"***{abn[-4:]}" if len(abn) > 4 else "****"
    
    log_entry = {
        "event": event_type,
        "client_id": client_id,
        "service": service_name,
        "details": safe_details,
        "success": success,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    if success:
        logger.info(f"Client event: {event_type} for client {client_id} by {service_name}", extra=log_entry)
    else:
        logger.warning(f"Client event FAILED: {event_type} for client {client_id} by {service_name}", extra=log_entry)


# ==================== DATA MODELS ====================

@dataclass
class CoreClient:
    """Core client record - canonical source of truth."""
    client_id: str
    name: str
    email: str
    abn: Optional[str] = None
    phone: Optional[str] = None
    
    # Linked system IDs
    myfdc_user_id: Optional[str] = None
    crm_client_id: Optional[str] = None
    bookkeeping_id: Optional[str] = None
    workpaper_id: Optional[str] = None
    
    # Status
    status: str = "active"
    entity_type: str = "individual"
    
    # Metadata
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON response."""
        return {
            "client_id": self.client_id,
            "name": self.name,
            "email": self.email,
            "abn": self.abn,
            "phone": self.phone,
            "myfdc_user_id": self.myfdc_user_id,
            "crm_client_id": self.crm_client_id,
            "bookkeeping_id": self.bookkeeping_id,
            "workpaper_id": self.workpaper_id,
            "status": self.status,
            "entity_type": self.entity_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
    
    def to_list_dict(self) -> Dict[str, Any]:
        """Compact dictionary for list responses."""
        return {
            "client_id": self.client_id,
            "name": self.name,
            "email": self.email,
            "linked_to_myfdc": self.myfdc_user_id is not None,
            "linked_to_crm": self.crm_client_id is not None,
            "linked_to_bookkeeping": self.bookkeeping_id is not None,
            "status": self.status
        }


@dataclass
class LinkOrCreateResult:
    """Result of link-or-create operation."""
    client_id: str
    linked: bool
    created: bool
    match_type: Optional[str] = None  # 'email', 'abn', or None if created
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "client_id": self.client_id,
            "linked": self.linked,
            "created": self.created,
            "match_type": self.match_type
        }


@dataclass
class MergeResult:
    """
    Result of merge operation (Ticket A3-12).
    
    Merge unifies two client records into one, preserving target as canonical.
    """
    merged_client_id: str
    source_client_id: str
    target_client_id: str
    records_moved: Dict[str, int]  # Count of moved records per table
    references_updated: Dict[str, int]  # Count of updated references
    success: bool
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "merged_client_id": self.merged_client_id,
            "source_client_id": self.source_client_id,
            "target_client_id": self.target_client_id,
            "records_moved": self.records_moved,
            "references_updated": self.references_updated,
            "success": self.success,
            "error": self.error
        }


# ==================== CLIENT SERVICE ====================

class CoreClientService:
    """
    Core Client Service - Canonical client authority.
    
    Provides:
    - Link or create clients
    - Deduplication by email/ABN
    - Client lookup and listing
    - Integration with MyFDC, CRM, Bookkeeping, Workpapers
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def link_or_create(
        self,
        myfdc_user_id: str,
        email: str,
        name: str,
        abn: Optional[str] = None,
        phone: Optional[str] = None,
        service_name: str = "myfdc"
    ) -> LinkOrCreateResult:
        """
        Link a MyFDC user to an existing Core client, or create a new one.
        
        Deduplication Logic:
        1. Check for existing client with matching email
        2. Check for existing client with matching ABN
        3. If no match, create new client
        
        Args:
            myfdc_user_id: MyFDC user ID to link
            email: User email
            name: User name
            abn: Optional ABN
            phone: Optional phone
            service_name: Calling service for audit
            
        Returns:
            LinkOrCreateResult with client_id and operation type
        """
        email = email.lower().strip()
        
        # Step 1: Check for existing client by email
        existing = await self._find_by_email(email)
        if existing:
            # Link MyFDC user to existing client
            await self._link_myfdc_user(existing['id'], myfdc_user_id)
            
            log_client_event(
                ClientAuditEvent.CLIENT_LINKED,
                existing['id'],
                service_name,
                {"myfdc_user_id": myfdc_user_id, "match_type": "email", "email_domain": email.split('@')[-1]}
            )
            
            return LinkOrCreateResult(
                client_id=existing['id'],
                linked=True,
                created=False,
                match_type="email"
            )
        
        # Step 2: Check for existing client by ABN
        if abn:
            clean_abn = abn.replace(' ', '').replace('-', '')
            existing = await self._find_by_abn(clean_abn)
            if existing:
                # Link MyFDC user to existing client
                await self._link_myfdc_user(existing['id'], myfdc_user_id)
                
                log_client_event(
                    ClientAuditEvent.CLIENT_LINKED,
                    existing['id'],
                    service_name,
                    {"myfdc_user_id": myfdc_user_id, "match_type": "abn"}
                )
                
                return LinkOrCreateResult(
                    client_id=existing['id'],
                    linked=True,
                    created=False,
                    match_type="abn"
                )
        
        # Step 3: Create new client
        client_id = await self._create_client(
            myfdc_user_id=myfdc_user_id,
            email=email,
            name=name,
            abn=abn,
            phone=phone,
            created_by=service_name
        )
        
        log_client_event(
            ClientAuditEvent.CLIENT_CREATED,
            client_id,
            service_name,
            {"myfdc_user_id": myfdc_user_id, "email_domain": email.split('@')[-1]}
        )
        
        return LinkOrCreateResult(
            client_id=client_id,
            linked=False,
            created=True,
            match_type=None
        )
    
    async def get_by_id(self, client_id: str, service_name: str = "api") -> Optional[CoreClient]:
        """
        Get client by ID.
        
        Args:
            client_id: Client UUID
            service_name: Calling service for audit
            
        Returns:
            CoreClient or None if not found
        """
        query = text("""
            SELECT 
                id, display_name, primary_contact_email, abn, 
                primary_contact_phone, myfdc_user_id, crm_client_id,
                bookkeeping_id, workpaper_id, client_status, entity_type,
                created_at, updated_at
            FROM public.client_profiles
            WHERE id = :client_id
        """)
        
        try:
            result = await self.db.execute(query, {'client_id': client_id})
            row = result.fetchone()
            
            if not row:
                log_client_event(
                    ClientAuditEvent.CLIENT_LOOKUP,
                    client_id,
                    service_name,
                    {"found": False},
                    success=False
                )
                return None
            
            client = CoreClient(
                client_id=str(row.id),
                name=row.display_name or "",
                email=row.primary_contact_email or "",
                abn=row.abn,
                phone=row.primary_contact_phone,
                myfdc_user_id=row.myfdc_user_id,
                crm_client_id=str(row.crm_client_id) if row.crm_client_id else None,
                bookkeeping_id=str(row.bookkeeping_id) if row.bookkeeping_id else None,
                workpaper_id=str(row.workpaper_id) if row.workpaper_id else None,
                status=row.client_status or "active",
                entity_type=row.entity_type or "individual",
                created_at=row.created_at,
                updated_at=row.updated_at
            )
            
            log_client_event(
                ClientAuditEvent.CLIENT_LOOKUP,
                client_id,
                service_name,
                {"found": True}
            )
            
            return client
            
        except Exception as e:
            logger.error(f"Error fetching client {client_id}: {e}")
            return None
    
    async def list_all(
        self,
        service_name: str = "api",
        status: Optional[str] = None,
        linked_to_myfdc: Optional[bool] = None,
        linked_to_crm: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[CoreClient]:
        """
        List all Core clients.
        
        Args:
            service_name: Calling service for audit
            status: Filter by status
            linked_to_myfdc: Filter by MyFDC link status
            linked_to_crm: Filter by CRM link status
            limit: Max results
            offset: Pagination offset
            
        Returns:
            List of CoreClient objects
        """
        where_clauses = ["1=1"]
        params = {"limit": limit, "offset": offset}
        
        if status:
            where_clauses.append("client_status = :status")
            params["status"] = status
        
        if linked_to_myfdc is not None:
            if linked_to_myfdc:
                where_clauses.append("myfdc_user_id IS NOT NULL")
            else:
                where_clauses.append("myfdc_user_id IS NULL")
        
        if linked_to_crm is not None:
            if linked_to_crm:
                where_clauses.append("crm_client_id IS NOT NULL")
            else:
                where_clauses.append("crm_client_id IS NULL")
        
        where_sql = " AND ".join(where_clauses)
        
        query = text(f"""
            SELECT 
                id, display_name, primary_contact_email, abn,
                primary_contact_phone, myfdc_user_id, crm_client_id,
                bookkeeping_id, workpaper_id, client_status, entity_type,
                created_at, updated_at
            FROM public.client_profiles
            WHERE {where_sql}
            ORDER BY display_name ASC
            LIMIT :limit OFFSET :offset
        """)
        
        try:
            result = await self.db.execute(query, params)
            rows = result.fetchall()
            
            clients = [
                CoreClient(
                    client_id=str(row.id),
                    name=row.display_name or "",
                    email=row.primary_contact_email or "",
                    abn=row.abn,
                    phone=row.primary_contact_phone,
                    myfdc_user_id=row.myfdc_user_id,
                    crm_client_id=str(row.crm_client_id) if row.crm_client_id else None,
                    bookkeeping_id=str(row.bookkeeping_id) if row.bookkeeping_id else None,
                    workpaper_id=str(row.workpaper_id) if row.workpaper_id else None,
                    status=row.client_status or "active",
                    entity_type=row.entity_type or "individual",
                    created_at=row.created_at,
                    updated_at=row.updated_at
                )
                for row in rows
            ]
            
            log_client_event(
                ClientAuditEvent.CLIENT_LIST,
                None,
                service_name,
                {"count": len(clients), "filters": {"status": status, "linked_to_myfdc": linked_to_myfdc}}
            )
            
            return clients
            
        except Exception as e:
            logger.error(f"Error listing clients: {e}")
            return []
    
    async def link_crm_client(
        self,
        client_id: str,
        crm_client_id: str,
        service_name: str = "crm"
    ) -> bool:
        """Link a CRM client ID to a Core client."""
        query = text("""
            UPDATE public.client_profiles
            SET crm_client_id = :crm_client_id,
                updated_at = :updated_at
            WHERE id = :client_id
        """)
        
        try:
            await self.db.execute(query, {
                'client_id': client_id,
                'crm_client_id': crm_client_id,
                'updated_at': datetime.now(timezone.utc)
            })
            await self.db.commit()
            
            log_client_event(
                ClientAuditEvent.CRM_LINKED,
                client_id,
                service_name,
                {"crm_client_id": crm_client_id, "link_type": "crm"}
            )
            
            return True
        except Exception as e:
            logger.error(f"Error linking CRM client: {e}")
            await self.db.rollback()
            return False
    
    # ==================== PRIVATE METHODS ====================
    
    async def _find_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Find client by email."""
        query = text("""
            SELECT id, display_name, primary_contact_email, myfdc_user_id
            FROM public.client_profiles
            WHERE LOWER(primary_contact_email) = LOWER(:email)
            AND client_status != 'archived'
            LIMIT 1
        """)
        
        result = await self.db.execute(query, {'email': email})
        row = result.fetchone()
        
        if row:
            return {'id': str(row.id), 'name': row.display_name, 'email': row.primary_contact_email}
        return None
    
    async def _find_by_abn(self, abn: str) -> Optional[Dict[str, Any]]:
        """Find client by ABN."""
        query = text("""
            SELECT id, display_name, primary_contact_email, abn
            FROM public.client_profiles
            WHERE REPLACE(REPLACE(abn, ' ', ''), '-', '') = :abn
            AND client_status != 'archived'
            LIMIT 1
        """)
        
        result = await self.db.execute(query, {'abn': abn})
        row = result.fetchone()
        
        if row:
            return {'id': str(row.id), 'name': row.display_name, 'abn': row.abn}
        return None
    
    async def _link_myfdc_user(self, client_id: str, myfdc_user_id: str) -> bool:
        """Link a MyFDC user ID to a client."""
        query = text("""
            UPDATE public.client_profiles
            SET myfdc_user_id = :myfdc_user_id,
                myfdc_linked = true,
                updated_at = :updated_at
            WHERE id = :client_id
        """)
        
        try:
            await self.db.execute(query, {
                'client_id': client_id,
                'myfdc_user_id': myfdc_user_id,
                'updated_at': datetime.now(timezone.utc)
            })
            await self.db.commit()
            return True
        except Exception as e:
            logger.error(f"Error linking MyFDC user: {e}")
            await self.db.rollback()
            return False
    
    async def _create_client(
        self,
        myfdc_user_id: str,
        email: str,
        name: str,
        abn: Optional[str] = None,
        phone: Optional[str] = None,
        created_by: str = "system"
    ) -> str:
        """Create a new client record."""
        client_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Generate client code
        client_code = f"MYF-{client_id[:8].upper()}"
        
        query = text("""
            INSERT INTO public.client_profiles (
                id, client_code, display_name, primary_contact_email,
                abn, primary_contact_phone, myfdc_user_id, myfdc_linked,
                client_status, entity_type, source_system,
                created_at, updated_at, created_by
            ) VALUES (
                :id, :client_code, :display_name, :email,
                :abn, :phone, :myfdc_user_id, true,
                'active', 'individual', 'myfdc',
                :created_at, :updated_at, :created_by
            )
        """)
        
        try:
            await self.db.execute(query, {
                'id': client_id,
                'client_code': client_code,
                'display_name': name,
                'email': email,
                'abn': abn,
                'phone': phone,
                'myfdc_user_id': myfdc_user_id,
                'created_at': now,
                'updated_at': now,
                'created_by': created_by
            })
            await self.db.commit()
            
            return client_id
            
        except Exception as e:
            logger.error(f"Error creating client: {e}")
            await self.db.rollback()
            raise
