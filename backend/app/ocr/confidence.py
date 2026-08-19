"""
OCR confidence scoring.

Used by the LangGraph `check_ocr_confidence` node (Phase 9) to decide
whether to fall back to Gemma 3 4B vision. In Phase 1 it's just returned
in the /analyze response so the number is visible and testable early.
"""

from __future__ import annotations


def calculate_ocr_confidence(blocks: list[dict]) -> float:
    """
    Aggregate a single confidence score from PaddleOCR's per-block scores.

    Weighted by text length so a handful of long, confident lines aren't
    dragged down by a couple of short, low-confidence noise detections
    (e.g. a stray logo mark).
    """
    if not blocks:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0

    for block in blocks:
        text = block.get("text", "") or ""
        conf = block.get("confidence", 0.0) or 0.0
        weight = max(len(text.strip()), 1)
        weighted_sum += conf * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0

    return round(weighted_sum / total_weight, 4)


def is_low_confidence(confidence: float, threshold: float) -> bool:
    return confidence < threshold


def has_insufficient_text(text: str, min_chars: int = 15) -> bool:
    """Used together with confidence to decide on the Gemma vision fallback."""
    return len((text or "").strip()) < min_chars
