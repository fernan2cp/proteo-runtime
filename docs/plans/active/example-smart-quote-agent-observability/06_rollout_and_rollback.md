# Rollout and Rollback — Smart Quote Agent: Observability & Telemetry

## Rollout Strategy

Implementation proceeds in five strictly bounded, self-contained stages to ensure zero regression of Phase 1 functional agent capabilities:

### Stage 1: Telemetry Database Foundation
- Implement `telemetry_db.py` (connection management, WAL pragmas, 5-table DDL, typed record insert helpers).
- Implement `init_observability.py` (CLI database setup script with `--reset`).
- *Verification Gate*: Database creation and reset scripts execute cleanly.

### Stage 2: Observers, Exporters, and Local Recording
- Implement `SQLiteEventObserver` in `observability.py`.
- Implement `RecordingLangSmithClient` in `langsmith_recording.py`.
- Implement `SQLiteSpanExporter` and `SQLiteMetricExporter` in `otel_recording.py`.
- *Verification Gate*: Unit tests verify that projected events persist into all 5 tables with proper schema alignment and `{"id": run_id}` return values.

### Stage 3: Observability Factory & Host `event_sink` Wiring
- Implement `create_observability_config` in `observability.py`.
- Wire `create_quote` tool executor's `event_sink` parameter in `graph.py` to `bus.emit`.
- Wire `CodexRuntime(observability=...)` in `app.py`.
- *Verification Gate*: Existing 51 Phase 1 tests continue to pass; tool approval and execution events are captured.

### Stage 4: Standalone Inspection CLI
- Implement `inspect_observability.py` with default summary table, `--last`, filter flags, tree rendering, and host-only interaction disclaimer.
- *Verification Gate*: Inspector renders recent invocations and trees correctly against recorded test database.

### Stage 5: Test Suite Expansion & Documentation
- Implement test suite in `examples/smart_quote_agent/tests/` covering observers, redaction canaries, thread concurrency, and inspector queries.
- Update `examples/smart_quote_agent/README.md` with complete architecture overview and dual-terminal walkthrough.
- *Verification Gate*: `mypy --strict`, `ruff check`, `ruff format --check`, and all tests pass with 100% success.

---

## Blast-Radius Mitigation

1. **Strict Repository Directory Isolation**:
   - Every file created or edited is strictly contained within `examples/smart_quote_agent/*`.
   - No project-level files (`pyproject.toml`, `src/*`, root `tests/*`) are touched.
2. **Runtime Failure Isolation**:
   - `strict=False` on `ObservabilityConfig` guarantees that an observer failure or database lock error cannot crash inference or disrupt business quote persistence.
3. **Storage Isolation**:
   - Telemetry data resides strictly in `observability.sqlite3`. Business data in `demo.sqlite3` is never touched by telemetry operations.
4. **Environment Safety**:
   - `DEMO_OBSERVABILITY=off` completely disables observer bindings, restoring pure Phase 1 behavior.
   - Default `local` mode requires zero cloud credentials and performs zero network calls.

---

## Verification Gates

Prior to declaring this SDD plan ready for human closure:
- [ ] All 10 tasks in `03_task_plan.md` transitioned to `done` with recorded evidence.
- [ ] All 14 acceptance criteria in `04_acceptance_criteria.md` satisfied.
- [ ] All automated tests pass: `uv run pytest examples/smart_quote_agent/tests/ -v`.
- [ ] Type checking passes: `uv run mypy examples/smart_quote_agent --strict`.
- [ ] Code formatting and linting pass: `uv run ruff check examples/smart_quote_agent` and `uv run ruff format --check examples/smart_quote_agent`.
- [ ] `git status --short` confirms zero modifications outside `examples/smart_quote_agent/` and the active plan directory.
- [ ] **Mandatory Human Review Gate**: Present full validation evidence to the user and obtain explicit approval before moving the plan to `docs/plans/complete/`.

---

## Rollback Procedure

If unresolvable regressions or design defects are discovered:

1. **Immediate Runtime Mitigation**:
   - Disable telemetry via environment variable:
     ```powershell
     $env:DEMO_OBSERVABILITY = "off"
     ```
   - The agent immediately reverts to unobserved Phase 1 execution without code changes.

2. **Clean Codebase Revert**:
   - Discard uncommitted changes or revert feature commits within the examples directory:
     ```powershell
     git checkout main -- examples/smart_quote_agent/
     ```

3. **Telemetry Database Cleanup**:
   - Delete the transient telemetry database:
     ```powershell
     Remove-Item examples/smart_quote_agent/data/observability.sqlite3 -ErrorAction Ignore
     ```

4. **Post-Rollback Verification**:
   - Re-run the baseline test suite:
     ```powershell
     uv run pytest examples/smart_quote_agent/tests/test_agent.py -v
     ```
   - Verify that the 51 baseline tests pass cleanly.
