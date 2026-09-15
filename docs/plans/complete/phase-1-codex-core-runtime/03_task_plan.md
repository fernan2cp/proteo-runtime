# Task Plan — Phase 1

States are `pending`, `in_progress`, `done`, or `blocked`. A task is `done` only when its local
evidence is recorded in `05_validation_plan.md` and `07_traceability.md`.

### P1-TASK-0001 — Reconfirm baseline and SDK contract

**State:** `done`
**Depends on:** none
**Requirements:** P1-REQ-001, P1-REQ-016, P1-REQ-018
**Acceptance:** AC-P1-001, AC-P1-022, AC-P1-024

Baseline and the pinned `openai-codex>=0.147,<0.148` SDK contract were recorded in `00_baseline.md`.

### P1-TASK-0002 — Establish provider boundary and lifecycle

**State:** `done`
**Depends on:** P1-TASK-0001
**Requirements:** P1-REQ-001, P1-REQ-002
**Acceptance:** AC-P1-002, AC-P1-003

Implemented `proteo_runtime.providers.codex.CodexRuntime`, an injectable SDK factory, explicit
start/close, async context management, and temporary workspace cleanup.

### P1-TASK-0003 — Implement authentication, identity, and model catalog

**State:** `done`
**Depends on:** P1-TASK-0002
**Requirements:** P1-REQ-003, P1-REQ-004, P1-REQ-005
**Acceptance:** AC-P1-004 through AC-P1-007

ChatGPT-managed account validation, SHA-256 identity fingerprinting, catalog mapping, default
selection, and effort validation are covered by SDK doubles.

### P1-TASK-0004 — Implement input mapping and secure model facade

**State:** `done`
**Depends on:** P1-TASK-0003
**Requirements:** P1-REQ-006, P1-REQ-007, P1-REQ-013
**Acceptance:** AC-P1-008 through AC-P1-010

Brain turns use ephemeral threads, deterministic role transcripts, deny-all approval, read-only
sandbox, and empty temporary workspaces. Structured output is explicitly reserved for Phase 2.

### P1-TASK-0005 — Implement shared turn runner

**State:** `done`
**Depends on:** P1-TASK-0004
**Requirements:** P1-REQ-011, P1-REQ-012, P1-REQ-014, P1-REQ-015
**Acceptance:** AC-P1-016 through AC-P1-021

`TurnRun` normalizes deltas, completed items, usage, terminal results, interruption, and sanitized
raw diagnostics for both invocation and streaming paths.

### P1-TASK-0006 — Implement persistent sessions

**State:** `done`
**Depends on:** P1-TASK-0003, P1-TASK-0005
**Requirements:** P1-REQ-008, P1-REQ-009, P1-REQ-010, P1-REQ-017
**Acceptance:** AC-P1-011 through AC-P1-015

Session create/resume, opaque `prt1.*` descriptors, user-only context policy, fail-fast locks,
close/archive/delete, and the isolated `thread/delete` shim are implemented. Migration remains a
capability rejection as planned.

### P1-TASK-0007 — Complete neutral event contract and fakes

**State:** `done`
**Depends on:** P1-TASK-0005, P1-TASK-0006
**Requirements:** P1-REQ-011, P1-REQ-015, P1-REQ-018
**Acceptance:** AC-P1-017, AC-P1-021, AC-P1-024

Terminal results and session lifecycle event kinds are present, and `FakeRuntime` preserves the
common lifecycle/streaming contract.

### P1-TASK-0008 — Add quota-safe unit and contract coverage

**State:** `done`
**Depends on:** P1-TASK-0002 through P1-TASK-0007
**Requirements:** P1-REQ-001 through P1-REQ-018
**Acceptance:** AC-P1-002 through AC-P1-022, AC-P1-024

The local suite uses injected SDK doubles; 46 tests pass and three opt-in integration tests are skipped by default. Coverage is 90.38% with branches enabled.

### P1-TASK-0009 — Add opt-in integration validation

**State:** `done`
**Depends on:** P1-TASK-0008
**Requirements:** P1-REQ-002 through P1-REQ-006, P1-REQ-008 through P1-REQ-017
**Acceptance:** AC-P1-003 through AC-P1-008, AC-P1-011 through AC-P1-023

The opt-in real run passed 3 integration tests covering catalog/brain, streaming, and persistent session cleanup; evidence is recorded in `05_validation_plan.md`.

### P1-TASK-0010 — Document, version, validate, and hand off

**State:** `done`
**Depends on:** P1-TASK-0009
**Requirements:** P1-REQ-016, P1-REQ-018
**Acceptance:** AC-P1-022 through AC-P1-024

README/version, local quality gates, 46 default tests, 90.38% branch-aware coverage, build, artifacts, and the real opt-in Codex smoke are evidenced. Remote CI run [34932338768](https://github.com/fernan2cp/proteo-runtime/actions/runs/34932338768) passed pre-commit, all Ubuntu/Windows Python 3.11–3.14 jobs, and packaging. The SDD has been moved to `docs/plans/complete/`.

## Dependency Summary

```text
0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006 -> 0007 -> 0008 -> 0009 -> 0010
                         \--------------------/
```
