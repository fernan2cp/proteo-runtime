# Baseline — Phase 0

## Repository State

At planning time the repository is a design-first, empty implementation repository. The only tracked product artifact is the project charter:

```text
docs/design/project-guide.md
```

There is no existing `pyproject.toml`, `src/` package, test suite, CI workflow, runtime implementation, provider adapter, or framework integration to preserve. The implementation must therefore establish the initial conventions without assuming compatibility with an earlier Python API.

Before implementation begins, the contributor must re-run a local status/tree check and record any worktree divergence in this document or in the implementation record. Existing user changes, if any, take precedence over this baseline and must not be overwritten.

## Architectural Baseline

The guide establishes these non-negotiable boundaries:

- the distribution is `proteo-runtime` and the import namespace is `proteo_runtime`;
- the core is framework-agnostic and must not import LangGraph;
- the initial provider is Codex, but provider-specific code stays behind a provider boundary;
- the host owns application state, execution authority, and application tools;
- runtime capability and effective permission are separate concepts;
- async behavior is primary;
- default tests use fakes and consume no subscription quota;
- public errors are Proteo errors, not provider exception types;
- secrets never appear in configuration, metadata, traces, tool payloads, or exception messages.

## Phase Boundary

Phase 0 is the repository and architectural foundation. It must produce a usable, installable package and executable contract tests, but it must not claim that Codex inference works.

The phase implements neutral contracts and deterministic behavior only. The Codex SDK is declared as the canonical base dependency so packaging direction is fixed, but no test may start its executable, inspect authentication, contact a network endpoint, or consume quota.

The following are intentionally deferred:

| Area | Deferred phase | Phase 0 treatment |
|---|---:|---|
| Codex transport/authentication/model listing | 1 | Dependency declaration and provider boundary only |
| File/environment configuration loading and resolution | 2 | Strict schema models and validation primitives only |
| Pydantic structured-output execution/retry | 2 | Generic result/schema contract only |
| LangGraph adapter | 3 | Reserved integration namespace and import boundary |
| LangSmith/OpenTelemetry exporters | 4 | Neutral event/diagnostic contract only |
| Host-managed tools | 5 | No executor or registry implementation |
| Security enforcement/sandbox isolation | 6 | Policy vocabulary and fail-closed contract only |
| Retry, timeout, and cancellation engine | 7 | Error/event hooks and fake-runtime scenarios only |
| `doctor` diagnostics | 8 | Diagnostic value object only |

## Authoritative Inputs

The implementation must remain aligned with:

1. `docs/design/project-guide.md`, especially requirements R-001, R-002, R-004, R-005, R-006, R-009, R-011, R-012, R-013, R-016, R-017, R-019, R-020, R-021, R-022, R-023, R-024, R-026, R-027, R-028, and roadmap Phase 0.
2. The stable `openai-codex` Python SDK documentation and its published package metadata. The baseline dependency range is `openai-codex>=0.147,<0.148`; update the range only through a documented compatibility decision.
3. Repository contribution rules in `AGENTS.md`, including English Google-style docstrings for every function, method, and test helper.

## Risks to Carry Forward

- Creating provider objects in core would make later provider and framework additions breaking changes.
- Making configuration permissive would invalidate path-aware failures and silent-fallback protections.
- Encoding a session identifier as an opaque token without validating decoded fields could turn it into an authorization boundary.
- Allowing fake tests to import or call Codex transport code could silently reintroduce quota consumption.
- Adding placeholder integrations or empty optional dependencies could imply support that Phase 0 does not provide.
