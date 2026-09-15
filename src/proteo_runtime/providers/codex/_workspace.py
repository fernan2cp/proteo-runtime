"""Temporary workspace management for the Codex provider."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


def create_workspace() -> Path:
    """Create an empty temporary workspace for one Codex execution."""

    return Path(tempfile.mkdtemp(prefix="proteo-codex-"))


def remove_workspace(path: Path | None) -> None:
    """Remove an owned temporary workspace idempotently."""

    if path is not None:
        shutil.rmtree(path, ignore_errors=True)
