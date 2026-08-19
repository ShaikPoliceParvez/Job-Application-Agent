"""Deployment-facing backend entrypoint.

The application implementation remains in ``app`` so local imports and tests
stay stable while Vercel can target a clearly separated backend module.
"""

from app.main import app

__all__ = ["app"]
