# Acceptance Criteria — Smart Quote Agent Example

All criteria start in state `pending`.

---

- `AC-SQA-001`: **Strict Directory Isolation & Zero Repository Pollution**
  **State:** `pending`
  **Requirements:** `SQA-REQ-001`
  **Tasks:** `SQA-TASK-0001`, `SQA-TASK-0010`
  *Criterion:* Executing `git status --short` confirms that zero files outside `examples/smart_quote_agent/` have been created, modified, or deleted. All example artifacts, code, and data reside strictly within `examples/smart_quote_agent/*`.

- `AC-SQA-002`: **Deterministic SQLite Provisioning & Seeding**
  **State:** `pending`
  **Requirements:** `SQA-REQ-002`
  **Tasks:** `SQA-TASK-0002`
  *Criterion:* Running `python examples/smart_quote_agent/init_demo.py --reset` provisions the database at `examples/smart_quote_agent/data/demo.sqlite3`, enables foreign keys, and seeds exactly 4 customers, 5 users (1 staff, 4 clients) with password `1234`, and 6 active products with accurate integer-cent prices.

- `AC-SQA-003`: **Masked Password Authentication & Sanitized State**
  **State:** `pending`
  **Requirements:** `SQA-REQ-003`, `SQA-REQ-004`, `SQA-REQ-009`
  **Tasks:** `SQA-TASK-0003`, `SQA-TASK-004`, `SQA-TASK-0008`
  *Criterion:* Password entry uses `getpass.getpass()`, suppressing terminal character echo. Valid credentials populate graph state solely with sanitized `AuthenticatedUser` fields. Invalid credentials reject login without changing state. Raw passwords are deleted immediately and never enter graph state, tool arguments, runtime events, or logs.

- `AC-SQA-004`: **Anonymous and Client Authorization Limits**
  **State:** `pending`
  **Requirements:** `SQA-REQ-004`, `SQA-REQ-005`, `SQA-REQ-008`
  **Tasks:** `SQA-TASK-0004`, `SQA-TASK-0005`, `SQA-TASK-0007`
  *Criterion:* Anonymous and client sessions are permitted to list products, search products, and compute quote previews. Any request to resolve customers, create persisted quotes, or inspect quote history is denied immediately by the host guard before any mutation can occur.

- `AC-SQA-005`: **Staff Capability Enforcement**
  **State:** `pending`
  **Requirements:** `SQA-REQ-004`, `SQA-REQ-005`, `SQA-REQ-008`
  **Tasks:** `SQA-TASK-0004`, `SQA-TASK-0005`, `SQA-TASK-0007`
  *Criterion:* Authenticated staff sessions are authorized to search customers, calculate quote drafts, initiate quote creation, list recent quotes, and view quote line details via the staff `ToolPermissionPolicy`.

- `AC-SQA-006`: **Interactive Discount Validation**
  **State:** `pending`
  **Requirements:** `SQA-REQ-007`
  **Tasks:** `SQA-TASK-0006`
  *Criterion:* The discount prompt accepts an integer percentage between 0 and 30. An empty input resolves to 0. Inputs outside 0–30 or non-numeric entries are rejected and re-prompted without crashing or defaulting to arbitrary figures.

- `AC-SQA-007`: **Quote Persistence Approval Gate & Transactional Atomicity**
  **State:** `pending`
  **Requirements:** `SQA-REQ-005`, `SQA-REQ-006`, `SQA-REQ-007`
  **Tasks:** `SQA-TASK-0005`, `SQA-TASK-0006`
  *Criterion:* Invoking `create_quote` triggers Proteo's Phase 5 `ApprovalHandler`. When the user rejects the prompt, zero rows are inserted into `quotes` or `quote_lines`. When the user approves, quote header and all line items are committed in a single atomic transaction with an ISO-8601 UTC timestamp and creator staff ID.

- `AC-SQA-008`: **Monetary Integrity and Price Re-Reading**
  **State:** `pending`
  **Requirements:** `SQA-REQ-002`, `SQA-REQ-006`
  **Tasks:** `SQA-TASK-0002`
  *Criterion:* Product prices are re-read from SQLite before calculating quote totals, ignoring any hallucinated prices from the LLM. Calculations use `Decimal` with `ROUND_HALF_UP` rounding, and amounts persist as integer cents. Historical price changes to products do not affect previously stored quote lines.

- `AC-SQA-009`: **Controlled Agent Catalog Routing & Sandboxing**
  **State:** `pending`
  **Requirements:** `SQA-REQ-008`, `SQA-REQ-009`
  **Tasks:** `SQA-TASK-0007`, `SQA-TASK-0008`
  *Criterion:* Conversational requests regarding product features, availability, and pricing route to `controlled_agent`. The agent is bounded by host-managed tools and possesses no access to the OS shell, local files outside the database query functions, raw SQL execution, or network requests.

- `AC-SQA-010`: **Secret-Safe Metadata-Only Observability**
  **State:** `pending`
  **Requirements:** `SQA-REQ-008`, `SQA-REQ-009`, `SQA-REQ-010`
  **Tasks:** `SQA-TASK-0007`, `SQA-TASK-0008`
  *Criterion:* Telemetry events emitted by the runtime and tools contain only correlation IDs and execution metadata (`PayloadMode.METADATA_ONLY`). Authentication events do not expose credentials.

- `AC-SQA-011`: **Strict Type Safety, Style and Documentation Conformance**
  **State:** `pending`
  **Requirements:** `SQA-REQ-003`, `SQA-REQ-011`, `SQA-REQ-012`, `SQA-REQ-013`
  **Tasks:** `SQA-TASK-0003`, `SQA-TASK-0009`, `SQA-TASK-0010`
  *Criterion:* `uv run mypy examples/smart_quote_agent --strict`, `uv run ruff check examples/smart_quote_agent`, and `uv run ruff format --check examples/smart_quote_agent` pass with zero errors. All functions and methods contain Google-style docstrings in English. `examples/smart_quote_agent/README.md` provides full setup and verification instructions.
