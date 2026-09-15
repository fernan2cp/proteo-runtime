# Baseline — Phase 2

## Repository State

At planning time the worktree is clean, Phase 1 is complete, and the package version is
`0.2.0`. The quota-safe baseline is `46 passed, 3 skipped`. The package supports Python
3.11–3.14, uses Pydantic 2, and pins `openai-codex>=0.147,<0.148`. Core remains independent
from the provider and external frameworks.

Phase 1 already provides a functional Codex runtime, normalized text results and streams,
ChatGPT-managed identity, catalog discovery, explicit lifecycle, isolated ephemeral workspaces,
persistent sessions, opaque `prt1.` descriptors, interruption, usage, and stable errors. No
Phase 2 behavior is evidenced by the existing passing suite.

## Confirmed Configuration and Profile Contracts

- `RuntimeConfigV1` is strict and frozen, accepts `schema_version`, `runtime`, and a nested
  `profiles` resolution mapping, and reports the first invalid Pydantic location through
  `ConfigurationError.path`.
- Configuration currently has no file loader, packaged defaults, environment handling, source
  precedence, or integration with `CodexRuntime`.
- `LogicalLevel` already defines `low`, `medium`, `high`, and `ultra`.
- `ProfileSpec` and the built-in profile vocabulary already exist. The implementation currently
  declares `controlled_agent` as `hybrid`, while the project guide requires `external`.
- `CodexRuntime(default_model=...)` selects one model globally. `model(profile, level)` stores
  the level as an effort override rather than resolving a configuration mapping.
- Per-call configuration temporarily mutates `_CodexModel.config`, creating a race between
  concurrent invocations and replacing rather than field-merging bound options.

## Confirmed Structured-Output Contracts

- `RuntimeModel.with_structured_output()` is part of the neutral protocol but the Codex model
  intentionally raises `CapabilityError`.
- `StructuredOutputError`, `VALIDATION_FAILED`, and `RETRY_SCHEDULED` already exist, but have no
  implementation path.
- The pinned SDK exposes stable `output_schema: JsonObject | None` on `AsyncThread.turn()` and
  `run()`. No direct App Server or experimental compatibility path is needed.
- Pydantic is installed; a general JSON Schema host validator is not installed.
- The current runner produces `RuntimeResult[str]`, emits raw text deltas, and terminates each
  provider turn as an invocation. Phase 2 needs a logical-invocation wrapper for multi-turn
  structured validation.

## Confirmed Context and Session Contracts

- Ephemeral `brain` serializes system instructions plus user/assistant/tool transcript into a
  new thread.
- Persistent sessions use the built-in `session` profile and reject every role except `user`.
- Session configuration fingerprints include model, effort, profile, context, security,
  sandbox, approval mode, and the SDK compatibility family.
- Resume currently recomputes the fingerprint using the runtime-wide selected model instead of
  resolving the descriptor profile and level.
- `migrate_session()` intentionally raises `CapabilityError` without provider access.
- The neutral protocol annotates `RuntimeSession.descriptor` as `SessionDescriptor`, while the
  guide and concrete provider expose the opaque public string. The codec object remains internal.

## Catalog Baseline and Closed Defaults

The visible catalog inspected on 2026-09-15 was:

| Model | Catalog default | Supported efforts |
|---|---:|---|
| `gpt-5.6-sol` | yes | low, medium, high, xhigh, max, ultra |
| `gpt-5.6-terra` | no | low, medium, high, xhigh, max, ultra |
| `gpt-5.6-luna` | no | low, medium, high, xhigh, max |
| `gpt-5.5` | no | low, medium, high, xhigh |

The version-one packaged mappings for `brain`, `structured`, and `session` are closed as:

| Logical level | Model | Provider effort |
|---|---|---|
| `low` | `gpt-5.6-luna` | `low` |
| `medium` | `gpt-5.6-terra` | `medium` |
| `high` | `gpt-5.6-sol` | `high` |
| `ultra` | `gpt-5.6-sol` | `ultra` |

Unavailable configured mappings fail explicitly. The resolver never substitutes the catalog
default or infers a logical level from a model name.

## Closed Decisions

- Keep configuration schema version `1` and add optional `profile_specs` without changing the
  existing `profiles.<name>.<level>` mapping shape.
- Custom profiles compose lifecycle, context policy, security policy, and host-tools mode. The
  schema accepts the full public vocabulary; semantic and effective-capability checks reject
  incoherent or deferred execution before thread creation.
- Use `jsonschema>=4,<5` as a base dependency and Draft 2020-12 for dictionary schemas.
- Structured retries are one logical ephemeral invocation using one thread/workspace and at
  most two turns by default. General runtime retry remains deferred.
- Structured streaming buffers provider text, exposes no partial JSON, and emits one validated
  terminal result.
- Same-provider migration reuses the provider thread and creates a new descriptor. It does not
  replay, copy, archive, or delete provider history.

## Risks and Implementation Checks

- Concrete packaged model IDs age faster than the library; catalog mismatch must be actionable
  and requires a new versioned mapping rather than silent fallback.
- A schema accepted by Codex may still fail Draft 2020-12 or Pydantic host validation.
- Multi-attempt event rewriting must preserve one invocation ID, monotonic sequence numbers,
  distinct turn IDs, cancellation, and total usage without leaking invalid output.
- Invalid raw output can contain sensitive data. It must remain opt-in, outside exception text,
  details, events, diagnostics, and exporters, with conservative redaction before exposure.
- Migration cannot revoke an opaque descriptor already persisted by a host because 1.0 has no
  alias or revocation store. Only in-process handles are invalidated.
- Phase 2 must not accidentally enable controlled tools, native permissions, caller read roots,
  external effects, implicit configuration discovery, or subscription-backed default tests.
