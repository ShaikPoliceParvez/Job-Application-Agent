"""Gmail OAuth, Upstash persistence, MIME construction, and send service."""

from __future__ import annotations

import base64
import html
import json
import re
from datetime import datetime, timezone
from email.utils import parseaddr
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.config import settings

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
OAUTH_STATE_KEY = "job-agent:gmail:oauth-state"
GMAIL_CREDENTIALS_KEY = "job-agent:gmail:credentials"
OAUTH_STATE_TTL_SECONDS = 600


def _redis_command(command: list[Any]) -> Any:
    if not settings.upstash_redis_rest_url or not settings.upstash_redis_rest_token:
        raise RuntimeError("Configure Upstash Redis persistence for Gmail OAuth")
    request = Request(
        settings.upstash_redis_rest_url.rstrip("/"),
        data=json.dumps(command).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.upstash_redis_rest_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            content = response.read()
    except HTTPError as exc:
        raise RuntimeError("Redis persistence request failed") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("Redis persistence is unavailable") from exc
    if not content:
        return None
    try:
        response_body = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("Redis returned malformed persistence data") from exc
    return response_body.get("result") if isinstance(response_body, dict) else None


def _redis_get(key: str) -> Any:
    return _redis_command(["GET", key])


def _redis_set(key: str, value: dict[str, Any], ttl: int | None = None) -> None:
    command: list[Any] = ["SET", key, json.dumps(value)]
    if ttl is not None:
        command.extend(["EX", ttl])
    _redis_command(command)


def _redis_delete(key: str) -> None:
    _redis_command(["DEL", key])


def resume_attachment_name(candidate_name: str, source_name: str) -> str:
    """Return ``Candidate_Name_resume`` with the source file extension."""
    stem = re.sub(r"[^A-Za-z0-9]+", "_", candidate_name).strip("_")
    suffix = Path(source_name).suffix.lower() or ".pdf"
    return f"{stem or 'Candidate'}_resume{suffix}"


def _client_config() -> dict[str, Any]:
    if not settings.google_client_id or not settings.google_client_secret:
        raise RuntimeError("Configure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env first")
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def _credentials():
    from google.oauth2.credentials import Credentials

    stored = _redis_get(GMAIL_CREDENTIALS_KEY)
    if not stored:
        return None
    data = json.loads(stored)
    if not isinstance(data, dict) or not data.get("token"):
        return None
    expiry = data.get("expiry")
    expiry_value = datetime.fromisoformat(expiry) if expiry else None
    return Credentials(
        token=data["token"],
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=SCOPES,
        expiry=expiry_value,
    )


def _credential_data(credentials: Any) -> dict[str, Any]:
    return {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "expiry": credentials.expiry.isoformat() if credentials.expiry else "",
    }


def authorization_url() -> str:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(_client_config(), SCOPES, state=None)
    flow.redirect_uri = settings.google_redirect_uri
    url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    _redis_set(
        OAUTH_STATE_KEY,
        {"state": state, "created_at": datetime.now(timezone.utc).isoformat()},
        OAUTH_STATE_TTL_SECONDS,
    )
    return url


def finish_authorization(code: str, state: str) -> str:
    stored = _redis_get(OAUTH_STATE_KEY)
    try:
        stored_data = json.loads(stored) if stored else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid Gmail authorization state") from exc
    stored_state = stored_data.get("state", "")
    created_at = stored_data.get("created_at", "")
    try:
        state_age = (datetime.now(timezone.utc) - datetime.fromisoformat(created_at)).total_seconds()
    except (TypeError, ValueError):
        state_age = OAUTH_STATE_TTL_SECONDS + 1
    if not stored_state or state != stored_state or state_age > OAUTH_STATE_TTL_SECONDS:
        raise RuntimeError("Invalid Gmail authorization state")
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(_client_config(), SCOPES, state=stored_state)
    flow.redirect_uri = settings.google_redirect_uri
    flow.fetch_token(code=code)
    _redis_set(GMAIL_CREDENTIALS_KEY, _credential_data(flow.credentials))
    _redis_delete(OAUTH_STATE_KEY)
    account = gmail_account()
    return account


def gmail_account() -> str:
    credentials = _credentials()
    if credentials is None:
        return ""
    if credentials.expired and credentials.refresh_token:
        from google.auth.transport.requests import Request

        credentials.refresh(Request())
        _redis_set(GMAIL_CREDENTIALS_KEY, _credential_data(credentials))
    if not credentials.valid:
        return ""
    from googleapiclient.discovery import build

    try:
        profile = build("gmail", "v1", credentials=credentials, cache_discovery=False).users().getProfile(
            userId="me"
        ).execute()
        return str(profile.get("emailAddress", "")) or "Gmail account connected"
    except Exception:
        return "Gmail account connected"


def logout() -> None:
    _redis_delete(GMAIL_CREDENTIALS_KEY)
    _redis_delete(OAUTH_STATE_KEY)


def text_to_html_email(body: str) -> str:
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", body.strip()):
        escaped = html.escape(paragraph.strip()).replace("\n", "<br>\n")
        if escaped:
            paragraphs.append(f'<p style="margin:0 0 16px 0;">{escaped}</p>')
    content = "\n".join(paragraphs)
    return f'''<!doctype html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#ffffff;color:#222222;font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.6;">
<div style="width:100%;max-width:680px;margin:0 auto;padding:24px 16px;box-sizing:border-box;">{content}</div>
</body></html>'''


def build_mime_message(
    recipient: str,
    subject: str,
    body: str,
    attachment_path: str = "",
    sender: str = "",
    attachment_name: str = "",
    attachment_bytes: bytes | None = None,
    attachment_source_name: str = "",
) -> MIMEMultipart:
    _, address = parseaddr(recipient.strip())
    if not address or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", address):
        raise ValueError("Recipient email is missing or invalid")
    if not subject.strip() or not body.strip():
        raise ValueError("Recipient, subject, and email body are required")
    message = MIMEMultipart("mixed")
    if sender.strip():
        message["From"] = sender.strip()
    message["To"] = recipient.strip()
    message["Subject"] = subject.strip()

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(body.strip(), "plain", "utf-8"))
    alternative.attach(MIMEText(text_to_html_email(body), "html", "utf-8"))
    message.attach(alternative)

    if attachment_bytes is None and not attachment_path:
        raise ValueError("Configure a candidate resume before sending")
    if attachment_bytes is None:
        source = Path(attachment_path)
        if not source.is_absolute():
            source = settings.resume_directory / source
        source = source.resolve()
        resume_root = settings.resume_directory.resolve()
        if resume_root not in source.parents or not source.is_file():
            raise ValueError("Configured candidate resume could not be found")
        attachment_bytes = source.read_bytes()
        source_name = source.name
    else:
        source_name = attachment_source_name or attachment_path or "resume.pdf"
    suffix = Path(source_name).suffix.lower()
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Candidate resume attachment must be a PDF or image")
    subtype = "pdf" if suffix == ".pdf" else suffix.lstrip(".")
    attachment = MIMEApplication(attachment_bytes, _subtype=subtype)
    attachment.add_header(
        "Content-Disposition", "attachment", filename=attachment_name or source_name
    )
    message.attach(attachment)
    return message


def send_email(
    recipient: str,
    subject: str,
    body: str,
    attachment_path: str = "",
    attachment_name: str = "",
    attachment_bytes: bytes | None = None,
    attachment_source_name: str = "",
) -> str:
    credentials = None
    if settings.email_send_mode == "gmail":
        credentials = _credentials()
        if credentials is None:
            raise RuntimeError("Connect a Gmail account before sending")
        if credentials.expired and credentials.refresh_token:
            from google.auth.transport.requests import Request

            credentials.refresh(Request())
            _redis_set(GMAIL_CREDENTIALS_KEY, _credential_data(credentials))
        if not credentials.valid:
            raise RuntimeError("Gmail authorization expired; connect the account again")

    message = build_mime_message(
        recipient,
        subject,
        body,
        attachment_path,
        attachment_name=attachment_name,
        attachment_bytes=attachment_bytes,
        attachment_source_name=attachment_source_name,
    )
    if settings.email_send_mode == "mock":
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        preview = settings.log_dir / "mock_email_preview.eml"
        preview.write_bytes(message.as_bytes())
        return f"mock:{preview.name}"

    from googleapiclient.discovery import build

    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    result = build("gmail", "v1", credentials=credentials, cache_discovery=False).users().messages().send(
        userId="me", body={"raw": encoded}
    ).execute()
    return str(result.get("id", ""))
