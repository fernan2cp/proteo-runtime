# SDD Phase 1 — Codex Core Runtime

## Purpose

This package defines the implementation-ready design for Phase 1 of Proteo Runtime. It
introduces the first production provider through the stable `openai-codex` Python SDK while
preserving the provider-neutral contracts completed in Phase 0.

## Sources of Truth

- `docs/design/project-guide.md`, especially normative requirements R-003, R-007, R-011,
  R-012, R-015, R-017, R-019 through R-024, R-026 through R-029, and roadmap Phase 1.
- `docs/plans/complete/phase-0-repository-architectural-foundation/` for established public
  contracts, dependency direction, validation conventions, and traceability style.
- Official OpenAI documentation for the [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk),
  [App Server](https://learn.chatgpt.com/docs/app-server), and
  [authentication](https://learn.chatgpt.com/docs/auth).
- The installed and pinned compatibility baseline `openai-codex>=0.147,<0.148`.

## Documents

```text
00_baseline.md             Current repository, SDK, contract, and risk baseline.
01_requirements.md         Verifiable Phase 1 requirements.
02_technical_design.md     Provider architecture, mappings, lifecycle, and failure behavior.
03_task_plan.md            Ordered implementation tasks and dependencies.
04_acceptance_criteria.md  Binary completion criteria.
05_validation_plan.md      Exact local, CI, and opt-in integration validation.
06_rollout_and_rollback.md Incremental delivery and rollback rules.
07_traceability.md         Guide, requirement, task, criterion, and evidence mapping.
```

## Status and Lifecycle

Status: `complete`.

All implementation tasks and acceptance criteria have recorded evidence. This package is moved to
`docs/plans/complete/` as the completed Phase 1 record.

## Scope

Included:

- public `proteo_runtime.providers.codex.CodexRuntime`;
- stable SDK-backed startup, shutdown, ChatGPT identity, and model discovery;
- `brain` text invocation through ephemeral Codex threads;
- normalized streaming, interruption, cancellation, timeout, usage, and events;
- public persistent session creation, resume, close, archive, and delete;
- basic fail-closed sandbox mapping and sanitized error/raw-data boundaries;
- deterministic unit and contract tests plus explicitly enabled real-runtime tests.

Deferred:

- JSON configuration loading and versioned model mappings;
- structured-output execution and validation retries;
- session migration and advanced context replay;
- LangGraph, observers, host-managed tools, strong isolation, general retries, and `doctor`.

## Traceability Rule

Every `P1-TASK-*` references at least one `P1-REQ-*` and one `AC-P1-*`. Every requirement is
covered by at least one task and acceptance criterion. Evidence is recorded only after the
corresponding validation succeeds.
