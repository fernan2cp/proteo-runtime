# ADR 0004 — Ephemeral task context and controlled execution profiles

- **Status:** Accepted
- **Date:** 2026-09-17
- **Decision owners:** Proteo Runtime maintainers
- **Supersedes:** the previous built-in `controlled_agent` profile semantics only
- **Related ADRs:** ADR 0001 — Runtime boundary and project scope; ADR 0003 — Host-managed tools

## Context

Proteo Runtime is designed to use subscription-backed agent runtimes as controlled reasoning engines without forcing stateful runtimes into a purely stateless chat-model abstraction.

The current built-in `controlled_agent` profile does not fully satisfy that goal. It is defined as:

```text
lifecycle:       ephemeral invocation
context:         external
security:        controlled_tools
host tools:      explicit registry
```

and the Codex adapter starts a new ephemeral provider thread for each invocation.

This gives strong isolation and explicit host-owned context, but it also discards runtime-local conversational state after every call. As a result, a multi-turn controlled task cannot naturally reuse Codex's own task-local context unless the host replays context or switches to a persistent/custom session.

The problem is conceptual rather than security-related: the design coupled two independent dimensions:

```text
ephemeral lifecycle
```

and:

```text
external context ownership
```

`ephemeral` should describe durability, not turn count.

A runtime context may be ephemeral and still span multiple turns, provided it is explicitly bounded and discarded when its owner finishes.

The existing one-shot behavior remains valid for callers that intentionally want a clean controlled invocation every time, so it should not be removed.

## Decision

Proteo Runtime will expose two distinct built-in controlled execution profiles.

### `controlled_turn`

`controlled_turn` preserves the current one-shot behavior.

```text
lifecycle:       ephemeral invocation
context:         external
security:        controlled_tools
host tools:      explicit registry
runtime history: not reused
```

Each invocation starts from a clean runtime context.

Typical use cases:

- isolated tool-enabled reasoning;
- host-replayed context;
- deterministic workflow nodes;
- cases where cross-turn provider memory is undesirable.

### `controlled_agent`

`controlled_agent` becomes the default profile for a bounded multi-turn controlled agent task.

```text
lifecycle:       ephemeral task
context:         runtime
security:        controlled_tools
host tools:      explicit registry
runtime history: reused within the active task only
```

One provider runtime context is created when the task starts and reused across its turns.

When the task closes:

```text
provider runtime context -> discarded
Proteo task context      -> closed
resume capability        -> unavailable
```

A later `controlled_agent` task starts from a clean context.

`controlled_agent` is therefore stateful within one task but is not a persistent or resumable session.

### Persistent sessions remain separate

`RuntimeSession` continues to represent durable/resumable runtime context.

The lifecycle distinction is:

```text
brain / structured
    invocation-scoped
    external context
    one-shot

controlled_turn
    invocation-scoped
    external context
    controlled host tools

controlled_agent
    task-scoped
    runtime-owned context
    controlled host tools
    multi-turn
    ephemeral after task close

session
    persistent runtime-owned context
    resumable through an opaque Proteo session identifier
```

## Lifecycle contract

The new `controlled_agent` behavior MUST have an explicit task boundary.

Proteo MUST NOT make a reusable `RuntimeModel` silently retain provider history indefinitely because that would make task ownership ambiguous and could accidentally mix contexts from unrelated tasks or users.

The public API may use a task, agent, ephemeral-session, or equivalent abstraction, but it must make these operations explicit:

```text
open controlled-agent task
    -> create one ephemeral provider context

invoke turn 1
invoke turn 2
invoke turn N
    -> reuse the same provider context

close task
    -> discard runtime context
```

The final public API shape is intentionally left to the implementation SDD.

## Security and tool authority

This decision does not weaken the Phase 5 host-tool boundary.

For both `controlled_turn` and `controlled_agent`:

- the host owns executable tool bindings;
- exact permission checks remain host-side;
- tool schemas remain explicit;
- native unrestricted Codex tools remain denied;
- sandbox and security-policy enforcement remain unchanged;
- approvals remain host-controlled and fail closed;
- tool execution remains observable;
- provider context MUST NOT grant additional authority.

Runtime-owned conversational state and host-owned execution authority remain separate concerns.

## Context ownership

For `controlled_agent`, Proteo/runtime owns task-local conversational state.

The host/framework continues to own:

```text
business state
workflow state
human decisions
artifacts
authorization state
global application state
```

The host should not replay assistant/tool history that is already owned by the active runtime task unless an explicit recovery/migration mechanism exists and is observable.

This preserves the project invariant:

> The runtime owns local execution semantics; the framework owns workflow and global state.

## Provider-neutral requirement

The public contract MUST NOT expose Codex `thread_id` as the Proteo task API.

Provider adapters may implement the task using provider-native ephemeral threads or equivalent stateful contexts, but applications interact only with neutral Proteo lifecycle contracts.

A provider that cannot preserve multi-turn ephemeral task context MUST fail capability checks rather than silently degrade `controlled_agent` to `controlled_turn`.

## Configuration

`controlled_turn` becomes a new built-in profile key.

`controlled_agent` keeps its existing public name but changes semantics before 1.0.

Both profiles require explicit model/reasoning mappings. They may initially resolve to the same provider model and reasoning effort, but configuration must treat them as distinct profile keys.

Existing custom profiles remain supported.

## Observability

A `controlled_agent` task must be observable as one bounded runtime context containing multiple turns.

Observability should make it possible to correlate:

```text
task opened
turn 1
tool calls
turn 2
tool calls
...
task closed
```

without representing the task as a durable persistent session.

If existing neutral events cannot express the lifecycle clearly, the implementation may add minimal task/context lifecycle events or metadata.

It MUST NOT fabricate persistent-session events solely to reuse existing tracing structures.

`controlled_turn` continues to produce isolated per-invocation traces.

## Concurrency and safety

Only one active turn should execute at a time within the same runtime-owned controlled-agent task unless a future explicit contract allows otherwise.

The implementation must define fail-closed behavior for:

- concurrent turns on one task;
- task reuse after close;
- provider context loss;
- interrupted or failed turns;
- runtime shutdown with active tasks;
- attempts to expand tool authority while a task is active.

Tool registry, permissions, model binding, reasoning level, context policy, and security policy should be frozen for the task lifetime unless the SDD defines an explicit safe rebinding operation.

## Compatibility and migration

This is a pre-1.0 behavioral correction.

Code that currently uses:

```python
profile="controlled_agent"
```

and relies on a clean provider context on every invocation must migrate to:

```python
profile="controlled_turn"
```

Code that expects a controlled multi-turn agent should continue to use:

```python
profile="controlled_agent"
```

through the new explicit ephemeral task lifecycle.

Proteo MUST NOT silently alias the new `controlled_agent` back to one-shot behavior, because that would preserve the architectural defect this ADR corrects.

## Alternatives considered

### Keep the current `controlled_agent` semantics

Rejected as the default meaning of `controlled_agent`.

Pros:

- already implemented;
- strong per-invocation isolation;
- simplest lifecycle;
- easy host-owned context.

Cons:

- discards provider-native task context;
- forces host context replay for multi-turn work;
- makes Codex behave closer to a stateless chat model;
- conflicts with Proteo's stated goal of preserving stateful agent-runtime semantics.

The behavior remains available as `controlled_turn`.

### Make `RuntimeModel.ainvoke()` implicitly stateful

Rejected.

A model object does not provide a clear task ownership boundary. Reusing it across users, requests, graph branches, or unrelated tasks could leak context.

Stateful behavior requires an explicit lifecycle owner.

### Use persistent `RuntimeSession` for all multi-turn controlled agents

Rejected as the default.

Persistent sessions solve a different problem: durability and resumability beyond the active task.

Using them for every controlled multi-turn task would add persistence semantics where none are required and blur the distinction between task-local runtime state and durable session state.

### Require applications to create custom profiles

Rejected for the common controlled-agent case.

The profile represents a first-class intended Proteo behavior and should be available through a safe built-in contract.

## Consequences

### Positive

- preserves Codex/provider-native multi-turn behavior within a task;
- avoids replaying full runtime history from the host;
- preserves host control over tools and permissions;
- cleanly separates durability from context ownership;
- retains the existing one-shot behavior through `controlled_turn`;
- makes execution-profile names better reflect actual semantics;
- aligns Proteo's implementation with its original stateful-runtime philosophy.

### Negative

- introduces an additional built-in profile;
- requires a new explicit ephemeral task lifecycle contract;
- increases provider-adapter lifecycle complexity;
- requires new capability, observability, concurrency, and cleanup tests;
- changes pre-1.0 `controlled_agent` semantics and therefore requires migration documentation;
- framework adapters must be able to carry an ephemeral task handle across the graph region that owns the task.

## Non-goals

This ADR does not:

- make `controlled_agent` durable or resumable;
- add application-level memory;
- persist ephemeral task history in Proteo;
- expose provider thread identifiers as public API;
- change `brain` or `structured` semantics;
- add structured output to controlled-agent tool loops;
- change tool permission or approval semantics;
- change business/workflow state ownership;
- define the final Python API name for the task-scoped lifecycle.

## Implementation requirement

Implementation MUST begin with an SDD that defines:

- the provider-neutral ephemeral task lifecycle contract;
- profile and configuration changes;
- Codex adapter reuse of one ephemeral context across turns;
- tool bridge lifecycle across turns;
- capability semantics;
- observability/correlation;
- concurrency and failure behavior;
- LangGraph integration;
- fake/contract/integration tests;
- migration from old `controlled_agent` behavior to `controlled_turn`.

The historical Phase 5 SDD and ADR 0003 should not be rewritten. This ADR records the later architectural correction and should be referenced by the new implementation plan.
