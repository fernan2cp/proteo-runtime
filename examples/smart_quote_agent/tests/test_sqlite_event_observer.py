"""Unit tests for SQLiteEventObserver."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

# Ensure examples/smart_quote_agent is on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from observability import SQLiteEventObserver  # noqa: E402
from telemetry_db import (  # noqa: E402
    fetch_invocation_events,
    init_telemetry_database,
)

from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind  # noqa: E402


@pytest.fixture
def temp_telemetry_db(tmp_path: Path) -> Path:
    """Provide an initialized clean telemetry database."""
    db_path = tmp_path / "observer_test.sqlite3"
    init_telemetry_database(db_path, reset=True)
    return db_path


@pytest.mark.asyncio
async def test_observer_records_events(temp_telemetry_db: Path) -> None:
    """Verify delivering RuntimeEvents persists them into runtime_events table."""
    observer = SQLiteEventObserver(temp_telemetry_db)
    now = datetime.now(UTC)

    # 1. invocation_started
    evt1 = RuntimeEvent(
        kind=RuntimeEventKind.INVOCATION_STARTED,
        event_id="evt_start",
        sequence=1,
        occurred_at=now,
        runtime="codex",
        invocation_id="inv_test_100",
        session_id="sess_1",
        metadata={
            "proteo.runtime": "codex",
            "proteo.model": "test-model",
            "proteo.profile": "agent",
        },
    )
    await observer.on_event(evt1)

    # 2. tool_completed
    evt2 = RuntimeEvent(
        kind=RuntimeEventKind.TOOL_COMPLETED,
        event_id="evt_tool",
        sequence=2,
        occurred_at=now,
        runtime="codex",
        invocation_id="inv_test_100",
        session_id="sess_1",
        metadata={
            "tool_name": "list_products",
            "tool_call_id": "call_99",
            "status": "completed",
            "duration_ms": 32.5,
            "total_tokens": 150,
        },
    )
    await observer.on_event(evt2)

    # 3. invocation_completed
    evt3 = RuntimeEvent(
        kind=RuntimeEventKind.INVOCATION_COMPLETED,
        event_id="evt_complete",
        sequence=3,
        occurred_at=now,
        runtime="codex",
        invocation_id="inv_test_100",
        session_id="sess_1",
        metadata={"status": "completed", "proteo.latency_ms": 1200.0},
    )
    await observer.on_event(evt3)

    await observer.flush()

    events = fetch_invocation_events(temp_telemetry_db, "inv_test_100")
    assert len(events) == 3

    assert events[0]["event_kind"] == "invocation_started"
    assert events[0]["model"] == "test-model"
    assert events[0]["profile"] == "agent"

    assert events[1]["event_kind"] == "tool_completed"
    assert events[1]["tool_name"] == "list_products"
    assert events[1]["tool_call_id"] == "call_99"
    assert events[1]["duration_ms"] == 32.5

    assert events[2]["event_kind"] == "invocation_completed"
    assert events[2]["status"] == "completed"
    assert events[2]["duration_ms"] == 1200.0


@pytest.mark.asyncio
async def test_observer_idempotent_close(temp_telemetry_db: Path) -> None:
    """Verify flush and close are idempotent and ignore subsequent events."""
    observer = SQLiteEventObserver(temp_telemetry_db)
    await observer.flush()
    await observer.close()
    await observer.close()

    evt = RuntimeEvent(
        kind=RuntimeEventKind.INVOCATION_STARTED,
        event_id="evt_ignored",
        sequence=1,
        occurred_at=datetime.now(UTC),
        runtime="codex",
        invocation_id="inv_ignored",
        metadata={},
    )
    await observer.on_event(evt)

    events = fetch_invocation_events(temp_telemetry_db, "inv_ignored")
    assert len(events) == 0


@pytest.mark.asyncio
async def test_observer_missing_fields_graceful(temp_telemetry_db: Path) -> None:
    """Verify events with empty metadata or missing attributes insert cleanly."""
    observer = SQLiteEventObserver(temp_telemetry_db)
    evt = RuntimeEvent(
        kind=RuntimeEventKind.TURN_STARTED,
        event_id="evt_minimal",
        sequence=1,
        occurred_at=datetime.now(UTC),
        runtime="codex",
        invocation_id="inv_minimal",
        metadata={},
    )
    await observer.on_event(evt)

    events = fetch_invocation_events(temp_telemetry_db, "inv_minimal")
    assert len(events) == 1
    assert events[0]["tool_name"] is None
    assert events[0]["model"] is None
    assert events[0]["metadata_json"] == "{}"
