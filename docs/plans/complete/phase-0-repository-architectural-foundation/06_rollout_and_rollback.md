# Rollout and Rollback — Phase 0

## Delivery Strategy

Phase 0 is delivered as a documentation-driven foundation in small reviewable commits or pull requests. Keep the order from `03_task_plan.md` so each layer can be verified before the next one depends on it.

1. Baseline and tooling metadata.
2. Package topology and import boundaries.
3. Core values, policies, protocols, events, usage, diagnostics, and errors.
4. Strict configuration models and `SessionCodec`.
5. Fake runtime and contract tests.
6. CLI, README, CI matrix, evidence, and handoff.

No production data migration, external service deployment, authentication change, or user-facing rollout is required. The package is pre-1.0 and remains explicitly experimental until later phases define provider behavior.

## Review Gates

Each gate requires all linked checks to pass before merging:

- **Gate A — Buildable repository:** package metadata, license, README, editable install, wheel/sdist build, and CLI version.
- **Gate B — Frozen architecture:** import-linter rules, public export review, and no provider/framework imports in core.
- **Gate C — Contract behavior:** value objects, policies, errors, configuration, session codec, fake runtime, and contract tests.
- **Gate D — Reproducible quality:** Ruff, mypy, pytest/coverage, quota-safety guards, and Linux/Windows CI matrix.
- **Gate E — Documentation handoff:** traceability complete, deferred scope explicit, and acceptance evidence attached.

## Rollback

Rollback is a source-control operation because Phase 0 changes only repository files:

- Before merge, discard or revise the isolated branch; do not reset a shared worktree or remove unrelated user changes.
- After merge, revert the Phase 0 commit(s) or revert the pull request as a single reviewable change.
- If only a contract defect is found, preserve the SDD and issue a follow-up patch with an explicit versioned decision; do not silently change public names or encodings.
- If the dependency range becomes incompatible, pin the last known-good `openai-codex` range, record the compatibility decision, and keep fake tests runnable without Codex.
- If CI exposes a platform-specific issue, block completion and leave the SDD under `docs/plans/active/` until the matrix is green.

## Completion Handoff

When all `AC-P0-*` criteria pass, record command output and CI links in the implementation record, mark all completed tasks `done`, mark later-phase work `deferred`, and move the entire directory unchanged to `docs/plans/complete/`. The next implementation plan must reference this completed package as its Phase 0 baseline.
