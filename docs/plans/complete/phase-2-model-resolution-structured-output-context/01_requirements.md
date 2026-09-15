# Requirements — Phase 2

## Configuration and Resolution

- `P2-REQ-001`: The package MUST load strict schema-version-one JSON as UTF-8 from the path
  selected by `PROTEO_RUNTIME_CONFIG` or explicit `config_path`; the explicit path MUST win,
  implicit current/parent directory discovery MUST NOT occur, and file, decode, JSON, version,
  runtime, and unknown-key failures MUST be path-aware `ConfigurationError` values.
- `P2-REQ-002`: Resolution MUST apply increasing precedence from packaged defaults, selected
  JSON, typed runtime initialization, and non-`None` invocation fields. A model or session MUST
  freeze its resolved values, and one-call overrides MUST NOT mutate later or concurrent calls.
  `InvocationConfig.include_raw` MUST distinguish inheritance (`None`) from an explicit `False`;
  metadata MUST merge by key and a method-level `include_raw` argument MUST take precedence.
- `P2-REQ-003`: Version-one defaults MUST explicitly map `brain`, `structured`, and `session`
  at `low`, `medium`, `high`, and `ultra` to the model/effort matrix in the baseline. Missing or
  unavailable mappings MUST fail without catalog-default, cross-level, or cross-model fallback.
- `P2-REQ-004`: `RuntimeConfigV1.profile_specs` MUST support fully composed custom profile
  lifecycle, context, security, and host-tool declarations, cross-reference their model maps,
  reject built-in redefinition and incoherent combinations, and preserve immutable values.
- `P2-REQ-005`: Profile and mapping resolution MUST remain provider-neutral in core/config.
  Codex catalog validation and effective-capability rejection MUST stay in the provider boundary
  and occur before a thread or turn is created.

## Structured Output

- `P2-REQ-006`: The public API MUST expose immutable `StructuredOutputPolicy(max_attempts=2)`
  with a valid range of one through five, and `with_structured_output(schema, *, policy=None)`
  MUST accept a Pydantic `BaseModel` class or a dictionary JSON Schema without mutating either.
- `P2-REQ-007`: Pydantic schemas MUST normalize through `model_json_schema()` and validate to
  model instances. Dictionary schemas MUST pass Draft 2020-12 meta-schema validation and return
  JSON-compatible values validated by `jsonschema`; malformed schemas MUST fail before SDK use.
- `P2-REQ-008`: Every structured attempt MUST pass `output_schema` to the stable SDK turn API,
  parse exactly one JSON value, and perform host validation even when provider enforcement
  succeeds.
- `P2-REQ-009`: Validation retry MUST use one ephemeral thread/workspace per logical invocation,
  bounded sanitized feedback, one initial attempt plus one retry by default, distinct turn IDs,
  accumulated usage, and no retry for authentication, capability, timeout, cancellation, or
  transport failures.
- `P2-REQ-010`: Exhausted validation MUST raise `StructuredOutputError` with safe attempt and
  validation metadata. Invalid provider text MUST be absent unless `include_raw=True`, and even
  then MUST remain outside exception messages, details, events, diagnostics, and default exports.
- `P2-REQ-011`: Structured `astream()` MUST buffer and suppress provider text deltas and invalid
  terminal results, emit correlated validation/retry events, and finish with exactly one
  `INVOCATION_COMPLETED` containing the validated `RuntimeResult[T]`.

## Context and Persistent Sessions

- `P2-REQ-012`: Ephemeral models MUST use `external` context and accept host-supplied neutral
  history. Persistent sessions MUST reject `external`; `runtime` accepts only new user messages,
  while `hybrid` accepts current system/user context and rejects assistant/tool replay.
- `P2-REQ-013`: Built-in profile semantics MUST match the project guide, including
  `controlled_agent` using `external`. Model and session factories MUST reject lifecycle/context
  combinations they cannot execute, with no permission or capability expansion.
- `P2-REQ-014`: Session create and resume MUST resolve model/effort from frozen profile and level,
  include the effective profile/context/security configuration in the fingerprint, expose a
  `level="medium"` session-factory argument while preserving positional profile compatibility,
  and preserve the existing one-active-turn and cleanup guarantees.
- `P2-REQ-015`: Same-Codex, same-identity migration MUST validate the source descriptor and
  provider thread, require a supported persistent target, prevent permission expansion, resume
  the same thread with target configuration, issue a new descriptor, invalidate old in-process
  handles, and emit a neutral `SESSION_MIGRATED` event.
- `P2-REQ-016`: Cross-provider, cross-identity, missing-thread, malformed-descriptor, active-turn,
  unsupported target, and permission-expansion migration MUST fail through stable Proteo errors
  without replaying, copying, archiving, or deleting history.
- `P2-REQ-017`: The public `RuntimeSession.descriptor` contract MUST be the opaque `str`; decoded
  `SessionDescriptor` data MUST remain internal and untrusted.

## Compatibility and Quality

- `P2-REQ-018`: Runtime and model effective capabilities MUST report structured output only where
  the complete Phase 2 path is executable. Deferred tools, native execution, read-root policy,
  strong isolation, persistent structured sessions, and general retry MUST fail explicitly.
- `P2-REQ-019`: Default tests MUST use fakes/doubles and MUST NOT launch Codex, read real auth,
  access the network, or consume subscription quota. Real catalog and structured calls MUST stay
  behind `PROTEO_CODEX_INTEGRATION=1` and the `integration` marker.
- `P2-REQ-020`: Phase 2 MUST preserve the core/provider/framework dependency boundary, English
  Google-style docstrings, Python 3.11–3.14 support, coverage of at least 90 percent, strict
  quality gates, installable artifacts, documented public APIs, and an explicit `0.3.0` handoff.
