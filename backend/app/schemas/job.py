"""Contracts for structured job extraction."""

from __future__ import annotations

from pydantic import BaseModel, Field


class JobPosting(BaseModel):
    company: str = ""
    role: str = ""
    hr_name: str = ""
    recipient_email: str = ""
    requirements: list[str] = Field(default_factory=list)
    deadline: str = ""


class JobExtractionRequest(BaseModel):
    text: str = Field(min_length=1)
    candidate_emails: list[str] = Field(default_factory=list)


class JobExtractionResponse(BaseModel):
    success: bool
    job: JobPosting | None = None
    error: str | None = None