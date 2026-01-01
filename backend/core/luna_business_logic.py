"""
Luna Business Logic Migration Module

This module contains business logic being migrated from the Luna CRM service
into the Core module. It provides:

1. Client lookup and matching utilities
2. Client data validation and normalization
3. Business rules for client management
4. Integration points for the migration endpoints

Note: TFN encryption is NOT activated until ENCRYPTION_KEY is available.
Note: Email functionality is NOT activated until Resend API key is available.
"""

import re
import logging
from datetime import datetime, timezone, date
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


# ==================== VALIDATION UTILITIES ====================

class ClientValidator:
    """
    Validates and normalizes client data during migration.
    Implements Luna's validation rules in Core.
    """
    
    # Australian Business Number format: 11 digits
    ABN_PATTERN = re.compile(r'^\d{11}$')
    
    # Australian Company Number format: 9 digits
    ACN_PATTERN = re.compile(r'^\d{9}$')
    
    # Tax File Number format: 8-9 digits
    TFN_PATTERN = re.compile(r'^\d{8,9}$')
    
    # Email pattern
    EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    
    # Australian phone formats
    PHONE_PATTERNS = [
        re.compile(r'^04\d{8}$'),           # Mobile: 04XX XXX XXX
        re.compile(r'^0[2-9]\d{8}$'),        # Landline: 0X XXXX XXXX
        re.compile(r'^\+61\d{9}$'),          # International: +61...
    ]
    
    # Australian states
    VALID_STATES = {'NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'NT', 'ACT'}
    
    # Valid entity types
    VALID_ENTITY_TYPES = {
        'individual', 'sole_trader', 'company', 'trust',
        'partnership', 'smsf', 'association', 'other'
    }
    
    # Valid client statuses
    VALID_STATUSES = {'active', 'inactive', 'prospect', 'archived', 'suspended'}
    
    @classmethod
    def validate_abn(cls, abn: Optional[str]) -> Tuple[bool, Optional[str]]:
        """
        Validate Australian Business Number.
        Returns (is_valid, normalized_abn or error_message).
        """
        if not abn:
            return True, None
        
        # Remove spaces and dashes
        clean_abn = re.sub(r'[\s\-]', '', abn)
        
        if not cls.ABN_PATTERN.match(clean_abn):
            return False, "ABN must be exactly 11 digits"
        
        # ABN checksum validation (weighted modulus algorithm)
        weights = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
        digits = [int(d) for d in clean_abn]
        digits[0] -= 1  # Subtract 1 from first digit
        
        checksum = sum(d * w for d, w in zip(digits, weights))
        if checksum % 89 != 0:
            return False, "Invalid ABN checksum"
        
        return True, clean_abn
    
    @classmethod
    def validate_acn(cls, acn: Optional[str]) -> Tuple[bool, Optional[str]]:
        """Validate Australian Company Number."""
        if not acn:
            return True, None
        
        clean_acn = re.sub(r'[\s\-]', '', acn)
        
        if not cls.ACN_PATTERN.match(clean_acn):
            return False, "ACN must be exactly 9 digits"
        
        return True, clean_acn
    
    @classmethod
    def validate_tfn(cls, tfn: Optional[str]) -> Tuple[bool, Optional[str]]:
        """
        Validate Tax File Number format.
        Note: Does not verify with ATO - format validation only.
        """
        if not tfn:
            return True, None
        
        clean_tfn = re.sub(r'[\s\-]', '', tfn)
        
        if not cls.TFN_PATTERN.match(clean_tfn):
            return False, "TFN must be 8-9 digits"
        
        return True, clean_tfn
    
    @classmethod
    def normalize_phone(cls, phone: Optional[str]) -> Optional[str]:
        """Normalize Australian phone number to standard format."""
        if not phone:
            return None
        
        # Remove all non-digit characters except +
        clean = re.sub(r'[^\d+]', '', phone)
        
        # Convert +61 to 0
        if clean.startswith('+61'):
            clean = '0' + clean[3:]
        elif clean.startswith('61') and len(clean) == 11:
            clean = '0' + clean[2:]
        
        # Add leading 0 if missing for 9-digit numbers
        if len(clean) == 9 and clean[0] != '0':
            clean = '0' + clean
        
        return clean if len(clean) == 10 else phone
    
    @classmethod
    def validate_email(cls, email: Optional[str]) -> Tuple[bool, Optional[str]]:
        """Validate email format."""
        if not email:
            return True, None
        
        email = email.strip().lower()
        
        if not cls.EMAIL_PATTERN.match(email):
            return False, "Invalid email format"
        
        return True, email
    
    @classmethod
    def normalize_state(cls, state: Optional[str]) -> Optional[str]:
        """Normalize Australian state abbreviation."""
        if not state:
            return None
        
        state = state.strip().upper()
        
        # Handle common variations
        state_mapping = {
            'NEW SOUTH WALES': 'NSW',
            'VICTORIA': 'VIC',
            'QUEENSLAND': 'QLD',
            'SOUTH AUSTRALIA': 'SA',
            'WESTERN AUSTRALIA': 'WA',
            'TASMANIA': 'TAS',
            'NORTHERN TERRITORY': 'NT',
            'AUSTRALIAN CAPITAL TERRITORY': 'ACT',
        }
        
        return state_mapping.get(state, state if state in cls.VALID_STATES else None)
    
    @classmethod
    def validate_entity_type(cls, entity_type: Optional[str]) -> str:
        """Validate and normalize entity type."""
        if not entity_type:
            return 'individual'
        
        normalized = entity_type.lower().strip().replace(' ', '_')
        
        # Map common variations
        type_mapping = {
            'pty_ltd': 'company',
            'pty': 'company',
            'proprietary_limited': 'company',
            'super_fund': 'smsf',
            'self_managed_super_fund': 'smsf',
            'unit_trust': 'trust',
            'family_trust': 'trust',
            'discretionary_trust': 'trust',
        }
        
        mapped = type_mapping.get(normalized, normalized)
        return mapped if mapped in cls.VALID_ENTITY_TYPES else 'individual'
    
    @classmethod
    def validate_status(cls, status: Optional[str]) -> str:
        """Validate and normalize client status."""
        if not status:
            return 'active'
        
        normalized = status.lower().strip()
        
        status_mapping = {
            'deleted': 'archived',
            'removed': 'archived',
            'lead': 'prospect',
            'potential': 'prospect',
            'paused': 'suspended',
            'on_hold': 'suspended',
        }
        
        mapped = status_mapping.get(normalized, normalized)
        return mapped if mapped in cls.VALID_STATUSES else 'active'


# ==================== CLIENT MATCHING ====================

class ClientMatcher:
    """
    Matches incoming Luna client data to existing Core profiles.
    Handles deduplication and conflict resolution during migration.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def find_match(
        self,
        client_code: Optional[str] = None,
        abn: Optional[str] = None,
        email: Optional[str] = None,
        display_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Find a matching client profile based on multiple criteria.
        Priority: client_code > ABN > email > name match
        """
        # Priority 1: Exact client code match
        if client_code:
            match = await self._find_by_client_code(client_code)
            if match:
                return {**match, 'match_type': 'client_code', 'confidence': 1.0}
        
        # Priority 2: ABN match (most reliable for businesses)
        if abn:
            match = await self._find_by_abn(abn)
            if match:
                return {**match, 'match_type': 'abn', 'confidence': 0.95}
        
        # Priority 3: Email match
        if email:
            match = await self._find_by_email(email)
            if match:
                return {**match, 'match_type': 'email', 'confidence': 0.85}
        
        # Priority 4: Name similarity (fuzzy match)
        if display_name:
            matches = await self._find_by_name_similarity(display_name)
            if matches:
                best_match = matches[0]
                return {**best_match, 'match_type': 'name_similarity', 'confidence': best_match.get('similarity', 0.5)}
        
        return None
    
    async def _find_by_client_code(self, client_code: str) -> Optional[Dict[str, Any]]:
        """Find by exact client code."""
        query = text("""
            SELECT id, client_code, display_name, abn, primary_contact_email, client_status
            FROM public.client_profiles
            WHERE client_code = :code AND client_status != 'archived'
        """)
        result = await self.db.execute(query, {'code': client_code})
        row = result.fetchone()
        return dict(row._mapping) if row else None
    
    async def _find_by_abn(self, abn: str) -> Optional[Dict[str, Any]]:
        """Find by ABN."""
        # Normalize ABN
        clean_abn = re.sub(r'[\s\-]', '', abn)
        
        query = text("""
            SELECT id, client_code, display_name, abn, primary_contact_email, client_status
            FROM public.client_profiles
            WHERE REPLACE(REPLACE(abn, ' ', ''), '-', '') = :abn 
            AND client_status != 'archived'
        """)
        result = await self.db.execute(query, {'abn': clean_abn})
        row = result.fetchone()
        return dict(row._mapping) if row else None
    
    async def _find_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Find by primary contact email."""
        query = text("""
            SELECT id, client_code, display_name, abn, primary_contact_email, client_status
            FROM public.client_profiles
            WHERE LOWER(primary_contact_email) = LOWER(:email)
            AND client_status != 'archived'
        """)
        result = await self.db.execute(query, {'email': email.strip()})
        row = result.fetchone()
        return dict(row._mapping) if row else None
    
    async def _find_by_name_similarity(
        self,
        name: str,
        threshold: float = 0.6,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find by name similarity using ILIKE (more reliable than trigram).
        """
        try:
            query = text("""
                SELECT id, client_code, display_name, abn, primary_contact_email, client_status
                FROM public.client_profiles
                WHERE client_status != 'archived'
                AND LOWER(display_name) ILIKE :pattern
                ORDER BY 
                    CASE 
                        WHEN LOWER(display_name) = LOWER(:exact_name) THEN 1
                        WHEN LOWER(display_name) LIKE LOWER(:starts_with) THEN 2
                        ELSE 3
                    END
                LIMIT :limit
            """)
            result = await self.db.execute(query, {
                'pattern': f'%{name}%',
                'exact_name': name,
                'starts_with': f'{name}%',
                'limit': limit
            })
            rows = result.fetchall()
            
            return [
                {**dict(row._mapping), 'similarity': 0.7 if name.lower() in str(row.display_name).lower() else 0.5}
                for row in rows
            ]
        except Exception as e:
            logger.warning(f"Name similarity search failed: {e}")
            return []


# ==================== BUSINESS RULES ====================

@dataclass
class MigrationRule:
    """Represents a business rule for migration."""
    name: str
    description: str
    required: bool = False
    validator: Optional[callable] = None


class LunaBusinessRules:
    """
    Encapsulates Luna's business rules for client management.
    These rules are applied during migration and ongoing sync.
    """
    
    # GST threshold in Australia (current as of 2024)
    GST_THRESHOLD = 75000
    
    # BAS frequencies
    BAS_FREQUENCIES = {
        'monthly': 'Monthly reporters (>$20M turnover)',
        'quarterly': 'Standard quarterly reporting',
        'annually': 'Annual reporting (<$75K turnover)'
    }
    
    @classmethod
    def determine_bas_frequency(
        cls,
        annual_turnover: Optional[float],
        gst_registered: bool
    ) -> str:
        """Determine BAS reporting frequency based on turnover."""
        if not gst_registered:
            return 'none'
        
        if annual_turnover is None:
            return 'quarterly'  # Default
        
        if annual_turnover >= 20_000_000:
            return 'monthly'
        elif annual_turnover < cls.GST_THRESHOLD:
            return 'annually'
        else:
            return 'quarterly'
    
    @classmethod
    def should_register_gst(cls, annual_turnover: Optional[float]) -> bool:
        """Determine if business should be registered for GST."""
        if annual_turnover is None:
            return False
        return annual_turnover >= cls.GST_THRESHOLD
    
    @classmethod
    def calculate_client_tier(
        cls,
        annual_turnover: Optional[float],
        services_engaged: Optional[List[str]]
    ) -> str:
        """
        Calculate client tier based on turnover and services.
        Luna's tiering system for service prioritization.
        """
        service_count = len(services_engaged) if services_engaged else 0
        
        if annual_turnover is None:
            annual_turnover = 0
        
        # Premium: High turnover or many services
        if annual_turnover >= 2_000_000 or service_count >= 5:
            return 'premium'
        
        # Standard: Mid-range
        if annual_turnover >= 500_000 or service_count >= 3:
            return 'standard'
        
        # Basic: Entry level
        if annual_turnover >= cls.GST_THRESHOLD or service_count >= 1:
            return 'basic'
        
        return 'starter'
    
    @classmethod
    def get_required_documents(cls, entity_type: str) -> List[str]:
        """Get list of required documents based on entity type."""
        base_docs = ['id_verification', 'proof_of_address']
        
        entity_docs = {
            'company': ['asic_extract', 'company_constitution', 'director_ids'],
            'trust': ['trust_deed', 'trustee_details'],
            'partnership': ['partnership_agreement', 'partner_ids'],
            'smsf': ['smsf_trust_deed', 'member_ids', 'ato_registration'],
        }
        
        return base_docs + entity_docs.get(entity_type, [])
    
    @classmethod
    def validate_for_lodgement(
        cls,
        profile: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """
        Validate client profile has minimum required data for ATO lodgement.
        Returns (is_valid, list of missing/invalid fields).
        """
        errors = []
        
        # Required for all lodgements
        if not profile.get('display_name'):
            errors.append('display_name: Required for lodgement')
        
        if not profile.get('abn') and profile.get('entity_type') not in ['individual']:
            errors.append('abn: Required for business entities')
        
        if not profile.get('primary_contact_email'):
            errors.append('primary_contact_email: Required for ATO correspondence')
        
        # GST-specific requirements
        if profile.get('gst_registered'):
            if not profile.get('gst_registration_date'):
                errors.append('gst_registration_date: Required for GST-registered entities')
            if not profile.get('gst_accounting_method'):
                errors.append('gst_accounting_method: Required (cash/accrual)')
        
        # Address requirements
        if not profile.get('primary_address_line1'):
            errors.append('primary_address_line1: Business address required')
        if not profile.get('primary_state'):
            errors.append('primary_state: Australian state required')
        if not profile.get('primary_postcode'):
            errors.append('primary_postcode: Postcode required')
        
        return len(errors) == 0, errors


# ==================== MIGRATION HELPERS ====================

class MigrationHelpers:
    """
    Helper functions for the Luna → Core migration process.
    """
    
    @staticmethod
    def generate_client_code(
        entity_type: str,
        display_name: str,
        existing_codes: List[str]
    ) -> str:
        """
        Generate a unique client code if not provided by Luna.
        Format: [TYPE_PREFIX]-[NAME_INITIALS]-[NUMBER]
        """
        prefixes = {
            'individual': 'IND',
            'sole_trader': 'SOL',
            'company': 'COM',
            'trust': 'TRU',
            'partnership': 'PTN',
            'smsf': 'SMF',
        }
        
        prefix = prefixes.get(entity_type, 'CLI')
        
        # Get initials from name
        words = display_name.split()[:3]
        initials = ''.join(w[0].upper() for w in words if w)[:3]
        if not initials:
            initials = 'XXX'
        
        # Find next available number
        base_code = f"{prefix}-{initials}"
        counter = 1
        
        while True:
            code = f"{base_code}-{counter:04d}"
            if code not in existing_codes:
                return code
            counter += 1
            if counter > 9999:
                # Fallback to UUID-based
                import uuid
                return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"
    
    @staticmethod
    def merge_custom_fields(
        core_fields: Optional[Dict[str, Any]],
        luna_fields: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Merge custom fields from Luna into Core.
        Luna fields take precedence for conflicts.
        """
        merged = core_fields.copy() if core_fields else {}
        
        if luna_fields:
            # Track Luna-originated fields
            for key, value in luna_fields.items():
                merged[key] = value
            merged['_luna_fields'] = list(luna_fields.keys())
        
        return merged
    
    @staticmethod
    def calculate_migration_priority(
        client_data: Dict[str, Any]
    ) -> int:
        """
        Calculate migration priority score (higher = migrate first).
        Based on client activity, tier, and data completeness.
        """
        score = 0
        
        # Active clients first
        if client_data.get('status', '').lower() == 'active':
            score += 100
        
        # Premium clients
        tier = client_data.get('tier', '').lower()
        tier_scores = {'premium': 50, 'standard': 30, 'basic': 20, 'starter': 10}
        score += tier_scores.get(tier, 0)
        
        # GST registered (more compliance-critical)
        if client_data.get('gst_registered'):
            score += 25
        
        # Has recent activity
        if client_data.get('last_activity'):
            score += 15
        
        # Data completeness
        key_fields = ['abn', 'email', 'phone', 'address_line1']
        completeness = sum(1 for f in key_fields if client_data.get(f))
        score += completeness * 5
        
        return score


# ==================== AUDIT TRAIL ====================

class MigrationAuditLogger:
    """
    Logs all migration operations for audit trail.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def log_migration_event(
        self,
        event_type: str,
        client_code: str,
        source_id: Optional[str],
        target_id: Optional[str],
        status: str,
        details: Optional[Dict[str, Any]] = None,
        performed_by: str = "luna-migration"
    ):
        """Log a migration event."""
        try:
            query = text("""
                INSERT INTO public.migration_audit_log 
                (event_type, client_code, source_id, target_id, status, details, performed_by, created_at)
                VALUES (:event_type, :client_code, :source_id, :target_id, :status, 
                        CAST(:details AS jsonb), :performed_by, :created_at)
            """)
            
            import json
            await self.db.execute(query, {
                'event_type': event_type,
                'client_code': client_code,
                'source_id': source_id,
                'target_id': target_id,
                'status': status,
                'details': json.dumps(details) if details else None,
                'performed_by': performed_by,
                'created_at': datetime.now(timezone.utc)
            })
            await self.db.commit()
        except Exception as e:
            # Don't fail migration if audit logging fails
            logger.warning(f"Failed to log migration event: {e}")
    
    async def ensure_audit_table(self):
        """Create audit table if it doesn't exist."""
        try:
            query = text("""
                CREATE TABLE IF NOT EXISTS public.migration_audit_log (
                    id SERIAL PRIMARY KEY,
                    event_type VARCHAR(50) NOT NULL,
                    client_code VARCHAR(50),
                    source_id VARCHAR(100),
                    target_id VARCHAR(100),
                    status VARCHAR(20) NOT NULL,
                    details JSONB,
                    performed_by VARCHAR(100),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            await self.db.execute(query)
            await self.db.commit()
        except Exception as e:
            logger.warning(f"Could not create audit table: {e}")
