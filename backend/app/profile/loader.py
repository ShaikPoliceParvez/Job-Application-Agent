"""Load the candidate context that is allowed into an application draft."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import settings
from ..storage.appwrite import configured as appwrite_configured
from ..storage.appwrite import download_resume


def _resume_text(content: bytes, filename: str) -> str:
    if filename.lower().endswith(".pdf"):
        from io import BytesIO
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)
    return content.decode("utf-8", errors="replace")


def load_candidate_context() -> tuple[dict, str, str]:
    profile: dict = {}
    if settings.profile_path.exists():
        profile = json.loads(settings.profile_path.read_text(encoding="utf-8"))

    if appwrite_configured() and settings.appwrite_resume_file_id:
        resume_name = settings.appwrite_resume_filename or "resume.pdf"
        return profile, _resume_text(download_resume(), resume_name), resume_name

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