# Technical Design — Smart Quote Agent: Observability & Telemetry

## Architectural Overview & Topology

The observability subsystem operates as a decoupled observer layer attached to the provider-neutral Proteo event bus. It translates runtime events into three distinct representations (Neutral SQLite, LangSmith run trees, and OpenTelemetry spans/metrics) without introducing cloud dependencies.

```text
                             Smart Quote Agent (app.py / graph.py)
                                    |                      |
                    (Codex Turn)    |                      | (Direct create_quote)
                                    v                      v
                             CodexRuntime            ToolExecutor
                                    |                      | (event_sink)
                                    +----------+-----------+
                                               |
                                               v
                                      RuntimeEventBus (Proteo)
                                               |
         +-------------------------------------+-------------------------------------+
         | (PayloadMode.METADATA_ONLY)         | (PayloadMode.METADATA_ONLY)         | (PayloadMode.METADATA_ONLY)
         v                                     v                                     v
   SQLiteEventObserver                 LangSmithObserver                     OpenTelemetryObserver
         |                                     |                                     |
         | (direct insert)                     v (client calls)                      v (span / metric export)
         |                             RecordingLangSmithClient              SQLiteSpanExporter / MetricExporter
         |                                     |                                     |
         +-------------------------------------+-------------------------------------+
                                               |
                                               v
                             observability.sqlite3 (WAL mode)
                             ├── runtime_events
                             ├── langsmith_runs
                             ├── otel_spans
                             ├── otel_span_events
                             └── otel_metrics
                                               ^
                                               | (read-only queries)
                                    inspect_observability.py
```

### Module Breakdown within `examples/smart_quote_agent/`

```text
examples/smart_quote_agent/
├── init_observability.py      # Telemetry database creation and reset CLI
├── telemetry_db.py            # SQLite connection factory, WAL pragmas, DDL, insert/read helpers
├── observability.py           # SQLiteEventObserver and create_observability_config() factory
├── langsmith_recording.py     # RecordingLangSmithClient with run hierarchy tracking
├── otel_recording.py          # SQLiteSpanExporter, SQLiteMetricExporter, and OTel provider factory
├── inspect_observability.py   # Decoupled read-only inspection CLI with tree rendering
├── graph.py                   # Connects create_quote ToolExecutor.event_sink to observability bus
├── app.py                     # Wires create_observability_config() into CodexRuntime lifecycle
└── tests/
    ├── test_sqlite_event_observer.py
    ├── test_recording_langsmith_client.py
    ├── test_sqlite_otel_exporters.py
    ├── test_observability_redaction.py
    └── test_inspector_queries.py
```

---

## SQLite Telemetry Schema & Concurrency

### Database File Location
`examples/smart_quote_agent/data/observability.sqlite3`

### Thread Safety & Connection Policy
Because `LangSmithObserver.on_event()` executes client calls on worker threads via `asyncio.to_thread()`, connections must never be shared across threads.
- `telemetry_db.py` provides `get_telemetry_connection()` which creates a fresh connection per thread/operation.
- Every connection initializes with:
  ```sql
  PRAGMA foreign_keys = ON;
  PRAGMA journal_mode = WAL;
  PRAGMA busy_timeout = 5000;
  ```
- Operations execute in short-lived transactions to minimize lock contention.

### DDL Definitions

```sql
-- Neutral Proteo Runtime Events
CREATE TABLE IF NOT EXISTS runtime_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at       TEXT NOT NULL,
    occurred_at       TEXT NOT NULL,
    event_id          TEXT NOT NULL,
    event_kind        TEXT NOT NULL,
    invocation_id     TEXT NULL,
    session_id        TEXT NULL,
    turn_id           TEXT NULL,
    runtime_name      TEXT NULL,
    model             TEXT NULL,
    profile           TEXT NULL,
    reasoning_effort  TEXT NULL,
    tool_name         TEXT NULL,
    tool_call_id      TEXT NULL,
    status            TEXT NULL,
    duration_ms       REAL NULL,
    metadata_json     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runtime_events_invocation
    ON runtime_events(invocation_id);
CREATE INDEX IF NOT EXISTS idx_runtime_events_kind
    ON runtime_events(event_kind);
CREATE INDEX IF NOT EXISTS idx_runtime_events_occurred_at
    ON runtime_events(occurred_at);

-- LangSmith Run Hierarchy
CREATE TABLE IF NOT EXISTS langsmith_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL UNIQUE,
    parent_run_id   TEXT NULL,
    name            TEXT NOT NULL,
    run_type        TEXT NULL,
    project_name    TEXT NULL,
    started_at      TEXT NULL,
    ended_at        TEXT NULL,
    status          TEXT NOT NULL DEFAULT 'running',
    error           TEXT NULL,
    tags_json       TEXT NOT NULL DEFAULT '[]',
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_langsmith_runs_parent
    ON langsmith_runs(parent_run_id);
CREATE INDEX IF NOT EXISTS idx_langsmith_runs_started
    ON langsmith_runs(started_at);

-- OpenTelemetry Trace Spans
CREATE TABLE IF NOT EXISTS otel_spans (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id          TEXT NOT NULL,
    span_id           TEXT NOT NULL UNIQUE,
    parent_span_id    TEXT NULL,
    name              TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    ended_at          TEXT NULL,
    duration_ms       REAL NULL,
    status_code       TEXT NULL,
    status_message    TEXT NULL,
    attributes_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_otel_spans_trace
    ON otel_spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_otel_spans_parent
    ON otel_spans(parent_span_id);
CREATE INDEX IF NOT EXISTS idx_otel_spans_started
    ON otel_spans(started_at);

-- OpenTelemetry Span Events
CREATE TABLE IF NOT EXISTS otel_span_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    span_id          TEXT NOT NULL,
    name             TEXT NOT NULL,
    occurred_at      TEXT NOT NULL,
    attributes_json  TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_otel_span_events_span
    ON otel_span_events(span_id);

-- OpenTelemetry Low-Cardinality Metrics
CREATE TABLE IF NOT EXISTS otel_metrics (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at      TEXT NOT NULL,
    instrument_name  TEXT NOT NULL,
    instrument_type  TEXT NOT NULL,
    value            REAL NOT NULL,
    attributes_json  TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_otel_metrics_recorded
    ON otel_metrics(recorded_at);
```

---

## Observer Protocols & Adaptations

### 1. `SQLiteEventObserver` (`observability.py`)

Conforms to Proteo's `RuntimeObserver`:
```python
class SQLiteEventObserver:
    """Consumes projected RuntimeEvents and records them into SQLite."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or get_telemetry_db_path()

    async def on_event(self, event: RuntimeEvent) -> None:
        """Extract safe scalar metadata and insert a runtime_events record."""
        record_runtime_event(self.db_path, event)

    async def flush(self) -> None:
        """No-op for immediate writes."""
        pass

    async def close(self) -> None:
        """No-op for short-lived connection model."""
        pass
```

### 2. `RecordingLangSmithClient` (`langsmith_recording.py`)

A minimal duck-typed client injected into `LangSmithObserver`:
```python
class RecordingLangSmithClient:
    """In-memory and SQLite recording client standing in for LangSmith Client."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or get_telemetry_db_path()

    def create_run(self, **kwargs: Any) -> dict[str, Any]:
        """Record run creation and return mapping with 'id' for parent/child tracking."""
        run_id = str(kwargs.get("id") or uuid.uuid4())
        record_langsmith_create_run(self.db_path, run_id, kwargs)
        return {"id": run_id}

    def update_run(self, **kwargs: Any) -> None:
        """Update run end time, status, and error message."""
        record_langsmith_update_run(self.db_path, kwargs)

    def flush(self) -> None:
        """Idempotent flush."""
        pass

    def close(self) -> None:
        """Idempotent close."""
        pass
```

### 3. OpenTelemetry SQLite Exporters (`otel_recording.py`)

Integrated via the standard OpenTelemetry SDK:
```python
class SQLiteSpanExporter(SpanExporter):
    """Custom OpenTelemetry SpanExporter persisting completed spans to SQLite."""

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            record_otel_span(self.db_path, span)
        return SpanExportResult.SUCCESS

class SQLiteMetricExporter(MetricExporter):
    """Custom OpenTelemetry MetricExporter persisting metric points to SQLite."""

    def export(self, metrics_data: MetricsData) -> MetricExportResult:
        record_otel_metrics(self.db_path, metrics_data)
        return MetricExportResult.SUCCESS
```

---

## Public `ToolExecutor.event_sink` Wiring

The Smart Quote Agent executes tool calls under two distinct modes:
1. **Conversational Tools** (e.g. `list_products`): Executed during a controlled agent model turn inside `CodexRuntime`. `CodexRuntime` automatically forwards tool events through its configured observability bus.
2. **Deterministic Direct Tool Execution** (`create_quote`): Executed by the host application outside of a model turn inside LangGraph (`graph.py`).

To capture the lifecycle of `create_quote` (approval requested, approval resolved, tool execution started, and tool completed):
- The host constructs a shared `RuntimeEventBus(observability_config)` for the application session.
- The `ToolExecutor` for `create_quote` is created with its public `event_sink` parameter bound to `bus.emit`:
  ```python
  quote_executor = create_tool_executor(
      registry=registry,
      user=staff_user,
      approval_handler=approval_handler,
      event_sink=bus.emit,
  )
  ```
- **Strict Boundary**: Zero calls to `CodexRuntime._dispatch`. Only the public `event_sink` and `bus.emit` are used.

---

## Host-Only Boundary & Correlation Architecture

### Host-Only Boundary
Host actions that represent deterministic application control (rather than model inference or tool dispatch) deliberately produce **no** `RuntimeEvent`s:
- Help and capability displays
- Out-of-scope intent rejections
- Generic acknowledgements ("ok", "thanks")
- Interactive login and logout
- Authorization and role guards
- Discount percentage prompt (HITL)
- Direct customer and product database queries performed by the host

### Correlation Patterns in Telemetry
One user message can result in:
- **Zero invocations**: Deterministic host turn (e.g., login).
- **One invocation**: Conversational tool execution:
  `invocation_started` -> `turn_started` -> `tool_requested (list_products)` -> `tool_completed` -> `turn_completed` -> `invocation_completed`.
- **Structured Planner + Direct Tool Execution**: Persistent quote creation:
  - Structured planner invocation: `invocation_started` -> `turn_started` -> `turn_completed` -> `invocation_completed`.
  - Host-side resolution & HITL: (no events).
  - Direct `create_quote` tool executor group: `tool_requested` -> `tool_approval_requested` -> `tool_approval_resolved` -> `tool_started` -> `tool_completed`.

---

## Inspector CLI Design (`inspect_observability.py`)

The inspector is an independent CLI utility that reads `observability.sqlite3` with `mode=ro`:

### 1. Default Summary View
Queries distinct `invocation_id`s from `runtime_events`:
```text
Recent Proteo invocations
────────────────────────────────────────────────────────────
#  Invocation        Started     Duration   Tools   Status
1  inv_8ca1...       12:41:02    4.21 s        3    completed
2  inv_4fed...       12:39:15    1.82 s        1    completed
```
If the database has no runtime events (e.g., only host-only CLI turns were performed), the CLI explicitly reports:
`"No Proteo runtime invocations recorded yet (host-only turns do not generate runtime events)."`

### 2. `--last` and `--invocation <id>` Detailed View
- **Header**: Scalar metadata (status, model, profile, latency, timestamps).
- **Runtime Events**: Chronological listing of event kinds and tool names.
- **LangSmith Projection**: Recursive tree display reconstructed from `langsmith_runs` using `run_id` and `parent_run_id`:
  ```text
  LangSmith Projection
  ────────────────────────────────────────
  proteo.runtime
  └── proteo.turn
      └── proteo.tool [list_products]
  ```
- **OpenTelemetry Spans**: Spans matching `invocation_id`, rendered hierarchically only if explicit parent relationships exist.
- **OpenTelemetry Metrics**: Rendered as recent/aggregate telemetry (counter sums, histogram observations) without attributing them to individual invocations.

---

## Security, Redaction, and Canary Guarantees

1. **Payload Mode**: All local observers are bound with `PayloadMode.METADATA_ONLY`.
2. **Credential Redaction**:
   - `auth.py` collects passwords via `getpass.getpass()` and purges them immediately after database authentication.
   - `DEMO_PASSWORD_CANARY = "CANARY_SECRET_PWD_98765"` and demo password `1234` are validated via automated redaction tests in `test_observability_redaction.py`.
   - The redaction test asserts that neither canaries nor sensitive keys (`prompt`, `response`, `password`, `token`, `provider_payload`) appear in any JSON column across all 5 tables in `observability.sqlite3`.
3. **Failure Isolation**:
   - `strict=False` on `ObservabilityConfig`.
   - If SQLite writes throw an operational error (e.g. database locked), the event bus records a diagnostic, switches status to `ObservabilityStatus.DEGRADED`, and allows agent inference to complete successfully.
