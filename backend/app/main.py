"""
Job Application Agent — FastAPI entrypoint.

PHASE 1-2 (per spec section 41):

    Screenshot -> preprocessing -> PP-OCRv4 -> confidence -> Ollama job extraction

POST /analyze accepts an image and returns extracted text, an aggregate
confidence score, per-block detections, and any email addresses found by
regex. Nothing beyond OCR happens yet — no LLM calls, no job-JSON
extraction, no Gmail, no LangGraph. Those arrive in later phases per the
spec's incremental build plan (section 40).
"""

from __future__ import annotations

import logging
import json
import os
import time
import uuid
from pathlib import Path
from collections.abc import Iterator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .logging_config import configure_logging
from .models.ocr_api import extract_email_candidates, extract_text as extract_external_ocr
from .ocr.confidence import is_low_confidence
from .ocr.storage import retain_recent_screenshots
from .schemas.job import JobExtractionRequest, JobExtractionResponse
from .schemas.ocr import AnalyzeResponse
from .agents.job_extraction import extract_job
from .agents.draft import stream_draft, stream_refinement
from .profile.loader import load_candidate_context
from .gmail.service import (
    authorization_url,
    finish_authorization,
    gmail_account,
    logout,
    resume_attachment_name,
    send_email,
)
from .storage.appwrite import configured as appwrite_storage_configured
from .storage.appwrite import upload_resume as upload_resume_to_appwrite

configure_logging()
logger = logging.getLogger("main")

app = FastAPI(
    title="Job Application Agent",
    description="Screenshot -> PaddleOCR -> Ollama models -> job data",
    version="0.1.0-phase1",
)

FRONTEND_DIRECTORY = Path(__file__).resolve().parent.parent.parent / "frontend"


def _is_production() -> bool:
    return settings.app_env == "production" or bool(
        os.getenv("APPWRITE_FUNCTION_ID") or os.getenv("APPWRITE_FUNCTION_NAME")
    )

configured_origins = {
    origin.strip().rstrip("/")
    for origin in settings.cors_allowed_origins.split(",")
    if origin.strip()
}
configured_origins.update({
    "http://localhost:8000",
    "https://job-application-agent.appwrite.network",
})

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(configured_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if not _is_production() and FRONTEND_DIRECTORY.is_dir():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIRECTORY), name="static")


@app.on_event("startup")
def warm_models() -> None:
    # Production OCR is an external API; local PaddleOCR remains available
    # through the local requirements and is not loaded by this app startup.
    return None

ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
MAX_UPLOAD_BYTES = settings.max_upload_size_mb * 1024 * 1024


def _extract_ocr(image_path: str, image_bytes: bytes, filename: str, content_type: str) -> dict:
    if settings.ocr_mode == "api":
        return extract_external_ocr(image_bytes, filename, content_type)
    from .models.paddle_ocr import get_ocr_model
    from .ocr.preprocessing import preprocess_image

    return get_ocr_model().extract_text(preprocess_image(image_path))


@app.get("/health")
def health() -> dict:
    profile, _, resume_name = load_candidate_context()
    return {
        "status": "ok",
        "service": "job-application-agent",
        "phase": 3,
        "profile_loaded": bool(profile),
        "resume_name": resume_name,
        "llm_provider": "ollama_cloud" if settings.llm_mode == "cloud" else "ollama_local",
        "model": settings.ollama_model,
    }


@app.get("/resume")
def resume_status() -> dict:
    _, resume_text, resume_name = load_candidate_context()
    resume_path = settings.resume_directory / resume_name if resume_name else None
    return {
        "configured": bool(resume_name),
        "name": resume_name,
        "storage": "appwrite" if appwrite_storage_configured() and settings.appwrite_resume_file_id else "local",
        "file_id": settings.appwrite_resume_file_id if appwrite_storage_configured() else "",
        "size_bytes": resume_path.stat().st_size if resume_path and resume_path.exists() else 0,
        "text_loaded": bool(resume_text.strip()),
    }


@app.get("/auth/gmail/start")
def gmail_start() -> RedirectResponse:
    try:
        return RedirectResponse(authorization_url())
    except Exception as exc:  # noqa: BLE001 - return setup error to local UI
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/auth/gmail/callback")
def gmail_callback(code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    if error:
        return RedirectResponse("/?gmail=error")
    try:
        finish_authorization(code, state)
    except Exception as exc:  # noqa: BLE001 - OAuth errors are shown after redirect
        logger.exception("GMAIL_AUTH_FAILED error=%s", exc)
        return RedirectResponse("/?gmail=error")
    return RedirectResponse("/?gmail=connected")


@app.get("/gmail/status")
def gmail_status() -> dict:
    try:
        account = gmail_account()
    except Exception as exc:  # noqa: BLE001 - status must remain safe to poll
        logger.warning("GMAIL_STATUS_FAILED error=%s", exc)
        account = ""
    return {"connected": bool(account), "account": account}


@app.post("/auth/gmail/logout")
def gmail_logout() -> dict:
    logout()
    return {"connected": False, "account": ""}


@app.post("/gmail/send")
def gmail_send(recipient: str = Form(""), subject: str = Form(""), body: str = Form("")) -> dict:
    try:
        profile, _, resume_name = load_candidate_context()
        if not resume_name:
            raise ValueError("Configure a candidate resume before sending")
        attachment_name = resume_attachment_name(str(profile.get("name", "")), resume_name)
        message_id = send_email(
            recipient,
            subject,
            body,
            attachment_path=resume_name,
            attachment_name=attachment_name,
        )
    except Exception as exc:  # noqa: BLE001 - return local Gmail error to UI
        logger.exception("GMAIL_SEND_FAILED error=%s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "sent": True,
        "message_id": message_id,
        "status": "MOCK_SENT" if settings.email_send_mode == "mock" else "SENT",
        "attachment_name": attachment_name,
        "preview": "logs/mock_email_preview.eml" if settings.email_send_mode == "mock" else "",
    }


@app.post("/resume")
async def upload_resume(file: UploadFile = File(...), file_id: str = Form("")) -> dict:
    allowed = {".pdf", ".txt", ".md", ".json"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail="Resume must be PDF, TXT, MD, or JSON.")
    raw = await file.read()
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Resume is empty or exceeds the upload limit.")
    if appwrite_storage_configured():
        try:
            stored = upload_resume_to_appwrite(raw, Path(file.filename or "resume.pdf").name, file_id)
        except Exception as exc:  # noqa: BLE001 - return safe storage error to UI
            logger.exception("APPWRITE_RESUME_UPLOAD_FAILED error=%s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"configured": True, "storage": "appwrite", **stored}
    safe_name = f"default_resume{suffix}"
    save_path = settings.resume_directory / safe_name
    for existing_path in settings.resume_directory.iterdir():
        if existing_path.is_file() and existing_path.suffix.lower() in allowed:
            existing_path.unlink()
    save_path.write_bytes(raw)
    return {"configured": True, "name": safe_name, "size_bytes": len(raw)}


@app.get("/", response_model=None)
def frontend() -> FileResponse | dict:
    if _is_production():
        return {"status": "ok", "service": "job-application-agent"}
    return FileResponse(
        FRONTEND_DIRECTORY / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=True)}\n\n"


SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@app.post("/draft")
async def draft(
    message: str = Form(""),
    instructions: str = Form(""),
    recipient: str = Form(""),
    file: UploadFile | None = File(None),
) -> StreamingResponse:
    """OCR or accept pasted text, then stream an Ollama email draft."""
    if not message.strip() and file is None:
        raise HTTPException(status_code=400, detail="Provide pasted job text or a screenshot.")

    raw: bytes | None = None
    filename = ""
    content_type = ""
    if file is not None:
        filename = file.filename or "screenshot.png"
        content_type = file.content_type or ""
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(status_code=400, detail="Screenshot must be PNG, JPEG, or WebP.")
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Uploaded screenshot is empty.")
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="Uploaded screenshot is too large.")

    def events() -> Iterator[str]:
        try:
            posting = message.strip()
            yield _sse("status", {"message": "Preparing the job posting..."})
            if raw is not None:
                suffix = Path(filename).suffix or ".png"
                save_path = settings.screenshot_directory / f"{uuid.uuid4().hex}{suffix}"
                save_path.write_bytes(raw)
                retain_recent_screenshots(settings.screenshot_directory, settings.screenshot_retention_count)
                yield _sse("status", {"message": "Reading the screenshot with PP-OCRv4..."})
                posting = _extract_ocr(str(save_path), raw, filename, content_type)["text"]
            if not posting:
                raise ValueError("No readable job text was found.")
            yield _sse("extracted_text", {"text": posting})
            profile, resume, resume_name = load_candidate_context()
            yield _sse("status", {"message": "Writing a draft with Ollama...", "resume_name": resume_name})
            trusted_recipient = recipient.strip() or next(iter(extract_email_candidates(posting)), "")
            for chunk in stream_draft(posting, profile, resume, instructions, trusted_recipient):
                yield _sse("draft_token", {"text": chunk})
            yield _sse("complete", {"resume_name": resume_name, "extracted_text": posting})
        except Exception as exc:  # noqa: BLE001 - streamed to the local UI
            logger.exception("DRAFT_FAILED error=%s", exc)
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)

@app.post("/refine")
async def refine(
    instruction: str = Form(""),
    current_draft: str = Form(""),
    posting: str = Form(""),
) -> StreamingResponse:
    """Stream a user-requested add, remove, or edit to the current draft."""
    if not instruction.strip():
        raise HTTPException(status_code=400, detail="Describe what you want to change.")
    if not current_draft.strip():
        raise HTTPException(status_code=400, detail="Create a draft before asking for edits.")

    def events() -> Iterator[str]:
        try:
            profile, resume, resume_name = load_candidate_context()
            yield _sse("status", {"message": "Applying your edit with Ollama...", "resume_name": resume_name})
            recipient = extract_email_candidates(posting)[:1]
            for chunk in stream_refinement(
                current_draft, instruction, posting, profile, resume, recipient[0] if recipient else ""
            ):
                yield _sse("draft_token", {"text": chunk})
            yield _sse("complete", {"resume_name": resume_name})
        except Exception as exc:  # noqa: BLE001 - streamed to the local UI
            logger.exception("DRAFT_REFINEMENT_FAILED error=%s", exc)
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/extract-job", response_model=JobExtractionResponse)
def extract_job_endpoint(request: JobExtractionRequest) -> JobExtractionResponse:
    """Extract structured job fields with the configured Ollama model."""
    try:
        job = extract_job(request.text, request.candidate_emails)
        return JobExtractionResponse(success=True, job=job)
    except Exception as exc:  # noqa: BLE001 - return a useful local-model error
        logger.exception("JOB_EXTRACTION_FAILED error=%s", exc)
        return JobExtractionResponse(success=False, error=str(exc))


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(file: UploadFile = File(...)) -> AnalyzeResponse:
    """
    PHASE 1 endpoint.

    1. Validate + save the uploaded screenshot (spec section 32: only
       image types, size-limited, saved only to the configured directory).
    2. Preprocess (resize / deskew).
    3. Run PaddleOCR (PP-OCRv4) text extraction.
    4. Calculate aggregate OCR confidence.
    5. Extract email candidates via regex (never via LLM — section 6).
    """
    logger.info("REQUEST_RECEIVED filename=%s content_type=%s", file.filename, file.content_type)

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{file.content_type}'. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}",
        )

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max {settings.max_upload_size_mb} MB.",
        )
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Persist the screenshot under the configured directory only (section 32).
    suffix = Path(file.filename or "screenshot.png").suffix or ".png"
    safe_name = f"{uuid.uuid4().hex}{suffix}"
    save_path = settings.screenshot_directory / safe_name
    save_path.write_bytes(raw)
    retain_recent_screenshots(settings.screenshot_directory, settings.screenshot_retention_count)

    try:
        start = time.time()

        ocr_result = _extract_ocr(
            str(save_path), raw, file.filename or "screenshot", file.content_type or "image/png"
        )

        confidence = ocr_result["confidence"]
        low_conf = is_low_confidence(confidence, settings.ocr_confidence_threshold)

        candidate_emails = extract_email_candidates(ocr_result["text"])

        logger.info(
            "OCR_CONFIDENCE value=%.4f threshold=%.2f low_confidence=%s duration=%.2fs",
            confidence,
            settings.ocr_confidence_threshold,
            low_conf,
            time.time() - start,
        )

        return AnalyzeResponse(
            success=True,
            text=ocr_result["text"],
            confidence=confidence,
            blocks=ocr_result["blocks"],
            candidate_emails=candidate_emails,
            low_confidence=low_conf,
            screenshot_path=str(save_path),
        )

    except Exception as exc:  # noqa: BLE001 - surfaced to the API caller deliberately
        logger.exception("OCR_FAILED error=%s", exc)
        return AnalyzeResponse(success=False, error=str(exc), screenshot_path=str(save_path))
