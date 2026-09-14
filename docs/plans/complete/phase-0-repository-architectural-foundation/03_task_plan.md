# Task Plan — Phase 0

## Conventions

Task states are `pending`, `in_progress`, `done`, or `blocked`. A task may be marked `done` only with evidence listed in `05_validation_plan.md`. Every task names its requirement and acceptance-criteria links.

## Ordered Workstreams

### P0-TASK-0001 — Reconfirm repository baseline

**State:** `done`
**Depends on:** none
**Requirements:** P0-REQ-001, P0-REQ-017
**Acceptance:** AC-P0-001, AC-P0-002

Inspect the local worktree, existing files, Git status, Python/tool versions, and current design guide. Record any divergence from `00_baseline.md` before adding files. Do not overwrite unrelated user changes.

### P0-TASK-0002 — Establish package metadata and project tooling

**State:** `done`
**Depends on:** P0-TASK-0001
**Requirements:** P0-REQ-001, P0-REQ-002, P0-REQ-012, P0-REQ-016
**Acceptance:** AC-P0-003, AC-P0-004, AC-P0-005

Add `pyproject.toml`, Hatchling configuration, package metadata/version, base dependencies, `dev` extra, console script, `py.typed`, MIT license, README skeleton, Ruff/mypy/pytest configuration, pre-commit configuration, and the initial CI workflow.

### P0-TASK-0003 — Create dependency-safe package topology

**State:** `done`
**Depends on:** P0-TASK-0002
**Requirements:** P0-REQ-003, P0-REQ-011
**Acceptance:** AC-P0-006, AC-P0-007

Create the `core`, `config`, `testing`, `providers`, `integrations`, and `cli` namespaces from `02_technical_design.md`. Add only documented package initializers and ensure internal modules are not accidentally re-exported.

### P0-TASK-0004 — Implement neutral value objects and protocols

**State:** `done`
**Depends on:** P0-TASK-0003
**Requirements:** P0-REQ-004, P0-REQ-005, P0-REQ-008, P0-REQ-013, P0-REQ-014
**Acceptance:** AC-P0-008 through AC-P0-012

Implement the core dataclasses, enums, generics, `Protocol` contracts, normalization helpers, profile specifications, context/security policy vocabulary, capabilities, usage, identity, diagnostics, and event envelope. Add English Google-style docstrings to every function and method.

### P0-TASK-0005 — Implement public error hierarchy

**State:** `done`
**Depends on:** P0-TASK-0004
**Requirements:** P0-REQ-007, P0-REQ-014
**Acceptance:** AC-P0-013, AC-P0-014

Add every public error named by R-021, stable inheritance, safe contextual attributes, provider-cause chaining, and tests proving that secrets are not copied into messages or diagnostics.

### P0-TASK-0006 — Implement strict configuration schema models

**State:** `done`
**Depends on:** P0-TASK-0004, P0-TASK-0005
**Requirements:** P0-REQ-006, P0-REQ-017
**Acceptance:** AC-P0-015 through AC-P0-017

Implement immutable schema-version-1 Pydantic models, forbidden unknown keys, logical-level validation, and conversion to path-aware `ConfigurationError`. Explicitly document and test that loading, precedence, and production resolution are not part of Phase 0.

### P0-TASK-0007 — Implement `SessionCodec`

**State:** `done`
**Depends on:** P0-TASK-0004, P0-TASK-0005
**Requirements:** P0-REQ-009, P0-REQ-014
**Acceptance:** AC-P0-018 through AC-P0-020

Implement descriptor validation, canonical JSON encoding, `prt1.` framing, deterministic round trips, malformed/incompatible errors, and secret-field rejection. Keep authorization and provider-session checks outside the codec.

### P0-TASK-0008 — Implement deterministic fake runtime

**State:** `done`
**Depends on:** P0-TASK-0004, P0-TASK-0005, P0-TASK-0007
**Requirements:** P0-REQ-010, P0-REQ-015
**Acceptance:** AC-P0-021 through AC-P0-025

Implement fake runtime/model/session lifecycle, scripted results and streams, ordered events, usage, resumable session simulation, cancellation/interruption, injected failures, and single-active-turn enforcement. Add guards proving the fake cannot start Codex or access network/authentication.

### P0-TASK-0009 — Add CLI and public exports

**State:** `done`
**Depends on:** P0-TASK-0003, P0-TASK-0004
**Requirements:** P0-REQ-001, P0-REQ-011, P0-REQ-012
**Acceptance:** AC-P0-003, AC-P0-026

Implement `proteo-runtime --version`, `python -m proteo_runtime`, root exports, package metadata smoke checks, and README examples that use only the fake runtime or neutral contracts.

### P0-TASK-0010 — Add contract/unit tests and quality gates

**State:** `done`
**Depends on:** P0-TASK-0004 through P0-TASK-0009
**Requirements:** P0-REQ-003, P0-REQ-007 through P0-REQ-016
**Acceptance:** AC-P0-006 through AC-P0-030

Add unit tests, provider-neutral contract tests, import-boundary tests, quota-safety tests, and build/install checks. Run Ruff, mypy, pytest with coverage, import-linter, and the complete CI matrix.

### P0-TASK-0011 — Review, evidence, and phase handoff

**State:** `done`
**Depends on:** P0-TASK-0010
**Requirements:** P0-REQ-016, P0-REQ-017
**Acceptance:** AC-P0-029, AC-P0-030

Fill the validation evidence record, reconcile the traceability matrix, document any blocked or deferred item, perform a documentation/API review, and move the SDD directory to `docs/plans/complete/` only when all acceptance criteria are satisfied.

## Dependency Summary

```text
0001 → 0002 → 0003 → 0004 → 0005 → 0006
                         ├────────→ 0007 → 0008
                         └────────→ 0009
                         └────────→ 0010 → 0011
```
## Implementation Evidence

Local validation is green on Windows Python 3.11.4, 3.12.14, 3.13.15, and 3.14.7, and on clean Linux containers Python 3.11.14, 3.12.12, 3.13.11, and 3.14.2. Each matrix entry passed 29 tests with coverage above 91%, and each Linux entry completed wheel/sdist build and artifact inspection. Pre-commit, Ruff format/check, mypy, and import-linter passed locally; the isolated wheel and sdist installs both imported version 0.1.0 and exercised both CLI entrypoints.

P0-TASK-0010 and P0-TASK-0011 are `done`. Local validation and the required remote matrix, including packaging, passed in GitHub Actions run https://github.com/fernan2cp/proteo-runtime/actions/runs/34890854934.
