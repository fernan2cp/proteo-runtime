"""Unit tests for ObservabilityManager and NonOwningObserver lifecycle management.

Verifies single-ownership architecture between CodexRuntime and host ToolExecutor,
ensuring zero double flush, zero double close, and zero event duplication.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

# Ensure examples/smart_quote_agent is on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from observability import (  # noqa: E402
    NonOwningObserver,
    ObservabilityManager,
    SQLiteEventObserver,
)
from session import AgentSessionManager  # noqa: E402
from telemetry_db import (  # noqa: E402
    fetch_interaction_events,
    fetch_invocation_events,
    fetch_task_events,
    init_telemetry_database,
)

from proteo_runtime.core.diagnostics import RuntimeDiagnostic  # noqa: E402
from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind  # noqa: E402
from proteo_runtime.observability import (  # noqa: E402
    RuntimeEventBus,
)


@pytest.fixture
def temp_obs_db(tmp_path: Path) -> Path:
    """Provide an initialized clean telemetry database."""
    db_path = tmp_path / "lifecycle_test.sqlite3"
    init_telemetry_database(db_path, reset=True)
    return db_path


@pytest.mark.asyncio
async def test_non_owning_observer_does_not_flush_or_close(temp_obs_db: Path) -> None:
    """Verify that NonOwningObserver ignores flush and close while delegating events and errors."""
    underlying = SQLiteEventObserver(temp_obs_db)
    non_owning = NonOwningObserver(underlying)

    # 1. Verify flush is a no-op on the underlying observer
    await non_owning.flush()
    assert underlying.flush_count == 0

    # 2. Verify close is a no-op on the underlying observer
    await non_owning.close()
    assert underlying.close_count == 0
    assert bool(underlying.is_closed) is False

    # 3. Verify on_event forwards to underlying observer
    evt = RuntimeEvent(
        kind=RuntimeEventKind.INVOCATION_STARTED,
        event_id="evt_test_1",
        sequence=1,
        occurred_at=datetime.now(UTC),
        runtime="codex",
        invocation_id="inv_test_lifecycle",
        session_id="sess_1",
    )
    await non_owning.on_event(evt)
    await underlying.flush()

    events = fetch_invocation_events(temp_obs_db, "inv_test_lifecycle")
    assert len(events) == 1
    assert events[0]["event_id"] == "evt_test_1"

    # 4. Verify record_failure forwards to underlying observer
    non_owning.record_failure("SQLiteEventObserver")
    assert underlying.failure_count == 1

    # Cleanup underlying observer
    await underlying.close()
    assert bool(underlying.is_closed) is True
    assert underlying.close_count == 1


@pytest.mark.asyncio
async def test_observability_manager_single_ownership_and_lifecycle(temp_obs_db: Path) -> None:
    """Verify ObservabilityManager owns observers and safely borrows them to CodexRuntime.

    CodexRuntime closing its internal event bus must not close host observers or
    shut down OpenTelemetry providers prematurely.
    """
    mgr = ObservabilityManager(mode="local", db_path=temp_obs_db)

    # Validate that runtime_config uses NonOwningObserver wrappers
    assert len(mgr.runtime_config.observers) == len(mgr.app_config.observers)
    for binding in mgr.runtime_config.observers:
        assert isinstance(binding.observer, NonOwningObserver)

    # Simulate CodexRuntime instantiating and closing its own RuntimeEventBus
    codex_bus = RuntimeEventBus(mgr.runtime_config)
    evt_codex = RuntimeEvent(
        kind=RuntimeEventKind.INVOCATION_STARTED,
        event_id="evt_codex_1",
        sequence=1,
        occurred_at=datetime.now(UTC),
        runtime="codex",
        invocation_id="inv_mgr_1",
        session_id="sess_mgr",
    )
    await codex_bus.emit(evt_codex)

    # CodexRuntime finishes and closes its bus
    await codex_bus.close()

    # Verify that underlying local observers and OTel bundle remain active
    sqlite_obs: SQLiteEventObserver | None = None
    for binding in mgr.app_config.observers:
        if isinstance(binding.observer, SQLiteEventObserver):
            sqlite_obs = binding.observer
            break

    assert sqlite_obs is not None
    assert bool(sqlite_obs.is_closed) is False
    assert sqlite_obs.close_count == 0
    if mgr.otel_bundle is not None:
        assert bool(mgr.otel_bundle.is_shutdown) is False

    # Host ToolExecutor emits event via mgr.bus
    evt_host = RuntimeEvent(
        kind=RuntimeEventKind.TOOL_COMPLETED,
        event_id="evt_host_1",
        sequence=2,
        occurred_at=datetime.now(UTC),
        runtime="codex",
        invocation_id="inv_mgr_1",
        session_id="sess_mgr",
        turn_id="turn_1",
        metadata={"tool_name": "create_quote"},
    )
    await mgr.bus.emit(evt_host)

    # Manager flush and close
    await mgr.flush()
    assert sqlite_obs.flush_count >= 1

    await mgr.close()
    assert bool(sqlite_obs.is_closed) is True
    assert sqlite_obs.close_count == 1
    if mgr.otel_bundle is not None:
        assert bool(mgr.otel_bundle.is_shutdown) is True

    # Idempotent close
    await mgr.close()
    assert sqlite_obs.close_count == 1


@pytest.mark.asyncio
async def test_zero_event_duplication_across_buses(temp_obs_db: Path) -> None:
    """Verify that events dispatched through codex_bus and host_bus do not duplicate."""
    mgr = ObservabilityManager(mode="local", db_path=temp_obs_db)
    codex_bus = RuntimeEventBus(mgr.runtime_config)

    evt1 = RuntimeEvent(
        kind=RuntimeEventKind.INVOCATION_STARTED,
        event_id="evt_dup_1",
        sequence=1,
        occurred_at=datetime.now(UTC),
        runtime="codex",
        invocation_id="inv_dup_test",
        session_id="sess_dup",
    )
    evt2 = RuntimeEvent(
        kind=RuntimeEventKind.INVOCATION_COMPLETED,
        event_id="evt_dup_2",
        sequence=2,
        occurred_at=datetime.now(UTC),
        runtime="codex",
        invocation_id="inv_dup_test",
        session_id="sess_dup",
    )

    try:
        await codex_bus.emit(evt1)
        await mgr.bus.emit(evt2)
    finally:
        await codex_bus.close()
        await mgr.close()

    events = fetch_invocation_events(temp_obs_db, "inv_dup_test")
    assert len(events) == 2
    event_ids = [e["event_id"] for e in events]
    assert event_ids == ["evt_dup_1", "evt_dup_2"]


@pytest.mark.asyncio
async def test_host_transition_event_is_task_correlated_and_metadata_only(
    temp_obs_db: Path,
) -> None:
    """Persist only allow-listed transition metadata under the runtime task ID."""
    manager = ObservabilityManager(mode="local", db_path=temp_obs_db)
    try:
        manager.record_host_event(
            {
                "interaction_id": "interaction-1",
                "task_id": "task-1",
                "workflow_id": "quote-1",
                "revision": 4,
                "intent": "quote_create",
                "route": "resolve_quote_data",
                "phase_before": "collecting",
                "phase_after": "needs_resolution",
                "result_code": "resolution_required",
                "prompt": "private user text",
                "password": "private credential",
            }
        )
    finally:
        await manager.close()

    events = fetch_task_events(temp_obs_db, "task-1")
    assert len(events) == 1
    assert events[0]["event_kind"] == "host.turn_transition"
    interaction_events = fetch_interaction_events(temp_obs_db, "interaction-1")
    assert interaction_events == events
    metadata = json.loads(str(events[0]["metadata_json"]))
    assert metadata["workflow_id"] == "quote-1"
    assert "prompt" not in metadata
    assert "password" not in metadata


@pytest.mark.asyncio
async def test_runtime_event_extracts_interaction_and_task_correlation(
    temp_obs_db: Path,
) -> None:
    """Project safe invocation metadata into indexed event correlation columns."""
    observer = SQLiteEventObserver(temp_obs_db)
    event = RuntimeEvent(
        kind=RuntimeEventKind.INVOCATION_STARTED,
        event_id="runtime-interaction-correlation",
        sequence=1,
        occurred_at=datetime.now(UTC),
        runtime="codex",
        invocation_id="inv-interaction-correlation",
        metadata={
            "interaction_id": "interaction-runtime-correlation",
            "task_id": "task-runtime-correlation",
            "stage": "intent_router",
        },
    )

    await observer.on_event(event)

    events = fetch_interaction_events(temp_obs_db, "interaction-runtime-correlation")
    assert len(events) == 1
    assert events[0]["event_kind"] == "invocation_started"
    assert events[0]["invocation_id"] == "inv-interaction-correlation"
    assert events[0]["task_id"] == "task-runtime-correlation"


@pytest.mark.asyncio
async def test_task_cleanup_diagnostic_is_correlated_and_redacted(temp_obs_db: Path) -> None:
    """Persist cleanup diagnostic codes from task lifecycle without provider details."""
    manager = ObservabilityManager(mode="local", db_path=temp_obs_db)
    business_conn = sqlite3.connect(":memory:")

    class DiagnosticTask:
        """Minimal closeable test task exposing a sanitized cleanup diagnostic."""

        id = "task-cleanup-1"
        diagnostics = (
            RuntimeDiagnostic(
                code="task.cleanup.provider_delete_failed",
                message="Remote task cleanup failed.",
                details={"provider_payload": "must not be stored"},
            ),
        )

        async def close(self) -> None:
            """Complete fake task close without provider interaction."""

    sessions = AgentSessionManager(
        runtime=object(),
        conn=business_conn,
        host_event_sink=manager.record_host_event,
    )
    sessions._active_task = cast(Any, DiagnosticTask())
    try:
        await sessions.close()
    finally:
        business_conn.close()
        await manager.close()

    events = fetch_task_events(temp_obs_db, "task-cleanup-1")
    assert len(events) == 1
    assert events[0]["event_kind"] == "task.cleanup.provider_delete_failed"
    metadata = json.loads(str(events[0]["metadata_json"]))
    assert metadata["diagnostic_code"] == "task.cleanup.provider_delete_failed"
    assert "provider_payload" not in metadata
