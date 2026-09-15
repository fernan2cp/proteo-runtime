# Technical Design — Phase 3

## Dependency and module boundary

Add these optional extras to `pyproject.toml` and regenerate `uv.lock`:

```toml
[project.optional-dependencies]
langgraph = ["langgraph>=1.2,<2"]
all = ["langgraph>=1.2,<2"]
```

The implementation lives under `src/proteo_runtime/integrations/langgraph/`. Its `__init__.py`
exports only `RuntimeNode`. `proteo_runtime.__init__`, `proteo_runtime.core` and
`proteo_runtime.testing` do not import it. Importing the integration without the extra raises an
actionable `ModuleNotFoundError` naming `proteo-runtime[langgraph]`; importing the base package
continues to work.

## Public API

The public shape is:

```python
class RuntimeNode(Generic[StateT]):
    def __init__(
        self,
        executor: RuntimeModel[Any] | Runtime,
        *,
        input_key: str = "input",
        output_key: str = "output",
        input_mapper: Callable[[StateT], str | RuntimeInput] | None = None,
        output_mapper: Callable[[RuntimeResult[Any]], Mapping[str, Any]] | None = None,
    ) -> None: ...

    async def __call__(
        self,
        state: StateT,
        config: RunnableConfig | None = None,
    ) -> Mapping[str, Any]: ...
```

Constructor validation rejects empty keys, an executor that is neither protocol, and ambiguous
objects that satisfy both execution modes. A `RuntimeModel` selects model mode; a `Runtime`
selects persistent-resume mode. No sync `invoke`, builder, provider overload or schema parameter
is added.

## State conversion

Without `input_mapper`, `state` must be a `Mapping`, must contain `input_key`, and that value must
normalize through `RuntimeInput.from_value()`. Missing keys raise `ConfigurationError` with path
`state.<input_key>`; invalid values retain the core `TypeError` contract.

An explicit `input_mapper` receives the original state. Its exception propagates unchanged and
its return value is normalized through the same core boundary. This prevents arbitrary framework
objects from reaching providers.

After the terminal result, the default output is a new dictionary containing only
`{output_key: result.value}`. An explicit `output_mapper` receives the neutral `RuntimeResult` and
must return a mapping; its exception propagates unchanged, invalid return types raise `TypeError`,
and the adapter returns `dict(mapping)` to avoid retaining mutable aliases. A host may explicitly
project usage or `session_id`; the default never does.

Structured nodes are created by passing a core-bound model:

```python
node = RuntimeNode(
    runtime.model(profile="structured").with_structured_output(Decision),
    input_key="question",
    output_key="decision",
)
```

The adapter neither sees nor transforms the schema and returns the validated Python value.

## RunnableConfig mapping

The node treats `RunnableConfig` as read-only. It builds a fresh `InvocationConfig` with two
namespaces:

```text
proteo    <- config.metadata.proteo
langgraph <- node, step, triggers, tags, run_id
```

Only `langgraph_node`, `langgraph_step` and `langgraph_triggers` are read from framework metadata.
`tags` must be a sequence of strings; `run_id` is stringified from its public identifier. The
adapter deep-copies JSON-compatible values and recursively rejects credential-shaped keys such as
`token`, `secret`, `password`, `authorization`, `credential`, `api_key` and variants. It rejects
non-finite floats and arbitrary Python objects. Empty namespaces are omitted.

No `callbacks`, `recursion_limit`, unknown metadata, arbitrary configurable field or session
descriptor is forwarded. Metadata validation completes before calling `astream()` or
`resume_session()`.

## Execution flow

For model mode:

```text
state -> RuntimeInput -> InvocationConfig -> RuntimeModel.astream()
      -> custom JSON events -> terminal RuntimeResult -> state update
```

If `configurable.proteo_session_id` exists in model mode, raise `ConfigurationError` at that path
before invoking the model.

For session mode:

```text
configurable.proteo_session_id -> Runtime.resume_session()
state -> RuntimeInput -> RuntimeSession.astream()
      -> custom JSON events -> terminal RuntimeResult -> state update
finally -> RuntimeSession.close()
```

The session identifier must be a non-empty string. Missing or invalid input raises
`ConfigurationError` at `config.configurable.proteo_session_id`. `close()` preserves provider
history and executes on success, runtime failure, mapper failure and cancellation. The adapter
never calls `session()`, `archive()`, `delete()` or `migrate_session()`.

## Custom stream envelope

Use LangGraph's current `get_stream_writer()` and emit one JSON-compatible dictionary per neutral
event:

```json
{
  "type": "proteo_runtime_event",
  "version": 1,
  "event": {
    "kind": "output_text_delta",
    "event_id": "...",
    "sequence": 3,
    "occurred_at": "2026-09-15T12:00:00+00:00",
    "runtime": {"provider": "codex", "fingerprint": "..."},
    "invocation_id": "...",
    "session_correlation_id": "sha256:...",
    "turn_id": "...",
    "metadata": {}
  }
}
```

`session_correlation_id` is `null` for ephemeral events and is a stable `sha256:` digest of the
opaque descriptor for persistent events; the resumable descriptor is never serialized. Optional
invocation/turn IDs are present with `null` when absent. Runtime metadata includes only provider
and opaque fingerprint, never labels or provider metadata. Event metadata is recursively copied,
credential-key redacted, and converted only when JSON-safe. Credential-shaped values in text are
conservatively replaced before streaming. `result`, `result.value`, `result.raw`, exception
causes and provider objects are never serialized. This is framework streaming, not the Phase 4
observer/exporter contract.

The adapter records the result carried by `INVOCATION_COMPLETED` internally. Exactly one
successful terminal is accepted. A completed event without result, EOF without result, or a
second successful terminal raises `RuntimeUnavailableError` with safe details. Provider failures
and existing `AgentRuntimeError` subclasses pass through unchanged.

## Cancellation and cleanup

The node retains the async iterator and calls `aclose()` in `finally`. `aclose()` is the only
neutral interruption signal; it activates the existing provider/session finalizer. If a provider
maps task cancellation to `CancellationError`, the adapter checks the current task cancellation
state and restores `asyncio.CancelledError` only for caller cancellation. It never calls
`session.interrupt()` a second time. The resumed session handle is then closed, preserving
history. Cleanup errors must not replace an in-flight cancellation; they are chained or attached
as safe diagnostics according to existing runtime behavior.

No adapter-owned background task survives the call. The implementation does not add retry,
checkpoint or lifecycle ownership beyond the contracts already implemented by core/providers.

## Compatibility and security

- Existing direct runtime APIs and base installation remain unchanged.
- Core import boundaries stay enforced; only the integration package imports LangGraph.
- State and custom events contain neutral/application values only, never SDK objects.
- Session descriptors are treated as untrusted input and never used as permission selectors.
- Host output mappers are an explicit trust boundary: if a mapper chooses to expose raw data or a
  descriptor, that is host-owned behavior and not automatic adapter behavior.
- Real Codex integration calls are forced to the Luna/low binding and assert the resolved model
  and reasoning effort before accepting a result.
