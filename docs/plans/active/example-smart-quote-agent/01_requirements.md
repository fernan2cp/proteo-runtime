# Requirements — Smart Quote Agent Example

## Functional Requirements

### SQA-REQ-001 — Bounded Change Isolation

1. Example product code, tests, scripts, local data, and example docs must be contained within:
   ```text
   examples/smart_quote_agent/
   ```
2. The current implementation request explicitly permits updates only to the existing active SDD package at `docs/plans/active/example-smart-quote-agent/` in addition to the example directory.
3. No implementation change may touch `src/*`, repository-level tests, configuration files, public runtime contracts, or the business database schema.
4. Pre-existing worktree changes must be preserved and must not be represented as changes made by this implementation.

### SQA-REQ-002 — SQLite Domain Schema and Deterministic Initialization

1. The application must operate against a local SQLite database at:
   ```text
   examples/smart_quote_agent/data/demo.sqlite3
   ```
2. SQLite foreign keys must be explicitly enabled on every connection via:
   ```sql
   PRAGMA foreign_keys = ON;
   ```
3. The schema must contain five relational tables:
   - `customers`: `id` (INTEGER PRIMARY KEY), `code` (TEXT NOT NULL UNIQUE), `name` (TEXT NOT NULL).
   - `users`: `id` (INTEGER PRIMARY KEY), `username` (TEXT NOT NULL UNIQUE), `password` (TEXT NOT NULL), `role` (TEXT CHECK in 'staff', 'client'), `display_name` (TEXT NOT NULL), `customer_id` (INTEGER NULL, FK to customers). Staff users must have `customer_id IS NULL`; client users must have a valid `customer_id`.
   - `products`: `id` (INTEGER PRIMARY KEY), `sku` (TEXT NOT NULL UNIQUE), `name` (TEXT NOT NULL), `description` (TEXT NOT NULL), `unit_price_cents` (INTEGER NOT NULL CHECK >= 0), `active` (INTEGER CHECK in 0, 1 DEFAULT 1).
   - `quotes`: `id` (INTEGER PRIMARY KEY AUTOINCREMENT), `customer_id` (INTEGER NOT NULL, FK to customers), `created_by_user_id` (INTEGER NOT NULL, FK to users), `created_at` (TEXT NOT NULL ISO-8601 UTC), `currency` (TEXT NOT NULL DEFAULT 'USD'), `subtotal_cents` (INTEGER NOT NULL CHECK >= 0), `discount_percent` (INTEGER NOT NULL CHECK BETWEEN 0 AND 30 DEFAULT 0), `discount_amount_cents` (INTEGER NOT NULL CHECK >= 0 DEFAULT 0), `total_cents` (INTEGER NOT NULL CHECK >= 0).
   - `quote_lines`: `id` (INTEGER PRIMARY KEY AUTOINCREMENT), `quote_id` (INTEGER NOT NULL, FK to quotes ON DELETE CASCADE), `product_id` (INTEGER NOT NULL, FK to products), `quantity` (INTEGER NOT NULL CHECK > 0), `unit_price_cents` (INTEGER NOT NULL CHECK >= 0), `subtotal_cents` (INTEGER NOT NULL CHECK >= 0).
4. An initialization script (`examples/smart_quote_agent/init_demo.py`) must provide a CLI command:
   ```bash
   python examples/smart_quote_agent/init_demo.py --reset
   ```
   When `--reset` is specified, it drops existing tables or deletes the database file and creates a fresh database seeded with:
   - 4 customers: Acme Corp. (`client1`), Globex LLC (`client2`), Initech (`client3`), Northwind Traders (`client4`).
   - 5 users with password `1234`: `staff` (role `staff`), `client1` (role `client`), `client2` (role `client`), `client3` (role `client`), `client4` (role `client`).
   - 6 active products: `NB-PRO` ($1,200.00), `NB-AIR` ($900.00), `MS-WL` ($40.00), `KB-MECH` ($85.00), `MON-27` ($320.00), `DOCK-USBC` ($150.00).

### SQA-REQ-003 — Domain Models and Structured Schemas

1. Structured models defined using Pydantic must handle router classification and quote extraction:
   - `IntentDecision`: classifies `login`, `logout`, `help`, `acknowledgement`, `catalog_query`, `quote_preview`, `quote_history`, `customer_query`, `quote_create`, or `out_of_scope`; turn language may be unknown.
   - `RequestedItem`: allows product and quantity to remain absent while information is being collected; any provided quantity must be positive.
   - `QuoteRequest`: allows customer/items to remain absent during collection rather than forcing a partial request into a complete schema.
   - `TurnDecision` may include an optional validated `QuotePatch` for the current pending workflow.
2. Graph state definitions must include:
   - `AuthenticatedUser`: immutable representation containing `user_id: int`, `username: str`, `display_name: str`, `role: Literal["staff", "client"]`, `customer_id: int | None`.
   - `DemoState`: typed dictionary tracking current `input: str`, `output: str`, `authenticated_user: AuthenticatedUser | None`, `intent: str`, `quote_request: QuoteRequest | None`, `quote_draft: Any | None`, and `created_quote_id: int | None`.
   - `DemoState` also carries stable session language, current `QuoteWorkflowState`, and interaction correlation; `quote_draft` remains revision-bound and ephemeral.

### SQA-REQ-004 — Host Authentication and Masked Credential Handling

1. Login must be routable from natural-language prompts (e.g. "login", "iniciar sesión", "quiero entrar").
2. Password input must use `getpass.getpass()` to prevent echoing the password to the terminal.
3. Passwords must be verified directly against SQLite user records.
4. On successful authentication, only the sanitized `AuthenticatedUser` record may be written to graph state.
5. The raw password must be discarded immediately after verification. It must never enter LangGraph state, runtime inputs, tool arguments, telemetry events, diagnostics, or logs.
6. Logout must be routable from natural-language prompts (e.g. "logout", "cerrar sesión") and must clear the authenticated user from state, reverting the session to anonymous mode without altering any database record.

### SQA-REQ-005 — Host-Managed Tools Registry and Dual-Role Policies

1. The application must define eight host-managed tools using the `@runtime_tool` decorator:
   - `list_products`: permission `catalog.read`, side effect `SideEffect.READ`, approval `never`. Lists active catalog products.
   - `find_product`: permission `catalog.read`, side effect `SideEffect.READ`, approval `never`. Searches products by name or SKU.
   - `calculate_quote`: permission `quote.calculate`, side effect `SideEffect.NONE`, approval `never`. Computes authoritative subtotal for resolved product IDs and quantities.
   - `find_customer`: permission `customer.read`, side effect `SideEffect.READ`, approval `never`. Staff-only customer lookup.
   - `list_customers`: permission `customer.read`, side effect `SideEffect.READ`, approval `never`. Staff-only bounded customer directory with `id`, `code`, and `name` fields.
   - `create_quote`: permission `quote.create`, side effect `SideEffect.WRITE`, approval `for_side_effects`. Staff-only quote persistence.
   - `list_quotes`: permission `quote.read`, side effect `SideEffect.READ`, approval `never`. Staff-only listing of recent quotes (default limit 10).
   - `get_quote`: permission `quote.read`, side effect `SideEffect.READ`, approval `never`. Staff-only detail lookup of a specific quote and its line items.
2. The host must construct two distinct `ToolPermissionPolicy` instances:
   - **Public/Client Policy**: frozenset `{"catalog.read", "quote.calculate"}`.
   - **Staff Policy**: frozenset `{"catalog.read", "quote.calculate", "customer.read", "quote.create", "quote.read"}`.
3. Registration of a tool does not grant execution permission. The host dynamically binds the permission policy matching the current interaction's authenticated role.

### SQA-REQ-006 — Deterministic Quote Calculation, Invariants and Atomicity

1. The model must never provide authoritative monetary figures, subtotals, discount amounts, totals, creator IDs, or timestamps.
2. Before quote creation or calculation:
   - Current product unit prices must be re-read from SQLite.
   - Line subtotal must be computed as `quantity * unit_price_cents`.
   - Quote subtotal must be computed as `sum(line subtotals)`.
3. Discount amount must be derived host-side:
   - `discount_amount_cents = round(subtotal_cents * discount_percent / 100)` using `Decimal` and `ROUND_HALF_UP`.
   - `total_cents = subtotal_cents - discount_amount_cents`.
4. Quote persistence must be transactional:
   - The insertion of the `quotes` record and all associated `quote_lines` records must occur within a single SQLite transaction.
   - In case of failure or cancellation, the transaction must roll back cleanly, ensuring no orphaned or partial quote records exist.
   - Quote line records must store a historical snapshot of `unit_price_cents`.
5. In provider-free offline mode, explicit `quote_preview` requests must use the same host-managed `calculate_quote` tool. Every requested line must resolve to an active catalog product and positive quantity; unknown or ambiguous lines reject the entire preview rather than returning a partial subtotal. A preview must never persist a quote.

### SQA-REQ-007 — Human-in-the-Loop (HITL) Workflows

1. **Discount HITL**:
   - For quote creation, the host prompts the user interactively whether to apply a discount.
   - If accepted, the user enters an integer percentage in the range `0..30`.
   - Empty input defaults to `0%`.
   - Values outside `0..30` or non-integer inputs are rejected and re-prompted.
2. **Persistence Approval**:
   - Quote persistence (`create_quote`) requires explicit human approval via Proteo Phase 5 `ApprovalHandler`.
   - A denial by the user immediately cancels the creation, outputs a cancellation message, and persists zero database records.
   - An approval proceeds with the atomic database commit.

### SQA-REQ-008 — LangGraph Orchestration & Hybrid Flow

1. The LangGraph `StateGraph` must orchestrate the application workflow according to the design:
   - `intent_router` classifies supported actions and, when a workflow is pending, prioritizes explicit read-only interruptions and validated quote edits.
   - `login` transitions to `login_hitl`.
   - `logout` transitions to `clear_auth`.
   - `quote_create` transitions to `auth_guard` (denying non-staff immediately), then `quote_planner`, `resolve_quote_data`, `discount_hitl`, `create_quote_tool` (with approval), and `final_output`.
   - catalog, customer, help, and quote-history inquiries transition to `controlled_agent` or a deterministic host reply according to role policy.
2. The controlled agent must only execute tools permitted by the active role policy and must never possess arbitrary shell, network, filesystem, or raw database access.

### SQA-REQ-009 — Interactive CLI Application

1. `examples/smart_quote_agent/app.py` must provide an interactive terminal REPL loop.
2. Startup banner must display current mode (`Mode: anonymous`), available commands (`login`, `logout`, `exit`), and prompt.
3. The prompt must reflect authentication status:
   - Anonymous: `> `
   - Authenticated: `[staff] > ` or `[client2] > `
4. Typing `exit` or `quit` terminates the CLI cleanly without invoking the model.

### SQA-REQ-010 — Metadata-Only Console Observability

1. Default observability must be configured via `ObservabilityConfig` using `PayloadMode.METADATA_ONLY`.
2. A lightweight console observer prints tool and invocation lifecycle events:
   - `invocation_started`, `invocation_completed`, `tool_requested`, `tool_started`, `tool_completed`, `tool_denied`, `tool_approval_requested`, `tool_approval_resolved`.
3. Event metadata must never log passwords, raw credential inputs, or secrets.

### SQA-REQ-011 — Example Documentation & User Guide

1. `examples/smart_quote_agent/README.md` must provide complete documentation:
   - Architecture overview and design philosophy ("model suggests, host decides").
   - Setup instructions (`python examples/smart_quote_agent/init_demo.py --reset`).
   - Default user credentials table and security disclaimer.
   - Step-by-step example interaction transcripts (anonymous preview, client denied quote creation, staff quote creation with discount and approval, quote query).
   - Proven security boundaries vs. non-proven production guarantees.

## Non-Functional Requirements

### SQA-REQ-012 — Strict Type Safety and Google-Style Docstrings

1. All Python source files must have 100% type annotations and pass `uv run mypy examples/smart_quote_agent --strict`.
2. Every public and internal class, function, and method must have an English docstring formatted according to the Google Python Style Guide.
3. PEP 604 union syntax (`A | B`) must be used for type hints and `isinstance` checks.

### SQA-REQ-013 — Linting and Formatting Conformance

1. All code must pass `uv run ruff check examples/smart_quote_agent` without errors or warnings.
2. All code must pass `uv run ruff format --check examples/smart_quote_agent`.

### SQA-REQ-014 — Transactional Quote Conversation State

1. LangGraph and host code own a `QuoteWorkflowState` containing a stable `workflow_id`, monotonic `revision`, phase (`collecting`, `needs_resolution`, or `ready_for_review`), customer request/resolution, stable line IDs, quantities, product resolution status, candidates, and the current focus.
2. A `QuoteDraft` is ephemeral and valid only for the exact active `workflow_id` and `revision`; validate this before discount prompts/review and persistence.
3. Customer/product/quantity resolution failures preserve the workflow and all unrelated lines. Resolve all lines and return per-line errors/candidates rather than stopping at the first error.
4. Cancel, logout, login identity switch, approval denial, success, and terminal persistence failure clear the workflow, draft, pending request, and patch references together.

### SQA-REQ-015 — Contextual Routing and Validated Quote Patches

1. Deterministic cancel/logout and explicit read-only intents take priority while a workflow is pending. Product, customer, help, and history queries do not consume or mutate that workflow.
2. `TurnDecision` may contain an optional `QuotePatch`; patch operations are a discriminated union of setting a customer, adding/replacing/removing a line, or setting quantity. A pure host reducer validates targets and applies each operation without dropping unrelated lines.
3. A short answer may complete a field only when exactly one compatible field is pending. An ambiguous answer must leave quote data and revision unchanged and ask a localized clarification.
4. Replacing a product preserves that line's quantity and every other line. Deictic references such as “ese/that” require exactly one stored candidate/reference.

### SQA-REQ-016 — Canonical Entity Search and Customer Directory

1. Add `list_customers` as a bounded staff-only tool authorized by `customer.read`; maintain `find_customer` for targeted search.
2. Normalize case, accents, and safe singular/plural aliases. Product resolution order is exact ID/SKU, exact normalized name, unique safe alias, then unique partial match. Multiple matches produce candidate lists.
3. Support safe `mouse`, `mice`, and `mouses` aliases. Never map `desk` to `dock` unless the user explicitly corrects the product.

### SQA-REQ-017 — Language and Controlled-Agent Continuity

1. Preserve the interaction language in host state; update it only when current-turn language is clear, and retain it for terse follow-ups.
2. A controlled `RuntimeTask` remembers only read-only turns actually sent to that task under `ContextPolicy.RUNTIME`; it is not the owner of quote workflow state and receives no host-side history replay.
3. Deterministic host replies use localized Spanish/English templates. Read-only interruptions briefly report that a quote remains pending and identify its next missing detail.

### SQA-REQ-018 — Task/Workflow Observability Correlation

1. Add `task_id` to the neutral local `runtime_events` table through an additive, idempotent SQLite migration. Do not alter the business database.
2. Record metadata-only host transitions correlating `interaction_id`, `task_id`, `workflow_id`, revision, intent, route, phases, and stable result code; never persist prompt, response, or sensitive arguments.
3. The inspector supports task and workflow timelines and displays provider cleanup diagnostics such as `task.cleanup.provider_delete_failed`. It distinguishes cumulative database metrics from invocation-scoped details.
4. Surfacing cleanup diagnostics is in scope; changing provider cleanup behavior is not.

### SQA-REQ-019 — Correlated, Redacted Turn Error Diagnostics

1. The CLI assigns a unique `interaction_id` before each graph invocation. Structured model calls and controlled `RuntimeTask` turns receive only safe correlation metadata (`interaction_id`, stage, and available task/workflow IDs) via `InvocationConfig.metadata`; no prompt or output is added to diagnostic records.
2. A host-side failure is recorded as `host.turn_error` with interaction ID, stage, exception module/type, an optional bounded stable error code, causal exception type names, and traceback frames containing only repository-relative or external-basename file, function, and line.
3. Error messages, exception representations, local variables, prompts, responses, tool arguments, credentials, and absolute external filesystem paths MUST NOT be persisted. Host logging is best effort and MUST NOT mask an original failure or alter the generic localized REPL response.
4. The local `runtime_events` table adds nullable `interaction_id` and an index through an additive, idempotent migration. The business database and public Proteo Runtime APIs remain unchanged.
5. `inspect_observability.py --interaction <id>` displays runtime and host events together. If a correlated `host.turn_error` exists, that interaction is shown as failed even when its runtime invocation lacks a terminal event; existing event rows are never rewritten. Completed runtime invocations remain reported as completed.
6. A live test uses the original quote request and approved staff identity. It proceeds to persistence only after review confirms Globex, one USB-C Dock, two Wireless Mouse, zero discount, and USD 230; if the provider fails first, the interaction is inspected and the demo quote count must remain unchanged.
