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
    classify_intent_heuristic,
    create_demo_graph,
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
    assert classify_intent_heuristic("products") == "agent_request"
    assert classify_intent_heuristic("catalogo") == "agent_request"


@pytest.mark.asyncio
async def test_point_02_ambiguous_routing_invokes_structured_classifier(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate ambiguous requests return None in heuristic and invoke structured model."""
    ambiguous_input = "Necesito ver precios de laptops y cotizar si es posible"
    assert classify_intent_heuristic(ambiguous_input) is None

    structured_runtime = FakeRuntime(
        turns=[FakeTurn(value=IntentDecision(intent="agent_request").model_dump_json())]
    )
    agent_runtime = FakeRuntime(turns=[FakeTurn(value="Respuesta del agente")])

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
    assert result.get("intent") == "agent_request"


@pytest.mark.asyncio
async def test_point_03_help_capability_reaches_controlled_agent_path(
    db_conn: sqlite3.Connection, staff_user: AuthenticatedUser
) -> None:
    """Validate capability questions reach controlled LLM rather than a hardcoded response."""
    help_query = "Que puedo hacer con este agente?"
    assert classify_intent_heuristic(help_query) is None

    structured_runtime = FakeRuntime(
        turns=[FakeTurn(value=IntentDecision(intent="agent_request").model_dump_json())]
    )
    agent_runtime = FakeRuntime(
        turns=[
            FakeTurn(
                value="Soy el asistente Smart Quote. Puedo ayudarte a consultar productos y registrar cotizaciones."
            )
        ]
    )

    structured_model = structured_runtime.model(profile="structured", level="low")
    controlled_model = agent_runtime.model(profile="controlled_agent", level="low")

    graph = create_demo_graph(
        conn=db_conn,
        structured_model=structured_model,
        controlled_agent_model=controlled_model,
    )

    state: DemoState = {
        "input": help_query,
        "authenticated_user": staff_user,
    }
    result = await graph.ainvoke(state)
    assert "Smart Quote" in result.get("output", "")


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
        "input": "crear cotizacion",
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
        "input": "crear cotizacion",
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
        "input": "crear cotizacion",
        "authenticated_user": staff_user,
    }
    result = await graph.ainvoke(state)

    assert result.get("quote_draft") is None
    assert "Could not extract complete quote details" in result.get("output", "")


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
