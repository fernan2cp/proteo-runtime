# Rollout and Rollback — Phase 1

## Delivery Sequence

1. Land neutral event additions and fake parity while preserving all Phase 0 tests.
2. Land the private SDK boundary, lifecycle, auth/catalog mapping, and unit tests.
3. Land brain invocation, security mapping, shared turn runner, and normalized failures.
4. Land persistent session lifecycle and the isolated delete shim.
5. Run the full quota-safe matrix, then the explicit disposable integration smoke suite.
6. Update README/public examples, set version `0.2.0`, record evidence, and complete the SDD.

Each step must remain reviewable and keep `import proteo_runtime` provider-free. No step may
enable real-runtime tests by default.

## Release Gate

Phase 1 is releasable only when all `AC-P1-*` are satisfied, package artifacts install cleanly,
the default suite proves quota safety, and one sanitized real-runtime run confirms the pinned SDK
integration. Release notes must identify structured output, migration, advanced configuration,
strong isolation, and automatic retries as unavailable.

## Runtime Rollback

Applications can roll back by removing use of `proteo_runtime.providers.codex.CodexRuntime` and
continuing to use the unchanged provider-neutral core and `FakeRuntime`. Persistent Codex thread
data is owned by Codex and is not deleted by package rollback. Hosts must retain opaque session
IDs only if they intend to resume with a compatible future build.

## Code Rollback

Revert provider commits in reverse delivery order. Revert the neutral terminal-result/event
change only together with corresponding fake and contract-test changes. Never delete or archive
real user threads as a rollback action. The private delete shim can be disabled independently if
SDK compatibility fails; session deletion must then fail explicitly with `CapabilityError`, not
silently report success.

## Failure Containment

- Authentication or catalog failure prevents all thread creation.
- Sandbox mapping failure prevents invocation.
- Unconfirmed interruption invalidates the runtime transport before reuse.
- Integration cleanup failure reports the disposable thread identifier through a local,
  non-published recovery record and fails the integration run.
- SDK range changes require a new compatibility review and traceability update before release.
