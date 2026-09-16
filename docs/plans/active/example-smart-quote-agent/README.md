# SDD Example — Smart Quote Agent

## Purpose

This package defines the decision-complete Software Design Document (SDD) for implementing the Smart Quote Agent example application inside `examples/smart_quote_agent/`.

The application is a small, integrated CLI demonstration that showcases:
- LangGraph orchestration owned by the host;
- structured routing and planning;
- a controlled agent utilizing host-managed tools;
- distinct anonymous, client, and staff interaction modes;
- host-enforced authorization policies;
- login and logout as human-in-the-loop (HITL) branches;
- masked password entry via `getpass`;
- deterministic, host-controlled quote calculation and invariants;
- discount selection through an interactive HITL prompt;
- final human approval prior to persistence via Proteo Phase 5 approval contracts;
- atomic SQLite persistence with quote and quote-line history;
- metadata-only runtime and tool observability;
- absolute boundary separation between model suggestions and host execution authority.

## Source of Truth

The authoritative sources of truth for this design are:
- `docs/design/project-guide.md` (Repository architectural source of truth, specifically §2.1, §9, §12–§15, §19, §21–§25).
- `docs/examples/smart_quote_agent/design/smart_quote_agent_implementation_guide.md` (Domain specifications, user model, SQLite schema, workflows, and acceptance scenarios).

## Documents

```text
00_baseline.md
    Repository baseline, core contracts, isolation constraints, and assumptions.

01_requirements.md
    Verifiable functional and non-functional requirements (SQA-REQ-*).

02_technical_design.md
    Topology, SQLite schema, LangGraph state, host tools, HITL, and security.

03_task_plan.md
    Ordered implementation tasks with dependencies and requirement links (SQA-TASK-*).

04_acceptance_criteria.md
    Binary, testable acceptance criteria (AC-SQA-*).

05_validation_plan.md
    Verification commands, static analysis, smoke tests, and demonstration scripts.

06_rollout_and_rollback.md
    Delivery stages, blast-radius mitigation, and clean rollback procedures.

07_traceability.md
    Mapping across design guides, requirements, tasks, criteria, and verification.
```

## Status and Lifecycle

Status: `active`.

- This package remains in `docs/plans/active/example-smart-quote-agent/` throughout planning, implementation, and verification.
- **Mandatory Human Review Gate**: Before finalizing and moving this plan to `docs/plans/complete/`, explicit human review must be requested with full verification evidence.
- Once approved by the repository owner, the directory will be moved unchanged to `docs/plans/complete/example-smart-quote-agent/`.

## Scope

### Included

- All files and code strictly confined within `examples/smart_quote_agent/`:
  - `README.md`: Setup, credentials, architecture, and example sessions.
  - `app.py`: CLI loop, runtime lifecycle, graph execution, and exit handling.
  - `init_demo.py`: Deterministic database reset and seeding script (`--reset`).
  - `database.py`: SQLite schema, foreign key enforcement, queries, and transactional persistence.
  - `models.py`: Pydantic structured output models and graph state definitions.
  - `auth.py`: Masked credential input, credential validation, sanitized identity, and permission mapping.
  - `tools.py`: Host-managed tools (`runtime_tool`), registry factory, and executor policy factory.
  - `graph.py`: LangGraph state graph compilation, deterministic workflow, and controlled agent branch.
  - `hitl.py`: Interactive discount validation (0–30%) and Phase 5 `ApprovalHandler` implementation.
  - `data/.gitkeep`: Local directory placeholder for `demo.sqlite3`.
- Deterministic seeding: 1 staff user, 4 client users, 4 customer records, 6 product catalog records.
- Trivial demo password (`1234`) with explicit non-production security disclaimer.
- Password masking via `getpass.getpass()`, with absolute zero-leakage guarantees (passwords never enter graph state, runtime events, or logs).
- Dual-layer authorization: early LangGraph guard and authoritative Phase 5 `ToolPermissionPolicy`.
- Money represented as integer cents in persistence, formatted and calculated via `Decimal` with `ROUND_HALF_UP`.
- Full compliance with `mypy --strict`, `ruff check`, and `ruff format`.

### Explicitly Excluded (Non-Scope & Strict Boundaries)

- **Zero Project Code Modifications**: Under no circumstances may any file outside `examples/smart_quote_agent/*` be created, modified, or deleted (no changes to `src/*`, `tests/*`, `pyproject.toml`, etc.).
- No customer CRUD or self-registration.
- No product creation or price modification interfaces.
- No shopping cart, checkout, payment processing, or inventory reservation.
- No web UI, REST API, or GraphQL server.
- No JWT, OAuth2, session tokens, or password hashing frameworks.
- No production database engines (PostgreSQL, MySQL), Redis, or Docker containers.
- No database migration frameworks (Alembic) or ORM libraries.
- No Phase 6 strong process/sandbox isolation or Phase 7 transport recovery.

## Traceability Rule

- Every task (`SQA-TASK-*`) links to at least one requirement (`SQA-REQ-*`) and one acceptance criterion (`AC-SQA-*`).
- Every requirement (`SQA-REQ-*`) maps to at least one task and one acceptance criterion.
- Every acceptance criterion (`AC-SQA-*`) specifies concrete, reproducible verification evidence in `05_validation_plan.md`.
