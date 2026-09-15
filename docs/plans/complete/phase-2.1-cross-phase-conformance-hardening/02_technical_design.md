# Technical design

## Contract corrections

`ProfileSpec` stores a `SecurityPolicy` value object and normalizes compatible strings at its
boundary. `RuntimeMessage` validates its role literal at construction. The built-in native
profile is `EXPLICIT/EXPLICIT`. `RuntimeResult.runtime` remains `RuntimeIdentity`; the guide is
updated to match the implementation.

## Codex runner state machine

The runner has one terminal outcome per invocation. Only `turn/completed` may construct a
`RuntimeResult`. Provider failed/interrupted states map to existing neutral errors and failure
events. EOF before a terminal maps to `TransportError`. The stream finalizer requests interruption,
waits a bounded grace period, and marks an unconfirmed SDK transport unusable.

Runtime shutdown first prevents new work, interrupts and awaits all registered runs, then closes
the SDK and removes only workspaces owned by the runtime.

## Configuration and immutable bindings

Startup fetches one catalog and validates the complete configured mapping table. A compatibility
`default_model` is resolved only when explicitly requested. `model()` and `session()` capture an
immutable resolved binding. Invocation configuration creates a temporary field-wise overlay;
it never changes the facade or another concurrent invocation. Structured facades expose effective
structured capability only after a schema is bound.

## Descriptor trust and migration

Descriptor bytes are untrusted input. Resume resolves the current profile specification first,
then compares descriptor provider, identity, context, security, mapping and fingerprint against
that trusted configuration. Migration uses the provider thread encoded by the validated descriptor,
not the local alias registry. A successful migration commits the new descriptor and workspace,
invalidates old generations, emits neutral old/new IDs and safe profile/level metadata, then removes
the old workspace. Any failed preparation removes only newly created resources.

## Fake parity and security

Fakes use immutable schema snapshots, the same include-raw precedence and sanitized diagnostics,
hide intermediate structured output from public events, aggregate usage across attempts, and model
the same lifecycle terminal guarantees. No credential, raw descriptor or provider-specific secret
is placed in events or errors.
