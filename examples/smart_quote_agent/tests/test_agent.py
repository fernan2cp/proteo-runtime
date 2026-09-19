"""Comprehensive audit and hardening test suite for Smart Quote Agent.

This module validates all 23 audit points required by the architectural audit:
1. Deterministic router recognizes unequivocal commands without LLM.
2. Ambiguous routing invokes structured low-level classifier.
3. Help/capability query reaches controlled LLM path (not hardcoded).
4. structured_model and controlled_agent_model are distinct bindings.
5. Every model binding uses level "low".
6. Controlled agent binds tools without CapabilityError.
7. Runtime enables experimental_dynamic_tools=True.
8. Controlled agent registry never exposes create_quote.
9. Anonymous cannot create persisted quotes.
10. Client cannot create persisted quotes.
11. Staff can enter quote workflow.
12. Missing customer/items cannot be hallucinated into valid draft.
13. Discount default is 0 and range is 0..30.
14. Final approval denial writes nothing.
15. Final approval success writes header + all lines.
16. Prices are re-read authoritatively before persistence.
17. Quote creation failure is not reported as ToolResult success.
18. Quote list/read remains staff-only.
19. Repeated direct tool calls use unique call IDs and executor cleanup.
20. Ambiguous customer/product match does not select arbitrarily.
21. Login password never appears in graph state.
22. Custom test input functions do not block on builtin console input.
23. Live-model exceptions are not silently converted into hardcoded fallback responses.
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

# Ensure examples/smart_quote_agent is on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from app import _run_repl_loop  # noqa: E402
from auth import (  # noqa: E402
    authenticate_user_interactive,
)
from database import (  # noqa: E402
    find_customer_by_query,
    find_product_by_query,
    get_connection,
    init_database,
    persist_quote_transactional,
    seed_database,
)
from graph import (  # noqa: E402
    _apply_quote_turn,
    _draft_matches_workflow,
    _request_from_workflow,
    _workflow_from_request,
    allowed_actions,
    classify_intent_heuristic,
    create_demo_graph,
    detect_language,
    resolve_language,
)
from hitl import ConsoleApprovalHandler, prompt_discount_interactive  # noqa: E402
from models import (  # noqa: E402
    AddItemOperation,
    AuthenticatedUser,
    DemoState,
    IntentDecision,
    QuoteDraft,
    QuotePatch,
    QuoteRequest,
    QuoteWorkflowItem,
    QuoteWorkflowState,
    RemoveItemOperation,
    ReplaceItemOperation,
    RequestedItem,
    SetCustomerOperation,
    SetQuantityOperation,
    TurnDecision,
)
from session import (  # noqa: E402
    AgentSessionManager,
    format_agent_instructions,
)
from tools import (  # noqa: E402
    create_tool_executor,
    get_agent_tool_registry,
    get_quote_write_registry,
)

from proteo_runtime.core.errors import (  # noqa: E402
    AgentRuntimeError,
    SessionNotFoundError,
    TransportError,
)
from proteo_runtime.core.model import RuntimeModel  # noqa: E402
from proteo_runtime.core.profiles import LogicalLevel  # noqa: E402
from proteo_runtime.core.task import RuntimeTask, TaskState  # noqa: E402
from proteo_runtime.providers.codex.runtime import CodexRuntime  # noqa: E402
from proteo_runtime.testing import FakeRuntime, FakeTurn  # noqa: E402
from proteo_runtime.tools import (  # noqa: E402
    ApprovalDecision,
    ApprovalRequest,
    ToolRequest,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a temporary initialized and seeded SQLite database.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        Path to the temporary SQLite database file.
    """
    db_file = tmp_path / "test_demo.sqlite3"
    init_database(db_file)
    seed_database(db_file)
    return db_file


@pytest.fixture
def db_conn(temp_db: Path) -> Generator[sqlite3.Connection, None, None]:
    """Provide an open sqlite3 connection to the temporary database.

    Args:
        temp_db: Path fixture to temporary database.

    Yields:
        Configured sqlite3.Connection.
    """
    conn = get_connection(temp_db)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def staff_user() -> AuthenticatedUser:
    """Provide a valid staff user context fixture.

    Returns:
        AuthenticatedUser with staff role.
    """
    return AuthenticatedUser(
        user_id=1,
        username="staff",
        display_name="Demo Staff",
        role="staff",
    )


@pytest.fixture
def client_user() -> AuthenticatedUser:
    """Provide a valid client user context fixture.

    Returns:
        AuthenticatedUser with client role.
    """
    return AuthenticatedUser(
        user_id=2,
        username="client1",
        display_name="Client 1",
        role="client",
        customer_id=1,
    )


def test_point_01_deterministic_router_unequivocal_commands() -> None:
    """Validate deterministic routing handles unequivocal commands without LLM."""
    assert classify_intent_heuristic("login") == "login"
    assert classify_intent_heuristic("iniciar sesion") == "login"
    assert classify_intent_heuristic("iniciar sesión") == "login"
    assert classify_intent_heuristic("logout") == "logout"
    assert classify_intent_heuristic("cerrar sesion") == "logout"
    assert classify_intent_heuristic("create quote") == "quote_create"
    assert classify_intent_heuristic("crear cotizacion") == "quote_create"
    assert classify_intent_heuristic("nueva cotizacion") == "quote_create"
    assert classify_intent_heuristic("presupuesto para Globex") == "quote_create"
    assert classify_intent_heuristic("products") == "catalog_query"
    assert classify_intent_heuristic("catalogo") == "catalog_query"
    assert classify_intent_heuristic("help") == "help"
    assert classify_intent_heuristic("ayuda") == "help"
    assert classify_intent_heuristic("hello") == "help"
    assert classify_intent_heuristic("hola") == "help"
    assert classify_intent_heuristic("show quotes") == "quote_history"


@pytest.mark.asyncio
async def test_point_02_ambiguous_routing_invokes_structured_classifier(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate ambiguous requests return None in heuristic and invoke structured model."""
    ambiguous_input = "I want to inspect laptop prices and check quotes"
    assert classify_intent_heuristic(ambiguous_input) is None

    structured_runtime = FakeRuntime(
        turns=[FakeTurn(value=IntentDecision(intent="catalog_query").model_dump_json())]
    )
    agent_runtime = FakeRuntime(turns=[FakeTurn(value="Agent response")])

    structured_model = structured_runtime.model(profile="structured", level="low")
    registry = get_agent_tool_registry(db_conn, staff_user)
    task = await agent_runtime.task(
        profile="controlled_agent",
        level="low",
        instructions="Test agent",
        registry=registry,
    )

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_model,
        context_agent=task,
    )

    state: DemoState = {
        "input": ambiguous_input,
        "authenticated_user": staff_user,
    }
    result = await graph.ainvoke(state)
    assert result.get("intent") == "catalog_query"
    assert result.get("action_allowed") is True


@pytest.mark.asyncio
async def test_point_03_help_capability_handled_host_side_without_controlled_agent(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate capability questions receive a deterministic host response without controlled LLM."""
    help_query = "What can I do with this agent?"
    assert classify_intent_heuristic(help_query) is None

    structured_runtime = FakeRuntime(
        turns=[FakeTurn(value=IntentDecision(intent="help").model_dump_json())]
    )

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        context_agent=None,
    )

    state: DemoState = {
        "input": help_query,
        "authenticated_user": staff_user,
    }
    result = await graph.ainvoke(state)
    assert result.get("intent") == "help"
    assert result.get("action_allowed") is True
    output = result.get("output", "")
    assert "consult products and prices" in output.lower() or "create quotes" in output.lower()


@pytest.mark.asyncio
async def test_point_04_distinct_model_bindings_for_structured_and_controlled(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate structured_model and controlled_agent task have distinct profile bindings."""
    runtime = FakeRuntime()
    structured = runtime.model(profile="structured", level="low")
    registry = get_agent_tool_registry(db_conn, staff_user)
    task = await runtime.task(
        profile="controlled_agent",
        level="low",
        instructions="Test agent",
        registry=registry,
    )

    assert isinstance(structured, RuntimeModel)
    assert isinstance(task, RuntimeTask)
    assert structured.profile == "structured"
    assert getattr(task, "_profile", None) == "controlled_agent"


@pytest.mark.asyncio
async def test_point_05_every_model_binding_uses_level_low(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate all model and task bindings are explicitly configured with logical level 'low'."""
    runtime = FakeRuntime()
    structured = runtime.model(profile="structured", level="low")
    registry = get_agent_tool_registry(db_conn, staff_user)
    task = await runtime.task(
        profile="controlled_agent",
        level="low",
        instructions="Test agent",
        registry=registry,
    )

    assert structured.level in (LogicalLevel.LOW, "low")
    assert getattr(task, "_level", None) in (LogicalLevel.LOW, "low")


@pytest.mark.asyncio
async def test_point_06_controlled_agent_binds_tools_without_capability_error(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate controlled_agent task with tools executes without CapabilityError."""
    registry = get_agent_tool_registry(db_conn, staff_user)
    executor = create_tool_executor(registry, staff_user)

    fake_runtime = FakeRuntime(
        turns=[
            FakeTurn(
                tool_calls=(("call_1", "list_products", {}),),
            ),
            FakeTurn(value="Executed list products tool"),
        ]
    )

    task = await fake_runtime.task(
        profile="controlled_agent",
        level="low",
        instructions="Test agent",
        registry=registry,
        executor=executor,
    )
    result = await task.ainvoke("Listar productos")
    assert result.value is not None


def test_point_07_runtime_enables_experimental_dynamic_tools() -> None:
    """Validate CodexRuntime enables experimental_dynamic_tools without error."""
    codex_runtime = CodexRuntime(experimental_dynamic_tools=True)
    assert codex_runtime is not None


def test_point_08_controlled_agent_registry_never_exposes_create_quote(
    db_conn: sqlite3.Connection,
    client_user: AuthenticatedUser,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate conversational agent registry never exposes create_quote to any user."""
    for user in (None, client_user, staff_user):
        registry = get_agent_tool_registry(db_conn, user)
        names = {d.name for d in registry.definitions()}
        assert "create_quote" not in names, f"create_quote leaked to {user}"


@pytest.mark.asyncio
async def test_point_09_anonymous_cannot_create_persisted_quotes(
    db_conn: sqlite3.Connection,
) -> None:
    """Validate anonymous user is blocked from entering quote creation workflow."""
    structured_runtime = FakeRuntime(
        turns=[FakeTurn(value=IntentDecision(intent="quote_create").model_dump_json())]
    )

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        context_agent=None,
    )

    state: DemoState = {
        "input": "create quote",
        "authenticated_user": None,
    }
    result = await graph.ainvoke(state)

    assert result.get("quote_authorized") is False
    assert "Access denied" in result.get("output", "")

    cur = db_conn.execute("SELECT count(*) FROM quotes;")
    assert cur.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_point_10_client_cannot_create_persisted_quotes(
    db_conn: sqlite3.Connection, client_user: AuthenticatedUser
) -> None:
    """Validate client user is blocked from entering quote creation workflow."""
    structured_runtime = FakeRuntime(
        turns=[FakeTurn(value=IntentDecision(intent="quote_create").model_dump_json())]
    )

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        context_agent=None,
    )

    state: DemoState = {
        "input": "create quote",
        "authenticated_user": client_user,
    }
    result = await graph.ainvoke(state)

    assert result.get("quote_authorized") is False
    assert "Access denied" in result.get("output", "")

    cur = db_conn.execute("SELECT count(*) FROM quotes;")
    assert cur.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_point_11_staff_can_enter_quote_workflow(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate staff user is authorized to enter quote creation workflow."""
    structured_runtime = FakeRuntime(
        turns=[
            FakeTurn(
                value=QuoteRequest(
                    customer="Acme Corp.",
                    items=[RequestedItem(product="Notebook Pro", quantity=2)],
                ).model_dump_json()
            ),
        ]
    )

    captured_requests: list[ApprovalRequest] = []

    class ImmediateApproval(ConsoleApprovalHandler):
        async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
            captured_requests.append(request)
            return ApprovalDecision.APPROVE

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        context_agent=None,
        approval_handler=ImmediateApproval(),
        discount_prompter=lambda _: 0,
        quote_reviewer=lambda _: None,
    )

    state: DemoState = {
        "input": "crear cotizacion para Acme Corp. con 2 Notebook Pro",
        "authenticated_user": staff_user,
    }
    result = await graph.ainvoke(state)

    assert result.get("quote_authorized") is True
    assert result.get("created_quote_id") is not None
    assert len(captured_requests) == 1
    # Verify complete 32-character UUID hex is used (not truncated to 8 characters)
    assert captured_requests[0].invocation_id.startswith("quote-inv-")
    assert len(captured_requests[0].invocation_id) == len("quote-inv-") + 32
    assert captured_requests[0].call_id.startswith("quote-call-")
    assert len(captured_requests[0].call_id) == len("quote-call-") + 32


@pytest.mark.asyncio
async def test_point_12_missing_customer_or_items_cannot_hallucinate_draft(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate missing customer or items prompts for clarification rather than hallucinating."""
    structured_runtime = FakeRuntime(
        turns=[
            FakeTurn(value=QuoteRequest(customer=None, items=[]).model_dump_json()),
        ]
    )

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        context_agent=None,
    )

    state: DemoState = {
        "input": "create quote",
        "authenticated_user": staff_user,
    }
    result = await graph.ainvoke(state)

    assert result.get("quote_draft") is None
    assert "Could not extract quote details" in result.get("output", "")


def test_point_13_discount_default_zero_and_range_validation() -> None:
    """Validate discount prompt defaults to 0 and enforces range 0..30."""
    # When user answers 'n' to apply discount, returns 0
    assert prompt_discount_interactive(10000, input_func=lambda _: "n") == 0

    # When user answers 'y' and enters empty, defaults to 0
    inputs_empty = iter(["y", ""])
    assert prompt_discount_interactive(10000, input_func=lambda _: next(inputs_empty)) == 0

    # Valid percentage
    inputs_valid = iter(["y", "15"])
    assert prompt_discount_interactive(10000, input_func=lambda _: next(inputs_valid)) == 15

    # Out of range clamped / reprompted
    inputs_range = iter(["y", "45", "-5", "10"])
    assert prompt_discount_interactive(10000, input_func=lambda _: next(inputs_range)) == 10


@pytest.mark.asyncio
async def test_point_14_final_approval_denial_writes_nothing(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate quote is not saved if user denies final HITL confirmation."""
    structured_runtime = FakeRuntime(
        turns=[
            FakeTurn(
                value=QuoteRequest(
                    customer="Acme Corp.",
                    items=[RequestedItem(product="Notebook Pro", quantity=1)],
                ).model_dump_json()
            ),
        ]
    )

    class DenialApproval(ConsoleApprovalHandler):
        async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
            return ApprovalDecision.DENY

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        context_agent=None,
        approval_handler=DenialApproval(),
        discount_prompter=lambda _: 0,
        quote_reviewer=lambda _: None,
    )

    state: DemoState = {
        "input": "crear cotizacion para Acme Corp. con 1 Notebook Pro",
        "authenticated_user": staff_user,
    }
    result = await graph.ainvoke(state)

    assert result.get("created_quote_id") is None
    assert "rechazó la creación" in result.get("output", "").lower()
    assert result.get("quote_workflow") is None
    assert result.get("quote_draft") is None
    assert result.get("quote_patch") is None
    assert result.get("quote_request") is None
    assert result.get("pending_quote_request") is None

    cur = db_conn.execute("SELECT count(*) FROM quotes;")
    assert cur.fetchone()[0] == 0


def test_point_15_final_approval_success_writes_header_and_lines(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate approved quote persists both header and all line items atomically."""
    lines = [(1, 2), (2, 3)]  # (product_id, quantity)

    quote_id = persist_quote_transactional(
        conn=db_conn,
        customer_id=1,
        created_by_user_id=staff_user.user_id,
        lines=lines,
        discount_percent=10,
    )

    assert quote_id > 0

    header = db_conn.execute("SELECT * FROM quotes WHERE id = ?;", (quote_id,)).fetchone()
    assert header is not None
    assert header["customer_id"] == 1
    assert header["discount_percent"] == 10

    line_rows = db_conn.execute(
        "SELECT * FROM quote_lines WHERE quote_id = ? ORDER BY id ASC;", (quote_id,)
    ).fetchall()
    assert len(line_rows) == 2
    assert line_rows[0]["product_id"] == 1
    assert line_rows[0]["quantity"] == 2
    assert line_rows[1]["product_id"] == 2
    assert line_rows[1]["quantity"] == 3


def test_point_16_prices_reread_authoritatively_before_persistence(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate persistence re-reads catalog prices authoritatively and ignores altered prices."""
    prod_row = db_conn.execute("SELECT unit_price_cents FROM products WHERE id = 1;").fetchone()
    catalog_price_cents = int(prod_row["unit_price_cents"])
    assert catalog_price_cents > 0

    quote_id = persist_quote_transactional(
        conn=db_conn,
        customer_id=1,
        created_by_user_id=staff_user.user_id,
        lines=[(1, 2)],
        discount_percent=0,
    )

    line = db_conn.execute(
        "SELECT unit_price_cents, subtotal_cents FROM quote_lines WHERE quote_id = ?;",
        (quote_id,),
    ).fetchone()
    assert line["unit_price_cents"] == catalog_price_cents
    assert line["subtotal_cents"] == catalog_price_cents * 2


def test_point_17_quote_creation_failure_not_reported_as_success(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate quote creation failure raises an exception and is never reported as success."""
    with pytest.raises(ValueError, match="Product 999999 not found or inactive"):
        persist_quote_transactional(
            conn=db_conn,
            customer_id=1,
            created_by_user_id=staff_user.user_id,
            lines=[(999999, 1)],
            discount_percent=0,
        )


def test_point_18_quote_list_read_remains_staff_only(
    db_conn: sqlite3.Connection,
    client_user: AuthenticatedUser,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate quote list/read tools are exposed exclusively to staff users."""
    anon_reg = get_agent_tool_registry(db_conn, None)
    anon_names = {d.name for d in anon_reg.definitions()}
    assert "list_quotes" not in anon_names
    assert "get_quote" not in anon_names

    client_reg = get_agent_tool_registry(db_conn, client_user)
    client_names = {d.name for d in client_reg.definitions()}
    assert "list_quotes" not in client_names
    assert "get_quote" not in client_names
    assert "list_customers" not in client_names

    staff_reg = get_agent_tool_registry(db_conn, staff_user)
    staff_names = {d.name for d in staff_reg.definitions()}
    assert "list_quotes" in staff_names
    assert "get_quote" in staff_names
    assert "list_customers" in staff_names


@pytest.mark.asyncio
async def test_hardening_list_customers_is_bounded_and_returns_minimal_fields(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Verify the authorized directory caps results and exposes only safe identifiers."""
    registry = get_agent_tool_registry(db_conn, staff_user)
    executor = create_tool_executor(registry, staff_user)
    request = ToolRequest(
        "customer-list-inv", "customer-list-call", "list_customers", {"limit": 500}
    )
    try:
        result = await executor.execute(request)
    finally:
        executor.end_invocation("customer-list-inv")

    assert result.success
    customers = result.as_provider_value()
    assert len(customers) == 4
    assert all(set(customer) == {"id", "code", "name"} for customer in customers)


@pytest.mark.asyncio
async def test_point_19_tool_calls_use_unique_ids_and_executor_cleanup(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate tool invocations generate unique IDs and invoke executor.end_invocation."""
    registry = get_quote_write_registry(db_conn, staff_user)

    class AutoApprove(ConsoleApprovalHandler):
        async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
            return ApprovalDecision.APPROVE

    executor = create_tool_executor(
        registry,
        staff_user,
        approval_handler=AutoApprove(),
    )

    req1 = ToolRequest(
        "inv-1",
        "call-1",
        "create_quote",
        {"customer_id": 1, "items": [{"product_id": 1, "quantity": 1}], "discount_percent": 0},
    )
    req2 = ToolRequest(
        "inv-2",
        "call-2",
        "create_quote",
        {"customer_id": 1, "items": [{"product_id": 1, "quantity": 1}], "discount_percent": 0},
    )

    try:
        res1 = await executor.execute(req1)
    finally:
        executor.end_invocation("inv-1")

    try:
        res2 = await executor.execute(req2)
    finally:
        executor.end_invocation("inv-2")

    assert res1.success
    assert res2.success
    val1 = res1.as_provider_value()
    val2 = res2.as_provider_value()
    assert val1["quote_id"] != val2["quote_id"]
    assert executor._calls == {}


def test_point_20_ambiguous_customer_and_product_matches_no_arbitrary_selection(
    db_conn: sqlite3.Connection,
) -> None:
    """Validate ambiguous search queries return candidate lists without arbitrary selection."""
    db_conn.execute(
        "INSERT INTO customers (id, code, name) VALUES (10, 'dup1', 'Omega Solutions Alpha');"
    )
    db_conn.execute(
        "INSERT INTO customers (id, code, name) VALUES (11, 'dup2', 'Omega Solutions Beta');"
    )
    db_conn.commit()

    res = find_customer_by_query(db_conn, "Omega Solutions")
    assert res is not None
    assert res.get("ambiguous") is True
    assert len(res.get("candidates", [])) == 2

    exact_res = find_customer_by_query(db_conn, "dup1")
    assert exact_res is not None
    assert exact_res.get("id") == 10

    prod_amb = find_product_by_query(db_conn, "Monitor")
    assert prod_amb is not None
    if prod_amb.get("ambiguous"):
        assert len(prod_amb.get("candidates", [])) >= 2


def test_point_21_login_password_never_in_graph_state(staff_user: AuthenticatedUser) -> None:
    """Validate login password is never stored or tracked in DemoState."""
    fields = DemoState.__annotations__.keys()
    assert "password" not in fields

    state: DemoState = {
        "input": "login staff 1234",
        "authenticated_user": staff_user,
    }
    assert "password" not in state


def test_point_22_custom_test_input_functions_do_not_block_console(
    db_conn: sqlite3.Connection,
) -> None:
    """Validate custom input functions run non-interactively without blocking console."""
    prompts: list[str] = []

    def username_input(prompt: str) -> str:
        """Record a localized username prompt and provide a test username."""
        prompts.append(prompt)
        return "staff"

    def password_input(prompt: str) -> str:
        """Record a localized password prompt and provide a test password."""
        prompts.append(prompt)
        return "1234"

    user = authenticate_user_interactive(
        db_conn,
        input_func=username_input,
        getpass_func=password_input,
        language="es",
    )
    assert user is not None
    assert user.username == "staff"
    assert prompts == ["Usuario: ", "Contraseña: "]

    disc = prompt_discount_interactive(10000, input_func=lambda _: "n")
    assert disc == 0


@pytest.mark.asyncio
async def test_point_23_live_model_exceptions_not_silently_swallowed(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate live model runtime exceptions are raised cleanly rather than swallowed."""

    class FailingTask:
        """Test task that always raises TransportError."""

        async def ainvoke(self, input_: Any, **kwargs: Any) -> Any:
            raise TransportError("Codex transport connection failed")

    graph = create_demo_graph(
        conn=db_conn,
        context_agent=FailingTask(),  # type: ignore[arg-type]
    )

    state: DemoState = {
        "input": "catalogo",
        "authenticated_user": staff_user,
    }

    with pytest.raises(AgentRuntimeError, match="Codex transport connection failed"):
        await graph.ainvoke(state)


def test_legacy_model_parameter_removed_from_create_demo_graph() -> None:
    """Validate legacy single-model compatibility parameter was removed from graph factory."""
    import inspect

    sig = inspect.signature(create_demo_graph)
    assert "model" not in sig.parameters
    assert "structured_model" in sig.parameters
    assert "context_agent" in sig.parameters


# =============================================================================
# Scope Containment & Host Policy Tests (20 Audit Requirements)
# =============================================================================


@pytest.mark.asyncio
async def test_scope_01_greeting_resolves_to_help_and_avoids_generic_assistant_claims(
    db_conn: sqlite3.Connection,
) -> None:
    """Validate greeting input resolves to help and never claims generic capabilities.

    Args:
        db_conn: SQLite connection fixture.
    """
    assert classify_intent_heuristic("Hello") == "help"
    assert classify_intent_heuristic("Hola") == "help"

    graph = create_demo_graph(
        conn=db_conn,
        context_agent=None,
    )

    result = await graph.ainvoke({"input": "Hello", "authenticated_user": None})
    output = result.get("output", "").lower()
    assert result.get("intent") == "help"
    assert result.get("action_allowed") is True
    assert any(term in output for term in ("product", "price", "quote", "preview"))
    for generic in ("browse", "internet", "code", "image", "file", "weather", "fastapi"):
        assert generic not in output


@pytest.mark.asyncio
async def test_scope_02_capability_query_returns_role_appropriate_scope(
    db_conn: sqlite3.Connection,
    client_user: AuthenticatedUser,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate capability questions return only role-appropriate application actions.

    Args:
        db_conn: SQLite connection fixture.
        client_user: Authenticated client user fixture.
        staff_user: Authenticated staff user fixture.
    """
    graph = create_demo_graph(
        conn=db_conn,
        context_agent=None,
    )

    # 1. Anonymous user
    res_anon = await graph.ainvoke({"input": "What things could I do?", "authenticated_user": None})
    out_anon = res_anon.get("output", "").lower()
    assert "log in" in out_anon or "login" in out_anon
    assert "create quotes" not in out_anon

    # 2. Client user
    res_client = await graph.ainvoke(
        {"input": "What things could I do?", "authenticated_user": client_user}
    )
    out_client = res_client.get("output", "").lower()
    assert "log out" in out_client or "logout" in out_client
    assert "create quotes" not in out_client

    # 3. Staff user
    res_staff = await graph.ainvoke(
        {"input": "What things could I do?", "authenticated_user": staff_user}
    )
    out_staff = res_staff.get("output", "").lower()
    assert "create quotes" in out_staff or "persisted quotes" in out_staff


@pytest.mark.asyncio
async def test_scope_03_unrelated_query_classifies_as_out_of_scope(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate unrelated general knowledge questions classify as out_of_scope.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    unrelated_input = "How do I implement an API with FastAPI?"
    assert classify_intent_heuristic(unrelated_input) is None

    structured_runtime = FakeRuntime(
        turns=[FakeTurn(value=IntentDecision(intent="out_of_scope").model_dump_json())]
    )
    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        context_agent=None,
    )

    result = await graph.ainvoke({"input": unrelated_input, "authenticated_user": staff_user})
    assert result.get("intent") == "out_of_scope"
    assert result.get("action_allowed") is False


@pytest.mark.asyncio
async def test_scope_04_out_of_scope_never_reaches_controlled_agent(
    db_conn: sqlite3.Connection,
) -> None:
    """Validate out-of-scope requests never invoke the controlled agent LLM.

    Args:
        db_conn: SQLite connection fixture.
    """
    structured_runtime = FakeRuntime(
        turns=[FakeTurn(value=IntentDecision(intent="out_of_scope").model_dump_json())]
    )
    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        context_agent=None,
    )

    result = await graph.ainvoke(
        {"input": "Write me a poem about summer", "authenticated_user": None}
    )
    assert result.get("intent") == "out_of_scope"
    assert result.get("action_allowed") is False
    assert "outside the scope" in result.get("output", "").lower()


@pytest.mark.asyncio
async def test_scope_05_out_of_scope_response_does_not_answer_underlying_question(
    db_conn: sqlite3.Connection,
) -> None:
    """Validate out-of-scope response provides a refusal without answering the topic.

    Args:
        db_conn: SQLite connection fixture.
    """
    structured_runtime = FakeRuntime(
        turns=[FakeTurn(value=IntentDecision(intent="out_of_scope").model_dump_json())]
    )
    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        context_agent=None,
    )

    result = await graph.ainvoke(
        {"input": "How do I implement an API with FastAPI?", "authenticated_user": None}
    )
    output = result.get("output", "")
    assert "outside the scope" in output.lower()
    for forbidden in ("fastapi", "uvicorn", "endpoint", "@app", "def root"):
        assert forbidden not in output.lower()


@pytest.mark.asyncio
async def test_scope_06_ambiguous_supported_requests_invoke_structured_classifier(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate ambiguous requests invoke the low-level structured classifier.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    ambiguous = "Could you check the pricing on available hardware?"
    assert classify_intent_heuristic(ambiguous) is None

    structured_runtime = FakeRuntime(
        turns=[FakeTurn(value=IntentDecision(intent="catalog_query").model_dump_json())]
    )
    agent_runtime = FakeRuntime(turns=[FakeTurn(value="Hardware pricing list")])
    reg = get_agent_tool_registry(db_conn, staff_user)
    task = await agent_runtime.task(
        profile="controlled_agent",
        level="low",
        instructions="Test agent",
        registry=reg,
    )
    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        context_agent=task,
    )

    result = await graph.ainvoke({"input": ambiguous, "authenticated_user": staff_user})
    assert result.get("intent") == "catalog_query"
    assert result.get("action_allowed") is True


@pytest.mark.asyncio
async def test_scope_07_classifier_receives_access_level_and_allowed_actions_context(
    db_conn: sqlite3.Connection,
    client_user: AuthenticatedUser,
) -> None:
    """Validate structured classifier prompt receives access level and allowed action context.

    Args:
        db_conn: SQLite connection fixture.
        client_user: Authenticated client user fixture.
    """
    captured_prompts: list[str] = []
    captured_configs: list[Any] = []

    class InspectingModel:
        """Double that captures input prompt text."""

        def with_structured_output(self, schema: Any) -> Any:
            del schema
            return self

        async def ainvoke(self, input_: Any, **kwargs: Any) -> Any:
            captured_configs.append(kwargs.get("config"))
            for msg in getattr(input_, "messages", ()):
                text = getattr(msg, "text", "")
                if text:
                    captured_prompts.append(text)
            return type("Res", (), {"value": IntentDecision(intent="catalog_query")})()

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=InspectingModel(),  # type: ignore[arg-type]
    )

    await graph.ainvoke(
        {
            "input": "What laptops are currently available?",
            "authenticated_user": client_user,
            "interaction_id": "interaction-router-test",
        }
    )
    assert len(captured_prompts) >= 1
    system_text = captured_prompts[0]
    assert "Current access level: client" in system_text
    assert "Actions currently available for this access level:" in system_text
    assert "out_of_scope" in system_text
    assert len(captured_configs) == 1
    assert captured_configs[0].metadata["interaction_id"] == "interaction-router-test"
    assert captured_configs[0].metadata["stage"] == "intent_router"


def test_scope_08_anonymous_allowed_actions() -> None:
    """Validate anonymous user action policy includes only public actions."""
    assert allowed_actions(None) == frozenset(
        {"login", "help", "acknowledgement", "catalog_query", "quote_preview"}
    )


def test_scope_09_client_allowed_actions_exclude_quote_history_and_create(
    client_user: AuthenticatedUser,
) -> None:
    """Validate client user action policy excludes quote_history and quote_create.

    Args:
        client_user: Authenticated client user fixture.
    """
    actions = allowed_actions(client_user)
    assert "quote_history" not in actions
    assert "quote_create" not in actions
    assert actions == frozenset(
        {"logout", "help", "acknowledgement", "catalog_query", "quote_preview"}
    )


def test_scope_10_staff_allowed_actions_include_quote_history_and_create(
    staff_user: AuthenticatedUser,
) -> None:
    """Validate staff user action policy includes quote_history and quote_create.

    Args:
        staff_user: Authenticated staff user fixture.
    """
    actions = allowed_actions(staff_user)
    assert "quote_history" in actions
    assert "quote_create" in actions
    assert actions == frozenset(
        {
            "logout",
            "help",
            "acknowledgement",
            "catalog_query",
            "quote_preview",
            "quote_history",
            "customer_query",
            "quote_create",
        }
    )


@pytest.mark.asyncio
async def test_scope_11_client_quote_history_recognized_but_denied_host_side(
    db_conn: sqlite3.Connection,
    client_user: AuthenticatedUser,
) -> None:
    """Validate client asking for quote history is recognized as quote_history but denied by host.

    Args:
        db_conn: SQLite connection fixture.
        client_user: Authenticated client user fixture.
    """
    graph = create_demo_graph(
        conn=db_conn,
        context_agent=None,
    )

    result = await graph.ainvoke(
        {"input": "Show the latest quotes", "authenticated_user": client_user}
    )
    assert result.get("intent") == "quote_history"
    assert result.get("action_allowed") is False
    assert "staff only" in result.get("output", "").lower()
    assert "outside the scope" not in result.get("output", "").lower()


@pytest.mark.asyncio
async def test_scope_12_anonymous_and_client_quote_create_denied_before_workflow(
    db_conn: sqlite3.Connection,
    client_user: AuthenticatedUser,
) -> None:
    """Validate quote creation is blocked host-side for anonymous and client users.

    Args:
        db_conn: SQLite connection fixture.
        client_user: Authenticated client user fixture.
    """
    graph = create_demo_graph(conn=db_conn)

    # Anonymous
    res_anon = await graph.ainvoke({"input": "create quote for Globex", "authenticated_user": None})
    assert res_anon.get("intent") == "quote_create"
    assert res_anon.get("action_allowed") is False
    assert res_anon.get("quote_authorized") is False
    assert "access denied" in res_anon.get("output", "").lower()

    # Client
    res_client = await graph.ainvoke(
        {"input": "create quote for Globex", "authenticated_user": client_user}
    )
    assert res_client.get("intent") == "quote_create"
    assert res_client.get("action_allowed") is False
    assert res_client.get("quote_authorized") is False
    assert "access denied" in res_client.get("output", "").lower()


@pytest.mark.asyncio
async def test_scope_13_staff_quote_create_follows_deterministic_write_path(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate staff quote creation proceeds through deterministic workflow nodes.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    graph = create_demo_graph(
        conn=db_conn,
        discount_prompter=lambda _subtotal: 10,
        approval_handler=ConsoleApprovalHandler(input_func=lambda _prompt: "yes"),
        quote_reviewer=lambda _draft: None,
    )

    result = await graph.ainvoke(
        {
            "input": "create quote for Globex for 2 Notebook Pro",
            "authenticated_user": staff_user,
        }
    )
    assert result.get("intent") == "quote_create"
    assert result.get("action_allowed") is True
    assert result.get("quote_authorized") is True
    assert result.get("created_quote_id") is not None
    assert "[SUCCESS]" in result.get("output", "")


def test_scope_14_create_quote_absent_from_every_conversational_registry(
    db_conn: sqlite3.Connection,
    client_user: AuthenticatedUser,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate create_quote is never exposed in any conversational tool registry.

    Args:
        db_conn: SQLite connection fixture.
        client_user: Authenticated client user fixture.
        staff_user: Authenticated staff user fixture.
    """
    for user in (None, client_user, staff_user):
        reg = get_agent_tool_registry(db_conn, user)
        names = {d.name for d in reg.definitions()}
        assert "create_quote" not in names


@pytest.mark.asyncio
async def test_scope_15_supported_catalog_queries_reach_controlled_agent(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate supported catalog inquiries reach controlled agent and execute tools.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    agent_runtime = FakeRuntime(
        turns=[
            FakeTurn(
                value="Notebook Pro and Wireless Mouse in catalog",
                tool_calls=(("c1", "list_products", {}),),
            ),
        ]
    )
    reg = get_agent_tool_registry(db_conn, staff_user)
    task = await agent_runtime.task(
        profile="controlled_agent",
        level="low",
        instructions="Test agent",
        registry=reg,
    )
    graph = create_demo_graph(
        conn=db_conn,
        context_agent=task,
    )

    result = await graph.ainvoke({"input": "products", "authenticated_user": staff_user})
    assert result.get("intent") == "catalog_query"
    assert result.get("action_allowed") is True
    assert "Notebook Pro" in result.get("output", "")


@pytest.mark.asyncio
async def test_scope_16_supported_quote_preview_reaches_controlled_agent(
    db_conn: sqlite3.Connection,
) -> None:
    """Validate quote preview calculations reach controlled agent and tool executor.

    Args:
        db_conn: SQLite connection fixture.
    """
    agent_runtime = FakeRuntime(
        turns=[
            FakeTurn(
                value="Subtotal is $2,400.00",
                tool_calls=(
                    (
                        "c1",
                        "calculate_quote",
                        {"items": [{"product_id": 1, "quantity": 2}], "discount_percent": 0},
                    ),
                ),
            ),
        ]
    )
    reg = get_agent_tool_registry(db_conn, None)
    task = await agent_runtime.task(
        profile="controlled_agent",
        level="low",
        instructions="Test agent",
        registry=reg,
    )
    graph = create_demo_graph(
        conn=db_conn,
        structured_model=FakeRuntime(
            turns=[FakeTurn(value=IntentDecision(intent="quote_preview").model_dump_json())]
        ).model(profile="structured", level="low"),
        context_agent=task,
    )

    result = await graph.ainvoke(
        {"input": "Calculate price preview for 2 laptops", "authenticated_user": None}
    )
    assert result.get("intent") == "quote_preview"
    assert result.get("action_allowed") is True
    assert "Subtotal is $2,400.00" in result.get("output", "")


@pytest.mark.asyncio
async def test_scope_17_staff_quote_history_reaches_controlled_agent_with_read_tools(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate staff quote history inquiries reach controlled agent and read tools.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    agent_runtime = FakeRuntime(
        turns=[
            FakeTurn(
                value="Quote #1 for Globex",
                tool_calls=(("c1", "list_quotes", {"limit": 5}),),
            ),
        ]
    )
    reg = get_agent_tool_registry(db_conn, staff_user)
    task = await agent_runtime.task(
        profile="controlled_agent",
        level="low",
        instructions="Test agent",
        registry=reg,
    )
    graph = create_demo_graph(
        conn=db_conn,
        context_agent=task,
    )

    result = await graph.ainvoke({"input": "show quotes", "authenticated_user": staff_user})
    assert result.get("intent") == "quote_history"
    assert result.get("action_allowed") is True
    assert "Quote #1 for Globex" in result.get("output", "")


@pytest.mark.asyncio
async def test_scope_18_controlled_agent_system_instruction_prohibits_generic_capabilities(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate controlled agent system instruction explicitly disclaims generic capabilities.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    sys_prompt = format_agent_instructions(staff_user)
    assert "You are ONLY the Smart Quote Agent for this application." in sys_prompt
    assert "Current role: staff" in sys_prompt
    assert "internet browsing" in sys_prompt
    assert "code execution/editing" in sys_prompt
    assert "image generation" in sys_prompt
    assert "filesystem access" in sys_prompt

    fake_runtime = FakeRuntime(turns=[FakeTurn(value="Inspected response")])
    session_mgr = AgentSessionManager(fake_runtime, db_conn)
    task = await session_mgr.get_or_create_task(staff_user)
    try:
        assert task.instructions is not None
        assert "You are ONLY the Smart Quote Agent for this application." in task.instructions
        assert "Current role: staff" in task.instructions
    finally:
        await session_mgr.close()


@pytest.mark.asyncio
async def test_scope_19_offline_mode_follows_same_scope_semantics(
    db_conn: sqlite3.Connection,
    client_user: AuthenticatedUser,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate offline mode enforces identical scope and containment rules.

    Args:
        db_conn: SQLite connection fixture.
        client_user: Authenticated client user fixture.
        staff_user: Authenticated staff user fixture.
    """
    graph = create_demo_graph(conn=db_conn, structured_model=None, context_agent=None)

    # 1. Help query
    res_help = await graph.ainvoke({"input": "help", "authenticated_user": None})
    assert res_help.get("intent") == "help"
    assert "consult products and prices" in res_help.get("output", "").lower()

    # 2. Out of scope
    res_oos = await graph.ainvoke(
        {"input": "How do I build a nuclear reactor?", "authenticated_user": None}
    )
    assert res_oos.get("intent") == "out_of_scope"
    assert "outside the scope" in res_oos.get("output", "").lower()

    # 3. Client denied quote history
    res_client = await graph.ainvoke({"input": "show quotes", "authenticated_user": client_user})
    assert res_client.get("intent") == "quote_history"
    assert "staff only" in res_client.get("output", "").lower()

    # 4. Staff allowed quote history
    res_staff = await graph.ainvoke({"input": "show quotes", "authenticated_user": staff_user})
    assert res_staff.get("intent") == "quote_history"
    assert "quotes" in res_staff.get("output", "").lower()


@pytest.mark.asyncio
async def test_hardening_offline_quote_preview_uses_authoritative_prices(
    db_conn: sqlite3.Connection,
) -> None:
    """Calculate explicit preview items offline without persisting a quote."""
    graph = create_demo_graph(conn=db_conn, structured_model=None, context_agent=None)
    result = await graph.ainvoke(
        {
            "input": "calcular presupuesto preliminar de 2 Notebook Pro y 3 mouses",
            "authenticated_user": None,
        }
    )

    assert result.get("intent") == "quote_preview"
    assert "Notebook Pro" in result.get("output", "")
    assert "Wireless Mouse" in result.get("output", "")
    assert "Subtotal: $2,520.00" in result.get("output", "")
    assert "no se guarda" in result.get("output", "").lower()
    assert db_conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_hardening_offline_quote_preview_disambiguates_generic_notebook(
    db_conn: sqlite3.Connection,
) -> None:
    """Ask which catalog item is intended instead of choosing a notebook arbitrarily."""
    graph = create_demo_graph(conn=db_conn, structured_model=None, context_agent=None)
    result = await graph.ainvoke(
        {
            "input": "calcular presupuesto preliminar de 2 notebooks",
            "authenticated_user": None,
        }
    )

    output = result.get("output", "")
    assert "Notebook Air (NB-AIR)" in output
    assert "Notebook Pro (NB-PRO)" in output
    assert db_conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("preview_request", "unknown_product"),
    (
        ("calcular presupuesto preliminar de 2 docks y 1 desk", "desk"),
        ("calcular presupuesto preliminar de 2 notebook pro desk", "desk"),
        ("calcular presupuesto preliminar de 2 notebook pro foo", "foo"),
    ),
)
@pytest.mark.asyncio
async def test_hardening_offline_quote_preview_rejects_unresolved_lines(
    db_conn: sqlite3.Connection,
    preview_request: str,
    unknown_product: str,
) -> None:
    """Never return a partial subtotal when any requested product is unknown."""
    graph = create_demo_graph(conn=db_conn, structured_model=None, context_agent=None)
    result = await graph.ainvoke(
        {
            "input": preview_request,
            "authenticated_user": None,
        }
    )

    output = result.get("output", "")
    assert f"No reconozco '{unknown_product}'" in output
    assert "no calculé el subtotal" in output.lower()
    assert "USB-C Dock" not in output
    assert db_conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_hardening_offline_quote_preview_resolves_exact_sku(
    db_conn: sqlite3.Connection,
) -> None:
    """Resolve explicit catalog SKUs exactly in offline preview requests."""
    graph = create_demo_graph(conn=db_conn, structured_model=None, context_agent=None)
    result = await graph.ainvoke(
        {
            "input": "calcular presupuesto preliminar de 2 DOCK-USBC",
            "authenticated_user": None,
        }
    )

    output = result.get("output", "")
    assert "USB-C Dock" in output
    assert "Subtotal: $300.00" in output
    assert db_conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_hardening_offline_quote_preview_accepts_natural_prepositions(
    db_conn: sqlite3.Connection,
) -> None:
    """Accept common Spanish articles and prepositions around explicit catalog items."""
    graph = create_demo_graph(conn=db_conn, structured_model=None, context_agent=None)
    result = await graph.ainvoke(
        {
            "input": "calcula el presupuesto preliminar para 2 docks",
            "authenticated_user": None,
        }
    )

    assert result.get("intent") == "quote_preview"
    assert "USB-C Dock" in result.get("output", "")
    assert "Subtotal: $300.00" in result.get("output", "")


@pytest.mark.parametrize(
    "preview_request",
    (
        "calcular presupuesto preliminar de dock x2",
        "calcular presupuesto preliminar de dock 2",
    ),
)
@pytest.mark.asyncio
async def test_hardening_offline_quote_preview_reads_trailing_quantity(
    db_conn: sqlite3.Connection,
    preview_request: str,
) -> None:
    """Read a quantity after the product instead of silently defaulting to one."""
    graph = create_demo_graph(conn=db_conn, structured_model=None, context_agent=None)
    result = await graph.ainvoke({"input": preview_request, "authenticated_user": None})

    assert "Subtotal: $300.00" in result.get("output", "")


@pytest.mark.asyncio
async def test_hardening_offline_quote_preview_reads_quantity_before_courtesy(
    db_conn: sqlite3.Connection,
) -> None:
    """Do not discard a trailing quantity when followed by a courtesy phrase."""
    graph = create_demo_graph(conn=db_conn, structured_model=None, context_agent=None)
    result = await graph.ainvoke(
        {
            "input": "calcular presupuesto preliminar de docks 2 por favor",
            "authenticated_user": None,
        }
    )

    assert "Subtotal: $300.00" in result.get("output", "")


@pytest.mark.parametrize(
    ("preview_request", "expected_message"),
    (
        (
            "calcular presupuesto preliminar de -2 docks",
            "entero positivo, no negativo",
        ),
        (
            "calcular presupuesto preliminar de −2 docks",
            "entero positivo, no negativo",
        ),
        (
            "calcular presupuesto preliminar de ﹣2 docks",
            "entero positivo, no negativo",
        ),
        (
            "calcular presupuesto preliminar de －2 docks",
            "entero positivo, no negativo",
        ),
        (
            "calcular presupuesto preliminar de dock-2",
            "entero positivo, no negativo",
        ),
        (
            "calcular presupuesto preliminar de docks﹣2",
            "entero positivo, no negativo",
        ),
        (
            "calcular presupuesto preliminar de docks－2",
            "entero positivo, no negativo",
        ),
        (
            "calcular presupuesto preliminar de 1.5 docks",
            "entero positivo, sin decimales",
        ),
    ),
)
@pytest.mark.asyncio
async def test_hardening_offline_quote_preview_rejects_invalid_numeric_quantities(
    db_conn: sqlite3.Connection,
    preview_request: str,
    expected_message: str,
) -> None:
    """Reject negative and fractional quantities before text normalization."""
    graph = create_demo_graph(conn=db_conn, structured_model=None, context_agent=None)
    result = await graph.ainvoke({"input": preview_request, "authenticated_user": None})

    output = result.get("output", "").lower()
    assert expected_message in output
    assert "vista preliminar" not in output
    assert "subtotal: $" not in output


@pytest.mark.asyncio
async def test_hardening_offline_quote_preview_rejects_unassociated_quantity(
    db_conn: sqlite3.Connection,
) -> None:
    """Never silently omit a quantity-only segment and return a partial subtotal."""
    graph = create_demo_graph(conn=db_conn, structured_model=None, context_agent=None)
    result = await graph.ainvoke(
        {
            "input": "calcular presupuesto preliminar de 2 docks y 3",
            "authenticated_user": None,
        }
    )

    output = result.get("output", "").lower()
    assert "cantidad 3" in output
    assert "no calculé el subtotal" in output
    assert "subtotal: $" not in output


@pytest.mark.asyncio
async def test_hardening_cli_sanitizes_errors_and_uses_current_language(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Hide internal exception text and localize a failed turn using its input language."""

    class FailingGraph:
        async def ainvoke(self, state: DemoState) -> DemoState:
            """Raise an internal error to verify the CLI boundary is sanitized."""
            del state
            raise RuntimeError("secret database path")

    log_attempts: list[dict[str, Any]] = []

    def failing_logger(error: BaseException, **metadata: Any) -> None:
        """Capture attempted error correlation, then simulate telemetry failure."""
        del error
        log_attempts.append(metadata)
        raise OSError("telemetry write failed")

    inputs = iter(("Cómo inicio sesión?", "exit"))
    await _run_repl_loop(
        FailingGraph(),
        input_func=lambda _prompt: next(inputs),
        interactive=True,
        host_error_sink=failing_logger,
    )

    output = capsys.readouterr().out
    assert "No se pudo procesar la solicitud" in output
    assert "Goodbye." in output
    assert "secret database path" not in output
    assert len(log_attempts) == 1
    assert log_attempts[0]["stage"] == "graph.invoke"
    assert log_attempts[0]["interaction_id"]


@pytest.mark.asyncio
async def test_structured_failure_logs_its_stage_and_invocation_correlation(
    db_conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Preserve the structured call stage and interaction ID at the REPL boundary."""
    captured_configs: list[Any] = []
    logged_errors: list[dict[str, Any]] = []

    class FailingStructuredModel:
        """Structured model double that fails after receiving invocation metadata."""

        def with_structured_output(self, schema: Any) -> Any:
            del schema
            return self

        async def ainvoke(self, input_: Any, **kwargs: Any) -> Any:
            del input_
            captured_configs.append(kwargs.get("config"))
            raise RuntimeError("sensitive provider detail")

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=FailingStructuredModel(),  # type: ignore[arg-type]
    )

    def capture_error(error: BaseException, **metadata: Any) -> None:
        """Capture safe error correlation for assertions."""
        del error
        logged_errors.append(metadata)

    inputs = iter(("write a poem about clouds", "exit"))
    await _run_repl_loop(
        graph,
        input_func=lambda _prompt: next(inputs),
        interactive=True,
        host_error_sink=capture_error,
    )

    output = capsys.readouterr().out
    assert "The request could not be processed" in output
    assert "sensitive provider detail" not in output
    assert len(captured_configs) == 1
    assert captured_configs[0].metadata["interaction_id"] == logged_errors[0]["interaction_id"]
    assert captured_configs[0].metadata["stage"] == "intent_router"
    assert logged_errors[0]["stage"] == "intent_router"


@pytest.mark.asyncio
async def test_scope_20_existing_quote_creation_hitl_and_database_flows_continue_to_pass(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate existing quote creation, discount prompt, and DB persistence continue working.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    graph = create_demo_graph(
        conn=db_conn,
        discount_prompter=lambda _subtotal: 5,
        approval_handler=ConsoleApprovalHandler(input_func=lambda _prompt: "yes"),
        quote_reviewer=lambda _draft: None,
    )

    result = await graph.ainvoke(
        {
            "input": "create quote for Globex for 1 Notebook Pro and 2 Wireless Mouse",
            "authenticated_user": staff_user,
        }
    )
    assert result.get("intent") == "quote_create"
    assert result.get("quote_authorized") is True
    assert result.get("created_quote_id") is not None

    cur = db_conn.execute(
        "SELECT customer_id, total_cents FROM quotes WHERE id = ?",
        (result["created_quote_id"],),
    )
    row = cur.fetchone()
    assert row is not None
    assert row[0] == 2  # Globex LLC is customer ID 2


# =============================================================================
# Functional Hardening Regression Tests (21 Items)
# =============================================================================


def test_hardening_01_and_02_login_questions_vs_direct_commands() -> None:
    """Validate login questions route to help while direct commands route to login."""
    # 1. Informational login queries classify as 'help'
    assert classify_intent_heuristic("How can I login?") == "help"
    assert classify_intent_heuristic("how do i log in") == "help"
    assert classify_intent_heuristic("Cómo inicio sesión?") == "help"
    assert classify_intent_heuristic("como iniciar sesion") == "help"
    assert classify_intent_heuristic("como me logueo?") == "help"

    # 2. Direct login commands classify as 'login'
    assert classify_intent_heuristic("login") == "login"
    assert classify_intent_heuristic("iniciar sesion") == "login"
    assert classify_intent_heuristic("iniciar sesión") == "login"
    assert classify_intent_heuristic("log in") == "login"


@pytest.mark.asyncio
async def test_hardening_01_and_02_login_routing_graph_execution(
    db_conn: sqlite3.Connection,
) -> None:
    """Validate graph routing for login questions vs direct login commands.

    Args:
        db_conn: SQLite connection fixture.
    """
    login_called = False

    def mock_auth(_conn: sqlite3.Connection) -> AuthenticatedUser | None:
        nonlocal login_called
        login_called = True
        return None

    graph = create_demo_graph(
        conn=db_conn,
        auth_interactive=mock_auth,
    )

    # Informational login query does NOT trigger login_hitl
    res_info = await graph.ainvoke({"input": "How can I login?", "authenticated_user": None})
    assert res_info.get("intent") == "help"
    assert not login_called
    assert "login" in res_info.get("output", "").lower()

    # Informational Spanish query does NOT trigger login_hitl
    res_info_es = await graph.ainvoke({"input": "Cómo inicio sesión?", "authenticated_user": None})
    assert res_info_es.get("intent") == "help"
    assert not login_called
    assert "login" in res_info_es.get("output", "").lower()

    # Direct login command triggers login_hitl
    res_direct = await graph.ainvoke({"input": "login", "authenticated_user": None})
    assert res_direct.get("intent") == "login"
    assert login_called


@pytest.mark.asyncio
async def test_hardening_03_and_04_acknowledgement_handling(
    db_conn: sqlite3.Connection,
    client_user: AuthenticatedUser,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate host-side polite closures for acknowledgements without LLM calls.

    Args:
        db_conn: SQLite connection fixture.
        client_user: Authenticated client user fixture.
        staff_user: Authenticated staff user fixture.
    """
    # Allowed actions check for all roles
    assert "acknowledgement" in allowed_actions(None)
    assert "acknowledgement" in allowed_actions(client_user)
    assert "acknowledgement" in allowed_actions(staff_user)

    # Heuristic classifications
    for ack_es in ("gracias", "muchas gracias", "perfecto", "ok"):
        assert classify_intent_heuristic(ack_es) == "acknowledgement"
    for ack_en in ("thank you", "thanks"):
        assert classify_intent_heuristic(ack_en) == "acknowledgement"

    class FailingIfCalledModel:
        """Model double that raises if invoked."""

        async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("Controlled LLM should never be invoked for acknowledgement.")

    graph = create_demo_graph(
        conn=db_conn,
        controlled_agent_model=FailingIfCalledModel(),
    )

    # Spanish acknowledgement
    res_es = await graph.ainvoke({"input": "gracias", "authenticated_user": None})
    assert res_es.get("intent") == "acknowledgement"
    assert res_es.get("action_allowed") is True
    assert "de nada" in res_es.get("output", "").lower()

    # English acknowledgement
    res_en = await graph.ainvoke({"input": "thank you", "authenticated_user": staff_user})
    assert res_en.get("intent") == "acknowledgement"
    assert res_en.get("action_allowed") is True
    assert "welcome" in res_en.get("output", "").lower()


@pytest.mark.asyncio
async def test_hardening_05_quote_planner_fine_grained_guidance_and_localization(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate quote planner emits specific guidance for missing customer, items, or both.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    # 1. Missing customer only (English)
    runtime_missing_cust = FakeRuntime(
        turns=[
            FakeTurn(
                value=QuoteRequest(
                    customer=None,
                    items=[RequestedItem(product="Notebook Pro", quantity=2)],
                ).model_dump_json()
            )
        ]
    )
    graph_cust = create_demo_graph(
        conn=db_conn,
        structured_model=runtime_missing_cust.model(profile="structured", level="low"),
    )
    res_cust_en = await graph_cust.ainvoke(
        {"input": "create quote for 2 Notebook Pro", "authenticated_user": staff_user}
    )
    assert res_cust_en.get("quote_request") is None
    assert "customer name or identifier is required" in res_cust_en.get("output", "").lower()

    # 2. Missing customer only (Spanish)
    runtime_missing_cust_es = FakeRuntime(
        turns=[
            FakeTurn(
                value=QuoteRequest(
                    customer=None,
                    items=[RequestedItem(product="Notebook Pro", quantity=2)],
                ).model_dump_json()
            )
        ]
    )
    graph_cust_es = create_demo_graph(
        conn=db_conn,
        structured_model=runtime_missing_cust_es.model(profile="structured", level="low"),
    )
    res_cust_es = await graph_cust_es.ainvoke(
        {"input": "crear cotización de 2 Notebook Pro", "authenticated_user": staff_user}
    )
    assert res_cust_es.get("quote_request") is None
    assert (
        "se requiere el nombre o identificador del cliente" in res_cust_es.get("output", "").lower()
    )

    # 3. Missing items only (English)
    runtime_missing_items = FakeRuntime(
        turns=[
            FakeTurn(
                value=QuoteRequest(
                    customer="Globex",
                    items=[],
                ).model_dump_json()
            )
        ]
    )
    graph_items = create_demo_graph(
        conn=db_conn,
        structured_model=runtime_missing_items.model(profile="structured", level="low"),
    )
    res_items_en = await graph_items.ainvoke(
        {"input": "create quote for Globex", "authenticated_user": staff_user}
    )
    assert res_items_en.get("quote_request") is None
    assert (
        "at least one product and quantity are required" in res_items_en.get("output", "").lower()
    )

    # 4. Missing items only (Spanish)
    runtime_missing_items_es = FakeRuntime(
        turns=[
            FakeTurn(
                value=QuoteRequest(
                    customer="Globex",
                    items=[],
                ).model_dump_json()
            )
        ]
    )
    graph_items_es = create_demo_graph(
        conn=db_conn,
        structured_model=runtime_missing_items_es.model(profile="structured", level="low"),
    )
    res_items_es = await graph_items_es.ainvoke(
        {"input": "crear cotización para Globex", "authenticated_user": staff_user}
    )
    assert res_items_es.get("quote_request") is None
    assert (
        "se requiere al menos un producto y su cantidad" in res_items_es.get("output", "").lower()
    )

    # 5. Missing both (English)
    runtime_missing_both = FakeRuntime(
        turns=[
            FakeTurn(
                value=QuoteRequest(
                    customer=None,
                    items=[],
                ).model_dump_json()
            )
        ]
    )
    graph_both = create_demo_graph(
        conn=db_conn,
        structured_model=runtime_missing_both.model(profile="structured", level="low"),
    )
    res_both_en = await graph_both.ainvoke(
        {"input": "create quote", "authenticated_user": staff_user}
    )
    assert res_both_en.get("quote_request") is None
    assert "could not extract quote details" in res_both_en.get("output", "").lower()

    # 6. Missing both (Spanish)
    runtime_missing_both_es = FakeRuntime(
        turns=[
            FakeTurn(
                value=QuoteRequest(
                    customer=None,
                    items=[],
                ).model_dump_json()
            )
        ]
    )
    graph_both_es = create_demo_graph(
        conn=db_conn,
        structured_model=runtime_missing_both_es.model(profile="structured", level="low"),
    )
    res_both_es = await graph_both_es.ainvoke(
        {"input": "crear cotización", "authenticated_user": staff_user}
    )
    assert res_both_es.get("quote_request") is None
    assert "no se pudieron extraer los detalles" in res_both_es.get("output", "").lower()


@pytest.mark.asyncio
async def test_hardening_06_help_output_localization_and_role_advertisement(
    db_conn: sqlite3.Connection,
    client_user: AuthenticatedUser,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate help message localization and role-appropriate capability listing.

    Args:
        db_conn: SQLite connection fixture.
        client_user: Authenticated client user fixture.
        staff_user: Authenticated staff user fixture.
    """
    graph = create_demo_graph(conn=db_conn)

    assert detect_language("ayuda") == "es"
    assert detect_language("help") == "en"

    # 1. Spanish query produces Spanish text
    res_es = await graph.ainvoke({"input": "ayuda", "authenticated_user": None})
    out_es = res_es.get("output", "")
    assert "Puedo ayudarte" in out_es
    assert "iniciar sesión" in out_es or "login" in out_es

    # 2. English query produces English text
    res_en = await graph.ainvoke({"input": "help", "authenticated_user": None})
    out_en = res_en.get("output", "")
    assert "I can help you" in out_en
    assert "log in" in out_en or "login" in out_en

    # 3. Anonymous user help: advertises login and public actions, NOT quote creation
    assert "log in" in out_en or "login" in out_en
    assert "create quotes" not in out_en
    assert "persisted quotes" not in out_en

    # 4. Client user help: advertises logout and public actions, NOT quote creation
    res_client = await graph.ainvoke({"input": "help", "authenticated_user": client_user})
    out_client = res_client.get("output", "")
    assert "logout" in out_client
    assert "create quotes" not in out_client
    assert "persisted quotes" not in out_client

    # 5. Staff user help: advertises quote creation, quote history, and public actions
    res_staff = await graph.ainvoke({"input": "help", "authenticated_user": staff_user})
    out_staff = res_staff.get("output", "")
    assert "create quotes" in out_staff
    assert "persisted quote history" in out_staff or "quote history" in out_staff


def test_hardening_07_controlled_agent_instructions_multiturn_and_silent_tools(
    staff_user: AuthenticatedUser,
) -> None:
    """Validate controlled agent instructions enforce silent tool execution and multi-turn context.

    Args:
        staff_user: Authenticated staff user fixture.
    """
    instructions = format_agent_instructions(staff_user)

    # Silence tool narration instruction
    assert "Do NOT narrate tool execution" in instructions
    assert "Voy a consultar" in instructions

    # Conversational multi-turn context instruction (replaces obsolete stateless restriction)
    assert "conversational context across turns" in instructions
    assert "host workflow" in instructions
    assert "owns quote-creation state" in instructions
    assert "stateless across turns" not in instructions


@pytest.mark.asyncio
async def test_hardening_08_offline_mode_zero_live_model_calls(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate offline deterministic mode functions without any live models.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    graph = create_demo_graph(
        conn=db_conn,
        structured_model=None,
        controlled_agent_model=None,
        discount_prompter=lambda _subtotal: 0,
        approval_handler=ConsoleApprovalHandler(input_func=lambda _prompt: "yes"),
        quote_reviewer=lambda _draft: None,
    )

    # 1. Help
    res_help = await graph.ainvoke({"input": "help", "authenticated_user": None})
    assert res_help.get("intent") == "help"
    assert "consult products" in res_help.get("output", "")

    # 2. Acknowledgement
    res_ack = await graph.ainvoke({"input": "thanks", "authenticated_user": None})
    assert res_ack.get("intent") == "acknowledgement"
    assert "welcome" in res_ack.get("output", "").lower()

    # 3. Catalog query
    res_cat = await graph.ainvoke({"input": "products", "authenticated_user": None})
    assert res_cat.get("intent") == "catalog_query"
    assert "Notebook Pro" in res_cat.get("output", "")

    # 4. Staff quote creation
    res_quote = await graph.ainvoke(
        {
            "input": "create quote for Globex for 1 Notebook Pro",
            "authenticated_user": staff_user,
        }
    )
    assert res_quote.get("intent") == "quote_create"
    assert res_quote.get("created_quote_id") is not None


# =============================================================================
# Multi-Turn Task Lifecycle and Context Isolation Tests (Tests A–H)
# =============================================================================


@pytest.mark.asyncio
async def test_a_task_reuse_and_stable_id_across_consecutive_turns(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate task instance and identifier remain stable across turns of the same identity.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    fake_runtime = FakeRuntime(
        turns=[
            FakeTurn(value="Turn 1 answer"),
            FakeTurn(value="Turn 2 answer"),
        ]
    )
    session_mgr = AgentSessionManager(fake_runtime, db_conn)
    try:
        task_turn1 = await session_mgr.get_or_create_task(staff_user)
        turn1_id = task_turn1.id

        res1 = await task_turn1.ainvoke("Show me available laptops")
        assert res1.value == "Turn 1 answer"

        task_turn2 = await session_mgr.get_or_create_task(staff_user)
        assert task_turn2 is task_turn1
        assert task_turn2.id == turn1_id

        res2 = await task_turn2.ainvoke("Show me mice")
        assert res2.value == "Turn 2 answer"
    finally:
        await session_mgr.close()


@pytest.mark.asyncio
async def test_b_multiturn_quote_gathering_products_then_customer(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate multi-turn quote creation when products are provided first and customer second.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    session_mgr = AgentSessionManager(FakeRuntime(), db_conn)
    try:
        graph = create_demo_graph(
            conn=db_conn,
            context_agent=session_mgr.get_active_task,
            session_manager=session_mgr,
            discount_prompter=lambda _: 0,
            approval_handler=ConsoleApprovalHandler(input_func=lambda _: "yes"),
            quote_reviewer=lambda _: None,
        )

        # Turn 1: user provides items only
        state_1: DemoState = {
            "input": "quiero cotizar 2 Notebook Pro",
            "authenticated_user": staff_user,
        }
        res_1 = await graph.ainvoke(state_1)

        # Incomplete request stops gracefully and prompts for customer
        assert res_1.get("created_quote_id") is None
        assert res_1.get("pending_action") == "quote_create"
        pending = res_1.get("pending_quote_request")
        assert pending is not None
        assert pending.customer is None
        assert len(pending.items) == 1
        assert pending.items[0].product == "Notebook Pro"
        assert pending.items[0].quantity == 2
        assert (
            "cliente" in res_1.get("output", "").lower()
            or "customer" in res_1.get("output", "").lower()
        )

        # Turn 2: user provides customer only, carrying over pending state
        state_2: DemoState = {
            "input": "Para Globex",
            "authenticated_user": staff_user,
            "pending_action": res_1["pending_action"],
            "pending_quote_request": res_1["pending_quote_request"],
        }
        res_2 = await graph.ainvoke(state_2)

        # Quote successfully resolved, approved, and created
        assert res_2.get("created_quote_id") is not None
        assert res_2.get("pending_action") is None
        assert res_2.get("pending_quote_request") is None

        cur = db_conn.execute(
            "SELECT customer_id, total_cents FROM quotes WHERE id = ?",
            (res_2["created_quote_id"],),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 2  # Globex LLC is customer ID 2
    finally:
        await session_mgr.close()


@pytest.mark.asyncio
async def test_c_multiturn_quote_gathering_customer_then_products(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate multi-turn quote creation when customer is provided first and products second.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    session_mgr = AgentSessionManager(FakeRuntime(), db_conn)
    try:
        graph = create_demo_graph(
            conn=db_conn,
            context_agent=session_mgr.get_active_task,
            session_manager=session_mgr,
            discount_prompter=lambda _: 0,
            approval_handler=ConsoleApprovalHandler(input_func=lambda _: "yes"),
            quote_reviewer=lambda _: None,
        )

        # Turn 1: user provides customer only
        state_1: DemoState = {
            "input": "Quiero crear una cotización para Globex",
            "authenticated_user": staff_user,
        }
        res_1 = await graph.ainvoke(state_1)

        # Incomplete request stops gracefully and prompts for products
        assert res_1.get("created_quote_id") is None
        assert res_1.get("pending_action") == "quote_create"
        pending = res_1.get("pending_quote_request")
        assert pending is not None
        assert pending.customer == "Globex"
        assert len(pending.items) == 0
        assert (
            "producto" in res_1.get("output", "").lower()
            or "product" in res_1.get("output", "").lower()
        )

        # Turn 2: user provides items only, carrying over pending state
        state_2: DemoState = {
            "input": "2 Notebook Pro",
            "authenticated_user": staff_user,
            "pending_action": res_1["pending_action"],
            "pending_quote_request": res_1["pending_quote_request"],
        }
        res_2 = await graph.ainvoke(state_2)

        # Quote successfully resolved, approved, and created
        assert res_2.get("created_quote_id") is not None
        assert res_2.get("pending_action") is None
        assert res_2.get("pending_quote_request") is None

        cur = db_conn.execute(
            "SELECT customer_id, total_cents FROM quotes WHERE id = ?",
            (res_2["created_quote_id"],),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 2  # Globex LLC is customer ID 2
    finally:
        await session_mgr.close()


@pytest.mark.asyncio
async def test_d_identity_switch_lifecycle_and_task_closure(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate task lifecycle closes previous tasks and creates distinct IDs across logins/logouts.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    session_mgr = AgentSessionManager(FakeRuntime(), db_conn)
    try:
        # Step 1: Anonymous task created
        task_anon = await session_mgr.get_or_create_task(None)
        assert task_anon.state == TaskState.OPEN
        anon_id = task_anon.id

        # Step 2: Login as staff -> switches identity, closing anonymous task
        task_staff = await session_mgr.switch_identity(staff_user)
        assert str(task_anon.state) == TaskState.CLOSED.value
        assert task_staff.state == TaskState.OPEN
        staff_id = task_staff.id
        assert staff_id != anon_id

        # Step 3: Logout -> switches identity, closing staff task
        task_anon_new = await session_mgr.switch_identity(None)
        assert str(task_staff.state) == TaskState.CLOSED.value
        assert task_anon_new.state == TaskState.OPEN
        anon_new_id = task_anon_new.id
        assert anon_new_id != staff_id
        assert anon_new_id != anon_id
    finally:
        await session_mgr.close()


@pytest.mark.asyncio
async def test_e_authority_freezing_at_task_creation(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate tools and permissions are frozen at task creation and immune to later mutations.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    fake_runtime = FakeRuntime()
    registry = get_agent_tool_registry(db_conn, staff_user)
    initial_count = len(registry.definitions())

    task = await fake_runtime.task(
        profile="controlled_agent",
        level="low",
        instructions="Test agent",
        registry=registry,
    )
    try:
        snapshot = getattr(task, "_tool_snapshot", None)
        assert snapshot is not None
        assert len(snapshot.definitions()) == initial_count

        # Mutate the external registry by registering a new tool
        from proteo_runtime.tools import runtime_tool

        @runtime_tool(
            name="external_rogue_tool",
            description="Unauthorized dynamic tool injected after task initialization.",
            permission="quote.read",
        )
        async def rogue_tool() -> str:
            """Rogue tool docstring."""
            return "rogue"

        registry.register(rogue_tool)
        assert len(registry.definitions()) == initial_count + 1

        # Assert frozen task snapshot is untouched
        assert len(snapshot.definitions()) == initial_count
        assert "external_rogue_tool" not in {d.name for d in snapshot.definitions()}
    finally:
        await task.close()


def test_f_write_tool_segregation(
    db_conn: sqlite3.Connection,
    client_user: AuthenticatedUser,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate create_quote is never exposed to controlled_agent and exclusive to write registry.

    Args:
        db_conn: SQLite connection fixture.
        client_user: Authenticated client user fixture.
        staff_user: Authenticated staff user fixture.
    """
    for user in (None, client_user, staff_user):
        agent_reg = get_agent_tool_registry(db_conn, user)
        agent_tool_names = {d.name for d in agent_reg.definitions()}
        assert "create_quote" not in agent_tool_names

    write_reg = get_quote_write_registry(db_conn, staff_user)
    write_tool_names = {d.name for d in write_reg.definitions()}
    assert "create_quote" in write_tool_names
    assert len(write_tool_names) == 1


@pytest.mark.asyncio
async def test_g_context_reset_after_logout(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate pending quote workflow state is purged on logout.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    session_mgr = AgentSessionManager(FakeRuntime(), db_conn)
    try:
        graph = create_demo_graph(
            conn=db_conn,
            context_agent=session_mgr.get_active_task,
            session_manager=session_mgr,
        )

        # Turn 1: Staff starts incomplete quote
        res_1 = await graph.ainvoke(
            {"input": "quiero cotizar 2 Notebook Pro", "authenticated_user": staff_user}
        )
        assert res_1.get("pending_action") == "quote_create"
        assert res_1.get("pending_quote_request") is not None

        # Turn 2: Staff logs out
        res_2 = await graph.ainvoke(
            {
                "input": "logout",
                "authenticated_user": staff_user,
                "pending_action": res_1["pending_action"],
                "pending_quote_request": res_1["pending_quote_request"],
            }
        )
        assert res_2.get("authenticated_user") is None
        assert res_2.get("pending_action") is None
        assert res_2.get("pending_quote_request") is None
        assert res_2.get("quote_workflow") is None
        assert res_2.get("quote_draft") is None
        assert res_2.get("quote_patch") is None
        assert res_2.get("quote_request") is None

        # Turn 3: Follow-up input as anonymous does not resume quote
        res_3 = await graph.ainvoke(
            {
                "input": "Para Globex",
                "authenticated_user": None,
                "pending_action": res_2.get("pending_action"),
                "pending_quote_request": res_2.get("pending_quote_request"),
            }
        )
        assert res_3.get("created_quote_id") is None
    finally:
        await session_mgr.close()


@pytest.mark.asyncio
async def test_h_context_reset_after_task_close(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate closed tasks reject turns and session creates a fresh task afterwards.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    session_mgr = AgentSessionManager(FakeRuntime(), db_conn)
    try:
        task_1 = await session_mgr.get_or_create_task(staff_user)
        task_1_id = task_1.id

        # Explicitly close task_1
        await task_1.close()
        assert task_1.state == TaskState.CLOSED

        # Turn on closed task raises SessionNotFoundError
        with pytest.raises(SessionNotFoundError):
            await task_1.ainvoke("Should fail on closed task")

        # Session manager detects terminal state and creates a fresh task
        task_2 = await session_mgr.get_or_create_task(staff_user)
        assert task_2 is not task_1
        assert task_2.id != task_1_id
        assert task_2.state == TaskState.OPEN
    finally:
        await session_mgr.close()


def test_hardening_workflow_replacement_preserves_unrelated_lines() -> None:
    """Replace one requested product without dropping other quote lines."""
    workflow = QuoteWorkflowState(
        customer_query="Globex",
        items=[
            QuoteWorkflowItem(product_query="desk", quantity=1, status="unresolved"),
            QuoteWorkflowItem(product_query="mouses", quantity=2, status="unresolved"),
        ],
    )

    updated = _apply_quote_turn(workflow, None, "quiero un dock en vez de un desk")

    assert [(item.product_query, item.quantity) for item in updated.items] == [
        ("dock", 1),
        ("mouses", 2),
    ]
    assert updated.revision == 2


def test_hardening_product_aliases_are_safe_and_unique(db_conn: sqlite3.Connection) -> None:
    """Resolve supported irregular mouse plurals without fuzzy desk-to-dock correction."""
    for query in ("mouse", "mice", "mouses"):
        product = find_product_by_query(db_conn, query)
        assert product is not None
        assert product.get("sku") == "MS-WL"
    assert find_product_by_query(db_conn, "desk") is None
    accented_customer = find_customer_by_query(db_conn, "GLÓBEX")
    assert accented_customer is not None
    assert accented_customer.get("id") == 2


def test_hardening_quote_patch_operations_preserve_unrelated_lines() -> None:
    """Apply add, replace, quantity, and remove operations to exact stable line targets."""
    first = QuoteWorkflowItem(product_query="Wireless Mouse", quantity=None)
    second = QuoteWorkflowItem(product_query="Mechanical Keyboard", quantity=1)
    workflow = QuoteWorkflowState(items=[first, second])

    quantity_update = _apply_quote_turn(
        workflow,
        None,
        "cantidad 2",
        QuotePatch(
            operations=[
                SetQuantityOperation(operation="set_quantity", target=first.line_id, quantity=2)
            ]
        ),
    )
    assert [(item.product_query, item.quantity) for item in quantity_update.items] == [
        ("Wireless Mouse", 2),
        ("Mechanical Keyboard", 1),
    ]

    replacement = _apply_quote_turn(
        quantity_update,
        None,
        "Notebook Pro en vez de Wireless Mouse",
        QuotePatch(
            operations=[
                ReplaceItemOperation(
                    operation="replace_item",
                    target=first.line_id,
                    product="Notebook Pro",
                )
            ]
        ),
    )
    assert [(item.product_query, item.quantity) for item in replacement.items] == [
        ("Notebook Pro", 2),
        ("Mechanical Keyboard", 1),
    ]

    added = _apply_quote_turn(
        replacement,
        None,
        "agrega 2 mouse",
        QuotePatch(
            operations=[AddItemOperation(operation="add_item", product="mouse", quantity=2)]
        ),
    )
    assert [(item.product_query, item.quantity) for item in added.items] == [
        ("Notebook Pro", 2),
        ("Mechanical Keyboard", 1),
        ("mouse", 2),
    ]

    removed = _apply_quote_turn(
        added,
        None,
        "elimina Mechanical Keyboard",
        QuotePatch(
            operations=[RemoveItemOperation(operation="remove_item", target=second.line_id)]
        ),
    )
    assert [(item.product_query, item.quantity) for item in removed.items] == [
        ("Notebook Pro", 2),
        ("mouse", 2),
    ]


@pytest.mark.asyncio
async def test_hardening_customer_interruption_preserves_quote_workflow(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """List customers during quote collection without consuming pending state."""
    workflow = QuoteWorkflowState(
        items=[QuoteWorkflowItem(product_query="desk", quantity=1, status="unresolved")]
    )
    graph = create_demo_graph(conn=db_conn, structured_model=None, context_agent=None)

    result = await graph.ainvoke(
        {
            "input": "muéstrame la lista de clientes",
            "authenticated_user": staff_user,
            "quote_workflow": workflow,
            "language": "es",
        }
    )

    assert result.get("intent") == "customer_query"
    assert result.get("quote_workflow") == workflow
    assert "Globex LLC" in result.get("output", "")


@pytest.mark.asyncio
async def test_hardening_pending_out_of_scope_turn_is_not_rewritten_as_quote_edit(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Keep unrelated structured intents out of the pending quote reducer."""
    workflow = QuoteWorkflowState(
        customer_query="Globex",
        items=[QuoteWorkflowItem(product_query="Wireless Mouse", quantity=2)],
    )
    structured_model = FakeRuntime(
        turns=[FakeTurn(value=TurnDecision(intent="out_of_scope", language="en").model_dump_json())]
    ).model(profile="structured", level="low")
    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_model,
        context_agent=None,
    )

    result = await graph.ainvoke(
        {
            "input": "write a poem about clouds",
            "authenticated_user": staff_user,
            "quote_workflow": workflow,
            "pending_action": "quote_create",
            "language": "es",
        }
    )
    assert result.get("intent") == "out_of_scope"
    assert result.get("quote_workflow") == workflow
    assert result["quote_workflow"].revision == workflow.revision
    assert "outside the scope" in result.get("output", "").lower()


def test_hardening_heuristic_recognizes_interleaved_quote_read_actions() -> None:
    """Classify common quote-history and preview wording as read-only actions."""
    assert classify_intent_heuristic("ver el listado de quote") == "quote_history"
    assert classify_intent_heuristic("calcular un presupuesto preliminar") == "quote_preview"


@pytest.mark.asyncio
async def test_hardening_specific_catalog_query_stores_unique_reference_candidate(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Resolve a later 'that' reference to one product found by a short catalog query."""
    workflow = QuoteWorkflowState(
        customer_query="Globex",
        items=[QuoteWorkflowItem(product_query="desk", quantity=1, status="unresolved")],
    )
    structured_model = FakeRuntime(
        turns=[
            FakeTurn(value=TurnDecision(intent="catalog_query", language=None).model_dump_json())
        ]
    ).model(profile="structured", level="low")
    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_model,
        context_agent=None,
    )

    state: DemoState = {
        "input": "show me a mouse",
        "authenticated_user": staff_user,
        "quote_workflow": workflow,
        "pending_action": "quote_create",
        "language": "es",
    }
    state = await graph.ainvoke(state)
    resolved_workflow = state.get("quote_workflow")
    assert resolved_workflow is not None
    assert resolved_workflow.last_candidates == ["Wireless Mouse (MS-WL)"]
    assert state["language"] == "en"

    state["input"] = "agrega ese"
    state = await graph.ainvoke(state)
    resolved_workflow = state.get("quote_workflow")
    assert resolved_workflow is not None
    assert [(item.product_query, item.quantity) for item in resolved_workflow.items] == [
        ("desk", 1),
        ("Wireless Mouse", 1),
    ]
    assert state.get("quote_draft") is None


def test_hardening_legacy_request_is_a_lossy_workflow_projection() -> None:
    """Document that legacy request state cannot preserve workflow identity or candidates."""
    workflow = QuoteWorkflowState(
        workflow_id="quote-stable",
        revision=4,
        customer_query="Globex",
        items=[
            QuoteWorkflowItem(
                line_id="line-stable",
                product_query="Notebook",
                quantity=1,
                status="ambiguous",
                candidates=["Notebook Air (NB-AIR)", "Notebook Pro (NB-PRO)"],
            )
        ],
        last_candidates=["Notebook Air (NB-AIR)", "Notebook Pro (NB-PRO)"],
    )

    projected = _request_from_workflow(workflow)
    restored = _workflow_from_request(projected)

    assert projected.customer == "Globex"
    assert projected.items[0].product == "Notebook"
    assert restored.workflow_id != workflow.workflow_id
    assert restored.revision != workflow.revision
    assert restored.items[0].line_id != workflow.items[0].line_id
    assert restored.last_candidates == []


def test_hardening_quote_patch_operation_validates_discriminator_fields() -> None:
    """Require each quote patch operation to contain only its valid target fields."""
    parsed_patch = QuotePatch.model_validate(
        {"operations": [{"operation": "add_item", "product": "Wireless Mouse", "quantity": 2}]}
    )
    assert isinstance(parsed_patch.operations[0], AddItemOperation)

    with pytest.raises(ValidationError):
        QuotePatch.model_validate(
            {
                "operations": [
                    {
                        "operation": "add_item",
                        "target": "line-1",
                        "product": "Wireless Mouse",
                        "quantity": 2,
                    }
                ]
            }
        )

    with pytest.raises(ValidationError):
        AddItemOperation.model_validate(
            {
                "operation": "add_item",
                "target": "line-1",
                "product": "Wireless Mouse",
                "quantity": 1,
            }
        )

    with pytest.raises(ValidationError):
        SetQuantityOperation.model_validate({"operation": "set_quantity", "target": "line-1"})

    with pytest.raises(ValidationError):
        SetCustomerOperation.model_validate({"operation": "set_customer", "target": " "})

    with pytest.raises(ValidationError):
        RemoveItemOperation.model_validate(
            {"operation": "remove_item", "target": "line-1", "product": "mouse"}
        )


@pytest.mark.asyncio
async def test_hardening_reported_transcript_completes_across_interruptions(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Complete one pending quote after customer/catalog interruptions and corrections."""

    class ImmediateApproval(ConsoleApprovalHandler):
        async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
            del request
            return ApprovalDecision.APPROVE

    prompted_languages: list[str] = []
    reviewed_languages: list[str] = []

    def localized_discount(_subtotal: int, *, language: str) -> int:
        prompted_languages.append(language)
        return 0

    def localized_review(_draft: QuoteDraft, *, language: str) -> None:
        reviewed_languages.append(language)

    workflow = QuoteWorkflowState(
        customer_query=None,
        items=[
            QuoteWorkflowItem(product_query="desk", quantity=None, status="unresolved"),
            QuoteWorkflowItem(product_query="mouses", quantity=2, status="unresolved"),
        ],
    )
    graph = create_demo_graph(
        conn=db_conn,
        structured_model=None,
        context_agent=None,
        approval_handler=ImmediateApproval(),
        discount_prompter=localized_discount,
        quote_reviewer=localized_review,
    )
    state: dict[str, Any] = {
        "authenticated_user": staff_user,
        "quote_workflow": workflow,
        "pending_action": "quote_create",
        "pending_quote_request": None,
        "language": "es",
    }

    state["input"] = "muestrame la lista de clientes"
    state = await graph.ainvoke(state)
    assert state.get("intent") == "customer_query"
    assert "Globex LLC" in state.get("output", "")
    assert state["quote_workflow"].workflow_id == workflow.workflow_id

    state["input"] = "qué productos activos hay?"
    state = await graph.ainvoke(state)
    assert state.get("intent") == "catalog_query"
    assert "USB-C Dock" in state.get("output", "")
    assert len(state["quote_workflow"].last_candidates) > 1

    state["input"] = "Me equivoqué, quiero un dock en vez de un desk"
    state = await graph.ainvoke(state)
    assert [(line.product_query, line.quantity) for line in state["quote_workflow"].items] == [
        ("dock", None),
        ("mouses", 2),
    ]

    state["input"] = "cantidad 1"
    state = await graph.ainvoke(state)
    assert state["quote_workflow"].items[0].quantity == 1
    assert state["language"] == "es"

    state["input"] = "para Globex"
    state = await graph.ainvoke(state)
    assert state.get("created_quote_id") == 1
    assert state.get("quote_workflow") is None
    assert db_conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 1
    lines = db_conn.execute(
        "SELECT p.sku, ql.quantity FROM quote_lines ql "
        "JOIN products p ON p.id = ql.product_id ORDER BY p.sku"
    ).fetchall()
    assert [(row["sku"], row["quantity"]) for row in lines] == [
        ("DOCK-USBC", 1),
        ("MS-WL", 2),
    ]
    assert prompted_languages == ["es"]
    assert reviewed_languages == ["es"]


@pytest.mark.asyncio
async def test_hardening_ambiguous_reference_and_quantity_are_noops(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Ask for clarification instead of mutating ambiguous references or quantities."""
    workflow = QuoteWorkflowState(
        customer_query="Globex",
        items=[
            QuoteWorkflowItem(product_query="Notebook", quantity=None, status="ambiguous"),
            QuoteWorkflowItem(product_query="Wireless Mouse", quantity=None),
        ],
        last_candidates=["Notebook Air (NB-AIR)", "Notebook Pro (NB-PRO)"],
    )
    graph = create_demo_graph(conn=db_conn, structured_model=None, context_agent=None)

    result = await graph.ainvoke(
        {
            "input": "agrega ese",
            "authenticated_user": staff_user,
            "quote_workflow": workflow,
            "pending_action": "quote_create",
            "language": "es",
        }
    )
    assert result["quote_workflow"].workflow_id == workflow.workflow_id
    assert result["quote_workflow"].revision == workflow.revision
    assert [(line.product_query, line.quantity) for line in result["quote_workflow"].items] == [
        ("Notebook", None),
        ("Wireless Mouse", None),
    ]
    assert "elige uno" in result.get("output", "").lower()

    quantity_result = await graph.ainvoke(
        {
            "input": "cantidad 1",
            "authenticated_user": staff_user,
            "quote_workflow": workflow,
            "pending_action": "quote_create",
            "language": "es",
        }
    )
    assert [line.quantity for line in quantity_result["quote_workflow"].items] == [None, None]
    assert "a cuál producto" in quantity_result.get("output", "").lower()

    unrelated_result = await graph.ainvoke(
        {
            "input": "maybe",
            "authenticated_user": staff_user,
            "quote_workflow": workflow,
            "pending_action": "quote_create",
            "language": "es",
        }
    )
    assert unrelated_result["quote_workflow"] == workflow
    assert unrelated_result["quote_workflow"].revision == workflow.revision
    assert unrelated_result.get("quote_draft") is None
    assert unrelated_result.get("intent") == "clarification"
    assert "no identifiqué una acción clara" in unrelated_result.get("output", "").lower()


@pytest.mark.asyncio
async def test_hardening_cancel_clears_all_quote_references(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Clear the complete pending quote transaction on an explicit cancellation."""
    workflow = QuoteWorkflowState(
        customer_query="Globex",
        items=[QuoteWorkflowItem(product_query="Wireless Mouse", quantity=2)],
    )
    graph = create_demo_graph(conn=db_conn, structured_model=None, context_agent=None)
    result = await graph.ainvoke(
        {
            "input": "cancel",
            "authenticated_user": staff_user,
            "quote_workflow": workflow,
            "quote_draft": {
                "workflow_id": workflow.workflow_id,
                "workflow_revision": workflow.revision,
                "customer_id": 2,
                "customer_name": "Globex LLC",
                "lines": [],
                "subtotal_cents": 0,
                "discount_percent": 0,
                "discount_amount_cents": 0,
                "total_cents": 0,
            },
            "quote_patch": QuotePatch(operations=[]),
            "pending_action": "quote_create",
            "pending_quote_request": QuoteRequest(
                customer="Globex",
                items=[RequestedItem(product="Wireless Mouse", quantity=2)],
            ),
        }
    )

    assert result.get("quote_workflow") is None
    assert result.get("quote_draft") is None
    assert result.get("quote_patch") is None
    assert result.get("quote_request") is None
    assert result.get("pending_quote_request") is None
    assert result.get("pending_action") is None


@pytest.mark.asyncio
async def test_hardening_terminal_persistence_failure_clears_workflow(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Clear quote state after a terminal persistence failure without writing rows."""
    db_conn.execute(
        "CREATE TRIGGER reject_quote BEFORE INSERT ON quotes "
        "BEGIN SELECT RAISE(FAIL, 'forced test failure'); END;"
    )
    structured_model = FakeRuntime(
        turns=[
            FakeTurn(
                value=QuoteRequest(
                    customer="Globex",
                    items=[RequestedItem(product="Wireless Mouse", quantity=2)],
                ).model_dump_json()
            )
        ]
    ).model(profile="structured", level="low")

    class ImmediateApproval(ConsoleApprovalHandler):
        async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
            """Approve the controlled test request to reach the forced database failure."""
            del request
            return ApprovalDecision.APPROVE

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_model,
        context_agent=None,
        approval_handler=ImmediateApproval(),
        discount_prompter=lambda _subtotal: 0,
        quote_reviewer=lambda _draft: None,
    )
    result = await graph.ainvoke(
        {"input": "crear cotización para Globex", "authenticated_user": staff_user}
    )

    assert result.get("created_quote_id") is None
    assert result.get("quote_workflow") is None
    assert result.get("quote_draft") is None
    assert result.get("quote_patch") is None
    assert result.get("quote_request") is None
    assert result.get("pending_quote_request") is None
    assert db_conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 0


def test_hardening_language_detection_preserves_short_product_references() -> None:
    """Keep the established language for product names, but detect clear language switches."""
    assert resolve_language("cantidad 1", "es") == "es"
    assert resolve_language("Wireless Mouse", "es") == "es"
    assert resolve_language("list customers", "es") == "en"


@pytest.mark.asyncio
async def test_hardening_stale_draft_cannot_survive_failed_resolution(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Clear an older ready draft before resolving a newer invalid workflow revision."""
    workflow = QuoteWorkflowState(
        workflow_id="quote-current",
        revision=2,
        customer_query="Globex",
        items=[QuoteWorkflowItem(product_query="desk", quantity=1, status="unresolved")],
    )
    stale: QuoteDraft = {
        "workflow_id": "quote-old",
        "workflow_revision": 1,
        "customer_id": 2,
        "customer_name": "Globex LLC",
        "lines": [],
        "subtotal_cents": 0,
        "discount_percent": 0,
        "discount_amount_cents": 0,
        "total_cents": 0,
    }
    assert not _draft_matches_workflow(workflow, stale)
    prompted: list[int] = []

    def discount_prompter(subtotal: int, *, language: str = "en") -> int:
        """Record any accidental prompt for a stale quote draft."""
        del language
        prompted.append(subtotal)
        return 0

    class RejectUnexpectedApproval(ConsoleApprovalHandler):
        async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
            """Fail the test if stale data reaches a persistence approval request."""
            del request
            raise AssertionError("Stale quote must not request persistence approval")

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=None,
        context_agent=None,
        discount_prompter=discount_prompter,
        approval_handler=RejectUnexpectedApproval(),
    )

    result = await graph.ainvoke(
        {
            "input": "para Globex",
            "authenticated_user": staff_user,
            "quote_workflow": workflow,
            "quote_draft": stale,
            "language": "es",
        }
    )

    assert result.get("quote_draft") is None
    assert result.get("pending_action") == "quote_create"
    assert result.get("created_quote_id") is None
    assert prompted == []
    assert db_conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_hardening_stale_draft_guards_discount_and_approval_nodes(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Reject stale drafts before discount callbacks and persistence approval."""
    prompted: list[int] = []
    approvals: list[ApprovalRequest] = []

    def discount_prompter(subtotal: int, *, language: str = "en") -> int:
        """Record any discount prompt that should be skipped for stale data."""
        del language
        prompted.append(subtotal)
        return 0

    class RecordingApproval(ConsoleApprovalHandler):
        async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
            """Record any approval request and deny it for safety."""
            approvals.append(request)
            return ApprovalDecision.DENY

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=None,
        context_agent=None,
        discount_prompter=discount_prompter,
        approval_handler=RecordingApproval(),
    )
    workflow = QuoteWorkflowState(workflow_id="quote-new", revision=3)
    stale: QuoteDraft = {
        "workflow_id": "quote-old",
        "workflow_revision": 2,
        "customer_id": 2,
        "customer_name": "Globex LLC",
        "lines": [],
        "subtotal_cents": 0,
        "discount_percent": 0,
        "discount_amount_cents": 0,
        "total_cents": 0,
    }
    state: DemoState = {
        "quote_workflow": workflow,
        "quote_draft": stale,
        "authenticated_user": staff_user,
        "language": "es",
    }

    discount_updates = await graph.nodes["discount_hitl"].bound.ainvoke(state)
    create_updates = await graph.nodes["create_quote_tool"].bound.ainvoke(state)

    assert discount_updates.get("quote_draft") is None
    assert create_updates.get("quote_draft") is None
    assert prompted == []
    assert approvals == []
    assert db_conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 0
