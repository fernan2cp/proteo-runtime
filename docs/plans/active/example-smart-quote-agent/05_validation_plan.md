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

### 3. Repository Boundary Verification (Zero Pollution Check)

```powershell
# Must report untracked/modified files strictly under examples/smart_quote_agent/
# and docs/plans/active/example-smart-quote-agent/
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
