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
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# Ensure demo directory is in sys.path when executed directly
_DEMO_DIR = str(Path(__file__).resolve().parent)
if _DEMO_DIR not in sys.path:
    sys.path.insert(0, _DEMO_DIR)

from telemetry_db import (  # noqa: E402
    derive_invocation_status,
    fetch_invocation_events,
    fetch_langsmith_runs_for_invocation,
    fetch_last_invocation_id,
    fetch_otel_span_events,
    fetch_otel_spans_for_invocation,
    fetch_recent_invocations,
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

    lines: list[str] = [
        f"Invocation {invocation_id}",
        f"Started:    {started_at}",
        f"Status:     {status}",
        f"Model:      {model or '-'}",
        f"Profile:    {profile or '-'}",
        f"Reasoning:  {reasoning or '-'}",
        f"Duration:   {_format_duration(duration_ms)}",
        "",
    ]

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
                "OpenTelemetry Metrics — recent/aggregate",
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


def inspect_telemetry(
    db_path: Path | str | None = None,
    *,
    last: bool = False,
    invocation: str | None = None,
    limit: int = 10,
    events_only: bool = False,
    langsmith_only: bool = False,
    otel_only: bool = False,
) -> str:
    """Execute telemetry inspection query and return formatted output.

    Args:
        db_path: Path to the telemetry database.
        last: If True, inspect the most recent invocation.
        invocation: Specific invocation ID to inspect.
        limit: Limit for recent invocations summary view.
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
        "--limit",
        type=int,
        default=10,
        help="Maximum number of recent invocations to display (default: 10)",
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
        limit=args.limit,
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
