"""Local LangSmith recording client capturing observer calls into SQLite."""

from __future__ import annotations

import sys
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure examples/smart_quote_agent is on sys.path when run directly
_DEMO_DIR = Path(__file__).resolve().parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from telemetry_db import (  # noqa: E402
    get_telemetry_db_path,
    insert_langsmith_create_run,
    update_langsmith_run,
    utc_now_iso,
)


def _format_timestamp(val: Any) -> str:
    """Format integer epoch milliseconds or datetime to an ISO-8601 UTC string.

    Args:
        val: Timestamp value as int (ms), float, datetime, or None.

    Returns:
        Formatted ISO-8601 UTC string.
    """
    if isinstance(val, int | float):
        return datetime.fromtimestamp(val / 1000.0, tz=UTC).isoformat()
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, str):
        return val
    return utc_now_iso()


class RecordingLangSmithClient:
    """Minimal local recording client satisfying LangSmithObserver contract."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialize the recording client with a target telemetry database.

        Args:
            db_path: Target SQLite database path, defaulting to DEFAULT_TELEMETRY_DB_PATH.
        """
        self.db_path = get_telemetry_db_path(db_path)
        self._closed = False
        self.flush_count = 0
        self.close_count = 0

    def create_run(self, **kwargs: Any) -> dict[str, Any]:
        """Record the start of a LangSmith run and return a descriptor with 'id'.

        Args:
            **kwargs: Run creation parameters supplied by LangSmithObserver.

        Returns:
            Dictionary exposing 'id' for child run hierarchy tracking.
        """
        if self._closed:
            return {"id": str(uuid.uuid4())}

        candidate_id = kwargs.get("id") or kwargs.get("run_id")
        run_id = str(candidate_id) if candidate_id else str(uuid.uuid4())
        name = str(kwargs.get("name", "unnamed"))
        run_type = str(kwargs.get("run_type")) if kwargs.get("run_type") else None
        parent_candidate = kwargs.get("parent_run_id")
        parent_run_id = str(parent_candidate) if parent_candidate else None
        project_name = str(kwargs.get("project_name")) if kwargs.get("project_name") else None
        started_at = _format_timestamp(kwargs.get("start_time"))

        tags_val = kwargs.get("tags")
        tags = list(tags_val) if isinstance(tags_val, list | tuple) else None

        extra = kwargs.get("extra")
        metadata = None
        if isinstance(extra, Mapping):
            meta_cand = extra.get("metadata")
            if isinstance(meta_cand, Mapping):
                metadata = dict(meta_cand)

        insert_langsmith_create_run(
            self.db_path,
            run_id=run_id,
            name=name,
            run_type=run_type,
            parent_run_id=parent_run_id,
            project_name=project_name,
            started_at=started_at,
            status="running",
            error=None,
            tags=tags,
            metadata=metadata,
        )

        return {"id": run_id}

    def update_run(self, **kwargs: Any) -> None:
        """Record completion or failure of an existing LangSmith run.

        Args:
            **kwargs: Run update parameters supplied by LangSmithObserver.
        """
        if self._closed:
            return

        candidate_id = kwargs.get("run_id") or kwargs.get("id")
        if not candidate_id:
            return

        run_id = str(candidate_id)
        ended_at = _format_timestamp(kwargs.get("end_time"))
        error_val = kwargs.get("error")
        error = str(error_val) if error_val is not None else None
        status = "error" if error is not None else "completed"

        update_langsmith_run(
            self.db_path,
            run_id=run_id,
            ended_at=ended_at,
            status=status,
            error=error,
        )

    def flush(self) -> None:
        """Flush pending writes (no-op as writes are synchronous per operation)."""
        self.flush_count += 1

    def close(self) -> None:
        """Release recording client resources idempotently."""
        self.close_count += 1
        self._closed = True
