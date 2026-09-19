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
    build_otel_span_tree,
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


def test_build_otel_span_tree_reconstruction() -> None:
    """Verify recursive OpenTelemetry span tree hierarchy reconstruction."""
    spans: list[dict[str, Any]] = [
        {
            "span_id": "span_root",
            "parent_span_id": None,
            "name": "proteo.runtime",
            "duration_ms": 250.0,
        },
        {
            "span_id": "span_turn",
            "parent_span_id": "span_root",
            "name": "proteo.turn",
            "duration_ms": 200.0,
        },
        {
            "span_id": "span_tool",
            "parent_span_id": "span_turn",
            "name": "proteo.tool",
            "duration_ms": 50.0,
        },
    ]
    tree_lines = build_otel_span_tree(spans)
    rendered = "\n".join(tree_lines)

    assert "proteo.runtime" in rendered
    assert "└── proteo.turn" in rendered
    assert "└── proteo.tool" in rendered
    assert "250 ms" in rendered
    assert "50 ms" in rendered


def test_inspector_correlation_isolation_no_fallback(clean_obs_db: Path) -> None:
    """Verify exact correlation matching without fallback to other invocations' data."""
    inv_a = "inv_session_alpha"
    inv_b = "inv_session_beta"

    # Seed Invocation A with events, LangSmith runs, and OTel spans
    insert_runtime_event(
        clean_obs_db,
        event_id="ea1",
        event_kind="invocation_started",
        occurred_at="2026-09-16T10:00:00.000Z",
        invocation_id=inv_a,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="ea2",
        event_kind="invocation_completed",
        occurred_at="2026-09-16T10:00:01.000Z",
        invocation_id=inv_a,
    )
    insert_langsmith_create_run(
        clean_obs_db,
        run_id="run_a",
        name="proteo.runtime.alpha",
        metadata={"proteo.invocation_id": inv_a},
    )
    insert_otel_span(
        clean_obs_db,
        trace_id="trace_a",
        span_id="span_a",
        name="span.alpha",
        started_at="2026-09-16T10:00:00.000Z",
        attributes={"proteo.invocation_id": inv_a},
    )

    # Seed Invocation B with events ONLY (no LangSmith runs, no OTel spans)
    insert_runtime_event(
        clean_obs_db,
        event_id="eb1",
        event_kind="invocation_started",
        occurred_at="2026-09-16T11:00:00.000Z",
        invocation_id=inv_b,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="eb2",
        event_kind="invocation_completed",
        occurred_at="2026-09-16T11:00:01.000Z",
        invocation_id=inv_b,
    )

    # Inspect Invocation B: must NOT contain Invocation A's runs or spans
    detail_b = inspect_telemetry(clean_obs_db, invocation=inv_b)
    assert f"Invocation {inv_b}" in detail_b
    assert "proteo.runtime.alpha" not in detail_b
    assert "span.alpha" not in detail_b
    assert "(No LangSmith runs recorded for this invocation)" in detail_b
    assert "(No OpenTelemetry spans recorded for this invocation)" in detail_b

    # Inspect Invocation A: must contain its own runs and spans
    detail_a = inspect_telemetry(clean_obs_db, invocation=inv_a)
    assert f"Invocation {inv_a}" in detail_a
    assert "proteo.runtime.alpha" in detail_a
    assert "span.alpha" in detail_a


def test_inspector_tool_invocation_statuses(clean_obs_db: Path) -> None:
    """Verify statuses ('completed', 'failed', 'denied', 'running') in summary and details."""
    # 1. Completed tool invocation
    insert_runtime_event(
        clean_obs_db,
        event_id="ec1",
        event_kind="tool_requested",
        occurred_at="2026-09-16T12:00:00.000Z",
        invocation_id="inv_completed",
        tool_name="list_products",
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="ec2",
        event_kind="tool_completed",
        occurred_at="2026-09-16T12:00:01.000Z",
        invocation_id="inv_completed",
        tool_name="list_products",
    )

    # 2. Denied tool invocation
    insert_runtime_event(
        clean_obs_db,
        event_id="ed1",
        event_kind="tool_requested",
        occurred_at="2026-09-16T12:01:00.000Z",
        invocation_id="inv_denied",
        tool_name="create_quote",
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="ed2",
        event_kind="tool_denied",
        occurred_at="2026-09-16T12:01:01.000Z",
        invocation_id="inv_denied",
        tool_name="create_quote",
    )

    # 3. Failed tool invocation
    insert_runtime_event(
        clean_obs_db,
        event_id="ef1",
        event_kind="tool_requested",
        occurred_at="2026-09-16T12:02:00.000Z",
        invocation_id="inv_failed",
        tool_name="get_quote",
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="ef2",
        event_kind="tool_failed",
        occurred_at="2026-09-16T12:02:01.000Z",
        invocation_id="inv_failed",
        tool_name="get_quote",
    )

    # 4. Running tool invocation (no terminal event)
    insert_runtime_event(
        clean_obs_db,
        event_id="er1",
        event_kind="tool_requested",
        occurred_at="2026-09-16T12:03:00.000Z",
        invocation_id="inv_running",
        tool_name="list_quotes",
    )

    summary = render_recent_invocations_summary(clean_obs_db)
    assert "completed" in summary
    assert "denied" in summary
    assert "failed" in summary
    assert "running" in summary

    detail_denied = inspect_telemetry(clean_obs_db, invocation="inv_denied")
    assert "Status:     denied" in detail_denied

    detail_completed = inspect_telemetry(clean_obs_db, invocation="inv_completed")
    assert "Status:     completed" in detail_completed

    detail_failed = inspect_telemetry(clean_obs_db, invocation="inv_failed")
    assert "Status:     failed" in detail_failed

    detail_running = inspect_telemetry(clean_obs_db, invocation="inv_running")
    assert "Status:     running" in detail_running


def test_inspector_histogram_metric_averaging(clean_obs_db: Path) -> None:
    """Verify inspector parses count from attributes_json to compute average duration."""
    inv_id = "inv_metric_test"
    insert_runtime_event(
        clean_obs_db,
        event_id="em1",
        event_kind="invocation_completed",
        occurred_at="2026-09-16T12:00:00.000Z",
        invocation_id=inv_id,
    )
    # Total sum 500.0 ms across 2 recorded calls (count=2)
    insert_otel_metric(
        clean_obs_db,
        instrument_name="proteo.runtime.duration",
        instrument_type="histogram",
        value=500.0,
        attributes={"count": 2},
    )

    output = inspect_telemetry(clean_obs_db, invocation=inv_id, otel_only=True)
    # 500 / 2 = 250 ms
    assert "250 ms" in output
    assert "not invocation-scoped" in output


def test_inspector_reconstructs_task_and_workflow_transitions(clean_obs_db: Path) -> None:
    """Render host workflow transitions and cleanup diagnostics without payload content."""
    insert_runtime_event(
        clean_obs_db,
        event_id="host-transition-1",
        event_kind="host.turn_transition",
        occurred_at="2026-09-19T12:00:00.000Z",
        task_id="task-demo",
        metadata={
            "interaction_id": "interaction-demo",
            "workflow_id": "quote-demo",
            "revision": 3,
            "intent": "quote_create",
            "route": "resolve_quote_data",
            "phase_before": "collecting",
            "phase_after": "needs_resolution",
            "result_code": "resolution_required",
            "prompt": "must never be persisted",
        },
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="task-closed-1",
        event_kind="task_closed",
        occurred_at="2026-09-19T12:00:01.000Z",
        task_id="task-demo",
        metadata={
            "diagnostics": [{"code": "task.cleanup.provider_delete_failed"}],
        },
    )

    task_output = inspect_telemetry(clean_obs_db, task="task-demo")
    workflow_output = inspect_telemetry(clean_obs_db, workflow="quote-demo")

    assert "interaction_id" not in task_output
    assert "resolve_quote_data" in task_output
    assert "phase_before=collecting" in task_output
    assert "diagnostic=task.cleanup.provider_delete_failed" in task_output
    assert "quote-demo" in workflow_output
    assert "must never be persisted" not in task_output


def test_interaction_inspector_correlates_errors_and_preserves_success_status(
    clean_obs_db: Path,
) -> None:
    """Render a correlated host failure as failed and successful runtime turns as completed."""
    insert_runtime_event(
        clean_obs_db,
        event_id="runtime-interaction-error-start",
        event_kind="invocation_started",
        occurred_at="2026-09-19T12:10:00.000Z",
        invocation_id="inv-interaction-error",
        interaction_id="interaction-error",
        task_id="task-interaction-error",
        metadata={"stage": "quote_planner"},
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="host-interaction-error",
        event_kind="host.turn_error",
        occurred_at="2026-09-19T12:10:01.000Z",
        interaction_id="interaction-error",
        task_id="task-interaction-error",
        status="failed",
        metadata={
            "stage": "quote_planner",
            "exception_module": "provider.errors",
            "exception_type": "TransportError",
            "code": "provider.transport_timeout",
            "cause_types": ["builtins.TimeoutError"],
            "frames": [
                {
                    "file": "examples/smart_quote_agent/graph.py",
                    "function": "quote_planner",
                    "line": 40,
                }
            ],
            "exception_message": "must not be rendered",
        },
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="runtime-interaction-success-complete",
        event_kind="invocation_completed",
        occurred_at="2026-09-19T12:11:00.000Z",
        invocation_id="inv-interaction-success",
        interaction_id="interaction-success",
    )

    failed_output = inspect_telemetry(clean_obs_db, interaction="interaction-error")
    success_output = inspect_telemetry(clean_obs_db, interaction="interaction-success")

    assert "Status:     failed" in failed_output
    assert "host.turn_error" in failed_output
    assert "stage=quote_planner" in failed_output
    assert "provider.errors.TransportError" in failed_output
    assert "provider.transport_timeout" in failed_output
    assert "graph.py:quote_planner:40" in failed_output
    assert "must not be rendered" not in failed_output
    assert "Status:     completed" in success_output
