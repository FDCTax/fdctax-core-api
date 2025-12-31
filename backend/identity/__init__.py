"""
Identity Spine Module

This module provides unified identity management for MyFDC and CRM,
ensuring a single source of truth for user identity.

Features:
- Unified person model (email as primary key)
- MyFDC account management
- CRM client management
- Identity linking and deduplication
- Engagement profile tracking
"""

from .models import (
    PersonDB,
    MyFDCAccountDB,
    CRMClientIdentityDB,
    EngagementProfileDB,
    IdentityLinkLogDB,
    PersonStatus,
    EntityType
)
from .service import IdentityService

__all__ = [
    'PersonDB',
    'MyFDCAccountDB',
    'CRMClientIdentityDB',
    'EngagementProfileDB',
    'IdentityLinkLogDB',
    'PersonStatus',
    'EntityType',
    'IdentityService'
]
