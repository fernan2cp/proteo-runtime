"""Unit and integration tests for unified observability configuration and host event wiring."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure examples/smart_quote_agent is on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from database import init_database, seed_database  # noqa: E402
from graph import create_demo_graph  # noqa: E402
from models import AuthenticatedUser, DemoState  # noqa: E402
from observability import (  # noqa: E402
    SQLiteEventObserver,
    create_observability_config,
    get_observability_bus,
)
from telemetry_db import init_telemetry_database  # noqa: E402

from proteo_runtime.observability import PayloadMode, RuntimeObserver  # noqa: E402
from proteo_runtime.observability.langsmith import LangSmithObserver  # noqa: E402
from proteo_runtime.observability.opentelemetry import OpenTelemetryObserver  # noqa: E402
from proteo_runtime.tools import ApprovalDecision, ApprovalHandler  # noqa: E402


class AutoApprovalHandler(ApprovalHandler):
    """Test approval handler that automatically approves all requests."""

    async def request_approval(self, request: Any) -> ApprovalDecision:
        """Approve unconditionally.

        Args:
            request: Inbound approval request.

        Returns:
            Always ApprovalDecision.APPROVE for testing.
        """
        return ApprovalDecision.APPROVE


def test_create_observability_config_modes(tmp_path: Path) -> None:
    """Verify create_observability_config handles all supported and invalid modes.

    Args:
        tmp_path: Temporary pytest directory.
    """
    obs_db = tmp_path / "obs.sqlite3"
    init_telemetry_database(obs_db)

    # 1. Mode: off
    cfg_off = create_observability_config(mode="off", db_path=obs_db)
    assert len(cfg_off.observers) == 0
    assert not cfg_off.strict

    # 2. Mode: local (default)
    cfg_local = create_observability_config(mode="local", db_path=obs_db)
    assert len(cfg_local.observers) == 3
    assert not cfg_local.strict
    for binding in cfg_local.observers:
        assert binding.payload_mode == PayloadMode.METADATA_ONLY

    observer_types = {type(b.observer) for b in cfg_local.observers}
    assert SQLiteEventObserver in observer_types
    assert LangSmithObserver in observer_types
    assert OpenTelemetryObserver in observer_types

    # 3. Mode: local+langsmith
    cfg_ls = create_observability_config(mode="local+langsmith", db_path=obs_db)
    assert len(cfg_ls.observers) == 4
    assert not cfg_ls.strict

    # 4. Mode from environment
    os.environ["DEMO_OBSERVABILITY"] = "off"
    try:
        cfg_env = create_observability_config(db_path=obs_db)
        assert len(cfg_env.observers) == 0
    finally:
        del os.environ["DEMO_OBSERVABILITY"]

    # 5. Invalid mode raises ValueError
    with pytest.raises(ValueError, match="Unsupported observability mode"):
        create_observability_config(mode="unsupported_mode", db_path=obs_db)


@pytest.mark.asyncio
async def test_quote_creation_publishes_tool_lifecycle_events(tmp_path: Path) -> None:
    """Verify that quote creation publishes tool lifecycle events through event_sink into SQLite.

    Args:
        tmp_path: Temporary pytest directory.
    """
    demo_db = tmp_path / "demo.sqlite3"
    init_database(demo_db, reset=True)
    seed_database(demo_db)

    obs_db = tmp_path / "observability.sqlite3"
    init_telemetry_database(obs_db)

    conn = sqlite3.connect(str(demo_db))
    conn.row_factory = sqlite3.Row

    obs_config = create_observability_config(mode="local", db_path=obs_db)
    bus = get_observability_bus(obs_config)

    staff_user = AuthenticatedUser(
        user_id=1,
        username="carla",
        display_name="Carla Staff",
        role="staff",
    )

    app_graph = create_demo_graph(
        conn,
        structured_model=None,
        context_agent=None,
        approval_handler=AutoApprovalHandler(),
        discount_prompter=lambda _subtotal: 10,
        event_sink=bus.emit,
    )

    try:
        initial_state: DemoState = {
            "input": "Create a quote for Globex for 2 Notebook Pro",
            "authenticated_user": staff_user,
        }
        result = await app_graph.ainvoke(initial_state)

        assert result.get("created_quote_id") is not None
        assert "[SUCCESS] Quote #" in result.get("output", "")
    finally:
        await bus.close()
        conn.close()

    # Query observability.sqlite3 directly to verify persisted telemetry
    obs_conn = sqlite3.connect(str(obs_db))
    obs_conn.row_factory = sqlite3.Row

    # Verify runtime_events contains tool lifecycle events
    events = obs_conn.execute(
        "SELECT event_kind, tool_name, status FROM runtime_events ORDER BY id ASC"
    ).fetchall()

    event_kinds = [row["event_kind"] for row in events]
    assert "tool_requested" in event_kinds
    assert "tool_approval_requested" in event_kinds
    assert "tool_approval_resolved" in event_kinds
    assert "tool_started" in event_kinds
    assert "tool_completed" in event_kinds

    # Verify tool_name was captured
    create_quote_events = [e for e in events if e["tool_name"] == "create_quote"]
    assert len(create_quote_events) >= 1

    # Verify otel_spans contains tool span
    spans = obs_conn.execute("SELECT name, status_code FROM otel_spans").fetchall()
    span_names = [row["name"] for row in spans]
    assert any("tool" in name for name in span_names)

    # Verify langsmith_runs contains tool run
    runs = obs_conn.execute("SELECT name, run_type, status FROM langsmith_runs").fetchall()
    run_names = [row["name"] for row in runs]
    assert any("tool" in name or "create_quote" in name for name in run_names)

    obs_conn.close()


class FailingObserver(RuntimeObserver):
    """Test observer that throws an error on every event to simulate backend crash."""

    async def on_event(self, event: Any) -> None:
        """Raise simulated database error.

        Args:
            event: Ignored event.

        Raises:
            sqlite3.OperationalError: Always.
        """
        raise sqlite3.OperationalError("Simulated database failure during write")

    async def flush(self) -> None:
        """No-op flush."""

    async def close(self) -> None:
        """No-op close."""


@pytest.mark.asyncio
async def test_observer_failure_isolation_allows_quote_creation(tmp_path: Path) -> None:
    """Verify that observer failures do not crash quote creation when strict=False.

    Args:
        tmp_path: Temporary pytest directory.
    """
    from proteo_runtime.core.observability import ObservabilityStatus
    from proteo_runtime.observability import ObservabilityConfig, ObserverBinding

    demo_db = tmp_path / "demo.sqlite3"
    init_database(demo_db, reset=True)
    seed_database(demo_db)

    failing_obs = FailingObserver()
    config = ObservabilityConfig(
        observers=(ObserverBinding(failing_obs, PayloadMode.METADATA_ONLY),),
        strict=False,
    )
    bus = get_observability_bus(config)

    conn = sqlite3.connect(str(demo_db))
    conn.row_factory = sqlite3.Row

    staff_user = AuthenticatedUser(
        user_id=1,
        username="carla",
        display_name="Carla Staff",
        role="staff",
    )

    app_graph = create_demo_graph(
        conn,
        structured_model=None,
        context_agent=None,
        approval_handler=AutoApprovalHandler(),
        discount_prompter=lambda _subtotal: 5,
        event_sink=bus.emit,
    )

    try:
        initial_state: DemoState = {
            "input": "Create a quote for Globex for 1 Notebook Pro",
            "authenticated_user": staff_user,
        }
        result = await app_graph.ainvoke(initial_state)

        # Business outcome succeeded despite observer failure
        assert result.get("created_quote_id") is not None
        assert "[SUCCESS] Quote #" in result.get("output", "")

        # Bus recorded failure and transitioned to DEGRADED
        assert bus.status == ObservabilityStatus.DEGRADED
    finally:
        await bus.close()
        conn.close()
