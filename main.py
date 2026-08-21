"""Appwrite Function entrypoint for the existing FastAPI backend."""

from backend.main import _body, _dispatch, app, main

__all__ = ["app", "main", "_body", "_dispatch"]
