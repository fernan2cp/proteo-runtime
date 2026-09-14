# Traceability — Phase 0

The matrix below distinguishes what Phase 0 implements from what it only constrains for later phases. A deferred requirement is not an acceptance gap; it is intentionally outside this phase.

| Project-guide source | Phase 0 requirement(s) | Task(s) | Acceptance / validation | Phase 0 status |
|---|---|---|---|---|
| R-001 Installable library | P0-REQ-001, P0-REQ-011 | 0002, 0009 | AC-P0-003–005 | Implemented |
| R-002 Framework-agnostic core | P0-REQ-003 | 0003, 0010 | AC-P0-006–007 | Implemented |
| R-004 Strict versioned configuration | P0-REQ-006, P0-REQ-017 | 0006 | AC-P0-015–017 | Schema only; loading/resolution deferred |
| R-005 Logical reasoning levels | P0-REQ-006 | 0006 | AC-P0-015–017 | Vocabulary/schema only; mappings deferred |
| R-006 Execution profiles | P0-REQ-005 | 0004 | AC-P0-012 | Vocabulary/default specifications implemented |
| R-009 Context ownership | P0-REQ-005, P0-REQ-009 | 0004, 0007 | AC-P0-012, AC-P0-020 | Contract only; runtime enforcement deferred |
| R-011 Observability-neutral core | P0-REQ-008 | 0004, 0008 | AC-P0-021–023 | Event contract only; exporters deferred |
| R-012 Runtime abstraction | P0-REQ-004 | 0004 | AC-P0-008, AC-P0-011 | Implemented as protocols |
| R-013 MIT license | P0-REQ-012 | 0002 | AC-P0-004 | Implemented |
| R-016 Security profiles | P0-REQ-005, P0-REQ-017 | 0004 | AC-P0-012, AC-P0-020 | Vocabulary/fail-closed contract; enforcement deferred |
| R-017 Capability discovery | P0-REQ-004, P0-REQ-008 | 0004, 0008 | AC-P0-008, AC-P0-022 | Neutral/provider capability values implemented |
| R-019 Async-first | P0-REQ-013 | 0004, 0008 | AC-P0-011, AC-P0-023 | Implemented in contracts/fakes |
| R-020 Lifecycle management | P0-REQ-004, P0-REQ-009, P0-REQ-010 | 0004, 0007, 0008 | AC-P0-018–024 | Fake lifecycle implemented; provider lifecycle deferred |
| R-021 Stable error model | P0-REQ-007 | 0005, 0008 | AC-P0-013–014, AC-P0-025 | Implemented |
| R-022 No quota in tests | P0-REQ-015 | 0008, 0010 | AC-P0-027; quota-safety checks | Implemented |
| R-023 Compatibility isolation | P0-REQ-002, P0-REQ-003 | 0002, 0003, 0010 | AC-P0-006–007, AC-P0-027 | Dependency/boundary only; provider implementation deferred |
| R-024 Usage accounting | P0-REQ-008 | 0004, 0008 | AC-P0-022–023 | Neutral model implemented |
| R-026 Security before convenience | P0-REQ-005, P0-REQ-009 | 0004, 0007 | AC-P0-012, AC-P0-020 | Contract guardrails implemented |
| R-027 No hidden secrets | P0-REQ-007, P0-REQ-009, P0-REQ-014 | 0005, 0006, 0007 | AC-P0-014, AC-P0-019–020 | Implemented in validation/contracts |
| R-028 Public API stability | P0-REQ-004, P0-REQ-011, P0-REQ-017 | 0003, 0004, 0009, 0011 | AC-P0-008, AC-P0-026, AC-P0-030 | Initial API explicitly documented |
| R-003, R-007, R-008, R-010, R-014, R-015, R-018, R-025, R-029 | P0-REQ-017 | 0001, 0011 | AC-P0-026, AC-P0-030 | Deferred to roadmap phases |

## Requirement-to-Test Index

| Test area | Requirements | Criteria |
|---|---|---|
| Packaging/install/CLI | P0-REQ-001, 002, 011, 012 | AC-P0-003–005, 026 |
| Import boundaries | P0-REQ-003, 017 | AC-P0-006–007 |
| Core values/protocols | P0-REQ-004, 005, 008, 013, 014 | AC-P0-008–012 |
| Error safety | P0-REQ-007, 014 | AC-P0-013–014 |
| Configuration schema | P0-REQ-006, 017 | AC-P0-015–017 |
| Session codec | P0-REQ-009, 014 | AC-P0-018–020 |
| Fake runtime | P0-REQ-010, 015 | AC-P0-021–025, 027 |
| Quality/CI | P0-REQ-012, 016, 017 | AC-P0-028–030 |

## Change-Control Rule

Any implementation change that alters a public symbol, profile name, error inheritance, session prefix/encoding, configuration version, or dependency boundary must update this matrix and the affected requirements/acceptance criteria before merge.
