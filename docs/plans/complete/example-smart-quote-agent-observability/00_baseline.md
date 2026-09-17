# Baseline — Smart Quote Agent: Observability & Telemetry

## Current Repository State

- **Baseline Revision**: Proteo Runtime `0.6.x` baseline with foundational phases 0 through 5 fully implemented and verified.
- **Phase 1 Example Baseline**:
  - `examples/smart_quote_agent/` is fully implemented and operational with 51 unit and integration tests passing (`examples/smart_quote_agent/tests/test_agent.py`).
  - Strict type checking (`uv run mypy examples/smart_quote_agent --strict`) passes with zero errors across all 10 source files.
  - Code formatting and linting (`ruff check`, `ruff format --check`) are 100% compliant.
  - Business persistence (`examples/smart_quote_agent/data/demo.sqlite3`) correctly manages tables: `users`, `customers`, `products`, `quotes`, and `quote_lines`.
- **Applicable Architecture Guides and ADRs**:
  - `docs/design/project-guide.md` (§4 Observability & Telemetry, §9 Tool Execution, §19 Non-Functional Requirements, §21 Security, §23 HITL, §24 Audit & Privacy).
  - `docs/examples/smart_quote_agent/design/smart_quote_agent_observability_guide.md` (Observability design source of truth).

## Existing Proteo Contracts Reused

The observability implementation reuses public contracts already provided by Proteo Runtime:

1. **Neutral Observability Contracts** (`proteo_runtime.observability`):
   - `ObservabilityConfig`: Immutable configuration accepting a tuple of `ObserverBinding`s, timeout settings, and strictness policy.
   - `ObserverBinding`: Pairs a `RuntimeObserver` with an explicit `PayloadMode` (default: `PayloadMode.METADATA_ONLY`).
   - `PayloadMode`: Enum controlling payload projection (`FULL`, `METADATA_ONLY`, `DISABLED`).
   - `RuntimeObserver`: Async protocol defining `on_event(event: RuntimeEvent)`, `flush()`, and `close()`.
   - `RuntimeEventBus`: Event dispatcher handling asynchronous notification, per-observer payload projection, secret redaction, and error isolation.
2. **Official Observer Projections**:
   - `LangSmithObserver` (`proteo_runtime.observability.langsmith`): Converts neutral runtime events to hierarchical LangSmith runs (`proteo.runtime`, `proteo.turn`, `proteo.tool`).
   - `OpenTelemetryObserver` (`proteo_runtime.observability.opentelemetry`): Converts neutral runtime events to OpenTelemetry trace spans (`proteo.runtime`, `proteo.invocation`, `proteo.turn`, `proteo.tool`) and low-cardinality metric counters/histograms (`proteo.runtime.events`, `proteo.runtime.invocations`, `proteo.runtime.tool_calls`, `proteo.runtime.duration`).
3. **Tool Lifecycle Event Sink** (`proteo_runtime.tools.ToolExecutor`):
   - `ToolExecutor` exposes a public `event_sink` parameter (`Callable[[RuntimeEvent], Awaitable[Any]] | None`) that dispatches tool lifecycle events (`tool_requested`, `tool_approval_requested`, `tool_approval_resolved`, `tool_started`, `tool_completed`, `tool_denied`, `tool_failed`).

## Constraints & Boundary Conditions

- **Zero Project Code Modifications**:
  - Under no circumstances may code outside `examples/smart_quote_agent/*` be created or modified. All adapters, exporters, and initializers reside strictly within the example folder.
- **Content Safety and Secret Protection**:
  - All local observer bindings must use `PayloadMode.METADATA_ONLY`.
  - Telemetry databases must never store raw prompts, model completions, passwords, customer credentials, tool arguments, or tool output values.
- **Failure Isolation**:
  - Observability must use `strict=False`. A failure in a local SQLite observer, recording client, or exporter must never abort business execution or cause quote creation to fail.
- **Storage Separation**:
  - Business data (`demo.sqlite3`) and telemetry data (`observability.sqlite3`) must remain completely separate. No cross-database queries or foreign keys.
- **Host-Only Boundary**:
  - Deterministic application behaviors (login, logout, help, out-of-scope rejections, scope guards, discount HITL prompt, direct database lookups) are host-owned and must not produce synthetic `RuntimeEvent`s.
- **Thread Safety & SQLite Concurrency**:
  - `LangSmithObserver` invokes client methods on worker threads via `asyncio.to_thread`.
  - SQLite connections must not be shared between the asyncio event loop and worker threads. Telemetry operations must use short-lived connections per thread/operation with WAL mode and `PRAGMA busy_timeout = 5000;`.
- **Public Contracts Only**:
  - No calls to private methods like `CodexRuntime._dispatch`. Host-side tool lifecycle is wired exclusively through the public `event_sink` hook.

## Closed Architectural Decisions

1. **Event Bus as Single Source of Truth**:
   - Telemetry data originates strictly from Proteo's neutral `RuntimeEventBus`. SQLite is a local recording sink, not a replacement backend for LangSmith or OpenTelemetry.
2. **Reuse of Official Observers**:
   - Rather than handwriting separate projection mappers, the example instantiates official `LangSmithObserver` and `OpenTelemetryObserver` instances and captures their downstream outputs.
3. **No Cloud Requirement by Default**:
   - The default mode (`DEMO_OBSERVABILITY=local`) runs 100% locally with zero external network calls or cloud API keys.
4. **Standalone Inspector**:
   - `inspect_observability.py` is a decoupled, read-only CLI script reading only `observability.sqlite3`. It never imports or initializes `CodexRuntime`.

## Gaps, Unknowns & Risks

| ID | Description | Impact | Mitigation / Planned Resolution |
|---|---|---|---|
| GAP-001 | Thread concurrency between asyncio event loop and `LangSmithObserver` worker threads accessing `observability.sqlite3`. | High | Enforce connection-per-thread factory with WAL journal mode and 5000 ms busy timeout in `telemetry_db.py`. Add concurrent write stress tests. |
| GAP-002 | Host-side `create_quote` tool execution occurs outside Codex model turn. | Med | Wire `event_sink` of the host-managed `ToolExecutor` directly to `RuntimeEventBus.emit`, capturing approval and tool lifecycle events. |
| GAP-003 | OpenTelemetry metrics are low-cardinality and lack invocation IDs. | Low | Design the inspector CLI to present metrics as recent/aggregate telemetry rather than misleading per-invocation claims. |
| GAP-004 | Accidental leakage of demo credentials (`1234` or canaries) into telemetry database. | High | Enforce `PayloadMode.METADATA_ONLY`, sanitize scalar metadata extraction, and provide automated canary tests (`DEMO_PASSWORD_CANARY`) in `test_observability_redaction.py`. |
