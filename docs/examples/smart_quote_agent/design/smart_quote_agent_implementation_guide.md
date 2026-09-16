# Smart Quote Agent — Implementation Guide

**Project:** Proteo Runtime
**Target repository:** `fernan2cp/proteo-runtime`
**Recommended location:** `examples/smart_quote_agent/`
**Baseline:** Proteo Runtime `0.6.x`, with Phases 0–5 completed
**Purpose:** small integrated demo showing LangGraph orchestration, structured routing/planning, Codex execution, host-managed tools, authorization, HITL, and SQLite persistence without introducing Phase 6 infrastructure. Observability is applied afterward through the separate Smart Quote Agent observability guide.

---

## 1. Goal

Build a small CLI demo in which a user can converse with a Proteo-powered agent about products and quotes.

The example must demonstrate, in one coherent application:

- a LangGraph workflow owned by the host;
- a structured router/planner;
- a controlled agent using host-managed tools;
- anonymous, client, and staff interaction;
- host-owned authorization;
- login/logout as HITL branches;
- masked password input;
- deterministic quote creation;
- a discount HITL step;
- final human approval before persistence;
- SQLite persistence;
- quote and quote-line history;
- explicit separation between model decisions and host authority;
- a clean handoff to the separate observability phase once the functional agent is validated.

The example is intentionally **not** a production commerce system, IAM system, checkout flow, or security sandbox.

---

## 2. Core design principle

The demo should visibly reinforce the Proteo rule:

> The model may decide what it wants to do. The host decides what it is allowed to do and what is actually executed.

The architecture is intentionally hybrid:

- **Agentic flow** for open-ended catalog questions, product exploration, quote previews, and staff quote lookup.
- **Deterministic workflow** for privileged quote creation, including customer resolution, discount HITL, permission validation, approval, and persistence.

This keeps the demo agentic where flexibility is useful and deterministic where mutation and authorization matter.

---

## 3. Scope

### Included

- CLI application.
- Local SQLite database.
- Seed/reset script.
- One staff login.
- Four client logins.
- Anonymous mode.
- Product catalog.
- Quote calculation.
- Quote creation by staff only.
- Quote listing/detail by staff only.
- Login/logout routing.
- Discount selection through HITL.
- Final quote creation approval.
- Host-managed tools.
- Structured routing/planning.
- LangGraph orchestration.
- Real Codex execution when explicitly run by the user.
- Observability integration is deferred to the separate Smart Quote Agent observability implementation phase.

### Explicitly excluded

- Customer creation.
- Product creation/editing.
- Checkout/payment.
- Inventory reservation.
- Web UI.
- API server.
- JWT/OAuth.
- Password reset.
- Production password storage.
- Database migrations framework.
- PostgreSQL.
- Redis.
- Docker.
- Strong filesystem/network/process isolation from Phase 6.
- General retry/backoff/recovery from Phase 7.
- Multi-tenant behavior.
- Durable distributed idempotency.
- Automatic provider fallback.

---

## 4. User model

The application recognizes three interaction states:

```text
anonymous
client
staff
```

There are only two authorization levels:

```text
public/client
staff
```

`anonymous` and `client` have identical tool permissions.

The only behavioral difference is that a logged-in client has an identity and `customer_id` in host state. That identity does **not** grant quote creation or quote-history access.

### Seeded users

All demo passwords are:

```text
1234
```

Seed:

```text
staff   / 1234 -> role=staff
client1 / 1234 -> role=client -> customer_id=1
client2 / 1234 -> role=client -> customer_id=2
client3 / 1234 -> role=client -> customer_id=3
client4 / 1234 -> role=client -> customer_id=4
```

The password is deliberately trivial because this is a demo. The README must state that authentication is not production-grade.

Password input must use `getpass.getpass()` so the password is not echoed to the terminal.

The password must never be copied into:

- LangGraph state;
- `RuntimeInput`;
- tool arguments;
- runtime events;
- LangSmith;
- OpenTelemetry;
- diagnostics;
- logs.

---

## 5. Authorization matrix

| Capability | Anonymous | Client | Staff |
|---|---:|---:|---:|
| View products | Yes | Yes | Yes |
| View product prices | Yes | Yes | Yes |
| Calculate quote preview | Yes | Yes | Yes |
| Login/logout | Yes | Yes | Yes |
| View own authenticated identity | No | Yes | Yes |
| Resolve/list customers | No | No | Yes |
| Create persisted quote | No | No | Yes |
| List persisted quotes | No | No | Yes |
| View persisted quote | No | No | Yes |

### Tool permission mapping

Public/client permission set:

```text
catalog.read
quote.calculate
```

Staff permission set:

```text
catalog.read
quote.calculate
customer.read
quote.create
quote.read
```

The host maps the authenticated role to `ToolPermissionPolicy`.

The model is never the authority for deciding which permission set applies.

---

## 6. SQLite domain model

Use one local SQLite file:

```text
examples/smart_quote_agent/data/demo.sqlite3
```

Use foreign keys:

```sql
PRAGMA foreign_keys = ON;
```

Use integer cents for persisted monetary values.

Python presentation/business calculations should use `Decimal`.

The demo uses a fixed currency:

```text
USD
```

### 6.1 `customers`

```sql
CREATE TABLE customers (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL
);
```

Seed:

```text
1 | client1 | Acme Corp.
2 | client2 | Globex LLC
3 | client3 | Initech
4 | client4 | Northwind Traders
```

### 6.2 `users`

```sql
CREATE TABLE users (
    id           INTEGER PRIMARY KEY,
    username     TEXT NOT NULL UNIQUE,
    password     TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('staff', 'client')),
    display_name TEXT NOT NULL,
    customer_id  INTEGER NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);
```

Constraints enforced by initialization code:

- `staff.customer_id IS NULL`
- every client has a valid `customer_id`
- no user creation is exposed by the demo

Recommended seed:

```text
staff   | 1234 | staff  | Demo Staff | NULL
client1 | 1234 | client | Client 1   | 1
client2 | 1234 | client | Client 2   | 2
client3 | 1234 | client | Client 3   | 3
client4 | 1234 | client | Client 4   | 4
```

### 6.3 `products`

```sql
CREATE TABLE products (
    id               INTEGER PRIMARY KEY,
    sku              TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    description      TEXT NOT NULL,
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    active           INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);
```

Recommended seed:

```text
NB-PRO    | Notebook Pro         | 120000
NB-AIR    | Notebook Air         |  90000
MS-WL     | Wireless Mouse       |   4000
KB-MECH   | Mechanical Keyboard  |   8500
MON-27    | 27" Monitor          |  32000
DOCK-USBC | USB-C Dock           |  15000
```

### 6.4 `quotes`

Every persisted quote belongs to a customer.

Only staff may create one.

```sql
CREATE TABLE quotes (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id           INTEGER NOT NULL,
    created_by_user_id    INTEGER NOT NULL,
    created_at            TEXT NOT NULL,
    currency              TEXT NOT NULL DEFAULT 'USD',
    subtotal_cents        INTEGER NOT NULL CHECK (subtotal_cents >= 0),
    discount_percent      INTEGER NOT NULL DEFAULT 0
                              CHECK (discount_percent BETWEEN 0 AND 30),
    discount_amount_cents INTEGER NOT NULL DEFAULT 0
                              CHECK (discount_amount_cents >= 0),
    total_cents           INTEGER NOT NULL CHECK (total_cents >= 0),
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (created_by_user_id) REFERENCES users(id)
);
```

`created_at` must be stored as UTC ISO-8601.

Example:

```text
2026-09-16T12:34:56+00:00
```

### 6.5 `quote_lines`

```sql
CREATE TABLE quote_lines (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id         INTEGER NOT NULL,
    product_id       INTEGER NOT NULL,
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    subtotal_cents   INTEGER NOT NULL CHECK (subtotal_cents >= 0),
    FOREIGN KEY (quote_id) REFERENCES quotes(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id)
);
```

For the demo, `unit_price_cents` is a price snapshot.

Later changes to `products.unit_price_cents` must not alter historical quote totals.

The demo does not edit product names/SKUs, so duplicating those fields into `quote_lines` is unnecessary.

---

## 7. Quote invariants

A quote must satisfy all of the following:

```text
customer_id is valid
creator is authenticated staff
at least one line exists
quantity > 0
unit price comes from current DB state
line subtotal = quantity * unit price
quote subtotal = sum(line subtotals)
discount_percent is integer 0..30
discount_amount is derived by host code
total = subtotal - discount_amount
total >= 0
creation timestamp is UTC
quote and quote_lines persist atomically
```

The model must never provide authoritative prices, subtotals, discount amounts, totals, creator IDs, timestamps, or permissions.

---

## 8. Discount rule

There is no automatic commercial discount rule in this demo.

For quote creation:

1. Resolve customer.
2. Resolve products and quantities.
3. Re-read current product prices.
4. Compute subtotal host-side.
5. Ask the human whether to apply a discount.
6. If yes, request a whole percentage in range `0..30`.
7. Default is `0`.
8. Compute `discount_amount`.
9. Compute final total.
10. Request final creation approval.
11. Persist only after approval.

Example:

```text
Subtotal: $3,800.00

Apply discount? [y/N]: y
Discount percentage [0-30, default 0]: 10

Discount: 10% ($380.00)
Total: $3,420.00
```

Invalid values are re-prompted:

```text
-1
31
abc
```

Empty input resolves to `0`.

---

## 9. HITL design

The demo has three human-interaction points.

### 9.1 Login HITL

Triggered by requests such as:

```text
login
iniciar sesión
quiero iniciar sesión
loguearme
```

The router selects the login branch.

The host node executes:

```python
username = input("Username: ")
password = getpass("Password: ")
```

Credentials are validated directly against SQLite.

On success, graph state receives only sanitized identity:

```python
{
    "user_id": 1,
    "username": "staff",
    "display_name": "Demo Staff",
    "role": "staff",
    "customer_id": None,
}
```

The password variable is discarded after validation.

### 9.2 Discount HITL

Used only inside the staff quote-creation workflow.

This is a host-owned graph step, not a model decision.

### 9.3 Final persistence approval

After the discount is known and final amounts are displayed, the actual `create_quote` tool execution must still require approval.

Preferred implementation:

- `create_quote` is `SideEffect.WRITE`;
- configure it with approval required for side effects;
- the Phase 5 `ApprovalHandler` asks the final confirmation.

Example:

```text
Create quote for Globex LLC?
Subtotal: $3,800.00
Discount: 10% ($380.00)
Total: $3,420.00

Approve? [y/N]:
```

A denial means:

```text
no INSERT
no quote ID
no partial quote lines
```

---

## 10. Logout

Requests such as:

```text
logout
cerrar sesión
salir de mi cuenta
```

route to a deterministic host node.

It clears the sanitized authenticated identity from graph state.

The process continues in anonymous mode.

No database row is deleted or modified.

---

## 11. LangGraph architecture

Recommended graph:

```text
                           START
                             |
                             v
                        intent_router
                    /      |       |       \
                 login   logout  quote_create  agent_request
                   |       |         |              |
                   v       v         v              v
              login_hitl clear_auth auth_guard  controlled_agent
                                   /      \
                                deny      allow
                                 |          |
                                 |          v
                                 |     quote_planner
                                 |          |
                                 |          v
                                 |   resolve_quote_data
                                 |          |
                                 |          v
                                 |     discount_hitl
                                 |          |
                                 |          v
                                 |   create_quote_tool
                                 |      + approval
                                 |          |
                   _____________|__________|
                  /
                 v
             final_output
                 |
                 v
                END
```

### Deliberate architectural choice

`controlled_agent` is used for open-ended conversational operations.

The quote mutation path is explicit and deterministic after intent detection.

This is intentional.

The demo should show that agentic reasoning and workflows can coexist:

```text
use an agent where flexibility helps
use deterministic orchestration where authority matters
```

---

## 12. Structured router

Use a small structured model with a schema conceptually similar to:

```python
class IntentDecision(BaseModel):
    intent: Literal[
        "login",
        "logout",
        "quote_create",
        "agent_request",
    ]
```

The router never receives credentials.

Routing is **heuristic-first**: unequivocal commands are classified deterministically. If the heuristic cannot identify the intent confidently, it returns `None` and the host invokes the structured LLM classifier.

Live mode uses two distinct bindings, both at logical level `low`:

```python
structured_model = runtime.model(profile="structured", level="low")
controlled_agent_model = runtime.model(profile="controlled_agent", level="low")
```

`structured_model` is used for ambiguous intent classification and quote extraction. `controlled_agent_model` is used only for the conversational tool-using branch. Live Codex startup must enable host-managed dynamic tools with `CodexRuntime(experimental_dynamic_tools=True)`.

### Routing semantics

`login`:
- host login HITL

`logout`:
- host logout node

`quote_create`:
- dedicated deterministic quote workflow

`agent_request`:
- controlled agent with role-appropriate tools

The router is advisory for intent classification only.

Authorization is enforced later by host code.

---

## 13. Quote planner

For `quote_create`, use structured output to convert the natural-language request into a draft:

```python
class RequestedItem(BaseModel):
    product: str | None = None
    quantity: int | None = Field(default=None, gt=0)


class QuoteRequest(BaseModel):
    customer: str | None = None
    items: list[RequestedItem] = Field(default_factory=list)
```

The structured model is instructed to extract only information explicitly present in the request and never invent customer, product, or quantity values.

Host-side validation then requires:

```text
customer non-empty
at least one complete item
product non-empty
quantity > 0
```

If required data is missing, the workflow returns a clarification request and stops before database resolution or HITL.

The planner does not resolve:

- customer IDs;
- product IDs;
- prices;
- permissions;
- discount;
- totals.

Those remain host-owned.

---

## 14. Graph state

Recommended conceptual state:

```python
class DemoState(TypedDict, total=False):
    input: str
    output: str

    authenticated_user: AuthenticatedUser | None

    intent: str
    quote_authorized: bool | None
    quote_request: QuoteRequest | None
    quote_draft: QuoteDraft | None
    created_quote_id: int | None
```

Never include:

```text
password
raw credential input
provider token
approval secrets
```

`authenticated_user` is host-owned state.

---

## 15. Host-managed tools

Keep the registry small.

### 15.1 `list_products`

```text
permission: catalog.read
side_effect: read
approval: never
```

Input can optionally contain a simple search/filter string.

Returns active products with:

```text
id
sku
name
description
unit_price
currency
```

### 15.2 `get_product` / `find_product`

Recommended single tool name:

```text
find_product
```

```text
permission: catalog.read
side_effect: read
approval: never
```

Input:

```text
query: str
```

Returns exact/closest deterministic DB matches.

Ambiguous matches must be returned as alternatives, not silently guessed.

### 15.3 `calculate_quote`

```text
permission: quote.calculate
side_effect: none
approval: never
```

This is a pure host calculation.

Input uses already resolved product IDs and quantities.

It re-reads current product prices.

Returns:

```text
lines
subtotal
```

It does not apply a discount and does not persist.

### 15.4 `find_customer`

```text
permission: customer.read
side_effect: read
approval: never
```

Staff-only through permission policy.

Input:

```text
query: str
```

Returns customer ID/code/name.

Ambiguous matching fails or returns alternatives.

### 15.5 `create_quote`

```text
permission: quote.create
side_effect: write
approval: for_side_effects
```

Staff-only.

The normal graph path calls it only after:

```text
auth guard
customer resolution
product resolution
price calculation
discount HITL
```

The tool must revalidate authoritative DB data before INSERT.

Input should contain IDs/quantities plus host-selected discount, not model-calculated money fields.

Recommended input:

```python
customer_id: int
items: list[{product_id: int, quantity: int}]
discount_percent: int
```

The callable:

1. verifies customer exists;
2. verifies products exist and are active;
3. re-reads prices;
4. recomputes line subtotals;
5. recomputes subtotal;
6. validates discount `0..30`;
7. computes discount amount;
8. computes total;
9. records authenticated staff user ID;
10. records UTC creation time;
11. inserts quote + lines in one transaction;
12. returns persisted quote summary.

### 15.6 `list_quotes`

```text
permission: quote.read
side_effect: read
approval: never
```

Staff-only.

Supports a bounded optional limit.

Default:

```text
10
```

Return newest first.

### 15.7 `get_quote`

```text
permission: quote.read
side_effect: read
approval: never
```

Staff-only.

Returns:

```text
quote ID
customer
creator
created_at
currency
lines
subtotal
discount_percent
discount_amount
total
```

---

## 16. Tool binding strategy

Create two logical policies.

### Public/client executor policy

```python
ToolPermissionPolicy(
    frozenset({
        "catalog.read",
        "quote.calculate",
    })
)
```

### Staff executor policy

```python
ToolPermissionPolicy(
    frozenset({
        "catalog.read",
        "quote.calculate",
        "customer.read",
        "quote.create",
        "quote.read",
    })
)
```

A login changes the host-selected permission policy for subsequent requests.

The conversational registry is also narrowed by role:

```text
anonymous/client -> list_products, find_product, calculate_quote
staff            -> the same tools + find_customer, list_quotes, get_quote
```

`create_quote` is never exposed to the conversational controlled agent. It lives in a dedicated write registry used only by the deterministic quote-creation branch.

The host decides which registry and executor/policy are bound for the current interaction.

Registration of a tool does not imply permission to execute it.

---

## 17. Defense in depth for quote creation

The normal quote-create branch performs an early staff check:

```text
if role != staff:
    deny before quote workflow
```

`create_quote` must still require `quote.create`.

This gives two layers:

```text
graph authorization guard
        +
tool permission policy
```

The second layer remains authoritative if the graph is changed incorrectly.

---

## 18. Controlled agent behavior

The controlled agent is intended for requests such as:

```text
What notebooks do you have?
How much are three Notebook Pro units?
Show me the available accessories.
What would two monitors and one dock cost?
```

For staff:

```text
Show the latest quotes.
Show quote 12.
Which customer owns quote 8?
```

The controlled agent may select host-managed tools dynamically from the role-appropriate conversational registry.

It must never receive `create_quote`; persistent quote mutation is reachable only through the deterministic quote workflow.

It must not receive arbitrary shell, filesystem-write, browser, network, SQL, or MCP authority.

SQLite is accessed only through application-owned functions.

---

## 19. Quote-creation flow

Example:

```text
User:
Create a quote for Globex for 3 Notebook Pro and 5 Wireless Mouse.

1. intent_router
   -> quote_create

2. auth_guard
   -> requires staff

3. quote_planner
   -> customer="Globex"
   -> items=[
        {"product":"Notebook Pro","quantity":3},
        {"product":"Wireless Mouse","quantity":5}
      ]

4. host resolves customer from SQLite
   -> Globex LLC / customer_id=2

5. host resolves products from SQLite
   -> NB-PRO
   -> MS-WL

6. host computes authoritative subtotal from DB prices

7. discount HITL
   -> 10%

8. host computes draft
   -> subtotal
   -> discount_amount
   -> total

9. create_quote request

10. ToolExecutor permission check
    -> quote.create allowed

11. ApprovalHandler
    -> final human approval

12. create_quote callable
    -> re-read DB
    -> recompute
    -> transaction INSERT

13. persisted quote returned

14. final_output
```

---

## 20. Price and money handling

Do not use binary floating point for business calculations.

Persist money as integer cents.

Use:

```python
Decimal
```

for display and percentage calculations.

Example conversion:

```python
Decimal(cents) / Decimal(100)
```

Discount amount should use one deterministic rounding rule.

Recommended:

```text
ROUND_HALF_UP to nearest cent
```

The same helper must be used everywhere.

---

## 21. SQLite transaction rules

`create_quote` must use one transaction:

```text
BEGIN
  INSERT quotes
  INSERT quote_lines...
COMMIT
```

Any failure:

```text
ROLLBACK
```

It must be impossible to persist:

```text
quote without all lines
partial lines
header with mismatched totals
```

---

## 22. Initialization script

Recommended command:

```bash
python examples/smart_quote_agent/init_demo.py --reset
```

Behavior:

1. create `data/`;
2. delete existing demo DB only when `--reset` is explicit;
3. create schema;
4. enable foreign keys;
5. seed customers;
6. seed users;
7. seed products;
8. print credentials and DB path.

Example:

```text
Smart Quote Agent demo initialized.

Database:
examples/smart_quote_agent/data/demo.sqlite3

Users:
staff   / 1234
client1 / 1234
client2 / 1234
client3 / 1234
client4 / 1234
```

Running without `--reset` should be idempotent or fail with a clear message if initialized already.

---

## 23. CLI interaction

Recommended startup:

```text
Proteo Runtime — Smart Quote Agent

Mode: anonymous
Type "login" to sign in.
Type "logout" to sign out.
Type "exit" to quit.

>
```

After login:

```text
Logged in as Demo Staff (staff)
```

After logout:

```text
Logged out. Continuing as anonymous.
```

`exit` should be handled deterministically by the host and never sent to the model.

---

## 24. Example authorization scenario

Client:

```text
> login

Username: client2
Password:
✓ Logged in as Client 2

> Create a quote for Globex for 2 Notebook Pro.

Access denied.
Persisted quotes can only be created by staff.
```

The workflow should deny before asking for discount or final approval.

No quote rows may be created.

---

## 25. Example successful quote

```text
> login

Username: staff
Password:
✓ Logged in as Demo Staff

> Create a quote for Globex for 3 Notebook Pro and 5 Wireless Mouse.

Customer: Globex LLC

3 × Notebook Pro      $3,600.00
5 × Wireless Mouse      $200.00

Subtotal: $3,800.00

Apply discount? [y/N]: y
Discount percentage [0-30, default 0]: 10

==================================================
HOST QUOTE REVIEW
==================================================
Customer: Globex LLC (ID: 2)
Line items:
  - Notebook Pro (NB-PRO): 3x @ $1,200.00 = $3,600.00
  - Wireless Mouse (MS-WL): 5x @ $40.00 = $200.00
Subtotal:        $3,800.00
Discount:        10% ($380.00)
Total:           $3,420.00
==================================================

[APPROVAL REQUIRED] Tool execution requested: create_quote
Approve quote creation? [y/N]: y
[APPROVED] Action approved.

[SUCCESS] Quote #1 created for Globex LLC.
Total: $3,420.00
```

Later:

```text
> Show quote 1

Quote #1
Customer: Globex LLC
Created: 2026-09-16T12:34:56+00:00
Created by: Demo Staff

3 × Notebook Pro      $3,600.00
5 × Wireless Mouse      $200.00

Subtotal:             $3,800.00
Discount 10%:           $380.00
Total:                $3,420.00
```

---

## 26. Observability handoff

Observability is intentionally implemented as a **separate second phase** after the functional agent in this guide has been validated.

The base Smart Quote Agent must not require a console observer, LangSmith, OpenTelemetry, or a telemetry SQLite database in order to run.

The separate observability guide may attach Phase 4 observers/exporters to this same runtime/tool activity while preserving the functional workflow unchanged.

Regardless of the observer/exporter used, never export:

```text
password
raw login input
unredacted credentials
```

Login remains a host interaction and credentials must not enter runtime telemetry.

---

## 27. Security boundaries demonstrated

The demo should explicitly explain what it proves:

```text
✓ model does not own credentials
✓ model does not choose role
✓ model does not grant permissions
✓ model does not own SQLite connection authority
✓ model does not choose authoritative prices
✓ model does not choose discount
✓ model does not persist without host approval
✓ tool registration does not imply tool permission
✓ quote mutation is staff-only
```

It must also explain what it does **not** prove:

```text
✗ production authentication
✗ hardened secret storage
✗ OS-level sandbox isolation
✗ filesystem/network enforcement
✗ malicious local process isolation
```

Those are outside this example and strong isolation remains Phase 6 territory.

---

## 28. Recommended file layout

```text
examples/
└── smart_quote_agent/
    ├── README.md
    ├── app.py
    ├── init_demo.py
    ├── database.py
    ├── models.py
    ├── auth.py
    ├── tools.py
    ├── graph.py
    ├── hitl.py
    ├── data/
    │   └── .gitkeep
    └── tests/
        ├── __init__.py
        └── test_agent.py
```

### Responsibilities

`app.py`
- CLI loop;
- runtime startup/shutdown;
- graph invocation;
- exit handling.

`init_demo.py`
- reset/create SQLite DB;
- seed demo records.

`database.py`
- connection helper;
- schema creation;
- query functions;
- transactional quote persistence;
- cents/Decimal helpers if desired.

`models.py`
- Pydantic structured router/planner types;
- graph-state supporting types;
- quote draft/view models.

`auth.py`
- login lookup;
- `getpass`;
- sanitized identity;
- role-to-permission mapping.

`tools.py`
- `runtime_tool` definitions;
- registry factory;
- executor/policy factory;
- approval handler.

`graph.py`
- LangGraph state and nodes;
- routing;
- quote workflow;
- controlled-agent branch.

`hitl.py`
- discount prompt/validation;
- final human approval implementation.

`README.md`
- setup;
- architecture;
- credentials;
- example sessions;
- security disclaimer.

`tests/test_agent.py`
- deterministic, zero-quota regression coverage for routing, authorization, tools, HITL, persistence, and live-error propagation.

---

## 29. Implementation boundary

The example should remain intentionally small and explicit. The original rough target was:

```text
300–500 lines of core application logic
```

excluding comments/README/schema/tests. Treat this as a complexity guideline rather than a hard acceptance gate; clarity and explicit security boundaries take priority over compressing the implementation.

Do not introduce abstractions merely to make the demo look enterprise-ready.

Prefer:

```text
small explicit functions
clear data flow
reusable Proteo contracts
```

over:

```text
repositories/services/factories for every object
DI container
generic RBAC engine
plugin architecture
ORM
migration framework
```

`sqlite3` from the Python standard library is sufficient.

---

## 30. Acceptance scenarios

The example is ready when all of these can be demonstrated.

### Initialization

- reset creates deterministic DB;
- four customers exist;
- four client users exist;
- one staff user exists;
- products exist.

### Authentication

- login is routable from natural language;
- password is masked;
- correct password logs in;
- wrong password does not change identity;
- logout returns to anonymous;
- password never enters graph state.

### Public/client

- anonymous can query products;
- client can query products;
- anonymous/client can calculate quote previews;
- anonymous/client cannot create persisted quotes;
- anonymous/client cannot read quote history.

### Staff

- staff can resolve customers;
- staff can request quote creation;
- discount defaults to zero;
- discount accepts 0–30;
- invalid discount is rejected/re-prompted;
- final approval denial persists nothing;
- final approval success creates quote + lines;
- quote timestamp is UTC;
- staff can list quotes;
- staff can read a quote.

### Integrity

- prices are re-read from DB before persistence;
- model-supplied monetary totals are ignored;
- total arithmetic is deterministic;
- price snapshots remain on quote lines;
- quote persistence is atomic;
- quote always has a customer;
- creator is recorded as staff.

### Proteo behavior

- structured router/planner is exercised;
- LangGraph controls workflow state;
- controlled agent selects tools on open-ended requests;
- ToolPermissionPolicy gates capabilities;
- Phase 5 approval is used for final persistence;
- no provider-specific SDK object leaks into graph state;
- observability remains a separate follow-on implementation phase and is not required for functional-agent acceptance.

---

## 31. Recommended demo narrative

For a short live demonstration:

```text
1. Start anonymous.
2. Ask which notebooks exist and their prices.
3. Ask for a non-persisted total for 2 Notebook Pro.
4. Ask to create a quote -> denied because anonymous.
5. Login as client2 -> password hidden.
6. Ask again to create quote -> still denied.
7. Logout.
8. Login as staff.
9. Create quote for Globex.
10. Apply 10% discount through HITL.
11. Reject final approval once -> verify nothing persisted.
12. Repeat and approve.
13. Ask "show the latest quotes".
14. Ask "show quote 1".
15. Logout.
```

This sequence demonstrates the architecture much better than a single happy-path request.

---

## 32. Key design decisions frozen for the demo

```text
- SQLite is local and disposable.
- Users/customers/products are seed-only.
- There is no customer CRUD.
- There is no checkout.
- Anonymous and client share the same business permissions.
- Staff alone can create/read persisted quotes.
- Every quote belongs to one customer.
- Every quote records the staff creator.
- Login/logout are host-side workflow branches.
- Password input is masked with getpass.
- Password never enters model/runtime state.
- Discount is host HITL, integer 0..30, default 0.
- Final persistence requires approval.
- Monetary authority belongs to host code.
- Persisted money uses integer cents.
- Quote creation is transactional.
- Open-ended queries use the controlled agent.
- Privileged mutation uses deterministic workflow orchestration.
- Observability is applied in a separate follow-on phase without changing functional authority boundaries.
- The demo does not attempt to implement Phase 6 security hardening.
```

---

## 33. Architectural references in Proteo Runtime

This example should stay aligned with the repository's existing contracts:

```text
docs/design/project-guide.md
docs/plans/complete/phase-3-langgraph-integration/
docs/plans/complete/phase-5-host-managed-tools/
docs/plans/complete/phase-4-observability-langsmith-opentelemetry/  # follow-on observability phase
```

In particular:

- the host owns application state and execution authority;
- LangGraph remains outside the core;
- tools are host-managed capabilities;
- tool permissions are exact host-side allow-lists;
- Phase 4 exporter payloads remain metadata-only when the separate observability phase is applied;
- controlled tools do not grant native shell/filesystem/network authority;
- strong runtime isolation remains separate from this demo.
