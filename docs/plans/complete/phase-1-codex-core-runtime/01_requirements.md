# Requirements — Phase 1

## Provider and Lifecycle

- `P1-REQ-001`: The package MUST expose `proteo_runtime.providers.codex.CodexRuntime` as the
  only intentional Phase 1 provider API; SDK and concrete model/session types MUST remain
  internal.
- `P1-REQ-002`: `CodexRuntime` MUST use `AsyncCodex` with its bundled runtime, support explicit
  idempotent startup/shutdown and async context management, and MUST NOT start implicitly from
  invocation methods.
- `P1-REQ-003`: Startup MUST reuse an existing Codex-managed `chatgpt` identity, reject absent
  or other authentication modes, and normalize only non-secret identity metadata.

## Models and Invocation

- `P1-REQ-004`: `models()` MUST map the complete visible SDK catalog to `ModelInfo` without
  leaking SDK objects.
- `P1-REQ-005`: Model and reasoning effort selection MUST use an explicit typed default or the
  single catalog default, validate availability, and fail rather than silently fall back.
- `P1-REQ-006`: `brain` invocation MUST create one ephemeral thread per call, translate
  `RuntimeInput` deterministically, and return `RuntimeResult[str]`.
- `P1-REQ-007`: `structured` MUST be recognized but `with_structured_output()` MUST raise
  `CapabilityError` until Phase 2.

## Persistent Sessions

- `P1-REQ-008`: `session()` MUST create a persistent Codex thread and return a functional
  `RuntimeSession[str]` with an opaque `prt1.` identifier.
- `P1-REQ-009`: `resume_session()` MUST validate descriptor schema, provider, active identity,
  frozen configuration, current permissions, and provider thread existence before returning a
  handle.
- `P1-REQ-010`: A session MUST permit only one active turn, accept user-only turn input, close
  without deleting history, and implement explicit archive and delete. Migration remains an
  explicit unsupported capability.

## Streaming, Usage, and Failures

- `P1-REQ-011`: Invocation and session streaming MUST emit causally ordered normalized events,
  support interruption, and finish with the same result produced by `ainvoke()`.
- `P1-REQ-012`: SDK token and timing data MUST map to `RuntimeUsage`; unavailable values remain
  `None` and provider-specific values remain sanitized.
- `P1-REQ-013`: Isolated execution MUST use a newly created empty workspace,
  `Sandbox.read_only`, and `ApprovalMode.deny_all`, with no caller-controlled permission
  expansion.
- `P1-REQ-014`: Authentication, transport, capability, session, interruption, cancellation,
  and timeout failures MUST map to Proteo errors with sanitized causes and no automatic retry.
- `P1-REQ-015`: Provider activity MUST emit neutral lifecycle/session/turn/usage events.
  `RuntimeResult.raw` MUST be absent by default and, when requested, contain only a sanitized
  provider-data snapshot.

## Compatibility and Quality

- `P1-REQ-016`: Default tests MUST use injected SDK doubles and MUST NOT launch Codex, inspect
  real authentication, access a network, or consume subscription quota. Real tests MUST be
  explicitly enabled and marked `integration`.
- `P1-REQ-017`: Thread deletion MAY use the SDK generic typed request only inside one private,
  tested compatibility module; no other experimental or direct JSON-RPC feature is enabled.
- `P1-REQ-018`: Phase 1 MUST preserve core/framework dependency boundaries, English
  Google-style docstrings, Python 3.11–3.14 compatibility, build quality gates, and an explicit
  `0.2.0` public handoff.
