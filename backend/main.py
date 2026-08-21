"""Deployment-facing backend entrypoint."""

from backend.app.main import app

__all__ = ["app"]