# Proteo Runtime

**Project Charter, Architecture and Implementation Guide**

**Status:** Draft v0.3\
**License:** MIT\
**Primary language:** Python\
**Initial runtime:** OpenAI Codex\
**Initial framework integration:** LangGraph\
**Initial observability integrations:** LangSmith and OpenTelemetry\
**Target:** Stable, installable open-source Python library

> **Project name:** Proteo Runtime
> **PyPI distribution:** `proteo-runtime`
> **Python namespace:** `proteo_runtime`
> **CLI command:** `proteo-runtime`

---

# 1. Project Vision

**Proteo Runtime** will provide a framework-agnostic Python abstraction layer that allows AI applications and agent frameworks to use subscription-backed agent runtimes as controlled LLM engines.

The initial implementation will use OpenAI Codex authenticated through a ChatGPT/Codex subscription.

The library must preserve the capabilities normally expected from API-backed LLM integrations while addressing the additional complexity introduced by stateful agent runtimes:

- structured outputs;
- model and reasoning configuration;
- context ownership;
- session lifecycle;
- host-managed tools;
- execution security;
- retries and failures;
- observability;
- token and latency accounting;
- capability discovery;
- framework interoperability.

The first supported framework will be LangGraph, but LangGraph must never become a dependency of the core architecture.

The long-term architectural goal is to allow additional subscription-backed or agentic runtimes to be implemented without modifying existing application code or breaking the public API.

Possible future runtimes include Claude Code, Grok runtimes, Google Antigravity or any other service exposing a suitable programmable runtime.

Those integrations are explicitly outside the scope of the initial implementation.

---

# 2. Core Philosophy

The library must follow five fundamental principles.

## 2.1 The host application owns execution authority

The model may decide what should happen.

The host application decides what is allowed to happen.

A model request such as:

```text
Use get_customer(customer_id=123)
```

may be accepted.

A model receiving unrestricted access to:

```text
execute_sql(...)
run_shell(...)
write_file(...)
http_request(...)
```

must not be the default architecture.

The security boundary must exist in code and runtime configuration, not only in prompts.

---

## 2.2 Global state belongs to the host

LangGraph, another agent framework, or the calling application remains the source of truth for global application state.

The underlying runtime may own local task state when explicitly configured to do so.

For example:

```text
Application state
────────────────────────────
goal
tasks
dependencies
human decisions
business state
artifacts
workflow state
```

remains host-owned.

A persistent Codex worker may independently retain:

```text
Worker-local state
────────────────────────────
technical investigation
previous worker turns
files inspected
tool results
discarded hypotheses
local reasoning history
```

The library must prevent accidental duplication of these two forms of context.

---

## 2.3 Runtime differences should be abstracted, not denied

For simple inference, Codex should feel similar to a normal API-backed LLM.

For stateful or agentic execution, runtime-specific behavior must remain explicit where hiding it would create ambiguity or unsafe assumptions.

The library must therefore support both:

```text
LLM-like invocation
```

and:

```text
agent-runtime invocation
```

without pretending that they are always semantically identical.

---

## 2.4 Observability is part of correctness

Tracing is not an optional debugging add-on.

Every important runtime decision should be observable:

- selected profile;
- resolved model;
- reasoning effort;
- thread;
- turn;
- duration;
- token usage;
- cache usage;
- retry;
- tool request;
- tool execution;
- validation error;
- interruption;
- failure;
- fallback.

The provider-neutral event contract is part of the core from Phase 0. LangSmith support is required from Phase 4 onward and in 1.0.

The core must expose provider-neutral observability contracts so LangSmith, OpenTelemetry and future exporters do not become architectural dependencies.

---

## 2.5 Safe defaults

A developer should have to explicitly request additional capabilities.

The default should be:

```text
reasoning allowed
external effects denied
```

not:

```text
everything allowed unless explicitly disabled
```

---

# 3. Normative Requirements

The following requirements define the design contract of the project.

Implementation details may change.

These requirements should not change without an explicit architectural decision.

---

## R-001 — Installable library

The project MUST be structured as a standard installable Python library from its first version.

The canonical distribution name MUST be `proteo-runtime` and the Python import namespace MUST be `proteo_runtime`.

It MUST use modern Python packaging through `pyproject.toml`.

The final goal is installation through:

```bash
pip install proteo-runtime
```

---

## R-002 — Framework-agnostic core

The core package MUST NOT depend on LangGraph.

LangGraph MUST be implemented as an adapter layer.

Future adapters must be possible without modifying runtime internals.

---

## R-003 — Transparent basic LLM usage

The `brain` and `structured` profiles SHOULD behave as closely as reasonably possible to normal LLM invocation.

The developer should be able to perform operations conceptually equivalent to:

```python
result = await model.ainvoke(prompt)
```

without manually managing Codex threads, turns or App Server messages.

---

## R-004 — Declarative model configuration

Model selection MUST be configurable through external configuration.

JSON MUST be supported.

Configuration MUST allow selection based on:

```text
profile
+
logical reasoning level
+
runtime
```

Configuration MUST use a strict, versioned JSON schema. The initial schema version MUST be `1`, and unknown keys MUST fail with an error that identifies their JSON path.

Configuration selection MUST use, in increasing precedence: versioned defaults, `PROTEO_RUNTIME_CONFIG`, explicit `config_path`, typed runtime initialization arguments and typed invocation overrides. An explicit path wins over the environment variable. Implicit current-directory or parent-directory discovery is forbidden.

Arbitrary environment-variable overrides are outside the 1.0 contract. Secrets MUST NOT be stored in the model configuration file.

---

## R-005 — Logical reasoning levels

Applications SHOULD request logical levels rather than hard-code provider models whenever possible.

Initial logical levels:

```text
low
medium
high
ultra
```

A configuration may resolve:

```text
brain.medium
```

to:

```text
model = gpt-X
reasoning_effort = medium
```

The application must not need to know that mapping.

Each release MUST ship tested, versioned default mappings. The resolver MUST NOT infer a logical level from a model name. Missing or unavailable mappings MUST fail explicitly and MUST NOT silently select another model or level.

---

## R-006 — Execution profiles

The library MUST include predefined profiles.

Initial target profiles:

```text
brain
structured
session
controlled_agent
native
```

Users MUST be able to define advanced custom profiles.

---

## R-007 — Subscription-backed runtime

The Codex 1.0 implementation MUST support ChatGPT subscription authentication managed by the official Codex runtime.

Proteo Runtime MUST:

- reuse authentication state exposed by Codex;
- NOT implement its own OAuth flow;
- NOT read, copy, return or persist Codex access tokens;
- expose only non-secret identity metadata made available by the official runtime.

Each runtime instance supports one active subscription-backed identity. Provider-neutral contracts MUST represent identity opaquely and MUST NOT assume that a provider can expose only one identity in future versions.

API-key authentication is outside the Codex 1.0 contract. Subscription-specific authentication MUST remain isolated from the provider-neutral core.

---

## R-008 — Structured output as a first-class capability

Structured output MUST be treated as a core feature.

The abstraction MUST support:

```text
JSON Schema
Pydantic models
```

Provider-side schema enforcement SHOULD be used where available.

Host-side validation MUST still occur.

Invalid structured output MUST be handled through a configurable validation/retry policy.

The default MUST allow two total attempts. Raw output MUST be absent unless the caller explicitly requests `include_raw=True`, and it MUST remain subject to redaction policy.

---

## R-009 — Explicit context ownership

The library MUST expose context policies.

Initial policies:

```text
external
runtime
hybrid
```

The selected policy MUST determine who owns conversational history.

The library MUST reject obvious attempts to duplicate persistent runtime context through host-supplied history under `runtime` or `hybrid`. It MUST raise `ContextPolicyError` unless explicit, observable context replay is enabled.

---

## R-010 — LangSmith support from Phase 4 and 1.0

The project MUST provide LangSmith instrumentation from Phase 4 onward and in 1.0. Earlier internal milestones may operate with the provider-neutral event contract only.

Tracing MUST include enough metadata to analyze:

```text
runtime
profile
model
reasoning effort
thread
turn
latency
tokens
cache tokens
tool calls
retries
errors
```

---

## R-011 — Observability-neutral core

The core MUST expose an observability contract independent of LangSmith.

LangSmith MUST be implemented as an observer/exporter.

Proteo OpenTelemetry export MUST be implemented as an official provider-neutral observer/exporter for 1.0 and correlated with LangSmith through neutral invocation, session and turn identifiers.

The Codex provider MAY additionally configure Codex-native OpenTelemetry as explicit, capability-gated enrichment. Provider-native telemetry MUST remain optional, disabled by default, and isolated from the neutral observability contract. It SHOULD use Proteo correlation identifiers when the upstream runtime permits propagation, but Proteo MUST NOT guarantee a shared OpenTelemetry `trace_id` unless the provider supports parent-context propagation.

Exporter failures MUST be isolated from inference by default, reported as local diagnostics and exposed as degraded observability. An explicit strict mode MAY raise `ObservabilityError`.

OpenTelemetry MUST describe only activity actually exposed by Proteo Runtime, provider event streams or explicitly enabled provider-native telemetry. Neither layer may claim access to hidden reasoning or unreported provider activity. The architecture SHOULD still allow Phoenix, Datadog or custom exporters.

---

## R-012 — Runtime abstraction

Provider implementations MUST conform to provider-neutral contracts.

At minimum:

```text
Runtime
RuntimeModel
RuntimeSession
RuntimeCapabilities
RuntimeUsage
RuntimeEvent
RuntimeInput
RuntimeMessage
RuntimeResult
RuntimeIdentity
```

Provider-neutral runtime contracts MUST support both simple inference and stateful agentic execution without constraining runtime implementations to a specific interaction model.

---

## R-013 — MIT license

The project MUST be published under the MIT license unless a future dependency creates a legal incompatibility requiring reconsideration.

---

## R-014 — Host-managed tools

Application tools MUST be executed by the host application.

The runtime may request a tool.

It MUST NOT directly own arbitrary application-side execution authority.

---

## R-015 — Native runtime tools must be restrictable

The library MUST support profiles where the runtime cannot freely:

```text
write files
execute shell commands
access databases
use arbitrary network resources
open browsers
invoke computer-use tools
use arbitrary MCP servers
```

Restrictions MUST be enforced by runtime configuration and process isolation where necessary.

Prompts alone are not a security mechanism.

---

## R-016 — Security profiles

The library MUST provide reusable security policies.

Initial public policies:

```text
isolated
read_only
controlled_tools
native
```

These names use `snake_case` and form part of the intended 1.0 public vocabulary.

---

## R-017 — Capability discovery

Features MUST NOT be inferred exclusively from provider identity.

The library MUST expose provider capabilities separately from effective capabilities.

`runtime.capabilities()` reports provider/runtime support. `model.effective_capabilities()` reports the intersection of provider support, model support, execution profile, security policy and host configuration.

Example:

```python
RuntimeCapabilities(
    structured_output=True,
    ephemeral_sessions=True,
    persistent_sessions=True,
    streaming=True,
    interruption=True,
    host_tools=True,
    native_tools=True,
    sandbox=True,
    usage_reporting=True,
)
```

Features unavailable on a runtime MUST fail explicitly rather than silently degrading.

---

## R-018 — Fallback-ready architecture

The architecture MUST allow future fallback chains.

Example:

```text
subscription runtime
        ↓ unavailable
API runtime
        ↓ unavailable
alternate runtime
```

Proteo Runtime 1.0 does NOT implement automatic API fallback, account rotation or cross-provider routing. It MUST instead expose normalized, actionable failures so the host/orchestrator can decide whether to retry, fall back to an API-backed model, select another subscription runtime or require human intervention.

The public contracts must not prevent future routing layers, but orchestration policy remains outside the provider-neutral core.

---

## R-019 — Async-first implementation

The internal architecture MUST be asynchronous first.

The primary public API SHOULD expose:

```python
ainvoke()
astream()
```

A synchronous convenience layer MAY be provided.

The sync API must not dictate core architecture.

---

## R-020 — Explicit lifecycle management

The library MUST manage:

```text
runtime startup
runtime shutdown
provider client/transport lifecycle
thread lifecycle
session lifecycle
cancellation
timeouts
interruptions
```

Resource leaks caused by forgotten Codex processes or threads must be actively prevented.

Closing a persistent session MUST release resources without deleting history. Archiving and deletion MUST be explicit operations. Only one turn may be active per session; concurrent invocation MUST raise `SessionBusyError`.

Persistent sessions MUST expose a versioned, self-contained and opaque Proteo session identifier. Proteo Runtime 1.0 MUST NOT require an internal alias database to resume a session. Session identifiers MUST contain no credentials or access tokens and MUST be treated as untrusted input rather than as a security boundary.

---

## R-021 — Stable project error model

Provider exceptions MUST NOT become the public error contract.

The library MUST define its own error hierarchy.

Initial public errors:

```text
AgentRuntimeError
AuthenticationError
RuntimeUnavailableError
CapabilityError
ConfigurationError
StructuredOutputError
ToolDeniedError
ToolExecutionError
ContextLimitError
ContextPolicyError
RuntimeTimeoutError
InterruptedError
CancellationError
RetryExhaustedError
SecurityPolicyError
SessionBusyError
SessionMismatchError
SessionNotFoundError
ObservabilityError
```

Provider errors may be preserved as causes.

---

## R-022 — Tests must not consume subscription quota by default

Unit tests MUST use fake or mock transports.

Running:

```bash
pytest
```

must not call a real Codex runtime.

Real-runtime tests MUST be explicitly marked as integration tests.

---

## R-023 — Compatibility isolation

The stable Python package `openai-codex` MUST be the canonical Codex transport and a base dependency of `proteo-runtime`. It controls the local App Server over JSON-RPC and includes a compatible pinned runtime.

Direct JSON-RPC access MAY be used internally only for capabilities absent from the stable SDK. It MUST remain behind an experimental provider boundary and MUST NOT become an equivalent public transport.

Changes in Codex MUST NOT require changes to application-facing APIs whenever avoidable.

Experimental Codex APIs MUST be especially isolated.

---

## R-024 — Provider-neutral usage accounting

The library MUST expose a normalized usage model.

Candidate fields:

```text
input_tokens
cached_input_tokens
output_tokens
reasoning_tokens
total_tokens
duration_ms
turn_count
tool_call_count
retry_count
```

Unavailable metrics may be `None`.

---

## R-025 — Diagnosticability

The project MUST provide a `doctor` diagnostic command before the stable 1.0 release.

The command must inspect:

```text
installation
runtime availability
authentication
subscription/account status when exposed
models
capabilities
configuration
security profile
observability configuration
experimental features
version compatibility
```

---

## R-026 — Security before convenience

A feature MUST NOT become available merely because the upstream runtime supports it.

The library's active security policy determines availability.

Provider capability and application permission are separate concepts.

---

## R-027 — No hidden secrets

The library MUST avoid placing credentials in:

```text
JSON configuration
LangSmith traces
runtime metadata
tool payload logs
exception messages
```

Sensitive-data redaction MUST be supported by the observability layer.

---

## R-028 — Public API stability

Before `1.0`, public modules and contracts must be explicitly labeled.

At `1.0`, Semantic Versioning MUST govern compatibility.

Internal transports, protocol models and provider-specific objects MUST NOT accidentally become part of the stable API.

---

## R-029 — Clear experimental boundaries

Experimental upstream features, especially Codex `dynamicTools`, MUST be clearly identified.

The library SHOULD expose them through:

```text
capability checks
feature flags
experimental modules
```

rather than silently mixing them into stable APIs.

---

# 4. Project Scope

## 4.1 Included in the initial project

The complete initial project through 1.0 includes:

- Python package architecture;
- Codex subscription authentication;
- Codex runtime lifecycle;
- model discovery;
- model configuration;
- reasoning-level configuration;
- ephemeral execution;
- persistent sessions;
- brain profile;
- structured profile;
- session profile;
- controlled-agent profile;
- advanced custom profiles;
- structured output;
- Pydantic validation;
- async invocation;
- streaming;
- cancellation;
- context ownership policies;
- LangGraph adapter;
- LangSmith tracing;
- OpenTelemetry export;
- normalized usage metrics;
- host-managed tools;
- security policies;
- runtime isolation;
- retries;
- timeout handling;
- normalized errors;
- capability discovery;
- `doctor` CLI;
- tests;
- benchmarks;
- stable public API;
- documentation;
- examples;
- packaging;
- PyPI readiness;
- contributor documentation.

---

## 4.2 Explicitly excluded from the initial project

The following are future improvements and MUST NOT delay 1.0:

```text
Claude Code implementation
Grok implementation
Antigravity implementation
other provider runtimes
framework adapters other than LangGraph
distributed remote runtime hosting
hosted SaaS control plane
graphical management UI
automatic provider cost optimization
automatic cross-provider routing
```

Their future integration must nevertheless remain architecturally possible.

---

# 5. High-Level Architecture

```text
                         User Application
                                │
                   LangGraph / direct Python
                                │
                    ┌───────────▼───────────┐
                    │   Framework Adapter   │
                    │                       │
                    │   LangGraph initially │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   Model Abstraction   │
                    │                       │
                    │ invoke / stream       │
                    │ structured output     │
                    │ sessions              │
                    └───────────┬───────────┘
                                │
                ┌───────────────▼────────────────┐
                │          Runtime Core          │
                │                                │
                │ Profiles                       │
                │ Model resolution               │
                │ Context policies               │
                │ Capability checks              │
                │ Structured validation          │
                │ Retry policies                 │
                │ Usage normalization            │
                │ Lifecycle                      │
                └───────────────┬────────────────┘
                                │
                ┌───────────────▼────────────────┐
                │        Provider Runtime        │
                │                                │
                │             Codex              │
                └───────────────┬────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │   openai-codex SDK    │
                    │   canonical path      │
                    └───────────┬───────────┘
                                │
                    pinned local Codex runtime
                    / App Server over JSON-RPC
                                │
                    ChatGPT / Codex account

        Experimental escape hatch:
        Codex provider ──► direct App Server compatibility bridge
                           only for SDK capability gaps
```

Cross-cutting components:

```text
Runtime Core
    │
    ├──── Tool Registry ─────── Host Workflows
    │
    ├──── Security Engine
    │
    ├──── Event Bus
    │          │
    │          ├─────────────── LangSmith
    │          └─────────────── OpenTelemetry
    │
    ├──── Usage / Metrics
    │
    └──── Configuration
```

---

# 6. Package Architecture

Proposed structure:

```text
src/
└── proteo_runtime/
    │
    ├── core/
    │   ├── runtime.py
    │   ├── model.py
    │   ├── session.py
    │   ├── capabilities.py
    │   ├── profiles.py
    │   ├── context.py
    │   ├── usage.py
    │   ├── events.py
    │   ├── retry.py
    │   └── errors.py
    │
    ├── config/
    │   ├── loader.py
    │   ├── models.py
    │   ├── validation.py
    │   └── defaults.py
    │
    ├── providers/
    │   └── codex/
    │       ├── runtime.py
    │       ├── sdk.py
    │       ├── capabilities.py
    │       ├── auth.py
    │       ├── mapping.py
    │       ├── telemetry.py
    │       └── experimental/
    │           └── app_server.py
    │
    ├── tools/
    │   ├── registry.py
    │   ├── definitions.py
    │   ├── executor.py
    │   ├── permissions.py
    │   └── validation.py
    │
    ├── security/
    │   ├── policy.py
    │   ├── profiles.py
    │   ├── sandbox.py
    │   └── isolation.py
    │
    ├── observability/
    │   ├── base.py
    │   ├── events.py
    │   ├── redaction.py
    │   ├── langsmith.py
    │   └── opentelemetry.py
    │
    ├── integrations/
    │   └── langgraph/
    │       ├── model.py
    │       ├── node.py
    │       ├── config.py
    │       └── callbacks.py
    │
    └── cli/
        ├── main.py
        └── doctor.py
```

The exact module names may evolve before 1.0.

Dependency direction MUST remain:

```text
integrations
      ↓
core
      ↑
providers
```

The core must never import LangGraph.

---

# 7. Core Contracts

## 7.1 Runtime

Conceptual interface:

```python
class Runtime(Protocol):

    async def start(self) -> None:
        ...

    async def close(self) -> None:
        ...

    async def capabilities(self) -> RuntimeCapabilities:
        ...

    async def models(self) -> list[ModelInfo]:
        ...

    def model(
        self,
        *,
        profile: str,
        level: str = "medium",
    ) -> RuntimeModel:
        ...

    async def session(
        self,
        *,
        profile: str = "session",
    ) -> RuntimeSession:
        ...

    async def resume_session(
        self,
        session_id: str,
    ) -> RuntimeSession:
        ...

    async def migrate_session(
        self,
        session_id: str,
        *,
        profile: str,
        level: str = "medium",
        security_policy: str,
    ) -> RuntimeSession:
        ...
```

`runtime.capabilities()` exposes provider support. Security-filtered support is obtained from `RuntimeModel.effective_capabilities()`.

---

## 7.2 RuntimeModel

```python
class RuntimeModel(Protocol, Generic[T]):

    async def ainvoke(
        self,
        input: RuntimeInput,
        *,
        config: InvocationConfig | None = None,
    ) -> RuntimeResult[T]:
        ...

    async def astream(
        self,
        input: RuntimeInput,
        *,
        config: InvocationConfig | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        ...

    def with_structured_output(
        self,
        schema: type[BaseModel] | dict,
    ) -> "RuntimeModel":
        ...

    async def effective_capabilities(self) -> RuntimeCapabilities:
        ...
```

---

## 7.3 RuntimeSession

The session abstraction represents stateful runtime context.

```python
class RuntimeSession(Protocol):

    id: str

    async def ainvoke(...) -> RuntimeResult[T]:
        ...

    async def astream(...) -> AsyncIterator[RuntimeEvent]:
        ...

    async def interrupt(self) -> None:
        ...

    async def close(self) -> None:
        ...

    async def archive(self) -> None:
        ...

    async def delete(self) -> None:
        ...
```

The host persists the opaque neutral session identifier and does not depend on a Codex thread object. Proteo Runtime does not provide an internal alias store in 1.0. Only one turn may be active per session. `close()` interrupts active work, releases subscriptions and local resources, and preserves resumability; `archive()` and `delete()` are explicit persistence operations. Runtime shutdown releases processes and subscriptions without deleting persistent sessions.

The canonical 1.0 session identifier is a versioned, self-contained descriptor encoded behind an opaque public string, conceptually:

```text
prt1.<base64url(versioned SessionDescriptor)>
```

The internal descriptor contains only non-secret resume metadata such as descriptor version, provider, provider session identifier, opaque identity fingerprint and frozen configuration/profile fingerprints. It contains no credentials or access tokens. The encoding is not an encryption or authorization boundary, and decoded fields are treated as untrusted input. An internal `SessionCodec` owns serialization and validation so later versions may change the encoding without exposing provider identifiers as public API.

Resume validates descriptor version, provider, active identity, provider session existence and frozen configuration. Descriptor contents can never expand current permissions. Incompatible resume raises `SessionMismatchError` and requires `runtime.migrate_session(...)`.

The 1.0 migration operation supports model, profile and security-policy changes only within the same Codex provider and active identity. Cross-provider or cross-identity migration raises `CapabilityError`. Every migration emits an auditable event. Persisted Codex rollout data remains managed by Codex; `close()` does not delete provider-persisted conversation data.

---

## 7.4 RuntimeInput and RuntimeResult

Proteo Runtime 1.0 supports text content only, represented through a small provider-neutral model:

```python
@dataclass(frozen=True)
class TextContent:
    text: str

@dataclass(frozen=True)
class RuntimeMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: tuple[TextContent, ...]

@dataclass(frozen=True)
class RuntimeInput:
    messages: tuple[RuntimeMessage, ...]
```

Passing `str` is syntactic sugar for one `user` message containing one `TextContent`. Framework-specific state, provider objects and arbitrary serializable values are not valid core input and must be converted by adapters.

Every invocation returns the same generic envelope:

```python
@dataclass(frozen=True)
class RuntimeResult(Generic[T]):
    value: T
    usage: RuntimeUsage
    runtime: str
    model: str
    profile: str
    reasoning_effort: str | None
    session_id: str | None
    turn_id: str | None
    diagnostics: tuple[RuntimeDiagnostic, ...] = ()
    raw: object | None = None
```

For text, `T` is `str`; for Pydantic, it is the validated model; for JSON Schema, it is a validated JSON-compatible value. `raw` is `None` unless `include_raw=True`, remains subject to redaction policy and is never exported by default. Provider failures are raised through the Proteo error hierarchy and may preserve the provider exception as their cause.

---

# 8. Model Configuration

Configuration is declarative, strict and versioned.

Example:

```json
{
  "schema_version": 1,
  "runtime": "codex",
  "profiles": {
    "brain": {
      "low": {
        "model": "gpt-model-a",
        "reasoning_effort": "low"
      },
      "medium": {
        "model": "gpt-model-b",
        "reasoning_effort": "medium"
      },
      "high": {
        "model": "gpt-model-c",
        "reasoning_effort": "high"
      }
    },

    "structured": {
      "low": {
        "model": "gpt-model-a",
        "reasoning_effort": "low"
      },
      "medium": {
        "model": "gpt-model-b",
        "reasoning_effort": "medium"
      }
    },

    "session": {
      "medium": {
        "model": "gpt-model-b",
        "reasoning_effort": "medium"
      }
    }
  }
}
```

Configuration precedence:

```text
versioned library defaults
        ↓
JSON selected by PROTEO_RUNTIME_CONFIG
        ↓
JSON selected by explicit config_path
        ↓
typed runtime initialization arguments
        ↓
typed invocation override
```

Higher levels override lower levels. An explicit path wins over the environment variable. Unknown keys and unsupported schema versions fail with path-aware errors.

Configuration is frozen when a model or session is created. Invocation overrides affect one call only; the provider adapter must prevent upstream sticky overrides from changing later calls.

---

# 9. Execution Profiles

The default profile matrix is:

| Execution profile | Lifecycle | Context policy | Security policy | Host tools |
|---|---|---|---|---|
| `brain` | ephemeral | `external` | `isolated` | disabled |
| `structured` | ephemeral | `external` | `isolated` | disabled |
| `session` | persistent | `runtime` | `isolated` | disabled |
| `controlled_agent` | ephemeral | `external` | `controlled_tools` | explicit registry only |
| `native` | explicit | explicit | `native` | provider-defined |

Persistent or hybrid controlled-agent behavior requires creating an explicit session.

## 9.1 Brain

Purpose:

```text
planner
router
classifier
evaluator
small reasoning nodes
```

Default semantics:

```text
ephemeral
external context ownership
no persistent runtime memory
no native external actions
host tools disabled unless explicit
structured output optional
```

The objective is API-like behavior.

---

## 9.2 Structured

Purpose:

```text
typed decisions
routing
validation
state transformation
planning outputs
```

Defaults:

```text
ephemeral
external context
output schema required
Pydantic validation
automatic schema retry policy
strict security
```

---

## 9.3 Session

Purpose:

```text
iterative reasoning
long investigations
multi-turn worker
```

Defaults:

```text
persistent runtime thread
runtime-owned local conversation
host owns global state
no automatic replay of full external history
```

---

## 9.4 Controlled Agent

Purpose:

```text
complex multi-step task
runtime chooses tools
host controls tool execution
```

Defaults:

```text
ephemeral
external context ownership
controlled_tools security policy
host-managed tools from an explicit registry
native unrestricted tools denied
tool schemas enforced
tool execution traced
```

Persistent or hybrid execution requires an explicit session.

---

## 9.5 Native

Purpose:

Expose Codex's native behavior where the caller explicitly wants it.

This profile requires both `profile="native"` and `allow_native=True` when creating the runtime.

It is not the default. Normal overrides may only remove capabilities; they cannot expand permissions.

---

# 10. Context Policies

## External

The host supplies the relevant context.

Runtime history is not reused.

Typical implementation:

```text
new ephemeral thread
        ↓
one or few turns
        ↓
discard
```

Recommended for:

```text
brain
structured
```

---

## Runtime

The runtime owns task-local conversational context.

The host stores:

```text
session_id
business state
artifacts
```

but does not replay previous runtime conversation.

Recommended for:

```text
long worker task
debugging
research
```

---

## Hybrid

The host owns business/global state.

The runtime owns technical/local state.

Example:

```text
LangGraph state
────────────────────
task_id
goal
constraints
human_decisions
artifacts
codex_session_id

Codex session
────────────────────
worker history
tool results
technical investigation
```

This is expected to be the preferred policy for complex agents.

When `runtime` or `hybrid` is used with a persistent session, replayed assistant or tool history is rejected with `ContextPolicyError`. Explicit replay is reserved for documented recovery or migration and must be traced.

---

# 11. Structured Output

Structured output uses a normalized, two-layer validation pipeline:

```text
schema normalization
        ↓
provider-side enforcement when supported
        ↓
host-side validation
        ↓
RuntimeResult[T]
```

Provider-side enforcement never replaces host validation.

Pydantic should be the primary Python developer experience.

Example:

```python
class Decision(BaseModel):
    action: Literal["continue", "retry", "human", "finish"]
    reason: str
```

Usage:

```python
model = runtime.model(
    profile="structured",
    level="medium",
).with_structured_output(Decision)

result = await model.ainvoke(input)
decision = result.value
```

Failure handling:

```text
schema generation failure
        ↓
validation error
        ↓
configured retry
        ↓
retry exhausted
        ↓
StructuredOutputError
```

The default allows two total attempts: the initial request and one retry with bounded validation feedback. Exhaustion raises `StructuredOutputError`.

Raw invalid output is available only with `include_raw=True`. It must be handled according to redaction policy and is never exported by default.

---

# 12. Tools Architecture

The canonical flow must be:

```text
Model
  │
  │ ToolRequest
  ▼
Tool Registry
  │
  ├── existence validation
  ├── schema validation
  ├── permission validation
  ├── security policy
  ├── optional HITL
  ├── execution
  └── audit
       │
       ▼
ToolResult
       │
       ▼
Model
```

---

## Tool definition

Conceptual API:

```python
@runtime_tool(
    permission="customer.read",
    side_effect="none",
    idempotent=True,
)
async def get_customer(customer_id: int) -> CustomerContext:
    ...
```

The library generates and validates the runtime-facing input and output schemas.

Every tool declares a permission category, side-effect classification, idempotency, approval requirement and optional timeout override. Human approval uses an asynchronous `ApprovalHandler`; no handler, timeout, failure or invalid response means denial.

Automatic retries are disabled unless the tool explicitly declares itself idempotent. The model never receives implementation authority.

---

## Tools should express business capabilities

Preferred:

```text
get_customer
get_customer_orders
calculate_quote
reserve_inventory
request_quote_approval
```

Avoid as default:

```text
execute_sql
run_shell
write_file
http_request
```

---

## Codex dynamic tools

Codex host-managed dynamic tools depend on the experimental App Server `dynamicTools` API.

Therefore:

```text
ToolRegistry
     ↓
stable neutral tool contract
     ↓
experimental Codex tool adapter
     ↓
internal direct App Server compatibility boundary
```

The adapter requires both a feature flag and a runtime capability check. No public application code depends directly on the experimental protocol.

---

# 13. Security Model

Security must use defense in depth.

Prompt instructions are only one layer.

The actual stack should be:

```text
Execution Profile
        ↓
Security Policy
        ↓
Available tool registry
        ↓
Runtime sandbox
        ↓
OS/process/container isolation
        ↓
credential isolation
```

---

## Isolated profile

Target:

```text
new empty temporary workspace
no implicit readable roots
no application credentials
no DB credentials
no host network access
no shell authority
host tools only when explicitly attached
```

The library guarantees policy validation and provider-sandbox mapping. Strong isolation requires an explicit external isolation adapter such as a container or host process boundary.

---

## Read-only profile

Allows intentionally scoped reading but no writes. Readable roots are mandatory and the current working directory is never inherited implicitly.

Appropriate for some coding/review use cases.

Not appropriate when even file reading is forbidden.

---

## Controlled-tools profile

The preferred agent profile.

```text
empty temporary workspace
native side effects denied
host tools allowed
host validates all arguments
host performs execution
```

---

## Native profile

Codex may receive wider native capabilities.

This profile must be explicit and clearly visible in diagnostics and traces. It requires the double opt-in defined in Section 9.5.

If any policy cannot be enforced on the active runtime or platform, inference fails before starting with `SecurityPolicyError`. Silent degradation is forbidden.

Linux and Windows are supported in 1.0 and must run the provider-neutral contract suite in CI. macOS is outside the 1.0 compatibility guarantee.

---

# 14. Observability Architecture

The core emits normalized events.

Example hierarchy:

```text
RuntimeEvent
│
├── RuntimeStarted
├── RuntimeStopped
├── InvocationStarted
├── InvocationCompleted
├── InvocationFailed
├── SessionCreated
├── SessionResumed
├── TurnStarted
├── TurnCompleted
├── TokenUsageUpdated
├── ToolRequested
├── ToolStarted
├── ToolCompleted
├── RetryScheduled
├── ValidationFailed
└── CapabilityRejected
```

Observers subscribe to these events.

Events for one invocation preserve causal order. Observer/exporter failures are isolated by default, append a diagnostic and mark observability degraded. Strict mode may raise `ObservabilityError`.

---

# 15. Observability Exporters

## LangSmith

LangSmith is the first official observer.

Desired trace structure:

```text
LangGraph Run
│
├── planner
│
├── codex.runtime
│   │
│   ├── thread
│   ├── turn
│   ├── model
│   ├── tool:get_customer
│   │    └── host workflow
│   ├── tool:calculate_quote
│   └── response
│
├── validator
└── final
```

Minimum metadata:

```text
runtime.provider
runtime.version

profile
security_policy
context_policy

model
reasoning_effort

thread_id
turn_id

input_tokens
cached_input_tokens
output_tokens
reasoning_tokens
total_tokens

duration_ms
retry_count
tool_call_count

ephemeral
structured_output
```

Sensitive payloads must support:

```text
metadata_only
redacted
full
disabled
```

`metadata_only` is the default. It excludes prompts, responses, schemas, tool arguments, tool results and raw provider payloads. `full` is explicit and never disables secret redaction.

LangSmith must be optional at install/runtime level.

## OpenTelemetry

Proteo OpenTelemetry is an official 1.0 observer/exporter. It consumes the same normalized `RuntimeEvent` stream as LangSmith and emits provider-neutral spans and metrics for runtime lifecycle, invocations, sessions, turns, tools, retries, validation, latency, usage and errors. It uses neutral invocation, session and turn identifiers for cross-exporter correlation.

The Codex provider may additionally enable **Codex-native OpenTelemetry** as explicit provider-specific enrichment when the installed runtime supports it. This layer is:

- opt-in and disabled by default;
- capability/configuration gated;
- configured to avoid user-prompt payload logging by default;
- correlated with `proteo.invocation_id`, `proteo.session_id` and `proteo.turn_id` when upstream propagation is available;
- not required to share the same OpenTelemetry `trace_id` unless Codex supports parent-context propagation.

Provider-native telemetry does not replace Proteo's neutral event stream and is not part of the provider-neutral runtime contract. Neither layer may claim access to hidden chain-of-thought or provider activity that is not surfaced by telemetry.

---

# 16. Usage Accounting

Normalized object:

```python
@dataclass
class RuntimeUsage:
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None

    duration_ms: int | None = None

    turn_count: int = 0
    tool_call_count: int = 0
    retry_count: int = 0
```

Provider-specific data may additionally exist under:

```python
usage.raw
```

but application code should not depend on it.

---

# 17. Retry Strategy

Retries must be classified.

Blind retry of all exceptions is forbidden.

Initial categories:

## Transient runtime failure

Examples:

```text
server busy
temporary unavailable
transport interruption
rate/overload event
```

Policy:

```text
retry
exponential backoff
jitter
3 total attempts by default
```

---

## Structured-output validation failure

Policy:

```text
retry once with bounded validation feedback
2 total attempts by default
then StructuredOutputError
```

---

## Authentication failure

Policy:

```text
do not blindly retry
surface AuthenticationError
```

---

## Capability failure

Policy:

```text
never retry
fail immediately
```

---

## Tool failure

Configurable:

```text
return error to model
retry tool
abort turn
require human
```

The host controls this policy. Automatic retry is permitted only when the tool explicitly declares itself idempotent.

---

# 18. Timeout and Cancellation

Timeouts exist at different scopes with configurable initial defaults:

```text
runtime startup timeout       30 seconds
turn timeout                 300 seconds
host-tool timeout             30 seconds
cancellation grace period      5 seconds
session inactivity timeout    configurable, disabled by default
overall task timeout           caller-owned, disabled by default
```

Cancellation from LangGraph or the caller propagates to the underlying runtime.

Events from one invocation are emitted in causal order. A normally drained `astream()` ends with a terminal event containing the same `RuntimeResult` that `ainvoke()` would return.

Closing, abandoning or cancelling the iterator interrupts the active turn and waits for the cancellation grace period. If cancellation cannot be confirmed, the transport is marked unhealthy and restarted or replaced before reuse; the condition is recorded in diagnostics. Codex must not continue expensive background work silently.

---

# 19. Capability Discovery

Runtime capabilities must be explicit.

Example:

```python
caps = await runtime.capabilities()

if not caps.structured_output:
    raise CapabilityError(...)
```

Profiles may also declare requirements.

Example:

```text
structured profile requires:
    structured_output
    ephemeral_sessions

controlled_agent requires:
    host_tools
```

Attempting an incompatible profile must fail before inference starts.

Provider support and effective permission are queried separately:

```python
supported = await runtime.capabilities()
effective = await model.effective_capabilities()
```

An available provider capability denied by model, profile, security policy or host configuration remains unavailable.

---

# 20. `doctor` CLI

The command:

```bash
proteo-runtime doctor
```

is part of the product.

Example output:

```text
Proteo Runtime Doctor
──────────────────────────────────────

Library
  Version                  0.4.0
  Python                   3.13.4
  Platform                 linux-x86_64

Runtime
  Provider                 Codex
  Runtime available        ✓
  Runtime version          0.xxx

Authentication
  Mode                     ChatGPT
  Authenticated            ✓
  Plan                     Plus

Configuration
  Config file              ./proteo-runtime.json
  Valid                    ✓

Models
  brain.low                gpt-model-a
  brain.medium             gpt-model-b
  brain.high               gpt-model-c
  structured.medium        gpt-model-b

Provider capabilities
  Ephemeral threads        ✓
  Persistent threads       ✓
  Structured output        ✓
  Streaming                ✓
  Interruption             ✓
  Usage reporting          ✓
  Host tools               experimental

Effective capabilities
  Profile                  controlled_agent
  Security policy          controlled_tools
  Filesystem read          none
  Filesystem write         disabled
  Native network           disabled
  Host tools               enabled

Observability
  LangSmith                ✓
  Payload mode             metadata_only
  Project                  proteo-runtime-dev
  Proteo OpenTelemetry     ✓
  Codex native OTel        disabled
  Status                   healthy

Warnings
  Dynamic tools depend on an experimental
  Codex App Server capability.
```

Exit codes should allow CI use.

Example:

```text
0 healthy
1 warnings
2 configuration/runtime failure
```

Exact codes may evolve before 1.0.

---

# 21. LangGraph Adapter

LangGraph is the first framework integration.

The adapter must translate between:

```text
LangGraph / LangChain expectations
            ↕
neutral runtime contracts
```

It must not bypass core policies.

The initial public surface is:

```python
RuntimeNode
```

`CodexNode`, `ChatRuntime`, `BaseChatModel` compatibility and other LangChain-style surfaces are outside the initial adapter contract.

---

## Initial decision

Do NOT begin by implementing `BaseChatModel`.

Start with the provider-neutral `RuntimeNode`.

Reason:

Codex is capable of stateful agentic execution and should not initially be forced into a stateless abstraction.

Once semantics are stable, add an LLM-compatible adapter implementing concepts such as:

```text
invoke
ainvoke
stream
astream
with_structured_output
bind_tools
```

where they can be mapped safely.

Framework state is converted to `RuntimeInput` before reaching the core. Persistent identity is transported only through:

```python
config["configurable"]["proteo_session_id"]
```

`RuntimeNode` does not write a session identifier into graph state automatically. The host/checkpointer owns persistence.

---

# 22. Public API Design Goal

Desired simple experience:

```python
from proteo_runtime import Runtime

async with Runtime.codex() as runtime:

    model = runtime.model(
        profile="brain",
        level="medium",
    )

    response = await model.ainvoke(
        "Determine the next action."
    )

    print(response.value)
```

Structured:

```python
model = runtime.model(
    profile="structured",
    level="medium",
).with_structured_output(Decision)

result = await model.ainvoke("Choose the next valid action.")
decision = result.value
```

Persistent:

```python
worker = await runtime.session(profile="session")
session_id = worker.id

await worker.ainvoke("Investigate the issue.")
await worker.close()

worker = await runtime.resume_session(session_id)
result = await worker.ainvoke(
    "Now verify the second hypothesis."
)
```

The application should not manually interact with:

```text
thread/start
turn/start
JSON-RPC
Codex SDK result types
Codex App Server protocol types
```

unless it explicitly enters an advanced provider-specific API.

---

# 23. Testing Strategy

Test pyramid:

```text
                 Real Codex E2E
                      ▲
                     / \
                    /   \
           Integration tests
                  ▲
                 / \
                /   \
          Contract tests
               ▲
              / \
             /   \
          Unit tests
```

---

## Unit tests

Must use:

```text
FakeRuntime
FakeProviderClient
FakeSession
FakeToolExecutor
FakeObserver
```

No quota usage.

---

## Contract tests

Every runtime implementation must satisfy the same behavioral contracts.

Required contract scenarios include:

- base installation starts the Codex integration without framework extras;
- `pytest` never consumes subscription quota;
- unknown configuration keys and unsupported schema versions fail with paths;
- missing model mappings, unavailable models and unsupported reasoning efforts do not silently fall back;
- arbitrary objects are rejected by the core input boundary;
- structured output succeeds, retries once, or raises `StructuredOutputError`;
- raw output is absent unless explicitly requested;
- session IDs round-trip through the versioned `SessionCodec` without an internal alias store;
- malformed or incompatible session descriptors fail explicitly and cannot expand permissions;
- concurrent use of one session raises `SessionBusyError`;
- closing and resuming a session preserves provider history;
- incompatible resume requires explicit migration;
- cancelling a stream interrupts the provider turn or invalidates the provider connection before reuse;
- replayed persistent history raises `ContextPolicyError`;
- secure profiles expose no implicit filesystem roots;
- normal overrides cannot expand effective permissions;
- `native` requires both explicit opt-ins;
- approval absence or failure denies a tool;
- non-idempotent tools are not retried automatically;
- exporter failure degrades observability without failing inference by default;
- strict observability mode surfaces exporter failure;
- Proteo OpenTelemetry and LangSmith correlate through neutral identifiers;
- Codex-native OpenTelemetry remains opt-in and does not alter inference behavior;
- a supported provider capability denied by policy remains unavailable;
- Linux and Windows execute the same provider-neutral contract suite.

Real Codex integration and end-to-end tests remain explicitly selected and quota-consuming. Unit and default contract tests use fakes only.

---

## Integration tests

Opt-in:

```bash
pytest -m integration
```

May use real Codex.

---

## End-to-end tests

Small, controlled and explicitly enabled.

They should validate actual subscription-backed behavior before releases.

---

# 24. Compatibility Strategy

The canonical Codex integration baseline is the official OpenAI Codex documentation for the [Codex SDK](https://developers.openai.com/codex/sdk/), [App Server](https://developers.openai.com/codex/app-server/) and [authentication](https://developers.openai.com/codex/auth/).

The stable `openai-codex` Python SDK is the canonical integration path. Direct App Server JSON-RPC is an internal experimental compatibility escape hatch only for SDK capability gaps; it is not a second equivalent public transport. `dynamicTools` remains experimental and requires both a feature flag and capability check.

Codex changes rapidly.

The project must therefore pin or define tested compatibility ranges.

CI should test against supported runtime versions where practical.

The compatibility layer must distinguish:

```text
stable openai-codex Python SDK
internal direct JSON-RPC compatibility boundary
experimental Codex dynamicTools adapter
```

The SDK-bundled pinned runtime is the default. A caller-supplied Codex executable requires an explicit compatibility check. Experimental support must not silently redefine stable behavior.

---

# 25. Packaging

Initial Python target:

```text
Python >= 3.11
```

Support should be validated through CI rather than assumed.

Suggested tooling:

```text
pyproject.toml
uv or standard pip tooling
pytest
pytest-asyncio
ruff
mypy or pyright
pre-commit
GitHub Actions
```

Packaging must include optional dependency groups.

Example:

```toml
[project.optional-dependencies]

langgraph = [...]
langsmith = [...]
otel = [...]
all = [...]
dev = [...]
```

`openai-codex` is a base dependency, so `pip install proteo-runtime` provides the primary runtime. A basic installation does not install LangGraph, LangSmith or Proteo OpenTelemetry dependencies.

The `all` extra includes all supported framework integrations and observers. The `dev` extra includes development and test tooling. Optional integrations must fail with actionable installation guidance when imported or configured without their corresponding extra.

---

# 26. Semantic Versioning

Before 1.0:

```text
0.x
```

breaking API changes are allowed but must be documented.

From:

```text
1.0.0
```

the project follows Semantic Versioning.

Experimental modules remain exempt from normal stability guarantees when clearly labeled.

---

# 27. Documentation Structure

Target repository documentation:

```text
README.md
LICENSE
CONTRIBUTING.md
SECURITY.md
CHANGELOG.md

docs/
├── README.md
├── design/
│   ├── project-guide.md
│   └── requirements.md          # extracted before 1.0
├── architecture/
│   ├── overview.md
│   ├── runtime-core.md
│   ├── context-management.md
│   ├── tools.md
│   ├── security.md
│   └── observability.md
├── plans/                       # versioned SDD implementation plans
├── adr/
├── guides/
│   ├── getting-started.md
│   ├── using-langgraph.md
│   └── structured-output.md
└── reference/
    ├── configuration.md
    ├── profiles.md
    ├── capabilities.md
    ├── errors.md
    ├── cli.md
    └── api/
```

`docs/design/project-guide.md` remains the design charter during early development. Before 1.0, its normative requirements should be extracted to `docs/design/requirements.md`; implementation plans remain historical engineering records under `docs/plans/`, while current behavior is documented under `architecture/`, `guides/` and `reference/`.

---

# 28. Examples

Examples must be small and focused.

Target:

```text
examples/

01_basic_brain.py
02_model_levels.py
03_structured_output.py
04_persistent_session.py
05_langgraph_basic.py
06_langgraph_structured_router.py
07_langsmith_tracing.py
08_controlled_tools.py
09_security_profiles.py
10_retry_and_errors.py
11_streaming.py
12_custom_profile.py
13_doctor_configuration/
```

At least one complete example application should be added before 1.0.

It should demonstrate:

```text
LangGraph
+
Codex subscription runtime
+
structured planner
+
controlled tools
+
persistent worker
+
LangSmith
+
security policy
```

without becoming an overly large demo application.

---

# 29. Documentation Quality Requirements

All public APIs must contain docstrings.

Every feature must answer:

```text
What is it?
Why does it exist?
When should I use it?
What are the security implications?
What runtime capabilities does it require?
```

Architecture documentation should explain trade-offs, not only syntax.

---

# 30. Implementation Roadmap

---

## Phase 0 — Repository and Architectural Foundation

### Goal

Create the library skeleton and freeze dependency direction.

### Deliverables

```text
pyproject.toml
MIT LICENSE
README skeleton
package structure
core protocols
error hierarchy
configuration models
FakeRuntime
CI
linting
typing
unit test setup
```

### Key contracts

Implement initial neutral definitions for:

```text
Runtime
RuntimeModel
RuntimeSession
RuntimeCapabilities
RuntimeUsage
RuntimeEvent
RuntimeInput
RuntimeMessage
RuntimeResult
RuntimeIdentity
RuntimeDiagnostic
SessionCodec
ExecutionProfile
ContextPolicy
SecurityPolicy
```

### Exit criteria

- package installs locally;
- imports do not depend on LangGraph;
- fake runtime passes initial contract tests;
- CI passes;
- no real Codex dependency is required for unit tests.

---

## Phase 1 — Codex Core Runtime

### Goal

Implement the first real provider.

### Features

```text
stable openai-codex SDK transport
reuse of Codex-managed ChatGPT authentication
one active opaque runtime identity
runtime startup/shutdown
model listing
thread start
thread resume
ephemeral threads
persistent threads
async invocation
streaming
interrupt
usage extraction
basic fail-closed sandbox mapping
```

### Profiles

Initial:

```text
brain
structured
```

### Exit criteria

A Python application can perform:

```python
await model.ainvoke(...)
```

through Codex without manually interacting with the Codex SDK. The result is a normalized `RuntimeResult[str]`.

---

## Phase 2 — Model Resolution, Structured Output and Context

### Goal

Make basic runtime use equivalent to an LLM engine.

### Features

```text
JSON configuration
logical reasoning levels
model resolution
reasoning effort resolution
Pydantic structured output
JSON Schema
validation
schema retries
context policies
persistent RuntimeSession
profile overrides
custom profiles
```

### Exit criteria

The caller can switch:

```text
brain.low
brain.medium
brain.high
structured.medium
```

through configuration only.

Structured calls return validated Python objects in `RuntimeResult[T].value` and omit raw output by default.

---

## Phase 3 — LangGraph Integration

### Goal

Use the runtime naturally inside LangGraph.

### Features

```text
provider-neutral RuntimeNode adapter
RunnableConfig propagation
async execution
stream propagation
cancellation propagation
structured nodes
session ID persistence through configurable.proteo_session_id
metadata propagation
```

### Exit criteria

A sample StateGraph uses Codex in place of a normal LLM for brain/structured nodes without leaking Codex-specific SDK objects into graph state.

---

## Phase 4 — Observability, LangSmith and OpenTelemetry

### Goal

Make runtime behavior inspectable through official exporters from Phase 4 onward.

### Features

```text
normalized event bus
observer interface
LangSmith observer with metadata_only default
Proteo OpenTelemetry observer
optional capability-gated Codex-native OpenTelemetry enrichment
cross-exporter correlation
exporter degradation and strict mode
nested trace hierarchy
token metadata
latency
model
reasoning effort
thread/turn IDs
profile
context policy
retry events
validation events
redaction
```

Correlate Proteo OpenTelemetry and LangSmith through neutral invocation, session and turn identifiers. When enabled and supported, configure Codex-native OpenTelemetry with the same Proteo correlation identifiers without assuming shared `trace_id` propagation. Exporters must not claim visibility into hidden reasoning.

### Exit criteria

A LangGraph execution displays a coherent metadata-only trace containing graph nodes and exposed Codex runtime activity, with correlated Proteo OpenTelemetry spans. Optional Codex-native telemetry can be enabled without changing inference semantics. Exporter failure is diagnosable and does not fail inference unless strict mode is active.

---

## Phase 5 — Host-Managed Tools

### Goal

Allow Codex to perform multi-step agentic reasoning without surrendering execution control.

### Features

```text
ToolDefinition
ToolRegistry
schema generation
argument validation
ToolExecutor
ToolResult
tool permission layer
tool tracing
tool retries
tool timeout
tool failure policies
async ApprovalHandler
idempotency and side-effect metadata
```

Implement Codex dynamic-tool support through an isolated experimental adapter and internal direct App Server compatibility boundary. Require both a feature flag and capability check.

### Exit criteria

Codex can choose among host-defined tools while possessing no direct authority over their implementations.

---

## Phase 6 — Security Hardening

### Goal

Convert safety assumptions into enforced boundaries.

### Features

```text
isolated profile
read-only profile
controlled-tools profile
native profile

credential isolation
filesystem policy
network policy
native-tool policy
sandbox mapping
process isolation
external isolation adapter
Linux and Windows enforcement tests
security diagnostics
trace redaction
```

### Exit criteria

Tests demonstrate that controlled profiles cannot bypass host tool boundaries through normal Codex runtime capabilities.

---

## Phase 7 — Reliability and Failure Handling

### Goal

Make runtime behavior predictable in long-running applications.

### Features

```text
retry policies
backoff + jitter
retry classification
timeouts
cancellation
interrupt propagation
connection recovery
structured retry
tool retry
session recovery
normalized exceptions
retry exhaustion
documented timeout and attempt defaults
runtime health checks
```

Ensure normalized failures carry enough information for host-owned fallback policies without implementing routing inside Proteo Runtime.

### Exit criteria

Failure scenarios are reproducible and represented through stable project exceptions.

---

## Phase 8 — Doctor and Capability Diagnostics

### Goal

Make configuration problems diagnosable without reading internal logs.

### Features

```bash
proteo-runtime doctor
proteo-runtime doctor --json
```

Checks:

```text
package
Python
runtime executable
SDK/runtime compatibility
authentication
models
profile resolution
capabilities
experimental features
security
LangSmith
Proteo OpenTelemetry
Codex native OpenTelemetry capability/status
configuration
```

### Exit criteria

A user opening an issue can attach `doctor --json` output after automatic secret redaction.

---

## Phase 9 — API Stabilization

### Goal

Prepare the library for 1.0.

### Work

Review:

```text
public imports
naming
errors
typing
profiles
configuration
lifecycle
runtime contracts
tool contracts
observer contracts
experimental namespaces
```

Remove accidental public internals.

Document deprecations.

Create compatibility tests.

### Exit criteria

Public API is intentionally defined rather than emerging accidentally from implementation.

---

## Phase 10 — Documentation, Examples and 1.0 Release

### Goal

Publish a production-quality open-source library.

### Deliverables

```text
complete README
requirements document
architecture docs
security docs
API reference
examples
contributor guide
security policy
changelog
benchmarks
PyPI metadata
release workflow
```

### Required showcase example

A LangGraph agent using:

```text
brain profile
structured planner
controlled tools
persistent worker
LangSmith tracing
security profile
```

### Exit criteria

A new developer can:

```text
install
authenticate
configure
run
trace
debug
```

the library by following only public documentation.

---

# 31. Stable 1.0 Definition of Done

Version 1.0 requires all of the following.

### Packaging

- installable package;
- `openai-codex` base dependency;
- optional `langgraph`, `langsmith`, `otel`, `all` and `dev` extras;
- reproducible build;
- PyPI-ready;
- MIT license;
- automated Linux and Windows CI.

### Core

- async runtime;
- neutral text input and uniform `RuntimeResult[T]`;
- profiles;
- strict versioned configuration;
- versioned model resolution;
- versioned self-contained session descriptors and `SessionCodec`;
- sessions;
- structured output;
- context policies;
- capability discovery;
- usage accounting.

### Codex

- Codex-managed ChatGPT subscription authentication;
- one active opaque identity per runtime instance;
- stable `openai-codex` SDK transport;
- direct JSON-RPC access kept internal and experimental;
- experimental `dynamicTools` adapter isolated by flag and capability;
- model discovery;
- ephemeral and persistent execution.

### LangGraph

- documented provider-neutral `RuntimeNode`;
- structured node usage;
- session IDs carried through `RunnableConfig.configurable`;
- tracing and cancellation propagation;
- no provider objects written to graph state.

### Tools

- host-managed tools;
- schema validation;
- permission checks;
- execution tracing.

### Security

- empty-workspace safe defaults and explicit read roots;
- monotonic permission overrides;
- double opt-in for `native`;
- external strong-isolation adapter;
- secret redaction;
- documented trust boundaries.

### Reliability

- classified retry policies with documented defaults;
- idempotency-aware tool retries;
- timeouts and cancellation grace period;
- stream interruption and unhealthy-transport recovery;
- session concurrency and resume compatibility;
- normalized errors.

### Observability

- LangSmith metadata-only by default;
- official provider-neutral OpenTelemetry exporter;
- optional capability-gated Codex-native OpenTelemetry enrichment;
- cross-exporter correlation;
- exporter degradation and strict mode;
- token usage;
- latency;
- tools;
- retries;
- session identifiers.

### Diagnostics

- `doctor`;
- JSON diagnostic mode;
- provider and effective capability views;
- LangSmith and OpenTelemetry health;
- secret-safe output.

### Quality

- unit tests;
- contract tests on Linux and Windows;
- default tests consume no subscription quota;
- opt-in integration tests;
- type checking;
- linting;
- API docs;
- examples.

---

# 32. Benchmarks

Benchmarks are not merely performance tests.

They should measure whether the abstraction provides value.

Candidate dimensions:

```text
direct API-style runtime call
vs
Codex brain profile

latency
time-to-first-token
total duration
input tokens
cached tokens
reasoning tokens
output tokens
success rate
structured-output validity
retry rate
```

For agentic execution:

```text
tool-call count
number of turns
task success
context growth
session token growth
```

Results should be reproducible and documented.

---

# 33. Architectural Decision Records

Significant changes should use ADRs.

Example:

```text
docs/adr/

0001-framework-agnostic-core.md
0002-async-first.md
0003-host-managed-tools.md
0004-context-ownership.md
0005-langsmith-as-observer.md
0006-experimental-codex-transport.md
```

This is especially valuable for an open-source infrastructure library where future contributors need to understand why constraints exist.

---

# 34. Contribution Model

Before public contribution is encouraged, provide:

```text
CONTRIBUTING.md
development setup
test commands
coding conventions
architecture overview
experimental API policy
issue templates
bug reproduction expectations
```

Provider integrations should eventually require compliance with runtime contract tests.

---

# 35. Security Disclosure

Create:

```text
SECURITY.md
```

It should explicitly explain:

- what the library isolates;
- what it does not isolate;
- why prompts are not security boundaries;
- implications of the native profile;
- credential handling;
- logging/redaction behavior;
- host-tool execution responsibilities;
- experimental runtime limitations.

Security issues must have a private reporting path when the project becomes public.

---

# 36. Future Provider Integration Contract

No additional provider will be implemented during the initial roadmap.

However, a future provider should be addable by implementing contracts such as:

```text
Runtime
RuntimeModel
RuntimeSession
RuntimeCapabilities
RuntimeIdentity
UsageMapper
```

Provider code must not require modifications to:

```text
LangGraph adapter
ToolRegistry
SecurityPolicy
LangSmith observer
OpenTelemetry observer
structured-output validation
retry engine
```

unless the provider introduces a genuinely new capability category.

This requirement is the primary test of whether the project is truly provider-agnostic.

---

# 37. Future Framework Integration Contract

Likewise, future frameworks should consume the neutral runtime API.

A future framework adapter should not require changes to Codex integration.

Conceptually:

```text
              Runtime Core
             /            \
        LangGraph       Future Framework
```

---

# 38. Guiding Design Question

Every significant implementation decision should be evaluated against the following question:

> Does this preserve the ability to use a stateful subscription-backed agent runtime as a controlled reasoning engine without surrendering application ownership of state, tools, security, observability or execution?

If the answer is no, the design should be reconsidered.

---

# 39. Project Identity

The project name is **Proteo Runtime**.

The canonical distribution and namespace conventions are:

```text
Project:          Proteo Runtime
PyPI:             proteo-runtime
Python namespace: proteo_runtime
CLI:              proteo-runtime
```

A more durable description is:

> A framework-agnostic Python runtime abstraction for using subscription-backed AI agent runtimes as controlled LLM engines, with structured outputs, isolated context, host-managed tools, security policies and full observability.

Initial implementation:

```text
Runtime:   OpenAI Codex
Framework: LangGraph
Tracing:   LangSmith + OpenTelemetry
```

---

# 40. Final Architectural Principle

The central separation of responsibilities is:

```text
MODEL
decides what should happen

HOST
decides what is allowed to happen

RUNTIME
provides reasoning and local execution semantics

FRAMEWORK
owns workflow and global state

OBSERVABILITY
records what happened
```

This boundary is the primary design invariant of the project.

Everything else should be built around preserving it.
---
