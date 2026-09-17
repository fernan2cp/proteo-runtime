"""Telemetry database initialization and reset script for Smart Quote Agent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure examples/smart_quote_agent is on sys.path when run directly
_DEMO_DIR = Path(__file__).resolve().parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from telemetry_db import get_telemetry_db_path, init_telemetry_database  # noqa: E402


def main() -> None:
    """Initialize or reset the Smart Quote Agent telemetry database."""
    parser = argparse.ArgumentParser(
        description="Initialize or reset the Smart Quote Agent telemetry SQLite database.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe existing telemetry data and create fresh tables.",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Optional custom path to the telemetry SQLite database file.",
    )
    args = parser.parse_args()

    db_path = get_telemetry_db_path(args.db_path)
    already_existed = db_path.exists()

    if already_existed and not args.reset:
        print(f"Telemetry database already exists at:\n  {db_path}")
        print("Run with --reset to wipe existing telemetry and recreate tables.")
        return

    init_telemetry_database(db_path, reset=args.reset)

    status_msg = "reset and initialized" if args.reset else "initialized"
    print(f"Smart Quote Agent telemetry database {status_msg}.\n")
    print(f"Database path:\n  {db_path}\n")
    print("Tables created:")
    print("  - runtime_events     (Proteo provider-neutral event stream)")
    print("  - langsmith_runs     (LangSmith run projection hierarchy)")
    print("  - otel_spans         (OpenTelemetry trace spans)")
    print("  - otel_span_events   (OpenTelemetry span lifecycle events)")
    print("  - otel_metrics       (OpenTelemetry aggregate metrics)")


if __name__ == "__main__":
    main()
