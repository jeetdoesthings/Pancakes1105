"""
Product Normalization Layer
============================
Maps extracted product names from RFPs to internal catalog entries
using fuzzy string matching and semantic similarity scoring.

Design Principle: Structured over Prompt-Based (Section 7.1)
"""

import json
import os
from difflib import SequenceMatcher
from typing import Optional, List, Dict, Any
from app.config import settings


def _load_catalog() -> List[Dict[str, Any]]:
    """Load the internal product catalog."""
    filepath = os.path.join(settings.DATA_DIR, "internal_pricing.json")
    with open(filepath, "r") as f:
        data = json.load(f)
    return data.get("products", [])


def normalize_product_name(query: str, threshold: float = 0.35) -> Optional[Dict[str, Any]]:
    """
    Fuzzy-match an extracted product name against the internal catalog.
    
    Uses SequenceMatcher for token-level similarity across both the
    product name and description fields.
    
    Args:
        query: The raw product name extracted from the RFP.
        threshold: Minimum similarity score (0.0-1.0) to accept a match.
    
    Returns:
        The best-matching product dict, or None if no match exceeds threshold.
    """
    catalog = _load_catalog()
    query_lower = query.lower().strip()
    
    best_match = None
    best_score = 0.0
    
    for product in catalog:
        # Score against product ID, name, description, and category
        candidates = [
            product["id"].lower(),
            product["name"].lower(),
            product.get("description", "").lower(),
            product.get("category", "").lower(),
        ]
        
        # Take the highest similarity across all candidate fields
        scores = [SequenceMatcher(None, query_lower, c).ratio() for c in candidates]
        
        # Bonus: if the query is a substring of the name or vice versa
        name_lower = product["name"].lower()
        if query_lower in name_lower or name_lower in query_lower:
            scores.append(0.85)
        
        # Check for keyword overlap (split tokens)
        query_tokens = set(query_lower.split())
        name_tokens = set(name_lower.split())
        overlap = query_tokens & name_tokens
        if overlap:
            token_score = len(overlap) / max(len(query_tokens), len(name_tokens))
            scores.append(token_score)
        
        max_score = max(scores)
        if max_score > best_score:
            best_score = max_score
            best_match = product
    
    if best_score >= threshold and best_match:
        return best_match
    return None


def normalize_all_items(scope_items: list) -> List[Dict[str, Any]]:
    """
    Normalize a list of scope items against the internal catalog.
    Returns a list of dicts with the original item and its matched product (if any).
    """
    results = []
    for item in scope_items:
        match = normalize_product_name(item.item_name)
        results.append({
            "original_name": item.item_name,
            "matched_product": match,
            "match_confidence": "high" if match else "none",
        })
    return results
