"""Unit tests for standalone telemetry inspector CLI and formatting."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, TypedDict

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
    render_latency_summary,
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


class _InteractionCorrelation(TypedDict):
    """Typed host correlation fields shared by latency telemetry fixtures."""

    interaction_id: str
    task_id: str


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
    insert_runtime_event(
        clean_obs_db,
        event_id="task-runtime-start",
        event_kind="invocation_started",
        occurred_at="2026-09-19T12:00:02.000Z",
        invocation_id="inv-task-runtime",
        interaction_id="interaction-demo",
        task_id="task-demo",
        model="gpt-5.6-luna",
        profile="structured",
        metadata={"stage": "intent_router", "call_id": "call-task-runtime"},
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="task-runtime-complete",
        event_kind="invocation_completed",
        occurred_at="2026-09-19T12:00:02.500Z",
        invocation_id="inv-task-runtime",
    )

    task_output = inspect_telemetry(clean_obs_db, task="task-demo")
    workflow_output = inspect_telemetry(clean_obs_db, workflow="quote-demo")

    assert "interaction_id" not in task_output
    assert "resolve_quote_data" in task_output
    assert "phase_before=collecting" in task_output
    assert "diagnostic=task.cleanup.provider_delete_failed" in task_output
    assert "model invocation span 500 ms" in task_output
    assert "quote-demo" in workflow_output
    assert "model invocation span 500 ms" in workflow_output
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
        event_id="runtime-interaction-turn-failed",
        event_kind="turn_failed",
        occurred_at="2026-09-19T12:10:00.500Z",
        invocation_id="inv-interaction-error",
        interaction_id="interaction-error",
        task_id="task-interaction-error",
        metadata={
            "provider_status": "failed",
            "provider_error_code": "responseStreamDisconnected",
            "provider_http_status": 400,
        },
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="runtime-interaction-invocation-failed",
        event_kind="invocation_failed",
        occurred_at="2026-09-19T12:10:00.750Z",
        invocation_id="inv-interaction-error",
        interaction_id="interaction-error",
        task_id="task-interaction-error",
        metadata={
            "provider_status": "failed",
            "provider_error_code": "responseStreamDisconnected",
            "provider_http_status": 400,
        },
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
            "provider_status": "failed",
            "provider_error_code": "responseStreamDisconnected",
            "provider_http_status": 400,
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
        event_id="runtime-interaction-success-start",
        event_kind="invocation_started",
        occurred_at="2026-09-19T12:10:59.500Z",
        invocation_id="inv-interaction-success",
        interaction_id="interaction-success",
        task_id="task-interaction-success",
        model="gpt-5.6-luna",
        profile="structured",
        metadata={"stage": "intent_router", "call_id": "call-interaction-success"},
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="runtime-interaction-success-complete",
        event_kind="invocation_completed",
        occurred_at="2026-09-19T12:11:00.000Z",
        invocation_id="inv-interaction-success",
    )

    failed_output = inspect_telemetry(clean_obs_db, interaction="interaction-error")
    success_output = inspect_telemetry(clean_obs_db, interaction="interaction-success")

    assert "Status:     failed" in failed_output
    assert "host.turn_error" in failed_output
    assert "stage=quote_planner" in failed_output
    assert "provider.errors.TransportError" in failed_output
    assert "provider.transport_timeout" in failed_output
    assert "provider_status=failed" in failed_output
    assert "provider_error_code=responseStreamDisconnected" in failed_output
    assert "provider_http_status=400" in failed_output
    assert "error=responseStreamDisconnected http_status=400" in failed_output
    assert "graph.py:quote_planner:40" in failed_output
    assert "must not be rendered" not in failed_output
    assert "Status:     completed" in success_output
    assert "structured terminal 500 ms (no text delta)" in success_output


def test_latency_breakdown_correlates_model_setup_tokens_tools_and_interaction(
    clean_obs_db: Path,
) -> None:
    """Render host setup, model, streaming, tool, and final cumulative usage timings.

    Args:
        clean_obs_db: Initialized telemetry database fixture.
    """
    interaction_id = "interaction-latency"
    task_id = "task-latency"
    invocation_id = "inv-latency"
    common: _InteractionCorrelation = {
        "interaction_id": interaction_id,
        "task_id": task_id,
    }

    insert_runtime_event(
        clean_obs_db,
        event_id="host-interaction-start",
        event_kind="host.interaction_started",
        occurred_at="2026-09-19T12:00:00.000Z",
        metadata=common,
        **common,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="host-model-start",
        event_kind="host.model_call_started",
        occurred_at="2026-09-19T12:00:00.100Z",
        metadata={**common, "call_id": "call-latency", "stage": "controlled_agent"},
        **common,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="runtime-model-start",
        event_kind="invocation_started",
        occurred_at="2026-09-19T12:00:00.200Z",
        invocation_id=invocation_id,
        runtime_name="codex",
        model="gpt-5.6-luna",
        profile="structured",
        metadata={
            **common,
            "call_id": "call-latency",
            "stage": "controlled_agent",
        },
        **common,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="runtime-turn-start",
        event_kind="turn_started",
        occurred_at="2026-09-19T12:00:00.250Z",
        invocation_id=invocation_id,
        metadata={"call_id": "call-latency"},
        **common,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="runtime-tool-request",
        event_kind="tool_requested",
        occurred_at="2026-09-19T12:00:00.500Z",
        invocation_id=invocation_id,
        tool_name="list_customers",
        tool_call_id="tool-latency",
        metadata={"call_id": "call-latency"},
        **common,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="runtime-tool-start",
        event_kind="tool_started",
        occurred_at="2026-09-19T12:00:00.550Z",
        invocation_id=invocation_id,
        tool_name="list_customers",
        tool_call_id="tool-latency",
        metadata={"call_id": "call-latency"},
        **common,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="runtime-tool-complete",
        event_kind="tool_completed",
        occurred_at="2026-09-19T12:00:00.580Z",
        invocation_id=invocation_id,
        tool_name="list_customers",
        tool_call_id="tool-latency",
        duration_ms=30,
        metadata={"call_id": "call-latency"},
        **common,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="runtime-output-delta",
        event_kind="output_text_delta",
        occurred_at="2026-09-19T12:00:00.900Z",
        invocation_id=invocation_id,
        metadata={"call_id": "call-latency"},
        **common,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="runtime-usage-old",
        event_kind="token_usage_updated",
        occurred_at="2026-09-19T12:00:01.000Z",
        invocation_id=invocation_id,
        metadata={"input_tokens": 20, "cached_input_tokens": 10, "output_tokens": 2},
        **common,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="runtime-usage-final",
        event_kind="token_usage_updated",
        occurred_at="2026-09-19T12:00:01.050Z",
        invocation_id=invocation_id,
        metadata={"input_tokens": 120, "cached_input_tokens": 90, "output_tokens": 15},
        **common,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="runtime-model-complete",
        event_kind="invocation_completed",
        occurred_at="2026-09-19T12:00:01.200Z",
        invocation_id=invocation_id,
        **common,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="host-model-complete",
        event_kind="host.model_call_completed",
        occurred_at="2026-09-19T12:00:01.210Z",
        duration_ms=1110,
        metadata={**common, "call_id": "call-latency", "stage": "controlled_agent"},
        **common,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="host-interaction-complete",
        event_kind="host.interaction_completed",
        occurred_at="2026-09-19T12:00:01.300Z",
        metadata=common,
        **common,
    )

    interaction_output = inspect_telemetry(clean_obs_db, interaction=interaction_id)
    invocation_output = inspect_telemetry(clean_obs_db, invocation=invocation_id)
    task_output = inspect_telemetry(clean_obs_db, task=task_id)

    for rendered in (interaction_output, invocation_output, task_output):
        assert "Latency Breakdown" in rendered
        assert "controlled_agent / gpt-5.6-luna / structured" in rendered
        assert "runtime task span (may include tool/HITL cycles) 1.00 s" in rendered
        assert "TTFT 700 ms" in rendered
        assert "input 120, cached 90/120 (75%), output 15" in rendered
        assert "Provider preparation (controlled_agent): 100 ms" in rendered
        assert "host task-call wall time (may include tool/HITL cycles)" in rendered
        assert "Tool execution: 30 ms" in rendered
        assert "Before tool(s): 250 ms" in rendered
        assert "After tool(s) to next model event: 320 ms" in rendered
        assert "input 20" not in rendered
    assert "Interaction total: 1.30 s" in interaction_output
    assert "Invocation span: 1.00 s" in invocation_output


def test_last_invocation_separates_approval_wait_from_tool_execution(
    clean_obs_db: Path,
) -> None:
    """Warn that approval wait is human time and never report it as LLM duration.

    Args:
        clean_obs_db: Initialized telemetry database fixture.
    """
    invocation_id = "inv-approval-only"
    tool_id = "approval-tool-1"
    insert_runtime_event(
        clean_obs_db,
        event_id="approval-requested",
        event_kind="tool_approval_requested",
        occurred_at="2026-09-19T12:00:00.000Z",
        invocation_id=invocation_id,
        tool_name="create_quote",
        tool_call_id=tool_id,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="approval-resolved",
        event_kind="tool_approval_resolved",
        occurred_at="2026-09-19T12:00:09.700Z",
        invocation_id=invocation_id,
        tool_name="create_quote",
        tool_call_id=tool_id,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="approval-tool-started",
        event_kind="tool_started",
        occurred_at="2026-09-19T12:00:09.700Z",
        invocation_id=invocation_id,
        tool_name="create_quote",
        tool_call_id=tool_id,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="approval-tool-completed",
        event_kind="tool_completed",
        occurred_at="2026-09-19T12:00:09.730Z",
        invocation_id=invocation_id,
        tool_name="create_quote",
        tool_call_id=tool_id,
        duration_ms=30,
    )

    output = inspect_telemetry(clean_obs_db, last=True)
    assert "Invocation span: not a model call" in output
    assert "Invocation approval wait: 9.70 s" in output
    assert "Tool execution: 30 ms" in output
    assert "invocation elapsed time can include approval wait" in output
    assert "Invocation span: 9.70 s" not in output


def test_invocation_latency_scopes_sibling_calls_and_labels_interaction_wait(
    clean_obs_db: Path,
) -> None:
    """Keep sibling model calls out of a single invocation's latency report.

    Args:
        clean_obs_db: Initialized telemetry database fixture.
    """
    interaction_id = "interaction-sibling-calls"
    task_id = "task-sibling-calls"
    common: _InteractionCorrelation = {
        "interaction_id": interaction_id,
        "task_id": task_id,
    }
    insert_runtime_event(
        clean_obs_db,
        event_id="sibling-interaction-start",
        event_kind="host.interaction_started",
        occurred_at="2026-09-19T12:00:00.000Z",
        metadata=common,
        **common,
    )
    call_specs = (
        (
            "target",
            "target-call",
            "intent_router",
            "2026-09-19T12:00:00.100Z",
            "2026-09-19T12:00:00.200Z",
            "2026-09-19T12:00:01.200Z",
            "2026-09-19T12:00:01.300Z",
            120,
            90,
        ),
        (
            "sibling",
            "sibling-call",
            "controlled_agent",
            "2026-09-19T12:00:02.000Z",
            "2026-09-19T12:00:02.100Z",
            "2026-09-19T12:00:05.100Z",
            "2026-09-19T12:00:05.200Z",
            900,
            0,
        ),
    )
    for (
        label,
        call_id,
        stage,
        host_start,
        model_start,
        model_end,
        host_end,
        inputs,
        cached,
    ) in call_specs:
        invocation_id = f"inv-{label}-call"
        metadata = {**common, "call_id": call_id, "stage": stage}
        insert_runtime_event(
            clean_obs_db,
            event_id=f"{label}-host-call-start",
            event_kind="host.model_call_started",
            occurred_at=host_start,
            metadata=metadata,
            **common,
        )
        insert_runtime_event(
            clean_obs_db,
            event_id=f"{label}-runtime-call-start",
            event_kind="invocation_started",
            occurred_at=model_start,
            invocation_id=invocation_id,
            model="gpt-5.6-luna",
            profile="structured",
            metadata=metadata,
            **common,
        )
        insert_runtime_event(
            clean_obs_db,
            event_id=f"{label}-runtime-call-usage",
            event_kind="token_usage_updated",
            occurred_at=model_end,
            invocation_id=invocation_id,
            metadata={**metadata, "input_tokens": inputs, "cached_input_tokens": cached},
            **common,
        )
        insert_runtime_event(
            clean_obs_db,
            event_id=f"{label}-runtime-call-complete",
            event_kind="invocation_completed",
            occurred_at=model_end,
            invocation_id=invocation_id,
            metadata=metadata,
            **common,
        )
        insert_runtime_event(
            clean_obs_db,
            event_id=f"{label}-host-call-complete",
            event_kind="host.model_call_completed",
            occurred_at=host_end,
            duration_ms=1_200 if label == "target" else 3_200,
            metadata=metadata,
            **common,
        )
    insert_runtime_event(
        clean_obs_db,
        event_id="interaction-discount-start",
        event_kind="host.hitl_started",
        occurred_at="2026-09-19T12:00:05.500Z",
        metadata={**common, "hitl_id": "discount-prompt", "workflow_id": "quote-1"},
        **common,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="interaction-discount-resolved",
        event_kind="host.hitl_resolved",
        occurred_at="2026-09-19T12:00:07.500Z",
        duration_ms=2_000,
        metadata={**common, "hitl_id": "discount-prompt", "workflow_id": "quote-1"},
        **common,
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="sibling-interaction-complete",
        event_kind="host.interaction_completed",
        occurred_at="2026-09-19T12:00:08.000Z",
        metadata=common,
        **common,
    )

    output = inspect_telemetry(clean_obs_db, invocation="inv-target-call")

    assert "Interaction total: 8.00 s" in output
    assert "intent_router / gpt-5.6-luna / structured" in output
    assert "structured terminal 1.00 s (no text delta)" in output
    assert "input 120, cached 90/120 (75%)" in output
    assert "Provider preparation (intent_router): 100 ms" in output
    assert "Interaction discount wait: 2.00 s" in output
    assert "controlled_agent / gpt-5.6-luna / structured" not in output
    assert "input 900" not in output
    assert "Provider preparation (controlled_agent)" not in output
    assert "Human approval/discount wait:" not in output


def test_structured_output_without_text_deltas_reports_terminal_latency(clean_obs_db: Path) -> None:
    """Use invocation completion time when structured output emits no text deltas."""
    invocation_id = "inv-structured-no-delta"
    insert_runtime_event(
        clean_obs_db,
        event_id="structured-no-delta-start",
        event_kind="invocation_started",
        occurred_at="2026-09-19T12:00:00.000Z",
        invocation_id=invocation_id,
        model="gpt-5.6-luna",
        profile="structured",
        metadata={"call_id": "call-structured-no-delta", "stage": "intent_router"},
    )
    insert_runtime_event(
        clean_obs_db,
        event_id="structured-no-delta-complete",
        event_kind="invocation_completed",
        occurred_at="2026-09-19T12:00:00.500Z",
        invocation_id=invocation_id,
    )

    output = inspect_telemetry(clean_obs_db, invocation=invocation_id)

    assert "structured terminal 500 ms (no text delta)" in output
    assert "TTFT" not in output


def test_latency_cli_reports_nearest_rank_and_excludes_incomplete_from_percentiles(
    clean_obs_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Use nearest-rank percentiles, final usage snapshots, and mark incomplete calls.

    Args:
        clean_obs_db: Initialized telemetry database fixture.
        capsys: Pytest output capture fixture for the CLI invocation.
    """
    samples = (("fast", "00.000Z", "00.100Z"), ("slow", "01.000Z", "01.300Z"))
    for name, start_time, end_time in samples:
        invocation_id = f"inv-{name}"
        start = f"2026-09-19T12:00:{start_time}"
        end = f"2026-09-19T12:00:{end_time}"
        insert_runtime_event(
            clean_obs_db,
            event_id=f"{name}-start",
            event_kind="invocation_started",
            occurred_at=start,
            invocation_id=invocation_id,
            model="gpt-5.6-luna",
            profile="structured",
            metadata={"stage": "intent_router"},
        )
        insert_runtime_event(
            clean_obs_db,
            event_id=f"{name}-usage-old",
            event_kind="token_usage_updated",
            occurred_at=f"2026-09-19T12:00:{'00.050Z' if name == 'fast' else '01.100Z'}",
            invocation_id=invocation_id,
            metadata={"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 1},
        )
        input_tokens = 100
        cached_tokens = 80 if name == "fast" else 50
        insert_runtime_event(
            clean_obs_db,
            event_id=f"{name}-usage-final",
            event_kind="token_usage_updated",
            occurred_at=f"2026-09-19T12:00:{'00.075Z' if name == 'fast' else '01.200Z'}",
            invocation_id=invocation_id,
            metadata={
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_tokens,
                "output_tokens": 8,
            },
        )
        insert_runtime_event(
            clean_obs_db,
            event_id=f"{name}-complete",
            event_kind="invocation_completed",
            occurred_at=end,
            invocation_id=invocation_id,
        )

    insert_runtime_event(
        clean_obs_db,
        event_id="incomplete-start",
        event_kind="invocation_started",
        occurred_at="2026-09-19T12:00:03.000Z",
        invocation_id="inv-incomplete",
        model="gpt-5.6-luna",
        profile="structured",
        metadata={"stage": "intent_router"},
    )

    output = render_latency_summary(clean_obs_db, limit=3)
    assert "Model calls: 3 across 3 selected runtime invocations" in output
    assert "intent_router" in output
    assert "100 ms" in output
    assert "300 ms" in output
    assert "Inc." in output
    assert " 3     1" in output
    assert "65%" in output
    assert main(["--db", str(clean_obs_db), "--latency", "--limit", "3"]) == 0
    assert "Cache ratio" in capsys.readouterr().out
