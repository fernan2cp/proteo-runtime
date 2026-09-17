# Task Plan — Smart Quote Agent: Observability & Telemetry

## Conventions

Task states are `pending`, `in_progress`, `done`, or `blocked`.
All tasks start in state `pending`. A task may only transition to `done` when concrete test or verification evidence is recorded in `05_validation_plan.md`.

**Strict Boundary Rule**:
Under no circumstances may any file outside `examples/smart_quote_agent/*` be created, modified, or touched during the execution of any task.

---

## Ordered Workstreams

### SQAO-TASK-0001 — Telemetry Database Schema, Connection Management, and Thread Safety

**State:** `done`  
**Depends on:** none  
**Requirements:** `SQAO-REQ-001`, `SQAO-REQ-015`  
**Acceptance:** `AC-SQAO-001`, `AC-SQAO-009`  

- Implement `examples/smart_quote_agent/telemetry_db.py`:
  - `get_telemetry_db_path()` returning path to `examples/smart_quote_agent/data/observability.sqlite3`.
  - `get_telemetry_connection()` providing fresh per-operation/per-thread SQLite connections with `PRAGMA foreign_keys = ON;`, `PRAGMA journal_mode = WAL;`, and `PRAGMA busy_timeout = 5000;`.
  - `init_telemetry_database(db_path, reset=False)` applying DDL for the 5 telemetry tables: `runtime_events`, `langsmith_runs`, `otel_spans`, `otel_span_events`, and `otel_metrics`.
  - Typed helper functions for inserting records into each table (`insert_runtime_event`, `insert_langsmith_create_run`, `insert_langsmith_update_run`, `insert_otel_span`, `insert_otel_span_event`, `insert_otel_metric`).
  - Helper functions for querying invocation summaries and individual event streams (`fetch_recent_invocations`, `fetch_invocation_events`, `fetch_langsmith_runs`, `fetch_otel_spans`, `fetch_recent_metrics`, `fetch_last_invocation_id`).
- Evidence: `telemetry_db.py` and `tests/test_telemetry_db.py` implemented; 6 tests passed in `test_telemetry_db.py` (including schema creation, 10 indexes, WAL/busy_timeout pragma verification, and 20-thread concurrency test); `mypy --strict` and `ruff check` passed cleanly.

---

### SQAO-TASK-0002 — Dedicated Telemetry Initializer

**State:** `done`  
**Depends on:** `SQAO-TASK-0001`  
**Requirements:** `SQAO-REQ-002`  
**Acceptance:** `AC-SQAO-002`  

- Implement `examples/smart_quote_agent/init_observability.py`:
  - CLI parser supporting `--reset` to remove existing `observability.sqlite3` and reapply schemas.
  - Automatically ensures `examples/smart_quote_agent/data/` exists.
  - Prints database path and initialization status to stdout.
  - Exits with return code 0 without importing or launching Codex.
- Evidence: `init_observability.py` implemented; verified with direct CLI run and automated subprocess tests in `test_telemetry_db.py::test_init_observability_cli` (initial creation, existing file warning, and `--reset` wipe and recreation). All tests passed; `mypy --strict` clean.

---

### SQAO-TASK-0003 — Local SQLite Event Observer

**State:** `done`  
**Depends on:** `SQAO-TASK-0001`  
**Requirements:** `SQAO-REQ-003`, `SQAO-REQ-013`  
**Acceptance:** `AC-SQAO-003`, `AC-SQAO-010`  

- Implement `SQLiteEventObserver` in `examples/smart_quote_agent/observability.py`:
  - Implement the `RuntimeObserver` protocol (`on_event`, `flush`, `close`).
  - In `on_event`, extract safe scalar metadata (`invocation_id`, `turn_id`, `runtime_name`, `model`, `profile`, `tool_name`, `status`, `duration_ms`) and serialize remaining safe metadata to `metadata_json`.
  - Ensure zero credential, password, prompt, or raw completion leakage.
  - Implement idempotent `flush()` and `close()` methods.
- Evidence: `observability.py` implemented; verified with 3 unit tests in `test_sqlite_event_observer.py` (multi-event ingestion with timeline ordering, idempotent close, and graceful tolerance of missing attributes); `mypy --strict` and `ruff check` passed cleanly.

---

### SQAO-TASK-0004 — LangSmith Projection Recording Client

**State:** `done`  
**Depends on:** `SQAO-TASK-0001`  
**Requirements:** `SQAO-REQ-004`  
**Acceptance:** `AC-SQAO-004`  

- Implement `examples/smart_quote_agent/langsmith_recording.py`:
  - Implement `RecordingLangSmithClient` conforming to the duck-typed interface expected by Proteo's `LangSmithObserver`.
  - In `create_run(**kwargs)`, insert into `langsmith_runs` and return `{"id": run_id}` so that child runs (such as tool runs) inherit parent run IDs correctly.
  - In `update_run(**kwargs)`, update completion timestamps, status (`completed` or `error`), and safe error diagnostics.
  - Provide no-op `flush()` and `close()` methods.
- Evidence: `langsmith_recording.py` implemented; verified with `test_recording_langsmith_client.py` (direct calls returning `{"id": run_id}` and real `LangSmithObserver` integration verifying `proteo.runtime` -> `proteo.turn` -> `proteo.tool` parent-child hierarchy and terminal status updates); `mypy --strict` and `ruff check` passed cleanly.

---

### SQAO-TASK-0005 — OpenTelemetry SQLite Exporters and Provider Setup

**State:** `done`  
**Depends on:** `SQAO-TASK-0001`  
**Requirements:** `SQAO-REQ-005`  
**Acceptance:** `AC-SQAO-005`  

- Implement `examples/smart_quote_agent/otel_recording.py`:
  - Implement `SQLiteSpanExporter(SpanExporter)` that transforms OpenTelemetry `ReadableSpan` objects and inserts them into `otel_spans`, and unpacks span events into `otel_span_events`.
  - Implement `SQLiteMetricExporter(MetricExporter)` that transforms `MetricsData` into `otel_metrics`.
  - Implement `create_local_otel_providers()` configuring `TracerProvider` with `SimpleSpanProcessor(SQLiteSpanExporter)` and `MeterProvider` with `SQLiteMetricExporter`.
- Evidence: `otel_recording.py` implemented; verified with `test_sqlite_otel_exporters.py` (direct export of spans, span events, and metrics, and real `OpenTelemetryObserver` integration generating trace spans and low-cardinality metric counters); `mypy --strict` and `ruff check` passed cleanly.

---

### SQAO-TASK-0006 — Unified Observability Configuration Factory and Host `event_sink` Wiring

**State:** `done`  
**Depends on:** `SQAO-TASK-0003`, `SQAO-TASK-0004`, `SQAO-TASK-0005`  
**Requirements:** `SQAO-REQ-006`, `SQAO-REQ-007`, `SQAO-REQ-010`, `SQAO-REQ-014`  
**Acceptance:** `AC-SQAO-006`, `AC-SQAO-007`, `AC-SQAO-011`  

- In `examples/smart_quote_agent/observability.py`:
  - Implement `create_observability_config(mode, db_path)` supporting `off`, `local`, and `local+langsmith`.
  - Default to `local` mode binding `SQLiteEventObserver`, `LangSmithObserver(RecordingLangSmithClient)`, and `OpenTelemetryObserver(tracer, meter)` with `PayloadMode.METADATA_ONLY` and `strict=False`.
- In `examples/smart_quote_agent/graph.py`:
  - Wire the host-managed `create_quote` tool executor's `event_sink` parameter to `bus.emit`.
  - Verify zero calls to private `CodexRuntime._dispatch`.
- In `examples/smart_quote_agent/app.py`:
  - Instantiate `create_observability_config()` and pass to `CodexRuntime(observability=...)`.
  - Retain clean fallback when `DEMO_OBSERVABILITY=off` or `--offline` is specified.
- Evidence: `observability.py` implemented with `create_observability_config` and `get_observability_bus`; `graph.py` and `app.py` wired to `bus.emit` and `await bus.close()`; verified with `test_observability_wiring.py` (modes validation, tool lifecycle events written to SQLite upon staff quote creation, and failure isolation under `strict=False`); 68 tests passing; `mypy --strict` and `ruff check` passed cleanly.

---

### SQAO-TASK-0007 — Standalone Telemetry Inspection CLI

**State:** `done`  
**Depends on:** `SQAO-TASK-0001`  
**Requirements:** `SQAO-REQ-008`, `SQAO-REQ-009`  
**Acceptance:** `AC-SQAO-008`  

- Implement `examples/smart_quote_agent/inspect_observability.py`:
  - Implement `argparse` CLI supporting no arguments (recent invocations list), `--last`, `--limit N`, `--invocation <id>`, `--events`, `--langsmith`, and `--otel`.
  - Display clear explanation when a host-only interaction produces no runtime invocation.
  - Reconstruct recursive tree hierarchy from `langsmith_runs` based on `run_id` and `parent_run_id`.
  - Render OpenTelemetry spans grouped by correlation attributes (`proteo.invocation_id`) and render metrics as recent/aggregate telemetry.
  - Connect to `observability.sqlite3` with read-only access (`mode=ro`) without importing Codex.
- Evidence: `inspect_observability.py` implemented; verified with `test_inspector_queries.py` (empty DB handling with host-only disclaimer, LangSmith recursive tree reconstruction, summary tabular rendering, detailed `--last` view with all sections, filter flags `--events`/`--langsmith`/`--otel`, and `main()` CLI exit code handling); 5 tests passing; `mypy --strict` and `ruff check` passed cleanly.

---

### SQAO-TASK-0008 — Redaction, Concurrency, and Component Unit Test Suite

**State:** `done`  
**Depends on:** `SQAO-TASK-0006`, `SQAO-TASK-0007`  
**Requirements:** `SQAO-REQ-013`, `SQAO-REQ-014`, `SQAO-REQ-015`  
**Acceptance:** `AC-SQAO-009`, `AC-SQAO-010`, `AC-SQAO-011`  

- Add tests under `examples/smart_quote_agent/tests/`:
  - `test_sqlite_event_observer.py`: Event persistence, metadata extraction, and ordering.
  - `test_recording_langsmith_client.py`: Run creation, update, and parent/child relationship integrity.
  - `test_sqlite_otel_exporters.py`: Span and metric export assertions.
  - `test_observability_redaction.py`: Assert `DEMO_PASSWORD_CANARY`, demo password `1234`, and secret keys never appear in any telemetry table.
  - `test_inspector_queries.py`: Summary queries, tree rendering, and CLI flag handling.
  - Concurrency stress test verifying multi-threaded inserts without database lock errors.
- Evidence: `test_observability_redaction.py` implemented; verified two-layer defense against credential leakage across all 5 tables (`runtime_events`, `langsmith_runs`, `otel_spans`, `otel_span_events`, `otel_metrics`) with canaries for password, api key, tokens, and raw prompts/responses; verified 20 concurrent worker tasks without database locking; 3 tests passing; `mypy --strict` and `ruff check` passed cleanly.

---

### SQAO-TASK-0009 — Documentation and Dual-Terminal Demonstration Walkthrough

**State:** `done`  
**Depends on:** `SQAO-TASK-0008`  
**Requirements:** `SQAO-REQ-011`  
**Acceptance:** `AC-SQAO-012`  

- Update `examples/smart_quote_agent/README.md`:
  - Document Phase 2 observability architecture.
  - Detail setup command `python init_observability.py --reset`.
  - Provide complete step-by-step dual-terminal demonstration guide:
    - Terminal 1: run `python app.py`.
    - Terminal 2: run `python inspect_observability.py --last`.
  - Document environment variable options (`DEMO_OBSERVABILITY=local|off|local+langsmith`).
- Evidence: `examples/smart_quote_agent/README.md` updated with comprehensive Phase 2 observability architecture section (diagram, principles, 3 parallel representations, storage separation, content-safe policy, failure isolation) and complete step-by-step dual-terminal demonstration walkthrough with real CLI transcripts and filter flags.

---

### SQAO-TASK-0010 — Static Analysis, Linting, and Repository Boundary Verification

**State:** `done`  
**Depends on:** `SQAO-TASK-0009`  
**Requirements:** `SQAO-REQ-012`, `SQAO-REQ-016`, `SQAO-REQ-017`  
**Acceptance:** `AC-SQAO-013`, `AC-SQAO-014`  

- Run `uv run mypy examples/smart_quote_agent --strict` and verify zero errors.
- Run `uv run ruff check examples/smart_quote_agent` and verify all checks pass.
- Run `uv run ruff format --check examples/smart_quote_agent` and verify formatting.
- Execute full test suite `uv run pytest examples/smart_quote_agent/tests/ -v`.
- Verify `git status` confirms zero files modified outside `examples/smart_quote_agent/` and the active plan folder.
- Evidence: `mypy --strict` passes with 0 errors across all 23 source files; `ruff check` passes with 0 errors; `ruff format --check` reports all 24 files formatted; full test suite passes 76/76 tests in 13.72s; `git status --short` confirms zero modifications outside `examples/smart_quote_agent/` and `docs/plans/active/example-smart-quote-agent-observability/`.

