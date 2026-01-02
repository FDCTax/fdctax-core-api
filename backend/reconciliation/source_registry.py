"""
Reconciliation Source Registry (A3-RECON-01)

Central registry of all supported reconciliation sources.
Each source has:
- Unique identifier
- Display name
- Matching priority
- Configuration options

Supported Sources:
- MYFDC: Family Day Care educator transactions
- OCR: Scanned receipts and invoices
- BANK_FEED: Bank transaction imports
- MANUAL: Manually entered transactions
"""

from enum import Enum
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


class ReconciliationSource(str, Enum):
    """
    Recognised reconciliation sources.
    
    These are the first-class sources that the reconciliation
    engine can match transactions from.
    """
    MYFDC = "MYFDC"
    OCR = "OCR"
    BANK_FEED = "BANK_FEED"
    MANUAL = "MANUAL"


class TargetType(str, Enum):
    """
    Types of targets for reconciliation matching.
    
    A source transaction can be matched against these target types.
    """
    BANK = "BANK"
    RECEIPT = "RECEIPT"
    INVOICE = "INVOICE"
    MANUAL = "MANUAL"
    UNKNOWN = "UNKNOWN"


class MatchStatus(str, Enum):
    """
    Status of a reconciliation match.
    """
    PENDING = "PENDING"         # Awaiting processing
    MATCHED = "MATCHED"         # Auto-matched with high confidence
    SUGGESTED = "SUGGESTED"     # Medium confidence, needs review
    NO_MATCH = "NO_MATCH"       # No suitable match found
    REJECTED = "REJECTED"       # User rejected suggested match
    CONFIRMED = "CONFIRMED"     # User confirmed the match


class MatchType(str, Enum):
    """
    Types of matches.
    """
    EXACT = "EXACT"             # All criteria match exactly
    AMOUNT_DATE = "AMOUNT_DATE" # Amount and date match
    AMOUNT_ONLY = "AMOUNT_ONLY" # Only amount matches
    FUZZY = "FUZZY"             # Fuzzy matching used
    MANUAL = "MANUAL"           # Manually matched by user


@dataclass
class SourceConfig:
    """
    Configuration for a reconciliation source.
    """
    source: ReconciliationSource
    display_name: str
    priority: int  # Lower = higher priority for matching
    enabled: bool
    match_targets: List[TargetType]  # What this source can match against
    auto_match_threshold: float  # Confidence threshold for auto-matching
    suggest_match_threshold: float  # Threshold for suggesting matches
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source.value,
            "display_name": self.display_name,
            "priority": self.priority,
            "enabled": self.enabled,
            "match_targets": [t.value for t in self.match_targets],
            "auto_match_threshold": self.auto_match_threshold,
            "suggest_match_threshold": self.suggest_match_threshold
        }


class SourceRegistry:
    """
    Central registry for reconciliation sources.
    
    Manages source configurations and provides lookup methods
    for the matching engine.
    """
    
    # Default configurations for each source
    _default_configs: Dict[ReconciliationSource, SourceConfig] = {
        ReconciliationSource.MYFDC: SourceConfig(
            source=ReconciliationSource.MYFDC,
            display_name="MyFDC Transactions",
            priority=1,  # Highest priority
            enabled=True,
            match_targets=[TargetType.BANK, TargetType.RECEIPT, TargetType.INVOICE],
            auto_match_threshold=0.85,
            suggest_match_threshold=0.60
        ),
        ReconciliationSource.OCR: SourceConfig(
            source=ReconciliationSource.OCR,
            display_name="OCR Scanned Documents",
            priority=2,
            enabled=True,
            match_targets=[TargetType.BANK, TargetType.MANUAL],
            auto_match_threshold=0.80,
            suggest_match_threshold=0.55
        ),
        ReconciliationSource.BANK_FEED: SourceConfig(
            source=ReconciliationSource.BANK_FEED,
            display_name="Bank Feed Transactions",
            priority=3,
            enabled=True,
            match_targets=[TargetType.RECEIPT, TargetType.INVOICE, TargetType.MANUAL],
            auto_match_threshold=0.90,
            suggest_match_threshold=0.65
        ),
        ReconciliationSource.MANUAL: SourceConfig(
            source=ReconciliationSource.MANUAL,
            display_name="Manual Entries",
            priority=4,
            enabled=True,
            match_targets=[TargetType.BANK, TargetType.RECEIPT],
            auto_match_threshold=0.75,
            suggest_match_threshold=0.50
        ),
    }
    
    def __init__(self):
        self._configs = dict(self._default_configs)
    
    def get_config(self, source: ReconciliationSource) -> Optional[SourceConfig]:
        """Get configuration for a source."""
        return self._configs.get(source)
    
    def get_all_configs(self) -> List[SourceConfig]:
        """Get all source configurations."""
        return list(self._configs.values())
    
    def get_enabled_sources(self) -> List[ReconciliationSource]:
        """Get list of enabled sources."""
        return [
            cfg.source for cfg in self._configs.values()
            if cfg.enabled
        ]
    
    def is_source_enabled(self, source: ReconciliationSource) -> bool:
        """Check if a source is enabled."""
        cfg = self._configs.get(source)
        return cfg.enabled if cfg else False
    
    def get_match_targets(self, source: ReconciliationSource) -> List[TargetType]:
        """Get valid match targets for a source."""
        cfg = self._configs.get(source)
        return cfg.match_targets if cfg else []
    
    def get_auto_match_threshold(self, source: ReconciliationSource) -> float:
        """Get auto-match confidence threshold for a source."""
        cfg = self._configs.get(source)
        return cfg.auto_match_threshold if cfg else 0.85
    
    def get_suggest_match_threshold(self, source: ReconciliationSource) -> float:
        """Get suggest-match confidence threshold for a source."""
        cfg = self._configs.get(source)
        return cfg.suggest_match_threshold if cfg else 0.60
    
    def update_config(self, source: ReconciliationSource, **kwargs):
        """Update configuration for a source."""
        if source not in self._configs:
            return
        
        cfg = self._configs[source]
        for key, value in kwargs.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
    
    def to_dict(self) -> Dict[str, Any]:
        """Export registry as dictionary."""
        return {
            source.value: cfg.to_dict()
            for source, cfg in self._configs.items()
        }


# Global registry instance
source_registry = SourceRegistry()
