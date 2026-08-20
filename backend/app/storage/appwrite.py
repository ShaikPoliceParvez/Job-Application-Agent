"""Appwrite Storage adapter with local-development fallback support."""

from __future__ import annotations

from typing import Any

from backend.app.config import settings


def configured() -> bool:
    credentials_present = bool(
        settings.appwrite_endpoint
        and settings.appwrite_project_id
        and settings.appwrite_api_key
        and settings.appwrite_bucket_id
    )
    if not credentials_present:
        return False
    try:
        import appwrite  # noqa: F401
    except ImportError:
        return False
    return True


def _storage() -> Any:
    if not configured():
        raise RuntimeError(
            "Configure APPWRITE_PROJECT_ID, APPWRITE_API_KEY, and APPWRITE_BUCKET_ID."
        )
    try:
        from appwrite.client import Client
        from appwrite.services.storage import Storage
    except ImportError as exc:
        raise RuntimeError("The Appwrite Python SDK is not installed.") from exc

    client = Client()
    client.set_endpoint(settings.appwrite_endpoint)
    client.set_project(settings.appwrite_project_id)
    client.set_key(settings.appwrite_api_key)
    return Storage(client)


def upload_resume(content: bytes, filename: str, previous_file_id: str = "") -> dict[str, Any]:
    try:
        from appwrite.id import ID
        from appwrite.input_file import InputFile

        storage = _storage()
        file_id = ID.unique()
        result = storage.create_file(
            bucket_id=settings.appwrite_bucket_id,
            file_id=file_id,
            file=InputFile.from_bytes(content, filename),
        )
        old_file_id = previous_file_id or settings.appwrite_resume_file_id
        if old_file_id and old_file_id != file_id:
            try:
                storage.delete_file(settings.appwrite_bucket_id, old_file_id)
            except Exception:
                # A successful replacement should not fail because cleanup is stale.
                pass
        settings.appwrite_resume_file_id = str(result.get("$id", file_id))
        settings.appwrite_resume_filename = filename
        return {
            "file_id": settings.appwrite_resume_file_id,
            "filename": filename,
            "size_bytes": len(content),
        }
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 - avoid exposing SDK details
        raise RuntimeError("Resume could not be uploaded to Appwrite Storage.") from exc


def download_resume(file_id: str = "") -> bytes:
    active_file_id = file_id or settings.appwrite_resume_file_id
    if not active_file_id:
        return b""
    try:
        return bytes(_storage().get_file_download(settings.appwrite_bucket_id, active_file_id))
    except Exception as exc:  # noqa: BLE001 - avoid exposing SDK details
        raise RuntimeError("Configured resume could not be downloaded from Appwrite Storage.") from exc
