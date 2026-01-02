"""
Reconciliation Engine Module (A3-RECON-01)

Provides transaction matching and reconciliation capabilities:
- MyFDC transaction matching against bank feeds
- Configurable confidence thresholds
- Auto-matching for high confidence
- Suggested matches for review
- Audit trail for all operations
"""

from reconciliation.source_registry import (
    ReconciliationSource,
    TargetType,
    MatchStatus,
    MatchType,
    SourceConfig,
    SourceRegistry,
    source_registry
)
from reconciliation.matching_rules.myfdc_rules import (
    MyFDCMatchingRules,
    MatchCandidate,
    MatchResult,
    myfdc_rules
)
from reconciliation.services.reconciliation_service import ReconciliationService
from reconciliation.endpoints.reconciliation_api import router as reconciliation_router

__all__ = [
    # Source Registry
    'ReconciliationSource',
    'TargetType',
    'MatchStatus',
    'MatchType',
    'SourceConfig',
    'SourceRegistry',
    'source_registry',
    # Matching Rules
    'MyFDCMatchingRules',
    'MatchCandidate',
    'MatchResult',
    'myfdc_rules',
    # Service
    'ReconciliationService',
    # Router
    'reconciliation_router'
]
