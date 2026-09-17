"""Unit tests for standalone telemetry inspector CLI and formatting."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure examples/smart_quote_agent is on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from inspect_observability import (  # noqa: E402
    build_langsmith_tree,
    inspect_telemetry,
    main,
    render_recent_invocations_summary,
)
from telemetry_db import (  # noqa: E402
    init_telemetry_database,
    insert_langsmith_create_run,
    insert_otel_metric,
    insert_otel_span,
    insert_otel_span_event,
    insert_runtime_event,
)


@pytest.fixture
def clean_obs_db(tmp_path: Path) -> Path:
    """Provide an initialized clean telemetry database."""
    db = tmp_path / "inspect_test.sqlite3"
    init_telemetry_database(db, reset=True)
    return db


def test_inspector_uninitialized_db(tmp_path: Path) -> None:
    """Verify friendly error message when database does not exist."""
    missing_db = tmp_path / "non_existent.sqlite3"
    out = inspect_telemetry(missing_db)
    assert "Observability database not found" in out
    assert "init_observability.py" in out


def test_inspector_empty_database(clean_obs_db: Path) -> None:
    """Verify empty database displays host-only disclaimer text in summary and --last."""
    # 1. Summary view
    out_summary = inspect_telemetry(clean_obs_db)
    assert "Recent Proteo invocations" in out_summary
    assert "No Proteo runtime invocations found" in out_summary
    assert "Host-only interactions" in out_summary

    # 2. --last view
    out_last = inspect_telemetry(clean_obs_db, last=True)
    assert "No Proteo runtime invocations found" in out_last
    assert "Host-only interactions" in out_last


def test_build_langsmith_tree_reconstruction() -> None:
    """Verify recursive LangSmith tree hierarchy reconstruction."""
    runs: list[dict[str, Any]] = [
        {
            "run_id": "root-1",
            "parent_run_id": None,
            "name": "proteo.runtime",
            "metadata_json": "{}",
        },
        {
            "run_id": "turn-1",
            "parent_run_id": "root-1",
            "name": "proteo.turn",
            "metadata_json": "{}",
        },
        {
            "run_id": "tool-1",
            "parent_run_id": "turn-1",
            "name": "proteo.tool",
            "metadata_json": '{"tool_name": "list_products"}',
        },
    ]
    tree_lines = build_langsmith_tree(runs)
    rendered = "\n".join(tree_lines)

    assert "proteo.runtime" in rendered
    assert "└── proteo.turn" in rendered
    assert "└── proteo.tool [list_products]" in rendered


def test_inspector_populated_database_queries(clean_obs_db: Path) -> None:
    """Verify summary, detailed --last, and filter views with populated telemetry."""
    inv_id = "inv_audit_100"

    # 1. Seed runtime_events
    insert_runtime_event(
        clean_obs_db,
        event_id="e1",
        event_kind="invocation_started",
        occurred_at="2026-09-16T12:00:00.000Z",
        invocation_id=inv_id,
        runtime_name="codex",
        model="gpt-4o-mini",
        profile="controlled_agent",
        reasoning_effort="low",
        duration_ms=0.0,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="e2",
        event_kind="tool_requested",
        occurred_at="2026-09-16T12:00:01.000Z",
        invocation_id=inv_id,
        tool_name="list_products",
        status="running",
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="e3",
        event_kind="tool_completed",
        occurred_at="2026-09-16T12:00:02.000Z",
        invocation_id=inv_id,
        tool_name="list_products",
        status="completed",
        duration_ms=150.0,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="e4",
        event_kind="invocation_completed",
        occurred_at="2026-09-16T12:00:03.000Z",
        invocation_id=inv_id,
        status="completed",
        duration_ms=3000.0,
    )

    # 2. Seed langsmith_runs
    insert_langsmith_create_run(
        clean_obs_db,
        run_id="ls_root",
        name="proteo.runtime",
        run_type="chain",
        started_at="2026-09-16T12:00:00.000Z",
        metadata={"proteo.invocation_id": inv_id},
    )
    insert_langsmith_create_run(
        clean_obs_db,
        run_id="ls_turn",
        parent_run_id="ls_root",
        name="proteo.turn",
        run_type="chain",
        started_at="2026-09-16T12:00:00.500Z",
        metadata={"proteo.invocation_id": inv_id},
    )
    insert_langsmith_create_run(
        clean_obs_db,
        run_id="ls_tool",
        parent_run_id="ls_turn",
        name="proteo.tool",
        run_type="tool",
        started_at="2026-09-16T12:00:01.000Z",
        metadata={"proteo.invocation_id": inv_id, "tool_name": "list_products"},
    )

    # 3. Seed otel_spans & span events
    insert_otel_span(
        clean_obs_db,
        trace_id="trace_1",
        span_id="span_tool",
        name="proteo.tool",
        started_at="2026-09-16T12:00:01.000Z",
        duration_ms=150.0,
        status_code="OK",
        attributes={"proteo.invocation_id": inv_id},
    )
    insert_otel_span_event(
        clean_obs_db,
        span_id="span_tool",
        name="tool_approval_requested",
        occurred_at="2026-09-16T12:00:01.200Z",
    )

    # 4. Seed otel_metrics
    insert_otel_metric(
        clean_obs_db,
        instrument_name="proteo.runtime.events",
        instrument_type="counter",
        value=4.0,
    )

    # --- Test Summary View ---
    summary = render_recent_invocations_summary(clean_obs_db)
    assert inv_id in summary or inv_id[:13] in summary
    assert "completed" in summary
    assert "Host-only interactions" in summary

    # --- Test --last View (all sections) ---
    detail_last = inspect_telemetry(clean_obs_db, last=True)
    assert f"Invocation {inv_id}" in detail_last
    assert "gpt-4o-mini" in detail_last
    assert "controlled_agent" in detail_last
    assert "Runtime Events" in detail_last
    assert "list_products" in detail_last
    assert "LangSmith Projection" in detail_last
    assert "└── proteo.tool [list_products]" in detail_last
    assert "OpenTelemetry Spans" in detail_last
    assert "event: tool_approval_requested" in detail_last
    assert "OpenTelemetry Metrics" in detail_last
    assert "proteo.runtime.events" in detail_last

    # --- Test Filters ---
    events_only = inspect_telemetry(clean_obs_db, last=True, events_only=True)
    assert "Runtime Events" in events_only
    assert "LangSmith Projection" not in events_only
    assert "OpenTelemetry Spans" not in events_only

    ls_only = inspect_telemetry(clean_obs_db, last=True, langsmith_only=True)
    assert "Runtime Events" not in ls_only
    assert "LangSmith Projection" in ls_only
    assert "OpenTelemetry Spans" not in ls_only

    otel_only = inspect_telemetry(clean_obs_db, last=True, otel_only=True)
    assert "Runtime Events" not in otel_only
    assert "LangSmith Projection" not in otel_only
    assert "OpenTelemetry Spans" in otel_only

    # --- Test Non-existent invocation ---
    missing_inv = inspect_telemetry(clean_obs_db, invocation="non_existent_id")
    assert "not found in telemetry database" in missing_inv


def test_main_cli_execution(clean_obs_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify main() entrypoint handles CLI flags and returns proper exit codes."""
    db_str = str(clean_obs_db)

    # 1. Exit code 0 on empty summary
    code = main(["--db", db_str])
    assert code == 0
    captured = capsys.readouterr()
    assert "Recent Proteo invocations" in captured.out

    # 2. Exit code 1 on non-existent invocation
    code = main(["--db", db_str, "--invocation", "missing_id"])
    assert code == 1
    captured = capsys.readouterr()
    assert "not found in telemetry database" in captured.out
