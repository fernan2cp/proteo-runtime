# Traceability Matrix — Smart Quote Agent: Observability & Telemetry

## Design Guide to Requirements Mapping

| Guide Section / Contract | Requirements | Topic / Scope |
|---|---|---|
| Guide §1–§4 & §21 | `SQAO-REQ-003`, `SQAO-REQ-006`, `SQAO-REQ-017` | Purpose, architectural principles, neutral event bus reuse, configuration factory. |
| Guide §5, §7, §11, §15–§17 | `SQAO-REQ-001`, `SQAO-REQ-015` | Storage layout, SQLite schemas for 5 tables, indexes, and thread safety. |
| Guide §6 | `SQAO-REQ-002` | Dedicated telemetry initializer (`init_observability.py --reset`). |
| Guide §8–§9 | `SQAO-REQ-003`, `SQAO-REQ-013` | `SQLiteEventObserver` implementation, scalar metadata extraction, and safety. |
| Guide §10–§12 | `SQAO-REQ-004` | `RecordingLangSmithClient`, run hierarchy tracking, and `{"id": run_id}` return contract. |
| Guide §13–§14, §18 | `SQAO-REQ-005` | OpenTelemetry SQLite exporters (`SQLiteSpanExporter`, `SQLiteMetricExporter`). |
| Guide §21.1 (Application ToolExecutor) | `SQAO-REQ-007` | Public `ToolExecutor.event_sink` wiring for host-managed `create_quote` tool without private runtime calls. |
| Guide §22 | `SQAO-REQ-014` | Failure behavior and observer isolation (`strict=False`). |
| Guide §23–§28 | `SQAO-REQ-008`, `SQAO-REQ-009` | Read-only inspection CLI (`inspect_observability.py`), summary table, `--last`, filter flags. |
| Guide §29 | `SQAO-REQ-009`, `SQAO-REQ-013` | Host-only observability boundary (deterministic actions produce no synthetic runtime events). |
| Guide §31 | `SQAO-REQ-013` | Privacy, password masking, and canary redaction testing. |
| Guide §33 | `SQAO-REQ-015` | SQLite thread safety, WAL mode, bounded busy timeout, and independent connection ownership. |
| Guide §34–§37 | `SQAO-REQ-010`, `SQAO-REQ-011` | Application wiring (`app.py`, `graph.py`), README documentation, dual-terminal demo. |
| Project Guide & AGENTS.md | `SQAO-REQ-012`, `SQAO-REQ-016` | Strict repository boundary enforcement and Python style/type standards. |

---

## Requirements to Tasks, Criteria & Validation Matrix

| Requirement | Tasks | Criteria | Validation Strategy |
|---|---|---|---|
| `SQAO-REQ-001` (Telemetry Schema) | `SQAO-TASK-0001` | `AC-SQAO-001` | Unit test in `test_sqlite_event_observer.py::test_telemetry_schema`. |
| `SQAO-REQ-002` (Initializer CLI) | `SQAO-TASK-0002` | `AC-SQAO-002` | Subprocess execution of `init_observability.py --reset`. |
| `SQAO-REQ-003` (SQLite Event Observer) | `SQAO-TASK-0003` | `AC-SQAO-003` | Unit tests in `test_sqlite_event_observer.py`. |
| `SQAO-REQ-004` (LangSmith Recording Client) | `SQAO-TASK-0004` | `AC-SQAO-004` | Unit tests in `test_recording_langsmith_client.py`. |
| `SQAO-REQ-005` (OpenTelemetry Exporters) | `SQAO-TASK-0005` | `AC-SQAO-005` | Unit tests in `test_sqlite_otel_exporters.py`. |
| `SQAO-REQ-006` (Observability Factory) | `SQAO-TASK-0006` | `AC-SQAO-006` | Unit tests for `create_observability_config` in `test_sqlite_event_observer.py`. |
| `SQAO-REQ-007` (Host `event_sink` Wiring) | `SQAO-TASK-0006` | `AC-SQAO-007` | Integration tests in `test_agent.py` asserting tool approval/execution events. |
| `SQAO-REQ-008` (Inspector CLI) | `SQAO-TASK-0007` | `AC-SQAO-008` | CLI execution tests in `test_inspector_queries.py`. |
| `SQAO-REQ-009` (Host-Only Boundary) | `SQAO-TASK-0007` | `AC-SQAO-008` | Assertion that host-only turns show disclaimer and do not fabricate events. |
| `SQAO-REQ-010` (App Integration) | `SQAO-TASK-0006` | `AC-SQAO-007` | Full app REPL session test with observability enabled. |
| `SQAO-REQ-011` (User Documentation) | `SQAO-TASK-0009` | `AC-SQAO-012` | Manual inspection of `examples/smart_quote_agent/README.md`. |
| `SQAO-REQ-012` (Boundary Enforcement) | `SQAO-TASK-0010` | `AC-SQAO-014` | `git status --short` verifying 0 changes outside target folder. |
| `SQAO-REQ-013` (Secret Redaction) | `SQAO-TASK-0003`, `SQAO-TASK-0008` | `AC-SQAO-010` | Automated canary tests in `test_observability_redaction.py`. |
| `SQAO-REQ-014` (Failure Isolation) | `SQAO-TASK-0006`, `SQAO-TASK-0008` | `AC-SQAO-011` | Injected failure tests in `test_sqlite_event_observer.py`. |
| `SQAO-REQ-015` (Thread Concurrency) | `SQAO-TASK-0001`, `SQAO-TASK-0008` | `AC-SQAO-009` | Concurrent write stress test in `test_sqlite_event_observer.py`. |
| `SQAO-REQ-016` (Type Safety & Style) | `SQAO-TASK-0010` | `AC-SQAO-013` | `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check`. |
| `SQAO-REQ-017` (Zero Cloud Mandate) | `SQAO-TASK-0006`, `SQAO-TASK-0010` | `AC-SQAO-006` | Test run without environment variables or credentials. |

---

## Acceptance Criteria Evidence Map

| Criteria ID | Primary Evidence / Verification Location |
|---|---|
| `AC-SQAO-001` | `examples/smart_quote_agent/tests/test_sqlite_event_observer.py::test_telemetry_schema_creation` |
| `AC-SQAO-002` | `examples/smart_quote_agent/tests/test_sqlite_event_observer.py::test_init_observability_cli` |
| `AC-SQAO-003` | `examples/smart_quote_agent/tests/test_sqlite_event_observer.py::test_event_ingestion_and_ordering` |
| `AC-SQAO-004` | `examples/smart_quote_agent/tests/test_recording_langsmith_client.py::test_langsmith_run_hierarchy` |
| `AC-SQAO-005` | `examples/smart_quote_agent/tests/test_sqlite_otel_exporters.py::test_otel_spans_and_metrics_persistence` |
| `AC-SQAO-006` | `examples/smart_quote_agent/tests/test_sqlite_event_observer.py::test_create_observability_config_modes` |
| `AC-SQAO-007` | `examples/smart_quote_agent/tests/test_agent.py::test_direct_create_quote_tool_event_sink` |
| `AC-SQAO-008` | `examples/smart_quote_agent/tests/test_inspector_queries.py::test_inspector_cli_views_and_filters` |
| `AC-SQAO-009` | `examples/smart_quote_agent/tests/test_sqlite_event_observer.py::test_concurrent_telemetry_writes` |
| `AC-SQAO-010` | `examples/smart_quote_agent/tests/test_observability_redaction.py::test_password_and_canary_redaction` |
| `AC-SQAO-011` | `examples/smart_quote_agent/tests/test_sqlite_event_observer.py::test_observer_failure_isolation` |
| `AC-SQAO-012` | Review and inspection of `examples/smart_quote_agent/README.md` |
| `AC-SQAO-013` | Clean outputs from `uv run mypy`, `uv run ruff check`, `uv run ruff format --check` |
| `AC-SQAO-014` | Clean output from `git status --short` matching allowed paths |
