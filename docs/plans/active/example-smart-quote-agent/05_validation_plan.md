# Validation Plan — Smart Quote Agent Example

## Automated Verification Commands

### 1. Type Safety (Strict Mode)

```powershell
uv run mypy examples/smart_quote_agent --strict
```

### 2. Linting & Style Conformance

```powershell
uv run ruff check examples/smart_quote_agent
uv run ruff format --check examples/smart_quote_agent
```

### 3. Bounded Change Verification (Baseline-Aware)

```powershell
# Review implementation changes against the task-start worktree baseline.
# Authorized changes: examples/smart_quote_agent/* and this active SDD package only.
# Preserve and separately report pre-existing user changes; do not require a clean tree.
git status --short
```

---

## Headless Smoke Verification Script

To validate domain logic, SQLite constraints, price calculations, and transactional rollback without requiring interactive keyboard entry or LLM quota:

```powershell
uv run python -c "
import sqlite3
from pathlib import Path
from examples.smart_quote_agent.database import (
    init_database, seed_database, get_connection,
    persist_quote_transactional, calculate_discount_amount, format_currency
)

db_path = Path('examples/smart_quote_agent/data/test_smoke.sqlite3')
init_database(db_path, reset=True)
seed_database(db_path)
conn = get_connection(db_path)

# Verify seeded counts
cur = conn.cursor()
assert cur.execute('SELECT COUNT(*) FROM customers').fetchone()[0] == 4
assert cur.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 5
assert cur.execute('SELECT COUNT(*) FROM products').fetchone()[0] == 6

# Verify discount calculation
assert calculate_discount_amount(380000, 10) == 38000
assert calculate_discount_amount(100, 30) == 30

# Verify transactional persistence
qid = persist_quote_transactional(
    conn,
    customer_id=2,
    created_by_user_id=1,
    lines=[(1, 3, 120000), (3, 5, 4000)],
    discount_percent=10
)
assert qid == 1
quote_row = cur.execute('SELECT total_cents, discount_percent FROM quotes WHERE id = 1').fetchone()
assert quote_row[0] == 342000
assert quote_row[1] == 10
lines_count = cur.execute('SELECT COUNT(*) FROM quote_lines WHERE quote_id = 1').fetchone()[0]
assert lines_count == 2
conn.close()
db_path.unlink(missing_ok=True)
print('SMOKE TESTS PASSED')
"
```

---

## Test Matrices & Scenarios

| Scenario ID | Description | Covered Criteria | Expected Result |
|---|---|---|---|
| SCEN-001 | Repository boundary verification | `AC-SQA-001` | No files outside `examples/smart_quote_agent/` touched. |
| SCEN-002 | Database reset and seed | `AC-SQA-002` | SQLite initialized with 4 customers, 5 users, 6 products. |
| SCEN-003 | Masked login with valid staff credentials | `AC-SQA-003` | Password hidden; state receives sanitized staff identity. |
| SCEN-004 | Masked login with invalid password | `AC-SQA-003` | Login fails; state remains anonymous; password discarded. |
| SCEN-005 | Anonymous user catalog inquiry | `AC-SQA-004`, `AC-SQA-009` | Products and prices returned successfully. |
| SCEN-006 | Anonymous user quote creation attempt | `AC-SQA-004` | Denied by guard before quote workflow executes. |
| SCEN-007 | Client login and quote creation attempt | `AC-SQA-004` | Denied; client role does not authorize quote mutation. |
| SCEN-008 | Staff quote creation with discount HITL | `AC-SQA-005`, `AC-SQA-006` | Whole percentage 0..30 applied correctly. |
| SCEN-009 | Quote creation approval denied | `AC-SQA-007` | Cancelled; zero rows committed to SQLite. |
| SCEN-010 | Quote creation approved | `AC-SQA-007`, `AC-SQA-008` | Transaction committed; quote and lines saved atomically. |
| SCEN-011 | Staff list and inspect quotes | `AC-SQA-005` | Returns accurate quote history and line item details. |
| SCEN-012 | Metadata-only telemetry check | `AC-SQA-010` | Observability events contain no passwords or secrets. |
| SCEN-013 | Static analysis and style | `AC-SQA-011` | mypy strict and ruff checks pass cleanly. |
| SCEN-014 | Staff lists customers while quote is pending | `AC-SQA-012`, `AC-SQA-015` | Customer response is returned; workflow and lines remain unchanged; next missing detail is stated in the active language. |
| SCEN-015 | Catalog question interrupts a pending quote | `AC-SQA-012`, `AC-SQA-016` | Active catalog is returned; workflow remains unchanged and product candidates are stored for bounded references. |
| SCEN-016 | Explicit replacement, add/remove, and isolated quantity | `AC-SQA-013` | Reducer changes only exact target lines; replacement preserves quantity and unrelated lines. |
| SCEN-017 | Ambiguous “that/ese” or multiple missing quantities | `AC-SQA-013` | Clarification is requested and quote data/revision do not mutate. |
| SCEN-018 | Obsolete workflow/revision draft | `AC-SQA-014` | Stale draft is cleared before discount/review and cannot reach create_quote. |
| SCEN-019 | Terminal workflow outcomes | `AC-SQA-014` | Cancel/logout/deny/success/terminal failure clear all workflow references. |
| SCEN-020 | Customer/product normalization and authorization | `AC-SQA-015` | Only staff can list customers; aliases and accents resolve safely; desk is not dock. |
| SCEN-021 | Stable language and runtime memory boundary | `AC-SQA-016` | Brief follow-up preserves language; controlled task input contains only this user's current read-only turn. |
| SCEN-022 | Task/workflow observability and migration | `AC-SQA-017` | Legacy DB migrates idempotently; inspector groups task/workflow transitions, excludes content, and surfaces cleanup diagnostics. |
| SCEN-023 | Offline quote preview completeness and exact identifiers | `AC-SQA-018` | Exact active name/SKU requests use `calculate_quote`; unknown/ambiguous products and invalid, unassociated, or malformed quantities abort the entire preview; no quote is persisted. |

---

## Conversational Hardening Regression Commands

The provider-free suite reproduces the reported thread without network calls or resetting the business database:

```powershell
uv run pytest examples/smart_quote_agent/tests/test_agent.py -q
uv run pytest examples/smart_quote_agent/tests/test_observability_*.py examples/smart_quote_agent/tests/test_inspector_queries.py -q
```

For local telemetry migration and the full task/workflow view, use a temporary observability DB in tests. Never reset `examples/smart_quote_agent/data/demo.sqlite3` as part of acceptance verification.

---

## Interactive Demonstration Scenario (Live CLI)

Execute `python examples/smart_quote_agent/app.py` and run through the following standard script:

1. **Start anonymous**: Verify prompt displays `Mode: anonymous`.
2. **Product exploration**: Input `What notebooks do you have and what are their prices?`. Observe controlled agent tool execution.
3. **Calculation preview**: Input `What would 2 Notebook Pro cost?`. Observe host calculation preview ($2,400.00).
4. **Anonymous creation attempt**: Input `Create a quote for Globex for 2 Notebook Pro`. Verify immediate denial ("Access denied. Persisted quotes can only be created by staff.").
5. **Client login**: Input `login`. Enter `client2` and password `1234` (masked). Verify `Logged in as Client 2 (client)`.
6. **Client creation attempt**: Input `Create a quote for Globex for 2 Notebook Pro`. Verify denial persists.
7. **Logout**: Input `logout`. Verify session returns to anonymous mode.
8. **Staff login**: Input `login`. Enter `staff` and password `1234` (masked). Verify `Logged in as Demo Staff (staff)`.
9. **Staff quote creation**: Input `Create a quote for Globex for 3 Notebook Pro and 5 Wireless Mouse`.
10. **Discount HITL**: On `Apply discount? [y/N]`, enter `y`. On `Discount percentage [0-30, default 0]:`, enter `10`. Verify Subtotal: $3,800.00, Discount 10%: $380.00, Total: $3,420.00.
11. **Approval denial**: On `Approve? [y/N]:`, enter `n`. Verify "Quote creation cancelled." and no database rows persisted.
12. **Approval confirmation**: Repeat quote creation, enter `10%` discount, and approve with `y`. Verify `Quote #1 created`.
13. **List quotes**: Input `Show the latest quotes`. Verify Quote #1 is listed for Globex LLC.
14. **Inspect quote**: Input `Show quote 1`. Verify line items and totals match the approved quote.
15. **Exit**: Input `exit`. Verify clean process termination.

---

## Verification Evidence Log

| Date | Task / AC | Command / Test Executed | Output / Evidence | Status |
|---|---|---|---|---|
| 2026-09-16 | `SQA-TASK-0001` / `AC-SQA-001` | `git status --short` | `?? examples/smart_quote_agent/` (0 project files modified) | Pass |
| 2026-09-16 | `SQA-TASK-0002` / `AC-SQA-002`, `AC-SQA-008` | `python examples/smart_quote_agent/init_demo.py --reset` & headless smoke test | Demo initialized with 4 customers, 5 users, 6 products; decimal rounding and transactional rollback assertions passed | Pass |
| 2026-09-16 | `SQA-TASK-0003` / `AC-SQA-003`, `AC-SQA-011` | Pydantic schema unit validation & `mypy --strict` | IntentDecision, RequestedItem, QuoteRequest validations, slots dataclass AuthenticatedUser | Pass |
| 2026-09-16 | `SQA-TASK-0004` / `AC-SQA-003`, `AC-SQA-004` | Auth unit test with mock getpass | Password masking, credential cleanup, role-based ToolPermissionPolicy mapping verified | Pass |
| 2026-09-16 | `SQA-TASK-0005` / `AC-SQA-004`, `AC-SQA-005` | ToolExecutor authorization test | 7 @runtime_tools verified, staff creation permitted, client creation denied | Pass |
| 2026-09-16 | `SQA-TASK-0006` / `AC-SQA-006` | HITL discount prompt bounds test | 0..30 bounds, re-prompting on invalid/out-of-range inputs verified | Pass |
| 2026-09-16 | `SQA-TASK-0007` / `AC-SQA-004`, `AC-SQA-005`, `AC-SQA-009` | StateGraph execution workflow test | Anonymous catalog queries, anonymous denial, client denial, staff quote creation, and quote lookup verified | Pass |
| 2026-09-16 | `SQA-TASK-0008` / `AC-SQA-010` | Interactive CLI scripted session & observer | REPL loop, dynamic prompt reflection, secret-safe ConsoleMetadataObserver verified | Pass |
| 2026-09-16 | `SQA-TASK-0009` / `AC-SQA-011` | Documentation inspection | `examples/smart_quote_agent/README.md` complete with architecture, credentials, 4 transcripts, and security limits | Pass |
| 2026-09-16 | `SQA-TASK-0010` / `AC-SQA-007` | Automated ApprovalHandler denial/allow test | Denial returns denied=True, 0 rows committed; approval commits atomic transaction | Pass |
| 2026-09-16 | `SQA-TASK-0010` / `AC-SQA-011` | `uv run mypy examples/smart_quote_agent --strict` | Success: no issues found in 8 source files | Pass |
| 2026-09-16 | `SQA-TASK-0010` / `AC-SQA-011` | `uv run ruff check examples/smart_quote_agent` | All checks passed! | Pass |
| 2026-09-16 | `SQA-TASK-0010` / `AC-SQA-011` | `uv run ruff format --check examples/smart_quote_agent` | 9 files already formatted | Pass |
| 2026-09-16 | `SQA-TASK-0010` / `AC-SQA-001` | `git status --short` | Zero files outside `examples/smart_quote_agent/` touched | Pass |
| 2026-09-19 | `SQA-TASK-0011` / `AC-SQA-012`, `AC-SQA-013` | `python -m pytest examples/smart_quote_agent/tests/test_agent.py examples/smart_quote_agent/tests/test_telemetry_db.py examples/smart_quote_agent/tests/test_inspector_queries.py -q` | 84 passed; transcript completion, line-safe edits, ambiguous no-op, schema migration, and task/workflow rendering covered | Pass |
| 2026-09-19 | `SQA-TASK-0012`–`SQA-TASK-0015` / `AC-SQA-012`–`AC-SQA-018` | `.venv\Scripts\python.exe -m pytest examples/smart_quote_agent/tests -q` | 137 passed, 2 opt-in live integration tests skipped; transcript recovery, stale guards, interruption/edit safety, customer/product resolution, offline preview edge cases, migration, and inspector covered. LangSmith emitted a non-fatal connectivity/compression warning; command exited successfully. | Pass |
| 2026-09-19 | `SQA-TASK-0016` / `AC-SQA-011` | `.venv\Scripts\python.exe -m mypy examples/smart_quote_agent --strict` | Success: no issues found in 26 source files. | Pass |
| 2026-09-19 | `SQA-TASK-0016` / `AC-SQA-011` | `.venv\Scripts\ruff.exe check examples/smart_quote_agent` | All checks passed. | Pass |
| 2026-09-19 | `SQA-TASK-0016` / `AC-SQA-011` | `.venv\Scripts\ruff.exe format --check examples/smart_quote_agent` | 27 files already formatted. | Pass |
| 2026-09-19 | `SQA-TASK-0016` / Live CLI | Initial provider-free task validation | Not run at that point because explicit live authorization was not available; superseded by the user-authorized diagnostic run recorded below. | Superseded |
| 2026-09-19 | `SQA-TASK-0017` / `AC-SQA-019` | `.venv\Scripts\python.exe -m pytest examples\smart_quote_agent\tests\test_agent.py examples\smart_quote_agent\tests\test_telemetry_db.py examples\smart_quote_agent\tests\test_observability_lifecycle.py examples\smart_quote_agent\tests\test_inspector_queries.py examples\smart_quote_agent\tests\test_host_error_diagnostics.py -q` | 124 passed. Includes CLI logger failure, structured-call stage propagation, exception redaction/external-path reduction/cause/frame capture, runtime interaction correlation, schema migration, and inspector status regressions. | Pass |
| 2026-09-19 | `SQA-TASK-0017` / `AC-SQA-019` | `.venv\Scripts\python.exe -m pytest examples\smart_quote_agent\tests -q` | 142 passed, 2 opt-in live tests skipped. LangSmith network warning was non-fatal; the environment proxy refused its external telemetry connection. | Pass |
| 2026-09-19 | `SQA-TASK-0017` / `AC-SQA-019` | `.venv\Scripts\python.exe -m mypy examples\smart_quote_agent --strict` | Success: no issues found in 28 source files. | Pass |
| 2026-09-19 | `SQA-TASK-0017` / `AC-SQA-019` | `.venv\Scripts\ruff.exe check examples\smart_quote_agent`; `.venv\Scripts\ruff.exe format --check examples\smart_quote_agent`; `git diff --check` | Ruff clean; 29 files already formatted; `git diff --check` returned no whitespace errors (Git printed a working-copy LF→CRLF advisory for the touched test file). | Pass |
| 2026-09-19 | `SQA-TASK-0017` / Live diagnostic | `uv run python examples/smart_quote_agent/app.py` | Could not reach app startup: uv cache access denied. Retried with workspace `.venv` interpreter; sandbox then denied access to local Codex state. User-authorized elevated run started the app and allowed staff login. | Pass with documented environment constraints |
| 2026-09-19 | `SQA-TASK-0017` / `AC-SQA-019` | Live REPL: `staff` login; submit original `quisira armar un presupuesto por un dock y 2 mouses` twice | Both turns returned the unchanged localized generic error. Each generated a distinct interaction ID and one `host.turn_error`; stage `intent_router`, type `proteo_runtime.core.errors.RuntimeUnavailableError`, code `runtime_unavailable`. Both runtime calls had `invocation_started` and no terminal event. No customer selection/review/approval prompt was reached. | Diagnosed; quote path blocked |
| 2026-09-19 | `SQA-TASK-0017` / `AC-SQA-019` | `inspect_observability.py --interaction 9ea8b8c8ff09401985727caf65bc9c1c`; `--interaction 1c82c85d14dd4a9aa42868c0631269df` | Both views rendered `Status: failed`, task `task_493a14a331f948f6a26a2b6ac2a8c8a6`, stage/type/code above, and repository-relative frames through `src/proteo_runtime/providers/codex/_runner.py:events:287`. No cause type was present. No exception message or local values were displayed. | Pass |
| 2026-09-19 | `SQA-TASK-0017` / Business DB safety | Read-only quote count before and after the live attempt | `(7, 7)` before and `(7, 7)` after. No quote was persisted; the DB was not reset. | Pass |

### Diagnostic Interpretation (Facts vs. Hypothesis)

Observed facts: each failed turn started a structured runtime invocation at `intent_router`; the REPL kept its generic Spanish response; the correlated host diagnostic recorded `RuntimeUnavailableError` with stable code `runtime_unavailable`; the interaction view correctly derived `failed` from the incomplete invocation plus `host.turn_error`. The exception had no causal exception in its chain, so the log reports no cause types. The inspected frames terminate in the runtime runner's event loop at `_runner.py:events:287`.

Inference from the current implementation: `_runner.py` constructs `RuntimeUnavailableError` with the message `Codex turn failed` when the provider terminal status is not successful. The sanitized record intentionally excludes that message and does not retain the provider status value, so the exact provider-side status/reason is not established by this evidence. This points to a provider-turn failure after invocation start, not a quote extraction or catalog-resolution failure; the quote workflow was never reached.
