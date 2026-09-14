# Requirements — Phase 0

## Scope

These requirements define the repository foundation only. They are subordinate to the normative requirements in `docs/design/project-guide.md` and use stable IDs for implementation traceability.

## Functional Requirements

### P0-REQ-001 — Installable distribution

The project MUST build as `proteo-runtime` from a PEP 517/518 `pyproject.toml`, expose the `proteo_runtime` namespace, declare Python `>=3.11`, include `py.typed`, and install successfully from both an editable checkout and built wheel.

### P0-REQ-002 — Base runtime dependency boundary

The package MUST declare `openai-codex>=0.147,<0.148` as a base dependency. Phase 0 MUST NOT instantiate or import provider transport objects during normal unit or contract tests.

### P0-REQ-003 — Framework-independent core

The `core` package MUST have no runtime dependency on LangGraph, LangSmith, OpenTelemetry, or provider-specific SDK types. Import-boundary checks MUST fail if a forbidden dependency is introduced.

### P0-REQ-004 — Public runtime contracts

The package MUST define and export provider-neutral contracts for `Runtime`, `RuntimeModel[T]`, `RuntimeSession`, `RuntimeInput`, `RuntimeMessage`, `TextContent`, `RuntimeResult[T]`, `RuntimeCapabilities`, `RuntimeUsage`, `RuntimeEvent`, `RuntimeIdentity`, `RuntimeDiagnostic`, `ModelInfo`, and `InvocationConfig`.

### P0-REQ-005 — Policy vocabulary

The package MUST define the public vocabulary `brain`, `structured`, `session`, `controlled_agent`, `native`; context policies `external`, `runtime`, `hybrid`; and security policies `isolated`, `read_only`, `controlled_tools`, `native`. Defaults MUST be fail-closed and MUST NOT grant native side effects.

### P0-REQ-006 — Strict configuration schema

The package MUST define immutable schema-version-1 configuration models with `extra=forbid`, logical levels `low`, `medium`, `high`, and `ultra`, and path-aware validation errors. File discovery, environment loading, precedence, and production model mappings MUST remain deferred to Phase 2.

### P0-REQ-007 — Stable error hierarchy

The package MUST expose the complete public error hierarchy from R-021, rooted at `AgentRuntimeError`. Provider failures may be chained as causes but MUST NOT replace public error types or leak secrets.

### P0-REQ-008 — Normalized usage and events

The package MUST define immutable provider-neutral usage and diagnostic values and a causal, ordered event envelope covering runtime, invocation, session, turn, usage, retry, validation, tool, and capability outcomes. Phase 0 does not execute tools or export events.

### P0-REQ-009 — Opaque session codec

`SessionCodec` MUST encode and decode a versioned, self-contained session descriptor using canonical JSON, unpadded base64url, and the `prt1.` prefix. Descriptors MUST contain no credentials or access tokens and MUST never expand current permissions.

### P0-REQ-010 — Deterministic fake runtime

`FakeRuntime`, `FakeRuntimeModel`, and `FakeRuntimeSession` MUST support scripted invocation and streaming, lifecycle events, usage, capabilities, resumable opaque session IDs, cancellation, and single-active-turn enforcement without network or Codex process access.

### P0-REQ-011 — Public exports and minimal CLI

Stable Phase 0 symbols MUST be re-exported from documented package modules and the root package where appropriate. The installed `proteo-runtime` command MUST provide `--version`; it MUST not imply that `doctor` or real provider execution is available.

### P0-REQ-012 — Documentation and license

The repository MUST include an MIT `LICENSE`, a README skeleton describing current limitations, and English Google-style docstrings for every function, method, and test helper introduced by the implementation.

## Non-Functional Requirements

### P0-REQ-013 — Async-first API

Primary runtime, model, and session operations MUST be asynchronous. A synchronous facade is out of scope for Phase 0 and must not constrain the protocol design.

### P0-REQ-014 — Immutability and safe inputs

Core value objects and configuration models MUST be immutable after construction. Core input MUST accept text and the documented text-message model only; arbitrary framework state and provider objects MUST be rejected.

### P0-REQ-015 — No quota by default

Running the default test command MUST not call a real Codex runtime, use authentication, make network requests, or consume subscription quota. Real-runtime tests, if added later, MUST be opt-in and marked as integration tests.

### P0-REQ-016 — Reproducible quality gates

The repository MUST configure Ruff, mypy, pytest, pytest-asyncio, coverage, pre-commit, and import-linter. CI MUST run the quality gates on Linux and Windows across Python 3.11–3.14 and build both wheel and sdist.

### P0-REQ-017 — Explicit phase deferral

The SDD and implementation MUST label Codex behavior, configuration resolution, structured-output execution, integrations, observers, tools, security enforcement, retries, and `doctor` as deferred rather than providing misleading placeholders.
