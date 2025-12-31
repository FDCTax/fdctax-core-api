"""
Identity Spine - Service Layer

Business logic for identity management including:
- MyFDC signup (creates/links person)
- CRM client creation (creates/links person)
- Identity linking
- Duplicate detection and merging
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, text, func
from sqlalchemy.orm import selectinload

from .models import (
    PersonDB,
    MyFDCAccountDB,
    CRMClientIdentityDB,
    EngagementProfileDB,
    IdentityLinkLogDB,
    PersonStatus
)

logger = logging.getLogger(__name__)


class IdentityService:
    """
    Identity Service - Core business logic for identity management.
    
    Ensures:
    - Single source of truth for identity (email-based)
    - No duplicate persons
    - Proper linking between MyFDC and CRM
    - Audit trail for all operations
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ==================== PERSON MANAGEMENT ====================
    
    async def get_person_by_email(self, email: str) -> Optional[PersonDB]:
        """Find person by email (case-insensitive)."""
        result = await self.db.execute(
            select(PersonDB)
            .options(
                selectinload(PersonDB.myfdc_account),
                selectinload(PersonDB.crm_client),
                selectinload(PersonDB.engagement_profile)
            )
            .where(func.lower(PersonDB.email) == email.lower().strip())
        )
        return result.scalar_one_or_none()
    
    async def get_person_by_id(self, person_id: uuid.UUID) -> Optional[PersonDB]:
        """Find person by ID."""
        result = await self.db.execute(
            select(PersonDB)
            .options(
                selectinload(PersonDB.myfdc_account),
                selectinload(PersonDB.crm_client),
                selectinload(PersonDB.engagement_profile)
            )
            .where(PersonDB.id == person_id)
        )
        return result.scalar_one_or_none()
    
    async def create_person(
        self,
        email: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        mobile: Optional[str] = None,
        phone: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        performed_by: str = "system"
    ) -> PersonDB:
        """
        Create a new person record.
        
        Args:
            email: Email address (must be unique)
            first_name: First name
            last_name: Last name
            mobile: Mobile number
            phone: Phone number
            metadata: Additional metadata
            performed_by: Who performed this action
            
        Returns:
            Created PersonDB
            
        Raises:
            ValueError: If email already exists
        """
        # Check if person already exists
        existing = await self.get_person_by_email(email)
        if existing:
            raise ValueError(f"Person with email {email} already exists")
        
        # Create person
        person = PersonDB(
            email=email.lower().strip(),
            first_name=first_name,
            last_name=last_name,
            mobile=mobile,
            phone=phone,
            extra_data=metadata or {},
            status=PersonStatus.ACTIVE.value
        )
        self.db.add(person)
        await self.db.flush()  # Ensure person.id is available
        
        # Create engagement profile
        engagement = EngagementProfileDB(
            person_id=person.id,
            first_engagement_at=datetime.now(timezone.utc)
        )
        self.db.add(engagement)
        
        # Log the action
        await self._log_action(
            person_id=person.id,
            action="create",
            source_type="person",
            source_id=str(person.id),
            performed_by=performed_by,
            details={"email": email}
        )
        
        await self.db.commit()
        await self.db.refresh(person)
        
        logger.info(f"Created person: {person.id} ({email})")
        return person
    
    async def get_or_create_person(
        self,
        email: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        mobile: Optional[str] = None,
        performed_by: str = "system"
    ) -> Tuple[PersonDB, bool]:
        """
        Get existing person or create new one.
        
        Returns:
            Tuple of (PersonDB, created: bool)
        """
        person = await self.get_person_by_email(email)
        if person:
            # Update fields if provided and person exists
            updated = False
            if first_name and not person.first_name:
                person.first_name = first_name
                updated = True
            if last_name and not person.last_name:
                person.last_name = last_name
                updated = True
            if mobile and not person.mobile:
                person.mobile = mobile
                updated = True
            
            if updated:
                await self.db.commit()
                await self.db.refresh(person)
            
            return person, False
        
        person = await self.create_person(
            email=email,
            first_name=first_name,
            last_name=last_name,
            mobile=mobile,
            performed_by=performed_by
        )
        return person, True
    
    # ==================== MYFDC SIGNUP ====================
    
    async def myfdc_signup(
        self,
        email: str,
        password_hash: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        mobile: Optional[str] = None,
        auth_provider: str = "local",
        auth_provider_id: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
        performed_by: str = "myfdc_signup"
    ) -> Dict[str, Any]:
        """
        Handle MyFDC signup.
        
        Rules:
        - If email exists, link to existing person
        - If person has no MyFDC account, create one
        - Never create duplicate persons
        
        Args:
            email: User email
            password_hash: Hashed password (for local auth)
            first_name: First name
            last_name: Last name
            mobile: Mobile number
            auth_provider: Auth provider (local, google, etc.)
            auth_provider_id: Provider-specific ID
            settings: Account settings
            performed_by: Who performed this action
            
        Returns:
            Dict with person, myfdc_account, created flags
        """
        # Get or create person
        person, person_created = await self.get_or_create_person(
            email=email,
            first_name=first_name,
            last_name=last_name,
            mobile=mobile,
            performed_by=performed_by
        )
        
        # Check if MyFDC account already exists
        if person.myfdc_account:
            return {
                "success": False,
                "error": "MyFDC account already exists for this email",
                "person": person.to_dict(),
                "myfdc_account": person.myfdc_account.to_dict(),
                "person_created": False,
                "account_created": False
            }
        
        # Create MyFDC account
        myfdc_account = MyFDCAccountDB(
            person_id=person.id,
            password_hash=password_hash,
            auth_provider=auth_provider,
            auth_provider_id=auth_provider_id,
            settings=settings or {},
            status="active"
        )
        self.db.add(myfdc_account)
        
        # Update engagement profile
        if person.engagement_profile:
            person.engagement_profile.is_myfdc_user = True
            person.engagement_profile.last_engagement_at = datetime.now(timezone.utc)
        
        # Log the action
        await self._log_action(
            person_id=person.id,
            action="create" if person_created else "link",
            source_type="myfdc",
            source_id=str(myfdc_account.id),
            target_type="person",
            target_id=str(person.id),
            performed_by=performed_by,
            details={
                "auth_provider": auth_provider,
                "person_created": person_created
            }
        )
        
        await self.db.commit()
        await self.db.refresh(person)
        await self.db.refresh(myfdc_account)
        
        logger.info(f"MyFDC signup: person={person.id}, account={myfdc_account.id}, new_person={person_created}")
        
        return {
            "success": True,
            "person": person.to_dict(),
            "myfdc_account": myfdc_account.to_dict(),
            "engagement_profile": person.engagement_profile.to_dict() if person.engagement_profile else None,
            "person_created": person_created,
            "account_created": True,
            "linked_to_crm": person.crm_client is not None
        }
    
    # ==================== CRM CLIENT CREATE ====================
    
    async def crm_client_create(
        self,
        email: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        mobile: Optional[str] = None,
        client_code: Optional[str] = None,
        abn: Optional[str] = None,
        business_name: Optional[str] = None,
        entity_type: Optional[str] = None,
        gst_registered: bool = False,
        source: Optional[str] = None,
        notes: Optional[str] = None,
        tags: Optional[List[str]] = None,
        custom_fields: Optional[Dict[str, Any]] = None,
        performed_by: str = "crm_create"
    ) -> Dict[str, Any]:
        """
        Handle CRM client creation.
        
        Rules:
        - If email exists, link to existing person
        - If person has no CRM client, create one
        - Never create duplicate persons
        
        Args:
            email: Client email
            first_name: First name
            last_name: Last name
            mobile: Mobile number
            client_code: External client reference
            abn: ABN
            business_name: Business name
            entity_type: Entity type (individual, company, etc.)
            gst_registered: GST registration status
            source: Lead source
            notes: Notes
            tags: Tags list
            custom_fields: Custom fields
            performed_by: Who performed this action
            
        Returns:
            Dict with person, crm_client, created flags
        """
        # Get or create person
        person, person_created = await self.get_or_create_person(
            email=email,
            first_name=first_name,
            last_name=last_name,
            mobile=mobile,
            performed_by=performed_by
        )
        
        # Check if CRM client already exists
        if person.crm_client:
            return {
                "success": False,
                "error": "CRM client already exists for this email",
                "person": person.to_dict(),
                "crm_client": person.crm_client.to_dict(),
                "person_created": False,
                "client_created": False
            }
        
        # Generate client code if not provided
        if not client_code:
            client_code = await self._generate_client_code()
        
        # Create CRM client
        crm_client = CRMClientIdentityDB(
            person_id=person.id,
            client_code=client_code,
            abn=abn,
            business_name=business_name,
            entity_type=entity_type,
            gst_registered=gst_registered,
            source=source,
            notes=notes,
            tags=tags or [],
            custom_fields=custom_fields or {},
            status="active"
        )
        self.db.add(crm_client)
        
        # Update engagement profile
        if person.engagement_profile:
            person.engagement_profile.is_crm_client = True
            person.engagement_profile.last_engagement_at = datetime.now(timezone.utc)
        
        # Log the action
        await self._log_action(
            person_id=person.id,
            action="create" if person_created else "link",
            source_type="crm",
            source_id=str(crm_client.id),
            target_type="person",
            target_id=str(person.id),
            performed_by=performed_by,
            details={
                "client_code": client_code,
                "person_created": person_created
            }
        )
        
        await self.db.commit()
        await self.db.refresh(person)
        await self.db.refresh(crm_client)
        
        logger.info(f"CRM client created: person={person.id}, client={crm_client.id}, new_person={person_created}")
        
        return {
            "success": True,
            "person": person.to_dict(),
            "crm_client": crm_client.to_dict(),
            "engagement_profile": person.engagement_profile.to_dict() if person.engagement_profile else None,
            "person_created": person_created,
            "client_created": True,
            "linked_to_myfdc": person.myfdc_account is not None
        }
    
    # ==================== LINK EXISTING ====================
    
    async def link_existing(
        self,
        source_type: str,
        source_email: str,
        target_type: str,
        target_email: str,
        performed_by: str = "admin"
    ) -> Dict[str, Any]:
        """
        Link existing MyFDC and CRM records.
        
        If the emails match, this is automatic. If they don't,
        we merge the persons and link the accounts.
        
        Args:
            source_type: "myfdc" or "crm"
            source_email: Email of source record
            target_type: "myfdc" or "crm"
            target_email: Email of target record
            performed_by: Who performed this action
            
        Returns:
            Dict with linking result
        """
        # Get source person
        source_person = await self.get_person_by_email(source_email)
        if not source_person:
            return {
                "success": False,
                "error": f"No person found with email: {source_email}"
            }
        
        # Get target person
        target_person = await self.get_person_by_email(target_email)
        if not target_person:
            return {
                "success": False,
                "error": f"No person found with email: {target_email}"
            }
        
        # If same person, no linking needed
        if source_person.id == target_person.id:
            return {
                "success": True,
                "message": "Records already linked (same person)",
                "person": source_person.to_dict()
            }
        
        # Merge the persons (keep the one that has CRM client or is older)
        primary_person, secondary_person = await self._determine_merge_primary(
            source_person, target_person
        )
        
        result = await self.merge_persons(
            primary_id=primary_person.id,
            secondary_id=secondary_person.id,
            performed_by=performed_by
        )
        
        return result
    
    # ==================== MERGE PERSONS ====================
    
    async def merge_persons(
        self,
        primary_id: uuid.UUID,
        secondary_id: uuid.UUID,
        performed_by: str = "admin"
    ) -> Dict[str, Any]:
        """
        Merge two person records into one.
        
        The primary person is kept, and secondary's linked records
        are moved to primary.
        
        Args:
            primary_id: ID of person to keep
            secondary_id: ID of person to merge into primary
            performed_by: Who performed this action
            
        Returns:
            Dict with merge result
        """
        primary = await self.get_person_by_id(primary_id)
        secondary = await self.get_person_by_id(secondary_id)
        
        if not primary or not secondary:
            return {
                "success": False,
                "error": "One or both persons not found"
            }
        
        if primary.id == secondary.id:
            return {
                "success": False,
                "error": "Cannot merge person with itself"
            }
        
        merged_records = []
        
        # Move MyFDC account if secondary has one and primary doesn't
        if secondary.myfdc_account and not primary.myfdc_account:
            secondary.myfdc_account.person_id = primary.id
            merged_records.append("myfdc_account")
        elif secondary.myfdc_account:
            # Delete secondary's account if primary already has one
            await self.db.delete(secondary.myfdc_account)
            merged_records.append("myfdc_account (deleted duplicate)")
        
        # Move CRM client if secondary has one and primary doesn't
        if secondary.crm_client and not primary.crm_client:
            secondary.crm_client.person_id = primary.id
            merged_records.append("crm_client")
        elif secondary.crm_client:
            # Delete secondary's client if primary already has one
            await self.db.delete(secondary.crm_client)
            merged_records.append("crm_client (deleted duplicate)")
        
        # Merge engagement profiles
        if secondary.engagement_profile and primary.engagement_profile:
            # Merge flags (OR logic)
            primary.engagement_profile.is_myfdc_user = (
                primary.engagement_profile.is_myfdc_user or 
                secondary.engagement_profile.is_myfdc_user
            )
            primary.engagement_profile.is_crm_client = (
                primary.engagement_profile.is_crm_client or 
                secondary.engagement_profile.is_crm_client
            )
            primary.engagement_profile.has_ocr = (
                primary.engagement_profile.has_ocr or 
                secondary.engagement_profile.has_ocr
            )
            # ... merge other flags
            await self.db.delete(secondary.engagement_profile)
            merged_records.append("engagement_profile")
        elif secondary.engagement_profile:
            secondary.engagement_profile.person_id = primary.id
            merged_records.append("engagement_profile")
        
        # Fill in missing fields on primary from secondary
        if not primary.first_name and secondary.first_name:
            primary.first_name = secondary.first_name
        if not primary.last_name and secondary.last_name:
            primary.last_name = secondary.last_name
        if not primary.mobile and secondary.mobile:
            primary.mobile = secondary.mobile
        if not primary.phone and secondary.phone:
            primary.phone = secondary.phone
        
        # Log the merge
        await self._log_action(
            person_id=primary.id,
            action="merge",
            source_type="person",
            source_id=str(secondary.id),
            target_type="person",
            target_id=str(primary.id),
            performed_by=performed_by,
            details={
                "merged_email": secondary.email,
                "merged_records": merged_records
            }
        )
        
        # Delete secondary person
        await self.db.delete(secondary)
        
        await self.db.commit()
        await self.db.refresh(primary)
        
        logger.info(f"Merged persons: {secondary.id} -> {primary.id}")
        
        return {
            "success": True,
            "primary_person": primary.to_dict(),
            "merged_email": secondary.email,
            "merged_records": merged_records
        }
    
    # ==================== ORPHAN DETECTION ====================
    
    async def list_orphaned_records(self) -> Dict[str, Any]:
        """
        Find orphaned MyFDC accounts and CRM clients.
        
        Orphaned = linked to a person that has been deleted or
        has no valid email.
        
        Returns:
            Dict with orphaned myfdc_accounts and crm_clients
        """
        # Find MyFDC accounts without valid person
        orphaned_myfdc_query = text("""
            SELECT m.id, m.person_id, m.created_at
            FROM myfdc_account m
            LEFT JOIN person p ON m.person_id = p.id
            WHERE p.id IS NULL OR p.status = 'deleted'
        """)
        result = await self.db.execute(orphaned_myfdc_query)
        orphaned_myfdc = [
            {"id": str(r[0]), "person_id": str(r[1]) if r[1] else None, "created_at": r[2].isoformat() if r[2] else None}
            for r in result.fetchall()
        ]
        
        # Find CRM clients without valid person
        orphaned_crm_query = text("""
            SELECT c.id, c.person_id, c.client_code, c.created_at
            FROM crm_client_identity c
            LEFT JOIN person p ON c.person_id = p.id
            WHERE p.id IS NULL OR p.status = 'deleted'
        """)
        result = await self.db.execute(orphaned_crm_query)
        orphaned_crm = [
            {"id": str(r[0]), "person_id": str(r[1]) if r[1] else None, "client_code": r[2], "created_at": r[3].isoformat() if r[3] else None}
            for r in result.fetchall()
        ]
        
        # Find persons without any linked accounts (potential cleanup)
        unlinked_persons_query = text("""
            SELECT p.id, p.email, p.created_at
            FROM person p
            LEFT JOIN myfdc_account m ON p.id = m.person_id
            LEFT JOIN crm_client_identity c ON p.id = c.person_id
            WHERE m.id IS NULL AND c.id IS NULL
        """)
        result = await self.db.execute(unlinked_persons_query)
        unlinked_persons = [
            {"id": str(r[0]), "email": r[1], "created_at": r[2].isoformat() if r[2] else None}
            for r in result.fetchall()
        ]
        
        return {
            "orphaned_myfdc_accounts": orphaned_myfdc,
            "orphaned_crm_clients": orphaned_crm,
            "unlinked_persons": unlinked_persons,
            "counts": {
                "orphaned_myfdc": len(orphaned_myfdc),
                "orphaned_crm": len(orphaned_crm),
                "unlinked_persons": len(unlinked_persons)
            }
        }
    
    async def find_duplicate_emails(self) -> List[Dict[str, Any]]:
        """
        Find potential duplicate persons based on similar emails.
        
        Returns:
            List of potential duplicates
        """
        # This shouldn't happen with unique constraint, but check anyway
        query = text("""
            SELECT email, COUNT(*) as count
            FROM person
            GROUP BY LOWER(email)
            HAVING COUNT(*) > 1
        """)
        result = await self.db.execute(query)
        duplicates = [{"email": r[0], "count": r[1]} for r in result.fetchall()]
        
        return duplicates
    
    # ==================== HELPER METHODS ====================
    
    async def _generate_client_code(self) -> str:
        """Generate unique client code."""
        query = text("""
            SELECT MAX(CAST(SUBSTRING(client_code FROM 8) AS INTEGER))
            FROM crm_client_identity
            WHERE client_code LIKE 'CLIENT-%'
        """)
        result = await self.db.execute(query)
        max_num = result.scalar() or 0
        return f"CLIENT-{max_num + 1:06d}"
    
    async def _determine_merge_primary(
        self,
        person1: PersonDB,
        person2: PersonDB
    ) -> Tuple[PersonDB, PersonDB]:
        """
        Determine which person should be primary in a merge.
        
        Priority:
        1. Person with CRM client
        2. Person with MyFDC account
        3. Older person (by created_at)
        """
        # Prefer person with CRM client
        if person1.crm_client and not person2.crm_client:
            return person1, person2
        if person2.crm_client and not person1.crm_client:
            return person2, person1
        
        # Prefer person with MyFDC account
        if person1.myfdc_account and not person2.myfdc_account:
            return person1, person2
        if person2.myfdc_account and not person1.myfdc_account:
            return person2, person1
        
        # Prefer older person
        if person1.created_at <= person2.created_at:
            return person1, person2
        return person2, person1
    
    async def _log_action(
        self,
        person_id: uuid.UUID,
        action: str,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        performed_by: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log an identity action."""
        log = IdentityLinkLogDB(
            person_id=person_id,
            action=action,
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            performed_by=performed_by,
            details=details or {}
        )
        self.db.add(log)
    
    async def update_engagement_profile(
        self,
        person_id: uuid.UUID,
        **flags
    ) -> Optional[EngagementProfileDB]:
        """Update engagement profile flags."""
        result = await self.db.execute(
            select(EngagementProfileDB).where(EngagementProfileDB.person_id == person_id)
        )
        profile = result.scalar_one_or_none()
        
        if not profile:
            return None
        
        for key, value in flags.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        
        profile.last_engagement_at = datetime.now(timezone.utc)
        profile.total_interactions += 1
        
        await self.db.commit()
        await self.db.refresh(profile)
        
        return profile
