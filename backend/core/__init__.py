"""
Core Module - Unified Backend Services

This module provides the core backend services after consolidation:
- Client Profiles (86-field schema)
- Luna migration endpoints
- Unified identity management
- Business logic validation (Phase 4)
"""

from .client_profiles import ClientProfileService, ClientProfile
from .migration import LunaMigrationService
from .luna_business_logic import (
    ClientValidator,
    ClientMatcher,
    LunaBusinessRules,
    MigrationHelpers,
    MigrationAuditLogger
)

__all__ = [
    'ClientProfileService',
    'ClientProfile',
    'LunaMigrationService',
    # Phase 4 additions
    'ClientValidator',
    'ClientMatcher',
    'LunaBusinessRules',
    'MigrationHelpers',
    'MigrationAuditLogger',
]
