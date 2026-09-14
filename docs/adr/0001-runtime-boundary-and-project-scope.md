# ADR 0001 — Runtime boundary and project scope

- **Status:** Accepted
- **Date:** 2026-09-14

## Context

Proteo Runtime provides a framework-agnostic Python abstraction for using subscription-backed agent runtimes as controlled reasoning engines. It is not intended to replace an orchestration framework, nor to act as a generic model router or complete agent harness.

Existing tools already cover important adjacent use cases: direct provider SDK usage, LangChain/LangGraph chat-model adapters, and full agent runtimes. Proteo therefore needs a clear architectural boundary so that users can decide when this abstraction is useful and when a simpler or more integrated alternative is preferable.

## Decision

Proteo Runtime will sit between the host/framework and the provider runtime:

```text
Application / Agent Framework
          │
          │ owns workflow and global state
          ▼
     Proteo Runtime
          │
          │ normalizes runtime semantics
          ▼
Subscription-backed agent runtime
```

Proteo owns the runtime-facing boundary: lifecycle, profiles, sessions, structured output, context policy, capabilities, security policy, host-tool contracts, usage, errors, retries, cancellation and observability.

The host/framework owns business workflow, graph topology, global state, application persistence, business-level retries, provider fallback and routing.

For the initial Codex implementation, Proteo uses the official stable SDK as the canonical provider integration. Provider transport details remain internal and must not become part of the provider-neutral public API.

## Why not simply use a chat-model adapter?

A chat-model adapter is often the better choice when the requirement is only:

```text
prompt/messages
      ↓
subscription-backed model
      ↓
text or structured response
```

If an application only needs Codex to behave like a conventional LangChain/LangGraph model, an existing chat-model integration is simpler and introduces less abstraction.

Proteo becomes useful when the application also needs explicit runtime semantics such as sessions, lifecycle, context ownership, security profiles, effective capabilities, host-controlled tools, cancellation and provider-neutral diagnostics.

## Alternatives and when they are preferable

### Direct provider SDK

Prefer direct SDK usage when:

- only one provider/runtime is needed;
- provider neutrality has little value;
- the application is comfortable managing provider-specific lifecycle and session concepts;
- minimizing abstraction is more important than portability.

Proteo is an additional layer. If that layer does not solve a concrete architectural problem, direct SDK usage is simpler.

### LangChain/LangGraph chat-model integrations

Prefer these when:

- the application is already centered on chat-model interfaces;
- API-like invocation is sufficient;
- provider-specific runtime semantics are not important;
- the desired abstraction is explicitly `BaseChatModel`-like behavior.

Proteo does not use a chat-model interface as its primary contract because stateful agent runtimes do not always map cleanly to stateless chat semantics.

### `open-langchain`

Prefer a library such as `open-langchain` when the primary goal is to expose subscription-backed providers through LangChain-compatible model interfaces with minimal integration work.

Proteo is more appropriate only when the application specifically wants a provider-neutral runtime layer with explicit session, lifecycle, capability, security and host-tool semantics independent of LangChain.

### Integrated agent harnesses

Prefer projects such as `agent-harness` or similar full agent runtimes when the application wants the library itself to provide orchestration capabilities such as agent loops, routing, fallback, memory, tool orchestration, sandboxing or multi-agent coordination.

Proteo intentionally leaves those responsibilities to the host/framework.

### Agent runtimes such as `sagent`

Prefer a complete agent-runtime library when the application is willing to adopt that runtime's own execution model, provider abstraction and session/tool semantics as the main application architecture.

Proteo is intended for applications where an external framework remains authoritative and the subscription-backed runtime is one controlled component inside that architecture.

## When Proteo Runtime is a good fit

Proteo is appropriate when several of the following are true:

- the application already has its own orchestration layer;
- provider-specific objects should not spread through application code;
- sessions require explicit lifecycle and context ownership;
- tool execution authority must remain with the host;
- provider capability and application permission must be separate concepts;
- normalized failures, usage and observability matter;
- more than one subscription-backed runtime may be supported over time;
- frameworks and providers should remain independently replaceable.

## When Proteo Runtime is not a good fit

Proteo is probably unnecessary when:

- the application only needs a few simple provider calls;
- a standard API-backed LLM already solves the problem;
- only a LangChain-compatible chat model is required;
- the application wants a complete agent framework rather than a lower-level runtime abstraction;
- provider neutrality has no expected value;
- the additional contracts around sessions, security, capabilities and lifecycle would add complexity without solving a real problem.

## Consequences

### Positive

- provider-specific runtime behavior is isolated from application code;
- LangGraph remains an adapter rather than a core dependency;
- future providers can be added behind the same runtime boundary;
- security, sessions, capabilities, usage and errors can be treated consistently;
- Proteo can support both API-like inference and stateful runtime execution without pretending they are identical.

### Negative

- Proteo adds another abstraction over official SDKs;
- some provider-specific features may lag upstream releases;
- some advanced provider features may need to remain experimental or provider-specific;
- simple applications may not benefit from the abstraction;
- provider-neutral contract tests become an ongoing maintenance cost.

## Non-goals for 1.0

Proteo 1.0 does not own:

- automatic provider routing;
- automatic cross-provider fallback;
- API-backed fallback orchestration;
- multi-agent orchestration;
- application-level memory;
- distributed runtime hosting;
- replacement of LangGraph or other orchestration frameworks;
- strong OS/container isolation unless an explicit isolation adapter is configured.

## Revisit conditions

Revisit this ADR if:

- provider runtimes converge on a common standard that makes the abstraction redundant;
- major frameworks provide equivalent provider-neutral runtime semantics;
- Proteo begins to own orchestration or routing responsibilities;
- additional providers demonstrate that the current contracts cannot represent their semantics without provider-specific leakage.

Until then, the guiding boundary is:

> The model decides what should happen; the host decides what is allowed to happen; the runtime provides reasoning and local execution semantics; the framework owns workflow and global state; observability records what happened.
