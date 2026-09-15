# SDD Phase 0 — Repository and Architectural Foundation

## Purpose

This package defines the implementation-ready design for Phase 0 of Proteo Runtime. Phase 0 establishes an installable Python library, freezes dependency direction, publishes provider-neutral contracts, and provides deterministic test doubles. It does not implement the Codex provider or any framework integration.

## Source of Truth

The authoritative design source is:

```text
docs/design/project-guide.md
```

The official Codex SDK documentation is the external compatibility reference for the base dependency:

```text
https://developers.openai.com/codex/sdk/
```

## Documents

```text
00_baseline.md
    Repository baseline, constraints, sources, and phase boundary.

01_requirements.md
    Verifiable Phase 0 functional and non-functional requirements.

02_technical_design.md
    Package topology, public contracts, configuration, fake runtime, and tooling.

03_task_plan.md
    Ordered implementation tasks with dependencies and requirement links.

04_acceptance_criteria.md
    Completion criteria identified as AC-P0-*.

05_validation_plan.md
    Commands, test scenarios, CI evidence, and quota-safety checks.

06_rollout_and_rollback.md
    Incremental delivery, review gates, and recoverable rollback procedure.

07_traceability.md
    Mapping between project-guide requirements, Phase 0 requirements, tasks, tests, and acceptance criteria.
```

## Status and Lifecycle

Status: `complete`.

The package remains under `docs/plans/active/` until every acceptance criterion has implementation evidence. Once Phase 0 is implemented and validated, move this directory unchanged to `docs/plans/complete/`.

## Scope

Included:

- Python package metadata and build configuration;
- MIT license and README skeleton;
- provider-neutral core protocols and value objects;
- profile, context, and security policy vocabulary;
- strict configuration schema version 1 models;
- versioned opaque session codec;
- complete public error hierarchy;
- normalized events, usage, diagnostics, and identity contracts;
- deterministic fake runtime/model/session;
- unit and contract tests that never invoke Codex;
- linting, typing, import-boundary checks, and Linux/Windows CI.

Deferred to later phases:

- real Codex startup, authentication, model discovery, and App Server transport;
- configuration file loading, precedence resolution, and production mappings;
- provider-side structured output and validation retries;
- LangGraph, LangSmith, OpenTelemetry, tools, sandbox enforcement, and `doctor` behavior.

## Traceability Rule

Every `P0-TASK-*` task must reference at least one `P0-REQ-*` requirement and one `AC-P0-*` criterion. Deferred project-guide requirements must be marked explicitly as deferred rather than represented as completed Phase 0 behavior.

Post-closure findings are recorded append-only in [`ERRATA.md`](ERRATA.md).
