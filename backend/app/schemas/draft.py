"""Streaming draft response contracts."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DraftRequest(BaseModel):
    message: str = Field(min_length=1)


class DraftComplete(BaseModel):
    resume_name: str = ""
    extracted_text: str