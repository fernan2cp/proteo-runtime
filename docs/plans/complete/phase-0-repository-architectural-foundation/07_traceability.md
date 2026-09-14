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

## Acceptance-criterion evidence index

Each criterion has a concrete implementation or validation reference; all Phase 0 criteria are satisfied by local evidence and the successful remote workflow.

| Criterion | Implementation / validation evidence | Status |
|---|---|---|
| AC-P0-001 | `git status`, branch, baseline and SDD review recorded in `00_baseline.md` and this evidence. | Met locally |
| AC-P0-002 | Only documented format changes plus Phase 0 files appear in `git diff`; no unrelated files were overwritten. | Met locally |
| AC-P0-003 | Editable install and isolated wheel/sdist imports passed; package metadata is `proteo-runtime`. | Met locally |
| AC-P0-004 | `uv build` and `check_artifacts.py` passed for wheel and sdist. | Met locally |
| AC-P0-005 | Both CLI entrypoints returned `0.1.0` in isolated environments. | Met locally |
| AC-P0-006 | Reviewed topology in `02_technical_design.md`; reserved namespaces contain only initializers. | Met locally |
| AC-P0-007 | `uv run lint-imports` and `test_import_boundaries.py` passed. | Met locally |
| AC-P0-008 | Core protocol/value/error exports and exact root `__all__` contract passed. | Met locally |
| AC-P0-009 | `test_core.py` covers string normalization and arbitrary-object rejection. | Met locally |
| AC-P0-010 | Immutable value, policy, usage, identity, diagnostic, profile, and event tests passed. | Met locally |
| AC-P0-011 | `test_protocols.py` verifies async-first runtime/model/session protocols. | Met locally |
| AC-P0-012 | Profile/policy vocabulary and safe defaults are covered by core contract tests. | Met locally |
| AC-P0-013 | Complete documented error hierarchy test passed. | Met locally |
| AC-P0-014 | Error redaction and safe fake provider-like failure normalization tests passed. | Met locally |
| AC-P0-015 | Valid Pydantic schema v1 and immutable nested mapping test passed. | Met locally |
| AC-P0-016 | Unknown-key/version path errors test passed. | Met locally |
| AC-P0-017 | Invalid levels and missing mapping no-fallback test passed; loader remains deferred. | Met locally |
| AC-P0-018 | Deterministic `prt1.` SessionCodec round-trip test passed. | Met locally |
| AC-P0-019 | Malformed, unsupported, missing-field, and secret-field descriptor tests passed. | Met locally |
| AC-P0-020 | Codec contains only non-secret identity/configuration data and does not alter active policy. | Met locally |
| AC-P0-021 | Fake lifecycle/context-manager/idempotence and ordered-event tests passed. | Met locally |
| AC-P0-022 | Fake result, usage, diagnostics, profile, and correlation fields are tested. | Met locally |
| AC-P0-023 | Streaming order, `aclose`, cancellation, interruption, and lock release tests passed. | Met locally |
| AC-P0-024 | Session close/resume/archive/delete and atomic busy-turn behavior are tested. | Met locally |
| AC-P0-025 | Authentication/capability/timeout pass-through and raw-failure sanitization are tested. | Met locally |
| AC-P0-026 | README/CLI explicitly describe deferred real providers and integrations. | Met locally |
| AC-P0-027 | `test_quota_safety.py` guards imports, network, subprocess, auth paths, and secret environment reads. | Met locally |
| AC-P0-028 | Pre-commit, Ruff, and mypy passed with no hiding suppressions. | Met locally |
| AC-P0-029 | All eight local OS/Python combinations and the required remote matrix passed in run [3489054934](https://github.com/fernan2cp/proteo-runtime/actions/runs/34890854934). | Met |
| AC-P0-030 | Evidence, matrix, exports, and deferred items are reconciled; this directory is ready to move unchanged to `docs/plans/complete/`. | Met |
