"""
Job Application Agent — FastAPI entrypoint.

PHASE 1-2 (per spec section 41):

    Upload -> hosted PP-OCRv5 -> confidence -> Groq job extraction

POST /analyze accepts an image and returns extracted text, an aggregate
confidence score, per-block detections, and any email addresses found by
regex. Nothing beyond OCR happens yet — no LLM calls, no job-JSON
extraction, no Gmail, no LangGraph. Those arrive in later phases per the
spec's incremental build plan (section 40).
"""

from __future__ import annotations

import logging
import json
import time
import uuid
from pathlib import Path
from collections.abc import Iterator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import settings
from backend.app.logging_config import configure_logging
from backend.app.services.ocr import extract_email_candidates
from backend.app.ocr.confidence import is_low_confidence
from backend.app.services.ocr import extract_text as extract_ocr_text
from backend.app.schemas.job import JobExtractionRequest, JobExtractionResponse
from backend.app.schemas.ocr import AnalyzeResponse
from backend.app.agents.job_extraction import extract_job
from backend.app.agents.draft import stream_draft, stream_refinement
from backend.app.profile.loader import load_candidate_context
from backend.app.gmail.service import (
    authorization_url,
    finish_authorization,
    gmail_account,
    logout,
    resume_attachment_name,
    send_email,
)

configure_logging()
logger = logging.getLogger("main")

app = FastAPI(
    title="Job Application Agent",
    description="Uploads -> hosted PP-OCRv5 -> Groq -> job data",
    version="0.1.0-phase1",
)

FRONTEND_DIRECTORY = Path(__file__).resolve().parent.parent.parent / "frontend"

allowed_origins = [origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=FRONTEND_DIRECTORY), name="static")


ALLOWED_CONTENT_TYPES = set(settings.allowed_upload_types)
MAX_UPLOAD_BYTES = settings.max_upload_size_mb * 1024 * 1024


@app.get("/health")
def health() -> dict:
    profile, _, resume_name = load_candidate_context()
    return {
        "status": "ok",
        "phase": 3,
        "profile_loaded": bool(profile),
        "resume_name": resume_name,
        "llm_provider": "groq",
        "model": settings.groq_model,
    }


@app.get("/resume")
def resume_status() -> dict:
    return {
        "configured": False,
        "name": "",
        "storage": "session",
        "file_id": "",
        "size_bytes": 0,
        "text_loaded": False,
    }


@app.get("/auth/gmail/start")
def gmail_start() -> RedirectResponse:
    try:
        return RedirectResponse(authorization_url())
    except Exception as exc:  # noqa: BLE001 - return setup error to the UI
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
async def gmail_send(
    recipient: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
    file: UploadFile | None = File(None),
) -> dict:
    try:
        profile, _, resume_name = load_candidate_context()
        attachment_bytes = None
        attachment_source_name = resume_name
        if file is not None:
            if file.content_type not in ALLOWED_CONTENT_TYPES:
                raise ValueError("Resume must be a PDF or image file")
            attachment_bytes = await file.read()
            if not attachment_bytes or len(attachment_bytes) > MAX_UPLOAD_BYTES:
                raise ValueError("Resume is empty or exceeds the upload limit")
            attachment_source_name = file.filename or "resume.pdf"
        if attachment_bytes is None and not resume_name:
            raise ValueError("Configure a candidate resume before sending")
        attachment_name = resume_attachment_name(str(profile.get("name", "")), attachment_source_name)
        message_id = send_email(
            recipient,
            subject,
            body,
            attachment_path=resume_name,
            attachment_name=attachment_name,
            attachment_bytes=attachment_bytes,
            attachment_source_name=attachment_source_name,
        )
    except Exception as exc:  # noqa: BLE001 - return Gmail error to the UI
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
async def upload_resume(file: UploadFile = File(...)) -> dict:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Resume must be a PDF, PNG, JPEG, or WebP file.")
    raw = await file.read()
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Resume is empty or exceeds the upload limit.")
    try:
        ocr = extract_ocr_text(raw, file.filename or "resume", file.content_type or "")
    except Exception as exc:  # noqa: BLE001 - provider error is safe for the client
        logger.exception("RESUME_OCR_FAILED error=%s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "configured": True,
        "name": file.filename or "resume",
        "size_bytes": len(raw),
        "text": ocr["text"],
        "confidence": ocr["confidence"],
        "blocks": ocr["blocks"],
    }


@app.get("/")
def frontend() -> FileResponse:
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
    resume_text: str = Form(""),
    file: UploadFile | None = File(None),
) -> StreamingResponse:
    """OCR or accept pasted text, then stream a Groq email draft."""
    if not message.strip() and file is None:
        raise HTTPException(status_code=400, detail="Provide pasted job text or a screenshot.")

    raw: bytes | None = None
    filename = ""
    content_type = ""
    if file is not None:
        filename = file.filename or "screenshot.png"
        content_type = file.content_type or ""
        if content_type not in {"image/png", "image/jpeg", "image/jpg", "image/webp", "application/pdf"}:
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
                yield _sse("status", {"message": "Reading the upload with hosted PP-OCRv5..."})
                posting = extract_ocr_text(raw, filename, content_type)["text"]
            if not posting:
                raise ValueError("No readable job text was found.")
            yield _sse("extracted_text", {"text": posting})
            profile, stored_resume, resume_name = load_candidate_context()
            resume = resume_text.strip() or stored_resume
            yield _sse("status", {"message": "Writing a draft with Groq...", "resume_name": resume_name})
            trusted_recipient = recipient.strip() or next(iter(extract_email_candidates(posting)), "")
            for chunk in stream_draft(posting, profile, resume, instructions, trusted_recipient):
                yield _sse("draft_token", {"text": chunk})
            yield _sse("complete", {"resume_name": resume_name, "extracted_text": posting})
        except Exception as exc:  # noqa: BLE001 - streamed to the UI
            logger.exception("DRAFT_FAILED error=%s", exc)
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)

@app.post("/refine")
async def refine(
    instruction: str = Form(""),
    current_draft: str = Form(""),
    posting: str = Form(""),
    resume_text: str = Form(""),
) -> StreamingResponse:
    """Stream a user-requested add, remove, or edit to the current draft."""
    if not instruction.strip():
        raise HTTPException(status_code=400, detail="Describe what you want to change.")
    if not current_draft.strip():
        raise HTTPException(status_code=400, detail="Create a draft before asking for edits.")

    def events() -> Iterator[str]:
        try:
            profile, stored_resume, resume_name = load_candidate_context()
            resume = resume_text.strip() or stored_resume
            yield _sse("status", {"message": "Applying your edit with Groq...", "resume_name": resume_name})
            recipient = extract_email_candidates(posting)[:1]
            for chunk in stream_refinement(
                current_draft, instruction, posting, profile, resume, recipient[0] if recipient else ""
            ):
                yield _sse("draft_token", {"text": chunk})
            yield _sse("complete", {"resume_name": resume_name})
        except Exception as exc:  # noqa: BLE001 - streamed to the UI
            logger.exception("DRAFT_REFINEMENT_FAILED error=%s", exc)
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/extract-job", response_model=JobExtractionResponse)
def extract_job_endpoint(request: JobExtractionRequest) -> JobExtractionResponse:
    """Extract structured job fields with Groq."""
    try:
        job = extract_job(request.text, request.candidate_emails)
        return JobExtractionResponse(success=True, job=job)
    except Exception as exc:  # noqa: BLE001 - return a useful provider error
        logger.exception("JOB_EXTRACTION_FAILED error=%s", exc)
        return JobExtractionResponse(success=False, error=str(exc))


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(file: UploadFile = File(...)) -> AnalyzeResponse:
    """
    PHASE 1 endpoint.

    1. Validate + save the uploaded screenshot (spec section 32: only
       image types, size-limited, saved only to the configured directory).
    2. Preprocess (resize / deskew).
    3. Run hosted PP-OCRv5 text extraction.
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

    try:
        start = time.time()
        ocr_result = extract_ocr_text(raw, file.filename or "upload", file.content_type or "")

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
            screenshot_path=None,
        )

    except Exception as exc:  # noqa: BLE001 - surfaced to the API caller deliberately
        logger.exception("OCR_FAILED error=%s", exc)
        return AnalyzeResponse(success=False, error=str(exc), screenshot_path=None)
