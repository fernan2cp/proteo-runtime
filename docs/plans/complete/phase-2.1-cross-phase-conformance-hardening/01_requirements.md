# Requirements

Estado de cierre: todos los requisitos `C21-REQ-001`–`C21-REQ-017` están `done`, con evidencia
en el plan de tareas y la matriz de trazabilidad.

## Core contracts

- `C21-REQ-001`: `native` MUST use `explicit` lifecycle and `explicit` context; its provider
  security and host-tools opt-ins remain unchanged.
- `C21-REQ-002`: `RuntimeMessage` MUST reject roles outside `system`, `user`, `assistant`,
  and `tool` at runtime.
- `C21-REQ-003`: `ProfileSpec.security_policy` MUST normalize valid values to `SecurityPolicy`
  and reject unknown values.

## Codex lifecycle

- `C21-REQ-004`: failed or interrupted provider turns MUST NOT emit a successful result.
- `C21-REQ-005`: a stream without a terminal event MUST fail and MUST NOT fabricate a result.
- `C21-REQ-006`: abandoned streams and runtime close MUST interrupt active work and confirm or
  invalidate cleanup before returning.

## Configuration and resolution

- `C21-REQ-007`: startup MUST validate every configured profile/level model and effort against
  one fetched catalog; no implicit default discovery or fallback is allowed.
- `C21-REQ-008`: model and session facades MUST freeze their resolved binding; invocation
  overrides are field-wise, local, and non-mutating.
- `C21-REQ-009`: persistent profiles MUST be rejected by `model()`, and structured invocation
  MUST require a schema before SDK access.
- `C21-REQ-010`: custom profile mappings and `profile_specs` MUST be cross-validated with exact
  configuration paths.

## Sessions and migration

- `C21-REQ-011`: `resume_session()` MUST accept only `str` and validate descriptors against the
  current trusted profile, context, security, identity, provider, and frozen configuration.
- `C21-REQ-012`: resume MUST fail before mutation when a local session is busy.
- `C21-REQ-013`: migration MUST work from a valid descriptor without requiring local `_sessions`,
  preserve the same Codex thread/identity, issue a new descriptor, invalidate old handles, emit
  auditable old/new metadata, and clean the previous workspace safely.

## Fakes, evidence and docs

- `C21-REQ-014`: fakes MUST mirror observable terminal, structured-output, retry, redaction,
  usage, stream and migration semantics.
- `C21-REQ-015`: tests MUST cover semantic lifecycle, trust, immutability and mapping invariants,
  not only a percentage threshold.
- `C21-REQ-016`: opt-in integration MUST validate all twelve mappings by catalog/capability checks
  and use only representative real inference smokes.
- `C21-REQ-017`: public documentation, version `0.3.1`, packaging metadata and historical errata
  MUST describe the corrected contracts without rewriting historical evidence.
