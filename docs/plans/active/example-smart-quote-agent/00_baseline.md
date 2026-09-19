# Baseline — Smart Quote Agent Example

## Current Repository State

- **Baseline Version**: Proteo Runtime `0.6.0` (commit `2976eb2`).
- **Phase Completion**: Phases 0–5 are complete, fully tested, and documented in `docs/plans/complete/`:
  - Phase 0: Repository & Architectural Foundation.
  - Phase 1: Codex Core Runtime.
  - Phase 2: Model Resolution, Structured Output & Context.
  - Phase 2.1: Cross-Phase Conformance Hardening.
  - Phase 3: LangGraph Integration (`RuntimeNode`).
  - Phase 4: Observability, LangSmith & OpenTelemetry (metadata-only payload mode).
  - Phase 5: Host-Managed Tools (`runtime_tool`, `ToolRegistry`, `ToolExecutor`, `ToolPermissionPolicy`, `ApprovalHandler`).
- **Local Environment**: Windows OS, Python 3.12+, managed with `uv`.
- **Existing Contracts Utilized**:
  - `proteo_runtime.core.runtime.Runtime`
  - `proteo_runtime.core.model.RuntimeModel`, `RuntimeResult`, `InvocationConfig`
  - `proteo_runtime.integrations.langgraph.RuntimeNode`
  - `proteo_runtime.tools.runtime_tool`, `ToolRegistry`, `ToolExecutor`, `ToolPermissionPolicy`, `ApprovalHandler`, `ApprovalRequirement`, `ApprovalDecision`, `SideEffect`, `ToolRequest`, `ToolResult`
  - `proteo_runtime.observability.ObservabilityConfig`, `ObserverBinding`, `PayloadMode`
  - `proteo_runtime.providers.codex.CodexRuntime`

## Constraints & Boundary Conditions

1. **Bounded Example Changes and SDD Exception**:
   - Example product code, tests, scripts, local data, and documentation may change only inside `examples/smart_quote_agent/`.
   - The already-active SDD may be updated only inside `docs/plans/active/example-smart-quote-agent/` because the implementation request explicitly authorizes that documentation work.
   - The current approved provider-hardening expansion additionally permits only `src/proteo_runtime/providers/codex/_structured.py`, `src/proteo_runtime/providers/codex/_runner.py`, `tests/unit/test_codex_structured.py`, and `tests/unit/test_codex_provider.py` outside the example/SDD packages.
   - No other changes are authorized in `src/` or repository tests; configuration files, public Proteo Runtime APIs, and the business database schema remain out of scope.
   - Pre-existing user modifications in the working tree are baseline state, not evidence of changes made by this implementation.
   - All code, scripts, local example data, and example documentation reside inside:
     ```text
     examples/smart_quote_agent/
     ```
2. **Standard Library SQLite**:
   - The example must use Python's built-in `sqlite3` module. No external database drivers, ORMs, or migration tools are allowed.
   - SQLite foreign keys must be explicitly enabled on every connection (`PRAGMA foreign_keys = ON;`).
3. **Typing and Code Quality**:
   - Python 3.12+ syntax and PEP 604 union types (e.g. `A | B` instead of `Union[A, B]` or tuple in `isinstance`).
   - Strict static type checking (`mypy --strict`).
   - Full conformance with repository linting and formatting rules (`ruff check`, `ruff format`).
   - English docstrings for every class, function, and method formatted according to the Google Python Style Guide.
4. **Quota and Network Safety**:
   - Automated tests and verification scripts must not invoke external LLM network endpoints or consume API quota unless explicitly instructed with an opt-in environment flag.
   - Local validation scenarios may utilize fakes, direct module execution, or mock inputs.

## Provider Failure Diagnostic Baseline (2026-09-19)

- Codex login succeeded; startup resolved the requested model and returned the available model catalog. A minimal structured inference completed, and account usage was not at its limit.
- A differential live schema probe failed with provider code `other` when given the production `TurnDecision` schema containing `oneOf`; the equivalent provider schema using `anyOf` with no `discriminator` completed.
- The failure was therefore isolated to the provider-facing structured schema path. The previous runtime diagnostic did not retain the provider code/status, and the structured wrapper withheld buffered terminal failure events, leaving only a started invocation in the local event database.
- These observations are the baseline for `SQA-REQ-020`; they do not establish a general Codex authentication, model-access, or quota outage.

## Closed Architectural Decisions

1. **Host-Owned Execution Authority**:
   - The model never decides what it is permitted to do, what prices apply, what discounts are granted, or whether an action is committed to persistent storage. The host retains total authority over authorization, calculation, and database writes.
2. **Hybrid Orchestration Architecture**:
   - **Agentic Flow**: Open-ended catalog questions, product discovery, and price inquiries route to a controlled agent bound with read-only tools.
   - **Deterministic Flow**: Privileged operations (login, logout, quote creation, customer resolution, discount HITL, and persistence approval) execute through deterministic LangGraph workflow nodes.
3. **Dual-Layer Authorization**:
   - Layer 1: LangGraph state guard verifies the authenticated user role before entering the quote creation workflow.
   - Layer 2: Phase 5 `ToolPermissionPolicy` enforces capability allow-lists (`catalog.read`, `quote.calculate`, `customer.read`, `quote.create`, `quote.read`) inside the `ToolExecutor`.
4. **Credential Isolation & Masking**:
   - Passwords must be collected interactively via `getpass.getpass()`, preventing terminal echo.
   - Raw passwords must be immediately discarded after SQLite validation and never written to LangGraph state, runtime inputs, tool arguments, telemetry events, diagnostics, or logs.
5. **Monetary Integrity**:
   - All persisted monetary fields use integer cents (e.g. `$1,200.00` is stored as `120000`).
   - Business calculations and user-facing formatting use Python's `Decimal` class with `ROUND_HALF_UP` rounding. Floating-point arithmetic for currency is strictly prohibited.
6. **Transactional Atomicity**:
   - Inserting a quote and its constituent line items must execute within a single SQLite transaction (`BEGIN ... COMMIT`).
   - Any failure or denial triggers an immediate `ROLLBACK`, guaranteeing that partial or orphaned quote records cannot exist.
7. **Observability Database Evolution**:
   - The local observability database may receive additive, idempotent SQLite migrations only; `demo.sqlite3` is not migrated or reset by this work.

## Gaps, Unknowns & Risks

| ID | Description | Impact | Planned Mitigation / Resolution |
|---|---|---|---|
| GAP-001 | Interactive terminal prompts (`getpass`, `input`) block automated test suites. | Medium | Provide modular functions that accept input abstractions or direct arguments, allowing headless testability while retaining interactive CLI execution in `app.py`. |
| GAP-002 | LangGraph `StateGraph` requires compile-time schema stability. | Low | Define explicit TypedDict schemas (`DemoState`) with well-typed Pydantic payload models in `models.py`. |
| GAP-003 | Live Codex LLM requires valid API credentials and internet connection. | Medium | CLI application gracefully detects missing credentials or provider errors and reports actionable guidance, while automated checks test the logic deterministically. |
| GAP-004 | Accidental project root or library pollution during example development. | High | Enforce pre-commit verification and git status checks confirming all new files are strictly inside `examples/smart_quote_agent/`. |
| GAP-005 | Earlier SDD text prohibits all documentation changes outside the example despite the current request to update this active SDD. | Medium | Permit only the active package update; leave all other docs and product/runtime sources unchanged and distinguish pre-existing worktree state from implementation changes. |
| GAP-006 | The REPL hides provider exceptions from the user, but neither assigns correlation before graph entry nor records a redacted host error; runtime events cannot be joined to one CLI interaction. | High | Add `SQA-REQ-019`: correlate every turn before graph entry, persist a redacted `host.turn_error`, and expose an interaction inspector without changing runtime APIs or business data. |

## Diagnostic Hardening Task Baseline (2026-09-19)

- `app.py::_run_repl_loop` catches graph exceptions and prints a localized generic message, but does not persist error type, phase, code, or frames.
- `graph.py::intent_router_node` creates `interaction_id` after its structured intent-router call, so that first runtime invocation cannot be correlated to the host transition/error.
- `runtime_events` has `task_id` but no dedicated `interaction_id` column/index; interaction identifiers exist only in selected host metadata.
- `inspect_observability.py` supports `--last`, `--task`, and `--workflow`, but cannot combine an incomplete runtime invocation with its host-side exception.
- Live provider startup and the business database were not changed as part of this baseline capture. The business database must not be reset for diagnostic validation.
