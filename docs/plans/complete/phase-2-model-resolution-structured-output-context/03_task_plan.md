# Task Plan — Phase 2

All tasks start as `pending`. A task changes to `done` only after its acceptance criteria have
recorded evidence in this package.

## Phase A — Baseline and Configuration

### P2-TASK-0001 — Reconfirm the implementation baseline

**State:** `done`

**Depends on:** none

**Requirements:** `P2-REQ-020`

**Acceptance:** `AC-P2-001`

**Actions:**

- record the starting commit, worktree state, package/lock versions, and default test count;
- re-inspect SDK schema signatures and the visible model/effort catalog without inference calls;
- record unrelated user changes and preserve them throughout implementation.

**Evidence:** Baseline reconfirmed on the implementation branch: worktree contained only the
new Phase 2 SDD, package version was `0.2.0`, and `.venv\\Scripts\\pytest.exe -q` reported
`46 passed, 3 skipped`.

### P2-TASK-0002 — Implement strict configuration loading and packaged defaults

**State:** `done`

**Depends on:** `P2-TASK-0001`

**Requirements:** `P2-REQ-001`, `P2-REQ-002`, `P2-REQ-003`, `P2-REQ-004`, `P2-REQ-005`

**Acceptance:** `AC-P2-002`, `AC-P2-003`, `AC-P2-004`, `AC-P2-005`, `AC-P2-006`,
`AC-P2-007`

**Actions:**

- extend schema v1 with immutable `ProfileConfig` and `profile_specs` validation;
- add UTF-8 JSON loading, source selection, normalized path-aware failures, and no implicit search;
- package the closed Codex v1 model matrix and load it with `importlib.resources`;
- extend `CodexRuntime` construction while preserving `default_model` compatibility;
- add focused loader, schema, immutability, package-data, and precedence tests.

**Evidence:** Implemented in `config/loader.py`, `config/models.py`, packaged
`config/defaults/codex_v1.json`, and `providers/codex/runtime.py`. The focused source and
precedence suite in `tests/unit/test_phase2_runtime.py` passes; `uv.lock` contains
`jsonschema==4.26.0` and its transitive validators; wheel and sdist checks confirm the defaults
are packaged.

### P2-TASK-0003 — Integrate immutable resolution and profile capability checks

**State:** `done`

**Depends on:** `P2-TASK-0002`

**Requirements:** `P2-REQ-002` through `P2-REQ-005`, `P2-REQ-013`, `P2-REQ-018`

**Acceptance:** `AC-P2-005`, `AC-P2-006`, `AC-P2-007`, `AC-P2-008`, `AC-P2-009`,
`AC-P2-018`

**Actions:**

- validate configured models and efforts against the complete visible startup catalog;
- resolve and freeze profile, level, model, effort, context, and security for each facade/session;
- merge invocation overrides without mutating shared state and add concurrent-call regression tests;
- correct `controlled_agent` context and enforce model/session lifecycle boundaries;
- reject deferred security/tool/native combinations before thread creation.

**Evidence:** Immutable binding, catalog validation, custom profile capability rejection, and
concurrency/override behavior pass in `tests/unit/test_codex_provider.py` and
`tests/unit/test_phase2_runtime.py`; `controlled_agent` is rejected before `thread_start`.

## Phase B — Structured Output

### P2-TASK-0004 — Implement schema normalization and typed validation

**State:** `done`

**Depends on:** `P2-TASK-0003`

**Requirements:** `P2-REQ-006`, `P2-REQ-007`, `P2-REQ-008`, `P2-REQ-018`

**Acceptance:** `AC-P2-010`, `AC-P2-011`, `AC-P2-012`, `AC-P2-013`

**Actions:**

- add/export `StructuredOutputPolicy` and the policy-aware protocol method;
- normalize immutable Pydantic and dictionary schemas and reject invalid inputs preflight;
- add `jsonschema>=4,<5`, lock it, and compile Draft 2020-12 validation;
- pass the normalized schema to the stable SDK API and validate exactly one JSON value locally;
- return Pydantic instances or JSON-compatible values in `RuntimeResult[T]`.

**Evidence:** `StructuredOutputPolicy`, schema normalization, Pydantic/Draft 2020-12 validation,
SDK `output_schema` capture, and typed results are covered by the phase-2 unit suite; the
real Codex structured smoke also passed after enforcing `additionalProperties: false`.

### P2-TASK-0005 — Implement validation retries and buffered structured streaming

**State:** `done`

**Depends on:** `P2-TASK-0004`

**Requirements:** `P2-REQ-009`, `P2-REQ-010`, `P2-REQ-011`

**Acceptance:** `AC-P2-014`, `AC-P2-015`, `AC-P2-016`, `AC-P2-017`, `AC-P2-018`

**Actions:**

- run structured attempts on one ephemeral thread/workspace with bounded safe feedback;
- aggregate usage and correlate attempts under one invocation with monotonic event sequencing;
- suppress partial JSON and per-attempt terminal invocation events from public streaming;
- add retry success/exhaustion, non-retry failure, timeout/cancellation, and cleanup tests;
- implement opt-in invalid-raw exposure with conservative redaction and leak tests.

**Evidence:** Unit tests cover retry success/exhaustion, bounded validation feedback, aggregated
usage, raw opt-in redaction, and buffered streaming with one logical invocation. Real Codex
structured Pydantic and JSON Schema streams passed under `PROTEO_CODEX_INTEGRATION=1`.

## Phase C — Context and Sessions

### P2-TASK-0006 — Enforce context ownership

**State:** `done`

**Depends on:** `P2-TASK-0003`

**Requirements:** `P2-REQ-012`, `P2-REQ-013`, `P2-REQ-018`

**Acceptance:** `AC-P2-008`, `AC-P2-019`, `AC-P2-020`

**Actions:**

- validate lifecycle/context combinations during profile resolution;
- preserve role-aware external context for ephemeral invocations;
- enforce user-only runtime sessions and current system/user hybrid sessions;
- reject assistant/tool replay before SDK access and cover each policy with captured calls.

**Evidence:** Runtime and hybrid role matrices, replay rejection, and controlled-agent context
correction pass in the provider and phase-2 unit suites.

### P2-TASK-0007 — Resolve, resume, and migrate persistent sessions

**State:** `done`

**Depends on:** `P2-TASK-0003`, `P2-TASK-0006`

**Requirements:** `P2-REQ-014`, `P2-REQ-015`, `P2-REQ-016`, `P2-REQ-017`,
`P2-REQ-018`

**Acceptance:** `AC-P2-021`, `AC-P2-022`, `AC-P2-023`, `AC-P2-024`, `AC-P2-025`,
`AC-P2-026`

**Actions:**

- align the opaque descriptor annotation and resolve session creation/resume by profile/level;
- add neutral `SESSION_MIGRATED` events and same-thread Codex migration;
- invalidate old in-process handles without adding an alias/revocation store;
- enforce active-turn, identity, provider, existence, target, and permission checks;
- preserve close/archive/delete, concurrency, interruption, and cleanup behavior.

**Evidence:** Session creation/resume, opaque `str` descriptors, same-thread migration, old-handle
generation invalidation, permission checks, and `SESSION_MIGRATED` are covered locally and by
the four-test real Codex integration run; only disposable test sessions were deleted.

## Phase D — Verification and Handoff

### P2-TASK-0008 — Complete fakes, unit tests, and contract tests

**State:** `done`

**Depends on:** `P2-TASK-0004` through `P2-TASK-0007`

**Requirements:** `P2-REQ-001`, `P2-REQ-002`, `P2-REQ-003`, `P2-REQ-004`,
`P2-REQ-005`, `P2-REQ-006`, `P2-REQ-007`, `P2-REQ-008`, `P2-REQ-009`,
`P2-REQ-010`, `P2-REQ-011`, `P2-REQ-012`, `P2-REQ-013`, `P2-REQ-014`,
`P2-REQ-015`, `P2-REQ-016`, `P2-REQ-017`, `P2-REQ-018`, `P2-REQ-019`,
`P2-REQ-020`

**Acceptance:** `AC-P2-002`, `AC-P2-003`, `AC-P2-004`, `AC-P2-005`, `AC-P2-006`,
`AC-P2-007`, `AC-P2-008`, `AC-P2-009`, `AC-P2-010`, `AC-P2-011`, `AC-P2-012`,
`AC-P2-013`, `AC-P2-014`, `AC-P2-015`, `AC-P2-016`, `AC-P2-017`, `AC-P2-018`,
`AC-P2-019`, `AC-P2-020`, `AC-P2-021`, `AC-P2-022`, `AC-P2-023`, `AC-P2-024`,
`AC-P2-025`, `AC-P2-026`, `AC-P2-027`, `AC-P2-028`

**Actions:**

- update fakes to mirror resolution, structured events/results, context, and migration;
- add focused unit and cross-provider contract matrices for every requirement;
- extend quota-safety guards to all configuration and structured paths;
- retain branch-aware coverage at or above 90 percent without blanket exclusions.

**Evidence:** Default `pytest -q` passes `60 passed, 4 skipped`; branch-aware coverage passes at
least 90% (`90.12%` in the final local run). Ruff, mypy, import-linter, and pre-commit all pass.

### P2-TASK-0009 — Run opt-in Codex integration validation

**State:** `done`

**Depends on:** `P2-TASK-0008`

**Requirements:** `P2-REQ-003`, `P2-REQ-008`, `P2-REQ-009`, `P2-REQ-010`,
`P2-REQ-011`, `P2-REQ-014`, `P2-REQ-015`, `P2-REQ-016`, `P2-REQ-019`

**Acceptance:** `AC-P2-006`, `AC-P2-012`, `AC-P2-015`, `AC-P2-017`, `AC-P2-021`,
`AC-P2-023`, `AC-P2-027`

**Actions:**

- require explicit quota authorization and an existing Codex-managed ChatGPT login;
- validate the packaged catalog matrix, structured Pydantic/JSON Schema calls, and buffered stream;
- migrate one disposable persistent thread and delete it only as planned test cleanup;
- record sanitized counts/IDs and failures without publishing identity, descriptors, or raw output.

**Evidence:** `PROTEO_CODEX_INTEGRATION=1 pytest -m integration tests/integration/codex -q` passes
`4 passed` on 2026-09-15. The run validated catalog, text/streaming, Pydantic/JSON Schema
structured output, and same-thread migration with disposable cleanup.

### P2-TASK-0010 — Document, version, validate, and hand off

**State:** `done`

**Depends on:** `P2-TASK-0009`

**Requirements:** `P2-REQ-019`, `P2-REQ-020`

**Acceptance:** `AC-P2-027`, `AC-P2-028`, `AC-P2-029`

**Actions:**

- update public configuration, structured-output, context, migration, security, and quota docs;
- set `0.3.0`, update dependency locks, and build/install wheel and sdist in isolation;
- run all local quality gates and the Linux/Windows Python 3.11–3.14 CI matrix;
- record evidence, audit traceability, mark completed tasks/criteria, and move this package to
  `docs/plans/complete/` without renaming it.

**Evidence:** Version `0.3.0`, README, CI artifact name, lockfile, isolated wheel/sdist installs,
and artifact inspection are complete locally. Workflow `34941152369` passed pre-commit, all
Linux/Windows Python 3.11–3.14 jobs, coverage, build, artifact, and isolated-install gates:
https://github.com/fernan2cp/proteo-runtime/actions/runs/34941152369.

## Dependency Summary

```text
0001 -> 0002 -> 0003 -> 0004 -> 0005 --\
                         \-> 0006 -> 0007 --+-> 0008 -> 0009 -> 0010
```
