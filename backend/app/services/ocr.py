"""Server-side client for the official PaddleOCR PP-OCRv5 API."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.config import settings
from backend.app.ocr.confidence import calculate_ocr_confidence


class OCRError(RuntimeError):
    """Raised when the hosted OCR service cannot process a document."""


EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def extract_email_candidates(text: str) -> list[str]:
    found = EMAIL_REGEX.findall(text or "")
    seen: set[str] = set()
    result: list[str] = []
    for email in found:
        normalized = email.strip().rstrip(".,;:")
        if normalized.lower() not in seen:
            seen.add(normalized.lower())
            result.append(normalized)
    return result


def _file_type(filename: str, content_type: str) -> int:
    suffix = Path(filename).suffix.lower()
    if content_type == "application/pdf" or suffix == ".pdf":
        return 0
    return 1


def _blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result") or {}
    blocks: list[dict[str, Any]] = []
    for page in result.get("ocrResults") or []:
        data = page.get("prunedResult") or {}
        texts = data.get("rec_texts") or []
        scores = data.get("rec_scores") or []
        boxes = data.get("rec_polys") or data.get("dt_polys") or []
        for index, text in enumerate(texts):
            if not text:
                continue
            score = float(scores[index]) if index < len(scores) else 0.0
            bbox = boxes[index] if index < len(boxes) else None
            blocks.append({"text": str(text), "confidence": round(score, 4), "bbox": bbox})
    return blocks


def extract_text(raw: bytes, filename: str, content_type: str) -> dict[str, Any]:
    if not settings.paddleocr_api_url:
        raise OCRError("PADDLEOCR_API_URL is not configured.")
    if not settings.paddleocr_access_token:
        raise OCRError("PADDLEOCR_ACCESS_TOKEN is not configured.")

    payload = {
        "file": base64.b64encode(raw).decode("ascii"),
        "fileType": _file_type(filename, content_type),
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useTextlineOrientation": False,
    }
    request = Request(
        settings.paddleocr_api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"token {settings.paddleocr_access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=settings.paddleocr_timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise OCRError("PaddleOCR authentication failed. Check PADDLEOCR_ACCESS_TOKEN.") from exc
        if exc.code == 429:
            raise OCRError("PaddleOCR quota was exceeded. Try again later.") from exc
        raise OCRError("PaddleOCR request failed.") from exc
    except (URLError, TimeoutError) as exc:
        raise OCRError("PaddleOCR request failed due to a network or timeout error.") from exc
    except json.JSONDecodeError as exc:
        raise OCRError("PaddleOCR returned malformed JSON.") from exc

    if not isinstance(body, dict) or body.get("errorCode", 0) not in (0, None):
        message = body.get("errorMsg", "PaddleOCR returned an error.") if isinstance(body, dict) else "PaddleOCR returned an invalid response."
        raise OCRError(str(message))

    blocks = _blocks(body)
    return {
        "text": "\n".join(block["text"] for block in blocks),
        "confidence": calculate_ocr_confidence(blocks),
        "blocks": blocks,
    }
