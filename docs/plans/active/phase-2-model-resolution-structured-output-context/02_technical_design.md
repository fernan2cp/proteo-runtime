# Technical Design — Phase 2

## Public Configuration Surface

Preserve the positional compatibility of `default_model` and extend construction as:

```python
CodexRuntime(
    default_model: str | None = None,
    *,
    config_path: str | os.PathLike[str] | None = None,
    config: RuntimeConfigV1 | None = None,
)
```

`config` is the authoritative typed initialization configuration when supplied. Otherwise the
loader selects the explicit `config_path`, then `PROTEO_RUNTIME_CONFIG`, then the packaged Codex
v1 defaults. The two paths are selectors, not merge layers: an explicit path entirely replaces
the environment-selected document. `default_model`, retained for `0.2.0` compatibility, then
overrides the model component of every resolved profile/level while leaving configured effort
unchanged. Non-`None` `InvocationConfig` fields overlay the frozen model binding field by field.

To make that distinction observable, `InvocationConfig.include_raw` is changed to
`bool | None = None`; the effective default remains `False`. `model`, `reasoning_effort`, and
`timeout_seconds` inherit when `None`; metadata is merged by key; an explicit method-level
`include_raw` argument has highest precedence. Existing callers that pass `False` retain the
same behavior.

Read files once as UTF-8, require a top-level JSON object, validate through `RuntimeConfigV1`,
and normalize all errors without including file contents. `ConfigurationError.path` uses `$` for
document/file failures and dotted schema locations for value failures. No search relative to the
current directory, parents, Git root, or package consumer occurs.

## Schema Version One and Custom Profiles

Keep the existing `profiles.<profile>.<level>.{model,reasoning_effort}` shape and add:

```json
{
  "profile_specs": {
    "research_worker": {
      "lifecycle": "persistent",
      "context_policy": "hybrid",
      "security_policy": "isolated",
      "host_tools": "disabled"
    }
  }
}
```

Expose a frozen Pydantic `ProfileConfig` from `proteo_runtime.config` and store
`RuntimeConfigV1.profile_specs` as an immutable mapping. Custom names must be non-empty, must
exist in `profiles`, and must not collide with a built-in profile. Every custom model map must
contain at least one logical level. Built-in specifications remain owned by core and cannot be
redefined in JSON.

Semantic validation accepts only coherent executable shapes:

- `external` requires `ephemeral`;
- `runtime` and `hybrid` require `persistent`;
- `explicit` lifecycle is reserved for built-in `native`;
- a Phase 2 custom profile may declare the full enum vocabulary, but factories reject any
  effective security other than `isolated` or host-tools mode other than `disabled` before
  creating a provider thread;
- `controlled_agent`, `native`, `read_only`, controlled/explicit/provider-defined tools, and
  persistent structured binding remain capability-gated for later phases.

Correct the built-in `controlled_agent` spec from `hybrid` to `external`. Other built-in profile
semantics remain unchanged.

## Packaged Defaults and Resolution

Ship the version-one Codex defaults as package data loaded through `importlib.resources`, not a
working-directory path. `brain`, `structured`, and `session` each contain the same explicit map:

```text
low     -> gpt-5.6-luna / low
medium  -> gpt-5.6-terra / medium
high    -> gpt-5.6-sol   / high
ultra   -> gpt-5.6-sol   / ultra
```

At startup validate every configured mapping against the visible catalog and its supported
efforts. Report the exact configuration path and unavailable identifier; never pick the catalog
default. Custom profiles without a requested logical level fail at lookup.

`model(profile, level)` resolves and freezes profile spec, model, effort, context, and security
without mutable shared overrides. The public session factory becomes
`session(profile="session", level="medium", config=None)`, preserving the existing positional
profile call. Each invocation constructs an effective immutable configuration locally. It must
not assign to the model facade, runtime defaults, profile maps, or session state. Provider
validation occurs before thread creation.

## Structured Schema and Validation

Add and export from core/root:

```python
@dataclass(frozen=True, slots=True)
class StructuredOutputPolicy:
    max_attempts: int = 2

def with_structured_output(
    schema: type[BaseModel] | dict[str, Any],
    *,
    policy: StructuredOutputPolicy | None = None,
) -> RuntimeModel[Any]: ...
```

Reject Pydantic instances, non-`BaseModel` classes, non-dictionary mappings, booleans masquerading
as schemas, invalid meta-schemas, and policies outside one through five attempts before provider
access. Copy caller dictionaries before validation and retain a frozen internal representation.
Pydantic classes produce their JSON Schema through `model_json_schema()` and validate with
`model_validate()`. Dictionary schemas use `Draft202012Validator.check_schema()` once and a
compiled validator per bound model. Provider text must parse as exactly one JSON value with no
Markdown-fence repair or trailing content.

## Structured Invocation and Streaming

One logical structured invocation creates one ephemeral Codex thread and one isolated workspace.
Every attempt calls `thread.turn(..., output_schema=<normalized schema>)`. On validation failure,
the next turn on that same thread receives a bounded feedback message containing only normalized
JSON paths, validator names, and corrective instructions; it never embeds the invalid output or
host secrets. The default is two total attempts. Provider, capability, timeout, interruption,
cancellation, and transport errors bypass validation retry.

Wrap provider-turn events in one logical invocation ID and resequence them monotonically.
Attempts retain distinct provider turn IDs and an `attempt` metadata field. Suppress
`OUTPUT_TEXT_DELTA` and per-attempt `INVOCATION_COMPLETED` events. On failure emit
`VALIDATION_FAILED`; before another attempt emit `RETRY_SCHEDULED`. Emit one final
`INVOCATION_COMPLETED` only after host validation, with `RuntimeResult[T]` and usage summed across
all attempts. Cancellation or timeout interrupts the active turn and follows Phase 1 cleanup.

Successful Pydantic values are model instances; dictionary-schema values are JSON-compatible
values. With `include_raw=False`, raw provider text is discarded. On exhausted validation,
`StructuredOutputError` exposes safe `attempts` and validation metadata plus a separate `raw`
property. That property is `None` unless `include_raw=True`; when enabled, it contains only the
last invalid text after conservative credential-pattern and secret-key redaction. Raw text never
appears in `str(error)`, `details`, events, diagnostics, or exporter-facing metadata.

## Context Policies

Ephemeral `external` invocation preserves Phase 1 role-aware serialization and never reuses a
thread across logical invocations. Persistent `runtime` sessions accept only new `user` messages.
Persistent `hybrid` sessions accept current `system` and `user` messages for the turn, serialize
system content as bounded current host context, and reject `assistant` or `tool` messages as
history replay. Empty effective user input remains invalid.

Factory checks enforce lifecycle and context before SDK thread creation. `model()` rejects
persistent profiles; `session()` rejects ephemeral or explicit profiles. Persistent structured
binding is not added to `RuntimeSession` in this phase.

## Session Resolution, Resume, and Migration

Change the neutral `RuntimeSession.descriptor` annotation to `str`; keep `SessionDescriptor` and
`SessionCodec` internal. Creation resolves the requested profile/level and fingerprints the
effective model, effort, profile spec, SDK family, sandbox, and approval policy. Resume resolves
model and effort from the descriptor profile/level under current configuration rather than the
runtime-wide catalog default, then requires the fingerprint to match.

`migrate_session(session_id, *, profile, level="medium", security_policy)` performs:

1. decode and validate descriptor version, provider, and active identity;
2. reject an active in-process turn with `SessionBusyError`;
3. resolve a persistent target profile/level and require the explicit security policy to match
   or reduce the target's effective permissions;
4. confirm the source provider thread exists by resuming it under the active identity;
5. resume that same thread with the target model and fail-closed settings;
6. generate a new configuration fingerprint and opaque descriptor;
7. close/invalidate old in-process handles without deleting provider history;
8. emit `SESSION_MIGRATED` with old/new neutral session IDs and safe profile/level metadata.

Migration intentionally does not require the old configuration fingerprint to match the current
configuration; this is the recovery path for changed mappings. It does require provider and
identity equality. No alias/revocation store is introduced, so an old externally persisted
descriptor is not globally revocable. Cross-provider/identity migration raises `CapabilityError`
or `SessionMismatchError`; missing provider history raises `SessionNotFoundError`; unsupported or
expanding permissions raise `SecurityPolicyError`/`CapabilityError` before a turn.

## Capabilities, Dependencies, and Compatibility

Add `SESSION_MIGRATED` to `RuntimeEventKind`. Advertise `structured_output=True` only for an
ephemeral profile whose schema binding, security, model, and SDK capabilities pass. Fakes mirror
configuration resolution, typed results, retry events, context rejection, and migration without
provider imports.

Add `jsonschema>=4,<5` to base dependencies and lock it. Keep core free of Codex, LangGraph,
LangSmith, and OpenTelemetry imports. `default_model`, text invocation, text streaming, existing
session descriptors, and Phase 1 error/lifecycle behavior remain compatible. Phase 2 hands off as
`0.3.0`; any unavoidable `0.x` contract correction is documented before release.
