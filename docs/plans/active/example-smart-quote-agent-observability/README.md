# SDD Example — Smart Quote Agent: Observability & Telemetry

## Purpose

This package defines the decision-complete Software Design Document (SDD) for implementing Phase 2 of the Smart Quote Agent example application inside `examples/smart_quote_agent/`.

Phase 1 established the functional agent (LangGraph orchestration, Codex model binding, structured planning, host-managed tools, login/logout HITL, staff/client authorization, and transactional SQLite quote persistence). Phase 2 augments this agent with full runtime observability and telemetry while strictly maintaining functional parity:
- Capturing the provider-neutral Proteo `RuntimeEvent` stream into a dedicated local SQLite telemetry database.
- Recording nested run hierarchies via the official Proteo `LangSmithObserver` using a lightweight local recording client (`RecordingLangSmithClient`).
- Recording distributed trace spans and low-cardinality aggregate metrics via the official Proteo `OpenTelemetryObserver` using local SQLite exporters (`SQLiteSpanExporter`, `SQLiteMetricExporter`).
- Providing a standalone, read-only inspection CLI (`inspect_observability.py`) to examine execution timelines, event sequences, LangSmith trees, and OTel spans without requiring cloud credentials or external collector infrastructure.
- Wiring host-side tools (specifically `create_quote`) through the public `ToolExecutor.event_sink` hook and `RuntimeEventBus.emit`.
- Enforcing content-safe observability via `PayloadMode.METADATA_ONLY` with absolute protection of passwords and sensitive application data.

## Source of Truth

The authoritative sources of truth for this design are:
- `docs/examples/smart_quote_agent/design/smart_quote_agent_observability_guide.md` (Domain observability architecture, telemetry database schema, recording contracts, and CLI inspection scenarios).
- `docs/design/project-guide.md` (Repository architectural source of truth, specifically §4, §9, §19, §21, §23, §24).
- `docs/examples/smart_quote_agent/design/smart_quote_agent_implementation_guide.md` (Underlying Phase 1 functional agent architecture).

## Documents

```text
00_baseline.md
    Current repository state, Phase 1 baseline, Proteo observability contracts, boundaries, and assumptions.

01_requirements.md
    Verifiable functional and non-functional requirements (SQAO-REQ-*).

02_technical_design.md
    Topology, SQLite telemetry schema, thread-safe connection management, observer adapters, event_sink wiring, and inspector algorithms.

03_task_plan.md
    Ordered, phased implementation tasks with dependencies and requirement links (SQAO-TASK-*).

04_acceptance_criteria.md
    Testable, binary acceptance criteria (AC-SQAO-*).

05_validation_plan.md
    Exact verification commands, automated test suites, concurrency tests, and demonstration scripts.

06_rollout_and_rollback.md
    Staged delivery phases, blast-radius containment within examples directory, and rollback procedures.

07_traceability.md
    Cross-reference matrices connecting design guide, requirements, tasks, criteria, and validation.
```

## Status and Lifecycle

Status: `active`.

- This package remains in `docs/plans/active/example-smart-quote-agent-observability/` throughout planning, implementation, and verification.
- **Mandatory Human Review Gate**: Before finalizing and moving this plan to `docs/plans/complete/`, explicit human review must be requested with full verification evidence.
- Once approved by the repository owner, the directory will be moved unchanged to `docs/plans/complete/example-smart-quote-agent-observability/`.

## Scope

### Included

- All files and code strictly confined within `examples/smart_quote_agent/*`:
  - `telemetry_db.py`: Dedicated SQLite connection management, WAL mode, bounded busy timeout, and DDL schema for 5 telemetry tables (`runtime_events`, `langsmith_runs`, `otel_spans`, `otel_span_events`, `otel_metrics`).
  - `init_observability.py`: Standalone CLI script for initializing and resetting (`--reset`) the telemetry database.
  - `observability.py`: `SQLiteEventObserver` (implementing `RuntimeObserver`), and the `create_observability_config` factory supporting `off`, `local`, and `local+langsmith` modes.
  - `langsmith_recording.py`: Local `RecordingLangSmithClient` duck-typed to satisfy `LangSmithObserver`, returning `{"id": run_id}` for hierarchical parent/child tracking.
  - `otel_recording.py`: Local `SQLiteSpanExporter` and `SQLiteMetricExporter` paired with OpenTelemetry SDK providers.
  - `inspect_observability.py`: Standalone, read-only inspection CLI with recent invocation summaries, detailed `--last` breakdown, and filters for `--invocation`, `--events`, `--langsmith`, and `--otel`.
  - `graph.py` & `app.py`: Connecting the host-side `create_quote` tool executor to `event_sink` via `RuntimeEventBus.emit`, and passing the observability configuration to `CodexRuntime`.
  - `examples/smart_quote_agent/tests/`: Comprehensive unit tests for observers, recording clients, exporters, thread safety, redaction canary guarantees, and inspector queries.
  - `examples/smart_quote_agent/README.md`: Updated user guide detailing the dual-terminal demonstration workflow and telemetry commands.

### Explicitly Excluded (Non-Scope & Strict Boundaries)

- **Zero Project Code Modifications**: Under no circumstances may any file outside `examples/smart_quote_agent/*` be created, modified, or touched (no changes to `src/*`, root `tests/*`, `pyproject.toml`, or configuration files).
- No modification of Proteo core contracts or private runtime internals (strictly zero calls to private `CodexRuntime._dispatch`).
- No replacement of LangSmith or OpenTelemetry backends with SQLite (SQLite is strictly a local demo sink for the existing Proteo observer projections).
- No synthetic `RuntimeEvent`s for host-only deterministic CLI interactions (help, login/logout, scope rejections, discount HITL, direct DB queries).
- No foreign key relationships or coupling between `demo.sqlite3` and `observability.sqlite3`.
- No cloud credentials or external infrastructure required for the default local mode.
- No web dashboards, server daemons, live streaming websockets, or log aggregation infrastructure.

## Traceability Rule

- Every task (`SQAO-TASK-*`) links to at least one requirement (`SQAO-REQ-*`) and one acceptance criterion (`AC-SQAO-*`).
- Every requirement (`SQAO-REQ-*`) maps to at least one task and one acceptance criterion.
- Every acceptance criterion (`AC-SQAO-*`) specifies concrete, reproducible verification evidence in `05_validation_plan.md`.
