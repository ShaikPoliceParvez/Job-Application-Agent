"""
Central logging setup.

Per spec section 38: log lifecycle events, never log OAuth tokens,
passwords, or full resume/private content. Handlers only ever receive
the short structured messages individual modules choose to log — this
file just wires up format + destinations.
"""

from __future__ import annotations

import logging
import sys

from .config import settings


def configure_logging() -> None:
    log_file = settings.log_dir / "app.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(stream_handler)
    root.addHandler(file_handler)

    # Quiet down noisy third-party libraries.
    for noisy in ("uvicorn.access", "PIL", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
