# Requirements — Smart Quote Agent: Observability & Telemetry

## Functional Requirements

### SQAO-REQ-001 — Dedicated Telemetry Database Schema
The example must define and manage a separate SQLite database file `examples/smart_quote_agent/data/observability.sqlite3` containing 5 dedicated telemetry tables:
1. `runtime_events`: Provider-neutral runtime event records including `id`, `recorded_at`, `occurred_at`, `event_id`, `event_kind`, `invocation_id`, `session_id`, `turn_id`, `runtime_name`, `model`, `profile`, `reasoning_effort`, `tool_name`, `tool_call_id`, `status`, `duration_ms`, and `metadata_json`, with indexes on `invocation_id`, `event_kind`, and `occurred_at`.
2. `langsmith_runs`: Captures LangSmith run hierarchy including `id`, `run_id` (UNIQUE), `parent_run_id`, `name`, `run_type`, `project_name`, `started_at`, `ended_at`, `status`, `error`, `tags_json`, and `metadata_json`, with indexes on `parent_run_id` and `started_at`.
3. `otel_spans`: Captures OpenTelemetry trace spans including `id`, `trace_id`, `span_id` (UNIQUE), `parent_span_id`, `name`, `started_at`, `ended_at`, `duration_ms`, `status_code`, `status_message`, and `attributes_json`, with indexes on `trace_id`, `parent_span_id`, and `started_at`.
4. `otel_span_events`: Captures span lifecycle events including `id`, `span_id`, `name`, `occurred_at`, and `attributes_json`.
5. `otel_metrics`: Captures exported metric data points including `id`, `recorded_at`, `instrument_name`, `instrument_type`, `value`, and `attributes_json`.

### SQAO-REQ-002 — Dedicated Telemetry Initializer
The example must provide a standalone script `examples/smart_quote_agent/init_observability.py` callable from the CLI:
- Accepts `--reset` to remove existing `observability.sqlite3` before creating fresh tables.
- Creates `examples/smart_quote_agent/data/` if missing.
- Applies the telemetry DDL schema without errors.
- Prints the absolute database path upon success.
- Exits cleanly with return code 0 without starting or importing Codex.

### SQAO-REQ-003 — Local SQLite Event Observer
The example must implement `SQLiteEventObserver` in `examples/smart_quote_agent/observability.py`:
- Conforms to Proteo's `RuntimeObserver` protocol (`on_event`, `flush`, `close`).
- Accepts projected `RuntimeEvent` instances delivered via the neutral event bus.
- Extracts safe scalar metadata fields (identifiers, runtime name, model, latency, tool attributes) and persists the complete safe metadata mapping into `metadata_json`.
- Maintains idempotent `flush()` and `close()` operations.
- Never reads or persists application passwords, prompt texts, or raw model completions.

### SQAO-REQ-004 — LangSmith Projection Recording Client
The example must implement `RecordingLangSmithClient` in `examples/smart_quote_agent/langsmith_recording.py`:
- Acts as an in-memory/local recording double injected into the official `LangSmithObserver`.
- Implements `create_run(**kwargs)` by storing run attributes into `langsmith_runs` and returning an object or mapping exposing `id` or `run_id` (e.g., `{"id": run_id}`) so that `LangSmithObserver` can establish proper child run associations.
- Implements `update_run(**kwargs)` by updating completion timestamps, terminal statuses, and error messages in `langsmith_runs`.
- Implements optional `flush()` and `close()` methods gracefully.

### SQAO-REQ-005 — OpenTelemetry Local SQLite Exporters
The example must implement local OpenTelemetry exporters in `examples/smart_quote_agent/otel_recording.py`:
- Implements `SQLiteSpanExporter` to persist finished spans into `otel_spans` and any embedded span events into `otel_span_events`.
- Implements `SQLiteMetricExporter` to persist metric data points into `otel_metrics`.
- Configures local `TracerProvider` and `MeterProvider` instances backed by these SQLite exporters to pass to the official `OpenTelemetryObserver`.

### SQAO-REQ-006 — Unified Observability Configuration Factory
The example must provide `create_observability_config(mode: str | None = None, ...)` in `examples/smart_quote_agent/observability.py`:
- Evaluates `mode` argument or `DEMO_OBSERVABILITY` environment variable, defaulting to `local`.
- Supports modes: `off` (empty observers), `local` (binds `SQLiteEventObserver`, `LangSmithObserver` with recording client, and `OpenTelemetryObserver` with local exporters), and `local+langsmith` (local recording plus real LangSmith client export).
- Enforces `PayloadMode.METADATA_ONLY` across all local bindings.
- Sets `strict=False` on `ObservabilityConfig` to ensure telemetry isolation.

### SQAO-REQ-007 — Public `ToolExecutor.event_sink` Wiring for Host Tools
The example must wire application-created `ToolExecutor` instances (specifically the host-side `create_quote` executor) into the observability pipeline:
- Supplies an async callable to the public `event_sink` parameter of `ToolExecutor` that routes tool lifecycle events directly through `RuntimeEventBus.emit`.
- Strictly avoids calling any private runtime methods (specifically zero calls to `CodexRuntime._dispatch`).
- Ensures tool approval requested, approval resolved, tool started, and tool completed events are captured for direct quote creation.

### SQAO-REQ-008 — Standalone Read-Only Telemetry Inspector CLI
The example must provide `examples/smart_quote_agent/inspect_observability.py`:
- Connects read-only to `observability.sqlite3` and executes without starting Codex.
- Default invocation: Displays a formatted table of recent Proteo invocations with index, invocation ID, start time, duration, tool count, and terminal status.
- Detailed view (`--last` or `--invocation <id>`): Displays scalar invocation metadata, chronological `RuntimeEvent` timeline, LangSmith run projection tree, OpenTelemetry span group, and recent/aggregate OTel metrics.
- Filtering options: `--limit N`, `--events` (only event list), `--langsmith` (only LangSmith tree), `--otel` (only OTel spans/metrics).

### SQAO-REQ-009 — Host-Only Boundary & CLI Disambiguation
The inspection CLI must clearly distinguish between host-owned deterministic turns and Proteo runtime invocations:
- When `--last` is requested after a host-only turn (such as login, logout, help, or discount prompt), the inspector must explain that the interaction was handled host-side and display the most recent Proteo runtime invocation.
- The inspector documentation must clarify that one user turn may produce zero, one, or multiple runtime invocations.

### SQAO-REQ-010 — Application CLI Integration
The interactive agent entrypoint `examples/smart_quote_agent/app.py` must incorporate observability:
- Integrates `create_observability_config` into `CodexRuntime(observability=...)`.
- Passes the application event sink to the LangGraph execution environment so that direct quote creation tool execution is recorded.
- Retains full functional parity when `DEMO_OBSERVABILITY=off` or `--offline` is set.

### SQAO-REQ-011 — Comprehensive Documentation and Demonstration Guide
The documentation in `examples/smart_quote_agent/README.md` must be updated with:
- Architecture narrative explaining how neutral events project to SQLite, LangSmith, and OpenTelemetry.
- Exact CLI setup commands: `python init_observability.py --reset`.
- Step-by-step dual-terminal live demonstration walkthrough (Terminal 1: agent interaction; Terminal 2: real-time telemetry inspection).
- Explicit security and privacy guarantees.

---

## Non-Functional Requirements

### SQAO-REQ-012 — Strict Boundary Enforcement
All new files, modifications, tests, and artifacts must reside strictly within `examples/smart_quote_agent/*`. Under no circumstances may any file in `src/*`, root `tests/*`, `pyproject.toml`, or other repository locations be altered.

### SQAO-REQ-013 — Content Redaction and Credential Hygiene
- All observer bindings must use `PayloadMode.METADATA_ONLY`.
- Application passwords (including default `1234` and test canaries `DEMO_PASSWORD_CANARY`) must never appear in `runtime_events.metadata_json`, `langsmith_runs.metadata_json`, `otel_spans.attributes_json`, `otel_span_events.attributes_json`, or `otel_metrics.attributes_json`.
- Prompts, model completions, raw arguments, and raw results must not be persisted in telemetry tables.

### SQAO-REQ-014 — Observer Failure Isolation
- Observability dispatch failures, database lock errors, or exporter exceptions must never abort business execution or interrupt user quotes.
- `strict=False` must be configured, ensuring degraded observability status is recorded in diagnostics without failing inference.

### SQAO-REQ-015 — Thread-Safe Database Concurrency
- Telemetry database access must be safe across asyncio event loop and worker threads used by `LangSmithObserver`.
- Database connections must be short-lived per operation/thread.
- WAL journal mode must be enabled (`PRAGMA journal_mode = WAL;`) and a bounded busy timeout (`PRAGMA busy_timeout = 5000;`) must be set.

### SQAO-REQ-016 — Strict Type Safety and Documentation Style
- All new code must be fully annotated and pass `uv run mypy examples/smart_quote_agent --strict` with zero errors.
- Code style must pass `uv run ruff check examples/smart_quote_agent` and `uv run ruff format --check examples/smart_quote_agent`.
- All public and private functions, classes, and methods must have English docstrings formatted according to the Google Python Style Guide.

### SQAO-REQ-017 — Zero Mandatory Cloud Infrastructure
- The default execution mode must require no external API keys (no LangSmith API keys, no OTLP collector endpoints, no cloud accounts). All telemetry must be inspectable locally via SQLite.
