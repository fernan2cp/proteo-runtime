# Technical Design — Smart Quote Agent Example

## Architectural Overview & Topology

The Smart Quote Agent is implemented as an autonomous CLI application inside `examples/smart_quote_agent/`. It relies upon Proteo Runtime's core contracts, LangGraph node integration (`RuntimeNode`), host-managed tools (`proteo_runtime.tools`), and metadata-only observability (`proteo_runtime.observability`).

```text
examples/smart_quote_agent/
├── README.md               # User guide, credentials, transcripts, security disclaimer
├── app.py                  # CLI loop, runtime lifecycle, graph runner, exit handling
├── init_demo.py            # SQLite reset and seed script (--reset)
├── database.py             # Schema creation, queries, transactional quote persistence, currency
├── models.py               # Pydantic schemas (router, planner) and graph state types
├── auth.py                 # Masked login, credential validation, sanitized identity, policy map
├── tools.py                # Host tools (@runtime_tool), registry factory, executor factory
├── graph.py                # LangGraph StateGraph, router, quote workflow, controlled agent
├── hitl.py                 # Interactive discount prompt and Phase 5 ApprovalHandler
└── data/
    └── .gitkeep            # Data folder placeholder for demo.sqlite3
```

## Module Specifications

### 1. `database.py`

Manages database connections, schema provisioning, queries, and transactional writes using standard library `sqlite3`.

```python
def get_db_path() -> Path:
    """Return the absolute path to the demo SQLite database."""

def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Create a connection with PRAGMA foreign_keys = ON and Row row_factory."""

def init_database(db_path: Path | None = None, *, reset: bool = False) -> None:
    """Initialize SQLite schema, dropping existing tables if reset is True."""

def seed_database(db_path: Path | None = None) -> None:
    """Insert default customers, users, and product catalog records."""

def find_customer_by_query(conn: sqlite3.Connection, query: str) -> dict[str, Any] | None:
    """Search customers table by exact ID, code, or name match."""

def list_active_products(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all active products ordered by SKU."""

def find_product_by_query(conn: sqlite3.Connection, query: str) -> dict[str, Any] | None:
    """Search products table by exact SKU, ID, or substring match."""

def get_quote_by_id(conn: sqlite3.Connection, quote_id: int) -> dict[str, Any] | None:
    """Fetch quote header and line items by quote ID."""

def list_recent_quotes(conn: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    """List recent quotes ordered by creation time descending."""

def persist_quote_transactional(
    conn: sqlite3.Connection,
    *,
    customer_id: int,
    created_by_user_id: int,
    lines: list[tuple[int, int, int]],  # (product_id, quantity, unit_price_cents)
    discount_percent: int,
) -> int:
    """Atomically insert quote header and lines within a single transaction."""
```

#### Monetary and Currency Calculation Helpers

```python
def cents_to_decimal(cents: int) -> Decimal:
    """Convert integer cents to Decimal dollars."""
    return Decimal(cents) / Decimal(100)

def calculate_discount_amount(subtotal_cents: int, discount_percent: int) -> int:
    """Compute discount amount in integer cents using ROUND_HALF_UP."""
    subtotal = Decimal(subtotal_cents)
    pct = Decimal(discount_percent)
    amount = (subtotal * pct / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(amount)

def format_currency(cents: int) -> str:
    """Format integer cents as USD string, e.g. $1,200.00."""
```

### 2. `models.py`

Defines structured Pydantic schemas for LLM routing and planning, alongside LangGraph state definitions.

```python
class IntentDecision(BaseModel):
    """Structured classifier output for top-level user intent."""
    intent: Literal["login", "logout", "quote_create", "agent_request"]
    reasoning: str = ""

class RequestedItem(BaseModel):
    """Product quantity pair requested by the user."""
    product: str
    quantity: int = Field(gt=0, description="Quantity must be at least 1")

class QuoteRequest(BaseModel):
    """Extracted quote creation request parameters."""
    customer: str = Field(min_length=1, description="Customer name or code")
    items: list[RequestedItem] = Field(min_length=1, description="At least one item required")

@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Sanitized user identity stored in host state."""
    user_id: int
    username: str
    display_name: str
    role: Literal["staff", "client"]
    customer_id: int | None

class QuoteLineDraft(TypedDict):
    """Draft quote line with authoritative prices from DB."""
    product_id: int
    sku: str
    name: str
    quantity: int
    unit_price_cents: int
    subtotal_cents: int

class QuoteDraft(TypedDict):
    """Authoritative quote draft calculated host-side."""
    customer_id: int
    customer_name: str
    lines: list[QuoteLineDraft]
    subtotal_cents: int
    discount_percent: int
    discount_amount_cents: int
    total_cents: int

class DemoState(TypedDict, total=False):
    """Host-owned LangGraph state."""
    input: str
    output: str
    authenticated_user: AuthenticatedUser | None
    intent: str
    quote_request: QuoteRequest | None
    quote_draft: QuoteDraft | None
    created_quote_id: int | None
```

### 3. `auth.py`

Encapsulates password masking, credential validation against SQLite, sanitized identity generation, and role-to-policy mapping.

```python
def authenticate_user_interactive(conn: sqlite3.Connection) -> AuthenticatedUser | None:
    """Prompt user for username and masked password (via getpass), validating in SQLite.

    The password variable is deleted immediately after check and never returned.
    """

def get_permission_policy_for_user(user: AuthenticatedUser | None) -> ToolPermissionPolicy:
    """Return the authoritative ToolPermissionPolicy matching the user's role."""
    if user is not None and user.role == "staff":
        return ToolPermissionPolicy(
            frozenset({
                "catalog.read",
                "quote.calculate",
                "customer.read",
                "quote.create",
                "quote.read",
            })
        )
    return ToolPermissionPolicy(
        frozenset({
            "catalog.read",
            "quote.calculate",
        })
    )
```

### 4. `tools.py`

Defines all seven host-managed tools using `@runtime_tool`, the registry factory, and the executor factory with approval configuration.

```python
def create_tool_registry(conn: sqlite3.Connection) -> ToolRegistry:
    """Instantiate and populate a ToolRegistry with all 7 host-managed tools."""

def create_tool_executor(
    registry: ToolRegistry,
    user: AuthenticatedUser | None,
    approval_handler: ApprovalHandler | None = None,
) -> ToolExecutor:
    """Build a ToolExecutor bound with the user's role policy and approval handler."""
```

#### Tool Definitions:
- `list_products()`: reads active products from SQLite.
- `find_product(query: str)`: matches product by SKU or name.
- `calculate_quote(items: list[dict[str, int]])`: re-reads authoritative prices, computes line subtotals and sum subtotal.
- `find_customer(query: str)`: matches customer by code or name (staff only).
- `create_quote(customer_id: int, items: list[dict[str, int]], discount_percent: int)`: requires write side-effect approval; executes `persist_quote_transactional`.
- `list_quotes(limit: int = 10)`: returns newest quotes (staff only).
- `get_quote(quote_id: int)`: returns full quote detail with lines (staff only).

### 5. `hitl.py`

Contains the interactive human-in-the-loop handlers for discount input and tool persistence approval.

```python
def prompt_discount_interactive(subtotal_cents: int) -> int:
    """Prompt the user for a discount percentage (0..30) in the CLI.

    Defaults to 0 on empty input; rejects and re-prompts invalid numbers.
    """

class ConsoleApprovalHandler(ApprovalHandler):
    """Phase 5 ApprovalHandler prompting the user interactively on stdout/stdin."""

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        """Render action details and ask for explicit [y/N] confirmation."""
```

### 6. `graph.py`

Compiles the LangGraph `StateGraph` combining the deterministic quote workflow with the controlled agent branch.

```mermaid
flowchart TD
    START([START]) --> intent_router[intent_router]

    intent_router -->|login| login_hitl[login_hitl]
    intent_router -->|logout| clear_auth[clear_auth]
    intent_router -->|agent_request| controlled_agent[controlled_agent]
    intent_router -->|quote_create| auth_guard[auth_guard]

    auth_guard -->|authorized staff| quote_planner[quote_planner]
    auth_guard -->|denied client/anon| final_output[final_output]

    quote_planner --> resolve_quote_data[resolve_quote_data]
    resolve_quote_data --> discount_hitl[discount_hitl]
    discount_hitl --> create_quote_tool[create_quote_tool + approval]
    create_quote_tool --> final_output

    login_hitl --> final_output
    clear_auth --> final_output
    controlled_agent --> final_output

    final_output --> END([END])
```

#### Node Responsibilities:
- `intent_router`: calls structured model with `IntentDecision` schema.
- `login_hitl`: executes `authenticate_user_interactive` and assigns `authenticated_user`.
- `clear_auth`: clears `authenticated_user` to `None`.
- `auth_guard`: checks `authenticated_user.role == "staff"`. If not, sets error output and routes to `final_output`.
- `quote_planner`: calls structured model with `QuoteRequest` schema to extract customer name and items.
- `resolve_quote_data`: resolves customer ID, product IDs, and re-reads DB prices to build `QuoteDraft`.
- `discount_hitl`: prompts user for discount (0–30%) and calculates `discount_amount_cents` and `total_cents`.
- `create_quote_tool`: invokes `create_quote` tool via `ToolExecutor` (triggering `ConsoleApprovalHandler` for final confirmation).
- `controlled_agent`: executes `RuntimeModel.with_tools(registry, executor)` on catalog/quote read inquiries.
- `final_output`: formats presentation message for the CLI.

### 7. `app.py`

Interactive CLI entrypoint:
- Checks if database exists; suggests running `init_demo.py --reset` if missing.
- Sets up `ObservabilityConfig` with `PayloadMode.METADATA_ONLY`.
- Runs async event loop for interactive user interaction.
- Intercepts `exit` / `quit` commands deterministically.
- Passes input to compiled graph, preserves `authenticated_user` between loop iterations, and prints formatted output.

## Security and Invariant Summary

| Security Boundary | Demonstrated Mechanism |
|---|---|
| Credential Masking | `getpass.getpass()` suppresses echo; password discarded immediately. |
| Zero Credential Leakage | Passwords never placed into graph state, inputs, events, or logs. |
| Dual-Layer Authorization | LangGraph `auth_guard` + host `ToolPermissionPolicy` in `ToolExecutor`. |
| Pricing Authority | Model monetary values ignored; DB prices and Decimal arithmetic enforced. |
| Discount Guard | Hard limit `0..30%` validated host-side; defaults to `0%`. |
| Transactional Integrity | SQLite atomic transaction (`BEGIN ... COMMIT`) with rollback on denial. |
| Controlled Agent Sandboxing | Tools strictly bounded to catalog/read; no OS, shell, or raw SQL access. |
| Observability Safety | `PayloadMode.METADATA_ONLY` prevents telemetry data leakage. |
