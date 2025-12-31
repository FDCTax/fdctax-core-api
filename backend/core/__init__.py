"""
Core Module - Unified Backend Services

This module provides the core backend services after consolidation:
- Client Profiles (86-field schema)
- Luna migration endpoints
- Unified identity management
"""

from .client_profiles import ClientProfileService, ClientProfile
from .migration import LunaMigrationService

__all__ = [
    'ClientProfileService',
    'ClientProfile',
    'LunaMigrationService',
]
