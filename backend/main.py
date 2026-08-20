"""Appwrite Function entrypoint for the backend-only deployment source."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

# Appwrite may invoke this file with a working directory other than the
# configured function root. Resolve the sibling `app` package from the
# entrypoint location instead of relying on the process working directory.
BACKEND_DIRECTORY = Path(__file__).resolve().parent
if str(BACKEND_DIRECTORY) not in sys.path:
	sys.path.insert(0, str(BACKEND_DIRECTORY))

from app.main import app


def _body(request: Any) -> bytes:
	# Appwrite's text body accessor can try to decode multipart/PDF bytes.
	# Prefer the binary accessor, but tolerate runtimes where reading it fails.
	def coerce(value: Any) -> bytes | None:
		if isinstance(value, bytes):
			return value
		if isinstance(value, bytearray):
			return bytes(value)
		if isinstance(value, str):
			return value.encode("latin-1")
		if value is None or isinstance(value, (dict, list)):
			return None
		return bytes(value)

	try:
		binary = getattr(request, "bodyBinary", None)
	except (UnicodeDecodeError, TypeError, ValueError):
		binary = None
	if binary:
		return coerce(binary) or b""

	# Some Appwrite Python runtimes expose bodyBinary through a failing
	# descriptor while retaining the raw value on the request instance.
	for attribute in ("body_binary", "bodyRaw", "body_raw", "rawBody", "raw_body", "_bodyBinary", "_body_binary"):
		try:
			binary = coerce(getattr(request, attribute, None))
		except (UnicodeDecodeError, TypeError, ValueError):
			binary = None
		if binary:
			return binary
	try:
		request_values = vars(request)
	except TypeError:
		request_values = {}
	for attribute, value in request_values.items():
		if "body" in attribute.lower() or "raw" in attribute.lower():
			try:
				binary = coerce(value)
			except (UnicodeDecodeError, TypeError, ValueError):
				binary = None
			if binary:
				return binary

	try:
		value = getattr(request, "body", b"")
	except (UnicodeDecodeError, TypeError, ValueError):
		value = b""
	binary = coerce(value)
	if binary is not None:
		return binary
	if isinstance(value, (dict, list)):
		return json.dumps(value).encode("utf-8")
	return str(value or "").encode("utf-8")


def _query(request: Any) -> str:
	value = getattr(request, "queryString", "") or ""
	if isinstance(value, dict):
		from urllib.parse import urlencode

		return urlencode(value, doseq=True)
	return str(value)


def _dispatch(request: Any):
	method = str(getattr(request, "method", "GET")).upper()
	path = str(getattr(request, "path", "/") or "/")
	query = _query(request)
	if query:
		path = f"{path}?{query}"
	headers = dict(getattr(request, "headers", {}) or {})
	headers.pop("host", None)
	headers.pop("content-length", None)
	with TestClient(app) as client:
		return client.request(method, path, content=_body(request), headers=headers)


def main(context: Any) -> Any:
	"""Appwrite's direct Python Function handler."""
	try:
		response = _dispatch(context.req)
	except Exception as exc:  # noqa: BLE001 - keep client errors generic
		context.error(f"Backend request failed: {exc}")
		return context.res.json({"success": False, "error": "Backend request failed."}, 500)

	content_type = response.headers.get("content-type", "")
	if "application/json" in content_type:
		try:
			return context.res.json(response.json(), response.status_code, dict(response.headers))
		except (ValueError, json.JSONDecodeError):
			pass
	return context.res.text(response.text, response.status_code, {"Content-Type": content_type or "text/plain"})


__all__ = ["app", "main"]