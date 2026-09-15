# Acceptance Criteria — Phase 2

Each criterion is binary and requires automated output, reviewed artifacts, explicitly enabled
integration evidence, or a recorded inspection.

- `AC-P2-001`: The implementation record captures the starting commit, clean/known worktree,
  package/SDK/catalog baseline, and `46 passed, 3 skipped` without overwriting unrelated work.
  Requirements: `P2-REQ-020`. Tasks: `P2-TASK-0001`. Evidence: satisfied by the baseline
  inspection and local test run recorded in `03_task_plan.md`.
- `AC-P2-002`: UTF-8 configuration loads from environment or explicit path, the explicit path
  wins, no current/parent directory is searched, and missing/unreadable/invalid JSON fails at `$`.
  Requirements: `P2-REQ-001`. Tasks: `P2-TASK-0002`, `P2-TASK-0008`.
- `AC-P2-003`: Unknown keys, unsupported versions/runtimes, invalid fields, and missing mappings
  raise `ConfigurationError` with the exact stable dotted path and no document contents.
  Requirements: `P2-REQ-001`, `P2-REQ-004`. Tasks: `P2-TASK-0002`, `P2-TASK-0008`.
- `AC-P2-004`: Parsed profiles, mappings, custom specifications, metadata, and packaged defaults
  are deeply immutable and caller-owned inputs remain unchanged. Requirements: `P2-REQ-002`,
  `P2-REQ-004`. Tasks: `P2-TASK-0002`, `P2-TASK-0008`.
- `AC-P2-005`: Tests prove the documented precedence including `default_model` compatibility and
  field-wise invocation overlays; bound and concurrent calls never mutate one another.
  Requirements: `P2-REQ-002`. Tasks: `P2-TASK-0002`, `P2-TASK-0003`, `P2-TASK-0008`.
- `AC-P2-006`: Installed source and built artifacts contain the exact v1 mappings for all four
  levels of `brain`, `structured`, and `session`, and an opt-in catalog check confirms them.
  Requirements: `P2-REQ-003`. Tasks: `P2-TASK-0002`, `P2-TASK-0008`, `P2-TASK-0009`.
- `AC-P2-007`: Missing mappings, models, or efforts fail at their configuration path before
  thread creation and never select a catalog default or alternate model/level. Requirements:
  `P2-REQ-003`, `P2-REQ-005`. Tasks: `P2-TASK-0002`, `P2-TASK-0003`, `P2-TASK-0008`.
- `AC-P2-008`: Valid custom profile compositions resolve, while collisions, cross-reference
  gaps, incoherent lifecycle/context, deferred tools/security/native, and wrong factory use fail
  before thread creation. Requirements: `P2-REQ-004`, `P2-REQ-005`, `P2-REQ-013`,
  `P2-REQ-018`. Tasks: `P2-TASK-0003`, `P2-TASK-0006`, `P2-TASK-0008`.
- `AC-P2-009`: Core/config contain no provider/framework imports; Codex catalog and effective
  capability checks remain provider-local. Requirements: `P2-REQ-005`. Tasks:
  `P2-TASK-0003`, `P2-TASK-0008`.
- `AC-P2-010`: `StructuredOutputPolicy` is public, immutable, defaults to two attempts, rejects
  values outside one through five, and the protocol/fakes/provider share its signature.
  Requirements: `P2-REQ-006`. Tasks: `P2-TASK-0004`, `P2-TASK-0008`.
- `AC-P2-011`: Pydantic classes and valid Draft 2020-12 dictionaries bind without mutation;
  invalid schema kinds/meta-schemas fail before SDK access. Requirements: `P2-REQ-006`,
  `P2-REQ-007`. Tasks: `P2-TASK-0004`, `P2-TASK-0008`.
- `AC-P2-012`: Captured SDK calls prove every structured turn receives `output_schema`; successful
  output is independently host-validated into a Pydantic instance or JSON-compatible value.
  Requirements: `P2-REQ-007`, `P2-REQ-008`. Tasks: `P2-TASK-0004`, `P2-TASK-0008`,
  `P2-TASK-0009`.
- `AC-P2-013`: Empty, fenced, malformed, multiple, trailing, type-invalid, and constraint-invalid
  JSON never reaches a successful typed result. Requirements: `P2-REQ-007`, `P2-REQ-008`.
  Tasks: `P2-TASK-0004`, `P2-TASK-0008`.
- `AC-P2-014`: Validation failure retries on the same ephemeral thread/workspace with bounded
  path-only feedback and succeeds or stops at the configured attempt count. Requirements:
  `P2-REQ-009`. Tasks: `P2-TASK-0005`, `P2-TASK-0008`.
- `AC-P2-015`: The successful terminal result aggregates all attempt usage, retains one logical
  invocation ID and distinct turn IDs, and reports the selected model/profile/effort accurately.
  Requirements: `P2-REQ-009`, `P2-REQ-011`. Tasks: `P2-TASK-0005`, `P2-TASK-0008`,
  `P2-TASK-0009`.
- `AC-P2-016`: Authentication, capability, timeout, cancellation, interruption, and transport
  failures do not consume a structured validation retry and preserve cleanup behavior.
  Requirements: `P2-REQ-009`. Tasks: `P2-TASK-0005`, `P2-TASK-0008`.
- `AC-P2-017`: Structured streaming exposes no text delta or invalid terminal result, emits
  monotonic validation/retry events, and emits exactly one validated terminal invocation result.
  Requirements: `P2-REQ-011`. Tasks: `P2-TASK-0005`, `P2-TASK-0008`, `P2-TASK-0009`.
- `AC-P2-018`: Exhaustion raises `StructuredOutputError`; invalid text is absent by default and,
  when explicitly requested, exists only in the redacted `raw` property with leak tests proving
  absence from strings, details, diagnostics, events, and default results. Requirements:
  `P2-REQ-010`, `P2-REQ-018`. Tasks: `P2-TASK-0003`, `P2-TASK-0005`, `P2-TASK-0008`.
- `AC-P2-019`: Separate ephemeral invocations use separate threads and accept role-preserving
  external history without retaining runtime context. Requirements: `P2-REQ-012`. Tasks:
  `P2-TASK-0006`, `P2-TASK-0008`.
- `AC-P2-020`: Runtime sessions accept only user messages; hybrid sessions accept current
  system/user context; both reject assistant/tool replay before SDK access. Requirements:
  `P2-REQ-012`, `P2-REQ-013`. Tasks: `P2-TASK-0006`, `P2-TASK-0008`.
- `AC-P2-021`: Session creation and resume use the profile/level mapping, preserve same-thread
  history and concurrency/cleanup guarantees, and do not use the catalog default implicitly.
  Requirements: `P2-REQ-014`. Tasks: `P2-TASK-0007`, `P2-TASK-0008`, `P2-TASK-0009`.
- `AC-P2-022`: `RuntimeSession.descriptor` is publicly an opaque `str`; codec fields remain
  internal, contain no credentials, and are treated as untrusted on resume/migration.
  Requirements: `P2-REQ-017`. Tasks: `P2-TASK-0007`, `P2-TASK-0008`.
- `AC-P2-023`: A valid migration returns a new descriptor for the same provider thread, applies
  target profile/model/effort, invalidates old in-process handles, emits `SESSION_MIGRATED`, and
  neither replays nor deletes history. Requirements: `P2-REQ-015`. Tasks: `P2-TASK-0007`,
  `P2-TASK-0008`, `P2-TASK-0009`.
- `AC-P2-024`: Malformed, cross-provider, cross-identity, missing-thread, active-turn,
  unsupported-target, and permission-expansion migration fails through the documented Proteo
  error without unsafe provider work. Requirements: `P2-REQ-015`, `P2-REQ-016`. Tasks:
  `P2-TASK-0007`, `P2-TASK-0008`.
- `AC-P2-025`: Rollback or migration failure never archives/deletes user history, and tests
  document that externally stored old descriptors cannot be globally revoked in 1.0.
  Requirements: `P2-REQ-016`. Tasks: `P2-TASK-0007`, `P2-TASK-0008`.
- `AC-P2-026`: Effective capabilities advertise structured output only for an executable bound
  model and explicitly reject persistent structure, tools, native execution, unsupported
  security, and general retries. Requirements: `P2-REQ-018`. Tasks: `P2-TASK-0007`,
  `P2-TASK-0008`.
- `AC-P2-027`: The default suite cannot launch Codex, read authentication, access the network,
  or consume quota; real catalog/structured/migration checks require both the integration marker
  and `PROTEO_CODEX_INTEGRATION=1`. Requirements: `P2-REQ-019`. Tasks: `P2-TASK-0008`,
  `P2-TASK-0009`, `P2-TASK-0010`.
- `AC-P2-028`: Ruff, mypy, import-linter, branch-aware coverage >=90 percent, build, artifact
  inspection, and Linux/Windows Python 3.11–3.14 CI all pass. Requirements: `P2-REQ-020`.
  Tasks: `P2-TASK-0008`, `P2-TASK-0010`.
- `AC-P2-029`: Public documentation describes configuration precedence, defaults, custom
  profiles, structured output/raw risk, context ownership, migration, capability limits, and
  `0.3.0`; traceability is complete and the SDD is moved to `complete`. Requirements:
  `P2-REQ-020`. Tasks: `P2-TASK-0010`.
