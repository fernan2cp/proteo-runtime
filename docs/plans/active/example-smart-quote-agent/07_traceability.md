# Traceability — Smart Quote Agent Example

## Design Guides to Requirements

| Source Section / Reference | Requirements | Topic / Scope |
|---|---|---|
| User Request / Repository Rules | `SQA-REQ-001` | Strict directory isolation and zero project code modification |
| Project Guide §2.4, §14–§15; User Request | `SQA-REQ-019` | Failure observability, metadata-only diagnostics, and host-owned interaction correlation |
| Guide §6, §21, §22 | `SQA-REQ-002`, `SQA-REQ-006` | SQLite domain model, constraints, seeds, and transactional atomicity |
| Guide §12, §13, §14 | `SQA-REQ-003` | Pydantic router/planner schemas, sanitized identity, and graph state |
| Guide §4, §9.1, §10 | `SQA-REQ-004` | Masked login, getpass, sanitized state, and logout routing |
| Guide §5, §15, §16 | `SQA-REQ-005` | Host-managed tools registry, tool bindings, and dual role policies |
| Guide §7, §8, §20 | `SQA-REQ-006` | Pricing invariants, Decimal arithmetic, and discount rules |
| Guide §8, §9.2, §9.3 | `SQA-REQ-007` | Interactive discount HITL and Phase 5 persistence approval |
| Guide §2, §11, §18 | `SQA-REQ-008` | LangGraph hybrid architecture and controlled agent sandboxing |
| Guide §1, §23, §24, §25 | `SQA-REQ-009` | Interactive CLI interface, mode indicators, and exit handling |
| Guide §26 | `SQA-REQ-010` | Safe metadata-only console observability without credential exposure |
| Guide §28, §31, §32 | `SQA-REQ-011` | Documentation, user credentials, demo scripts, and security disclaimers |
| Project Guide §2.1, AGENTS.md | `SQA-REQ-012`, `SQA-REQ-013` | Strict type safety (`mypy --strict`), Google docstrings, and ruff styling |

---

## Requirements to Tasks, Criteria & Validation

| Requirement | Tasks | Criteria | Validation Strategy |
|---|---|---|---|
| `SQA-REQ-001` (Isolation) | `SQA-TASK-0001`, `SQA-TASK-0010` | `AC-SQA-001` | `git status --short` inspection |
| `SQA-REQ-002` (SQLite & Seeds) | `SQA-TASK-0002` | `AC-SQA-002`, `AC-SQA-008` | `python examples/smart_quote_agent/init_demo.py --reset` & headless smoke test |
| `SQA-REQ-003` (Models & Schemas) | `SQA-TASK-0003` | `AC-SQA-003`, `AC-SQA-011` | `uv run mypy examples/smart_quote_agent --strict` |
| `SQA-REQ-004` (Auth & Masking) | `SQA-TASK-0004` | `AC-SQA-003`, `AC-SQA-004`, `AC-SQA-005` | Interactive CLI login testing & graph state inspection |
| `SQA-REQ-005` (Tools & Policies) | `SQA-TASK-0005` | `AC-SQA-004`, `AC-SQA-005`, `AC-SQA-007` | Role policy execution tests & ToolExecutor assertions |
| `SQA-REQ-006` (Pricing Invariants) | `SQA-TASK-0002`, `SQA-TASK-0005` | `AC-SQA-007`, `AC-SQA-008` | Headless smoke assertions on `persist_quote_transactional` |
| `SQA-REQ-007` (HITL Workflows) | `SQA-TASK-0006` | `AC-SQA-006`, `AC-SQA-007` | Interactive CLI discount and approval prompts |
| `SQA-REQ-008` (LangGraph Hybrid) | `SQA-TASK-0007` | `AC-SQA-004`, `AC-SQA-005`, `AC-SQA-009`, `AC-SQA-010` | Graph compilation and node transition verification |
| `SQA-REQ-009` (CLI Application) | `SQA-TASK-0008` | `AC-SQA-003`, `AC-SQA-009`, `AC-SQA-010` | Live interactive demonstration walkthrough |
| `SQA-REQ-010` (Observability) | `SQA-TASK-0007`, `SQA-TASK-0008` | `AC-SQA-010` | Telemetry event stream inspection (metadata-only) |
| `SQA-REQ-011` (Documentation) | `SQA-TASK-0009` | `AC-SQA-011` | Review of `examples/smart_quote_agent/README.md` |
| `SQA-REQ-012` (Strict Types) | `SQA-TASK-0003`, `SQA-TASK-0010` | `AC-SQA-011` | `uv run mypy examples/smart_quote_agent --strict` |
| `SQA-REQ-013` (Linting & Style) | `SQA-TASK-0010` | `AC-SQA-011` | `uv run ruff check` and `uv run ruff format --check` |

---

## Acceptance Criteria Evidence Map

| Criteria ID | Topic / Scope | Primary Verification Command / Inspection Location |
|---|---|---|
| `AC-SQA-001` | Strict Directory Isolation | `git status --short` |
| `AC-SQA-002` | SQLite Provisioning & Seeds | `python examples/smart_quote_agent/init_demo.py --reset` |
| `AC-SQA-003` | Masked Login & Sanitized State | Interactive CLI execution & `auth.py` inspection |
| `AC-SQA-004` | Anonymous / Client Permissions | Interactive CLI scenarios 4 & 6 |
| `AC-SQA-005` | Staff Capability Access | Interactive CLI scenarios 9, 13 & 14 |
| `AC-SQA-006` | Discount HITL Validation | Interactive CLI scenario 10 |
| `AC-SQA-007` | Approval Gate & Atomicity | Interactive CLI scenarios 11 & 12 |
| `AC-SQA-008` | Pricing Invariants & Cents Math | Headless smoke verification script |
| `AC-SQA-009` | Controlled Agent Sandboxing | Interactive CLI scenario 2 & `tools.py` inspection |
| `AC-SQA-010` | Metadata-Only Telemetry | Console telemetry log output inspection |
| `AC-SQA-011` | Quality, Types & Docstrings | `uv run mypy examples/smart_quote_agent --strict` & `uv run ruff check` |

---

## Conversational Hardening Traceability (Incremental)

The user-reported CLI transcript is the regression source for this addendum. The scope exception is limited to updating this active SDD package; code changes remain in `examples/smart_quote_agent/`.

### Hardening Requirements to Tasks, Criteria, and Validation

| Requirement | Tasks | Criteria | Validation |
|---|---|---|---|
| `SQA-REQ-001` (Bounded isolation) | `SQA-TASK-0011`, `SQA-TASK-0016` | `AC-SQA-001`, `AC-SQA-011` | Baseline-aware diff review; preserve pre-existing worktree changes |
| `SQA-REQ-005` (Staff customer directory tool) | `SQA-TASK-0014` | `AC-SQA-015` | Staff/client/anonymous registry tests and customer list output |
| `SQA-REQ-006` (Authoritative calculations and atomicity) | `SQA-TASK-0013`, `SQA-TASK-0016` | `AC-SQA-018` | Offline multi-line preview uses `calculate_quote`; exact SKU resolution; unknown/ambiguous lines abort without persistence |
| `SQA-REQ-014` (Workflow state and revision-bound draft) | `SQA-TASK-0012` | `AC-SQA-012`, `AC-SQA-014` | End-to-end workflow, stale draft, cleanup, and persistence assertions |
| `SQA-REQ-015` (Contextual router and quote patches) | `SQA-TASK-0011`, `SQA-TASK-0012`, `SQA-TASK-0013` | `AC-SQA-012`, `AC-SQA-013` | Interruption, replacement, add/remove, quantity, and ambiguity graph tests |
| `SQA-REQ-016` (Canonical customer/product resolution) | `SQA-TASK-0014` | `AC-SQA-015`, `AC-SQA-018` | Accent/plural/alias, SKU, ambiguity, `desk` negative lookup, and permission tests |
| `SQA-REQ-017` (Stable language and task continuity) | `SQA-TASK-0013` | `AC-SQA-016` | Language follow-up and turn-only RuntimeTask input assertions |
| `SQA-REQ-018` (Task/workflow observability) | `SQA-TASK-0015` | `AC-SQA-017` | Legacy DB migration, metadata whitelist, `--task`, `--workflow`, and cleanup diagnostics |
| `SQA-REQ-019` (Correlated, redacted turn errors) | `SQA-TASK-0017`, `SQA-TASK-0016` | `AC-SQA-019` | Exception redaction/logger isolation, `InvocationConfig.metadata`, idempotent interaction migration, `--interaction` failed/success status, and live evidence |

### Hardening Acceptance Evidence Map

| Criteria ID | Topic | Verification |
|---|---|---|
| `AC-SQA-012` | Original conversation completes with one correct Globex quote | `test_hardening_reported_transcript_completes_across_interruptions` |
| `AC-SQA-013` | Edits preserve lines; ambiguous input is a no-op | `test_hardening_quote_patch_operations_preserve_unrelated_lines`; `test_hardening_ambiguous_reference_and_quantity_are_noops` |
| `AC-SQA-014` | Draft identity/revision guards and terminal cleanup | Stale draft and lifecycle graph tests; full test suite |
| `AC-SQA-015` | Staff customer directory and canonical resolution | Registry tests; customer accent lookup; product alias and desk-negative tests |
| `AC-SQA-016` | Language and RuntimeTask context policy | Language-persistence and user-only task turn tests |
| `AC-SQA-017` | Additive migration and safe correlated timeline | `test_task_id_schema_migration_is_additive_and_idempotent`; task/workflow inspector and host-event tests |
| `AC-SQA-018` | Complete, authoritative offline preview | Offline preview tests: multi-line total, ambiguous notebook, exact SKU, unknown line, and no persistence |
| `AC-SQA-019` | Correlated, redacted live-turn diagnostics | `test_host_error_is_correlated_and_excludes_exception_messages`; REPL logger-failure and invocation-metadata regressions; interaction migration/inspector tests; live `--interaction` inspection in `05_validation_plan.md` |

**AC-SQA-001 interpretation:** historical evidence that the original example was initially isolated remains historical. For hardening, criterion 001 permits this active SDD update and judges only changes introduced by the current implementation against its task-start baseline.
