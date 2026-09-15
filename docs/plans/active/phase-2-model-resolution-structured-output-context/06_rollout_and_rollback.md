# Rollout and Rollback — Phase 2

## Delivery Sequence

1. Land schema-v1 additions, packaged defaults, loader, and tests without connecting them to Codex.
2. Land immutable resolver/profile integration and remove mutable per-call facade state.
3. Land schema normalization, host validation, and provider `output_schema` binding.
4. Land structured validation retry, usage aggregation, buffered streaming, and raw isolation.
5. Land context-policy corrections and same-thread session migration.
6. Complete fakes, contract/quota guards, the local quality matrix, and artifact checks.
7. Run explicitly authorized disposable Codex integration, update public docs/version, record
   evidence, and close the SDD.

Every step must keep text invocation and existing persistent-session behavior testable. No step
may enable real-runtime tests, native permissions, tools, or configuration discovery by default.

## Compatibility Rules

- Preserve `CodexRuntime(default_model)` and text `ainvoke`/`astream` behavior from `0.2.0`.
- Existing valid configuration payloads remain valid because `profile_specs` is optional.
- Existing `prt1.` strings keep their encoding. Resume may reject a descriptor when the active
  resolved configuration no longer matches; explicit migration is the recovery operation.
- Correcting `RuntimeSession.descriptor` to `str` aligns typing with existing runtime behavior and
  does not change its wire value.
- Correcting `controlled_agent` context to `external` is a documented pre-1.0 contract correction;
  that profile remains non-executable until host tools exist.

## Release Gate

Phase 2 is releasable as `0.3.0` only when every `AC-P2-*` is satisfied, the packaged mappings
match an authorized live catalog check, artifacts include/load their defaults, default tests prove
quota safety, and one sanitized opt-in run proves provider schema enforcement plus migration.

Release notes must identify concrete model mappings as versioned and potentially time-sensitive.
They must list persistent structured sessions, tools, native execution, strong isolation, general
retry, LangGraph, and observers as unavailable rather than silently degraded.

## Runtime Rollback

Applications can roll back by removing JSON/custom-profile/structured/migration use and returning
to the `0.2.0` text and session surface. Rollback never archives or deletes Codex threads. Hosts
must retain the opaque descriptor that matches the version/configuration they intend to resume.

If a packaged model disappears, fail startup/configuration resolution and publish a new mapping;
do not hot-substitute a model. A caller can temporarily supply `default_model` or an explicit
validated configuration only when that choice is intentional and available.

## Code Rollback

Revert in reverse delivery order while preserving schema/implementation compatibility within each
commit. Revert event/protocol changes together with fakes and contract tests. Revert dependency and
package-data changes together with structured/config loader code. Never rewrite, delete, archive,
or bulk-migrate real user sessions as a rollback action.

## Failure Containment

- Configuration/catalog failure prevents thread creation.
- Schema/policy failure prevents a structured attempt.
- Validation exhaustion affects only the logical invocation and removes its ephemeral workspace.
- Timeout/cancellation interrupts only the active attempt and invalidates transport on unconfirmed
  interruption under the Phase 1 rule.
- Migration failure leaves provider history intact and returns no successful new descriptor.
- An old descriptor cannot be globally revoked without an alias store; this limitation remains
  explicit in documentation and is not disguised as a successful revocation.
