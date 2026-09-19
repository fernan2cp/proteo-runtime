# Task Plan — Smart Quote Agent Example

## Conventions

Task states are `pending`, `in_progress`, `done`, or `blocked`.
All tasks start in `pending`. A task may only transition to `done` when concrete test or verification evidence is recorded in `05_validation_plan.md`.

Strict Boundary Rule:
Product code, tests, scripts, and example docs may change inside `examples/smart_quote_agent/`. The explicit documentation exception is this existing active SDD package. The completed Codex provider hardening had a narrow additional implementation/test allowlist in `_structured.py`, `_runner.py`, `test_codex_structured.py`, and `test_codex_provider.py`; that prior exception does not expand the current latency task. The current latency implementation is limited to the example and this SDD. No `src/*`, repository tests, configuration, public runtime APIs, provider/model configuration, or business database schema may change. Pre-existing worktree changes must be preserved and must not be attributed to this plan.

---

## Ordered Workstreams

### SQA-TASK-0001 — Directory Layout and Data Placeholder

**State:** `done`
**Depends on:** none
**Requirements:** `SQA-REQ-001`
**Acceptance:** `AC-SQA-001`

- Create directory `examples/smart_quote_agent/data/` if not present.
- Place `examples/smart_quote_agent/data/.gitkeep` to maintain directory tracking without checking in transient SQLite files.
- Verify working tree boundaries: no modifications outside `examples/smart_quote_agent/`.
- Evidence: `examples/smart_quote_agent/data/.gitkeep` created; `git status --short` confirmed 0 files modified outside target.

---

### SQA-TASK-0002 — SQLite Schema, Query Helpers and Initialization Script

**State:** `done`
**Depends on:** `SQA-TASK-0001`
**Requirements:** `SQA-REQ-002`, `SQA-REQ-006`
**Acceptance:** `AC-SQA-002`, `AC-SQA-008`

- Implement `examples/smart_quote_agent/database.py`:
  - `get_db_path()`, `get_connection()` with `PRAGMA foreign_keys = ON;`.
  - DDL statements for `customers`, `users`, `products`, `quotes`, `quote_lines`.
  - Cents and Decimal conversion helpers (`cents_to_decimal`, `calculate_discount_amount`, `format_currency`).
  - Query functions: `find_customer_by_query`, `list_active_products`, `find_product_by_query`, `get_quote_by_id`, `list_recent_quotes`.
  - Transactional quote persistence `persist_quote_transactional` using a single transaction (`BEGIN ... COMMIT`) with rollback on error.
- Implement `examples/smart_quote_agent/init_demo.py`:
  - CLI argument parsing for `--reset`.
  - Database provisioning and seed execution (4 customers, 5 users with password `1234`, 6 active products).
  - Status printout displaying credentials and database location.
- Evidence: `database.py` and `init_demo.py` implemented; verified with `init_demo.py --reset`, table counts, constraint enforcement, and transactional rollback tests.

---

### SQA-TASK-0003 — Pydantic Structured Schemas and Graph State Types

**State:** `done`
**Depends on:** `SQA-TASK-0001`
**Requirements:** `SQA-REQ-003`, `SQA-REQ-012`
**Acceptance:** `AC-SQA-003`, `AC-SQA-011`

- Implement `examples/smart_quote_agent/models.py`:
  - `IntentDecision` structured output schema for intent routing (`login`, `logout`, `quote_create`, `agent_request`).
  - `RequestedItem` and `QuoteRequest` structured output schemas for quote extraction with strict field validations (`quantity > 0`, non-empty customer and items).
  - `AuthenticatedUser` dataclass with slots and immutability.
  - `QuoteLineDraft`, `QuoteDraft`, and `DemoState` typed dictionaries for LangGraph state management.
- Evidence: `models.py` implemented; verified with `mypy --strict`, ruff checks, and Pydantic validation unit tests.

---

### SQA-TASK-0004 — Host Authentication, Masked Input and Permission Policy Mapping

**State:** `done`
**Depends on:** `SQA-TASK-0002`, `SQA-TASK-0003`
**Requirements:** `SQA-REQ-004`, `SQA-REQ-005`
**Acceptance:** `AC-SQA-003`, `AC-SQA-004`, `AC-SQA-005`

- Implement `examples/smart_quote_agent/auth.py`:
  - `authenticate_user_interactive(conn)` using `getpass.getpass()` for password input.
  - Verification against `users` table; immediate password variable cleanup.
  - Returns `AuthenticatedUser` on success, `None` on invalid credentials.
  - `get_permission_policy_for_user(user)` mapping staff role to full permissions and client/anonymous to public read/calculate permissions.
- Evidence: `auth.py` implemented; verified with `mypy --strict`, ruff checks, and unit assertions on authentication, getpass masking, credential cleanup, and role permission policies.

---

### SQA-TASK-0005 — Host-Managed Tools and Tool Registry Factory

**State:** `done`
**Depends on:** `SQA-TASK-0002`, `SQA-TASK-0004`
**Requirements:** `SQA-REQ-005`, `SQA-REQ-006`
**Acceptance:** `AC-SQA-004`, `AC-SQA-005`, `AC-SQA-007`

- Implement `examples/smart_quote_agent/tools.py`:
  - Decorate all 7 tools with `@runtime_tool`:
    - `list_products`: `catalog.read`, `SideEffect.READ`.
    - `find_product`: `catalog.read`, `SideEffect.READ`.
    - `calculate_quote`: `quote.calculate`, `SideEffect.NONE`.
    - `find_customer`: `customer.read`, `SideEffect.READ`.
    - `create_quote`: `quote.create`, `SideEffect.WRITE`, approval required.
    - `list_quotes`: `quote.read`, `SideEffect.READ`.
    - `get_quote`: `quote.read`, `SideEffect.READ`.
  - `create_tool_registry(conn)` returning populated `ToolRegistry`.
  - `create_tool_executor(registry, user, approval_handler)` returning bound `ToolExecutor`.
- Evidence: `tools.py` implemented; verified with `mypy --strict`, ruff checks, and full ToolExecutor assertions confirming permission allow-lists, client denial, and staff creation.

---

### SQA-TASK-0006 — Human-In-The-Loop Discount Prompt and Approval Handler

**State:** `done`
**Depends on:** `SQA-TASK-0002`, `SQA-TASK-0003`
**Requirements:** `SQA-REQ-007`
**Acceptance:** `AC-SQA-006`, `AC-SQA-007`

- Implement `examples/smart_quote_agent/hitl.py`:
  - `prompt_discount_interactive(subtotal_cents)` prompting for whole percentage `0..30` (default 0), with validation and re-prompting.
  - `ConsoleApprovalHandler` implementing `ApprovalHandler` protocol: renders quote details, asks `Approve? [y/N]`, and returns `ApprovalDecision.ALLOW` or `ApprovalDecision.DENY`.
- Evidence: `hitl.py` implemented; verified with `mypy --strict`, ruff checks, and unit tests confirming discount prompt validation (0..30 bounds, re-prompt on invalid) and ConsoleApprovalHandler approve/deny logic.

---

### SQA-TASK-0007 — LangGraph Workflow Graph and Hybrid Execution Assembly

**State:** `done`
**Depends on:** `SQA-TASK-0003`, `SQA-TASK-0004`, `SQA-TASK-0005`, `SQA-TASK-0006`
**Requirements:** `SQA-REQ-008`, `SQA-REQ-010`
**Acceptance:** `AC-SQA-004`, `AC-SQA-005`, `AC-SQA-009`, `AC-SQA-010`

- Implement `examples/smart_quote_agent/graph.py`:
  - Build `StateGraph(DemoState)`.
  - Add nodes: `intent_router`, `login_hitl`, `clear_auth`, `quote_planner`, `auth_guard`, `resolve_quote_data`, `discount_hitl`, `create_quote_tool`, `controlled_agent`, `final_output`.
  - Connect conditional routing from `intent_router` to `login_hitl`, `clear_auth`, `auth_guard`, or `controlled_agent`.
  - Wire `auth_guard` rejection for non-staff directly to `final_output`.
  - Wire authorized quote path: `quote_planner` -> `resolve_quote_data` -> `discount_hitl` -> `create_quote_tool` -> `final_output`.
  - Compile the graph.
- Evidence: `graph.py` implemented; verified with `mypy --strict`, ruff checks, and end-to-end LangGraph StateGraph execution assertions covering anonymous catalog queries, anonymous denial, client denial, staff quote creation, and quote lookup.

---

### SQA-TASK-0008 — Interactive CLI Entrypoint and REPL Loop

**State:** `done`
**Depends on:** `SQA-TASK-0007`
**Requirements:** `SQA-REQ-009`, `SQA-REQ-010`
**Acceptance:** `AC-SQA-003`, `AC-SQA-009`, `AC-SQA-010`

- Implement `examples/smart_quote_agent/app.py`:
  - CLI banner, database auto-detection, and help text.
  - Main async REPL loop with mode indicators: `> ` vs `[role] > `.
  - Deterministic handling of `exit` and `quit`.
  - State preservation (`authenticated_user`) between conversational turns.
  - Metadata-only observer binding configuration.
- Evidence: `app.py` implemented; verified with `mypy --strict`, ruff checks, and automated scripted REPL session testing banner display, prompt mode formatting, query execution, and deterministic exit.

---

### SQA-TASK-0009 — Comprehensive Example Documentation and User Guide

**State:** `done`
**Depends on:** `SQA-TASK-0008`
**Requirements:** `SQA-REQ-011`
**Acceptance:** `AC-SQA-011`

- Implement `examples/smart_quote_agent/README.md`:
  - Architecture narrative and core principles.
  - Setup instructions and default credentials table.
  - 4 complete example interaction transcripts.
  - Security boundaries and limitations disclaimer.
- Evidence: `examples/smart_quote_agent/README.md` created with complete sections on architecture, credentials table, installation, CLI usage, 4 comprehensive scenario transcripts, and security boundaries.

---

### SQA-TASK-0010 — Static Analysis, Linting and Verification Execution

**State:** `done`
**Depends on:** `SQA-TASK-0009`
**Requirements:** `SQA-REQ-001`, `SQA-REQ-012`, `SQA-REQ-013`
**Acceptance:** `AC-SQA-001`, `AC-SQA-011`

- Run `uv run mypy examples/smart_quote_agent --strict`.
- Run `uv run ruff check examples/smart_quote_agent`.
- Run `uv run ruff format --check examples/smart_quote_agent`.
- Perform a baseline-aware changed-path review under the current `SQA-REQ-001` allowlist; preserve and report pre-existing user modifications.
- Record execution logs and evidence in `05_validation_plan.md`.
- Historical evidence: `mypy --strict`, `ruff check`, `ruff format --check`, and approval denial/allow tests passed for the original example implementation. The old zero-worktree-change assertion is superseded by bounded isolation in `SQA-REQ-001`; pre-existing user changes are not attributed to this plan.

---

### SQA-TASK-0011 — Conversational Failure Characterization and SDD Boundary Repair

**State:** `done`
**Depends on:** `SQA-TASK-0010`
**Requirements:** `SQA-REQ-001`, `SQA-REQ-014`, `SQA-REQ-015`
**Acceptance:** `AC-SQA-012`, `AC-SQA-013`

- Add provider-free regressions for customer/catalog interruptions, product correction, isolated quantity, successful continuation, ambiguous reference, and stale draft.
- Update this active SDD in place to record its documentation exception and preserve the then-current code-only example boundary.
- Record the initial transcript failure modes as concrete acceptance tests.
- Evidence: targeted command `python -m pytest examples/smart_quote_agent/tests/test_agent.py -q` passed with 68 cases after transcript and ambiguity characterization; the active SDD boundary text now distinguishes authorized docs from pre-existing worktree changes.

---

### SQA-TASK-0012 — Quote Workflow Reducer and Revision-Bound Draft Lifecycle

**State:** `done`
**Depends on:** `SQA-TASK-0011`
**Requirements:** `SQA-REQ-014`, `SQA-REQ-015`
**Acceptance:** `AC-SQA-013`, `AC-SQA-014`

- Introduce `QuoteWorkflowState`, stable line IDs, revision/phase, customer and per-line resolution state.
- Reduce validated `QuotePatch` operations without replacing unrelated lines; preserve quantity for product replacement and merge canonical duplicate product lines in the draft.
- Clear stale drafts before planning and check draft workflow/revision before discount review and persistence.
- Clear all workflow references on cancellation, logout, identity change, approval denial, success, and terminal persistence failure.
- Evidence: reducer, transcript, terminal-cleanup, failed-resolution, and direct stale-before-discount/approval regressions pass in the 137-pass full suite; strict mypy and Ruff checks pass.

---

### SQA-TASK-0013 — Contextual Routing, Interruption, Clarification, and Language

**State:** `done`
**Depends on:** `SQA-TASK-0012`
**Requirements:** `SQA-REQ-006`, `SQA-REQ-015`, `SQA-REQ-017`
**Acceptance:** `AC-SQA-012`, `AC-SQA-013`, `AC-SQA-016`, `AC-SQA-018`

- Prioritize deterministic cancel/logout and explicit read-only intent while collecting a quote.
- Feed one context-aware `TurnDecision` and optional patch into the reducer; avoid a second structured extraction when a validated patch is available.
- Keep ambiguous references and multi-target quantities as no-op clarifications.
- Preserve Spanish/English across short replies and append a localized next-step reminder after read-only interruption.
- Provide deterministic offline previews through `calculate_quote`; reject partial previews when any requested line is unresolved.
- Evidence: interruption, clarification, stable-language, CLI error localization, and offline preview regressions pass in the full suite; strict mypy and Ruff checks pass.

---

### SQA-TASK-0014 — Canonical Customer and Product Resolution

**State:** `done`
**Depends on:** `SQA-TASK-0012`
**Requirements:** `SQA-REQ-005`, `SQA-REQ-016`
**Acceptance:** `AC-SQA-015`, `AC-SQA-018`

- Add bounded staff-only `list_customers` under `customer.read`; keep targeted `find_customer`.
- Normalize case, accents, safe singular/plural forms and the mouse/mice/mouses alias.
- Resolve all quote lines and retain per-line candidates/errors; never infer desk → dock.
- Evidence: bounded directory authorization, accent/plural/alias matching, explicit ambiguity, SKU preview resolution, unknown-line rejection, and `desk` negative lookup pass in the full suite; strict mypy and Ruff checks pass.

---

### SQA-TASK-0015 — Task/Workflow Event Correlation and Inspector

**State:** `done`
**Depends on:** `SQA-TASK-0013`
**Requirements:** `SQA-REQ-018`
**Acceptance:** `AC-SQA-017`

- Add `task_id` to local `runtime_events` with an additive idempotent migration.
- Emit metadata-only host transition records for router, planner, resolution, stale draft, and persistence outcomes.
- Extend inspector with `--task` and `--workflow` views; show cleanup diagnostic codes and label cumulative metrics explicitly.
- Evidence: legacy-schema migration, task/workflow timeline, cleanup diagnostic display, and metadata-whitelist tests pass in the 137-pass full suite.

---

### SQA-TASK-0016 — User Guide, Final Verification, and Human Review Handoff

**State:** `in_progress`
**Depends on:** `SQA-TASK-0012`, `SQA-TASK-0013`, `SQA-TASK-0014`, `SQA-TASK-0015`, `SQA-TASK-0017`, `SQA-TASK-0018`, `SQA-TASK-0019`, `SQA-TASK-0020`, `SQA-TASK-0021`
**Requirements:** `SQA-REQ-001`, `SQA-REQ-006`, `SQA-REQ-011`, `SQA-REQ-012`, `SQA-REQ-013`, `SQA-REQ-016`, `SQA-REQ-018`–`SQA-REQ-023`
**Acceptance:** `AC-SQA-001`, `AC-SQA-011`, `AC-SQA-012`–`AC-SQA-023`

- Update the example README with workflow state, interruptions, corrections, customer listing, and task/workflow inspection usage.
- Document the new latency inspector, one-call quote decision behavior, and cache-eligible prompt layout in the example README.
- Keep the active SDD open until the repository owner reviews the completed evidence and approves closure.
- Run targeted and full example tests, strict mypy, Ruff lint/format, and bounded worktree review.
- Preserve the completed post-fix Globex live evidence already recorded below; run the new latency session with the ambiguous Notebook Pro/Wireless Mouse request and inspect its review, but decline approval so no additional business quote is written. Never reset the user's business database.
- Keep this SDD active until evidence is complete and human review is requested; do not move it to `complete` automatically.
- Evidence: after the provider fix, 27 focused runtime provider/structured tests passed, the full example suite reported 143 passed / 2 skipped, and strict mypy, Ruff lint/format, and `git diff --check` passed. The live workflow created quote #8 for Globex with one USB-C Dock, two Wireless Mouse, zero discount, and USD 230; read-only database and completed-invocation evidence is in `05_validation_plan.md`. Human review and SDD closure remain pending, so this task stays `in_progress`.

---

### SQA-TASK-0018 — Codex Schema Adaptation and Terminal Failure Telemetry

**State:** `done`
**Depends on:** `SQA-TASK-0017`
**Requirements:** `SQA-REQ-001`, `SQA-REQ-019`, `SQA-REQ-020`
**Acceptance:** `AC-SQA-001`, `AC-SQA-019`, `AC-SQA-020`

- Adapt provider-facing structured schemas recursively by converting `oneOf` to `anyOf` and removing `discriminator`, while keeping original host-side Pydantic validation semantics.
- Preserve only safe Codex terminal error code/status metadata, and publish buffered terminal turn/invocation failure events exactly once before raising.
- Add focused tests in the specifically authorized runtime unit-test files; add or update the example inspector/tests as needed to verify correlated failure status and metadata redaction.
- Validate the full example suite, focused runtime suites, strict typing, Ruff, diff boundaries, and the requested live quote transcript. Do not approve a quote unless its review exactly matches the acceptance values.
- Evidence: 27 focused runtime provider/structured tests and the 143-passed/2-skipped example suite pass; strict mypy, Ruff lint/format, and `git diff --check` pass. The live `staff/1234` transcript completed with the exact accepted Globex quote and created quote #8 only, as verified by read-only database inspection and a `completed` inspector invocation. Details are recorded in `05_validation_plan.md`.

---

### SQA-TASK-0017 — Correlated Host Error Logging and Interaction Inspector

**State:** `done`
**Depends on:** `SQA-TASK-0015`
**Requirements:** `SQA-REQ-018`, `SQA-REQ-019`
**Acceptance:** `AC-SQA-017`, `AC-SQA-019`

- Assign a unique interaction ID in the REPL before graph entry and pass safe `InvocationConfig.metadata` to every structured-model and controlled-task call.
- Add `host.turn_error` persistence with bounded stage/code/type/cause fields and sanitized traceback frames; keep logging best effort and preserve the generic localized error message.
- Add nullable `runtime_events.interaction_id` and its index through an additive idempotent migration; correlate runtime and host rows in the read-only `--interaction` inspector and derive incomplete correlated failures as failed.
- Add tests for redaction, error codes/frames, invocation metadata, logger failure, migration idempotence, correlated failed/success inspector states, and REPL continuation.
- Execute the original live request twice after staff login, inspect each failed interaction, and verify no business quote was added when review was not reached.
- Evidence: all targeted tests and the full suite pass (142 passed, 2 skipped); strict mypy, Ruff, format, and diff checks pass. Both live attempts were recorded as `RuntimeUnavailableError` (`runtime_unavailable`) at `intent_router` with sanitized frames. Quote count remained 7; details are in `05_validation_plan.md`.

---

### SQA-TASK-0019 — Interaction Latency Events and Inspector Summary

**State:** `done`
**Depends on:** `SQA-TASK-0015`, `SQA-TASK-0017`, `SQA-TASK-0018`
**Requirements:** `SQA-REQ-018`, `SQA-REQ-019`, `SQA-REQ-021`
**Acceptance:** `AC-SQA-021`

- Instrument interaction, model-call, and discount HITL start/completion using the existing local telemetry event store and metadata-only payload policy. Add a per-call `call_id` through existing invocation metadata.
- Derive provider preparation, direct model-call or controlled-task invocation/terminal latency, TTFT, pre/post-tool intervals, actual tool duration, approval wait, discount wait, and token/cache summaries in the inspector. Mark tool-inclusive task spans rather than labeling them as pure inference time. Use only the latest usage snapshot for each invocation.
- Add `--latency` summary over the latest `--limit N` invocations, grouped by stage/model/profile with count, nearest-rank p50/p95, and weighted cache ratio. Keep the default limit at 10 and label incomplete calls separately.
- Do not add telemetry tables/columns/indexes/migrations or change public runtime APIs, provider code, or the business database schema.
- Add provider-free tests with controlled timestamps for tool cycles, HITL pauses, missing streaming deltas, incomplete calls, cumulative usage snapshots, redaction, and logger-failure isolation.
- Evidence: metadata-only interaction/model/discount events and call correlation are implemented. Tests cover exact timing derivation, 9.7-second approval versus 30-ms tool execution, TTFT/structured terminal, incomplete invocations, final usage snapshots, cache ratios, logger failure, interaction/task/workflow correlation, and exclusion of sibling model calls from per-invocation reports. The live task report separates 4.49-second controlled-agent runtime from its 13-ms tool, 3.54-second approval wait, and 3.90-second discount wait. See `05_validation_plan.md`.

### SQA-TASK-0020 — Stable Structured Prompt Prefixes

**State:** `done`
**Depends on:** `SQA-TASK-0018`
**Requirements:** `SQA-REQ-022`
**Acceptance:** `AC-SQA-022`

- Move structured decision rules into one constant system prompt with no dynamic identity, language, workflow, quote, candidate, or user-input values.
- Serialize those values and the current user input into compact UTF-8 JSON with recursively lexicographically sorted object keys, preserved array order, `ensure_ascii=False`, and separators `(',', ':')`; enforce the 16,384-byte dynamic payload cap without silent truncation or an LLM call on overflow.
- Keep controlled-agent task instructions stable at the prefix and append the sanitized identity role once as the final task-creation suffix. Preserve `ContextPolicy.RUNTIME` and do not replay host-side history.
- Add tests comparing system prompt and schema serialization byte-for-byte across initial/pending/edit contexts, checking JSON escaping and the payload bound, and confirming no cache hit is required for correctness.
- Evidence: the fixed system prompt and `TurnDecision` schema remain byte-identical across initial and pending contexts; dynamic JSON uses stable sorted compact UTF-8 serialization and rejects payloads above 16,384 bytes without truncation or model invocation. The live controlled-agent call reported 15,104/16,133 cached input tokens (94%); structured-router calls reported no cached input, which is acceptable because provider cache hits are not required. See `AC-SQA-022` and `05_validation_plan.md`.

### SQA-TASK-0021 — Single-Inference Classification and Quote Extraction

**State:** `done`
**Depends on:** `SQA-TASK-0019`, `SQA-TASK-0020`
**Requirements:** `SQA-REQ-003`, `SQA-REQ-015`, `SQA-REQ-023`
**Acceptance:** `AC-SQA-023`

- Extend `TurnDecision` with optional `quote_request` while retaining `quote_patch`, and validate the mutually exclusive payload/intention rules specified in `SQA-REQ-023`.
- Have the sole structured router inference return intent, language, and an initial/reformulated `QuoteRequest`, pending-workflow `QuotePatch`, or neither when quote details are absent.
- Convert `quote_planner` into a host-only workflow initializer/reducer and remove its separate `QuoteRequest` model invocation. Keep SQLite resolution, authorization, totals, discounts, approval, and persistence host-controlled.
- Do not add keyword/regex fast paths. Confirm the ambiguous baseline phrase still calls Codex exactly once and produces Notebook Pro quantity 1 plus Wireless Mouse quantity 2. Verify a full reformulation replaces a pending workflow with a fresh ID and invalidates its draft.
- Evidence: the ambiguous baseline phrase used one structured invocation (`5476ef0f7c314ec5baadf2e957190b14`, stage `intent_router`) and the host-only planner preserved Notebook Pro 1x and Wireless Mouse 2x. The first live attempt exposed a missing singular quantity; the fixed system prompt now explicitly maps singular articles to quantity 1, and the repeat reached the correct review without a quantity clarification. Persistence was declined. See `AC-SQA-023` and `05_validation_plan.md`.
