# Task Plan — Smart Quote Agent Example

## Conventions

Task states are `pending`, `in_progress`, `done`, or `blocked`.
All tasks start in `pending`. A task may only transition to `done` when concrete test or verification evidence is recorded in `05_validation_plan.md`.

Strict Boundary Rule:
No files outside `examples/smart_quote_agent/` may be created, modified, or touched during the execution of any task.

---

## Ordered Workstreams

### SQA-TASK-0001 — Directory Layout and Data Placeholder

**State:** `pending`
**Depends on:** none
**Requirements:** `SQA-REQ-001`
**Acceptance:** `AC-SQA-001`

- Create directory `examples/smart_quote_agent/data/` if not present.
- Place `examples/smart_quote_agent/data/.gitkeep` to maintain directory tracking without checking in transient SQLite files.
- Verify working tree boundaries: no modifications outside `examples/smart_quote_agent/`.

---

### SQA-TASK-0002 — SQLite Schema, Query Helpers and Initialization Script

**State:** `pending`
**Depends on:** `SQA-TASK-0001`
**Requirements:** `SQA-REQ-002`, `SQA-REQ-006`
**Acceptance:** `AC-SQA-002`, `AC-SQA-008`

- Implement `examples/smart_quote_agent/database.py`:
  - `get_db_path()`, `get_connection()` with `PRAGMA foreign_keys = ON;`.
  - DDL statements for `customers`, `users`, `products`, `quotes`, `quote_lines`.
  - Cents and Decimal conversion helpers (`cents_to_decimal`, `calculate_discount_amount`, `format_currency`).
  - Query functions: `find_customer_by_query`, `list_active_products`, `find_product_by_query`, `get_quote_by_id`, `list_recent_quotes`.
  - Transactional quote persistence `persist_quote_transactional` using a single transaction (`BEGIN ... COMMIT`) with rollback on error.
- Implement `examples/smart_quote_agent/init_demo.py`:
  - CLI argument parsing for `--reset`.
  - Database provisioning and seed execution (4 customers, 5 users with password `1234`, 6 active products).
  - Status printout displaying credentials and database location.

---

### SQA-TASK-0003 — Pydantic Structured Schemas and Graph State Types

**State:** `pending`
**Depends on:** `SQA-TASK-0001`
**Requirements:** `SQA-REQ-003`, `SQA-REQ-012`
**Acceptance:** `AC-SQA-003`, `AC-SQA-011`

- Implement `examples/smart_quote_agent/models.py`:
  - `IntentDecision` structured output schema for intent routing (`login`, `logout`, `quote_create`, `agent_request`).
  - `RequestedItem` and `QuoteRequest` structured output schemas for quote extraction with strict field validations (`quantity > 0`, non-empty customer and items).
  - `AuthenticatedUser` dataclass with slots and immutability.
  - `QuoteLineDraft`, `QuoteDraft`, and `DemoState` typed dictionaries for LangGraph state management.

---

### SQA-TASK-0004 — Host Authentication, Masked Input and Permission Policy Mapping

**State:** `pending`
**Depends on:** `SQA-TASK-0002`, `SQA-TASK-0003`
**Requirements:** `SQA-REQ-004`, `SQA-REQ-005`
**Acceptance:** `AC-SQA-003`, `AC-SQA-004`, `AC-SQA-005`

- Implement `examples/smart_quote_agent/auth.py`:
  - `authenticate_user_interactive(conn)` using `getpass.getpass()` for password input.
  - Verification against `users` table; immediate password variable cleanup.
  - Returns `AuthenticatedUser` on success, `None` on invalid credentials.
  - `get_permission_policy_for_user(user)` mapping staff role to full permissions and client/anonymous to public read/calculate permissions.

---

### SQA-TASK-0005 — Host-Managed Tools and Tool Registry Factory

**State:** `pending`
**Depends on:** `SQA-TASK-0002`, `SQA-TASK-0004`
**Requirements:** `SQA-REQ-005`, `SQA-REQ-006`
**Acceptance:** `AC-SQA-004`, `AC-SQA-005`, `AC-SQA-007`

- Implement `examples/smart_quote_agent/tools.py`:
  - Decorate all 7 tools with `@runtime_tool`:
    - `list_products`: `catalog.read`, `SideEffect.READ`.
    - `find_product`: `catalog.read`, `SideEffect.READ`.
    - `calculate_quote`: `quote.calculate`, `SideEffect.NONE`.
    - `find_customer`: `customer.read`, `SideEffect.READ`.
    - `create_quote`: `quote.create`, `SideEffect.WRITE`, approval required.
    - `list_quotes`: `quote.read`, `SideEffect.READ`.
    - `get_quote`: `quote.read`, `SideEffect.READ`.
  - `create_tool_registry(conn)` returning populated `ToolRegistry`.
  - `create_tool_executor(registry, user, approval_handler)` returning bound `ToolExecutor`.

---

### SQA-TASK-0006 — Human-In-The-Loop Discount Prompt and Approval Handler

**State:** `pending`
**Depends on:** `SQA-TASK-0002`, `SQA-TASK-0003`
**Requirements:** `SQA-REQ-007`
**Acceptance:** `AC-SQA-006`, `AC-SQA-007`

- Implement `examples/smart_quote_agent/hitl.py`:
  - `prompt_discount_interactive(subtotal_cents)` prompting for whole percentage `0..30` (default 0), with validation and re-prompting.
  - `ConsoleApprovalHandler` implementing `ApprovalHandler` protocol: renders quote details, asks `Approve? [y/N]`, and returns `ApprovalDecision.ALLOW` or `ApprovalDecision.DENY`.

---

### SQA-TASK-0007 — LangGraph Workflow Graph and Hybrid Execution Assembly

**State:** `pending`
**Depends on:** `SQA-TASK-0003`, `SQA-TASK-0004`, `SQA-TASK-0005`, `SQA-TASK-0006`
**Requirements:** `SQA-REQ-008`, `SQA-REQ-010`
**Acceptance:** `AC-SQA-004`, `AC-SQA-005`, `AC-SQA-009`, `AC-SQA-010`

- Implement `examples/smart_quote_agent/graph.py`:
  - Build `StateGraph(DemoState)`.
  - Add nodes: `intent_router`, `login_hitl`, `clear_auth`, `quote_planner`, `auth_guard`, `resolve_quote_data`, `discount_hitl`, `create_quote_tool`, `controlled_agent`, `final_output`.
  - Connect conditional routing from `intent_router` to `login_hitl`, `clear_auth`, `auth_guard`, or `controlled_agent`.
  - Wire `auth_guard` rejection for non-staff directly to `final_output`.
  - Wire authorized quote path: `quote_planner` -> `resolve_quote_data` -> `discount_hitl` -> `create_quote_tool` -> `final_output`.
  - Compile the graph.

---

### SQA-TASK-0008 — Interactive CLI Entrypoint and REPL Loop

**State:** `pending`
**Depends on:** `SQA-TASK-0007`
**Requirements:** `SQA-REQ-009`, `SQA-REQ-010`
**Acceptance:** `AC-SQA-003`, `AC-SQA-009`, `AC-SQA-010`

- Implement `examples/smart_quote_agent/app.py`:
  - CLI banner, database auto-detection, and help text.
  - Main async REPL loop with mode indicators: `> ` vs `[role] > `.
  - Deterministic handling of `exit` and `quit`.
  - State preservation (`authenticated_user`) between conversational turns.
  - Metadata-only observer binding configuration.

---

### SQA-TASK-0009 — Comprehensive Example Documentation and User Guide

**State:** `pending`
**Depends on:** `SQA-TASK-0008`
**Requirements:** `SQA-REQ-011`
**Acceptance:** `AC-SQA-011`

- Implement `examples/smart_quote_agent/README.md`:
  - Architecture narrative and core principles.
  - Setup instructions and default credentials table.
  - 4 complete example interaction transcripts.
  - Security boundaries and limitations disclaimer.

---

### SQA-TASK-0010 — Static Analysis, Linting and Verification Execution

**State:** `pending`
**Depends on:** `SQA-TASK-0009`
**Requirements:** `SQA-REQ-001`, `SQA-REQ-012`, `SQA-REQ-013`
**Acceptance:** `AC-SQA-001`, `AC-SQA-011`

- Run `uv run mypy examples/smart_quote_agent --strict`.
- Run `uv run ruff check examples/smart_quote_agent`.
- Run `uv run ruff format --check examples/smart_quote_agent`.
- Verify `git status` confirms zero modifications outside `examples/smart_quote_agent/`.
- Record execution logs and evidence in `05_validation_plan.md`.
