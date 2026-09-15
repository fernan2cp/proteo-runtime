# Traceability — Phase 2

## Project Guide to Phase Requirements

| Source | Phase 2 requirements | Phase treatment |
|---|---|---|
| R-003, R-004 | P2-REQ-001–003, 005 | LLM-like configuration, precedence, and resolution |
| R-005, roadmap Phase 2 | P2-REQ-002–005 | Logical levels, explicit defaults, and no fallback |
| R-006, sections 9–10 | P2-REQ-004–005, 012–013, 018 | Built-in/custom profiles and context ownership |
| R-008, section 11 | P2-REQ-006–011 | Pydantic/JSON Schema, host validation, retries, raw policy |
| R-009 | P2-REQ-012–017 | Replay prevention, sessions, descriptors, and migration |
| R-012, R-017 | P2-REQ-005, 018 | Neutral contracts and effective capability checks |
| R-019, R-020 | P2-REQ-002, 009, 011, 014–016 | Async concurrency, lifecycle, streaming, and migration |
| R-021 | P2-REQ-001, 010, 016 | Stable normalized configuration/structure/session errors |
| R-022 | P2-REQ-019 | Quota-safe default tests and opt-in integration |
| R-023, R-028, R-029 | P2-REQ-005, 008, 018, 020 | Stable SDK boundary and intentional public API |
| R-026, R-027 | P2-REQ-004, 010, 013, 016, 018 | Safe defaults, permission monotonicity, and raw secrecy |

## Requirement Coverage

| Requirement | Tasks | Acceptance criteria | Planned validation |
|---|---|---|---|
| P2-REQ-001 | 0002, 0008 | AC-P2-002–003 | loader/source/error matrix |
| P2-REQ-002 | 0002–0003, 0008 | AC-P2-004–005 | immutability, precedence, concurrent calls |
| P2-REQ-003 | 0002–0003, 0008–0009 | AC-P2-006–007 | package data, catalog doubles/live check |
| P2-REQ-004 | 0002, 0008 | AC-P2-003–004, 008 | custom profile schema/cross-validation |
| P2-REQ-005 | 0002–0003, 0008 | AC-P2-007–009 | preflight and import-boundary tests |
| P2-REQ-006 | 0004, 0008 | AC-P2-010–011 | public policy and schema-kind tests |
| P2-REQ-007 | 0004, 0008 | AC-P2-011–013 | Pydantic/Draft 2020-12 validation matrix |
| P2-REQ-008 | 0004, 0008–0009 | AC-P2-012–013 | captured/live output-schema calls |
| P2-REQ-009 | 0005, 0008–0009 | AC-P2-014–016 | retry/thread/usage/failure tests |
| P2-REQ-010 | 0005, 0008 | AC-P2-018 | exhaustion and raw leak tests |
| P2-REQ-011 | 0005, 0008–0009 | AC-P2-015, 017 | buffered event sequence/live stream |
| P2-REQ-012 | 0006, 0008 | AC-P2-019–020 | context-policy captured-call matrix |
| P2-REQ-013 | 0003, 0006, 0008 | AC-P2-008, 020 | built-in/factory/capability tests |
| P2-REQ-014 | 0007–0009 | AC-P2-021 | create/resume mapping and smoke |
| P2-REQ-015 | 0007–0009 | AC-P2-023–024 | same-thread migration and failures |
| P2-REQ-016 | 0007–0009 | AC-P2-024–025 | migration safety/destructive-call assertions |
| P2-REQ-017 | 0007–0008 | AC-P2-022 | typing, exports, descriptor/redaction tests |
| P2-REQ-018 | 0003–0008 | AC-P2-008, 018, 026 | effective-capability/deferred-feature matrix |
| P2-REQ-019 | 0008–0010 | AC-P2-027 | quota guard and opt-in suite selection |
| P2-REQ-020 | 0001, 0008, 0010 | AC-P2-001, 028–029 | baseline, quality, CI, artifacts, docs |

Task numbers in this table abbreviate the `P2-TASK-` prefix.

## Acceptance Evidence Index

| Criteria | Evidence owner | Status |
|---|---|---|
| AC-P2-001 | baseline inspection and preserved worktree | Pending |
| AC-P2-002–004 | config loader/schema/immutability tests | Pending |
| AC-P2-005–009 | resolver, profile, concurrency, and import contracts | Pending |
| AC-P2-010–013 | policy/schema/provider/host validation tests | Pending |
| AC-P2-014–018 | retry, usage, stream, cleanup, and raw-leak tests | Pending |
| AC-P2-019–020 | external/runtime/hybrid context tests | Pending |
| AC-P2-021–026 | session, descriptor, migration, and capability tests | Pending |
| AC-P2-027 | quota contract plus explicitly authorized integration | Pending |
| AC-P2-028 | local quality, coverage, build, artifacts, and remote matrix | Pending |
| AC-P2-029 | public docs, version, traceability audit, and SDD move | Pending |

## Traceability Audit Procedure

Before closure, mechanically extract all `P2-REQ-*`, `P2-TASK-*`, and `AC-P2-*` identifiers and
verify:

- every task references at least one existing requirement and criterion;
- every requirement occurs in this matrix, at least one task, and at least one criterion;
- every criterion names existing requirements/tasks and has a validation/evidence owner;
- no implementation item remains pending or blocked;
- source-guide references still describe the implemented behavior.

## Change-Control Rule

Any change to configuration precedence/schema, packaged mappings, profile composition,
`StructuredOutputPolicy`, schema dialect, retry/stream semantics, raw handling, context replay,
session fingerprints/migration, public descriptor typing, dependency boundary, or Phase 2
exclusions must update requirements, tasks, acceptance criteria, validation, rollout, and both
traceability matrices before merge.
