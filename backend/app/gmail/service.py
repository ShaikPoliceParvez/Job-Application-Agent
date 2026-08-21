"""Local Gmail OAuth, MIME construction, and send service."""

from __future__ import annotations

import base64
import html
import re
from email.utils import parseaddr
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from backend.app.config import settings
from backend.app.storage.appwrite import configured as appwrite_configured
from backend.app.storage.appwrite import download_resume

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
_oauth_state = ""
_oauth_flow: Any = None


def resume_attachment_name(candidate_name: str, source_name: str) -> str:
    """Return a safe, readable filename without changing the PDF contents."""
    stem = re.sub(r"[^A-Za-z0-9]+", "_", candidate_name).strip("_")
    return f"{stem}_resume.pdf" if stem else source_name


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

    if not settings.google_token_path.exists():
        return None
    return Credentials.from_authorized_user_file(str(settings.google_token_path), SCOPES)


def authorization_url() -> str:
    global _oauth_flow, _oauth_state
    from google_auth_oauthlib.flow import Flow

    _oauth_flow = Flow.from_client_config(_client_config(), SCOPES, state=None)
    _oauth_flow.redirect_uri = settings.google_redirect_uri
    url, _oauth_state = _oauth_flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    return url


def finish_authorization(code: str, state: str) -> str:
    global _oauth_flow, _oauth_state
    if _oauth_flow is None or not _oauth_state or state != _oauth_state:
        raise RuntimeError("Invalid Gmail authorization state")
    _oauth_flow.fetch_token(code=code)
    settings.google_token_path.parent.mkdir(parents=True, exist_ok=True)
    settings.google_token_path.write_text(_oauth_flow.credentials.to_json(), encoding="utf-8")
    settings.google_token_path.chmod(0o600)
    account = gmail_account()
    _oauth_flow = None
    _oauth_state = ""
    return account


def gmail_account() -> str:
    credentials = _credentials()
    if credentials is None:
        return ""
    if credentials.expired and credentials.refresh_token:
        from google.auth.transport.requests import Request

        credentials.refresh(Request())
        settings.google_token_path.write_text(credentials.to_json(), encoding="utf-8")
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
    global _oauth_flow, _oauth_state
    if settings.google_token_path.exists():
        settings.google_token_path.unlink()
    _oauth_flow = None
    _oauth_state = ""


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

    if not attachment_path:
        raise ValueError("Configure a candidate resume before sending")
    if appwrite_configured() and settings.appwrite_resume_file_id:
        attachment_bytes = download_resume()
        source_name = settings.appwrite_resume_filename or attachment_path
    else:
        source = Path(attachment_path)
        if not source.is_absolute():
            source = settings.resume_directory / source
        source = source.resolve()
        resume_root = settings.resume_directory.resolve()
        if resume_root not in source.parents or not source.is_file():
            raise ValueError("Configured candidate resume could not be found")
        attachment_bytes = source.read_bytes()
        source_name = source.name
    if Path(source_name).suffix.lower() != ".pdf":
        raise ValueError("Candidate resume attachment must be a PDF")
    attachment = MIMEApplication(attachment_bytes, _subtype="pdf")
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
) -> str:
    credentials = _credentials()
    if settings.email_send_mode == "gmail":
        if credentials is None:
            raise RuntimeError("Connect a Gmail account before sending")
        if credentials.expired and credentials.refresh_token:
            from google.auth.transport.requests import Request

            credentials.refresh(Request())
            settings.google_token_path.write_text(credentials.to_json(), encoding="utf-8")
        if not credentials.valid:
            raise RuntimeError("Gmail authorization expired; connect the account again")

    message = build_mime_message(recipient, subject, body, attachment_path, attachment_name=attachment_name)
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
