from unittest.mock import MagicMock, patch

import numpy as np

from backend.app.models.paddle_ocr import PaddleOCRModel


def test_supports_paddleocr_29_legacy_ocr_result():
    engine = MagicMock(spec=["ocr"])
    engine.ocr.return_value = [
        [
            [[[0, 0], [100, 0], [100, 20], [0, 20]], ("Hiring Python Engineer", 0.93)],
            [[[0, 30], [150, 30], [150, 50], [0, 50]], ("hr@example.com", 0.99)],
        ]
    ]
    model = PaddleOCRModel(ocr_version="PP-OCRv5")

    with patch.object(model, "_load", return_value=engine):
        result = model.extract_text(np.zeros((20, 20, 3), dtype=np.uint8))

    assert result["text"] == "Hiring Python Engineer\nhr@example.com"
    assert result["confidence"] > 0.9
    assert len(result["blocks"]) == 2