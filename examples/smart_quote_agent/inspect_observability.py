"""Standalone CLI inspector for Proteo telemetry database (observability.sqlite3).

This module operates strictly read-only against the telemetry database and
never imports or starts the Codex runtime.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from math import ceil
from pathlib import Path
from typing import Any

# Ensure demo directory is in sys.path when executed directly
_DEMO_DIR = str(Path(__file__).resolve().parent)
if _DEMO_DIR not in sys.path:
    sys.path.insert(0, _DEMO_DIR)

from telemetry_db import (  # noqa: E402
    derive_invocation_status,
    fetch_interaction_events,
    fetch_invocation_events,
    fetch_langsmith_runs_for_invocation,
    fetch_last_invocation_id,
    fetch_otel_span_events,
    fetch_otel_spans_for_invocation,
    fetch_recent_invocation_event_groups,
    fetch_recent_invocations,
    fetch_task_events,
    fetch_workflow_events,
    get_telemetry_connection,
    get_telemetry_db_path,
)

HOST_ONLY_NOTE = (
    "Note: Host-only interactions (such as help, login, logout, scope rejection, "
    "or discount prompts) do not trigger runtime invocations."
)


def _format_time_hhmmss(iso_str: str | None) -> str:
    """Format an ISO-8601 timestamp string into HH:MM:SS format.

    Args:
        iso_str: ISO formatted timestamp.

    Returns:
        Formatted time string, or '-' if empty.
    """
    if not iso_str:
        return "-"
    try:
        # Expected format e.g. 2026-09-16T12:41:02...
        if "T" in iso_str:
            time_part = iso_str.split("T")[1]
            return time_part.split(".")[0].split("+")[0].split("Z")[0][:8]
        return iso_str[:8]
    except Exception:
        return str(iso_str)[:8]


def _format_duration(duration_ms: float | int | None) -> str:
    """Format a duration in milliseconds to human-readable seconds or milliseconds.

    Args:
        duration_ms: Duration in milliseconds.

    Returns:
        Formatted duration string.
    """
    if duration_ms is None:
        return "-"
    if duration_ms >= 1000:
        return f"{duration_ms / 1000:.2f} s"
    return f"{duration_ms:.0f} ms"


def _shorten_id(val: str | None, max_len: int = 16) -> str:
    """Shorten an identifier with ellipsis if longer than max_len.

    Args:
        val: Input string.
        max_len: Maximum length before truncation.

    Returns:
        Shortened string.
    """
    if not val:
        return "-"
    if len(val) <= max_len:
        return val
    return f"{val[: max_len - 3]}..."


def _event_metadata(event: Mapping[str, Any]) -> dict[str, Any]:
    """Decode event metadata defensively for timeline filtering and rendering.

    Args:
        event: Runtime event row returned by the telemetry query layer.

    Returns:
        Metadata object, or an empty mapping for malformed/non-object JSON.
    """
    try:
        value = json.loads(str(event.get("metadata_json") or "{}"))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _event_timestamp_ms(event: Mapping[str, Any]) -> float | None:
    """Parse an event's ISO timestamp as epoch milliseconds.

    Args:
        event: Runtime or host telemetry event row.

    Returns:
        Epoch timestamp in milliseconds, or None if missing or invalid.
    """
    value = event.get("occurred_at")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return None


def _elapsed_ms(start: Mapping[str, Any], end: Mapping[str, Any]) -> float | None:
    """Return elapsed milliseconds between two telemetry event rows.

    Args:
        start: Earlier lifecycle event row.
        end: Later lifecycle event row.

    Returns:
        Non-negative elapsed milliseconds, or None if timestamps are unusable.
    """
    start_ms = _event_timestamp_ms(start)
    end_ms = _event_timestamp_ms(end)
    if start_ms is None or end_ms is None or end_ms < start_ms:
        return None
    return end_ms - start_ms


def _metadata_value(event: Mapping[str, Any], key: str) -> Any:
    """Read a value from a runtime event column or its metadata object.

    Args:
        event: Runtime or host telemetry event row.
        key: Field name to read.

    Returns:
        Top-level field or metadata value, if present.
    """
    value = event.get(key)
    return value if value is not None else _event_metadata(event).get(key)


def _recorded_duration(event: Mapping[str, Any]) -> float | None:
    """Read a finite non-negative duration from a completion event.

    Args:
        event: Event row that may contain duration_ms.

    Returns:
        Duration in milliseconds, or None if absent or invalid.
    """
    value = event.get("duration_ms")
    if value is None:
        value = _event_metadata(event).get("duration_ms")
    if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0:
        return float(value)
    return None


def _event_order(event: Mapping[str, Any]) -> tuple[float, int]:
    """Return a stable chronological sort key for an event row.

    Args:
        event: Runtime or host telemetry event row.

    Returns:
        Timestamp and SQLite row ID used for chronological ordering.
    """
    timestamp = _event_timestamp_ms(event)
    row_id = event.get("id")
    return timestamp if timestamp is not None else 0.0, row_id if isinstance(row_id, int) else 0


def _pair_durations(
    events: Sequence[Mapping[str, Any]],
    start_kinds: set[str],
    end_kinds: set[str],
    *,
    correlation_keys: tuple[str, ...],
) -> tuple[list[float], list[Mapping[str, Any]]]:
    """Pair lifecycle events and return completed durations and pending starts.

    Args:
        events: Runtime and host lifecycle event rows.
        start_kinds: Event kinds that begin measured intervals.
        end_kinds: Event kinds that finish measured intervals.
        correlation_keys: Metadata or column fields used to pair each interval.

    Returns:
        Completed interval durations and lifecycle starts with no matching end.
    """
    pending: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    durations: list[float] = []
    ordered = sorted(events, key=_event_order)
    for event in ordered:
        kind = str(event.get("event_kind", ""))
        correlation = next(
            (
                str(value)
                for key in correlation_keys
                if (value := _metadata_value(event, key)) is not None
            ),
            "unkeyed",
        )
        if kind in start_kinds:
            pending[correlation].append(event)
        elif kind in end_kinds and pending[correlation]:
            start = pending[correlation].pop(0)
            duration = _elapsed_ms(start, event)
            if duration is not None:
                durations.append(duration)

    pending_starts = [event for starts in pending.values() for event in starts]
    return durations, pending_starts


def _final_token_snapshot(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return the last cumulative token usage snapshot for an invocation.

    Args:
        events: Chronological event rows for one invocation.

    Returns:
        Final usage metadata, or an empty mapping if no usage was recorded.
    """
    usage_events = sorted(
        (event for event in events if event.get("event_kind") == "token_usage_updated"),
        key=_event_order,
    )
    if not usage_events:
        return {}
    metadata = _event_metadata(usage_events[-1])
    usage = metadata.get("usage")
    if isinstance(usage, dict):
        return {**metadata, **usage}
    return metadata


def _token_number(snapshot: Mapping[str, Any], key: str) -> int | None:
    """Read a non-negative integer token count from a usage snapshot.

    Args:
        snapshot: Final token usage metadata.
        key: Usage field name.

    Returns:
        Token count, or None if missing or invalid.
    """
    value = snapshot.get(key)
    if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0:
        return int(value)
    return None


def _derive_invocation_latency(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Derive model and tool timings from one invocation's neutral events.

    Args:
        events: Runtime event rows associated with one invocation.

    Returns:
        Metadata-only timing and token summary for the invocation.
    """
    ordered = sorted(events, key=_event_order)
    starts = [event for event in ordered if event.get("event_kind") == "invocation_started"]
    terminals = [
        event
        for event in ordered
        if event.get("event_kind")
        in {"invocation_completed", "invocation_failed", "cancelled", "turn_failed"}
    ]
    start = starts[0] if starts else None
    terminal = terminals[-1] if terminals else None
    model_duration = _elapsed_ms(start, terminal) if start is not None and terminal else None
    if model_duration is None and start is not None and terminal is not None:
        # Older event streams may provide no parseable timestamps but retain a duration.
        duration_value = terminal.get("duration_ms")
        model_duration = float(duration_value) if isinstance(duration_value, int | float) else None

    first_delta = next(
        (event for event in ordered if event.get("event_kind") == "output_text_delta"),
        None,
    )
    ttft = _elapsed_ms(start, first_delta) if start is not None and first_delta else None
    token_snapshot = _final_token_snapshot(ordered)
    input_tokens = _token_number(token_snapshot, "input_tokens")
    cached_tokens = _token_number(token_snapshot, "cached_input_tokens")
    output_tokens = _token_number(token_snapshot, "output_tokens")
    if input_tokens is None:
        input_tokens = _token_number(token_snapshot, "prompt_tokens")
    if cached_tokens is None:
        cached_tokens = _token_number(token_snapshot, "cache_read_input_tokens")

    requested_tools = [event for event in ordered if event.get("event_kind") == "tool_requested"]
    started_tools = [event for event in ordered if event.get("event_kind") == "tool_started"]
    completed_tools = [event for event in ordered if event.get("event_kind") == "tool_completed"]
    tool_durations, _ = _pair_durations(
        ordered,
        {"tool_started"},
        {"tool_completed", "tool_failed"},
        correlation_keys=("tool_call_id",),
    )
    if not tool_durations:
        tool_durations = [
            float(event["duration_ms"])
            for event in completed_tools
            if isinstance(event.get("duration_ms"), int | float)
        ]
    turn_start = next(
        (event for event in ordered if event.get("event_kind") == "turn_started"), start
    )
    pre_tool_ms: list[float] = []
    post_tool_ms: list[float] = []
    previous_tool_completion = turn_start
    used_completion_ids: set[int] = set()
    for requested_tool in requested_tools:
        if previous_tool_completion is not None:
            before_tool = _elapsed_ms(previous_tool_completion, requested_tool)
            if before_tool is not None:
                pre_tool_ms.append(before_tool)
        tool_call_id = _metadata_value(requested_tool, "tool_call_id")
        completion = next(
            (
                event
                for event in ordered
                if event.get("event_kind") in {"tool_completed", "tool_failed"}
                and _event_order(event) > _event_order(requested_tool)
                and event.get("id") not in used_completion_ids
                and (tool_call_id is None or _metadata_value(event, "tool_call_id") == tool_call_id)
            ),
            None,
        )
        if completion is None:
            continue
        completion_id = completion.get("id")
        if isinstance(completion_id, int):
            used_completion_ids.add(completion_id)
        previous_tool_completion = completion
        next_model_event = next(
            (
                event
                for event in ordered
                if _event_order(event) > _event_order(completion)
                and event.get("event_kind")
                in {
                    "tool_requested",
                    "output_text_delta",
                    "turn_completed",
                    "turn_failed",
                    "invocation_completed",
                    "invocation_failed",
                    "cancelled",
                }
            ),
            None,
        )
        if next_model_event is not None:
            after_tool = _elapsed_ms(completion, next_model_event)
            if after_tool is not None:
                post_tool_ms.append(after_tool)

    stage = next(
        (value for event in ordered if isinstance((value := _metadata_value(event, "stage")), str)),
        "unknown",
    )
    model = next((event.get("model") for event in ordered if event.get("model")), None)
    profile = next((event.get("profile") for event in ordered if event.get("profile")), None)
    call_id = next(
        (
            str(value)
            for event in ordered
            if (value := _metadata_value(event, "call_id")) is not None
        ),
        None,
    )
    is_model_call = bool(start is not None and (call_id or model or profile or token_snapshot))
    return {
        "invocation_id": next(
            (event.get("invocation_id") for event in ordered if event.get("invocation_id")),
            "-",
        ),
        "stage": stage,
        "model": model or "-",
        "profile": profile or "-",
        "call_id": call_id,
        "started": start is not None,
        "is_model_call": is_model_call,
        "duration_ms": model_duration,
        "ttft_ms": ttft,
        "structured_terminal_ms": model_duration if first_delta is None else None,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "cache_ratio": (
            cached_tokens / input_tokens
            if cached_tokens is not None and input_tokens is not None and input_tokens > 0
            else None
        ),
        "tool_count": len(started_tools) or len(requested_tools),
        "tool_duration_ms": tool_durations,
        "pre_tool_ms": pre_tool_ms,
        "post_tool_ms": post_tool_ms,
        "first_event": start,
        "terminal_event": terminal,
    }


def _render_latency_breakdown(
    events: Sequence[Mapping[str, Any]], *, invocation_scoped: bool = False
) -> list[str]:
    """Render safe latency measurements from invocation and host lifecycle events.

    Args:
        events: Correlated runtime and host event rows.
        invocation_scoped: Whether to label tool approval and interaction HITL
            measurements at their distinct scopes.

    Returns:
        Report lines containing timings and non-sensitive token counts.
    """
    lines = ["Latency Breakdown", "─" * 40]
    ordered = sorted(events, key=_event_order)
    interactions, pending_interactions = _pair_durations(
        ordered,
        {"host.interaction_started"},
        {"host.interaction_completed"},
        correlation_keys=("interaction_id",),
    )
    if interactions:
        lines.append(
            "Interaction total: " + ", ".join(_format_duration(value) for value in interactions)
        )
    else:
        interaction_fallbacks = [
            duration
            for event in ordered
            if event.get("event_kind") == "host.interaction_completed"
            and (duration := _recorded_duration(event)) is not None
        ]
        if interaction_fallbacks:
            lines.append(
                "Interaction total: "
                + ", ".join(_format_duration(value) for value in interaction_fallbacks)
            )
        elif pending_interactions:
            lines.append("Interaction total: running")

    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in ordered:
        invocation_id = event.get("invocation_id")
        if isinstance(invocation_id, str) and not str(event.get("event_kind", "")).startswith(
            "host."
        ):
            groups[invocation_id].append(event)
    summaries = [_derive_invocation_latency(group) for group in groups.values()]
    for summary in summaries:
        if not summary["is_model_call"]:
            continue
        duration = summary["duration_ms"]
        if summary["stage"] == "controlled_agent":
            span_label = "runtime task span (may include tool/HITL cycles)"
        else:
            span_label = "model invocation span"
        label = (
            f"{summary['stage']} / {summary['model']} / {summary['profile']}: "
            f"{span_label} {_format_duration(duration)}"
        )
        if summary["ttft_ms"] is not None:
            label += f", TTFT {_format_duration(summary['ttft_ms'])}"
        elif summary["structured_terminal_ms"] is not None:
            label += f", structured terminal {_format_duration(summary['structured_terminal_ms'])} (no text delta)"
        input_tokens = summary["input_tokens"]
        cached_tokens = summary["cached_input_tokens"]
        output_tokens = summary["output_tokens"]
        if input_tokens is not None:
            cache_text = (
                f", cached {cached_tokens}/{input_tokens} ({summary['cache_ratio']:.0%})"
                if cached_tokens is not None and summary["cache_ratio"] is not None
                else f", cached n/a/{input_tokens}"
            )
            output_text = f", output {output_tokens}" if output_tokens is not None else ""
            label += f", input {input_tokens}{cache_text}{output_text}"
        lines.append(label)
        if summary["pre_tool_ms"]:
            lines.append(
                "  Before tool(s): "
                + ", ".join(_format_duration(value) for value in summary["pre_tool_ms"])
            )
        if summary["tool_duration_ms"]:
            lines.append(
                "  Tool execution: "
                + ", ".join(_format_duration(value) for value in summary["tool_duration_ms"])
            )
        if summary["post_tool_ms"]:
            lines.append(
                "  After tool(s) to next model event: "
                + ", ".join(_format_duration(value) for value in summary["post_tool_ms"])
            )

    model_starts: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    runtime_starts: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in ordered:
        kind = str(event.get("event_kind", ""))
        call_id = _metadata_value(event, "call_id")
        if not isinstance(call_id, str):
            continue
        if kind == "host.model_call_started":
            model_starts[call_id].append(event)
        elif kind == "invocation_started":
            runtime_starts[call_id].append(event)
    for call_id, host_starts in model_starts.items():
        runtime_events = runtime_starts.get(call_id, [])
        if host_starts and runtime_events:
            setup_ms = _elapsed_ms(host_starts[0], runtime_events[0])
            if setup_ms is not None:
                stage = _metadata_value(host_starts[0], "stage") or "unknown"
                lines.append(f"Provider preparation ({stage}): {_format_duration(setup_ms)}")
        host_completions = [
            event
            for event in ordered
            if event.get("event_kind") == "host.model_call_completed"
            and _metadata_value(event, "call_id") == call_id
        ]
        if host_completions:
            host_duration = _recorded_duration(host_completions[-1])
            if host_duration is not None:
                stage = _metadata_value(host_completions[-1], "stage") or "unknown"
                host_span_label = (
                    "host task-call wall time (may include tool/HITL cycles)"
                    if stage == "controlled_agent"
                    else "host model-call wall time"
                )
                lines.append(f"{host_span_label} ({stage}): {_format_duration(host_duration)}")

    tool_durations, pending_tools = _pair_durations(
        ordered,
        {"tool_started"},
        {"tool_completed", "tool_failed"},
        correlation_keys=("tool_call_id",),
    )
    if tool_durations and not any(summary["is_model_call"] for summary in summaries):
        lines.append(
            "Tool execution: " + ", ".join(_format_duration(value) for value in tool_durations)
        )
    if pending_tools:
        lines.append(f"Tool execution: {len(pending_tools)} still running")

    approval_durations, pending_approvals = _pair_durations(
        ordered,
        {"tool_approval_requested"},
        {"tool_approval_resolved", "tool_denied"},
        correlation_keys=("tool_call_id", "interaction_id"),
    )
    hitl_durations, pending_hitl = _pair_durations(
        ordered,
        {"host.hitl_started"},
        {"host.hitl_resolved"},
        correlation_keys=("hitl_id", "interaction_id", "workflow_id"),
    )
    if not approval_durations:
        approval_durations = [
            duration
            for event in ordered
            if event.get("event_kind") in {"tool_approval_resolved", "tool_denied"}
            and (duration := _recorded_duration(event)) is not None
        ]
    if not hitl_durations:
        hitl_durations = [
            duration
            for event in ordered
            if event.get("event_kind") == "host.hitl_resolved"
            and (duration := _recorded_duration(event)) is not None
        ]
    if invocation_scoped:
        if approval_durations:
            lines.append(
                "Invocation approval wait: "
                + ", ".join(_format_duration(value) for value in approval_durations)
            )
        if hitl_durations:
            lines.append(
                "Interaction discount wait: "
                + ", ".join(_format_duration(value) for value in hitl_durations)
            )
        if pending_approvals:
            lines.append("Invocation approval wait: pending")
        if pending_hitl:
            lines.append("Interaction discount wait: pending")
        if approval_durations or hitl_durations or pending_approvals or pending_hitl:
            lines.append(
                "Note: invocation elapsed time can include approval wait; discount wait is interaction-scoped."
            )
    else:
        waits = approval_durations + hitl_durations
        if waits:
            lines.append(
                "Human approval/discount wait: "
                + ", ".join(_format_duration(value) for value in waits)
            )
            lines.append(
                "Note: invocation elapsed time can include human wait; it is not all LLM time."
            )
        if pending_approvals or pending_hitl:
            lines.append("Human approval/discount wait: pending")
            lines.append(
                "Note: invocation elapsed time can include human wait; it is not all LLM time."
            )

    if len(lines) == 2:
        lines.append("No correlated model, tool, or human-wait timing events found.")
    return lines


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    """Calculate a linearly interpolated percentile for numeric samples.

    Args:
        values: Numeric sample values.
        percentile: Fractional percentile between zero and one.

    Returns:
        Interpolated percentile value, or None for an empty sample set.
    """
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, ceil(percentile * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def render_latency_summary(db_path: Path | str | None = None, limit: int = 10) -> str:
    """Summarize latency and prompt-cache rates for recent model invocations.

    Args:
        db_path: Optional telemetry SQLite path.
        limit: Number of most recently active runtime invocations to inspect.

    Returns:
        Formatted latency percentile and cache-rate summary.
    """
    groups = fetch_recent_invocation_event_groups(db_path, limit=limit)
    summaries = [_derive_invocation_latency(events) for events in groups]
    model_calls = [summary for summary in summaries if summary["is_model_call"]]
    lines = [
        f"Recent model invocation latency (last {limit} runtime invocations)",
        "─" * 72,
        "",
    ]
    if not model_calls:
        lines.append("No model invocations found in the selected recent invocation window.")
        return "\n".join(lines)

    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for call in model_calls:
        buckets[(str(call["stage"]), str(call["model"]), str(call["profile"]))].append(call)
    lines.append(
        f"Model calls: {len(model_calls)} across {len(groups)} selected runtime invocations"
    )
    lines.append("")
    lines.append(
        f"{'Stage':<24} {'Model':<22} {'Profile':<20} {'Count':>5} {'Inc.':>5} {'p50':>10} {'p95':>10} {'Cache':>9}"
    )
    for (stage, model, profile), calls in sorted(buckets.items()):
        durations = [
            float(call["duration_ms"]) for call in calls if call["duration_ms"] is not None
        ]
        incomplete_count = len(calls) - len(durations)
        cache_samples = [
            call
            for call in calls
            if call["input_tokens"] is not None and call["cached_input_tokens"] is not None
        ]
        input_total = sum(int(call["input_tokens"]) for call in cache_samples)
        cached_total = sum(int(call["cached_input_tokens"]) for call in cache_samples)
        cache_ratio = f"{cached_total / input_total:.0%}" if input_total else "n/a"
        p50 = _percentile(durations, 0.50)
        p95 = _percentile(durations, 0.95)
        lines.append(
            f"{stage:<24.24} {model:<22.22} {profile:<20.20} {len(calls):>5} {incomplete_count:>5} "
            f"{_format_duration(p50):>10} {_format_duration(p95):>10} {cache_ratio:>9}"
        )
    lines.append("")
    lines.append("Cache ratio = summed final cached-input tokens / summed final input tokens.")
    lines.append(
        "Latency uses invocation_started → terminal; human waits are reported separately in detail views."
    )
    lines.append("Controlled-agent spans may include internal tool and human-wait cycles.")
    return "\n".join(lines)


def render_recent_invocations_summary(
    db_path: Path | str | None = None,
    limit: int = 10,
) -> str:
    """Render the default tabular summary of recent Proteo runtime invocations.

    Args:
        db_path: Path to the telemetry database.
        limit: Maximum number of invocations to list.

    Returns:
        Formatted summary table text.
    """
    invocations = fetch_recent_invocations(db_path, limit=limit)

    lines: list[str] = [
        "Recent Proteo invocations",
        "─" * 60,
        "",
    ]

    if not invocations:
        lines.append("No Proteo runtime invocations found in observability database.")
        lines.append("")
        lines.append(HOST_ONLY_NOTE)
        return "\n".join(lines)

    lines.append(
        f"{'#':<3} {'Invocation':<17} {'Started':<11} {'Duration':<10} {'Tools':<7} {'Status':<10}"
    )
    for idx, inv in enumerate(invocations, start=1):
        inv_id = _shorten_id(inv.get("invocation_id"))
        started = _format_time_hhmmss(inv.get("started_at"))
        dur = _format_duration(inv.get("duration_ms"))
        tools = str(inv.get("tool_count", 0))
        status = str(inv.get("status", "completed"))
        lines.append(f"{idx:<3} {inv_id:<17} {started:<11} {dur:<10} {tools:<7} {status:<10}")

    lines.append("")
    lines.append(HOST_ONLY_NOTE)
    return "\n".join(lines)


def build_langsmith_tree(runs: Sequence[dict[str, Any]]) -> list[str]:
    """Reconstruct a recursive tree representation from LangSmith run records.

    Args:
        runs: Sequence of run dictionaries containing run_id and parent_run_id.

    Returns:
        List of formatted lines representing the execution hierarchy.
    """
    if not runs:
        return ["(No LangSmith runs recorded for this invocation)"]

    children_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    run_by_id: dict[str, dict[str, Any]] = {str(r["run_id"]): dict(r) for r in runs}

    root_runs: list[dict[str, Any]] = []

    for r in runs:
        parent_id = r.get("parent_run_id")
        if parent_id and str(parent_id) in run_by_id:
            children_map[str(parent_id)].append(dict(r))
        else:
            root_runs.append(dict(r))

    def _format_node(run: dict[str, Any]) -> str:
        name = run.get("name") or "run"
        meta_raw = run.get("metadata_json") or "{}"
        try:
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else dict(meta_raw)
        except Exception:
            meta = {}
        tool_name = meta.get("tool_name") or meta.get("name")
        if tool_name and tool_name not in name:
            return f"{name} [{tool_name}]"
        return name

    def _render_node(run: dict[str, Any], prefix: str, is_last: bool, is_root: bool) -> list[str]:
        output: list[str] = []
        node_label = _format_node(run)
        if is_root:
            output.append(f"{prefix}{node_label}")
            child_prefix = prefix
        else:
            connector = "└── " if is_last else "├── "
            output.append(f"{prefix}{connector}{node_label}")
            child_prefix = prefix + ("    " if is_last else "│   ")

        run_id = str(run["run_id"])
        children = children_map.get(run_id, [])
        for i, child in enumerate(children):
            output.extend(_render_node(child, child_prefix, i == len(children) - 1, is_root=False))
        return output

    result: list[str] = []
    for root in root_runs:
        result.extend(_render_node(root, "", is_last=True, is_root=True))
    return result


def build_otel_span_tree(
    spans: Sequence[dict[str, Any]],
    db_path: Path | str | None = None,
) -> list[str]:
    """Reconstruct a recursive tree representation from OpenTelemetry span records.

    Args:
        spans: Sequence of span dictionaries containing span_id and parent_span_id.
        db_path: Optional database path to fetch associated span events.

    Returns:
        List of formatted lines representing the span execution hierarchy.
    """
    if not spans:
        return ["(No OpenTelemetry spans recorded for this invocation)"]

    span_by_id: dict[str, dict[str, Any]] = {str(s["span_id"]): dict(s) for s in spans}
    children_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    root_spans: list[dict[str, Any]] = []

    for s in spans:
        parent_id = s.get("parent_span_id")
        if parent_id and str(parent_id) in span_by_id:
            children_map[str(parent_id)].append(dict(s))
        else:
            root_spans.append(dict(s))

    def _render_node(
        span: dict[str, Any],
        prefix: str,
        is_last: bool,
        is_root: bool,
    ) -> list[str]:
        output: list[str] = []
        name = span.get("name") or "span"
        dur_val = span.get("duration_ms")
        dur_text = f"{dur_val:.0f} ms" if dur_val is not None else "-"

        if is_root:
            output.append(f"{prefix}{name:<24} {dur_text:>10}".rstrip())
            child_prefix = prefix
            event_prefix = prefix + "  "
        else:
            connector = "└── " if is_last else "├── "
            output.append(f"{prefix}{connector}{name:<24} {dur_text:>10}".rstrip())
            child_prefix = prefix + ("    " if is_last else "│   ")
            event_prefix = child_prefix

        span_id = str(span["span_id"])
        if db_path is not None:
            span_events = fetch_otel_span_events(db_path, span_id)
            for se in span_events:
                output.append(f"{event_prefix}event: {se.get('name')}")

        children = children_map.get(span_id, [])
        for i, child in enumerate(children):
            output.extend(
                _render_node(
                    child,
                    child_prefix,
                    i == len(children) - 1,
                    is_root=False,
                )
            )
        return output

    result: list[str] = []
    for root in root_spans:
        result.extend(_render_node(root, "", is_last=True, is_root=True))
    return result


def render_invocation_details(
    db_path: Path | str | None,
    invocation_id: str,
    *,
    show_events: bool = True,
    show_langsmith: bool = True,
    show_otel: bool = True,
) -> str:
    """Render comprehensive telemetry sections for a specific runtime invocation.

    Args:
        db_path: Database path to read from.
        invocation_id: Target invocation ID.
        show_events: Whether to render the runtime events section.
        show_langsmith: Whether to render the LangSmith run tree projection.
        show_otel: Whether to render OpenTelemetry spans and metrics.

    Returns:
        Multi-line formatted inspection report.
    """
    events = fetch_invocation_events(db_path, invocation_id)
    if not events:
        return f"Invocation '{invocation_id}' not found in telemetry database."

    # Extract invocation scalar attributes from events
    first_event = events[0]
    started_at = first_event.get("occurred_at", "-")

    # Determine status using shared terminal mapping
    status = derive_invocation_status(events)

    # Extract model, profile, reasoning, duration
    model = None
    profile = None
    reasoning = None
    duration_ms = None

    for e in events:
        if e.get("model"):
            model = e["model"]
        if e.get("profile"):
            profile = e["profile"]
        if e.get("reasoning_effort"):
            reasoning = e["reasoning_effort"]
        if e.get("duration_ms") is not None:
            duration_ms = max(duration_ms or 0.0, float(e["duration_ms"]))

    latency_summary = _derive_invocation_latency(events)
    if latency_summary["duration_ms"] is not None:
        duration_ms = float(latency_summary["duration_ms"])
    elif latency_summary["is_model_call"]:
        duration_ms = None

    host_latency_events: list[dict[str, Any]] = []
    invocation_call_id = latency_summary["call_id"]
    interaction_ids = {
        str(event["interaction_id"]) for event in events if event.get("interaction_id") is not None
    }
    for interaction_id in interaction_ids:
        host_latency_events.extend(
            event
            for event in fetch_interaction_events(db_path, interaction_id)
            if str(event.get("event_kind", "")).startswith("host.interaction_")
            or str(event.get("event_kind", "")).startswith("host.hitl_")
            or (
                invocation_call_id is not None
                and str(event.get("event_kind", "")).startswith("host.model_call_")
                and _metadata_value(event, "call_id") == invocation_call_id
            )
        )
    latency_events = [*events, *host_latency_events]

    lines: list[str] = [
        f"Invocation {invocation_id}",
        f"Started:    {started_at}",
        f"Status:     {status}",
        f"Model:      {model or '-'}",
        f"Profile:    {profile or '-'}",
        f"Reasoning:  {reasoning or '-'}",
        f"Invocation span: {_format_duration(duration_ms) if latency_summary['is_model_call'] else 'not a model call'}",
        "",
    ]
    lines.extend(_render_latency_breakdown(latency_events, invocation_scoped=True))
    lines.append("")

    # Section 1: Runtime Events
    if show_events:
        lines.extend(
            [
                "Runtime Events",
                "─" * 40,
            ]
        )
        for e in events:
            time_str = _format_time_hhmmss(e.get("occurred_at"))
            kind = str(e.get("event_kind", ""))
            tool = str(e.get("tool_name") or "")
            if tool:
                lines.append(f"{time_str}  {kind:<23} {tool}")
            else:
                lines.append(f"{time_str}  {kind}")
        lines.append("")

    # Section 2: LangSmith Projection
    if show_langsmith:
        lines.extend(
            [
                "LangSmith Projection",
                "─" * 40,
                "",
            ]
        )
        matching_runs = fetch_langsmith_runs_for_invocation(db_path, invocation_id)
        if not matching_runs:
            lines.append("(No LangSmith runs recorded for this invocation)")
        else:
            tree_lines = build_langsmith_tree(matching_runs)
            lines.extend(tree_lines)
        lines.append("")

    # Section 3: OpenTelemetry Projection
    if show_otel:
        lines.extend(
            [
                "OpenTelemetry Spans",
                "─" * 40,
                "",
            ]
        )
        matching_spans = fetch_otel_spans_for_invocation(db_path, invocation_id)
        tree_lines = build_otel_span_tree(matching_spans, db_path)
        lines.extend(tree_lines)
        lines.append("")

        lines.extend(
            [
                "OpenTelemetry Metrics — cumulative across database (not invocation-scoped)",
                "─" * 40,
                "",
            ]
        )
        conn = get_telemetry_connection(db_path, read_only=True)
        try:
            metric_rows = conn.execute(
                """
                SELECT instrument_name, instrument_type, value, attributes_json
                FROM otel_metrics
                ORDER BY instrument_name ASC
                """
            ).fetchall()
        finally:
            conn.close()

        if not metric_rows:
            lines.append("(No OpenTelemetry metrics recorded)")
        else:
            metrics_summary: dict[str, dict[str, Any]] = {}
            for row in metric_rows:
                inst_name = str(row["instrument_name"])
                val = float(row["value"])
                itype = str(row["instrument_type"])
                attrs_raw = row["attributes_json"] or "{}"
                try:
                    attrs = json.loads(attrs_raw) if isinstance(attrs_raw, str) else dict(attrs_raw)
                except Exception:
                    attrs = {}

                if inst_name not in metrics_summary:
                    metrics_summary[inst_name] = {
                        "type": itype,
                        "total": 0.0,
                        "count": 0,
                    }
                metrics_summary[inst_name]["total"] += val
                sample_count = attrs.get("count", 1)
                if isinstance(sample_count, int | float):
                    metrics_summary[inst_name]["count"] += int(sample_count)
                else:
                    metrics_summary[inst_name]["count"] += 1

            for inst_name, data in sorted(metrics_summary.items()):
                total = data["total"]
                count = data["count"]
                if "duration" in inst_name and count > 0:
                    val_str = f"{total / count:.0f} ms"
                elif total.is_integer():
                    val_str = str(int(total))
                else:
                    val_str = f"{total:.2f}"
                lines.append(f"{inst_name:<30} {val_str:>10}")
        lines.append("")

    return "\n".join(lines).rstrip()


def render_interaction_details(
    db_path: Path | str | None,
    interaction_id: str,
) -> str:
    """Render runtime events and redacted host errors for one CLI interaction.

    Args:
        db_path: Path to the telemetry database.
        interaction_id: Host-generated per-turn correlation identifier.

    Returns:
        Multi-line interaction report with no exception messages or user content.
    """
    events = fetch_interaction_events(db_path, interaction_id)
    if not events:
        return f"Interaction '{interaction_id}' not found in telemetry database."

    errors = [event for event in events if event.get("event_kind") == "host.turn_error"]
    invocation_ids = list(
        dict.fromkeys(
            str(event["invocation_id"])
            for event in events
            if event.get("invocation_id") is not None
        )
    )
    invocation_statuses = [
        derive_invocation_status(fetch_invocation_events(db_path, invocation_id))
        for invocation_id in invocation_ids
    ]
    if errors or "failed" in invocation_statuses:
        status = "failed"
    elif "running" in invocation_statuses:
        status = "running"
    elif invocation_statuses:
        status = "completed"
    else:
        status = "host-only"

    lines = [
        f"Interaction {interaction_id}",
        f"Status:     {status}",
        f"Task:       {next((event.get('task_id') for event in events if event.get('task_id')), '-')}",
        "",
    ]
    lines.extend(_render_latency_breakdown(events))
    lines.extend(
        [
            "",
            "Correlated Runtime and Host Events",
            "─" * 40,
        ]
    )
    for event in events:
        metadata = _event_metadata(event)
        kind = str(event.get("event_kind", ""))
        invocation_id = str(event.get("invocation_id") or "-")
        stage = metadata.get("stage")
        suffix = f" stage={stage}" if isinstance(stage, str) else ""
        provider_status = metadata.get("provider_status")
        provider_code = metadata.get("provider_error_code")
        provider_http = metadata.get("provider_http_status")
        if isinstance(provider_status, str):
            suffix += f" provider_status={_safe_display_value(provider_status, '-')}"
        if isinstance(provider_code, str):
            suffix += f" provider_error_code={_safe_display_value(provider_code, '-')}"
        if isinstance(provider_http, int) and not isinstance(provider_http, bool):
            suffix += f" provider_http_status={provider_http}"
        lines.append(
            f"{_format_time_hhmmss(event.get('occurred_at'))}  {kind:<24} {invocation_id}{suffix}"
        )

    if errors:
        lines.extend(["", "Host Error Diagnostics", "─" * 40])
        for error in errors:
            metadata = _event_metadata(error)
            stage = _safe_display_value(metadata.get("stage"), "unknown")
            module = _safe_display_value(metadata.get("exception_module"), "unknown")
            exception_type = _safe_display_value(metadata.get("exception_type"), "unknown")
            code = _safe_display_value(metadata.get("code"), "-")
            lines.append(f"stage={stage} exception={module}.{exception_type} code={code}")
            provider_status = _safe_display_value(metadata.get("provider_status"), "-")
            provider_code = _safe_display_value(metadata.get("provider_error_code"), "-")
            provider_http = metadata.get("provider_http_status")
            if provider_status != "-" or provider_code != "-" or isinstance(provider_http, int):
                safe_http = (
                    str(provider_http)
                    if isinstance(provider_http, int) and not isinstance(provider_http, bool)
                    else "-"
                )
                lines.append(
                    "provider: "
                    f"status={provider_status} error={provider_code} http_status={safe_http}"
                )
            causes = metadata.get("cause_types")
            if isinstance(causes, list):
                safe_causes = [
                    _safe_display_value(value, "unknown")
                    for value in causes
                    if isinstance(value, str)
                ]
                if safe_causes:
                    lines.append(f"causes: {' -> '.join(safe_causes)}")
            frames = metadata.get("frames")
            if isinstance(frames, list) and frames:
                lines.append("frames:")
                for frame in frames:
                    if not isinstance(frame, dict):
                        continue
                    filename = _safe_display_value(frame.get("file"), "unknown")
                    function = _safe_display_value(frame.get("function"), "unknown")
                    line_number = frame.get("line")
                    if isinstance(line_number, int):
                        lines.append(f"  {filename}:{function}:{line_number}")
    return "\n".join(lines)


def _safe_display_value(value: Any, default: str) -> str:
    """Render only short scalar diagnostic values from local telemetry."""
    if isinstance(value, str) and len(value) <= 240:
        return "".join(character if character.isprintable() else " " for character in value)
    return default


def inspect_telemetry(
    db_path: Path | str | None = None,
    *,
    last: bool = False,
    invocation: str | None = None,
    interaction: str | None = None,
    task: str | None = None,
    workflow: str | None = None,
    limit: int = 10,
    latency: bool = False,
    events_only: bool = False,
    langsmith_only: bool = False,
    otel_only: bool = False,
) -> str:
    """Execute telemetry inspection query and return formatted output.

    Args:
        db_path: Path to the telemetry database.
        last: If True, inspect the most recent invocation.
        invocation: Specific invocation ID to inspect.
        interaction: Specific host interaction ID to inspect with host diagnostics.
        task: Specific ephemeral task ID to inspect as a multi-turn timeline.
        workflow: Specific quote workflow ID to inspect as a host transition timeline.
        limit: Limit for recent invocations summary view.
        latency: If True, summarize latency and cache ratios for recent model calls.
        events_only: Show only runtime events.
        langsmith_only: Show only LangSmith tree.
        otel_only: Show only OpenTelemetry spans and metrics.

    Returns:
        Formatted inspection output.
    """
    target_db = get_telemetry_db_path(db_path)
    if not target_db.exists():
        return (
            f"Observability database not found at {target_db}.\n"
            "Run 'python init_observability.py' to initialize the telemetry database."
        )

    if latency:
        return render_latency_summary(target_db, limit=limit)

    if interaction is not None:
        return render_interaction_details(target_db, interaction)

    if task is not None or workflow is not None:
        task_events = (
            fetch_task_events(target_db, task)
            if task is not None
            else fetch_workflow_events(target_db, workflow or "")
        )
        if not task_events:
            label = f"Task '{task}'" if task is not None else f"Workflow '{workflow}'"
            return f"{label} not found in telemetry database."
        heading = f"Task {task}" if task is not None else f"Workflow {workflow}"
        lines = [heading, "─" * 48, "Correlated Runtime and Host Events"]
        lines.extend(_render_latency_breakdown(task_events))
        lines.append("")
        for event in task_events:
            if event.get("event_kind") == "output_text_delta":
                continue
            invocation_id = str(event.get("invocation_id") or "-")
            metadata = _event_metadata(event)
            details: list[str] = []
            if event.get("event_kind") == "host.turn_transition":
                for key in (
                    "route",
                    "intent",
                    "workflow_id",
                    "revision",
                    "phase_before",
                    "phase_after",
                    "result_code",
                ):
                    value = metadata.get(key)
                    if value is not None:
                        details.append(f"{key}={value}")
            diagnostics = metadata.get("diagnostics", [])
            diagnostic_code = metadata.get("diagnostic_code")
            if isinstance(diagnostic_code, str) and diagnostic_code.startswith("task.cleanup."):
                details.append(f"diagnostic={diagnostic_code}")
            if isinstance(diagnostics, list):
                details.extend(
                    f"diagnostic={diagnostic.get('code')}"
                    for diagnostic in diagnostics
                    if isinstance(diagnostic, dict) and diagnostic.get("code")
                )
            suffix = " " + " ".join(details) if details else ""
            lines.append(
                f"{_format_time_hhmmss(event.get('occurred_at'))}  "
                f"{str(event.get('event_kind')):<24} {invocation_id}{suffix}"
            )
        return "\n".join(lines)

    # 1. Inspect specific invocation or --last
    target_id = invocation
    if last:
        target_id = fetch_last_invocation_id(target_db)
        if target_id is None:
            return (
                "Recent Proteo invocations\n"
                "────────────────────────────────────────────────────────────\n"
                "No Proteo runtime invocations found in observability database.\n\n"
                f"{HOST_ONLY_NOTE}"
            )

    if target_id is not None:
        show_all = not (events_only or langsmith_only or otel_only)
        return render_invocation_details(
            target_db,
            target_id,
            show_events=show_all or events_only,
            show_langsmith=show_all or langsmith_only,
            show_otel=show_all or otel_only,
        )

    # 2. Default view: recent invocations summary
    return render_recent_invocations_summary(target_db, limit=limit)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone CLI inspection tool.

    Args:
        argv: Optional command line arguments sequence.

    Returns:
        Exit code: 0 on success, non-zero on error.
    """
    if hasattr(sys.stdout, "reconfigure"):
        with contextlib.suppress(Exception):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Inspect local Proteo telemetry from observability.sqlite3",
    )
    parser.add_argument(
        "--last",
        action="store_true",
        help="Inspect the most recent Proteo runtime invocation",
    )
    parser.add_argument(
        "--invocation",
        type=str,
        default=None,
        help="Inspect a specific Proteo runtime invocation by ID",
    )
    parser.add_argument(
        "--interaction",
        type=str,
        default=None,
        help="Inspect runtime events and sanitized host diagnostics for one interaction ID",
    )
    parser.add_argument(
        "--task",
        type=str,
        default=None,
        help="Inspect every recorded turn belonging to an ephemeral task ID",
    )
    parser.add_argument(
        "--workflow",
        type=str,
        default=None,
        help="Inspect metadata-only host transitions for one quote workflow ID",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of recent invocations to display (default: 10)",
    )
    parser.add_argument(
        "--latency",
        action="store_true",
        help="Summarize latency percentiles and prompt-cache ratio for recent model calls",
    )
    parser.add_argument(
        "--events",
        action="store_true",
        help="Display only runtime events",
    )
    parser.add_argument(
        "--langsmith",
        action="store_true",
        help="Display only LangSmith run tree projection",
    )
    parser.add_argument(
        "--otel",
        action="store_true",
        help="Display only OpenTelemetry spans and metrics projection",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Optional path to observability SQLite database",
    )

    args = parser.parse_args(argv)

    output = inspect_telemetry(
        db_path=args.db,
        last=args.last,
        invocation=args.invocation,
        interaction=args.interaction,
        task=args.task,
        workflow=args.workflow,
        limit=args.limit,
        latency=args.latency,
        events_only=args.events,
        langsmith_only=args.langsmith,
        otel_only=args.otel,
    )
    print(output)
    if "not found in telemetry database" in output:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
