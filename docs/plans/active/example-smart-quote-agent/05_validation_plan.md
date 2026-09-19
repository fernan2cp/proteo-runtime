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
# Authorized changes: examples/smart_quote_agent/*, this active SDD package,
# src/proteo_runtime/providers/codex/_structured.py,
# src/proteo_runtime/providers/codex/_runner.py,
# tests/unit/test_codex_structured.py, and tests/unit/test_codex_provider.py.
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
| SCEN-001 | Repository boundary verification | `AC-SQA-001` | Changes stay within the example, active SDD, and four explicitly allowlisted runtime/test paths; no other core, test, config, API, or business-schema changes. |
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
| SCEN-024 | Codex provider schema adaptation and failure terminal events | `AC-SQA-020` | The `TurnDecision` request schema has recursive `anyOf` and no discriminator; original Pydantic validation still enforces exactly one variant; provider code/status survive without message text; buffered failed terminal events appear once; successful turns remain completed. |

---

## Conversational Hardening Regression Commands

The provider-free suite reproduces the reported thread without network calls or resetting the business database:

```powershell
uv run pytest examples/smart_quote_agent/tests/test_agent.py -q
uv run pytest examples/smart_quote_agent/tests/test_observability_*.py examples/smart_quote_agent/tests/test_inspector_queries.py -q
```

For local telemetry migration and the full task/workflow view, use a temporary observability DB in tests. Never reset `examples/smart_quote_agent/data/demo.sqlite3` as part of acceptance verification.

## Codex Provider Regression Commands

Run the focused provider suites and full example suite:

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_codex_structured.py tests/unit/test_codex_provider.py -q
.venv\Scripts\python.exe -m pytest examples/smart_quote_agent/tests -q
```

Run strict typing, lint/format checks, and whitespace validation across the exact expanded code boundary:

```powershell
.venv\Scripts\python.exe -m mypy src/proteo_runtime/providers/codex/_structured.py src/proteo_runtime/providers/codex/_runner.py tests/unit/test_codex_structured.py tests/unit/test_codex_provider.py examples/smart_quote_agent --strict
.venv\Scripts\ruff.exe check src/proteo_runtime/providers/codex/_structured.py src/proteo_runtime/providers/codex/_runner.py tests/unit/test_codex_structured.py tests/unit/test_codex_provider.py examples/smart_quote_agent
.venv\Scripts\ruff.exe format --check src/proteo_runtime/providers/codex/_structured.py src/proteo_runtime/providers/codex/_runner.py tests/unit/test_codex_structured.py tests/unit/test_codex_provider.py examples/smart_quote_agent
git diff --check
```

The focused tests must cover recursive provider-only schema conversion, strict host validation through the original Pydantic model, redaction of a sentinel provider error message, safe stable code/status propagation, exactly-once publication of buffered turn/invocation failure events, and normal successful completion. Then repeat the live transcript below with a read-only quote count before and after; never reset either database.

---

## Latency, Prompt Cache, and Single-Inference Verification

### Provider-Free Regression Commands

All automated checks use fake runtimes/controlled timestamps and must not call Codex or consume model quota:

```powershell
uv run pytest examples/smart_quote_agent/tests -q
uv run mypy examples/smart_quote_agent --strict
uv run ruff check examples/smart_quote_agent
uv run ruff format --check examples/smart_quote_agent
git diff --check
```

The tests must verify the following evidence:

- Latency events correlate `interaction_id`, `call_id`, stage, and available task/workflow IDs without storing content. A failing telemetry write does not affect the graph result.
- Controlled timestamps separate provider preparation, direct structured model duration or a controlled-task invocation span, TTFT, structured time-to-terminal, each pre/post-tool interval, tool execution, quote-approval wait, discount prompt wait, and total interaction wall time. Tool-inclusive task spans are labeled accordingly, not presented as pure model inference. A simulated 9.7-second approval pause and 30-ms tool call must display as separate durations.
- Repeated usage snapshots for one invocation contribute only their latest token/cache counts. Aggregate cache ratio is weighted by input token count. Missing terminal events remain incomplete and are not included in latency percentiles.
- `--latency --limit N` selects at most the latest N invocations and groups by stage/model/profile. Count, nearest-rank p50/p95, and cache ratio match a fixture with known timestamps and usage. Default `--limit` remains 10.
- `--last` labels a wall duration containing human approval or discount wait. `--interaction` and `--task` show correlated model/HITL/tool breakdowns without rendering prompt or response content.
- Initial, pending, and edited structured-turn inputs produce byte-identical system prompt and `TurnDecision` schema. Variable context is deterministic fixed-key JSON with correct escaping. Payloads through 16,384 UTF-8 bytes are accepted; an over-limit payload yields a localized host response, preserves workflow state, and makes no model call.
- Controlled-agent instructions have a shared stable prefix, append the sanitized identity role once at task creation, and contain no host-side history replay.
- `TurnDecision` rejects simultaneous request+patch and quote payloads for non-quote intents. A new request, pending patch, full reformulation that replaces a pending workflow and invalidates its draft, incomplete quote, unrelated intent, and malformed result each follow the rules in `SQA-REQ-023`.
- For the ambiguous initial quote phrase, the graph records exactly one structured decision invocation, emits no second structured `quote_planner` invocation, and retains Notebook Pro quantity 1 plus Wireless Mouse quantity 2. No new keyword or regex route is introduced.

### Live Latency Session

Run the live demonstration only with the existing local Codex state and without resetting either database. Capture a read-only quote count before starting. Log in as `staff` with the demo password and use the deliberately ambiguous initial phrase `Crea un presupuesto por una notebook pro y 2 mouse`; inspect that interaction and confirm one structured invocation. Then request the customer list, choose Initech, and accept the default zero discount. The host review must show Initech, Notebook Pro 1x, Wireless Mouse 2x, subtotal USD 1,280, discount USD 0, total USD 1,280. Decline final persistence after inspecting the review so this latency validation does not add a business quote. Capture the task/interaction inspector timelines, model/token/cache measurements, HITL timing, and read-only quote count after the session. Compare the first turn's invocation count against the baseline two structured calls; do not require an absolute wall-latency target or a live cache hit.

#### Observed Live Evidence — 2026-09-19

- The first run with the combined decision exposed one prompt gap: the LLM omitted the quantity implied by the singular article before Notebook Pro. The fixed, constant system prompt now states that singular articles such as `un/una` imply quantity 1 unless an explicit quantity is given. Repeating the same phrase reached review without asking for the quantity; the console showed Initech (ID 3), Notebook Pro 1x, Wireless Mouse 2x, subtotal USD 1,280, discount 0%, and total USD 1,280.
- The repeated session used task `task_874639f3ca994eb68375a7f79c1cb9b2`; the initial quote interaction was `655a249d5045491387ab981479082614`, with structured invocation `5476ef0f7c314ec5baadf2e957190b14`. The initial quote turn made exactly one `intent_router` structured invocation; `quote_planner` performed host-side reduction only. The structured invocation took 4.35 s from `invocation_started` to terminal, with 137 ms host-to-invocation provider preparation, 16,643 input tokens, 55 output tokens, and 0 cached input tokens. The interaction wall time was 4.53 s.
- The customer-list turn intentionally invoked the controlled agent after classification. Its runtime task span was 4.49 s, including a 13 ms customer-list tool call, with TTFT 3.75 s and 15,104/16,133 cached input tokens (94%). The interaction lasted 9.51 s. This is the separate conversational/tool-selection call permitted by the design, not a second quote extraction call.
- The final interaction (`e19ae70c29dd4049b374765902a46cb4`) took 7.60 s. The inspector reports discount HITL wait of 3.90 s and approval wait of 3.54 s separately from model/tool work. Final quote approval was declined. A read-only business-database count was 9 both before and after the session; no quote was persisted.
- `--latency --limit 10` selected 10 recent runtime invocations and reported 7 model calls. For `intent_router` / `gpt-5.6-luna` / `structured`, count 5, p50 4.35 s, p95 5.24 s, cached input 0%. For `controlled_agent` / `gpt-5.6-luna`, count 2, p50 4.49 s, p95 5.30 s, cached input 94%. These are observed samples, not absolute latency or cache-hit acceptance thresholds.
- The task close emitted the known `task.cleanup.provider_delete_failed` diagnostic. Provider cleanup remediation remains outside this plan; it did not prevent the quote review or change the business database.

Commands used for read-only review: `.venv\\Scripts\\python.exe examples/smart_quote_agent/inspect_observability.py --task task_874639f3ca994eb68375a7f79c1cb9b2` and `.venv\\Scripts\\python.exe examples/smart_quote_agent/inspect_observability.py --latency --limit 10`.

Do not enter a password, prompt, model response, tool argument, or customer/product content into any telemetry event. If a latency event lacks a required timestamp/correlation ID or contains unapproved metadata, treat acceptance as failed and preserve the database.

### Latency Scenario Matrix

| Scenario ID | Description | Covered Criteria | Expected Result |
|---|---|---|---|
| SCEN-025 | Interaction/model/tool/HITL timeline | `AC-SQA-021` | Fake events derive correct durations; an invocation view excludes sibling model calls and labels invocation approval separately from interaction discount wait; tool execution is separate; final token snapshot and cache ratio are correct; content is redacted. |
| SCEN-026 | Cache-eligible prompt serialization | `AC-SQA-022` | System prompt and schema are byte-identical across contexts; fixed-key escaped JSON is bounded; overflow does not call the model or mutate the workflow. |
| SCEN-027 | Combined intent and quote extraction | `AC-SQA-023` | Ambiguous initial request uses exactly one structured inference and retains 1 Notebook Pro plus 2 Wireless Mouse; host planner makes no LLM call. |

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
| 2026-09-19 | `SQA-TASK-0017` / `AC-SQA-019` | Initial pre-fix live REPL: staff login; submit original `quisira armar un presupuesto por un dock y 2 mouses` twice | Both turns returned the generic localized error. Each generated a distinct interaction ID and `host.turn_error` at `intent_router`, type `RuntimeUnavailableError`, code `runtime_unavailable`; the buffered terminal events were absent. No customer selection/review/approval prompt was reached. | Pre-fix failure; superseded by successful post-fix run |
| 2026-09-19 | `SQA-TASK-0017` / `AC-SQA-019` | `inspect_observability.py --interaction 9ea8b8c8ff09401985727caf65bc9c1c`; `--interaction 1c82c85d14dd4a9aa42868c0631269df` | Both views rendered `Status: failed`, task `task_493a14a331f948f6a26a2b6ac2a8c8a6`, stage/type/code above, and repository-relative frames through `src/proteo_runtime/providers/codex/_runner.py:events:287`. No cause type was present. No exception message or local values were displayed. | Pass |
| 2026-09-19 | `SQA-TASK-0017` / Business DB safety | Read-only quote count before and after the live attempt | `(7, 7)` before and `(7, 7)` after. No quote was persisted; the DB was not reset. | Pass |
| 2026-09-19 | `SQA-TASK-0018` / diagnostic baseline | Differential Codex structured-output probe | Login/account startup succeeded, the requested model remained discoverable, a minimal structured inference completed, and usage was not at its limit. The production `TurnDecision` schema containing `oneOf` failed with provider code `other`; the provider-only variant using `anyOf` and no `discriminator` completed. This isolated the observed failure to schema compatibility. | Confirmed diagnosis |
| 2026-09-19 | `SQA-TASK-0018` / `AC-SQA-020` | `.venv\Scripts\python.exe -m pytest tests/unit/test_codex_structured.py tests/unit/test_codex_provider.py -q` | 27 runtime provider/structured tests passed, including schema adaptation, host validation, provider failure metadata redaction, terminal event flushing, and successful completion. | Pass |
| 2026-09-19 | `SQA-TASK-0016`, `SQA-TASK-0018` / `AC-SQA-011`, `AC-SQA-020` | `.venv\Scripts\python.exe -m pytest examples/smart_quote_agent/tests -q` | 143 passed, 2 skipped. | Pass |
| 2026-09-19 | `SQA-TASK-0016`, `SQA-TASK-0018` / `AC-SQA-001`, `AC-SQA-011`, `AC-SQA-020` | Strict mypy, Ruff check/format, `git diff --check` | All checks passed for the affected runtime modules/tests and example scope. | Pass |
| 2026-09-19 | `SQA-TASK-0018` / Live CLI | Initial `.venv` attempt, then permitted run using existing local Codex state | The sandboxed attempt could not access `%USERPROFILE%\.codex`; the permitted run used the existing state. No login state was reset or re-created. | Pass with documented environment constraint |
| 2026-09-19 | `SQA-TASK-0018` / `AC-SQA-019`, `AC-SQA-020` | Live REPL: staff login; original Spanish request; list customers; choose Globex; accept 0% discount; review and approve | Review matched Globex LLC, 1 USB-C Dock (`DOCK-USBC`), 2 Wireless Mouse (`MS-WL`), 0% discount, USD 230.00. Approved exactly once; created Quote #8. | Pass |
| 2026-09-19 | `SQA-TASK-0018` / Business DB safety | Read-only business DB counts and quote/line lookup before and after live run | Quote count changed from 7 to 8. Quote #8 has `customer_id=2`, subtotal/total `23000` cents, discount 0; lines are product 6 × 1 at 15000 cents and product 3 × 2 at 4000 cents. No reset was performed. | Pass; exactly one quote added |
| 2026-09-19 | `SQA-TASK-0018` / `AC-SQA-020` | `inspect_observability.py --last --events` | The invocation is `completed`; events include the `create_quote` approval and tool completion. | Pass |
| 2026-09-19 | `SQA-TASK-0019`–`SQA-TASK-0021` / `AC-SQA-021`–`AC-SQA-023` | `.venv\Scripts\python.exe -m pytest examples/smart_quote_agent/tests -q` | 159 passed, 2 skipped. LangSmith emitted a non-fatal network/compression warning because the environment proxy blocks its external telemetry connection. | Pass |
| 2026-09-19 | `SQA-TASK-0019`–`SQA-TASK-0021` / `AC-SQA-011`, `AC-SQA-021`–`AC-SQA-023` | Strict mypy; Ruff check/format; `git diff --check` | Mypy: no issues in 28 source files; Ruff check passed; 29 files formatted; no diff whitespace errors. | Pass |
| 2026-09-19 | `SQA-TASK-0019` / `AC-SQA-021` | `inspect_observability.py --task task_874639f3ca994eb68375a7f79c1cb9b2`; `--latency --limit 10`; final `--last --events` review | The task timeline separates the 13-ms customer tool, 3.54-s quote approval wait, 3.90-s discount wait, 4.35-s initial structured call, and 4.49-s controlled-agent runtime. Updated `--last` labels approval as invocation-scoped and discount as interaction-scoped, without sibling model spans. | Pass |
| 2026-09-19 | `SQA-TASK-0021` / `AC-SQA-023` | Live CLI: staff login; ambiguous Notebook Pro/Wireless Mouse request; list customers; choose Initech; accept zero discount; decline approval | Reached review with 1 Notebook Pro, 2 Wireless Mouse, USD 1,280 subtotal/total and 0% discount. The initial quote turn had exactly one structured router invocation; quote persistence was declined. Read-only quote count remained 9 before and after. | Pass; no business write |

### Diagnostic Interpretation (Facts vs. Hypothesis)

Observed facts: the two pre-fix turns began at `intent_router` and were recorded as `RuntimeUnavailableError` / `runtime_unavailable`; the correlated inspector derived their incomplete interactions as failed. A differential probe confirmed that Codex login/startup, model discovery, minimal structured inference, and current usage were healthy; `TurnDecision` with `oneOf` failed with provider code `other`, while the `anyOf`/no-discriminator provider schema completed. After the fix, 27 runtime tests and the 143-passed/2-skipped example suite passed, and the live flow completed with the expected review and quote #8.

Implementation gap confirmed and corrected: `_runner.py` now preserves safe provider code/status metadata, and the structured wrapper publishes buffered terminal failure events exactly once before propagating the error. The original failure was caused by the provider rejecting the `oneOf` schema; host-side validation retains the original Pydantic semantics. The successful post-fix live run and read-only database check confirm the quote path is unblocked for the reported scenario.
