"""Pydantic schemas for the Phase 1 /analyze endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OCRBlock(BaseModel):
    text: str
    confidence: float
    bbox: list | None = None


class AnalyzeResponse(BaseModel):
    success: bool
    text: str = ""
    confidence: float = 0.0
    blocks: list[OCRBlock] = Field(default_factory=list)
    candidate_emails: list[str] = Field(default_factory=list)
    low_confidence: bool = False
    screenshot_path: str | None = None
    error: str | None = None
