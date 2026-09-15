# Traceability — Phase 1

## Project Guide to Phase Requirements

| Source | Phase 1 requirements | Phase treatment |
|---|---|---|
| R-003, R-019 | P1-REQ-002, 006, 011 | Async LLM-like invocation and streaming |
| R-006, roadmap Phase 1/2 | P1-REQ-006–010 | Brain, reserved structured, advanced public sessions |
| R-007, R-027 | P1-REQ-003, 014–016 | Managed ChatGPT identity and secret-safe boundaries |
| R-011, R-012 | P1-REQ-001, 011, 015 | Neutral provider and event contracts |
| R-015, R-017, R-026 | P1-REQ-005, 007, 013 | Capability checks and fail-closed sandbox mapping |
| R-020, R-021 | P1-REQ-002, 008–011, 014 | Lifecycle, sessions, concurrency, and normalized errors |
| R-022 | P1-REQ-016 | No subscription quota in default tests |
| R-023, R-028, R-029 | P1-REQ-001, 017, 018 | Stable SDK boundary and isolated compatibility shim |
| R-024 | P1-REQ-012 | Provider-neutral usage accounting |

## Requirement Coverage

| Requirement | Tasks | Acceptance criteria | Planned validation |
|---|---|---|---|
| P1-REQ-001 | 0001, 0002, 0008 | AC-P1-002 | exports/import contracts |
| P1-REQ-002 | 0002, 0009 | AC-P1-003 | lifecycle unit + integration |
| P1-REQ-003 | 0003, 0009 | AC-P1-004–005 | account/redaction tests |
| P1-REQ-004 | 0003, 0009 | AC-P1-006 | catalog fixtures/smoke |
| P1-REQ-005 | 0003, 0009 | AC-P1-006–007 | resolution failure matrix |
| P1-REQ-006 | 0004, 0008, 0009 | AC-P1-008 | captured SDK calls/smoke |
| P1-REQ-007 | 0004, 0008 | AC-P1-009 | preflight rejection test |
| P1-REQ-008 | 0006, 0008, 0009 | AC-P1-011 | session create tests |
| P1-REQ-009 | 0006, 0008, 0009 | AC-P1-012 | descriptor/resume matrix |
| P1-REQ-010 | 0006, 0008, 0009 | AC-P1-013–015 | concurrency/lifecycle tests |
| P1-REQ-011 | 0005, 0007–0009 | AC-P1-016–017 | stream parity tests |
| P1-REQ-012 | 0005, 0008–0009 | AC-P1-018 | usage fixtures/smoke |
| P1-REQ-013 | 0004, 0008–0009 | AC-P1-010 | captured policy/temp-root tests |
| P1-REQ-014 | 0005, 0008–0009 | AC-P1-020–021 | error/cancel matrix |
| P1-REQ-015 | 0005, 0007–0009 | AC-P1-017, 019, 021 | event/raw/redaction tests |
| P1-REQ-016 | 0001, 0008–0010 | AC-P1-022–023 | quota guard + opt-in smoke |
| P1-REQ-017 | 0006, 0008–0009 | AC-P1-014 | typed shim unit/smoke |
| P1-REQ-018 | 0001, 0007, 0008, 0010 | AC-P1-001, 024 | quality/build/CI evidence |

Task numbers in this table abbreviate the `P1-TASK-` prefix.

## Acceptance Evidence Index

| Criteria | Evidence owner | Status |
|---|---|---|
| AC-P1-001 | baseline review and preserved worktree | Satisfied locally |
| AC-P1-002–003 | provider boundary, lifecycle and startup-failure tests | Satisfied locally |
| AC-P1-004–007 | auth, identity, catalog and effort tests | Satisfied locally |
| AC-P1-008–010 | brain input and sandbox policy tests | Satisfied locally |
| AC-P1-011–015 | session unit tests plus real create/turn/close/resume/archive/delete smoke | Satisfied locally and by opt-in integration |
| AC-P1-016–021 | runner, usage, terminal parity, error, cancellation and cleanup tests | Satisfied locally |
| AC-P1-022 | quota-safety contract plus default suite | Satisfied: 46 passed, 3 skipped |
| AC-P1-023 | explicit ChatGPT-backed smoke | Satisfied: 3 passed, 0 failed, 0 skipped |
| AC-P1-024 | local quality, 90.38% coverage, build, artifacts and docs; remote matrix | Satisfied: local gates plus [CI run 34932195741](https://github.com/fernan2cp/proteo-runtime/actions/runs/34932195741) passed all quality, Ubuntu/Windows 3.11–3.14, and packaging jobs |

## Change-Control Rule

Any change to public imports, the `prt1.` descriptor, model/default selection, authentication
mode, sandbox mapping, terminal stream result, SDK compatibility range, or the Phase 1/2
boundary must update requirements, tasks, acceptance criteria, and both matrices before merge.
