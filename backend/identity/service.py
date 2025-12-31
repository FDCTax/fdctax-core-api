"""
Identity Spine - Service Layer

Business logic for identity management including:
- MyFDC signup (creates/links person)
- CRM client creation (creates/links person)
- Identity linking
- Duplicate detection and merging

Uses raw SQL queries for async compatibility.
"""

import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


class IdentityService:
    """
    Identity Service - Core business logic for identity management.
    
    Uses raw SQL for async compatibility with the existing database setup.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ==================== PERSON MANAGEMENT ====================
    
    async def get_person_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Find person by email (case-insensitive)."""
        query = text("""
            SELECT id, email, first_name, last_name, mobile, phone, 
                   date_of_birth, status, email_verified, mobile_verified,
                   metadata, created_at, updated_at
            FROM person
            WHERE LOWER(email) = LOWER(:email)
        """)
        result = await self.db.execute(query, {"email": email.strip()})
        row = result.fetchone()
        if not row:
            return None
        return self._row_to_person_dict(row)
    
    async def get_person_by_id(self, person_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """Find person by ID."""
        query = text("""
            SELECT id, email, first_name, last_name, mobile, phone, 
                   date_of_birth, status, email_verified, mobile_verified,
                   metadata, created_at, updated_at
            FROM person
            WHERE id = :person_id
        """)
        result = await self.db.execute(query, {"person_id": str(person_id)})
        row = result.fetchone()
        if not row:
            return None
        return self._row_to_person_dict(row)
    
    async def _check_myfdc_account_exists(self, person_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """Check if MyFDC account exists for person."""
        query = text("""
            SELECT id, person_id, username, auth_provider, last_login_at,
                   login_count, settings, preferences, onboarding_completed,
                   onboarding_step, status, created_at, updated_at
            FROM myfdc_account
            WHERE person_id = :person_id
        """)
        result = await self.db.execute(query, {"person_id": str(person_id)})
        row = result.fetchone()
        if not row:
            return None
        return self._row_to_myfdc_dict(row)
    
    async def _check_crm_client_exists(self, person_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """Check if CRM client exists for person."""
        query = text("""
            SELECT id, person_id, client_code, abn, business_name, entity_type,
                   gst_registered, gst_registration_date, tax_agent_id,
                   assigned_staff_id, source, notes, tags, custom_fields,
                   status, created_at, updated_at
            FROM crm_client_identity
            WHERE person_id = :person_id
        """)
        result = await self.db.execute(query, {"person_id": str(person_id)})
        row = result.fetchone()
        if not row:
            return None
        return self._row_to_crm_dict(row)
    
    async def _check_engagement_profile_exists(self, person_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """Check if engagement profile exists for person."""
        query = text("""
            SELECT id, person_id, is_myfdc_user, is_crm_client, has_ocr,
                   is_diy_bas_user, is_diy_itr_user, is_full_service_bas_client,
                   is_full_service_itr_client, is_bookkeeping_client, is_payroll_client,
                   subscription_tier, subscription_start_date, subscription_end_date,
                   first_engagement_at, last_engagement_at, total_interactions,
                   created_at, updated_at
            FROM engagement_profile
            WHERE person_id = :person_id
        """)
        result = await self.db.execute(query, {"person_id": str(person_id)})
        row = result.fetchone()
        if not row:
            return None
        return {
            "id": str(row[0]),
            "person_id": str(row[1]),
            "is_myfdc_user": row[2],
            "is_crm_client": row[3],
            "has_ocr": row[4],
            "is_diy_bas_user": row[5],
            "is_diy_itr_user": row[6],
            "is_full_service_bas_client": row[7],
            "is_full_service_itr_client": row[8],
            "is_bookkeeping_client": row[9],
            "is_payroll_client": row[10],
            "subscription_tier": row[11],
            "subscription_start_date": row[12].isoformat() if row[12] else None,
            "subscription_end_date": row[13].isoformat() if row[13] else None,
            "first_engagement_at": row[14].isoformat() if row[14] else None,
            "last_engagement_at": row[15].isoformat() if row[15] else None,
            "total_interactions": row[16],
            "created_at": row[17].isoformat() if row[17] else None,
            "updated_at": row[18].isoformat() if row[18] else None
        }
    
    async def create_person(
        self,
        email: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        mobile: Optional[str] = None,
        phone: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        performed_by: str = "system"
    ) -> Dict[str, Any]:
        """Create a new person record."""
        # Check if person already exists
        existing = await self.get_person_by_email(email)
        if existing:
            raise ValueError(f"Person with email {email} already exists")
        
        person_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        
        # Create person
        insert_person = text("""
            INSERT INTO person (id, email, first_name, last_name, mobile, phone, 
                               status, email_verified, mobile_verified, metadata, 
                               created_at, updated_at)
            VALUES (:id, :email, :first_name, :last_name, :mobile, :phone,
                    'active', false, false, CAST(:metadata AS jsonb), :created_at, :updated_at)
            RETURNING id
        """)
        await self.db.execute(insert_person, {
            "id": str(person_id),
            "email": email.lower().strip(),
            "first_name": first_name,
            "last_name": last_name,
            "mobile": mobile,
            "phone": phone,
            "metadata": json.dumps(metadata or {}),
            "created_at": now,
            "updated_at": now
        })
        
        # Create engagement profile
        engagement_id = uuid.uuid4()
        insert_engagement = text("""
            INSERT INTO engagement_profile (id, person_id, is_myfdc_user, is_crm_client,
                                           has_ocr, is_diy_bas_user, is_diy_itr_user,
                                           is_full_service_bas_client, is_full_service_itr_client,
                                           is_bookkeeping_client, is_payroll_client,
                                           first_engagement_at, total_interactions,
                                           created_at, updated_at)
            VALUES (:id, :person_id, false, false, false, false, false, false, false, 
                    false, false, :first_engagement_at, 0, :created_at, :updated_at)
        """)
        await self.db.execute(insert_engagement, {
            "id": str(engagement_id),
            "person_id": str(person_id),
            "first_engagement_at": now,
            "created_at": now,
            "updated_at": now
        })
        
        # Log the action
        await self._log_action(
            person_id=person_id,
            action="create",
            source_type="person",
            source_id=str(person_id),
            performed_by=performed_by,
            details={"email": email}
        )
        
        await self.db.commit()
        
        logger.info(f"Created person: {person_id} ({email})")
        return await self.get_person_by_id(person_id)
    
    async def get_or_create_person(
        self,
        email: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        mobile: Optional[str] = None,
        performed_by: str = "system"
    ) -> Tuple[Dict[str, Any], bool]:
        """Get existing person or create new one."""
        person = await self.get_person_by_email(email)
        if person:
            # Update fields if provided and person exists
            updated = False
            updates = {}
            if first_name and not person.get("first_name"):
                updates["first_name"] = first_name
                updated = True
            if last_name and not person.get("last_name"):
                updates["last_name"] = last_name
                updated = True
            if mobile and not person.get("mobile"):
                updates["mobile"] = mobile
                updated = True
            
            if updated:
                update_query = text("""
                    UPDATE person SET 
                        first_name = COALESCE(:first_name, first_name),
                        last_name = COALESCE(:last_name, last_name),
                        mobile = COALESCE(:mobile, mobile),
                        updated_at = :updated_at
                    WHERE id = :person_id
                """)
                await self.db.execute(update_query, {
                    "first_name": updates.get("first_name"),
                    "last_name": updates.get("last_name"),
                    "mobile": updates.get("mobile"),
                    "updated_at": datetime.now(timezone.utc),
                    "person_id": person["id"]
                })
                await self.db.commit()
                person = await self.get_person_by_id(uuid.UUID(person["id"]))
            
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
        """Handle MyFDC signup."""
        # Get or create person
        person, person_created = await self.get_or_create_person(
            email=email,
            first_name=first_name,
            last_name=last_name,
            mobile=mobile,
            performed_by=performed_by
        )
        
        person_id = uuid.UUID(person["id"])
        
        # Check if MyFDC account already exists
        existing_account = await self._check_myfdc_account_exists(person_id)
        if existing_account:
            return {
                "success": False,
                "error": "MyFDC account already exists for this email",
                "person": person,
                "myfdc_account": existing_account,
                "person_created": False,
                "account_created": False
            }
        
        # Create MyFDC account
        account_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        
        insert_account = text("""
            INSERT INTO myfdc_account (id, person_id, password_hash, auth_provider,
                                      auth_provider_id, settings, preferences,
                                      onboarding_completed, onboarding_step, status,
                                      login_count, created_at, updated_at)
            VALUES (:id, :person_id, :password_hash, :auth_provider, :auth_provider_id,
                    CAST(:settings AS jsonb), '{}'::jsonb, false, 0, 'active', 0, :created_at, :updated_at)
        """)
        await self.db.execute(insert_account, {
            "id": str(account_id),
            "person_id": str(person_id),
            "password_hash": password_hash,
            "auth_provider": auth_provider,
            "auth_provider_id": auth_provider_id,
            "settings": json.dumps(settings or {}),
            "created_at": now,
            "updated_at": now
        })
        
        # Update engagement profile
        update_engagement = text("""
            UPDATE engagement_profile 
            SET is_myfdc_user = true, last_engagement_at = :last_engagement_at
            WHERE person_id = :person_id
        """)
        await self.db.execute(update_engagement, {
            "person_id": str(person_id),
            "last_engagement_at": now
        })
        
        # Log the action
        await self._log_action(
            person_id=person_id,
            action="create" if person_created else "link",
            source_type="myfdc",
            source_id=str(account_id),
            target_type="person",
            target_id=str(person_id),
            performed_by=performed_by,
            details={
                "auth_provider": auth_provider,
                "person_created": person_created
            }
        )
        
        await self.db.commit()
        
        # Fetch created account
        myfdc_account = await self._check_myfdc_account_exists(person_id)
        engagement_profile = await self._check_engagement_profile_exists(person_id)
        crm_client = await self._check_crm_client_exists(person_id)
        
        logger.info(f"MyFDC signup: person={person_id}, account={account_id}, new_person={person_created}")
        
        return {
            "success": True,
            "person": person,
            "myfdc_account": myfdc_account,
            "engagement_profile": engagement_profile,
            "person_created": person_created,
            "account_created": True,
            "linked_to_crm": crm_client is not None
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
        """Handle CRM client creation."""
        # Get or create person
        person, person_created = await self.get_or_create_person(
            email=email,
            first_name=first_name,
            last_name=last_name,
            mobile=mobile,
            performed_by=performed_by
        )
        
        person_id = uuid.UUID(person["id"])
        
        # Check if CRM client already exists
        existing_client = await self._check_crm_client_exists(person_id)
        if existing_client:
            return {
                "success": False,
                "error": "CRM client already exists for this email",
                "person": person,
                "crm_client": existing_client,
                "person_created": False,
                "client_created": False
            }
        
        # Generate client code if not provided
        if not client_code:
            client_code = await self._generate_client_code()
        
        # Create CRM client
        client_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        
        insert_client = text("""
            INSERT INTO crm_client_identity (id, person_id, client_code, abn, business_name,
                                            entity_type, gst_registered, source, notes,
                                            tags, custom_fields, status, created_at, updated_at)
            VALUES (:id, :person_id, :client_code, :abn, :business_name, :entity_type,
                    :gst_registered, :source, :notes, CAST(:tags AS jsonb), CAST(:custom_fields AS jsonb), 'active',
                    :created_at, :updated_at)
        """)
        await self.db.execute(insert_client, {
            "id": str(client_id),
            "person_id": str(person_id),
            "client_code": client_code,
            "abn": abn,
            "business_name": business_name,
            "entity_type": entity_type,
            "gst_registered": gst_registered,
            "source": source,
            "notes": notes,
            "tags": json.dumps(tags or []),
            "custom_fields": json.dumps(custom_fields or {}),
            "created_at": now,
            "updated_at": now
        })
        
        # Update engagement profile
        update_engagement = text("""
            UPDATE engagement_profile 
            SET is_crm_client = true, last_engagement_at = :last_engagement_at
            WHERE person_id = :person_id
        """)
        await self.db.execute(update_engagement, {
            "person_id": str(person_id),
            "last_engagement_at": now
        })
        
        # Log the action
        await self._log_action(
            person_id=person_id,
            action="create" if person_created else "link",
            source_type="crm",
            source_id=str(client_id),
            target_type="person",
            target_id=str(person_id),
            performed_by=performed_by,
            details={
                "client_code": client_code,
                "person_created": person_created
            }
        )
        
        await self.db.commit()
        
        # Fetch created client
        crm_client = await self._check_crm_client_exists(person_id)
        engagement_profile = await self._check_engagement_profile_exists(person_id)
        myfdc_account = await self._check_myfdc_account_exists(person_id)
        
        logger.info(f"CRM client created: person={person_id}, client={client_id}, new_person={person_created}")
        
        return {
            "success": True,
            "person": person,
            "crm_client": crm_client,
            "engagement_profile": engagement_profile,
            "person_created": person_created,
            "client_created": True,
            "linked_to_myfdc": myfdc_account is not None
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
        """Link existing MyFDC and CRM records."""
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
        if source_person["id"] == target_person["id"]:
            return {
                "success": True,
                "message": "Records already linked (same person)",
                "person": source_person
            }
        
        # Merge the persons (keep the one that has CRM client or is older)
        primary_person, secondary_person = await self._determine_merge_primary(
            source_person, target_person
        )
        
        result = await self.merge_persons(
            primary_id=uuid.UUID(primary_person["id"]),
            secondary_id=uuid.UUID(secondary_person["id"]),
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
        """Merge two person records into one."""
        primary = await self.get_person_by_id(primary_id)
        secondary = await self.get_person_by_id(secondary_id)
        
        if not primary or not secondary:
            return {
                "success": False,
                "error": "One or both persons not found"
            }
        
        if primary["id"] == secondary["id"]:
            return {
                "success": False,
                "error": "Cannot merge person with itself"
            }
        
        merged_records = []
        
        # Check linked accounts
        primary_myfdc = await self._check_myfdc_account_exists(primary_id)
        secondary_myfdc = await self._check_myfdc_account_exists(secondary_id)
        primary_crm = await self._check_crm_client_exists(primary_id)
        secondary_crm = await self._check_crm_client_exists(secondary_id)
        
        # Move MyFDC account if secondary has one and primary doesn't
        if secondary_myfdc and not primary_myfdc:
            update_query = text("UPDATE myfdc_account SET person_id = :primary_id WHERE person_id = :secondary_id")
            await self.db.execute(update_query, {"primary_id": str(primary_id), "secondary_id": str(secondary_id)})
            merged_records.append("myfdc_account")
        elif secondary_myfdc:
            delete_query = text("DELETE FROM myfdc_account WHERE person_id = :secondary_id")
            await self.db.execute(delete_query, {"secondary_id": str(secondary_id)})
            merged_records.append("myfdc_account (deleted duplicate)")
        
        # Move CRM client if secondary has one and primary doesn't
        if secondary_crm and not primary_crm:
            update_query = text("UPDATE crm_client_identity SET person_id = :primary_id WHERE person_id = :secondary_id")
            await self.db.execute(update_query, {"primary_id": str(primary_id), "secondary_id": str(secondary_id)})
            merged_records.append("crm_client")
        elif secondary_crm:
            delete_query = text("DELETE FROM crm_client_identity WHERE person_id = :secondary_id")
            await self.db.execute(delete_query, {"secondary_id": str(secondary_id)})
            merged_records.append("crm_client (deleted duplicate)")
        
        # Delete secondary engagement profile
        delete_engagement = text("DELETE FROM engagement_profile WHERE person_id = :secondary_id")
        await self.db.execute(delete_engagement, {"secondary_id": str(secondary_id)})
        
        # Fill in missing fields on primary from secondary
        update_primary = text("""
            UPDATE person SET
                first_name = COALESCE(first_name, :first_name),
                last_name = COALESCE(last_name, :last_name),
                mobile = COALESCE(mobile, :mobile),
                phone = COALESCE(phone, :phone),
                updated_at = :updated_at
            WHERE id = :primary_id
        """)
        await self.db.execute(update_primary, {
            "first_name": secondary.get("first_name"),
            "last_name": secondary.get("last_name"),
            "mobile": secondary.get("mobile"),
            "phone": secondary.get("phone"),
            "updated_at": datetime.now(timezone.utc),
            "primary_id": str(primary_id)
        })
        
        # Log the merge
        await self._log_action(
            person_id=primary_id,
            action="merge",
            source_type="person",
            source_id=str(secondary_id),
            target_type="person",
            target_id=str(primary_id),
            performed_by=performed_by,
            details={
                "merged_email": secondary["email"],
                "merged_records": merged_records
            }
        )
        
        # Delete secondary person
        delete_person = text("DELETE FROM person WHERE id = :secondary_id")
        await self.db.execute(delete_person, {"secondary_id": str(secondary_id)})
        
        await self.db.commit()
        
        logger.info(f"Merged persons: {secondary_id} -> {primary_id}")
        
        updated_primary = await self.get_person_by_id(primary_id)
        
        return {
            "success": True,
            "primary_person": updated_primary,
            "merged_email": secondary["email"],
            "merged_records": merged_records
        }
    
    # ==================== ORPHAN DETECTION ====================
    
    async def list_orphaned_records(self) -> Dict[str, Any]:
        """Find orphaned MyFDC accounts and CRM clients."""
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
        
        # Find persons without any linked accounts
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
        """Find potential duplicate persons based on similar emails."""
        query = text("""
            SELECT LOWER(email) as email, COUNT(*) as count
            FROM person
            GROUP BY LOWER(email)
            HAVING COUNT(*) > 1
        """)
        result = await self.db.execute(query)
        duplicates = [{"email": r[0], "count": r[1]} for r in result.fetchall()]
        return duplicates
    
    async def update_engagement_profile(
        self,
        person_id: uuid.UUID,
        **flags
    ) -> Optional[Dict[str, Any]]:
        """Update engagement profile flags."""
        # Build dynamic update
        set_clauses = ["last_engagement_at = :last_engagement_at", "total_interactions = total_interactions + 1"]
        params = {"person_id": str(person_id), "last_engagement_at": datetime.now(timezone.utc)}
        
        for key, value in flags.items():
            if value is not None:
                set_clauses.append(f"{key} = :{key}")
                params[key] = value
        
        query = text(f"UPDATE engagement_profile SET {', '.join(set_clauses)} WHERE person_id = :person_id")
        await self.db.execute(query, params)
        await self.db.commit()
        
        return await self._check_engagement_profile_exists(person_id)
    
    # ==================== MERGE PREVIEW ====================
    
    async def merge_preview(
        self,
        person_id_a: uuid.UUID,
        person_id_b: uuid.UUID,
        performed_by: str = "system"
    ) -> Dict[str, Any]:
        """
        Generate a read-only preview of what would happen if two persons were merged.
        
        This endpoint:
        - Does NOT perform any merge operations
        - Detects conflicts between the two identities
        - Recommends merge direction
        - Logs the preview request for audit
        
        Args:
            person_id_a: First person ID
            person_id_b: Second person ID
            performed_by: Who requested the preview
            
        Returns:
            Dict with preview data, conflicts, and recommendation
        """
        # Fetch both persons
        person_a = await self.get_person_by_id(person_id_a)
        person_b = await self.get_person_by_id(person_id_b)
        
        if not person_a:
            return {
                "success": False,
                "error": f"Person A not found: {person_id_a}"
            }
        
        if not person_b:
            return {
                "success": False,
                "error": f"Person B not found: {person_id_b}"
            }
        
        if person_id_a == person_id_b:
            return {
                "success": False,
                "error": "Cannot preview merge of person with itself"
            }
        
        # Fetch linked accounts for both
        myfdc_a = await self._check_myfdc_account_exists(person_id_a)
        myfdc_b = await self._check_myfdc_account_exists(person_id_b)
        crm_a = await self._check_crm_client_exists(person_id_a)
        crm_b = await self._check_crm_client_exists(person_id_b)
        engagement_a = await self._check_engagement_profile_exists(person_id_a)
        engagement_b = await self._check_engagement_profile_exists(person_id_b)
        
        # Detect conflicts
        conflicts = []
        
        # 1. Conflicting emails (different emails)
        if person_a["email"].lower() != person_b["email"].lower():
            conflicts.append({
                "type": "conflicting_emails",
                "severity": "warning",
                "description": "Persons have different email addresses",
                "details": {
                    "email_a": person_a["email"],
                    "email_b": person_b["email"]
                }
            })
        
        # 2. Multiple MyFDC accounts
        if myfdc_a and myfdc_b:
            conflicts.append({
                "type": "multiple_myfdc_accounts",
                "severity": "high",
                "description": "Both persons have MyFDC accounts - one will be deleted",
                "details": {
                    "account_a_id": myfdc_a["id"],
                    "account_a_provider": myfdc_a["auth_provider"],
                    "account_b_id": myfdc_b["id"],
                    "account_b_provider": myfdc_b["auth_provider"]
                }
            })
        
        # 3. Multiple CRM clients
        if crm_a and crm_b:
            conflicts.append({
                "type": "multiple_crm_clients",
                "severity": "high",
                "description": "Both persons have CRM client records - one will be deleted",
                "details": {
                    "client_a_code": crm_a["client_code"],
                    "client_a_business": crm_a["business_name"],
                    "client_b_code": crm_b["client_code"],
                    "client_b_business": crm_b["business_name"]
                }
            })
        
        # 4. Mismatched service flags
        if engagement_a and engagement_b:
            mismatched_flags = []
            service_flags = [
                ("is_myfdc_user", "MyFDC User"),
                ("is_crm_client", "CRM Client"),
                ("has_ocr", "Has OCR"),
                ("is_diy_bas_user", "DIY BAS User"),
                ("is_diy_itr_user", "DIY ITR User"),
                ("is_full_service_bas_client", "Full Service BAS"),
                ("is_full_service_itr_client", "Full Service ITR"),
                ("is_bookkeeping_client", "Bookkeeping Client"),
                ("is_payroll_client", "Payroll Client")
            ]
            
            for flag_key, flag_name in service_flags:
                val_a = engagement_a.get(flag_key, False)
                val_b = engagement_b.get(flag_key, False)
                if val_a != val_b:
                    mismatched_flags.append({
                        "flag": flag_key,
                        "name": flag_name,
                        "value_a": val_a,
                        "value_b": val_b,
                        "merged_value": val_a or val_b  # OR logic in merge
                    })
            
            if mismatched_flags:
                conflicts.append({
                    "type": "mismatched_service_flags",
                    "severity": "low",
                    "description": "Service flags differ between persons (will be merged with OR logic)",
                    "details": {
                        "mismatched_flags": mismatched_flags
                    }
                })
        
        # 5. Mismatched identity sources (auth providers)
        if myfdc_a and myfdc_b:
            if myfdc_a["auth_provider"] != myfdc_b["auth_provider"]:
                conflicts.append({
                    "type": "mismatched_auth_providers",
                    "severity": "medium",
                    "description": "MyFDC accounts use different authentication providers",
                    "details": {
                        "provider_a": myfdc_a["auth_provider"],
                        "provider_b": myfdc_b["auth_provider"]
                    }
                })
        
        # 6. Check for different contact info
        contact_diffs = []
        if person_a["mobile"] and person_b["mobile"] and person_a["mobile"] != person_b["mobile"]:
            contact_diffs.append({"field": "mobile", "value_a": person_a["mobile"], "value_b": person_b["mobile"]})
        if person_a["phone"] and person_b["phone"] and person_a["phone"] != person_b["phone"]:
            contact_diffs.append({"field": "phone", "value_a": person_a["phone"], "value_b": person_b["phone"]})
        if person_a["first_name"] and person_b["first_name"] and person_a["first_name"] != person_b["first_name"]:
            contact_diffs.append({"field": "first_name", "value_a": person_a["first_name"], "value_b": person_b["first_name"]})
        if person_a["last_name"] and person_b["last_name"] and person_a["last_name"] != person_b["last_name"]:
            contact_diffs.append({"field": "last_name", "value_a": person_a["last_name"], "value_b": person_b["last_name"]})
        
        if contact_diffs:
            conflicts.append({
                "type": "different_contact_info",
                "severity": "low",
                "description": "Contact information differs (primary's values will be kept)",
                "details": {
                    "differences": contact_diffs
                }
            })
        
        # Calculate combined engagement profile (what it would look like after merge)
        combined_engagement = None
        if engagement_a or engagement_b:
            ea = engagement_a or {}
            eb = engagement_b or {}
            combined_engagement = {
                "is_myfdc_user": ea.get("is_myfdc_user", False) or eb.get("is_myfdc_user", False),
                "is_crm_client": ea.get("is_crm_client", False) or eb.get("is_crm_client", False),
                "has_ocr": ea.get("has_ocr", False) or eb.get("has_ocr", False),
                "is_diy_bas_user": ea.get("is_diy_bas_user", False) or eb.get("is_diy_bas_user", False),
                "is_diy_itr_user": ea.get("is_diy_itr_user", False) or eb.get("is_diy_itr_user", False),
                "is_full_service_bas_client": ea.get("is_full_service_bas_client", False) or eb.get("is_full_service_bas_client", False),
                "is_full_service_itr_client": ea.get("is_full_service_itr_client", False) or eb.get("is_full_service_itr_client", False),
                "is_bookkeeping_client": ea.get("is_bookkeeping_client", False) or eb.get("is_bookkeeping_client", False),
                "is_payroll_client": ea.get("is_payroll_client", False) or eb.get("is_payroll_client", False),
                "subscription_tier": ea.get("subscription_tier") or eb.get("subscription_tier"),
                "total_interactions": (ea.get("total_interactions", 0) or 0) + (eb.get("total_interactions", 0) or 0)
            }
        
        # Determine recommended merge direction
        primary, secondary = await self._determine_merge_primary(person_a, person_b)
        merge_direction = f"{secondary['id']} → {primary['id']}"
        merge_direction_reason = self._get_merge_direction_reason(
            primary, secondary, 
            myfdc_a if primary["id"] == person_a["id"] else myfdc_b,
            myfdc_b if primary["id"] == person_a["id"] else myfdc_a,
            crm_a if primary["id"] == person_a["id"] else crm_b,
            crm_b if primary["id"] == person_a["id"] else crm_a
        )
        
        # Count conflicts by severity
        conflict_summary = {
            "total": len(conflicts),
            "high": len([c for c in conflicts if c["severity"] == "high"]),
            "medium": len([c for c in conflicts if c["severity"] == "medium"]),
            "low": len([c for c in conflicts if c["severity"] == "low"]),
            "warning": len([c for c in conflicts if c["severity"] == "warning"])
        }
        
        # Log the preview request (this is the only write operation)
        await self._log_action(
            person_id=person_id_a,
            action="merge_preview",
            source_type="person",
            source_id=str(person_id_a),
            target_type="person",
            target_id=str(person_id_b),
            performed_by=performed_by,
            details={
                "conflict_count": conflict_summary["total"],
                "high_severity_conflicts": conflict_summary["high"],
                "recommended_direction": merge_direction
            }
        )
        await self.db.commit()
        
        return {
            "success": True,
            "preview": {
                "person_a": person_a,
                "person_b": person_b,
                "myfdc_account_a": myfdc_a,
                "myfdc_account_b": myfdc_b,
                "crm_client_a": crm_a,
                "crm_client_b": crm_b,
                "engagement_a": engagement_a,
                "engagement_b": engagement_b
            },
            "combined_engagement_profile": combined_engagement,
            "conflicts": conflicts,
            "conflict_summary": conflict_summary,
            "recommendation": {
                "merge_direction": merge_direction,
                "primary_person_id": primary["id"],
                "secondary_person_id": secondary["id"],
                "reason": merge_direction_reason,
                "safe_to_merge": conflict_summary["high"] == 0
            }
        }
    
    def _get_merge_direction_reason(
        self,
        primary: Dict[str, Any],
        secondary: Dict[str, Any],
        primary_myfdc: Optional[Dict],
        secondary_myfdc: Optional[Dict],
        primary_crm: Optional[Dict],
        secondary_crm: Optional[Dict]
    ) -> str:
        """Generate human-readable reason for merge direction."""
        reasons = []
        
        if primary_crm and not secondary_crm:
            reasons.append("has CRM client record")
        elif primary_crm and secondary_crm:
            reasons.append("CRM client will be kept (secondary's deleted)")
        
        if primary_myfdc and not secondary_myfdc:
            reasons.append("has MyFDC account")
        elif primary_myfdc and secondary_myfdc:
            reasons.append("MyFDC account will be kept (secondary's deleted)")
        
        if not reasons:
            reasons.append("is older record")
        
        return f"Person {primary['id'][:8]}... selected as primary because it {', '.join(reasons)}"
    
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
        person1: Dict[str, Any],
        person2: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Determine which person should be primary in a merge."""
        p1_id = uuid.UUID(person1["id"])
        p2_id = uuid.UUID(person2["id"])
        
        # Prefer person with CRM client
        p1_crm = await self._check_crm_client_exists(p1_id)
        p2_crm = await self._check_crm_client_exists(p2_id)
        
        if p1_crm and not p2_crm:
            return person1, person2
        if p2_crm and not p1_crm:
            return person2, person1
        
        # Prefer person with MyFDC account
        p1_myfdc = await self._check_myfdc_account_exists(p1_id)
        p2_myfdc = await self._check_myfdc_account_exists(p2_id)
        
        if p1_myfdc and not p2_myfdc:
            return person1, person2
        if p2_myfdc and not p1_myfdc:
            return person2, person1
        
        # Prefer older person
        p1_created = person1.get("created_at", "")
        p2_created = person2.get("created_at", "")
        if p1_created <= p2_created:
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
        log_id = uuid.uuid4()
        insert_log = text("""
            INSERT INTO identity_link_log (id, person_id, action, source_type, source_id,
                                          target_type, target_id, performed_by, details, created_at)
            VALUES (:id, :person_id, :action, :source_type, :source_id, :target_type,
                    :target_id, :performed_by, CAST(:details AS jsonb), :created_at)
        """)
        await self.db.execute(insert_log, {
            "id": str(log_id),
            "person_id": str(person_id),
            "action": action,
            "source_type": source_type,
            "source_id": source_id,
            "target_type": target_type,
            "target_id": target_id,
            "performed_by": performed_by,
            "details": json.dumps(details or {}),
            "created_at": datetime.now(timezone.utc)
        })
    
    def _row_to_person_dict(self, row) -> Dict[str, Any]:
        """Convert database row to person dict."""
        return {
            "id": str(row[0]),
            "email": row[1],
            "first_name": row[2],
            "last_name": row[3],
            "full_name": " ".join(p for p in [row[2], row[3]] if p) or row[1],
            "mobile": row[4],
            "phone": row[5],
            "date_of_birth": row[6].isoformat() if row[6] else None,
            "status": row[7],
            "email_verified": row[8],
            "mobile_verified": row[9],
            "metadata": row[10],
            "created_at": row[11].isoformat() if row[11] else None,
            "updated_at": row[12].isoformat() if row[12] else None
        }
    
    def _row_to_myfdc_dict(self, row) -> Dict[str, Any]:
        """Convert database row to MyFDC account dict."""
        return {
            "id": str(row[0]),
            "person_id": str(row[1]),
            "username": row[2],
            "auth_provider": row[3],
            "last_login_at": row[4].isoformat() if row[4] else None,
            "login_count": row[5],
            "settings": row[6],
            "preferences": row[7],
            "onboarding_completed": row[8],
            "onboarding_step": row[9],
            "status": row[10],
            "created_at": row[11].isoformat() if row[11] else None,
            "updated_at": row[12].isoformat() if row[12] else None
        }
    
    def _row_to_crm_dict(self, row) -> Dict[str, Any]:
        """Convert database row to CRM client dict."""
        return {
            "id": str(row[0]),
            "person_id": str(row[1]),
            "client_code": row[2],
            "abn": row[3],
            "business_name": row[4],
            "entity_type": row[5],
            "gst_registered": row[6],
            "gst_registration_date": row[7].isoformat() if row[7] else None,
            "tax_agent_id": row[8],
            "assigned_staff_id": str(row[9]) if row[9] else None,
            "source": row[10],
            "notes": row[11],
            "tags": row[12],
            "custom_fields": row[13],
            "status": row[14],
            "created_at": row[15].isoformat() if row[15] else None,
            "updated_at": row[16].isoformat() if row[16] else None
        }
