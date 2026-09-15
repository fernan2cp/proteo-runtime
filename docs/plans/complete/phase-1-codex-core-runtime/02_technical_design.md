# Technical Design — Phase 1

## Package Boundary

Create `src/proteo_runtime/providers/codex/` with public `CodexRuntime` and internal modules for
SDK adaptation, model/session handles, turn execution, mapping, errors, workspace management,
and the delete compatibility shim. `providers.codex.__all__` exports only `CodexRuntime`.
Neither root package imports nor `core` imports the provider automatically.

`CodexRuntime` accepts `default_model: str | None = None`. Test-only construction dependencies
are private keyword arguments or internal factories; SDK types never appear in public
signatures. Caller-supplied binaries, arbitrary SDK config, API credentials, and permission
overrides are not accepted.

## Runtime Lifecycle and Identity

`start()` enters one `AsyncCodex` instance, reads `account(refresh_token=False)`, requires
account type `chatgpt`, fetches the model catalog, resolves the default model, and creates the
runtime identity. Repeated starts are no-ops while active. Starting after `close()` creates a
fresh SDK instance; methods requiring an active runtime otherwise raise
`RuntimeUnavailableError`.

The identity fingerprint is SHA-256 over canonical `{provider, auth_mode, normalized_email,
plan_type}` data. Email participates in the digest but is never retained in the public identity
or diagnostics. Public metadata is limited to `auth_mode`, `plan_type`, and an
`identity_precision` flag. Missing email yields a deterministic degraded fingerprint and a
warning diagnostic; it never becomes an authorization claim.

`close()` atomically prevents new work, interrupts active turns, waits for their cleanup,
closes handles and the SDK client, and removes temporary workspaces. It never archives or
deletes persistent provider threads.

## Model Discovery and Selection

`models()` returns non-hidden SDK entries as `ModelInfo`, preserving identifier, display name,
and supported reasoning efforts. Phase 1 capabilities are text invocation, ephemeral and
persistent sessions, streaming, interruption, sandbox mapping, and usage reporting;
structured output, host tools, and native tools are false in effective capabilities.

At startup, an explicit `default_model` must exist. Without one, exactly one visible SDK model
must have `is_default=True`; zero or multiple defaults raise `ConfigurationError`. The logical
level and per-call `InvocationConfig.reasoning_effort` map to the identically named SDK effort
only after catalog validation. `InvocationConfig.model` is a one-call override and never
changes later calls or persistent session configuration.

## Input and Brain Invocation

`RuntimeInput.from_value()` remains the normalization boundary. For an ephemeral `brain` call:

1. concatenate system-message text into thread `developer_instructions` using stable ordering;
2. serialize user/assistant/tool messages into an escaped, role-labelled text transcript;
3. create `thread_start(ephemeral=True)` with the selected model and fail-closed execution
   settings;
4. execute the turn through the shared turn runner;
5. discard the ephemeral handle and workspace after terminal cleanup.

Empty effective user input fails before SDK access. `structured` uses the same profile lookup
but schema binding always raises `CapabilityError` in this phase.

## Persistent Sessions

`session(profile="session")` resolves the medium effort and active default model, creates a
new empty isolated workspace, starts `ephemeral=False`, and encodes its SDK thread ID through
`SessionCodec`. The configuration fingerprint hashes provider, SDK compatibility range, model,
effort, profile, context policy, security policy, and sandbox mapping.

`resume_session()` decodes the descriptor, rejects any provider other than `codex`, rechecks
the current ChatGPT identity, recomputes the configuration fingerprint, confirms permissions
cannot expand, then calls `thread_resume()`. Missing rollout/thread maps to
`SessionNotFoundError`; other mismatches map to `SessionMismatchError`.

Each session owns an `asyncio.Lock`-protected active-turn slot shared across handles in the
runtime. Contention fails immediately with `SessionBusyError`. Persistent turns accept exactly
one or more `user` messages and reject `system`, `assistant`, or `tool` roles with
`ContextPolicyError`.

`close()` interrupts active work and releases the local handle/workspace while retaining the
Codex thread. `archive()` uses the public SDK operation. `delete()` uses `_compat.py`, which
calls the existing SDK client's generic typed request with `thread/delete`,
`ThreadDeleteParams`, and `ThreadDeleteResponse`. The shim is version-checked, private, and
covered by focused tests. `migrate_session()` raises `CapabilityError` without provider access.

## Fail-Closed Workspace and Sandbox

Every ephemeral call and session receives a unique empty directory owned by the runtime. No
application cwd or readable root is inherited through Proteo configuration. Thread creation
and turns use `Sandbox.read_only` and `ApprovalMode.deny_all`; invocation overrides cannot
change them. Cleanup uses exact recorded paths and is idempotent.

This prevents writes and interactive approvals through the supported SDK surface but is not
advertised as strong process or read-root isolation. Strong isolation, restricted absolute
reads, network enforcement, and platform security tests remain Phase 6.

## Shared Turn Runner and Events

Both `ainvoke()` and `astream()` create an SDK turn handle and consume the same notification
mapper. The runner accumulates final response, usage, status, and safe diagnostics while
emitting Proteo events. `ainvoke()` drains it and returns the result; `astream()` yields its
events.

Extend `RuntimeEvent` with `result: RuntimeResult[Any] | None`, populated only on terminal
`INVOCATION_COMPLETED`. Add `SESSION_CLOSED`, `SESSION_ARCHIVED`, and `SESSION_DELETED` event
kinds. Update `FakeRuntime` so a drained fake stream follows the same terminal-result contract.
Raw SDK notifications are never placed in event metadata.

Map agent-message deltas to `OUTPUT_TEXT_DELTA`, token updates to
`TOKEN_USAGE_UPDATED`, completed status to turn/invocation terminal events, and interruption to
`INTERRUPTED`. Event IDs are Proteo-generated and sequences are monotonic per runtime.

## Usage, Raw Data, and Errors

Map the SDK total usage breakdown to input, cached input, output, reasoning, and total tokens;
map turn duration and set `turn_count=1`. Cache-write tokens and context-window information may
appear only in a sanitized immutable `usage.raw` mapping.

`include_raw=False` always produces `raw=None`. When true, `raw` is a plain immutable mapping
containing safe turn ID, status, timestamps, item type names, and sanitized usage—not SDK
objects, prompts, responses duplicated outside `value`, account data, paths, or credentials.

Map missing/wrong auth to `AuthenticationError`; closed/busy transport to
`RuntimeUnavailableError`; unsupported model/profile/effort to `CapabilityError`; bad resume
to session errors; interrupted status to `InterruptedError`. Apply `asyncio.timeout()` when
requested. Timeout or caller cancellation first interrupts the active turn, then raises
`RuntimeTimeoutError` or `CancellationError`. If interruption cannot be confirmed, close the
SDK client and mark the runtime unavailable before reuse. Preserve safe causes with `raise ...
from`, and perform no automatic retry.
