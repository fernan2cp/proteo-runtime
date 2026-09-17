"""Unit tests for RecordingLangSmithClient and integration with LangSmithObserver."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

# Ensure examples/smart_quote_agent is on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from langsmith_recording import RecordingLangSmithClient  # noqa: E402
from telemetry_db import fetch_langsmith_runs, init_telemetry_database  # noqa: E402

from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind  # noqa: E402
from proteo_runtime.observability.langsmith import LangSmithObserver  # noqa: E402


@pytest.fixture
def temp_telemetry_db(tmp_path: Path) -> Path:
    """Provide an initialized clean telemetry database."""
    db_path = tmp_path / "langsmith_test.sqlite3"
    init_telemetry_database(db_path, reset=True)
    return db_path


def test_recording_client_direct_calls(temp_telemetry_db: Path) -> None:
    """Verify create_run returns dict with id and persists to langsmith_runs."""
    client = RecordingLangSmithClient(temp_telemetry_db)

    run = client.create_run(
        name="root_chain",
        run_type="chain",
        start_time=1700000000000,
        extra={"metadata": {"test": "val"}},
        tags=["unit_test"],
    )
    assert "id" in run
    run_id = run["id"]

    runs = fetch_langsmith_runs(temp_telemetry_db)
    assert len(runs) == 1
    assert runs[0]["run_id"] == run_id
    assert runs[0]["name"] == "root_chain"
    assert runs[0]["status"] == "running"

    # Update run
    client.update_run(
        run_id=run_id,
        end_time=1700000005000,
    )
    runs_after = fetch_langsmith_runs(temp_telemetry_db)
    assert len(runs_after) == 1
    assert runs_after[0]["status"] == "completed"
    assert runs_after[0]["ended_at"] is not None


@pytest.mark.asyncio
async def test_langsmith_observer_integration(temp_telemetry_db: Path) -> None:
    """Verify real LangSmithObserver creates proper hierarchical runs using RecordingLangSmithClient."""
    client = RecordingLangSmithClient(temp_telemetry_db)
    observer = LangSmithObserver(
        client=client,
        project_name="proteo-test",
        owns_client=False,
    )
    now = datetime.now(UTC)

    # 1. INVOCATION_STARTED -> proteo.runtime
    evt_inv_start = RuntimeEvent(
        kind=RuntimeEventKind.INVOCATION_STARTED,
        event_id="evt_inv_start",
        sequence=1,
        occurred_at=now,
        runtime="codex",
        invocation_id="inv_hier_1",
        session_id="sess_1",
        metadata={"proteo.runtime": "codex"},
    )
    await observer.on_event(evt_inv_start)

    # 2. TURN_STARTED -> proteo.turn
    evt_turn_start = RuntimeEvent(
        kind=RuntimeEventKind.TURN_STARTED,
        event_id="evt_turn_start",
        sequence=2,
        occurred_at=now,
        runtime="codex",
        invocation_id="inv_hier_1",
        session_id="sess_1",
        turn_id="turn_1",
        metadata={},
    )
    await observer.on_event(evt_turn_start)

    # 3. TOOL_REQUESTED -> proteo.tool
    evt_tool_req = RuntimeEvent(
        kind=RuntimeEventKind.TOOL_REQUESTED,
        event_id="evt_tool_req",
        sequence=3,
        occurred_at=now,
        runtime="codex",
        invocation_id="inv_hier_1",
        session_id="sess_1",
        turn_id="turn_1",
        metadata={"tool_name": "list_products", "tool_call_id": "call_123"},
    )
    await observer.on_event(evt_tool_req)

    # 4. TOOL_COMPLETED
    evt_tool_comp = RuntimeEvent(
        kind=RuntimeEventKind.TOOL_COMPLETED,
        event_id="evt_tool_comp",
        sequence=4,
        occurred_at=now,
        runtime="codex",
        invocation_id="inv_hier_1",
        session_id="sess_1",
        turn_id="turn_1",
        metadata={"tool_name": "list_products", "tool_call_id": "call_123", "status": "completed"},
    )
    await observer.on_event(evt_tool_comp)

    # 5. TURN_COMPLETED
    evt_turn_comp = RuntimeEvent(
        kind=RuntimeEventKind.TURN_COMPLETED,
        event_id="evt_turn_comp",
        sequence=5,
        occurred_at=now,
        runtime="codex",
        invocation_id="inv_hier_1",
        session_id="sess_1",
        turn_id="turn_1",
        metadata={"status": "completed"},
    )
    await observer.on_event(evt_turn_comp)

    # 6. INVOCATION_COMPLETED
    evt_inv_comp = RuntimeEvent(
        kind=RuntimeEventKind.INVOCATION_COMPLETED,
        event_id="evt_inv_comp",
        sequence=6,
        occurred_at=now,
        runtime="codex",
        invocation_id="inv_hier_1",
        session_id="sess_1",
        metadata={"status": "completed"},
    )
    await observer.on_event(evt_inv_comp)

    await observer.flush()
    await observer.close()

    runs = fetch_langsmith_runs(temp_telemetry_db, project_name="proteo-test")
    assert len(runs) == 3

    run_by_name = {r["name"]: r for r in runs}
    assert "proteo.runtime" in run_by_name
    assert "proteo.turn" in run_by_name
    assert "proteo.tool" in run_by_name

    root_run = run_by_name["proteo.runtime"]
    turn_run = run_by_name["proteo.turn"]
    tool_run = run_by_name["proteo.tool"]

    # Verify hierarchy
    assert root_run["parent_run_id"] is None
    assert turn_run["parent_run_id"] == root_run["run_id"]
    assert tool_run["parent_run_id"] == turn_run["run_id"]

    # Verify completion
    assert root_run["status"] == "completed"
    assert turn_run["status"] == "completed"
    assert tool_run["status"] == "completed"
