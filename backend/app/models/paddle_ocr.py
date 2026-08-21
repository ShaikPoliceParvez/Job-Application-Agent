"""
PaddleOCR model wrapper (PP-OCRv5 Mobile with paddleocr==3.0.3).

Responsibility per spec section 4: TEXT EXTRACTION ONLY.
No "understanding" happens here — that's Qwen3's job (Phase 2+).

Lazy-loaded (spec section 36): the underlying PaddleOCR engine is only
constructed the first time `extract_text()` is called, and reused after
that (loading the models is the expensive part, not running them).
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import numpy as np

from backend.app.config import settings
from backend.app.models.base import OCRModel

logger = logging.getLogger("models.paddle_ocr")

# Simple, conservative email regex. Deliberately not "clever" -
# spec section 6 requires the LLM to never invent emails, so this
# regex is the sole source of truth for candidate emails alongside
# explicit user input.
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


class PaddleOCRModel(OCRModel):
    """Thin, lazy wrapper around paddleocr.PaddleOCR."""

    def __init__(self, lang: str | None = None, ocr_version: str = "PP-OCRv5"):
        self._lang = lang or settings.ocr_lang
        self._ocr_version = ocr_version
        self._engine = None  # lazy

    def _load(self):
        if self._engine is not None:
            return self._engine

        logger.info(
            "MODEL_LOADING PaddleOCR ocr_version=%s lang=%s (first use, lazy)",
            self._ocr_version,
            self._lang,
        )
        start = time.time()

        # Imported here (not at module top) so importing this module never
        # triggers the heavy paddle import / model load as a side effect.
        from paddleocr import PaddleOCR

        self._engine = PaddleOCR(
            lang=self._lang,
            ocr_version=self._ocr_version,
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="PP-OCRv5_mobile_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device="cpu",
        )

        logger.info("MODEL_LOADED PaddleOCR in %.2fs", time.time() - start)
        return self._engine

    def warmup(self) -> None:
        """Load and run one tiny inference before the first user request."""
        engine = self._load()
        if hasattr(engine, "predict"):
            engine.predict(np.zeros((64, 64, 3), dtype=np.uint8))

    def extract_text(self, image: "str | np.ndarray") -> dict[str, Any]:
        """
        Run OCR on either a file path or an already-preprocessed numpy array
        (e.g. the output of app.ocr.preprocessing.preprocess_image).

        Returns:
            {
                "text": "...",              # all detected lines joined
                "confidence": 0.95,          # aggregate, see ocr/confidence.py
                "blocks": [
                    {"text": "...", "confidence": 0.97, "bbox": [[x,y],...]}
                ]
            }
        """
        engine = self._load()

        logger.info("OCR_STARTED image=%s", image if isinstance(image, str) else "<array>")
        start = time.time()

        if hasattr(engine, "predict"):
            result = engine.predict(image)
            pages = result
        else:
            # Keep compatibility with the legacy OCR result shape used by older engines.
            result = engine.ocr(image, cls=True)
            pages = [{"legacy_lines": page or []} for page in (result or [])]

        blocks: list[dict[str, Any]] = []
        for page in result:
            if isinstance(page, dict):
                texts = page.get("rec_texts", []) or []
                scores = page.get("rec_scores", []) or []
                polys = page.get("rec_polys", None)
                if polys is None:
                    polys = page.get("dt_polys", [None] * len(texts))
            else:
                continue

            for i, text in enumerate(texts):
                score = float(scores[i]) if i < len(scores) else 0.0
                bbox = polys[i] if i < len(polys) else None
                if isinstance(bbox, np.ndarray):
                    bbox = bbox.tolist()
                blocks.append({"text": text, "confidence": round(score, 4), "bbox": bbox})

        if not blocks and not hasattr(engine, "predict"):
            for page in pages:
                for line in page["legacy_lines"]:
                    if len(line) < 2:
                        continue
                    text_score = line[1]
                    if not isinstance(text_score, (list, tuple)) or len(text_score) < 2:
                        continue
                    text, score = text_score[0], text_score[1]
                    blocks.append({
                        "text": str(text),
                        "confidence": round(float(score), 4),
                        "bbox": line[0],
                    })

        full_text = "\n".join(b["text"] for b in blocks if b["text"])

        from backend.app.ocr.confidence import calculate_ocr_confidence

        confidence = calculate_ocr_confidence(blocks)

        logger.info(
            "OCR_COMPLETED blocks=%d confidence=%.4f duration=%.2fs",
            len(blocks),
            confidence,
            time.time() - start,
        )

        return {"text": full_text, "confidence": confidence, "blocks": blocks}


def extract_email_candidates(text: str) -> list[str]:
    """
    Pull every email-looking string out of OCR text via regex ONLY.

    Spec section 6: the LLM must never invent a recipient email — this
    function (plus explicit user input) is the sole allowed source.
    Order-preserving de-duplication so the "first seen" email stays first.
    """
    found = EMAIL_REGEX.findall(text or "")
    seen: set[str] = set()
    unique: list[str] = []
    for email in found:
        normalized = email.strip().rstrip(".,;:")
        key = normalized.lower()
        if key not in seen:
            seen.add(key)
            unique.append(normalized)
    return unique


# Module-level singleton so FastAPI request handlers share one loaded
# model instead of re-instantiating (and re-loading weights) per request.
_ocr_model: PaddleOCRModel | None = None


def get_ocr_model() -> PaddleOCRModel:
    global _ocr_model
    if _ocr_model is None:
        _ocr_model = PaddleOCRModel(ocr_version=settings.model_ocr)
    return _ocr_model
