# Rollout and rollback

## Delivery

Release as `0.3.1` from `codex/phase-2-1-cross-phase-conformance-hardening`. Changes are split
into reviewable English commits and pushed with upstream. CI must pass before SDD closure.

## Compatibility

Existing provider-neutral result identity remains `RuntimeIdentity`. Valid security-policy strings
remain accepted and normalized. Existing positional provider behavior remains unchanged. Invalid
roles, persistent `model()` usage, missing structured schemas and unsafe descriptors now fail
earlier and explicitly.

## Rollback

Revert commits in reverse order if a gate fails. No migration deletes history or threads. A failed
session migration retains the source descriptor/thread/workspace and removes only newly allocated
resources. A cleanup timeout invalidates the provider transport rather than returning a reusable
possibly active handle.

