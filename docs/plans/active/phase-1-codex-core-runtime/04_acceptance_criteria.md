# Acceptance Criteria — Phase 1

Each criterion is binary and requires automated output, reviewed artifacts, or explicitly
enabled integration evidence.

- `AC-P1-001`: The implementation record confirms the repository, dependency, SDK API, and
  test baseline without overwriting unrelated changes. Requirements: `P1-REQ-018`. Tasks:
  `P1-TASK-0001`.
- `AC-P1-002`: `CodexRuntime` is importable only from the intentional provider package, conforms
  to `Runtime`, and no core module imports SDK/provider code. Requirements: `P1-REQ-001`.
  Tasks: `P1-TASK-0002`, `P1-TASK-0008`.
- `AC-P1-003`: Startup, repeated startup, close, repeated close, restart, context exit, and
  partial-start failure release exactly one SDK/process lifecycle without leaked work.
  Requirements: `P1-REQ-002`. Tasks: `P1-TASK-0002`, `P1-TASK-0009`.
- `AC-P1-004`: Missing authentication and non-ChatGPT modes fail with `AuthenticationError`
  before thread creation. Requirements: `P1-REQ-003`. Tasks: `P1-TASK-0003`.
- `AC-P1-005`: Result identity exposes only a stable digest, auth mode, plan type, and precision
  indicator; tests prove email and credential-shaped values are absent. Requirements:
  `P1-REQ-003`. Tasks: `P1-TASK-0003`.
- `AC-P1-006`: Visible models and supported efforts map accurately to immutable `ModelInfo`
  values with no SDK objects. Requirements: `P1-REQ-004`, `P1-REQ-005`. Tasks:
  `P1-TASK-0003`.
- `AC-P1-007`: Missing, ambiguous, unavailable, or unsupported model/effort selections fail
  explicitly and never select an alternative. Requirements: `P1-REQ-005`. Tasks:
  `P1-TASK-0003`.
- `AC-P1-008`: Brain invocation uses one new ephemeral thread, deterministic role-preserving
  text, the validated model/effort, and returns normalized `RuntimeResult[str]`. Requirements:
  `P1-REQ-006`. Tasks: `P1-TASK-0004`, `P1-TASK-0009`.
- `AC-P1-009`: `structured` is recognized while schema binding raises `CapabilityError` without
  SDK access. Requirements: `P1-REQ-007`. Tasks: `P1-TASK-0004`.
- `AC-P1-010`: Every invocation uses an empty owned workspace, read-only sandbox, and deny-all
  approvals; callers cannot override these settings. Requirements: `P1-REQ-013`. Tasks:
  `P1-TASK-0004`.
- `AC-P1-011`: `session()` creates a non-ephemeral thread and returns a deterministic `prt1.`
  descriptor without credentials. Requirements: `P1-REQ-008`. Tasks: `P1-TASK-0006`,
  `P1-TASK-0009`.
- `AC-P1-012`: Valid resume preserves provider history; malformed, cross-provider,
  cross-identity, configuration, permission, and missing-thread cases raise the specified
  session errors before unsafe execution. Requirements: `P1-REQ-009`. Tasks: `P1-TASK-0006`.
- `AC-P1-013`: Concurrent turns fail immediately with `SessionBusyError`, and persistent
  assistant/tool/system replay fails with `ContextPolicyError`. Requirements: `P1-REQ-010`.
  Tasks: `P1-TASK-0006`.
- `AC-P1-014`: Session close preserves history, archive uses the stable SDK API, and delete uses
  only the private version-checked typed shim and removes the disposable integration thread.
  Requirements: `P1-REQ-010`, `P1-REQ-017`. Tasks: `P1-TASK-0006`, `P1-TASK-0009`.
- `AC-P1-015`: `migrate_session()` raises `CapabilityError` without an SDK request.
  Requirements: `P1-REQ-010`. Tasks: `P1-TASK-0006`.
- `AC-P1-016`: Streaming emits normalized start, delta, usage, and terminal events in causal
  order and does not expose raw notifications. Requirements: `P1-REQ-011`. Tasks:
  `P1-TASK-0005`.
- `AC-P1-017`: A normally drained stream ends with `INVOCATION_COMPLETED.result` equal to the
  result from `ainvoke()` for the same scripted SDK turn; fakes obey the same contract.
  Requirements: `P1-REQ-011`, `P1-REQ-015`. Tasks: `P1-TASK-0005`, `P1-TASK-0007`.
- `AC-P1-018`: All SDK token categories and duration map correctly; unavailable values remain
  `None` and sanitized provider-only counters stay under `usage.raw`. Requirements:
  `P1-REQ-012`. Tasks: `P1-TASK-0005`.
- `AC-P1-019`: `raw` is absent by default and contains only the documented immutable safe
  mapping when requested. Requirements: `P1-REQ-015`. Tasks: `P1-TASK-0005`.
- `AC-P1-020`: SDK failure classes and statuses map to stable Proteo errors with safe causes and
  zero automatic retries. Requirements: `P1-REQ-014`. Tasks: `P1-TASK-0005`.
- `AC-P1-021`: Timeout, cancellation, abandoned stream, session close, and runtime close request
  interruption, release locks/workspaces, and invalidate an unconfirmed transport.
  Requirements: `P1-REQ-014`, `P1-REQ-015`. Tasks: `P1-TASK-0005`, `P1-TASK-0007`.
- `AC-P1-022`: The default suite cannot launch Codex, read real auth, access network, or consume
  quota; integration tests are skipped unless explicitly enabled. Requirements: `P1-REQ-016`.
  Tasks: `P1-TASK-0001`, `P1-TASK-0008`, `P1-TASK-0010`.
- `AC-P1-023`: An explicit ChatGPT-backed integration run validates catalog, brain invocation,
  streaming, persistent create/resume, and disposable thread cleanup. Requirements:
  `P1-REQ-016`. Tasks: `P1-TASK-0009`, `P1-TASK-0010`.
- `AC-P1-024`: Ruff, mypy, import-linter, coverage, builds, artifact inspection, Linux/Windows
  Python 3.11–3.14 CI, public docs, version `0.2.0`, and complete traceability all pass.
  Requirements: `P1-REQ-018`. Tasks: `P1-TASK-0001`, `P1-TASK-0007`, `P1-TASK-0008`,
  `P1-TASK-0010`.
