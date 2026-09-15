# Acceptance criteria

- `AC-C21-001`: The SDD package exists under `active/`, has nine documents, and all tasks start
  `pending`. Requirements: `C21-REQ-017`. Tasks: `C21-TASK-0001`, `C21-TASK-0008`.
- `AC-C21-002`: Native resolves to explicit lifecycle and explicit context. Requirements:
  `C21-REQ-001`. Task: `C21-TASK-0002`.
- `AC-C21-003`: Invalid RuntimeMessage roles fail at construction. Requirements: `C21-REQ-002`.
  Task: `C21-TASK-0002`.
- `AC-C21-004`: Security policy values normalize or fail closed. Requirements: `C21-REQ-003`.
  Task: `C21-TASK-0002`.
- `AC-C21-005`: Failed and interrupted turns never return or emit successful completion.
  Requirements: `C21-REQ-004`. Task: `C21-TASK-0003`.
- `AC-C21-006`: Missing stream terminal fails with no fabricated result. Requirements:
  `C21-REQ-005`. Task: `C21-TASK-0003`.
- `AC-C21-007`: Abandoned streams request interruption and release or invalidate transport.
  Requirements: `C21-REQ-006`. Task: `C21-TASK-0003`.
- `AC-C21-008`: Runtime close waits for registered runs before SDK/workspace cleanup. Requirements:
  `C21-REQ-006`. Task: `C21-TASK-0003`.
- `AC-C21-009`: Fake lifecycle matches the provider terminal contract. Requirements:
  `C21-REQ-014`. Tasks: `C21-TASK-0003`, `C21-TASK-0006`.
- `AC-C21-010`: Startup validates all twelve mappings against one catalog. Requirements:
  `C21-REQ-007`, `C21-REQ-016`. Tasks: `C21-TASK-0004`, `C21-TASK-0007`.
- `AC-C21-011`: No implicit default/fallback is required for configured mappings. Requirements:
  `C21-REQ-007`. Task: `C21-TASK-0004`.
- `AC-C21-012`: Bound models/sessions remain unchanged across config mutation and concurrency.
  Requirements: `C21-REQ-008`. Task: `C21-TASK-0004`.
- `AC-C21-013`: Persistent profiles are rejected by model() and structured calls require schema.
  Requirements: `C21-REQ-009`. Task: `C21-TASK-0004`.
- `AC-C21-014`: Custom mappings/specs cross-validate with exact paths. Requirements:
  `C21-REQ-010`. Task: `C21-TASK-0004`.
- `AC-C21-015`: Invocation overlays do not mutate shared bindings. Requirements: `C21-REQ-008`.
  Tasks: `C21-TASK-0004`, `C21-TASK-0006`.
- `AC-C21-016`: Non-string resume input fails before descriptor decoding. Requirements:
  `C21-REQ-011`. Task: `C21-TASK-0005`.
- `AC-C21-017`: Descriptor fields cannot select current context or security. Requirements:
  `C21-REQ-011`. Task: `C21-TASK-0005`.
- `AC-C21-018`: Busy resume fails before resource mutation. Requirements: `C21-REQ-012`.
  Task: `C21-TASK-0005`.
- `AC-C21-019`: Descriptor-only migration preserves provider identity and thread. Requirements:
  `C21-REQ-013`. Task: `C21-TASK-0005`.
- `AC-C21-020`: Successful migration issues a new descriptor and invalidates old handles.
  Requirements: `C21-REQ-013`. Task: `C21-TASK-0005`.
- `AC-C21-021`: Migration emits safe old/new metadata and never leaks old workspaces or history.
  Requirements: `C21-REQ-013`. Task: `C21-TASK-0005`.
- `AC-C21-022`: Fakes preserve schema immutability, include_raw precedence, redaction, retries,
  usage and event visibility. Requirements: `C21-REQ-014`. Task: `C21-TASK-0006`.
- `AC-C21-023`: Named semantic tests cover every P0/P1 lifecycle and trust invariant.
  Requirements: `C21-REQ-015`. Task: `C21-TASK-0006`.
- `AC-C21-024`: Opt-in integration validates twelve mappings without twelve inference calls.
  Requirements: `C21-REQ-016`. Task: `C21-TASK-0007`.
- `AC-C21-025`: Guide, README and errata state the corrected contracts and preserve history.
  Requirements: `C21-REQ-017`. Tasks: `C21-TASK-0001`, `C21-TASK-0008`.
- `AC-C21-026`: Version, lock and artifact checks report `0.3.1` and the new artifact name.
  Requirements: `C21-REQ-017`. Task: `C21-TASK-0007`.
- `AC-C21-027`: Ruff, mypy, import-linter, pre-commit, tests, coverage, build and isolated installs
  pass locally. Requirements: `C21-REQ-015`, `C21-REQ-017`. Task: `C21-TASK-0007`.
- `AC-C21-028`: Opt-in Codex smokes pass using only disposable test resources. Requirements:
  `C21-REQ-016`. Task: `C21-TASK-0007`.
- `AC-C21-029`: Remote CI passes on Linux/Windows Python 3.11–3.14 for both implementation and
  closure commits. Requirements: `C21-REQ-017`. Tasks: `C21-TASK-0007`, `C21-TASK-0008`.
