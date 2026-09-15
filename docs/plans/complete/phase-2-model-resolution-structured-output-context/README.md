# SDD Phase 2 — Model Resolution, Structured Output and Context

## Purpose

This package defines the implementation-ready design for Phase 2 of Proteo Runtime. It turns
the Codex provider delivered in Phase 1 into an LLM-like engine with strict configuration,
logical model resolution, validated structured output, explicit context ownership, and
compatible persistent-session migration.

## Sources of Truth

- `docs/design/project-guide.md`, especially R-003 through R-006, R-008, R-009, R-012,
  R-017 through R-023, R-026 through R-029, sections 7 through 11, and roadmap Phase 2.
- `docs/plans/complete/phase-1-codex-core-runtime/` for the implemented provider, session,
  security, test, rollout, and traceability baseline.
- The installed compatibility baseline `openai-codex>=0.147,<0.148`; its stable
  `AsyncThread.turn()` surface accepts `output_schema`.
- The Codex catalog inspected on 2026-09-15 for the explicit version-one default mappings.

## Documents

```text
00_baseline.md             Current repository, contracts, SDK, catalog, and risk baseline.
01_requirements.md         Verifiable Phase 2 requirements.
02_technical_design.md     Configuration, resolution, structure, context, and migration design.
03_task_plan.md            Ordered implementation tasks, dependencies, and evidence slots.
04_acceptance_criteria.md  Binary completion criteria.
05_validation_plan.md      Exact quota-safe, integration, CI, and packaging validation.
06_rollout_and_rollback.md Incremental delivery, release gates, and rollback rules.
07_traceability.md         Guide, requirement, task, criterion, and validation mapping.
```

## Status and Lifecycle

Status: `complete`.

All implementation tasks began as `pending`. Implementation, acceptance criteria, validation
evidence, and the `0.3.0` handoff are complete; this package is moved unchanged by filename to
`docs/plans/complete/`.

## Scope

Included:

- strict JSON and typed runtime configuration with explicit precedence;
- versioned Codex mappings for all four logical reasoning levels;
- fully composed custom profile declarations with capability-gated execution;
- immutable model/session resolution and per-call overrides safe for concurrency;
- Pydantic and Draft 2020-12 JSON Schema structured output;
- provider-side schema enforcement, host validation, bounded validation retry, and buffered
  structured streaming;
- external, runtime, and hybrid context-policy enforcement;
- persistent-session creation, resume, and same-thread migration under resolved configuration;
- public contract, fake, documentation, packaging, and quota-safe test updates for `0.3.0`.

Deferred:

- persistent structured-output sessions;
- LangGraph and other framework adapters;
- host-managed tools and `controlled_agent` execution;
- `native` execution and strong read-root/process isolation;
- general transport, tool, and session recovery retry policies;
- observer exporters, `doctor`, automatic fallback, and cross-provider/session-identity migration.

## Traceability Rule

Every `P2-TASK-*` references at least one `P2-REQ-*` and one `AC-P2-*`. Every requirement is
covered by at least one task and one acceptance criterion. Every acceptance criterion names its
planned automated, inspection, integration, or operational evidence. Evidence may be marked
satisfied only after the recorded validation succeeds.

Post-closure findings are recorded append-only in [`ERRATA.md`](ERRATA.md).
