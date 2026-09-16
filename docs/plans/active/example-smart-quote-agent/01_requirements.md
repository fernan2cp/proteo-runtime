# Requirements — Smart Quote Agent Example

## Functional Requirements

### SQA-REQ-001 — Directory Isolation and Zero Repository Pollution

1. The example application must be 100% contained within the directory:
   ```text
   examples/smart_quote_agent/
   ```
2. No file outside this directory (including `src/*`, `tests/*`, `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`, or root documentation) may be created, modified, or deleted during the implementation or execution of this example.
3. The repository working tree outside `examples/smart_quote_agent/` must remain completely unmodified.

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
   - `IntentDecision`: specifies `intent` restricted to `"login"`, `"logout"`, `"quote_create"`, `"agent_request"`.
   - `RequestedItem`: contains `product: str` and `quantity: int` (with validation `quantity > 0`).
   - `QuoteRequest`: contains `customer: str` and `items: list[RequestedItem]` (with validation `customer` non-empty, `len(items) >= 1`).
2. Graph state definitions must include:
   - `AuthenticatedUser`: immutable representation containing `user_id: int`, `username: str`, `display_name: str`, `role: Literal["staff", "client"]`, `customer_id: int | None`.
   - `DemoState`: typed dictionary tracking current `input: str`, `output: str`, `authenticated_user: AuthenticatedUser | None`, `intent: str`, `quote_request: QuoteRequest | None`, `quote_draft: Any | None`, and `created_quote_id: int | None`.

### SQA-REQ-004 — Host Authentication and Masked Credential Handling

1. Login must be routable from natural-language prompts (e.g. "login", "iniciar sesión", "quiero entrar").
2. Password input must use `getpass.getpass()` to prevent echoing the password to the terminal.
3. Passwords must be verified directly against SQLite user records.
4. On successful authentication, only the sanitized `AuthenticatedUser` record may be written to graph state.
5. The raw password must be discarded immediately after verification. It must never enter LangGraph state, runtime inputs, tool arguments, telemetry events, diagnostics, or logs.
6. Logout must be routable from natural-language prompts (e.g. "logout", "cerrar sesión") and must clear the authenticated user from state, reverting the session to anonymous mode without altering any database record.

### SQA-REQ-005 — Host-Managed Tools Registry and Dual-Role Policies

1. The application must define seven host-managed tools using the `@runtime_tool` decorator:
   - `list_products`: permission `catalog.read`, side effect `SideEffect.READ`, approval `never`. Lists active catalog products.
   - `find_product`: permission `catalog.read`, side effect `SideEffect.READ`, approval `never`. Searches products by name or SKU.
   - `calculate_quote`: permission `quote.calculate`, side effect `SideEffect.NONE`, approval `never`. Computes authoritative subtotal for resolved product IDs and quantities.
   - `find_customer`: permission `customer.read`, side effect `SideEffect.READ`, approval `never`. Staff-only customer lookup.
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
   - `intent_router` classifies user input into `login`, `logout`, `quote_create`, or `agent_request`.
   - `login` transitions to `login_hitl`.
   - `logout` transitions to `clear_auth`.
   - `quote_create` transitions to `auth_guard` (denying non-staff immediately), then `quote_planner`, `resolve_quote_data`, `discount_hitl`, `create_quote_tool` (with approval), and `final_output`.
   - `agent_request` transitions to `controlled_agent` (using Proteo's `RuntimeModel.with_tools`).
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
