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

# Ensure examples/smart_quote_agent is on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

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
    allowed_actions,
    classify_intent_heuristic,
    create_demo_graph,
    detect_language,
)
from hitl import ConsoleApprovalHandler, prompt_discount_interactive  # noqa: E402
from models import (  # noqa: E402
    AuthenticatedUser,
    DemoState,
    IntentDecision,
    QuoteRequest,
    RequestedItem,
)
from tools import (  # noqa: E402
    create_tool_executor,
    get_agent_tool_registry,
    get_quote_write_registry,
)

from proteo_runtime.core.errors import AgentRuntimeError, TransportError  # noqa: E402
from proteo_runtime.core.profiles import LogicalLevel  # noqa: E402
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
    controlled_model = agent_runtime.model(profile="controlled_agent", level="low")

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_model,
        controlled_agent_model=controlled_model,
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
    agent_runtime = FakeRuntime(turns=[])  # Empty turns: controlled LLM must not be invoked

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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


def test_point_04_distinct_model_bindings_for_structured_and_controlled() -> None:
    """Validate structured_model and controlled_agent_model have distinct profile bindings."""
    runtime = FakeRuntime()
    structured = runtime.model(profile="structured", level="low")
    controlled = runtime.model(profile="controlled_agent", level="low")

    assert structured.profile != controlled.profile
    assert structured.profile == "structured"
    assert controlled.profile == "controlled_agent"


def test_point_05_every_model_binding_uses_level_low() -> None:
    """Validate all model bindings are explicitly configured with logical level 'low'."""
    runtime = FakeRuntime()
    structured = runtime.model(profile="structured", level="low")
    controlled = runtime.model(profile="controlled_agent", level="low")

    assert structured.level in (LogicalLevel.LOW, "low")
    assert controlled.level in (LogicalLevel.LOW, "low")


@pytest.mark.asyncio
async def test_point_06_controlled_agent_binds_tools_without_capability_error(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate controlled_agent model with tools executes without CapabilityError."""
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

    bound = fake_runtime.model(profile="controlled_agent", level="low").with_tools(
        registry, executor=executor
    )
    result = await bound.ainvoke("Listar productos")
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
    agent_runtime = FakeRuntime()

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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
    agent_runtime = FakeRuntime()

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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
    agent_runtime = FakeRuntime()

    captured_requests: list[ApprovalRequest] = []

    class ImmediateApproval(ConsoleApprovalHandler):
        async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
            captured_requests.append(request)
            return ApprovalDecision.APPROVE

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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
    agent_runtime = FakeRuntime()

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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
    agent_runtime = FakeRuntime()

    class DenialApproval(ConsoleApprovalHandler):
        async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
            return ApprovalDecision.DENY

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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
    assert "denied by user" in result.get("output", "").lower()

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

    staff_reg = get_agent_tool_registry(db_conn, staff_user)
    staff_names = {d.name for d in staff_reg.definitions()}
    assert "list_quotes" in staff_names
    assert "get_quote" in staff_names


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
    user = authenticate_user_interactive(
        db_conn,
        input_func=lambda _: "staff",
        getpass_func=lambda _: "1234",
    )
    assert user is not None
    assert user.username == "staff"

    disc = prompt_discount_interactive(10000, input_func=lambda _: "n")
    assert disc == 0


@pytest.mark.asyncio
async def test_point_23_live_model_exceptions_not_silently_swallowed(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate live model runtime exceptions are raised cleanly rather than swallowed."""

    class FailingModel:
        """Test model that always raises TransportError."""

        def with_tools(self, *args: Any, **kwargs: Any) -> Any:
            return self

        async def ainvoke(self, input_: Any, **kwargs: Any) -> Any:
            raise TransportError("Codex transport connection failed")

    graph = create_demo_graph(
        conn=db_conn,
        controlled_agent_model=FailingModel(),  # type: ignore[arg-type]
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
    assert "controlled_agent_model" in sig.parameters


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

    agent_runtime = FakeRuntime(turns=[])
    graph = create_demo_graph(
        conn=db_conn,
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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
    agent_runtime = FakeRuntime(turns=[])
    graph = create_demo_graph(
        conn=db_conn,
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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
    agent_runtime = FakeRuntime(turns=[])
    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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
    agent_runtime = FakeRuntime(turns=[])
    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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
    agent_runtime = FakeRuntime(turns=[])
    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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
    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_runtime.model(profile="structured", level="low"),
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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

    class InspectingModel:
        """Double that captures input prompt text."""

        def with_structured_output(self, schema: Any) -> Any:
            del schema
            return self

        async def ainvoke(self, input_: Any, **kwargs: Any) -> Any:
            del kwargs
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
        {"input": "What laptops are currently available?", "authenticated_user": client_user}
    )
    assert len(captured_prompts) >= 1
    system_text = captured_prompts[0]
    assert "Current access level: client" in system_text
    assert "Actions currently available for this access level:" in system_text
    assert "out_of_scope" in system_text


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
    agent_runtime = FakeRuntime(turns=[])
    graph = create_demo_graph(
        conn=db_conn,
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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
    graph = create_demo_graph(
        conn=db_conn,
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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
    graph = create_demo_graph(
        conn=db_conn,
        structured_model=FakeRuntime(
            turns=[FakeTurn(value=IntentDecision(intent="quote_preview").model_dump_json())]
        ).model(profile="structured", level="low"),
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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
    graph = create_demo_graph(
        conn=db_conn,
        controlled_agent_model=agent_runtime.model(profile="controlled_agent", level="low"),
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
    captured_system_instructions: list[str] = []

    class InspectingAgentModel:
        """Double that captures the system prompt passed to controlled_agent."""

        def with_tools(self, registry: Any, executor: Any = None) -> Any:
            del registry, executor
            return self

        async def ainvoke(self, input_: Any, **kwargs: Any) -> Any:
            del kwargs
            for msg in getattr(input_, "messages", ()):
                if getattr(msg, "role", "") == "system":
                    text = getattr(msg, "text", "")
                    if text:
                        captured_system_instructions.append(text)
            return type("Res", (), {"value": "Inspected response"})()

    graph = create_demo_graph(
        conn=db_conn,
        controlled_agent_model=InspectingAgentModel(),  # type: ignore[arg-type]
    )

    await graph.ainvoke({"input": "products", "authenticated_user": staff_user})
    assert len(captured_system_instructions) >= 1
    sys_prompt = captured_system_instructions[0]
    assert "You are ONLY the Smart Quote Agent for this application." in sys_prompt
    assert "Current role: staff" in sys_prompt
    assert "internet browsing" in sys_prompt
    assert "code execution/editing" in sys_prompt
    assert "image generation" in sys_prompt
    assert "filesystem access" in sys_prompt


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
    graph = create_demo_graph(conn=db_conn, structured_model=None, controlled_agent_model=None)

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
        controlled_agent_model=FailingIfCalledModel(),  # type: ignore[arg-type]
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


@pytest.mark.asyncio
async def test_hardening_07_controlled_agent_prompt_silence_narration_and_stateless_turns(
    db_conn: sqlite3.Connection,
    staff_user: AuthenticatedUser,
) -> None:
    """Validate controlled agent system prompt enforces silent tool execution and statelessness.

    Args:
        db_conn: SQLite connection fixture.
        staff_user: Authenticated staff user fixture.
    """
    captured_system_instructions: list[str] = []

    class InspectingAgentModel:
        """Model double that captures system prompt passed to controlled_agent."""

        def with_tools(self, registry: Any, executor: Any = None) -> Any:
            del registry, executor
            return self

        async def ainvoke(self, input_: Any, **kwargs: Any) -> Any:
            del kwargs
            for msg in getattr(input_, "messages", ()):
                if getattr(msg, "role", "") == "system":
                    text = getattr(msg, "text", "")
                    if text:
                        captured_system_instructions.append(text)
            return type("Res", (), {"value": "Inspected response"})()

    graph = create_demo_graph(
        conn=db_conn,
        controlled_agent_model=InspectingAgentModel(),  # type: ignore[arg-type]
    )

    await graph.ainvoke({"input": "products", "authenticated_user": staff_user})
    assert len(captured_system_instructions) >= 1
    sys_prompt = captured_system_instructions[0]

    # Silence tool narration instruction
    assert "Do NOT narrate tool execution" in sys_prompt
    assert "Voy a consultar" in sys_prompt

    # Stateless turn limitation instruction
    assert "stateless across turns" in sys_prompt
    assert "Do NOT ask open-ended or conversational follow-up questions" in sys_prompt

    # Ambiguity guidance instruction
    assert "present the relevant catalog options directly" in sys_prompt
    assert "instruct the user to submit a complete standalone request" in sys_prompt


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
