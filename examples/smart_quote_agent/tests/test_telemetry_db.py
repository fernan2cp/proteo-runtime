"""Unit tests for telemetry database schema, connection management, and concurrency."""

from __future__ import annotations

import concurrent.futures
import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure examples/smart_quote_agent is on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from telemetry_db import (  # noqa: E402
    fetch_invocation_events,
    fetch_langsmith_runs,
    fetch_last_invocation_id,
    fetch_otel_span_events,
    fetch_otel_spans,
    fetch_recent_invocations,
    fetch_recent_metrics,
    get_telemetry_connection,
    init_telemetry_database,
    insert_langsmith_create_run,
    insert_otel_metric,
    insert_otel_span,
    insert_otel_span_event,
    insert_runtime_event,
    update_langsmith_run,
    utc_now_iso,
)


@pytest.fixture
def temp_telemetry_db(tmp_path: Path) -> Path:
    """Create a clean, initialized temporary telemetry database path."""
    db_path = tmp_path / "observability_test.sqlite3"
    init_telemetry_database(db_path, reset=True)
    return db_path


def test_schema_creation_and_indexes(temp_telemetry_db: Path) -> None:
    """Verify that all 5 telemetry tables and their 10 indexes are created."""
    conn = get_telemetry_connection(temp_telemetry_db)
    try:
        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        assert "runtime_events" in tables
        assert "langsmith_runs" in tables
        assert "otel_spans" in tables
        assert "otel_span_events" in tables
        assert "otel_metrics" in tables

        indexes = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        expected_indexes = {
            "idx_runtime_events_invocation",
            "idx_runtime_events_interaction",
            "idx_runtime_events_kind",
            "idx_runtime_events_occurred_at",
            "idx_langsmith_runs_parent",
            "idx_langsmith_runs_started",
            "idx_otel_spans_trace",
            "idx_otel_spans_parent",
            "idx_otel_spans_started",
            "idx_otel_span_events_span",
            "idx_otel_metrics_recorded",
        }
        for idx in expected_indexes:
            assert idx in indexes, f"Missing index: {idx}"
    finally:
        conn.close()


def test_task_id_schema_migration_is_additive_and_idempotent(tmp_path: Path) -> None:
    """Add task correlation to an existing runtime event table without dropping data."""
    db_path = tmp_path / "legacy_observability.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE runtime_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, recorded_at TEXT NOT NULL, "
            "occurred_at TEXT NOT NULL, event_id TEXT NOT NULL, event_kind TEXT NOT NULL, "
            "invocation_id TEXT NULL, session_id TEXT NULL, turn_id TEXT NULL, "
            "runtime_name TEXT NULL, model TEXT NULL, profile TEXT NULL, "
            "reasoning_effort TEXT NULL, tool_name TEXT NULL, tool_call_id TEXT NULL, "
            "status TEXT NULL, duration_ms REAL NULL, metadata_json TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO runtime_events "
            "(recorded_at, occurred_at, event_id, event_kind, metadata_json) "
            "VALUES ('now', 'then', 'legacy-1', 'invocation_started', '{}')"
        )
        conn.commit()
    finally:
        conn.close()

    init_telemetry_database(db_path)
    init_telemetry_database(db_path)

    conn = get_telemetry_connection(db_path, read_only=True)
    try:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(runtime_events);").fetchall()
        }
        indexes = {
            str(row["name"])
            for row in conn.execute("PRAGMA index_list(runtime_events);").fetchall()
        }
        rows = conn.execute(
            "SELECT event_id, task_id, interaction_id FROM runtime_events;"
        ).fetchall()
        assert "task_id" in columns
        assert "interaction_id" in columns
        assert "idx_runtime_events_task" in indexes
        assert "idx_runtime_events_interaction" in indexes
        assert [(row["event_id"], row["task_id"], row["interaction_id"]) for row in rows] == [
            ("legacy-1", None, None)
        ]
    finally:
        conn.close()


def test_wal_and_busy_timeout_pragmas(temp_telemetry_db: Path) -> None:
    """Verify that WAL mode and 5000 ms busy timeout are enabled on connections."""
    conn = get_telemetry_connection(temp_telemetry_db)
    try:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert journal_mode.lower() == "wal"

        busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
        assert busy_timeout == 5000

        foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        assert foreign_keys == 1
    finally:
        conn.close()


def test_reset_functionality(temp_telemetry_db: Path) -> None:
    """Verify that reset cleans existing rows and reapplies schema."""
    insert_runtime_event(
        temp_telemetry_db,
        event_id="evt_1",
        event_kind="invocation_started",
        occurred_at=utc_now_iso(),
        invocation_id="inv_test",
    )

    events_before = fetch_invocation_events(temp_telemetry_db, "inv_test")
    assert len(events_before) == 1

    # Reset
    init_telemetry_database(temp_telemetry_db, reset=True)
    events_after = fetch_invocation_events(temp_telemetry_db, "inv_test")
    assert len(events_after) == 0


def test_typed_insert_helpers(temp_telemetry_db: Path) -> None:
    """Verify inserting records across all 5 tables."""
    now = utc_now_iso()

    # 1. runtime_events
    row_id = insert_runtime_event(
        temp_telemetry_db,
        event_id="evt_abc",
        event_kind="tool_completed",
        occurred_at=now,
        invocation_id="inv_123",
        tool_name="list_products",
        tool_call_id="call_1",
        status="completed",
        duration_ms=45.2,
        metadata={"total_tokens": 120},
    )
    assert row_id > 0

    # 2. langsmith_runs
    insert_langsmith_create_run(
        temp_telemetry_db,
        run_id="run_root",
        name="proteo.runtime",
        run_type="chain",
        project_name="test-project",
        started_at=now,
        tags=["demo"],
        metadata={"model": "test-model"},
    )
    update_langsmith_run(
        temp_telemetry_db,
        run_id="run_root",
        ended_at=now,
        status="completed",
    )

    # 3. otel_spans
    insert_otel_span(
        temp_telemetry_db,
        trace_id="trace_001",
        span_id="span_001",
        name="proteo.invocation",
        started_at=now,
        ended_at=now,
        duration_ms=102.5,
        status_code="OK",
        attributes={"proteo.invocation_id": "inv_123"},
    )

    # 4. otel_span_events
    insert_otel_span_event(
        temp_telemetry_db,
        span_id="span_001",
        name="tool_approval_requested",
        occurred_at=now,
        attributes={"tool_name": "create_quote"},
    )

    # 5. otel_metrics
    insert_otel_metric(
        temp_telemetry_db,
        instrument_name="proteo.runtime.events",
        instrument_type="counter",
        value=1.0,
        attributes={"runtime": "codex"},
    )

    # Verify reads
    events = fetch_invocation_events(temp_telemetry_db, "inv_123")
    assert len(events) == 1
    assert events[0]["tool_name"] == "list_products"

    runs = fetch_langsmith_runs(temp_telemetry_db, project_name="test-project")
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"

    spans = fetch_otel_spans(temp_telemetry_db, trace_id="trace_001")
    assert len(spans) == 1
    assert spans[0]["name"] == "proteo.invocation"

    span_events = fetch_otel_span_events(temp_telemetry_db, "span_001")
    assert len(span_events) == 1
    assert span_events[0]["name"] == "tool_approval_requested"

    metrics = fetch_recent_metrics(temp_telemetry_db)
    assert len(metrics) == 1
    assert metrics[0]["instrument_name"] == "proteo.runtime.events"


def test_read_helpers_and_summary_queries(temp_telemetry_db: Path) -> None:
    """Verify invocation summary queries and last invocation resolution."""
    ts1 = "2026-09-16T12:00:00.000Z"
    ts2 = "2026-09-16T12:05:00.000Z"

    insert_runtime_event(
        temp_telemetry_db,
        event_id="e1",
        event_kind="invocation_started",
        occurred_at=ts1,
        invocation_id="inv_old",
        model="model-v1",
    )
    insert_runtime_event(
        temp_telemetry_db,
        event_id="e2",
        event_kind="invocation_completed",
        occurred_at=ts1,
        invocation_id="inv_old",
        duration_ms=2000.0,
    )

    insert_runtime_event(
        temp_telemetry_db,
        event_id="e3",
        event_kind="invocation_started",
        occurred_at=ts2,
        invocation_id="inv_new",
        model="model-v2",
    )

    summaries = fetch_recent_invocations(temp_telemetry_db, limit=10)
    assert len(summaries) == 2
    assert summaries[0]["invocation_id"] == "inv_new"
    assert summaries[1]["invocation_id"] == "inv_old"

    last_id = fetch_last_invocation_id(temp_telemetry_db)
    assert last_id == "inv_new"


def test_concurrent_writes(temp_telemetry_db: Path) -> None:
    """Verify that multiple worker threads can write concurrently without database lock errors."""

    def _worker(thread_idx: int) -> None:
        for i in range(10):
            insert_runtime_event(
                temp_telemetry_db,
                event_id=f"evt_t{thread_idx}_{i}",
                event_kind="tool_started",
                occurred_at=utc_now_iso(),
                invocation_id=f"inv_concurrent_{thread_idx}",
                tool_name="test_tool",
            )
            insert_otel_metric(
                temp_telemetry_db,
                instrument_name="concurrent_counter",
                instrument_type="counter",
                value=1.0,
            )

    thread_count = 20
    with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as executor:
        futures = [executor.submit(_worker, idx) for idx in range(thread_count)]
        for f in concurrent.futures.as_completed(futures):
            f.result()  # Will raise if any thread encountered OperationalError

    # Assert total records
    conn = get_telemetry_connection(temp_telemetry_db)
    try:
        event_count = conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0]
        assert event_count == thread_count * 10

        metric_count = conn.execute("SELECT COUNT(*) FROM otel_metrics").fetchone()[0]
        assert metric_count == thread_count * 10
    finally:
        conn.close()


def test_init_observability_cli(tmp_path: Path) -> None:
    """Verify executing init_observability.py directly via subprocess."""
    import subprocess

    target_db = tmp_path / "cli_test.sqlite3"
    init_script = _DEMO_DIR / "init_observability.py"

    # 1. Initial creation
    result = subprocess.run(
        [sys.executable, str(init_script), "--db-path", str(target_db)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "initialized" in result.stdout
    assert target_db.exists()

    # 2. Already exists without --reset
    result_exists = subprocess.run(
        [sys.executable, str(init_script), "--db-path", str(target_db)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_exists.returncode == 0
    assert "already exists" in result_exists.stdout

    # 3. Wipe and reset with --reset
    result_reset = subprocess.run(
        [sys.executable, str(init_script), "--db-path", str(target_db), "--reset"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_reset.returncode == 0
    assert "reset and initialized" in result_reset.stdout
    assert target_db.exists()
