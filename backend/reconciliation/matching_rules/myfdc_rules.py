"""
MyFDC Matching Rules (A3-RECON-01)

Implements MyFDC-specific matching logic for the reconciliation engine.

Primary Match Keys:
- amount (exact or within tolerance)
- transaction_date (exact or within window)
- category_code

Secondary Heuristics:
- description similarity
- GST consistency
- attachment presence (OCR receipts)

Confidence Scoring:
- High (>0.85): Auto-match
- Medium (0.60-0.85): Suggested match
- Low (<0.60): No match
"""

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from difflib import SequenceMatcher

from reconciliation.source_registry import (
    ReconciliationSource, 
    TargetType, 
    MatchType,
    source_registry
)


@dataclass
class MatchCandidate:
    """
    A potential match candidate.
    """
    target_id: str
    target_type: TargetType
    target_reference: Optional[str]
    confidence_score: float
    match_type: MatchType
    scoring_breakdown: Dict[str, float]
    target_data: Dict[str, Any]


@dataclass
class MatchResult:
    """
    Result of matching attempt.
    """
    source_transaction_id: str
    source_type: ReconciliationSource
    candidates: List[MatchCandidate]
    best_match: Optional[MatchCandidate]
    auto_matched: bool
    suggested_match: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_transaction_id": self.source_transaction_id,
            "source_type": self.source_type.value,
            "candidates_count": len(self.candidates),
            "candidates": [
                {
                    "target_id": c.target_id,
                    "target_type": c.target_type.value,
                    "target_reference": c.target_reference,
                    "confidence_score": c.confidence_score,
                    "match_type": c.match_type.value,
                    "scoring_breakdown": c.scoring_breakdown
                }
                for c in self.candidates
            ],
            "best_match": {
                "target_id": self.best_match.target_id,
                "confidence_score": self.best_match.confidence_score
            } if self.best_match else None,
            "auto_matched": self.auto_matched,
            "suggested_match": self.suggested_match
        }


class MyFDCMatchingRules:
    """
    Matching rules engine for MyFDC transactions.
    
    Implements the scoring algorithm and matching logic
    specific to Family Day Care educator transactions.
    """
    
    # Scoring weights
    WEIGHT_AMOUNT = 0.35
    WEIGHT_DATE = 0.25
    WEIGHT_CATEGORY = 0.15
    WEIGHT_DESCRIPTION = 0.10
    WEIGHT_GST = 0.10
    WEIGHT_ATTACHMENT = 0.05
    
    # Tolerances
    AMOUNT_TOLERANCE_PERCENT = 0.01  # 1% tolerance
    DATE_TOLERANCE_DAYS = 3
    
    def __init__(self):
        self.source = ReconciliationSource.MYFDC
        self.config = source_registry.get_config(self.source)
    
    def find_matches(
        self,
        source_transaction: Dict[str, Any],
        target_transactions: List[Dict[str, Any]],
        target_type: TargetType
    ) -> MatchResult:
        """
        Find matches for a MyFDC transaction against target transactions.
        
        Args:
            source_transaction: The MyFDC transaction to match
            target_transactions: List of potential target transactions
            target_type: Type of targets being matched against
            
        Returns:
            MatchResult with candidates and best match
        """
        candidates = []
        
        for target in target_transactions:
            score, breakdown = self._score_match(source_transaction, target)
            
            if score >= self.config.suggest_match_threshold:
                match_type = self._determine_match_type(breakdown)
                
                candidates.append(MatchCandidate(
                    target_id=str(target.get('id', '')),
                    target_type=target_type,
                    target_reference=target.get('reference'),
                    confidence_score=score,
                    match_type=match_type,
                    scoring_breakdown=breakdown,
                    target_data=target
                ))
        
        # Sort by confidence score
        candidates.sort(key=lambda c: c.confidence_score, reverse=True)
        
        # Determine best match
        best_match = candidates[0] if candidates else None
        auto_matched = (
            best_match is not None and 
            best_match.confidence_score >= self.config.auto_match_threshold
        )
        suggested_match = (
            best_match is not None and
            not auto_matched and
            best_match.confidence_score >= self.config.suggest_match_threshold
        )
        
        return MatchResult(
            source_transaction_id=str(source_transaction.get('id', '')),
            source_type=self.source,
            candidates=candidates,
            best_match=best_match,
            auto_matched=auto_matched,
            suggested_match=suggested_match
        )
    
    def _score_match(
        self,
        source: Dict[str, Any],
        target: Dict[str, Any]
    ) -> Tuple[float, Dict[str, float]]:
        """
        Score the match between source and target transactions.
        
        Returns:
            Tuple of (total_score, scoring_breakdown)
        """
        breakdown = {}
        
        # Amount matching
        amount_score = self._score_amount(source, target)
        breakdown['amount'] = amount_score
        
        # Date matching
        date_score = self._score_date(source, target)
        breakdown['date'] = date_score
        
        # Category matching
        category_score = self._score_category(source, target)
        breakdown['category'] = category_score
        
        # Description similarity
        description_score = self._score_description(source, target)
        breakdown['description'] = description_score
        
        # GST consistency
        gst_score = self._score_gst(source, target)
        breakdown['gst'] = gst_score
        
        # Attachment presence
        attachment_score = self._score_attachment(source, target)
        breakdown['attachment'] = attachment_score
        
        # Calculate weighted total
        total_score = (
            amount_score * self.WEIGHT_AMOUNT +
            date_score * self.WEIGHT_DATE +
            category_score * self.WEIGHT_CATEGORY +
            description_score * self.WEIGHT_DESCRIPTION +
            gst_score * self.WEIGHT_GST +
            attachment_score * self.WEIGHT_ATTACHMENT
        )
        
        breakdown['total'] = round(total_score, 4)
        
        return total_score, breakdown
    
    def _score_amount(self, source: Dict, target: Dict) -> float:
        """Score amount matching."""
        try:
            source_amount = abs(Decimal(str(source.get('amount', 0))))
            target_amount = abs(Decimal(str(target.get('amount', 0))))
            
            if source_amount == 0 and target_amount == 0:
                return 1.0
            
            if source_amount == 0 or target_amount == 0:
                return 0.0
            
            # Exact match
            if source_amount == target_amount:
                return 1.0
            
            # Within tolerance
            tolerance = source_amount * Decimal(str(self.AMOUNT_TOLERANCE_PERCENT))
            diff = abs(source_amount - target_amount)
            
            if diff <= tolerance:
                return 0.95
            
            # Proportional scoring for larger differences
            percent_diff = float(diff / source_amount)
            if percent_diff <= 0.05:  # 5%
                return 0.8
            elif percent_diff <= 0.10:  # 10%
                return 0.6
            elif percent_diff <= 0.20:  # 20%
                return 0.3
            
            return 0.0
            
        except (ValueError, TypeError):
            return 0.0
    
    def _score_date(self, source: Dict, target: Dict) -> float:
        """Score date matching."""
        try:
            source_date = source.get('transaction_date')
            target_date = target.get('date') or target.get('transaction_date')
            
            if not source_date or not target_date:
                return 0.5  # Neutral score if date missing
            
            # Parse dates if strings
            if isinstance(source_date, str):
                source_date = date.fromisoformat(source_date)
            if isinstance(target_date, str):
                target_date = date.fromisoformat(target_date)
            
            # Exact match
            if source_date == target_date:
                return 1.0
            
            # Within tolerance
            diff = abs((source_date - target_date).days)
            
            if diff <= 1:
                return 0.9
            elif diff <= self.DATE_TOLERANCE_DAYS:
                return 0.7
            elif diff <= 7:
                return 0.4
            elif diff <= 14:
                return 0.2
            
            return 0.0
            
        except (ValueError, TypeError):
            return 0.5
    
    def _score_category(self, source: Dict, target: Dict) -> float:
        """Score category matching."""
        source_code = source.get('category_code', '')
        target_code = target.get('category_code', '') or target.get('category', '')
        
        if not source_code or not target_code:
            return 0.5  # Neutral score
        
        # Exact match
        if source_code == target_code:
            return 1.0
        
        # Same category group (first 2 digits)
        if source_code[:2] == target_code[:2]:
            return 0.7
        
        return 0.3
    
    def _score_description(self, source: Dict, target: Dict) -> float:
        """Score description similarity using fuzzy matching."""
        source_desc = (source.get('description', '') or '').lower().strip()
        target_desc = (target.get('description', '') or target.get('memo', '') or '').lower().strip()
        
        if not source_desc or not target_desc:
            return 0.5  # Neutral score
        
        # Use sequence matcher for similarity
        similarity = SequenceMatcher(None, source_desc, target_desc).ratio()
        
        return similarity
    
    def _score_gst(self, source: Dict, target: Dict) -> float:
        """Score GST consistency."""
        source_gst = source.get('gst_included', True)
        target_gst = target.get('gst_included', True)
        
        # Both have same GST status
        if source_gst == target_gst:
            return 1.0
        
        return 0.5
    
    def _score_attachment(self, source: Dict, target: Dict) -> float:
        """Score attachment presence."""
        source_attachments = source.get('attachments', []) or []
        target_attachments = target.get('attachments', []) or []
        
        # Both have attachments
        if source_attachments and target_attachments:
            return 1.0
        
        # One has attachments
        if source_attachments or target_attachments:
            return 0.7
        
        # Neither has attachments
        return 0.5
    
    def _determine_match_type(self, breakdown: Dict[str, float]) -> MatchType:
        """Determine the type of match based on scoring breakdown."""
        amount_score = breakdown.get('amount', 0)
        date_score = breakdown.get('date', 0)
        
        # Exact match: all scores very high
        if amount_score >= 0.95 and date_score >= 0.9:
            return MatchType.EXACT
        
        # Amount and date match
        if amount_score >= 0.8 and date_score >= 0.7:
            return MatchType.AMOUNT_DATE
        
        # Amount only
        if amount_score >= 0.8:
            return MatchType.AMOUNT_ONLY
        
        return MatchType.FUZZY


# Instantiate rules engine
myfdc_rules = MyFDCMatchingRules()
