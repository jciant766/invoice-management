"""
Fuzzy Supplier Matching Service

Algorithmically matches extracted supplier names to existing suppliers in the database
using multiple string similarity techniques.
"""

from typing import List, Dict, Tuple, Optional
import re
from difflib import SequenceMatcher


def normalize_company_name(name: str) -> str:
    """
    Normalize a company name for comparison.

    - Convert to lowercase
    - Remove common suffixes (Ltd, Limited, Inc, etc.)
    - Remove punctuation
    - Collapse whitespace
    """
    if not name:
        return ""

    # Convert to lowercase
    name = name.lower().strip()

    # Remove common company suffixes (only at end of string or before punctuation)
    # This prevents removing "co" from "test & co" but removes "ltd" from "abc ltd"
    suffixes = [
        r'\blimited\s*$', r'\bltd\.?\s*$', r'\bllc\.?\s*$', r'\binc\.?\s*$',
        r'\bcorporation\s*$', r'\bcorp\.?\s*$', r'\bco\.?\s*$',
        r'\bplc\.?\s*$', r'\bkummercjali\s*$', r'\bp\.l\.c\.?\s*$',
        r'\bcompany\s*$'
    ]
    for suffix in suffixes:
        name = re.sub(suffix, '', name)

    # Remove punctuation and extra whitespace
    name = re.sub(r'[^\w\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()

    return name


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Calculate the Levenshtein distance between two strings.

    This measures the minimum number of single-character edits (insertions,
    deletions, or substitutions) required to change one string into another.
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Cost of insertions, deletions, or substitutions
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def calculate_similarity_score(extracted: str, existing: str) -> float:
    """
    Calculate a similarity score between 0.0 and 1.0.

    Uses multiple techniques:
    1. Exact match on normalized names (1.0 score)
    2. Sequence matching (difflib)
    3. Levenshtein distance
    4. Token overlap (word-level matching)

    Returns:
        Float between 0.0 (no match) and 1.0 (perfect match)
    """
    if not extracted or not existing:
        return 0.0

    # Normalize both names
    extracted_norm = normalize_company_name(extracted)
    existing_norm = normalize_company_name(existing)

    # Exact match on normalized names
    if extracted_norm == existing_norm:
        return 1.0

    # If either is empty after normalization, no match
    if not extracted_norm or not existing_norm:
        return 0.0

    # 1. Sequence matching (Python's difflib)
    sequence_score = SequenceMatcher(None, extracted_norm, existing_norm).ratio()

    # 2. Levenshtein distance normalized
    max_len = max(len(extracted_norm), len(existing_norm))
    lev_distance = levenshtein_distance(extracted_norm, existing_norm)
    lev_score = 1.0 - (lev_distance / max_len)

    # 3. Token-based matching (word overlap)
    extracted_tokens = set(extracted_norm.split())
    existing_tokens = set(existing_norm.split())

    if extracted_tokens and existing_tokens:
        # Jaccard similarity: intersection / union
        intersection = len(extracted_tokens & existing_tokens)
        union = len(extracted_tokens | existing_tokens)
        token_score = intersection / union if union > 0 else 0.0
    else:
        token_score = 0.0

    # 4. Check if one name contains the other (substring match)
    substring_score = 0.0
    if extracted_norm in existing_norm or existing_norm in extracted_norm:
        shorter = min(len(extracted_norm), len(existing_norm))
        longer = max(len(extracted_norm), len(existing_norm))
        substring_score = shorter / longer if longer > 0 else 0.0

    # Weighted combination of all scores
    # Sequence matching and Levenshtein are most reliable, so weight them higher
    final_score = (
        sequence_score * 0.35 +
        lev_score * 0.35 +
        token_score * 0.20 +
        substring_score * 0.10
    )

    return final_score


def find_supplier_matches(
    extracted_name: str,
    existing_suppliers: List[Dict],
    top_k: int = 5,
    auto_select_threshold: float = 0.90
) -> Dict:
    """
    Find the best matching suppliers for an extracted name.

    Args:
        extracted_name: The supplier name extracted by AI
        existing_suppliers: List of dicts with 'id' and 'name' keys
        top_k: Number of top matches to return
        auto_select_threshold: Confidence threshold for auto-selection (default 0.90 = 90%)

    Returns:
        {
            "matches": [
                {
                    "supplier_id": int,
                    "supplier_name": str,
                    "confidence": float,  # 0.0 to 1.0
                    "confidence_label": str  # "Exact", "High", "Medium", "Low"
                },
                ...
            ],
            "auto_selected": {  # Only present if a match exceeds threshold
                "supplier_id": int,
                "supplier_name": str,
                "confidence": float
            } or None,
            "is_new_supplier": bool  # True if no good matches found
        }
    """
    if not extracted_name or not existing_suppliers:
        return {
            "matches": [],
            "auto_selected": None,
            "is_new_supplier": True
        }

    # Calculate similarity for all suppliers
    scored_suppliers = []
    for supplier in existing_suppliers:
        # Validate supplier has required fields
        if 'name' not in supplier or 'id' not in supplier:
            continue  # Skip malformed supplier data

        score = calculate_similarity_score(extracted_name, supplier['name'])
        scored_suppliers.append({
            "supplier_id": supplier['id'],
            "supplier_name": supplier['name'],
            "confidence": round(score, 3)
        })

    # Sort by confidence (descending)
    scored_suppliers.sort(key=lambda x: x['confidence'], reverse=True)

    # Take top K
    top_matches = scored_suppliers[:top_k]

    # Add confidence labels
    for match in top_matches:
        conf = match['confidence']
        if conf >= 0.95:
            match['confidence_label'] = "Exact"
        elif conf >= 0.80:
            match['confidence_label'] = "High"
        elif conf >= 0.60:
            match['confidence_label'] = "Medium"
        else:
            match['confidence_label'] = "Low"

    # Check if we should auto-select
    best_match = top_matches[0] if top_matches else None
    auto_selected = None
    is_new_supplier = True

    if best_match and best_match['confidence'] >= auto_select_threshold:
        auto_selected = {
            "supplier_id": best_match['supplier_id'],
            "supplier_name": best_match['supplier_name'],
            "confidence": best_match['confidence']
        }
        is_new_supplier = False
    elif best_match and best_match['confidence'] >= 0.70:
        # Good match, but not confident enough to auto-select
        is_new_supplier = False

    return {
        "matches": top_matches,
        "auto_selected": auto_selected,
        "is_new_supplier": is_new_supplier,
        "extracted_name": extracted_name
    }


def get_match_explanation(confidence: float) -> str:
    """
    Get a human-readable explanation for a confidence score.

    Args:
        confidence: Score between 0.0 and 1.0

    Returns:
        Explanation string
    """
    if confidence >= 0.95:
        return "Exact or near-exact match"
    elif confidence >= 0.85:
        return "Very strong match, minor differences"
    elif confidence >= 0.75:
        return "Strong match, some variations"
    elif confidence >= 0.65:
        return "Good match, noticeable differences"
    elif confidence >= 0.50:
        return "Moderate match, significant differences"
    else:
        return "Weak match, consider as new supplier"
