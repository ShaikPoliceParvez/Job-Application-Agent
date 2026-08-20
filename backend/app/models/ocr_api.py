"""External OCR client used by the serverless production path."""

from __future__ import annotations

import re
from typing import Any

import httpx

from backend.app.config import settings

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def extract_email_candidates(text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in EMAIL_REGEX.findall(text or ""):
        normalized = value.rstrip(".,;:")
        if normalized.lower() not in seen:
            seen.add(normalized.lower())
            result.append(normalized)
    return result


def extract_text(image_bytes: bytes, filename: str, content_type: str) -> dict[str, Any]:
    if not settings.ocr_api_url:
        raise RuntimeError("OCR_API_URL is not configured for the production OCR service.")
    headers = {"Accept": "application/json"}
    if settings.ocr_api_key:
        headers["Authorization"] = f"Bearer {settings.ocr_api_key}"
    try:
        response = httpx.post(
            settings.ocr_api_url,
            headers=headers,
            files={"file": (filename, image_bytes, content_type)},
            timeout=settings.ocr_api_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.TimeoutException as exc:
        raise RuntimeError("External OCR service timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"External OCR service returned HTTP {exc.response.status_code}.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("External OCR service request failed.") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("External OCR service returned malformed JSON.")
    text = payload.get("text", payload.get("result", ""))
    if not isinstance(text, str):
        raise RuntimeError("External OCR service returned malformed text.")
    blocks = payload.get("blocks", [])
    if not isinstance(blocks, list):
        blocks = []
    confidence = payload.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "text": text.strip(),
        "confidence": confidence,
        "blocks": blocks,
        "candidate_emails": extract_email_candidates(text),
    }