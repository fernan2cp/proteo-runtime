# Traceability — Smart Quote Agent Example

## Design Guides to Requirements

| Source Section / Reference | Requirements | Topic / Scope |
|---|---|---|
| User Request / Repository Rules | `SQA-REQ-001` | Strict directory isolation and zero project code modification |
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
