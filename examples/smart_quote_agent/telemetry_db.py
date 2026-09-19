"""SQLite telemetry database operations, schema creation, and typed record persistence."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_TELEMETRY_DB_PATH = Path(__file__).resolve().parent / "data" / "observability.sqlite3"

TELEMETRY_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;

-- Neutral Proteo Runtime Events
CREATE TABLE IF NOT EXISTS runtime_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at       TEXT NOT NULL,
    occurred_at       TEXT NOT NULL,
    event_id          TEXT NOT NULL,
    event_kind        TEXT NOT NULL,
    invocation_id     TEXT NULL,
    interaction_id    TEXT NULL,
    session_id        TEXT NULL,
    task_id           TEXT NULL,
    turn_id           TEXT NULL,
    runtime_name      TEXT NULL,
    model             TEXT NULL,
    profile           TEXT NULL,
    reasoning_effort  TEXT NULL,
    tool_name         TEXT NULL,
    tool_call_id      TEXT NULL,
    status            TEXT NULL,
    duration_ms       REAL NULL,
    metadata_json     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runtime_events_invocation
    ON runtime_events(invocation_id);
CREATE INDEX IF NOT EXISTS idx_runtime_events_interaction
    ON runtime_events(interaction_id);
CREATE INDEX IF NOT EXISTS idx_runtime_events_task
    ON runtime_events(task_id);
CREATE INDEX IF NOT EXISTS idx_runtime_events_kind
    ON runtime_events(event_kind);
CREATE INDEX IF NOT EXISTS idx_runtime_events_occurred_at
    ON runtime_events(occurred_at);

-- LangSmith Run Hierarchy
CREATE TABLE IF NOT EXISTS langsmith_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL UNIQUE,
    parent_run_id   TEXT NULL,
    name            TEXT NOT NULL,
    run_type        TEXT NULL,
    project_name    TEXT NULL,
    started_at      TEXT NULL,
    ended_at        TEXT NULL,
    status          TEXT NOT NULL DEFAULT 'running',
    error           TEXT NULL,
    tags_json       TEXT NOT NULL DEFAULT '[]',
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_langsmith_runs_parent
    ON langsmith_runs(parent_run_id);
CREATE INDEX IF NOT EXISTS idx_langsmith_runs_started
    ON langsmith_runs(started_at);

-- OpenTelemetry Trace Spans
CREATE TABLE IF NOT EXISTS otel_spans (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id          TEXT NOT NULL,
    span_id           TEXT NOT NULL UNIQUE,
    parent_span_id    TEXT NULL,
    name              TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    ended_at          TEXT NULL,
    duration_ms       REAL NULL,
    status_code       TEXT NULL,
    status_message    TEXT NULL,
    attributes_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_otel_spans_trace
    ON otel_spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_otel_spans_parent
    ON otel_spans(parent_span_id);
CREATE INDEX IF NOT EXISTS idx_otel_spans_started
    ON otel_spans(started_at);

-- OpenTelemetry Span Events
CREATE TABLE IF NOT EXISTS otel_span_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    span_id          TEXT NOT NULL,
    name             TEXT NOT NULL,
    occurred_at      TEXT NOT NULL,
    attributes_json  TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_otel_span_events_span
    ON otel_span_events(span_id);

-- OpenTelemetry Low-Cardinality Metrics
CREATE TABLE IF NOT EXISTS otel_metrics (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at      TEXT NOT NULL,
    instrument_name  TEXT NOT NULL,
    instrument_type  TEXT NOT NULL,
    value            REAL NOT NULL,
    attributes_json  TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_otel_metrics_recorded
    ON otel_metrics(recorded_at);
"""


def utc_now_iso() -> str:
    """Return the current UTC timestamp formatted as ISO 8601 with milliseconds.

    Returns:
        ISO 8601 formatted UTC timestamp string.
    """
    return datetime.now(UTC).isoformat()


def safe_json_dumps(data: Any) -> str:
    """Safely serialize an object to JSON, converting non-serializable elements to strings.

    Args:
        data: Arbitrary object to serialize.

    Returns:
        JSON encoded string representation.
    """

    def _default(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, set | frozenset):
            return sorted(list(obj))
        return str(obj)

    try:
        return json.dumps(data, default=_default)
    except Exception:
        return json.dumps(str(data))


def get_telemetry_db_path(custom_path: Path | str | None = None) -> Path:
    """Resolve and return the absolute path to the telemetry database file.

    Args:
        custom_path: Optional custom path or string override.

    Returns:
        Path object pointing to the telemetry SQLite database file.
    """
    if custom_path is None:
        return DEFAULT_TELEMETRY_DB_PATH
    return Path(custom_path).resolve()


def get_telemetry_connection(
    db_path: Path | str | None = None,
    *,
    read_only: bool = False,
) -> sqlite3.Connection:
    """Create a thread-safe connection to the telemetry database with WAL enabled.

    Args:
        db_path: Optional custom database path.
        read_only: If True, opens database in URI read-only mode.

    Returns:
        Configured SQLite connection object with Row factory and WAL pragmas.
    """
    target_path = get_telemetry_db_path(db_path)
    if read_only:
        uri = f"file:{target_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    else:
        conn = sqlite3.connect(str(target_path), timeout=5.0)

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


def init_telemetry_database(
    db_path: Path | str | None = None,
    *,
    reset: bool = False,
) -> Path:
    """Initialize the telemetry SQLite database with all 5 required tables and indexes.

    Args:
        db_path: Target database path, defaulting to DEFAULT_TELEMETRY_DB_PATH.
        reset: When True, removes existing database before applying schema.

    Returns:
        Path to the initialized telemetry database file.
    """
    target_path = get_telemetry_db_path(db_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if reset and target_path.exists():
        target_path.unlink()
        # Clean up transient WAL/SHM files if present
        wal_file = Path(f"{target_path}-wal")
        shm_file = Path(f"{target_path}-shm")
        if wal_file.exists():
            wal_file.unlink()
        if shm_file.exists():
            shm_file.unlink()

    conn = get_telemetry_connection(target_path)
    try:
        has_events_table = (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'runtime_events';"
            ).fetchone()
            is not None
        )
        if has_events_table:
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(runtime_events);").fetchall()
            }
            if "task_id" not in columns:
                conn.execute("ALTER TABLE runtime_events ADD COLUMN task_id TEXT NULL;")
            if "interaction_id" not in columns:
                conn.execute("ALTER TABLE runtime_events ADD COLUMN interaction_id TEXT NULL;")
        conn.executescript(TELEMETRY_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()

    return target_path


def insert_runtime_event(
    db_path: Path | str | None,
    *,
    event_id: str,
    event_kind: str,
    occurred_at: str,
    invocation_id: str | None = None,
    interaction_id: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
    turn_id: str | None = None,
    runtime_name: str | None = None,
    model: str | None = None,
    profile: str | None = None,
    reasoning_effort: str | None = None,
    tool_name: str | None = None,
    tool_call_id: str | None = None,
    status: str | None = None,
    duration_ms: float | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> int:
    """Insert one neutral Proteo runtime event into runtime_events.

    Args:
        db_path: Database path to write to.
        event_id: Unique event identifier.
        event_kind: String kind of the runtime event.
        occurred_at: ISO-8601 UTC timestamp of occurrence.
        invocation_id: Optional correlation invocation identifier.
        interaction_id: Optional host-generated per-turn correlation identifier.
        session_id: Optional session identifier.
        task_id: Optional ephemeral task identifier.
        turn_id: Optional turn identifier.
        runtime_name: Name of the runtime provider.
        model: Target model name.
        profile: Active profile name.
        reasoning_effort: Optional reasoning effort level.
        tool_name: Tool name if associated with a tool call.
        tool_call_id: Tool call ID if associated with a tool call.
        status: Event or execution status.
        duration_ms: Duration in milliseconds if terminal or measured.
        metadata: Full projected safe metadata mapping.

    Returns:
        Auto-incremented row ID of the inserted event.
    """
    recorded_at = utc_now_iso()
    metadata_json = safe_json_dumps(metadata or {})

    conn = get_telemetry_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO runtime_events (
                    recorded_at, occurred_at, event_id, event_kind,
                    invocation_id, interaction_id, session_id, task_id, turn_id, runtime_name,
                    model, profile, reasoning_effort, tool_name,
                    tool_call_id, status, duration_ms, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recorded_at,
                    occurred_at,
                    event_id,
                    event_kind,
                    invocation_id,
                    interaction_id,
                    session_id,
                    task_id,
                    turn_id,
                    runtime_name,
                    model,
                    profile,
                    reasoning_effort,
                    tool_name,
                    tool_call_id,
                    status,
                    duration_ms,
                    metadata_json,
                ),
            )
            return cursor.lastrowid or 0
    finally:
        conn.close()


def insert_langsmith_create_run(
    db_path: Path | str | None,
    *,
    run_id: str,
    name: str,
    run_type: str | None = None,
    parent_run_id: str | None = None,
    project_name: str | None = None,
    started_at: str | None = None,
    status: str = "running",
    error: str | None = None,
    tags: list[str] | tuple[str, ...] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Insert a new LangSmith run record into langsmith_runs.

    Args:
        db_path: Database path to write to.
        run_id: Unique run identifier.
        name: Name of the run chain or tool.
        run_type: Type of the run (e.g. chain, tool).
        parent_run_id: Optional parent run identifier.
        project_name: Optional project name tag.
        started_at: ISO-8601 start timestamp.
        status: Initial status, defaults to 'running'.
        error: Optional initial error string.
        tags: Optional list of tags.
        metadata: Optional metadata dictionary.
    """
    tags_json = safe_json_dumps(tags or [])
    metadata_json = safe_json_dumps(metadata or {})

    conn = get_telemetry_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO langsmith_runs (
                    run_id, parent_run_id, name, run_type, project_name,
                    started_at, ended_at, status, error, tags_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    parent_run_id,
                    name,
                    run_type,
                    project_name,
                    started_at,
                    status,
                    error,
                    tags_json,
                    metadata_json,
                ),
            )
    finally:
        conn.close()


def update_langsmith_run(
    db_path: Path | str | None,
    *,
    run_id: str,
    ended_at: str | None = None,
    status: str = "completed",
    error: str | None = None,
) -> None:
    """Update an existing LangSmith run with end time, status, and error.

    Args:
        db_path: Database path to write to.
        run_id: Run identifier to update.
        ended_at: ISO-8601 end timestamp.
        status: Terminal status.
        error: Optional safe error description.
    """
    conn = get_telemetry_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                UPDATE langsmith_runs
                SET ended_at = ?, status = ?, error = ?
                WHERE run_id = ?
                """,
                (ended_at, status, error, run_id),
            )
    finally:
        conn.close()


def insert_otel_span(
    db_path: Path | str | None,
    *,
    trace_id: str,
    span_id: str,
    name: str,
    started_at: str,
    parent_span_id: str | None = None,
    ended_at: str | None = None,
    duration_ms: float | None = None,
    status_code: str | None = None,
    status_message: str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> None:
    """Insert or replace an OpenTelemetry span in otel_spans.

    Args:
        db_path: Database path to write to.
        trace_id: Trace hex identifier.
        span_id: Span hex identifier.
        name: Span operation name.
        started_at: ISO-8601 start timestamp.
        parent_span_id: Optional parent span identifier.
        ended_at: Optional ISO-8601 end timestamp.
        duration_ms: Duration in milliseconds.
        status_code: Status code string (e.g. OK, ERROR).
        status_message: Optional status message.
        attributes: Attribute dictionary.
    """
    attributes_json = safe_json_dumps(attributes or {})

    conn = get_telemetry_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO otel_spans (
                    trace_id, span_id, parent_span_id, name,
                    started_at, ended_at, duration_ms,
                    status_code, status_message, attributes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    span_id,
                    parent_span_id,
                    name,
                    started_at,
                    ended_at,
                    duration_ms,
                    status_code,
                    status_message,
                    attributes_json,
                ),
            )
    finally:
        conn.close()


def insert_otel_span_event(
    db_path: Path | str | None,
    *,
    span_id: str,
    name: str,
    occurred_at: str,
    attributes: Mapping[str, Any] | None = None,
) -> None:
    """Insert a span lifecycle event into otel_span_events.

    Args:
        db_path: Database path to write to.
        span_id: Span identifier the event belongs to.
        name: Name of the event.
        occurred_at: ISO-8601 timestamp of occurrence.
        attributes: Event attributes.
    """
    attributes_json = safe_json_dumps(attributes or {})

    conn = get_telemetry_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO otel_span_events (
                    span_id, name, occurred_at, attributes_json
                ) VALUES (?, ?, ?, ?)
                """,
                (span_id, name, occurred_at, attributes_json),
            )
    finally:
        conn.close()


def insert_otel_metric(
    db_path: Path | str | None,
    *,
    instrument_name: str,
    instrument_type: str,
    value: float,
    recorded_at: str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> None:
    """Insert one OpenTelemetry metric data point into otel_metrics.

    Args:
        db_path: Database path to write to.
        instrument_name: Name of the metric instrument.
        instrument_type: Type of metric instrument (counter, histogram).
        value: Numeric value observed.
        recorded_at: Optional timestamp string, defaults to now.
        attributes: Attribute dictionary.
    """
    ts = recorded_at or utc_now_iso()
    attributes_json = safe_json_dumps(attributes or {})

    conn = get_telemetry_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO otel_metrics (
                    recorded_at, instrument_name, instrument_type, value, attributes_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (ts, instrument_name, instrument_type, value, attributes_json),
            )
    finally:
        conn.close()


def derive_invocation_status(events: Sequence[Mapping[str, Any]]) -> str:
    """Derive invocation status from chronological runtime events.

    Args:
        events: Sequence of runtime event dictionaries for the invocation.

    Returns:
        One of 'completed', 'failed', 'denied', or 'running'.
    """
    for e in reversed(events):
        kind = e.get("event_kind")
        if kind in ("invocation_completed", "tool_completed"):
            return "completed"
        if kind in ("invocation_failed", "tool_failed"):
            return "failed"
        if kind == "tool_denied":
            return "denied"
    return "running"


def fetch_recent_invocations(
    db_path: Path | str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Fetch distinct recent Proteo invocations with summary metrics.

    Args:
        db_path: Database path to read from.
        limit: Maximum number of invocations to return.

    Returns:
        List of invocation summary dictionaries.
    """
    conn = get_telemetry_connection(db_path, read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT
                invocation_id,
                MIN(occurred_at) AS started_at,
                MAX(duration_ms) AS duration_ms,
                COUNT(CASE WHEN event_kind LIKE 'tool_%' THEN 1 END) AS tool_events,
                COUNT(DISTINCT tool_name) AS tool_count,
                COALESCE(
                    (SELECT CASE
                        WHEN e2.event_kind IN ('invocation_completed', 'tool_completed') THEN 'completed'
                        WHEN e2.event_kind IN ('invocation_failed', 'tool_failed') THEN 'failed'
                        WHEN e2.event_kind = 'tool_denied' THEN 'denied'
                     END
                     FROM runtime_events e2
                     WHERE e2.invocation_id = runtime_events.invocation_id
                       AND e2.event_kind IN ('invocation_completed', 'tool_completed', 'invocation_failed', 'tool_failed', 'tool_denied')
                     ORDER BY e2.occurred_at DESC, e2.id DESC
                     LIMIT 1),
                    'running'
                ) AS status,
                MAX(model) AS model,
                MAX(profile) AS profile,
                MAX(reasoning_effort) AS reasoning_effort
            FROM runtime_events
            WHERE invocation_id IS NOT NULL
            GROUP BY invocation_id
            ORDER BY MIN(occurred_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_last_invocation_id(db_path: Path | str | None = None) -> str | None:
    """Fetch the invocation ID of the most recent Proteo runtime invocation.

    Args:
        db_path: Database path to read from.

    Returns:
        Most recent invocation ID string, or None if no invocations recorded.
    """
    conn = get_telemetry_connection(db_path, read_only=True)
    try:
        row = conn.execute(
            """
            SELECT invocation_id
            FROM runtime_events
            WHERE invocation_id IS NOT NULL
            ORDER BY occurred_at DESC
            LIMIT 1
            """
        ).fetchone()
        return str(row["invocation_id"]) if row else None
    finally:
        conn.close()


def fetch_invocation_events(
    db_path: Path | str | None,
    invocation_id: str,
) -> list[dict[str, Any]]:
    """Fetch all chronological runtime events belonging to an invocation.

    Args:
        db_path: Database path to read from.
        invocation_id: Target invocation ID.

    Returns:
        List of runtime event record dictionaries.
    """
    conn = get_telemetry_connection(db_path, read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM runtime_events
            WHERE invocation_id = ?
            ORDER BY occurred_at ASC, id ASC
            """,
            (invocation_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_task_events(
    db_path: Path | str | None,
    task_id: str,
) -> list[dict[str, Any]]:
    """Fetch all chronological neutral events correlated to one ephemeral task.

    Args:
        db_path: Database path to read from.
        task_id: Provider-neutral task identifier.

    Returns:
        Chronological runtime event dictionaries for the task.
    """
    conn = get_telemetry_connection(db_path, read_only=True)
    try:
        rows = conn.execute(
            "SELECT * FROM runtime_events WHERE task_id = ? ORDER BY occurred_at, id",
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_interaction_events(
    db_path: Path | str | None,
    interaction_id: str,
) -> list[dict[str, Any]]:
    """Fetch chronological runtime and host events for one interaction.

    Args:
        db_path: Telemetry database path.
        interaction_id: Host-generated per-turn correlation identifier.

    Returns:
        Chronological event dictionaries associated with the interaction.
    """
    conn = get_telemetry_connection(db_path, read_only=True)
    try:
        rows = conn.execute(
            "SELECT * FROM runtime_events WHERE interaction_id = ? ORDER BY occurred_at, id",
            (interaction_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_workflow_events(
    db_path: Path | str | None,
    workflow_id: str,
) -> list[dict[str, Any]]:
    """Fetch host transitions associated with one quote workflow.

    Args:
        db_path: Telemetry database path.
        workflow_id: Host-generated quote workflow identifier.

    Returns:
        Chronological metadata-only transitions for the workflow.
    """
    conn = get_telemetry_connection(db_path, read_only=True)
    try:
        rows = conn.execute(
            "SELECT * FROM runtime_events WHERE event_kind = 'host.turn_transition' "
            "ORDER BY occurred_at, id"
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            event = dict(row)
            try:
                metadata = json.loads(str(event.get("metadata_json") or "{}"))
            except (TypeError, ValueError):
                metadata = {}
            if metadata.get("workflow_id") == workflow_id:
                result.append(event)
        return result
    finally:
        conn.close()


def fetch_langsmith_runs(
    db_path: Path | str | None,
    *,
    project_name: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch all LangSmith runs ordered by start time for tree reconstruction.

    Args:
        db_path: Database path to read from.
        project_name: Optional filter by project name.

    Returns:
        List of LangSmith run dictionaries.
    """
    conn = get_telemetry_connection(db_path, read_only=True)
    try:
        if project_name:
            rows = conn.execute(
                """
                SELECT *
                FROM langsmith_runs
                WHERE project_name = ?
                ORDER BY started_at ASC, id ASC
                """,
                (project_name,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM langsmith_runs
                ORDER BY started_at ASC, id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_langsmith_runs_for_invocation(
    db_path: Path | str | None,
    invocation_id: str,
) -> list[dict[str, Any]]:
    """Fetch LangSmith runs strictly correlated to a specific invocation ID.

    Args:
        db_path: Database path to read from.
        invocation_id: Target Proteo invocation ID.

    Returns:
        List of matching LangSmith run dictionaries ordered chronologically.
    """
    conn = get_telemetry_connection(db_path, read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM langsmith_runs
            ORDER BY started_at ASC, id ASC
            """
        ).fetchall()
        matching: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            meta_raw = record.get("metadata_json") or "{}"
            try:
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else dict(meta_raw)
            except Exception:
                meta = {}
            if isinstance(meta, dict) and meta.get("proteo.invocation_id") == invocation_id:
                matching.append(record)
        return matching
    finally:
        conn.close()


def fetch_otel_spans(
    db_path: Path | str | None,
    *,
    trace_id: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch OpenTelemetry spans ordered chronologically.

    Args:
        db_path: Database path to read from.
        trace_id: Optional filter by trace ID.

    Returns:
        List of OpenTelemetry span dictionaries.
    """
    conn = get_telemetry_connection(db_path, read_only=True)
    try:
        if trace_id:
            rows = conn.execute(
                """
                SELECT *
                FROM otel_spans
                WHERE trace_id = ?
                ORDER BY started_at ASC, id ASC
                """,
                (trace_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM otel_spans
                ORDER BY started_at ASC, id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_otel_spans_for_invocation(
    db_path: Path | str | None,
    invocation_id: str,
) -> list[dict[str, Any]]:
    """Fetch OpenTelemetry spans strictly correlated to a specific invocation ID.

    Args:
        db_path: Database path to read from.
        invocation_id: Target Proteo invocation ID.

    Returns:
        List of matching OpenTelemetry span dictionaries ordered chronologically.
    """
    conn = get_telemetry_connection(db_path, read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM otel_spans
            ORDER BY started_at ASC, id ASC
            """
        ).fetchall()
        matching: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            attrs_raw = record.get("attributes_json") or "{}"
            try:
                attrs = json.loads(attrs_raw) if isinstance(attrs_raw, str) else dict(attrs_raw)
            except Exception:
                attrs = {}
            if isinstance(attrs, dict) and attrs.get("proteo.invocation_id") == invocation_id:
                matching.append(record)
        return matching
    finally:
        conn.close()


def fetch_otel_span_events(
    db_path: Path | str | None,
    span_id: str,
) -> list[dict[str, Any]]:
    """Fetch span lifecycle events for a given span.

    Args:
        db_path: Database path to read from.
        span_id: Target span ID.

    Returns:
        List of span event dictionaries.
    """
    conn = get_telemetry_connection(db_path, read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM otel_span_events
            WHERE span_id = ?
            ORDER BY occurred_at ASC, id ASC
            """,
            (span_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_recent_metrics(
    db_path: Path | str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Fetch recent OpenTelemetry metric entries.

    Args:
        db_path: Database path to read from.
        limit: Maximum number of metric rows to fetch.

    Returns:
        List of metric dictionaries.
    """
    conn = get_telemetry_connection(db_path, read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM otel_metrics
            ORDER BY recorded_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
