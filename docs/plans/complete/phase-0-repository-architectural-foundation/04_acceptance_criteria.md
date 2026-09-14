# Acceptance Criteria — Phase 0

Criteria are binary and must be backed by command output, test results, or reviewed artifacts.

## Baseline and Packaging

### AC-P0-001

The implementation record identifies the local repository state and confirms whether it matches `00_baseline.md`.

### AC-P0-002

No unrelated worktree change is overwritten or incorporated without being recorded.

### AC-P0-003

`pip install -e .` succeeds, the distribution is named `proteo-runtime`, the import namespace is `proteo_runtime`, and `python -c "import proteo_runtime"` succeeds in a clean environment.

### AC-P0-004

Both wheel and sdist build successfully and install into a clean environment with the expected package metadata and `py.typed` marker.

### AC-P0-005

`proteo-runtime --version` and `python -m proteo_runtime --version` return the declared package version without initializing Codex.

## Architecture and Public Contracts

### AC-P0-006

The package topology matches `02_technical_design.md`, and reserved provider/integration namespaces contain no unplanned implementation.

### AC-P0-007

Import-linter and dedicated tests prove that core imports neither LangGraph nor provider, integration, exporter, or SDK modules.

### AC-P0-008

All Phase 0 contract symbols are importable from their documented modules and the approved root exports.

### AC-P0-009

`str` input normalizes to one user `RuntimeMessage` containing one `TextContent`, while arbitrary objects and provider/framework objects are rejected.

### AC-P0-010

Core result, usage, capability, identity, diagnostic, policy, profile, and message values cannot be mutated after construction.

### AC-P0-011

The runtime/model/session protocols are async-first and contain no provider-specific result, transport, or protocol types.

### AC-P0-012

Profile, context-policy, and security-policy defaults match the guide and do not grant native side effects implicitly.

### AC-P0-013

Every error in the R-021 list is present under `AgentRuntimeError` with stable inheritance.

### AC-P0-014

Provider causes can be chained for diagnostics, but exception text and structured diagnostics redact or reject credential-shaped values.

## Configuration and Sessions

### AC-P0-015

A valid schema-version-1 configuration model parses successfully and preserves profile/level mappings immutably.

### AC-P0-016

Unknown keys and unsupported schema versions fail with a `ConfigurationError` that identifies the JSON path.

### AC-P0-017

Invalid logical levels and missing mappings fail explicitly; no loader, precedence rule, or silent model fallback is implemented in Phase 0.

### AC-P0-018

A valid session descriptor round-trips through `SessionCodec` with a deterministic `prt1.` representation.

### AC-P0-019

Malformed base64/JSON, wrong prefix, unsupported version, missing required fields, and forbidden secret fields raise `SessionMismatchError`.

### AC-P0-020

Decoded session data cannot expand current permissions, and the codec contains no internal alias database or credential material.

## Fake Runtime and Quota Safety

### AC-P0-021

`FakeRuntime` starts and closes idempotently, emits ordered lifecycle/invocation events, and reports deterministic metadata.

### AC-P0-022

Fake model invocation returns `RuntimeResult[str]` with configured usage, diagnostics, profile, and correlation identifiers.

### AC-P0-023

Fake streaming preserves event order, supports cancellation/interruption, and terminates without leaking an active turn.

### AC-P0-024

Fake sessions close without deleting simulated history, resume through an opaque session ID, and reject concurrent turns with `SessionBusyError`.

### AC-P0-025

Injected authentication, capability, timeout, cancellation, and provider-like failures are normalized through the public error hierarchy.

### AC-P0-026

The README and CLI describe Phase 0 limitations accurately and do not claim real Codex, LangGraph, tools, or exporters are available.

### AC-P0-027

The default test suite performs no Codex process launch, authentication read, network request, or subscription-quota operation.

## Quality and Handoff

### AC-P0-028

Every introduced function, method, and test helper has an English Google-style docstring; Ruff and mypy pass without suppressions that hide contract errors.

### AC-P0-029

The complete unit/contract suite, coverage threshold, import-boundary checks, and build checks pass on Linux and Windows for Python 3.11–3.14.

### AC-P0-030

The traceability matrix is complete, validation evidence is recorded, unresolved gaps are marked, and the SDD is moved to `docs/plans/complete/` only after all required criteria pass.
