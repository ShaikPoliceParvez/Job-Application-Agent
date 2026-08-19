"""Local Gmail OAuth and send service."""

from __future__ import annotations

import base64
import mimetypes
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from app.config import settings

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
_oauth_state = ""
_oauth_flow: Any = None


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
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
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
        # The send-only scope is sufficient for sending but not for reading
        # the profile endpoint. A valid send token is still connected.
        return "Gmail account connected"


def logout() -> None:
    global _oauth_flow, _oauth_state
    if settings.google_token_path.exists():
        settings.google_token_path.unlink()
    _oauth_flow = None
    _oauth_state = ""


def send_email(recipient: str, subject: str, body: str, attachment_path: str = "") -> str:
    if not recipient.strip() or not subject.strip() or not body.strip():
        raise ValueError("Recipient, subject, and email body are required")
    credentials = _credentials()
    if credentials is None:
        raise RuntimeError("Connect a Gmail account before sending")
    if credentials.expired and credentials.refresh_token:
        from google.auth.transport.requests import Request

        credentials.refresh(Request())
        settings.google_token_path.write_text(credentials.to_json(), encoding="utf-8")
    if not credentials.valid:
        raise RuntimeError("Gmail authorization expired; connect the account again")

    from googleapiclient.discovery import build

    message = EmailMessage()
    message["To"] = recipient.strip()
    message["Subject"] = subject.strip()
    message.set_content(body.strip())
    if attachment_path:
        source = Path(attachment_path)
        if not source.is_absolute():
            source = settings.resume_directory / source
        source = source.resolve()
        resume_root = settings.resume_directory.resolve()
        if resume_root not in source.parents or not source.is_file():
            raise ValueError("Configured candidate resume could not be found")
        content_type, _ = mimetypes.guess_type(source.name)
        maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
        message.add_attachment(
            source.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=source.name,
        )
    else:
        raise ValueError("Configure a candidate resume before sending")
    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    result = build("gmail", "v1", credentials=credentials, cache_discovery=False).users().messages().send(
        userId="me", body={"raw": encoded}
    ).execute()
    return str(result.get("id", ""))
