# Baseline — Phase 1

## Repository State

At planning time the worktree is clean and Phase 0 is complete. The package is version
`0.1.0`; `uv run pytest -q` passes all 29 tests. The repository contains provider-neutral core,
configuration schema models, `SessionCodec`, deterministic fakes, public errors, and reserved
`providers` and `integrations` namespaces. No real provider implementation exists.

The README still says provider integrations are deferred and links to the former active Phase
0 path. Phase 1 implementation must update that description and link as part of its handoff,
without treating this documentation drift as existing provider behavior.

## Confirmed Contracts

- `Runtime` exposes `start`, `close`, `capabilities`, `models`, `model`, `session`,
  `resume_session`, and `migrate_session`.
- `RuntimeModel` and `RuntimeSession` expose async invocation and event streaming.
- `RuntimeResult`, `RuntimeUsage`, `RuntimeIdentity`, `RuntimeEvent`, `ModelInfo`, policy enums,
  and the complete public error hierarchy are immutable provider-neutral values.
- `SessionCodec` encodes a self-contained `prt1.` descriptor containing provider session ID,
  identity/configuration fingerprints, profile, level, context policy, and security policy.
- `brain` and `structured` are ephemeral/external/isolated profiles; `session` is
  persistent/runtime/isolated.
- Core cannot import `openai_codex`, providers, LangGraph, LangSmith, or OpenTelemetry.

## SDK Baseline

The locked environment contains `openai-codex 0.147.0`. Its stable async surface includes:

- `AsyncCodex`, SDK-managed process lifecycle, `account()`, `models()`, `thread_start()`,
  `thread_resume()`, and thread archive operations;
- `AsyncThread.run()` and `turn()`, plus `AsyncTurnHandle.stream()` and `interrupt()`;
- `Sandbox.read_only|workspace_write|full_access` and
  `ApprovalMode.deny_all|auto_review`;
- typed model, account, turn, notification, and token-usage values.

The generated SDK includes `ThreadDeleteParams` and `ThreadDeleteResponse`, but the public
`AsyncCodex` wrapper does not expose `thread_delete()` in 0.147. The SDK client has a generic
typed request method; Phase 1 may use that method only through the private compatibility shim
defined in `02_technical_design.md`.

## Closed Decisions

- The SDK-bundled runtime is the only supported transport. Caller-supplied Codex binaries,
  API keys, custom OAuth, and direct standalone App Server clients are excluded.
- Only an already authenticated `chatgpt` account is accepted.
- Persistent `RuntimeSession` is intentionally advanced from Phase 2 into this phase.
- `structured` remains recognized but schema execution remains Phase 2.
- `migrate_session()` remains unavailable and fails explicitly.
- Strong OS isolation is not claimed. Phase 1 provides only the basic fail-closed mapping
  described in this SDD.
- Automatic retry is disabled; retry policy remains Phase 7.

## Gaps To Validate During Implementation

- Validate all used SDK symbols against every supported Python version and the full locked SDK
  range before release.
- Confirm the exact terminal notification shapes using SDK-generated types, not stringly typed
  payload access.
- Confirm the compatibility shim against a real disposable thread before declaring deletion
  accepted.
- Record whether ChatGPT account email is absent in integration evidence; the identity
  fingerprint remains non-authoritative because session descriptors are not security tokens.

## Risks

- SDK notification or private generic-request changes could break streaming or delete.
- `Sandbox.read_only` does not constitute strong isolation by itself.
- Cancellation without confirmed interruption could leave costly provider work running.
- Publishing SDK models through `raw`, exceptions, or exports would accidentally couple users
  to provider internals.
- Account metadata may be incomplete; identity matching must fail safely without claiming an
  authorization guarantee.
