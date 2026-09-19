# Acceptance Criteria — Smart Quote Agent Example

All criteria start in state `pending`.

---

- `AC-SQA-001`: **Bounded Change Isolation**
  **State:** `done`
  **Requirements:** `SQA-REQ-001`
  **Tasks:** `SQA-TASK-0001`, `SQA-TASK-0010`
  *Criterion:* Implementation changes are confined to `examples/smart_quote_agent/*` plus the explicitly authorized active SDD package. No implementation change touches `src/*`, repository tests, configuration, public runtime contracts, or the business database schema. Existing user changes are preserved and are not treated as implementation changes.
  *Evidence:* Compare the implementation diff against the starting worktree state; report pre-existing changes separately. Do not use a clean-worktree assertion as evidence when unrelated user changes are present.

- `AC-SQA-002`: **Deterministic SQLite Provisioning & Seeding**
  **State:** `done`
  **Requirements:** `SQA-REQ-002`
  **Tasks:** `SQA-TASK-0002`
  *Criterion:* Running `python examples/smart_quote_agent/init_demo.py --reset` provisions the database at `examples/smart_quote_agent/data/demo.sqlite3`, enables foreign keys, and seeds exactly 4 customers, 5 users (1 staff, 4 clients) with password `1234`, and 6 active products with accurate integer-cent prices.
  *Evidence:* Verified with `init_demo.py --reset` and assertion tests on table row counts and schema constraints.

- `AC-SQA-003`: **Masked Password Authentication & Sanitized State**
  **State:** `done`
  **Requirements:** `SQA-REQ-003`, `SQA-REQ-004`, `SQA-REQ-009`
  **Tasks:** `SQA-TASK-0003`, `SQA-TASK-004`, `SQA-TASK-0008`
  *Criterion:* Password entry uses `getpass.getpass()`, suppressing terminal character echo. Valid credentials populate graph state solely with sanitized `AuthenticatedUser` fields. Invalid credentials reject login without changing state. Raw passwords are deleted immediately and never enter graph state, tool arguments, runtime events, or logs.
  *Evidence:* Verified with unit assertions on authenticate_user_credentials and authenticate_user_interactive using mock getpass.

- `AC-SQA-004`: **Anonymous and Client Authorization Limits**
  **State:** `done`
  **Requirements:** `SQA-REQ-004`, `SQA-REQ-005`, `SQA-REQ-008`
  **Tasks:** `SQA-TASK-0004`, `SQA-TASK-0005`, `SQA-TASK-0007`
  *Criterion:* Anonymous and client sessions are permitted to list products, search products, and compute quote previews. Any request to resolve customers, create persisted quotes, or inspect quote history is denied immediately by the host guard before any mutation can occur.
  *Evidence:* Verified with StateGraph test confirming anonymous and client quote creation attempts are blocked by auth_guard.

- `AC-SQA-005`: **Staff Capability Enforcement**
  **State:** `done`
  **Requirements:** `SQA-REQ-004`, `SQA-REQ-005`, `SQA-REQ-008`
  **Tasks:** `SQA-TASK-0004`, `SQA-TASK-0005`, `SQA-TASK-0007`
  *Criterion:* Authenticated staff sessions are authorized to search customers, calculate quote drafts, initiate quote creation, list recent quotes, and view quote line details via the staff `ToolPermissionPolicy`.
  *Evidence:* Verified with StateGraph test confirming staff user creates quote #1, lists recent quotes, and views quote details.

- `AC-SQA-006`: **Interactive Discount Validation**
  **State:** `done`
  **Requirements:** `SQA-REQ-007`
  **Tasks:** `SQA-TASK-0006`
  *Criterion:* The discount prompt accepts an integer percentage between 0 and 30. An empty input resolves to 0. Inputs outside 0–30 or non-numeric entries are rejected and re-prompted without crashing or defaulting to arbitrary figures.
  *Evidence:* Verified with unit test assertions on prompt_discount_interactive testing default 0, valid range, and invalid input re-prompting.

- `AC-SQA-007`: **Quote Persistence Approval Gate & Transactional Atomicity**
  **State:** `done`
  **Requirements:** `SQA-REQ-005`, `SQA-REQ-006`, `SQA-REQ-007`
  **Tasks:** `SQA-TASK-0005`, `SQA-TASK-0006`, `SQA-TASK-0010`
  *Criterion:* Invoking `create_quote` triggers Proteo's Phase 5 `ApprovalHandler`. When the user rejects the prompt, zero rows are inserted into `quotes` or `quote_lines`. When the user approves, quote header and all line items are committed in a single atomic transaction with an ISO-8601 UTC timestamp and creator staff ID.
  *Evidence:* Verified with automated test asserting that user denial returns `denied=True` and commits zero rows to `quotes` and `quote_lines`, whereas user approval returns `success=True` and commits an atomic quote with UTC timestamp and creator staff user ID.

- `AC-SQA-008`: **Monetary Integrity and Price Re-Reading**
  **State:** `done`
  **Requirements:** `SQA-REQ-002`, `SQA-REQ-006`
  **Tasks:** `SQA-TASK-0002`
  *Criterion:* Product prices are re-read from SQLite before calculating quote totals, ignoring any hallucinated prices from the LLM. Calculations use `Decimal` with `ROUND_HALF_UP` rounding, and amounts persist as integer cents. Historical price changes to products do not affect previously stored quote lines.
  *Evidence:* Verified with headless unit assertions on discount rounding (ROUND_HALF_UP) and persist_quote_transactional price re-reading.

- `AC-SQA-009`: **Controlled Agent Catalog Routing & Sandboxing**
  **State:** `done`
  **Requirements:** `SQA-REQ-008`, `SQA-REQ-009`
  **Tasks:** `SQA-TASK-0007`, `SQA-TASK-0008`
  *Criterion:* Conversational requests regarding product features, availability, and pricing route to `controlled_agent`. The agent is bounded by host-managed tools and possesses no access to the OS shell, local files outside the database query functions, raw SQL execution, or network requests.
  *Evidence:* Verified with StateGraph test confirming open-ended product inquiries route to controlled_agent and return active product details.

- `AC-SQA-010`: **Secret-Safe Metadata-Only Observability**
  **State:** `done`
  **Requirements:** `SQA-REQ-008`, `SQA-REQ-009`, `SQA-REQ-010`
  **Tasks:** `SQA-TASK-0007`, `SQA-TASK-0008`
  *Criterion:* Telemetry events emitted by the runtime and tools contain only correlation IDs and execution metadata (`PayloadMode.METADATA_ONLY`). Authentication events do not expose credentials.
  *Evidence:* Verified with ConsoleMetadataObserver inspecting event envelopes and ensuring zero credential fields are exposed.

- `AC-SQA-011`: **Strict Type Safety, Style and Documentation Conformance**
  **State:** `done`
  **Requirements:** `SQA-REQ-003`, `SQA-REQ-011`, `SQA-REQ-012`, `SQA-REQ-013`
  **Tasks:** `SQA-TASK-0003`, `SQA-TASK-0009`, `SQA-TASK-0010`
  *Criterion:* `uv run mypy examples/smart_quote_agent --strict`, `uv run ruff check examples/smart_quote_agent`, and `uv run ruff format --check examples/smart_quote_agent` pass with zero errors. All functions and methods contain Google-style docstrings in English. `examples/smart_quote_agent/README.md` provides full setup and verification instructions.
  *Evidence:* Verified clean passes for `uv run mypy examples/smart_quote_agent --strict` (8 source files, 0 errors), `uv run ruff check examples/smart_quote_agent` (0 errors), and `uv run ruff format --check examples/smart_quote_agent` (9 files formatted). Complete documentation published in `examples/smart_quote_agent/README.md`.

- `AC-SQA-012`: **Reported Conversation Completes Without Losing the Quote**
  **State:** `done`
  **Requirements:** `SQA-REQ-014`, `SQA-REQ-015`, `SQA-REQ-017`
  **Tasks:** `SQA-TASK-0011`, `SQA-TASK-0012`, `SQA-TASK-0013`
  *Criterion:* A single pending quote survives customer and product-catalog interruptions, accepts an explicit desk → dock correction and a uniquely targeted quantity, then resolves Globex and persists exactly one quote with one USB-C Dock and two Wireless Mouse lines.
  *Evidence:* `test_hardening_reported_transcript_completes_across_interruptions` passes in provider-free graph tests and asserts the stored customer, quantities, and products.

- `AC-SQA-013`: **Line-Safe Edits and No-Op Clarification**
  **State:** `done`
  **Requirements:** `SQA-REQ-014`, `SQA-REQ-015`
  **Tasks:** `SQA-TASK-0011`, `SQA-TASK-0012`, `SQA-TASK-0013`
  *Criterion:* Replace/add/set-quantity/remove operations preserve unrelated lines; replacement preserves quantity; a deictic reference or isolated quantity with multiple targets leaves quote data and revision unchanged and requests clarification.
  *Evidence:* Reducer operation test and `test_hardening_ambiguous_reference_and_quantity_are_noops` pass.

- `AC-SQA-014`: **Workflow-Bound Draft and Complete Terminal Cleanup**
  **State:** `done`
  **Requirements:** `SQA-REQ-014`
  **Tasks:** `SQA-TASK-0012`
  *Criterion:* A draft from another workflow/revision cannot reach discount review or persistence; failed resolution preserves the current workflow, while cancel/logout/denial/success/terminal write failure clear workflow, draft, patch, and request references.
  *Evidence:* `test_hardening_stale_draft_guards_discount_and_approval_nodes`, stale-resolution, cancel cleanup, approved transcript, and terminal persistence-failure regressions pass. The stale node checks occur before discount prompting and before creating a write executor.

- `AC-SQA-015`: **Authorized Customer Directory and Safe Canonical Search**
  **State:** `done`
  **Requirements:** `SQA-REQ-005`, `SQA-REQ-016`
  **Tasks:** `SQA-TASK-0014`
  *Criterion:* Only staff receives `list_customers` and customer resolution tools; listing is bounded and returns `id`/`code`/`name`; accent/case/plural aliases resolve uniquely, multiple matches stay explicit, and `desk` never resolves as `dock`.
  *Evidence:* Staff/client registry assertions, bounded `list_customers` output, accent-insensitive customer lookup, mouse/mice/mouses aliases, ambiguity, and the negative `desk` lookup pass.

- `AC-SQA-016`: **Stable Language and Runtime-Owned Read-Only Memory**
  **State:** `done`
  **Requirements:** `SQA-REQ-017`
  **Tasks:** `SQA-TASK-0013`
  *Criterion:* A short answer inherits the active conversation language; host-side interruption reminders use that language; the controlled task receives only the current user turn and does not receive replayed host workflow history or write authority.
  *Evidence:* Spanish persistence on terse follow-ups, localized login prompts and CLI errors, pending-workflow reminders, and user-only RuntimeTask input tests pass.

- `AC-SQA-017`: **Task/Workflow-Correlated Metadata-Only Observability**
  **State:** `done`
  **Requirements:** `SQA-REQ-018`
  **Tasks:** `SQA-TASK-0015`
  *Criterion:* Existing telemetry databases migrate idempotently to nullable `task_id`; task and workflow inspector views reconstruct host transitions and runtime turns without user content; provider cleanup diagnostic codes are visible; displayed OTel metrics are labeled database-cumulative.
  *Evidence:* Additive/idempotent migration, task/workflow inspector, cleanup-diagnostic display, and metadata-whitelist tests pass in the full example suite.

- `AC-SQA-018`: **Complete, Authoritative Offline Quote Preview**
  **State:** `done`
  **Requirements:** `SQA-REQ-006`, `SQA-REQ-016`
  **Tasks:** `SQA-TASK-0013`, `SQA-TASK-0014`, `SQA-TASK-0016`
  *Criterion:* Offline previews resolve explicit active product names, safe aliases, or exact SKUs through the host catalog and calculate prices with `calculate_quote`. If any line is unknown, ambiguous, or has an unassociated/invalid quantity, the whole preview requests clarification and no partial subtotal or persisted quote is produced.
  *Evidence:* Offline preview tests cover multi-line authoritative totals, ambiguous `notebooks`, exact `DOCK-USBC`, unknown `desk` mixed with a valid dock, negative ASCII/Unicode signs both spaced and attached to a product, fractional quantities, trailing quantities with courtesy text, orphan quantities, and zero persistence.

- `AC-SQA-019`: **Correlated, Redacted Live-Turn Diagnostics**
  **State:** `done`
  **Requirements:** `SQA-REQ-018`, `SQA-REQ-019`
  **Tasks:** `SQA-TASK-0017`
  *Criterion:* Every graph turn has an interaction ID before entry; runtime metadata, host transitions, and host errors share it. Host errors expose only stage, exception module/type, bounded stable code, cause types, and sanitized frames; no exception message, locals, credentials, prompts, or responses are stored. Logger failure leaves the localized generic CLI response and session alive. The additive schema migration is idempotent, `--interaction` labels an incomplete invocation with a correlated host error as failed, and a terminal successful invocation remains completed. The live quote path either reaches and verifies the exact review before approving one write or leaves the quote count unchanged and reports the inspected failure.
  *Evidence:* `test_host_error_is_correlated_and_excludes_exception_messages`, REPL logger-failure test, interaction inspector status test, migration test, and router metadata test pass. Live attempt 2026-09-19: after `staff` login, two submissions of the original phrase both failed at `intent_router` with `RuntimeUnavailableError` / `runtime_unavailable`; both `--interaction` reports contain an incomplete runtime invocation and sanitized frames. The demo quote count remained 7 before and after; no persistence prompt was reached.
