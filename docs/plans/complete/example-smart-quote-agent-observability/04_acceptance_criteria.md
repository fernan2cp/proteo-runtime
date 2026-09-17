# Acceptance Criteria — Smart Quote Agent: Observability & Telemetry

All criteria have been verified and passed.

---

- `AC-SQAO-001`: **Telemetry Database Schema Creation** [PASSED]  
  `init_telemetry_database()` creates all 5 telemetry tables (`runtime_events`, `langsmith_runs`, `otel_spans`, `otel_span_events`, `otel_metrics`) and all specified indexes in `examples/smart_quote_agent/data/observability.sqlite3`.  
  *Requirements:* `SQAO-REQ-001`. *Tasks:* `SQAO-TASK-0001`. *Evidence:* Verified in `test_telemetry_db.py` (`test_init_telemetry_database_creates_all_tables_and_indexes`).

- `AC-SQAO-002`: **Dedicated Initializer CLI Execution** [PASSED]  
  Running `python examples/smart_quote_agent/init_observability.py --reset` removes existing telemetry tables, creates a fresh database, prints the database path, and exits with code 0 without importing or connecting to Codex.  
  *Requirements:* `SQAO-REQ-002`. *Tasks:* `SQAO-TASK-0002`. *Evidence:* Verified CLI execution with `--reset` flag exiting with code 0 in isolated subprocess.

- `AC-SQAO-003`: **Local Neutral Event Capture & Ordering** [PASSED]  
  Every projected `RuntimeEvent` delivered to `SQLiteEventObserver` is inserted into `runtime_events` with valid UTC ISO timestamps, extracted scalar fields, and preserves chronological ordering by `occurred_at`.  
  *Requirements:* `SQAO-REQ-003`. *Tasks:* `SQAO-TASK-0003`. *Evidence:* Verified in `test_sqlite_event_observer.py` (`test_sqlite_event_observer_records_projected_events`).

- `AC-SQAO-004`: **LangSmith Projection & Hierarchy Reconstruction** [PASSED]  
  The official `LangSmithObserver` paired with `RecordingLangSmithClient` writes runs to `langsmith_runs`. `create_run` returns an object or mapping exposing `id` or `run_id` (e.g. `{"id": run_id}`), allowing parent-child relationships between runtime, turn, and tool runs to be recursively reconstructed.  
  *Requirements:* `SQAO-REQ-004`. *Tasks:* `SQAO-TASK-0004`. *Evidence:* Verified in `test_recording_langsmith_client.py` (`test_langsmith_client_records_and_updates_runs`, `test_langsmith_client_reconstructs_parent_child_hierarchy`).

- `AC-SQAO-005`: **OpenTelemetry Spans & Metric Persistence** [PASSED]  
  `SQLiteSpanExporter` and `SQLiteMetricExporter` write trace spans to `otel_spans` (with span events to `otel_span_events`) and metric observations to `otel_metrics`. Spans can be grouped by safe Proteo correlation attributes (`proteo.invocation_id`).  
  *Requirements:* `SQAO-REQ-005`. *Tasks:* `SQAO-TASK-0005`. *Evidence:* Verified in `test_sqlite_otel_exporters.py` (`test_span_exporter_records_spans_and_events`, `test_metric_exporter_records_metrics`).

- `AC-SQAO-006`: **Unified Configuration Factory** [PASSED]  
  `create_observability_config()` returns an `ObservabilityConfig` with `strict=False`. Modes `off`, `local`, and `local+langsmith` bind the appropriate observers with `PayloadMode.METADATA_ONLY`.  
  *Requirements:* `SQAO-REQ-006`. *Tasks:* `SQAO-TASK-0006`. *Evidence:* Verified in `test_observability_wiring.py` (`test_create_observability_config_modes`).

- `AC-SQAO-007`: **Direct Host-Side Tool Event Wiring** [PASSED]  
  When staff creates a quote, the direct `create_quote` tool executor dispatches tool lifecycle events (`tool_requested`, `tool_approval_requested`, `tool_approval_resolved`, `tool_started`, `tool_completed`) into the observability pipeline via its public `event_sink` parameter without calling private `CodexRuntime._dispatch`.  
  *Requirements:* `SQAO-REQ-007`, `SQAO-REQ-010`. *Tasks:* `SQAO-TASK-0006`. *Evidence:* Verified in `test_observability_wiring.py` (`test_create_quote_emits_tool_events_to_event_sink`).

- `AC-SQAO-008`: **Standalone Inspector CLI Output** [PASSED]  
  `inspect_observability.py` executes in read-only mode without starting Codex:
  - Default view lists recent Proteo runtime invocations.
  - Explains clearly when host-only CLI turns (login, logout, help, discount prompt) produce no runtime invocation.
  - Detailed `--last` or `--invocation <id>` view renders scalar metadata, chronological events, LangSmith tree, OTel span group, and recent/aggregate OTel metrics.
  - Filters `--events`, `--langsmith`, and `--otel` restrict output as requested.  
  *Requirements:* `SQAO-REQ-008`, `SQAO-REQ-009`. *Tasks:* `SQAO-TASK-0007`. *Evidence:* Verified in `test_inspector_queries.py` (5 tests covering read-only safety, invocations, details, filters, and host-only interaction messaging).

- `AC-SQAO-009`: **Thread-Safe SQLite Concurrency** [PASSED]  
  `observability.sqlite3` operates with `PRAGMA journal_mode = WAL;` and `PRAGMA busy_timeout = 5000;`. Concurrent writes from worker threads (simulating `LangSmithObserver.on_event` via `asyncio.to_thread`) execute without `sqlite3.OperationalError: database is locked`.  
  *Requirements:* `SQAO-REQ-015`. *Tasks:* `SQAO-TASK-0001`, `SQAO-TASK-0008`. *Evidence:* Verified in `test_telemetry_db.py` (`test_concurrent_writes_thread_safety_20_threads`) and `test_observability_redaction.py` (`test_concurrent_event_bus_emission_thread_safety`).

- `AC-SQAO-010`: **Zero Leakage of Passwords and Sensitive Content** [PASSED]  
  Automated tests in `test_observability_redaction.py` verify that passwords (including `1234` and `DEMO_PASSWORD_CANARY`), raw prompts, model responses, and unredacted credentials never appear in any column of any table in `observability.sqlite3`.  
  *Requirements:* `SQAO-REQ-013`. *Tasks:* `SQAO-TASK-0003`, `SQAO-TASK-0008`. *Evidence:* Verified in `test_observability_redaction.py` (`test_zero_credential_leakage_in_all_telemetry_tables`, `test_zero_raw_prompt_leakage_in_all_telemetry_tables`).

- `AC-SQAO-011`: **Observer Failure Isolation** [PASSED]  
  Simulated observer or SQLite insertion failures do not cause agent inference to crash or prevent quote creation. The event bus logs a failure diagnostic and the runtime completes normally.  
  *Requirements:* `SQAO-REQ-014`. *Tasks:* `SQAO-TASK-0006`, `SQAO-TASK-0008`. *Evidence:* Verified via `strict=False` in `create_observability_config()`, graceful try-except in custom observers/exporters, and `test_observability_wiring.py` (`test_event_bus_lifecycle_and_observer_isolation`).

- `AC-SQAO-012`: **Documentation & Dual-Terminal Walkthrough** [PASSED]  
  `examples/smart_quote_agent/README.md` contains complete, reproducible instructions for running the telemetry initializer, the agent application, and the inspection CLI in a dual-terminal setup.  
  *Requirements:* `SQAO-REQ-011`. *Tasks:* `SQAO-TASK-0009`. *Evidence:* README updated with full architecture diagrams, principles, terminal command transcripts, and query filter examples.

- `AC-SQAO-013`: **Strict Type Safety and Style Compliance** [PASSED]  
  All code under `examples/smart_quote_agent/` passes `uv run mypy examples/smart_quote_agent --strict`, `uv run ruff check examples/smart_quote_agent`, and `uv run ruff format --check examples/smart_quote_agent` with zero errors. All functions have Google-style English docstrings.  
  *Requirements:* `SQAO-REQ-016`, `SQAO-REQ-017`. *Tasks:* `SQAO-TASK-0010`. *Evidence:* 0 mypy errors across 23 source files, 0 ruff errors, clean ruff format check.

- `AC-SQAO-014`: **Strict Repository Boundary Enforcement** [PASSED]  
  `git status --short` confirms zero files modified or created outside `examples/smart_quote_agent/*` and `docs/plans/active/example-smart-quote-agent-observability/`.  
  *Requirements:* `SQAO-REQ-012`. *Tasks:* `SQAO-TASK-0010`. *Evidence:* Verified `git status -s` shows changes restricted entirely to `examples/smart_quote_agent/` and plan documentation.

