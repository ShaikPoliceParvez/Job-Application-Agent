from backend.app.ocr.confidence import (
    calculate_ocr_confidence,
    has_insufficient_text,
    is_low_confidence,
)


def test_confidence_empty_blocks_is_zero():
    assert calculate_ocr_confidence([]) == 0.0


def test_confidence_single_block_matches_its_score():
    blocks = [{"text": "hello world", "confidence": 0.9}]
    assert calculate_ocr_confidence(blocks) == 0.9


def test_confidence_is_length_weighted():
    # A long, confident line should dominate a short, noisy one.
    blocks = [
        {"text": "This is a long confident line of extracted text", "confidence": 0.95},
        {"text": "x", "confidence": 0.10},
    ]
    result = calculate_ocr_confidence(blocks)
    assert result > 0.85  # much closer to 0.95 than a naive average (0.525) would be


def test_confidence_ignores_missing_fields_gracefully():
    blocks = [{"text": "abc"}]  # no confidence key
    assert calculate_ocr_confidence(blocks) == 0.0


def test_is_low_confidence_threshold():
    assert is_low_confidence(0.5, threshold=0.8) is True
    assert is_low_confidence(0.9, threshold=0.8) is False


def test_has_insufficient_text():
    assert has_insufficient_text("") is True
    assert has_insufficient_text("hi") is True
    assert has_insufficient_text("This is definitely enough text to pass.") is False
