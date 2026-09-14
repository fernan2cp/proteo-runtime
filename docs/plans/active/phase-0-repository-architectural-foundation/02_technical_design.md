# Technical Design — Phase 0

## Package Topology

The implementation creates this minimal topology:

```text
pyproject.toml
README.md
LICENSE
py.typed (inside package)
pre-commit-config.yaml
.github/workflows/ci.yml

src/proteo_runtime/
├── __init__.py
├── __main__.py
├── cli/
│   ├── __init__.py
│   └── main.py
├── core/
│   ├── __init__.py
│   ├── capabilities.py
│   ├── context.py
│   ├── diagnostics.py
│   ├── errors.py
│   ├── events.py
│   ├── identity.py
│   ├── model.py
│   ├── profiles.py
│   ├── runtime.py
│   ├── session.py
│   ├── session_codec.py
│   ├── types.py
│   └── usage.py
├── config/
│   ├── __init__.py
│   ├── models.py
│   └── validation.py
├── integrations/
│   └── __init__.py
├── providers/
│   └── __init__.py
└── testing/
    ├── __init__.py
    └── fakes.py

tests/
├── contract/
├── unit/
└── test_import_boundaries.py
```

`providers` and `integrations` are reserved namespaces only. No Codex or LangGraph implementation is created in this phase.

## Dependency Direction

The allowed graph is:

```text
config ───────┐
testing ──────┼──> core
providers ────┘
integrations ───> core
```

The core MUST NOT import `providers`, `integrations`, LangGraph, LangSmith, OpenTelemetry, or `openai_codex`. Configuration models may reuse core vocabulary only through dependency-safe types or string literals; core must never import the configuration loader.

Import-linter contracts must enforce these rules in CI.

## Core Value Objects

Use frozen dataclasses unless a `Protocol` is required:

- `TextContent(text: str)` and `RuntimeMessage(role, content)` where role is `system|user|assistant|tool`;
- `RuntimeInput(messages)` with a constructor/helper that converts `str` into one user message;
- `RuntimeResult[T]` containing `value`, `usage`, runtime/model/profile metadata, optional session/turn IDs, diagnostics, and `raw=None` by default;
- `RuntimeCapabilities` containing provider support flags for structured output, session modes, streaming, interruption, host/native tools, sandbox, and usage reporting;
- `RuntimeUsage` containing nullable token counters, duration, turn/tool/retry counts, and optional provider data isolated under `raw`;
- `RuntimeIdentity` containing opaque non-secret identity metadata only;
- `RuntimeDiagnostic` containing a safe code, message, severity, and structured non-secret details.

Value objects must reject invalid enum values and mutable aliases at their boundary. Provider objects and arbitrary framework state are not valid core values.

## Protocols

`Runtime` exposes async `start`, `close`, `capabilities`, `models`, `session`, `resume_session`, and `migrate_session`, plus synchronous model construction. `RuntimeModel[T]` exposes async `ainvoke`, async `astream`, `with_structured_output`, and async `effective_capabilities`. `RuntimeSession` exposes `id`, async invocation/streaming, `interrupt`, `close`, `archive`, and `delete`.

Protocols use type variables for future structured values while keeping Phase 0 behavior provider-neutral. Concrete fakes implement the protocols; no protocol method may mention an SDK result type.

## Profiles and Policies

Represent profile and policy names as validated enums or `Literal`-compatible string enums. Provide immutable profile specifications that encode the guide’s defaults:

| Profile | Lifecycle | Context | Security | Host tools |
|---|---|---|---|---|
| `brain` | ephemeral | `external` | `isolated` | disabled |
| `structured` | ephemeral | `external` | `isolated` | disabled |
| `session` | persistent | `runtime` | `isolated` | disabled |
| `controlled_agent` | ephemeral | `external` | `controlled_tools` | explicit only |
| `native` | explicit | explicit | `native` | provider-defined |

Phase 0 validates vocabulary and safe defaults. It does not enforce OS sandboxing or native double opt-in; those belong to later phases.

## Configuration Models

Use strict Pydantic v2 models with `ConfigDict(extra="forbid", frozen=True)`. Define `RuntimeConfigV1` with:

```text
schema_version: Literal[1]
runtime: str
profiles: mapping[profile_name, mapping[logical_level, ModelMapping]]
```

`ModelMapping` contains `model` and `reasoning_effort`. Logical levels are restricted to `low`, `medium`, `high`, and `ultra`. Convert Pydantic validation locations into `ConfigurationError` paths without exposing file contents or secrets. Loader precedence and model resolution are explicitly deferred to Phase 2.

## SessionCodec

Define a private `SessionDescriptorV1` with non-secret fields sufficient to validate provider, provider session ID, opaque identity fingerprint, frozen configuration/profile fingerprints, context policy, security policy, and descriptor version. Encode canonical UTF-8 JSON with sorted keys and compact separators, base64url-encode without padding, and prefix with `prt1.`.

Decoding must validate prefix, base64, JSON shape, version, required fields, and forbidden credential-shaped fields. The codec is not encryption or authorization. The runtime validates current identity, provider session existence, and permissions after decoding. Malformed or incompatible descriptors raise `SessionMismatchError`; absent provider sessions are represented by `SessionNotFoundError` from the runtime.

## Events and Observability Boundary

Use one immutable event envelope with a typed `kind`, monotonic sequence, timestamp, runtime ID, invocation/session/turn correlation IDs, and safe metadata. Initial kinds cover runtime start/stop, invocation start/completion/failure, session create/resume, turn start/completion, token usage updates, retry scheduling, validation failure, tool lifecycle, and capability rejection.

Events preserve causal order per invocation. Phase 0 provides the contract and fake emission only; exporters and provider-native telemetry are deferred.

## Fake Runtime Behavior

`FakeRuntime` is deterministic and injectable:

- scripted text results, event streams, usage, capabilities, and failures;
- async context-manager lifecycle with idempotent close;
- in-memory provider-session simulation for resume tests while keeping the public ID codec opaque;
- one active turn per session enforced by an async lock and `SessionBusyError`;
- cancellation and interruption events;
- no imports of `openai_codex`, no subprocesses, no network, and no credential reads.

The fake is a test support implementation, not a production fallback provider.

## Packaging and Tooling

Use Hatchling as the PEP 517 build backend. Declare `openai-codex>=0.147,<0.148` as the base dependency and `pydantic>=2,<3` for strict configuration models. Add a functional `dev` extra containing pytest, pytest-asyncio, coverage, Ruff, mypy, pre-commit, and import-linter. Do not add placeholder LangGraph, LangSmith, or OpenTelemetry dependencies in Phase 0.

Configure the `proteo-runtime` console script to call the minimal version-capable CLI. The root package should export only the documented Phase 0 contracts and avoid wildcard exports from internal modules.
