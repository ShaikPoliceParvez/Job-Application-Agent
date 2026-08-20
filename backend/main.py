"""Appwrite Function entrypoint for the backend-only deployment source."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app.main import app


def _body(request: Any) -> bytes:
	binary = getattr(request, "bodyBinary", None)
	if binary:
		return binary if isinstance(binary, bytes) else bytes(binary)
	value = getattr(request, "body", b"")
	if isinstance(value, bytes):
		return value
	if isinstance(value, (dict, list)):
		return json.dumps(value).encode("utf-8")
	return str(value or "").encode("utf-8")


def _query(request: Any) -> str:
	value = getattr(request, "queryString", "") or ""
	if isinstance(value, dict):
		return str(httpx.QueryParams(value))
	return str(value)


async def _dispatch(request: Any) -> httpx.Response:
	method = str(getattr(request, "method", "GET")).upper()
	path = str(getattr(request, "path", "/") or "/")
	query = _query(request)
	if query:
		path = f"{path}?{query}"
	headers = dict(getattr(request, "headers", {}) or {})
	headers.pop("host", None)
	headers.pop("content-length", None)
	transport = httpx.ASGITransport(app=app)
	async with httpx.AsyncClient(transport=transport, base_url="http://appwrite.local") as client:
		return await client.request(method, path, content=_body(request), headers=headers)


def main(context: Any) -> Any:
	"""Appwrite's direct Python Function handler."""
	try:
		response = asyncio.run(_dispatch(context.req))
	except Exception as exc:  # noqa: BLE001 - keep client errors generic
		context.error(f"Backend request failed: {exc}")
		return context.res.json({"success": False, "error": "Backend request failed."}, 500)

	content_type = response.headers.get("content-type", "")
	if "application/json" in content_type:
		try:
			return context.res.json(response.json(), response.status_code)
		except (ValueError, json.JSONDecodeError):
			pass
	return context.res.text(response.text, response.status_code, {"Content-Type": content_type or "text/plain"})


__all__ = ["app", "main"]