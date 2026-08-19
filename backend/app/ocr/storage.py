"""Retention helpers for uploaded OCR screenshots."""

from __future__ import annotations

from pathlib import Path


def retain_recent_screenshots(directory: Path, limit: int = 5) -> list[Path]:
    """Keep the newest screenshot files and remove older uploads."""
    if limit < 1:
        raise ValueError("Screenshot retention limit must be at least 1")
    screenshots = sorted(
        (path for path in directory.iterdir() if path.is_file() and path.name != ".gitkeep"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    removed: list[Path] = []
    for path in screenshots[limit:]:
        path.unlink()
        removed.append(path)
    return removed
