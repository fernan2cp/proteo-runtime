# Task Plan — Phase 1

## Conventions

States are `pending`, `in_progress`, `done`, or `blocked`. A task becomes `done` only after its
evidence is recorded in `05_validation_plan.md` and `07_traceability.md`.

### P1-TASK-0001 — Reconfirm baseline and SDK contract

**State:** `pending`  
**Depends on:** none  
**Requirements:** P1-REQ-001, P1-REQ-016, P1-REQ-018  
**Acceptance:** AC-P1-001, AC-P1-022, AC-P1-024

Recheck status, versions, generated SDK types, public methods, current tests, and documentation
drift. Record deviations before implementation.

### P1-TASK-0002 — Establish provider boundary and lifecycle

**State:** `pending`  
**Depends on:** P1-TASK-0001  
**Requirements:** P1-REQ-001, P1-REQ-002  
**Acceptance:** AC-P1-002, AC-P1-003

Create the Codex package, intentional export, injectable internal SDK boundary, idempotent
lifecycle, context management, state guards, and resource cleanup.

### P1-TASK-0003 — Implement authentication, identity, and model catalog

**State:** `pending`  
**Depends on:** P1-TASK-0002  
**Requirements:** P1-REQ-003, P1-REQ-004, P1-REQ-005  
**Acceptance:** AC-P1-004 through AC-P1-007

Validate ChatGPT-managed auth, generate safe identity metadata, map model entries, resolve one
default, and validate explicit model/effort choices without fallback.

### P1-TASK-0004 — Implement input mapping and secure model facade

**State:** `pending`  
**Depends on:** P1-TASK-0003  
**Requirements:** P1-REQ-006, P1-REQ-007, P1-REQ-013  
**Acceptance:** AC-P1-008 through AC-P1-010

Implement deterministic transcript conversion, ephemeral brain threads, reserved structured
behavior, temporary workspace ownership, deny-all approvals, and read-only sandbox mapping.

### P1-TASK-0005 — Implement shared turn runner

**State:** `pending`  
**Depends on:** P1-TASK-0004  
**Requirements:** P1-REQ-011, P1-REQ-012, P1-REQ-014, P1-REQ-015  
**Acceptance:** AC-P1-016 through AC-P1-021

Map notifications, final results, usage, raw snapshots, errors, timeout/cancellation, stream
abandonment, and unhealthy transport cleanup through one runner.

### P1-TASK-0006 — Implement persistent sessions

**State:** `pending`  
**Depends on:** P1-TASK-0003, P1-TASK-0005  
**Requirements:** P1-REQ-008, P1-REQ-009, P1-REQ-010, P1-REQ-017  
**Acceptance:** AC-P1-011 through AC-P1-015

Implement persistent start/resume, frozen descriptor validation, shared concurrency guards,
user-only input, close/archive/delete semantics, private delete shim, and explicit migration
rejection.

### P1-TASK-0007 — Complete neutral event contract and fakes

**State:** `pending`  
**Depends on:** P1-TASK-0005, P1-TASK-0006  
**Requirements:** P1-REQ-011, P1-REQ-015, P1-REQ-018  
**Acceptance:** AC-P1-017, AC-P1-021, AC-P1-024

Add terminal results and session lifecycle kinds, update fakes and public contract tests, and
preserve provider-free core imports.

### P1-TASK-0008 — Add quota-safe unit and contract coverage

**State:** `pending`  
**Depends on:** P1-TASK-0002 through P1-TASK-0007  
**Requirements:** P1-REQ-001 through P1-REQ-018  
**Acceptance:** AC-P1-002 through AC-P1-022, AC-P1-024

Add injected SDK doubles and tests for all mappings, lifecycles, failures, cleanup, concurrency,
compatibility, exports, and quota-safety guards.

### P1-TASK-0009 — Add opt-in integration validation

**State:** `pending`  
**Depends on:** P1-TASK-0008  
**Requirements:** P1-REQ-002 through P1-REQ-006, P1-REQ-008 through P1-REQ-017  
**Acceptance:** AC-P1-003 through AC-P1-008, AC-P1-011 through AC-P1-023

Add environment-gated real-runtime tests for authentication/catalog, brain invoke, streaming,
session create/resume, archive/delete cleanup, and interruption where deterministic.

### P1-TASK-0010 — Document, version, validate, and hand off

**State:** `pending`  
**Depends on:** P1-TASK-0009  
**Requirements:** P1-REQ-016, P1-REQ-018  
**Acceptance:** AC-P1-022 through AC-P1-024

Update public documentation and examples, set version `0.2.0`, run every quality gate and OS
matrix, record evidence, reconcile traceability, and move the SDD only after full acceptance.

## Dependency Summary

```text
0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006 -> 0007 -> 0008 -> 0009 -> 0010
                         \--------------------/
```

## Implementation Evidence

Pending. Evidence must identify commands, environments, test counts, integration account mode
without PII, and CI run URLs.
