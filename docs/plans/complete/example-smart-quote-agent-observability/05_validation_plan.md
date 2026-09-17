# Validation Plan — Smart Quote Agent: Observability & Telemetry

## Automated Verification Commands

```powershell
# 1. Type Checking
uv run mypy examples/smart_quote_agent --strict

# 2. Linting and Code Style
uv run ruff check examples/smart_quote_agent
uv run ruff format --check examples/smart_quote_agent

# 3. Unit and Integration Test Suite
uv run pytest examples/smart_quote_agent/tests/ -v

# 4. Strict Repository Boundary Check
git status --short
```

---

## Test Matrices & Scenarios

| Scenario ID | Test Suite / Target | Description | Covered Criteria | Expected Result |
|---|---|---|---|---|
| SCEN-001 | `test_sqlite_event_observer.py` | Verify `init_telemetry_database` applies schema and creates all 5 tables and indexes. | `AC-SQAO-001` | All tables exist with correct columns and indexes. |
| SCEN-002 | CLI Execution | Run `init_observability.py --reset`. | `AC-SQAO-002` | Reset completes, prints DB path, exits with code 0 without starting Codex. |
| SCEN-003 | `test_sqlite_event_observer.py` | Deliver fake `RuntimeEvent` sequence to `SQLiteEventObserver`. | `AC-SQAO-003` | Events persisted with valid UTC ISO timestamps, ordered by `occurred_at`. |
| SCEN-004 | `test_recording_langsmith_client.py` | Ingest events via official `LangSmithObserver` with `RecordingLangSmithClient`. | `AC-SQAO-004` | `create_run` returns `{"id": run_id}`; parent/child tree is reconstructed. |
| SCEN-005 | `test_sqlite_otel_exporters.py` | Ingest events via official `OpenTelemetryObserver` with `SQLiteSpanExporter` and `SQLiteMetricExporter`. | `AC-SQAO-005` | Spans, span events, and metrics persisted into SQLite. |
| SCEN-006 | `test_sqlite_event_observer.py` | Test `create_observability_config` across `off`, `local`, and `local+langsmith` modes. | `AC-SQAO-006` | Correct bindings created with `PayloadMode.METADATA_ONLY` and `strict=False`. |
| SCEN-007 | `test_agent.py` | Execute staff quote creation workflow with direct `create_quote` tool executor. | `AC-SQAO-007` | Tool lifecycle events (`tool_requested`, `tool_approval_*`, `tool_completed`) captured via `event_sink`. |
| SCEN-008 | `test_inspector_queries.py` | Test inspector CLI parsing and rendering for default summary, `--last`, and filter flags. | `AC-SQAO-008` | Formatted output matches guide specification; host-only disclaimer displayed. |
| SCEN-009 | `test_sqlite_event_observer.py` | Concurrency stress test: 20 worker threads concurrently writing events to `observability.sqlite3`. | `AC-SQAO-009` | Zero `OperationalError: database is locked` exceptions due to WAL and busy timeout. |
| SCEN-010 | `test_observability_redaction.py` | Canary redaction test: insert canary credentials (`DEMO_PASSWORD_CANARY`, `1234`). | `AC-SQAO-010` | Full database text search verifies 0 occurrences of secret strings in any table. |
| SCEN-011 | `test_sqlite_event_observer.py` | Inject simulated SQLite write failure into observer. | `AC-SQAO-011` | Event bus records diagnostic; agent execution finishes without exception. |
| SCEN-012 | Documentation Inspection | Verify `examples/smart_quote_agent/README.md` completeness. | `AC-SQAO-012` | Walkthrough transcripts, setup instructions, and architecture narrative present. |
| SCEN-013 | Static Analysis | Run `mypy --strict`, `ruff check`, and `ruff format --check`. | `AC-SQAO-013` | 0 type errors, 0 lint warnings, 100% formatted. |
| SCEN-014 | Repository Cleanliness | Run `git status --short`. | `AC-SQAO-014` | Zero modifications outside `examples/smart_quote_agent/*`. |

---

## Live Demonstration Verification Scenario

### Prerequisites
```powershell
python examples/smart_quote_agent/init_demo.py --reset
python examples/smart_quote_agent/init_observability.py --reset
```

### Steps

1. **Terminal 1**: Start agent application:
   ```powershell
   python examples/smart_quote_agent/app.py
   ```
2. **Terminal 1**: Ask for products:
   ```text
   > what products do you have?
   ```
3. **Terminal 2**: Inspect recent invocations:
   ```powershell
   python examples/smart_quote_agent/inspect_observability.py
   ```
   *Expected*: Lists invocation #1 with duration and status `completed`.
4. **Terminal 2**: Inspect detailed breakdown:
   ```powershell
   python examples/smart_quote_agent/inspect_observability.py --last
   ```
   *Expected*: Shows runtime events (`list_products`), LangSmith tree, OTel span, and aggregate metrics.
5. **Terminal 1**: Sign in as staff:
   ```text
   > login
   Username: alice
   Password: [masked]
   ```
6. **Terminal 2**: Inspect last invocation:
   ```powershell
   python examples/smart_quote_agent/inspect_observability.py --last
   ```
   *Expected*: Informs user that login was handled host-side and re-displays invocation #1.
7. **Terminal 1**: Create a quote:
   ```text
   [alice] > create quote for Acme Corp with 2 Standard Widgets
   Discount % (0-30) [0]: 10
   Approve persistence? [y/N]: y
   ```
8. **Terminal 2**: Inspect latest invocation and tool execution:
   ```powershell
   python examples/smart_quote_agent/inspect_observability.py --last
   ```
   *Expected*: Shows structured planner invocation and direct `create_quote` tool executor event group with approval resolution.

---

## Verification Evidence Log

| Date | Task / Scenario | Command / Test Executed | Output / Evidence | Status |
|---|---|---|---|---|
| 2026-09-16 | `SQAO-TASK-0001` / `SCEN-001` | `uv run pytest examples/smart_quote_agent/tests/test_telemetry_db.py -k test_schema` | `1 passed in 0.05s`: 5 tables and 10 indexes verified | Pass |
| 2026-09-16 | `SQAO-TASK-0002` / `SCEN-002` | `python examples/smart_quote_agent/init_observability.py --reset` | CLI reset completed, tables created, exit code 0 without starting Codex | Pass |
| 2026-09-16 | `SQAO-TASK-0003` / `SCEN-003` | `uv run pytest examples/smart_quote_agent/tests/test_sqlite_event_observer.py -k test_events` | `1 passed in 0.05s`: 3 events persisted, scalar fields extracted, order verified | Pass |
| 2026-09-16 | `SQAO-TASK-0004` / `SCEN-004` | `uv run pytest examples/smart_quote_agent/tests/test_recording_langsmith_client.py` | `2 passed in 0.29s`: create/update verified; runtime -> turn -> tool hierarchy reconstructed | Pass |
| 2026-09-16 | `SQAO-TASK-0005` / `SCEN-005` | `uv run pytest examples/smart_quote_agent/tests/test_sqlite_otel_exporters.py` | `2 passed in 0.40s`: direct provider exports and OpenTelemetryObserver spans/metrics verified | Pass |
| 2026-09-16 | `SQAO-TASK-0006` / `SCEN-006`, `SCEN-007`, `SCEN-011` | `uv run pytest examples/smart_quote_agent/tests/test_observability_wiring.py` | `3 passed in 1.23s`: factory modes (off/local/local+ls), quote creation host event_sink wiring, and failure isolation under strict=False | Pass |
| 2026-09-16 | `SQAO-TASK-0007` / `SCEN-008` | `uv run pytest examples/smart_quote_agent/tests/test_inspector_queries.py` | `5 passed in 0.35s`: summary tabular view, --last view, tree reconstruction, CLI flags, host-only disclaimers | Pass |
| 2026-09-16 | `SQAO-TASK-0001` / `SCEN-009` | `uv run pytest examples/smart_quote_agent/tests/test_telemetry_db.py -k test_concurrent_writes` | `1 passed in 0.35s`: 20 threads concurrent inserts with WAL mode, 0 errors | Pass |
| 2026-09-16 | `SQAO-TASK-0008` / `SCEN-010` | `uv run pytest examples/smart_quote_agent/tests/test_observability_redaction.py` | `3 passed in 2.98s`: zero credential/canary leakage across all 5 tables and 20-worker concurrent emission | Pass |
| 2026-09-16 | `SQAO-TASK-0009` / `SCEN-012` | Documentation Inspection | `examples/smart_quote_agent/README.md` verified with architecture narrative, database layout, setup instructions, and step-by-step dual-terminal transcripts | Pass |
| 2026-09-16 | `SQAO-TASK-0010` / `SCEN-013` | `uv run mypy examples/smart_quote_agent --strict`, `ruff check`, `ruff format --check` | 0 mypy errors across 23 source files, 0 lint warnings, 24 files formatted cleanly | Pass |
| 2026-09-16 | `SQAO-TASK-0010` / `SCEN-014` | `git status --short` | Zero files modified or created outside `examples/smart_quote_agent/*` and `docs/plans/active/example-smart-quote-agent-observability/` | Pass |

