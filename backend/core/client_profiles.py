"""
Client Profile Service

Provides CRUD operations for the 86-field client profiles schema.
Handles encryption/decryption of sensitive fields (TFN).
"""

import uuid
import json
import logging
from datetime import datetime, timezone, date
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from utils.encryption import (
    encrypt_tfn, decrypt_tfn, mask_tfn, get_tfn_last_four,
    is_encryption_configured, log_tfn_access
)

logger = logging.getLogger(__name__)


@dataclass
class ClientProfile:
    """
    Client Profile Data Transfer Object.
    Represents the 86-field client profile schema.
    """
    # Identity
    id: Optional[str] = None
    person_id: Optional[str] = None
    crm_client_id: Optional[str] = None
    legacy_client_id: Optional[str] = None
    
    # Basic Info
    client_code: str = ""
    display_name: str = ""
    legal_name: Optional[str] = None
    trading_name: Optional[str] = None
    entity_type: str = "individual"
    client_status: str = "active"
    client_category: Optional[str] = None
    client_tier: Optional[str] = None
    referral_source: Optional[str] = None
    
    # Contact Person
    primary_contact_first_name: Optional[str] = None
    primary_contact_last_name: Optional[str] = None
    primary_contact_title: Optional[str] = None
    primary_contact_email: Optional[str] = None
    primary_contact_phone: Optional[str] = None
    primary_contact_mobile: Optional[str] = None
    preferred_contact_method: str = "email"
    preferred_contact_time: Optional[str] = None
    
    # Primary Address
    primary_address_line1: Optional[str] = None
    primary_address_line2: Optional[str] = None
    primary_suburb: Optional[str] = None
    primary_state: Optional[str] = None
    primary_postcode: Optional[str] = None
    primary_country: str = "Australia"
    primary_address_type: str = "business"
    
    # Postal Address
    postal_address_line1: Optional[str] = None
    postal_address_line2: Optional[str] = None
    postal_suburb: Optional[str] = None
    postal_state: Optional[str] = None
    postal_postcode: Optional[str] = None
    postal_country: str = "Australia"
    
    # Tax Identifiers (TFN stored encrypted)
    abn: Optional[str] = None
    abn_status: Optional[str] = None
    abn_registration_date: Optional[date] = None
    acn: Optional[str] = None
    tfn: Optional[str] = None  # Plaintext - encrypted before storage
    tfn_last_four: Optional[str] = None
    tax_file_number_status: Optional[str] = None
    withholding_payer_number: Optional[str] = None
    
    # GST
    gst_registered: bool = False
    gst_registration_date: Optional[date] = None
    gst_accounting_method: str = "accrual"
    gst_reporting_frequency: str = "quarterly"
    gst_branch_number: Optional[str] = None
    gst_group_member: bool = False
    
    # Business Details
    industry_code: Optional[str] = None
    industry_description: Optional[str] = None
    business_description: Optional[str] = None
    date_established: Optional[date] = None
    financial_year_end: str = "30-Jun"
    employees_count: Optional[int] = None
    annual_turnover_range: Optional[str] = None
    registered_for_payg_withholding: bool = False
    
    # Staff Assignments
    assigned_partner_id: Optional[str] = None
    assigned_manager_id: Optional[str] = None
    assigned_accountant_id: Optional[str] = None
    assigned_bookkeeper_id: Optional[str] = None
    
    # Services & Fees
    services_engaged: List[str] = field(default_factory=list)
    engagement_type: Optional[str] = None
    fee_structure: Optional[str] = None
    standard_hourly_rate: Optional[Decimal] = None
    monthly_retainer: Optional[Decimal] = None
    billing_frequency: str = "monthly"
    payment_terms: int = 14
    credit_limit: Optional[Decimal] = None
    
    # Integrations
    xero_tenant_id: Optional[str] = None
    myob_company_file_id: Optional[str] = None
    quickbooks_realm_id: Optional[str] = None
    bank_feed_status: Optional[str] = None
    document_portal_enabled: bool = True
    myfdc_linked: bool = False
    
    # Compliance
    aml_kyc_verified: bool = False
    aml_kyc_verified_date: Optional[date] = None
    aml_risk_rating: Optional[str] = None
    identity_verified: bool = False
    identity_verified_date: Optional[date] = None
    poa_on_file: bool = False
    
    # Notes & Custom
    internal_notes: Optional[str] = None
    client_notes: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    custom_fields: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    source_system: Optional[str] = None
    migrated_from: Optional[str] = None
    migration_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    
    def to_dict(self, include_tfn: bool = False) -> Dict[str, Any]:
        """Convert to dictionary, optionally masking TFN."""
        data = asdict(self)
        
        # Convert dates to ISO format
        for key, value in data.items():
            if isinstance(value, (date, datetime)):
                data[key] = value.isoformat() if value else None
            elif isinstance(value, Decimal):
                data[key] = float(value) if value else None
        
        # Mask TFN unless explicitly requested
        if not include_tfn and data.get("tfn"):
            data["tfn"] = mask_tfn(data["tfn"])
        
        return data


class ClientProfileService:
    """
    Service for managing client profiles.
    
    Handles:
    - CRUD operations on public.client_profiles
    - TFN encryption/decryption
    - Search and filtering
    - Audit logging
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(
        self,
        profile: ClientProfile,
        created_by: str = "system"
    ) -> Dict[str, Any]:
        """
        Create a new client profile.
        
        Args:
            profile: ClientProfile to create
            created_by: User/system creating the profile
            
        Returns:
            Created profile dict
        """
        profile_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Encrypt TFN if provided
        tfn_encrypted = None
        tfn_last_four = None
        if profile.tfn:
            tfn_encrypted = encrypt_tfn(profile.tfn)
            tfn_last_four = get_tfn_last_four(profile.tfn)
            log_tfn_access("encrypt", profile.client_code, created_by, True, "profile_create")
        
        insert_sql = text("""
            INSERT INTO public.client_profiles (
                id, person_id, crm_client_id, legacy_client_id,
                client_code, display_name, legal_name, trading_name,
                entity_type, client_status, client_category, client_tier, referral_source,
                primary_contact_first_name, primary_contact_last_name, primary_contact_title,
                primary_contact_email, primary_contact_phone, primary_contact_mobile,
                preferred_contact_method, preferred_contact_time,
                primary_address_line1, primary_address_line2, primary_suburb,
                primary_state, primary_postcode, primary_country, primary_address_type,
                postal_address_line1, postal_address_line2, postal_suburb,
                postal_state, postal_postcode, postal_country,
                abn, abn_status, abn_registration_date, acn,
                tfn_encrypted, tfn_last_four, tax_file_number_status, withholding_payer_number,
                gst_registered, gst_registration_date, gst_accounting_method,
                gst_reporting_frequency, gst_branch_number, gst_group_member,
                industry_code, industry_description, business_description,
                date_established, financial_year_end, employees_count,
                annual_turnover_range, registered_for_payg_withholding,
                assigned_partner_id, assigned_manager_id, assigned_accountant_id, assigned_bookkeeper_id,
                services_engaged, engagement_type, fee_structure,
                standard_hourly_rate, monthly_retainer, billing_frequency, payment_terms, credit_limit,
                xero_tenant_id, myob_company_file_id, quickbooks_realm_id,
                bank_feed_status, document_portal_enabled, myfdc_linked,
                aml_kyc_verified, aml_kyc_verified_date, aml_risk_rating,
                identity_verified, identity_verified_date, poa_on_file,
                internal_notes, client_notes, tags, custom_fields,
                source_system, migrated_from, migration_date,
                created_at, updated_at, created_by, updated_by
            ) VALUES (
                :id, :person_id, :crm_client_id, :legacy_client_id,
                :client_code, :display_name, :legal_name, :trading_name,
                :entity_type, :client_status, :client_category, :client_tier, :referral_source,
                :primary_contact_first_name, :primary_contact_last_name, :primary_contact_title,
                :primary_contact_email, :primary_contact_phone, :primary_contact_mobile,
                :preferred_contact_method, :preferred_contact_time,
                :primary_address_line1, :primary_address_line2, :primary_suburb,
                :primary_state, :primary_postcode, :primary_country, :primary_address_type,
                :postal_address_line1, :postal_address_line2, :postal_suburb,
                :postal_state, :postal_postcode, :postal_country,
                :abn, :abn_status, :abn_registration_date, :acn,
                :tfn_encrypted, :tfn_last_four, :tax_file_number_status, :withholding_payer_number,
                :gst_registered, :gst_registration_date, :gst_accounting_method,
                :gst_reporting_frequency, :gst_branch_number, :gst_group_member,
                :industry_code, :industry_description, :business_description,
                :date_established, :financial_year_end, :employees_count,
                :annual_turnover_range, :registered_for_payg_withholding,
                :assigned_partner_id, :assigned_manager_id, :assigned_accountant_id, :assigned_bookkeeper_id,
                CAST(:services_engaged AS jsonb), :engagement_type, :fee_structure,
                :standard_hourly_rate, :monthly_retainer, :billing_frequency, :payment_terms, :credit_limit,
                :xero_tenant_id, :myob_company_file_id, :quickbooks_realm_id,
                :bank_feed_status, :document_portal_enabled, :myfdc_linked,
                :aml_kyc_verified, :aml_kyc_verified_date, :aml_risk_rating,
                :identity_verified, :identity_verified_date, :poa_on_file,
                :internal_notes, :client_notes, CAST(:tags AS jsonb), CAST(:custom_fields AS jsonb),
                :source_system, :migrated_from, :migration_date,
                :created_at, :updated_at, :created_by, :updated_by
            )
            RETURNING id
        """)
        
        params = {
            "id": profile_id,
            "person_id": profile.person_id,
            "crm_client_id": profile.crm_client_id,
            "legacy_client_id": profile.legacy_client_id,
            "client_code": profile.client_code,
            "display_name": profile.display_name,
            "legal_name": profile.legal_name,
            "trading_name": profile.trading_name,
            "entity_type": profile.entity_type,
            "client_status": profile.client_status,
            "client_category": profile.client_category,
            "client_tier": profile.client_tier,
            "referral_source": profile.referral_source,
            "primary_contact_first_name": profile.primary_contact_first_name,
            "primary_contact_last_name": profile.primary_contact_last_name,
            "primary_contact_title": profile.primary_contact_title,
            "primary_contact_email": profile.primary_contact_email,
            "primary_contact_phone": profile.primary_contact_phone,
            "primary_contact_mobile": profile.primary_contact_mobile,
            "preferred_contact_method": profile.preferred_contact_method,
            "preferred_contact_time": profile.preferred_contact_time,
            "primary_address_line1": profile.primary_address_line1,
            "primary_address_line2": profile.primary_address_line2,
            "primary_suburb": profile.primary_suburb,
            "primary_state": profile.primary_state,
            "primary_postcode": profile.primary_postcode,
            "primary_country": profile.primary_country,
            "primary_address_type": profile.primary_address_type,
            "postal_address_line1": profile.postal_address_line1,
            "postal_address_line2": profile.postal_address_line2,
            "postal_suburb": profile.postal_suburb,
            "postal_state": profile.postal_state,
            "postal_postcode": profile.postal_postcode,
            "postal_country": profile.postal_country,
            "abn": profile.abn,
            "abn_status": profile.abn_status,
            "abn_registration_date": profile.abn_registration_date,
            "acn": profile.acn,
            "tfn_encrypted": tfn_encrypted,
            "tfn_last_four": tfn_last_four,
            "tax_file_number_status": profile.tax_file_number_status,
            "withholding_payer_number": profile.withholding_payer_number,
            "gst_registered": profile.gst_registered,
            "gst_registration_date": profile.gst_registration_date,
            "gst_accounting_method": profile.gst_accounting_method,
            "gst_reporting_frequency": profile.gst_reporting_frequency,
            "gst_branch_number": profile.gst_branch_number,
            "gst_group_member": profile.gst_group_member,
            "industry_code": profile.industry_code,
            "industry_description": profile.industry_description,
            "business_description": profile.business_description,
            "date_established": profile.date_established,
            "financial_year_end": profile.financial_year_end,
            "employees_count": profile.employees_count,
            "annual_turnover_range": profile.annual_turnover_range,
            "registered_for_payg_withholding": profile.registered_for_payg_withholding,
            "assigned_partner_id": profile.assigned_partner_id,
            "assigned_manager_id": profile.assigned_manager_id,
            "assigned_accountant_id": profile.assigned_accountant_id,
            "assigned_bookkeeper_id": profile.assigned_bookkeeper_id,
            "services_engaged": json.dumps(profile.services_engaged),
            "engagement_type": profile.engagement_type,
            "fee_structure": profile.fee_structure,
            "standard_hourly_rate": float(profile.standard_hourly_rate) if profile.standard_hourly_rate else None,
            "monthly_retainer": float(profile.monthly_retainer) if profile.monthly_retainer else None,
            "billing_frequency": profile.billing_frequency,
            "payment_terms": profile.payment_terms,
            "credit_limit": float(profile.credit_limit) if profile.credit_limit else None,
            "xero_tenant_id": profile.xero_tenant_id,
            "myob_company_file_id": profile.myob_company_file_id,
            "quickbooks_realm_id": profile.quickbooks_realm_id,
            "bank_feed_status": profile.bank_feed_status,
            "document_portal_enabled": profile.document_portal_enabled,
            "myfdc_linked": profile.myfdc_linked,
            "aml_kyc_verified": profile.aml_kyc_verified,
            "aml_kyc_verified_date": profile.aml_kyc_verified_date,
            "aml_risk_rating": profile.aml_risk_rating,
            "identity_verified": profile.identity_verified,
            "identity_verified_date": profile.identity_verified_date,
            "poa_on_file": profile.poa_on_file,
            "internal_notes": profile.internal_notes,
            "client_notes": profile.client_notes,
            "tags": json.dumps(profile.tags),
            "custom_fields": json.dumps(profile.custom_fields),
            "source_system": profile.source_system or "core",
            "migrated_from": profile.migrated_from,
            "migration_date": profile.migration_date,
            "created_at": now,
            "updated_at": now,
            "created_by": created_by,
            "updated_by": created_by
        }
        
        await self.db.execute(insert_sql, params)
        await self.db.commit()
        
        logger.info(f"Created client profile: {profile.client_code} ({profile_id})")
        
        return await self.get_by_id(profile_id)
    
    async def get_by_id(
        self,
        profile_id: str,
        include_tfn: bool = False,
        user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get client profile by ID.
        
        Args:
            profile_id: Profile UUID
            include_tfn: Whether to decrypt and include TFN
            user_id: User requesting (for audit logging)
            
        Returns:
            Profile dict or None
        """
        query = text("""
            SELECT * FROM public.client_profiles WHERE id = :id
        """)
        
        result = await self.db.execute(query, {"id": profile_id})
        row = result.fetchone()
        
        if not row:
            return None
        
        return self._row_to_dict(row, include_tfn, user_id)
    
    async def get_by_client_code(
        self,
        client_code: str,
        include_tfn: bool = False,
        user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get client profile by client code."""
        query = text("""
            SELECT * FROM public.client_profiles WHERE client_code = :client_code
        """)
        
        result = await self.db.execute(query, {"client_code": client_code})
        row = result.fetchone()
        
        if not row:
            return None
        
        return self._row_to_dict(row, include_tfn, user_id)
    
    async def search(
        self,
        query_str: Optional[str] = None,
        entity_type: Optional[str] = None,
        client_status: Optional[str] = None,
        assigned_to: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Search client profiles.
        
        Args:
            query_str: Search term (matches name, code, ABN)
            entity_type: Filter by entity type
            client_status: Filter by status
            assigned_to: Filter by assigned staff
            limit: Max results
            offset: Pagination offset
            
        Returns:
            List of profile dicts
        """
        conditions = []
        params = {"limit": limit, "offset": offset}
        
        if query_str:
            conditions.append("""
                (display_name ILIKE :query 
                 OR legal_name ILIKE :query 
                 OR client_code ILIKE :query 
                 OR abn ILIKE :query)
            """)
            params["query"] = f"%{query_str}%"
        
        if entity_type:
            conditions.append("entity_type = :entity_type")
            params["entity_type"] = entity_type
        
        if client_status:
            conditions.append("client_status = :client_status")
            params["client_status"] = client_status
        
        if assigned_to:
            conditions.append("""
                (assigned_partner_id = :assigned_to 
                 OR assigned_manager_id = :assigned_to 
                 OR assigned_accountant_id = :assigned_to 
                 OR assigned_bookkeeper_id = :assigned_to)
            """)
            params["assigned_to"] = assigned_to
        
        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        
        query = text(f"""
            SELECT * FROM public.client_profiles 
            WHERE {where_clause}
            ORDER BY display_name ASC
            LIMIT :limit OFFSET :offset
        """)
        
        result = await self.db.execute(query, params)
        rows = result.fetchall()
        
        return [self._row_to_dict(row, include_tfn=False) for row in rows]
    
    async def update(
        self,
        profile_id: str,
        updates: Dict[str, Any],
        updated_by: str = "system"
    ) -> Optional[Dict[str, Any]]:
        """
        Update client profile.
        
        Args:
            profile_id: Profile UUID
            updates: Dict of fields to update
            updated_by: User making the update
            
        Returns:
            Updated profile dict
        """
        # Handle TFN encryption if being updated
        if "tfn" in updates and updates["tfn"]:
            updates["tfn_encrypted"] = encrypt_tfn(updates["tfn"])
            updates["tfn_last_four"] = get_tfn_last_four(updates["tfn"])
            log_tfn_access("encrypt", profile_id, updated_by, True, "profile_update")
            del updates["tfn"]
        
        # Handle JSON fields
        if "services_engaged" in updates:
            updates["services_engaged"] = json.dumps(updates["services_engaged"])
        if "tags" in updates:
            updates["tags"] = json.dumps(updates["tags"])
        if "custom_fields" in updates:
            updates["custom_fields"] = json.dumps(updates["custom_fields"])
        
        updates["updated_at"] = datetime.now(timezone.utc)
        updates["updated_by"] = updated_by
        
        # Build dynamic update query
        set_clauses = [f"{k} = :{k}" for k in updates.keys()]
        set_clause = ", ".join(set_clauses)
        
        query = text(f"""
            UPDATE public.client_profiles 
            SET {set_clause}
            WHERE id = :profile_id
        """)
        
        params = {**updates, "profile_id": profile_id}
        await self.db.execute(query, params)
        await self.db.commit()
        
        logger.info(f"Updated client profile: {profile_id}")
        
        return await self.get_by_id(profile_id)
    
    async def delete(self, profile_id: str) -> bool:
        """Soft delete client profile by setting status to archived."""
        return await self.update(profile_id, {"client_status": "archived"}) is not None
    
    def _row_to_dict(
        self,
        row,
        include_tfn: bool = False,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Convert database row to dict."""
        # Get column names from row
        columns = row._fields if hasattr(row, '_fields') else row.keys()
        data = dict(zip(columns, row))
        
        # Handle TFN
        if include_tfn and data.get("tfn_encrypted"):
            try:
                data["tfn"] = decrypt_tfn(data["tfn_encrypted"])
                if user_id:
                    log_tfn_access("decrypt", str(data.get("id")), user_id, True, "view")
            except Exception as e:
                logger.error(f"Failed to decrypt TFN: {e}")
                data["tfn"] = None
        else:
            data["tfn"] = mask_tfn(data.get("tfn_last_four", "")) if data.get("tfn_last_four") else None
        
        # Remove encrypted field from response
        data.pop("tfn_encrypted", None)
        
        # Convert UUIDs to strings
        for key in ["id", "person_id", "crm_client_id", "assigned_partner_id", 
                    "assigned_manager_id", "assigned_accountant_id", "assigned_bookkeeper_id"]:
            if data.get(key):
                data[key] = str(data[key])
        
        # Convert dates to ISO format
        for key in ["abn_registration_date", "gst_registration_date", "date_established",
                    "aml_kyc_verified_date", "identity_verified_date", "migration_date",
                    "created_at", "updated_at"]:
            if data.get(key):
                data[key] = data[key].isoformat() if hasattr(data[key], 'isoformat') else str(data[key])
        
        return data
