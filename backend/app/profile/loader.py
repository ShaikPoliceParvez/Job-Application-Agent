"""Load the candidate context that is allowed into an application draft."""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.config import settings


def load_candidate_context() -> tuple[dict, str, str]:
    profile: dict = {}
    if settings.profile_path.exists():
        profile = json.loads(settings.profile_path.read_text(encoding="utf-8"))

    resume_files = sorted(
        path
        for path in settings.resume_directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".txt", ".md", ".json", ".pdf"}
    )
    if not resume_files:
        return profile, "", ""

    resume_path = resume_files[0]
    if resume_path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        resume_text = "\n".join(page.extract_text() or "" for page in PdfReader(resume_path).pages)
    else:
        resume_text = resume_path.read_text(encoding="utf-8", errors="replace")
    return profile, resume_text, resume_path.name