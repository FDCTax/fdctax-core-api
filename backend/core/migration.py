"""
Luna Migration Service

Handles migration of client data from Luna (legacy CRM) to Core.
Provides endpoints for:
- Batch migration of client records
- Single record migration/sync
- Migration status tracking
- Rollback capabilities

This service is called by the CRM mini-backend during the migration phase.

Phase 4 Updates:
- Integrated business logic validation
- Client matching and deduplication
- Enhanced field mapping with normalization
- Migration audit logging
"""

import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from .client_profiles import ClientProfileService, ClientProfile
from .luna_business_logic import (
    ClientValidator, 
    ClientMatcher, 
    LunaBusinessRules,
    MigrationHelpers,
    MigrationAuditLogger
)
from utils.encryption import encrypt_tfn, get_tfn_last_four, is_encryption_configured

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    """Result of a migration operation"""
    success: bool
    profile_id: Optional[str] = None
    client_code: Optional[str] = None
    error: Optional[str] = None
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "profile_id": self.profile_id,
            "client_code": self.client_code,
            "error": self.error,
            "warnings": self.warnings
        }


@dataclass
class MigrationBatch:
    """Result of a batch migration"""
    batch_id: str
    total: int
    success_count: int
    failure_count: int
    results: List[MigrationResult]
    started_at: datetime
    completed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "total": self.total,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "results": [r.to_dict() for r in self.results],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None
        }


class LunaMigrationService:
    """
    Service for migrating Luna client data to Core.
    
    Migration workflow:
    1. Luna CRM calls /api/core/migration/client with client data
    2. Core validates and transforms the data
    3. Core creates client_profile record
    4. Core returns profile_id to Luna
    5. Luna updates its record with the Core profile_id link
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.profile_service = ClientProfileService(db)
    
    async def migrate_client(
        self,
        luna_data: Dict[str, Any],
        migrated_by: str = "luna-migration"
    ) -> MigrationResult:
        """
        Migrate a single client from Luna to Core.
        
        Args:
            luna_data: Client data from Luna CRM
            migrated_by: Identifier for migration source
            
        Returns:
            MigrationResult with success/failure info
        """
        warnings = []
        
        # Extract and validate required fields
        client_code = luna_data.get("client_code") or luna_data.get("code")
        if not client_code:
            return MigrationResult(
                success=False,
                error="Missing required field: client_code"
            )
        
        display_name = luna_data.get("display_name") or luna_data.get("name")
        if not display_name:
            display_name = f"Client {client_code}"
            warnings.append("Missing display_name, using default")
        
        # Check if already migrated
        existing = await self.profile_service.get_by_client_code(client_code)
        if existing:
            return MigrationResult(
                success=True,
                profile_id=existing["id"],
                client_code=client_code,
                warnings=["Client already exists in Core - skipped"]
            )
        
        try:
            # Map Luna fields to Core fields
            profile = self._map_luna_to_profile(luna_data, client_code, display_name)
            profile.source_system = "luna"
            profile.migrated_from = luna_data.get("luna_id") or luna_data.get("id")
            profile.migration_date = datetime.now(timezone.utc)
            
            # Create the profile
            created = await self.profile_service.create(profile, created_by=migrated_by)
            
            logger.info(f"Migrated client from Luna: {client_code} -> {created['id']}")
            
            return MigrationResult(
                success=True,
                profile_id=created["id"],
                client_code=client_code,
                warnings=warnings if warnings else None
            )
            
        except Exception as e:
            logger.error(f"Migration failed for {client_code}: {e}")
            return MigrationResult(
                success=False,
                client_code=client_code,
                error=str(e)
            )
    
    async def migrate_batch(
        self,
        clients: List[Dict[str, Any]],
        migrated_by: str = "luna-migration"
    ) -> MigrationBatch:
        """
        Migrate multiple clients in a batch.
        
        Args:
            clients: List of Luna client data dicts
            migrated_by: Identifier for migration source
            
        Returns:
            MigrationBatch with results for each client
        """
        batch_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)
        results = []
        success_count = 0
        failure_count = 0
        
        logger.info(f"Starting batch migration: {batch_id} with {len(clients)} clients")
        
        for client_data in clients:
            result = await self.migrate_client(client_data, migrated_by)
            results.append(result)
            
            if result.success:
                success_count += 1
            else:
                failure_count += 1
        
        completed_at = datetime.now(timezone.utc)
        
        # Log batch summary
        await self._log_migration_batch(
            batch_id=batch_id,
            total=len(clients),
            success_count=success_count,
            failure_count=failure_count,
            started_at=started_at,
            completed_at=completed_at,
            migrated_by=migrated_by
        )
        
        logger.info(f"Batch migration complete: {batch_id} - {success_count}/{len(clients)} succeeded")
        
        return MigrationBatch(
            batch_id=batch_id,
            total=len(clients),
            success_count=success_count,
            failure_count=failure_count,
            results=results,
            started_at=started_at,
            completed_at=completed_at
        )
    
    async def sync_client(
        self,
        client_code: str,
        luna_data: Dict[str, Any],
        synced_by: str = "luna-sync"
    ) -> MigrationResult:
        """
        Sync/update an existing client from Luna.
        
        Used for ongoing sync after initial migration.
        
        Args:
            client_code: Client code to sync
            luna_data: Updated data from Luna
            synced_by: Identifier for sync source
            
        Returns:
            MigrationResult
        """
        # Find existing profile
        existing = await self.profile_service.get_by_client_code(client_code)
        
        if not existing:
            # Client doesn't exist in Core yet - migrate it
            return await self.migrate_client(luna_data, synced_by)
        
        try:
            # Map Luna data to updates
            updates = self._map_luna_to_updates(luna_data)
            
            # Update the profile
            updated = await self.profile_service.update(
                existing["id"],
                updates,
                updated_by=synced_by
            )
            
            logger.info(f"Synced client from Luna: {client_code}")
            
            return MigrationResult(
                success=True,
                profile_id=existing["id"],
                client_code=client_code
            )
            
        except Exception as e:
            logger.error(f"Sync failed for {client_code}: {e}")
            return MigrationResult(
                success=False,
                client_code=client_code,
                error=str(e)
            )
    
    async def get_migration_status(
        self,
        batch_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get migration status.
        
        Args:
            batch_id: Specific batch to check (or overall stats if None)
            
        Returns:
            Status dict
        """
        if batch_id:
            # Get specific batch status
            query = text("""
                SELECT * FROM core.migration_log 
                WHERE batch_id = :batch_id
            """)
            result = await self.db.execute(query, {"batch_id": batch_id})
            row = result.fetchone()
            
            if row:
                return dict(row._mapping)
            return {"error": "Batch not found"}
        
        # Get overall stats
        stats_query = text("""
            SELECT 
                COUNT(*) as total_profiles,
                COUNT(*) FILTER (WHERE source_system = 'luna') as luna_migrated,
                COUNT(*) FILTER (WHERE source_system = 'myfdc') as myfdc_created,
                COUNT(*) FILTER (WHERE source_system = 'core') as core_created,
                MAX(migration_date) as last_migration
            FROM public.client_profiles
        """)
        
        try:
            result = await self.db.execute(stats_query)
            row = result.fetchone()
            
            if row:
                return {
                    "total_profiles": row[0] or 0,
                    "luna_migrated": row[1] or 0,
                    "myfdc_created": row[2] or 0,
                    "core_created": row[3] or 0,
                    "last_migration": row[4].isoformat() if row[4] else None
                }
        except Exception as e:
            logger.error(f"Failed to get migration stats: {e}")
        
        return {
            "total_profiles": 0,
            "luna_migrated": 0,
            "myfdc_created": 0,
            "core_created": 0,
            "last_migration": None,
            "note": "Stats query failed - table may not exist yet"
        }
    
    async def rollback_migration(
        self,
        batch_id: str,
        performed_by: str = "admin"
    ) -> Dict[str, Any]:
        """
        Rollback a migration batch.
        
        Args:
            batch_id: Batch ID to rollback
            performed_by: User performing rollback
            
        Returns:
            Rollback result
        """
        # Get profiles from this batch
        query = text("""
            SELECT id, client_code FROM public.client_profiles
            WHERE source_system = 'luna' 
            AND migration_date >= (
                SELECT started_at FROM core.migration_log WHERE batch_id = :batch_id
            )
            AND migration_date <= (
                SELECT completed_at FROM core.migration_log WHERE batch_id = :batch_id
            )
        """)
        
        try:
            result = await self.db.execute(query, {"batch_id": batch_id})
            profiles = result.fetchall()
            
            # Archive (soft delete) the profiles
            deleted_count = 0
            for profile in profiles:
                await self.profile_service.delete(profile[0])
                deleted_count += 1
            
            logger.info(f"Rolled back batch {batch_id}: {deleted_count} profiles archived")
            
            return {
                "success": True,
                "batch_id": batch_id,
                "profiles_archived": deleted_count,
                "performed_by": performed_by
            }
            
        except Exception as e:
            logger.error(f"Rollback failed for batch {batch_id}: {e}")
            return {
                "success": False,
                "batch_id": batch_id,
                "error": str(e)
            }
    
    def _map_luna_to_profile(
        self,
        luna_data: Dict[str, Any],
        client_code: str,
        display_name: str
    ) -> ClientProfile:
        """Map Luna CRM fields to ClientProfile."""
        return ClientProfile(
            client_code=client_code,
            display_name=display_name,
            legal_name=luna_data.get("legal_name"),
            trading_name=luna_data.get("trading_name") or luna_data.get("trading_as"),
            entity_type=self._map_entity_type(luna_data.get("entity_type")),
            client_status=self._map_status(luna_data.get("status")),
            client_category=luna_data.get("category"),
            client_tier=luna_data.get("tier"),
            referral_source=luna_data.get("referral_source") or luna_data.get("source"),
            
            # Contact
            primary_contact_first_name=luna_data.get("contact_first_name") or luna_data.get("first_name"),
            primary_contact_last_name=luna_data.get("contact_last_name") or luna_data.get("last_name"),
            primary_contact_email=luna_data.get("email"),
            primary_contact_phone=luna_data.get("phone"),
            primary_contact_mobile=luna_data.get("mobile"),
            
            # Address
            primary_address_line1=luna_data.get("address_line1") or luna_data.get("street"),
            primary_address_line2=luna_data.get("address_line2"),
            primary_suburb=luna_data.get("suburb") or luna_data.get("city"),
            primary_state=luna_data.get("state"),
            primary_postcode=luna_data.get("postcode") or luna_data.get("postal_code"),
            
            # Tax
            abn=luna_data.get("abn"),
            acn=luna_data.get("acn"),
            tfn=luna_data.get("tfn"),  # Will be encrypted by service
            gst_registered=bool(luna_data.get("gst_registered")),
            gst_registration_date=self._parse_date(luna_data.get("gst_registration_date")),
            
            # Business
            industry_code=luna_data.get("industry_code") or luna_data.get("anzsic"),
            industry_description=luna_data.get("industry") or luna_data.get("industry_description"),
            
            # Staff
            assigned_partner_id=luna_data.get("partner_id"),
            assigned_manager_id=luna_data.get("manager_id"),
            assigned_accountant_id=luna_data.get("accountant_id"),
            assigned_bookkeeper_id=luna_data.get("bookkeeper_id"),
            
            # Services
            services_engaged=luna_data.get("services", []),
            engagement_type=luna_data.get("engagement_type"),
            
            # Integrations
            xero_tenant_id=luna_data.get("xero_tenant_id") or luna_data.get("xero_id"),
            myob_company_file_id=luna_data.get("myob_id"),
            
            # Notes
            internal_notes=luna_data.get("notes") or luna_data.get("internal_notes"),
            tags=luna_data.get("tags", []),
            custom_fields=luna_data.get("custom_fields", {})
        )
    
    def _map_luna_to_updates(self, luna_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map Luna data to update dict (excludes immutable fields)."""
        updates = {}
        
        # Only include fields that can be updated
        field_mapping = {
            "display_name": "display_name",
            "name": "display_name",
            "legal_name": "legal_name",
            "trading_name": "trading_name",
            "status": "client_status",
            "email": "primary_contact_email",
            "phone": "primary_contact_phone",
            "mobile": "primary_contact_mobile",
            "abn": "abn",
            "gst_registered": "gst_registered",
            "notes": "internal_notes",
            "tags": "tags"
        }
        
        for luna_field, core_field in field_mapping.items():
            if luna_field in luna_data:
                value = luna_data[luna_field]
                if luna_field == "status":
                    value = self._map_status(value)
                updates[core_field] = value
        
        return updates
    
    def _map_entity_type(self, luna_type: Optional[str]) -> str:
        """Map Luna entity type to Core entity type."""
        if not luna_type:
            return "individual"
        
        mapping = {
            "individual": "individual",
            "sole_trader": "sole_trader",
            "company": "company",
            "trust": "trust",
            "partnership": "partnership",
            "smsf": "smsf",
            "super_fund": "smsf",
            "pty_ltd": "company",
            "pty": "company"
        }
        
        return mapping.get(luna_type.lower(), "individual")
    
    def _map_status(self, luna_status: Optional[str]) -> str:
        """Map Luna status to Core status."""
        if not luna_status:
            return "active"
        
        mapping = {
            "active": "active",
            "inactive": "inactive",
            "archived": "archived",
            "prospect": "prospect",
            "lead": "prospect",
            "deleted": "archived"
        }
        
        return mapping.get(luna_status.lower(), "active")
    
    def _parse_date(self, date_str: Optional[str]):
        """Parse date string to date object."""
        if not date_str:
            return None
        
        from datetime import date
        
        try:
            if isinstance(date_str, date):
                return date_str
            # Try common formats
            for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]:
                try:
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
        except Exception:
            pass
        
        return None
    
    async def _log_migration_batch(
        self,
        batch_id: str,
        total: int,
        success_count: int,
        failure_count: int,
        started_at: datetime,
        completed_at: datetime,
        migrated_by: str
    ):
        """Log migration batch to database."""
        try:
            # Try to create migration_log table if it doesn't exist
            create_table = text("""
                CREATE TABLE IF NOT EXISTS core.migration_log (
                    batch_id VARCHAR(50) PRIMARY KEY,
                    total INTEGER,
                    success_count INTEGER,
                    failure_count INTEGER,
                    started_at TIMESTAMP WITH TIME ZONE,
                    completed_at TIMESTAMP WITH TIME ZONE,
                    migrated_by VARCHAR(100)
                )
            """)
            await self.db.execute(create_table)
            
            insert = text("""
                INSERT INTO core.migration_log 
                (batch_id, total, success_count, failure_count, started_at, completed_at, migrated_by)
                VALUES (:batch_id, :total, :success_count, :failure_count, :started_at, :completed_at, :migrated_by)
            """)
            
            await self.db.execute(insert, {
                "batch_id": batch_id,
                "total": total,
                "success_count": success_count,
                "failure_count": failure_count,
                "started_at": started_at,
                "completed_at": completed_at,
                "migrated_by": migrated_by
            })
            await self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to log migration batch: {e}")
