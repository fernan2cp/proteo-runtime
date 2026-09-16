"""LangGraph state graph compiling deterministic workflow and controlled agent nodes."""

from __future__ import annotations

import re
import sqlite3
import uuid
from collections.abc import Callable
from typing import Any, cast

from auth import authenticate_user_interactive, get_permission_policy_for_user
from database import (
    calculate_discount_amount,
    find_customer_by_query,
    find_product_by_query,
    format_currency,
    list_active_products,
)
from hitl import ConsoleApprovalHandler, prompt_discount_interactive
from langgraph.graph import END, START, StateGraph
from models import (
    AuthenticatedUser,
    DemoState,
    IntentDecision,
    QuoteDraft,
    QuoteLineDraft,
    QuoteRequest,
    RequestedItem,
)
from tools import (
    create_tool_executor,
    get_agent_tool_registry,
    get_quote_write_registry,
)

from proteo_runtime.core.input import RuntimeInput, RuntimeMessage, TextContent
from proteo_runtime.core.model import RuntimeModel
from proteo_runtime.tools import (
    ApprovalHandler,
    ToolRequest,
)


def classify_intent_heuristic(text: str) -> str | None:
    """Classify user intent deterministically only when unequivocal.

    Args:
        text: Raw user input text.

    Returns:
        One of 'login', 'logout', 'quote_create', 'agent_request', or None if ambiguous.
    """
    clean = text.strip().lower()
    if not clean:
        return "agent_request"

    # 1. Unequivocal login phrases
    if clean in ("login", "iniciar sesion", "iniciar sesión", "log in", "sign in", "quiero entrar"):
        return "login"

    # 2. Unequivocal logout phrases
    if clean in (
        "logout",
        "cerrar sesion",
        "cerrar sesión",
        "log out",
        "sign out",
        "salir de mi cuenta",
    ):
        return "logout"

    # 3. Unequivocal quote creation phrases
    if clean.startswith(
        (
            "create quote",
            "crear cotizacion",
            "crear cotización",
            "new quote",
            "nueva cotizacion",
            "nueva cotización",
            "generar cotizacion",
            "generar cotización",
            "build quote",
            "presupuesto para",
            "cotizar para",
        )
    ) or bool(
        re.search(
            r"^(create|crear|generar|build)\s+(a\s+)?(quote|cotizaci[oó]n|presupuesto)\b", clean
        )
    ):
        return "quote_create"

    # 4. Unequivocal read-only catalog / help / quote list inquiries
    if clean in (
        "help",
        "ayuda",
        "products",
        "productos",
        "catalogo",
        "catálogo",
        "list products",
        "show products",
        "listar productos",
        "ver catalogo",
        "ver catálogo",
        "quotes",
        "cotizaciones",
        "show quotes",
        "list quotes",
        "show latest quotes",
        "show the latest quotes",
        "ver cotizaciones",
    ) or clean.startswith(
        (
            "list products",
            "show products",
            "show quotes",
            "list quotes",
            "show the latest quotes",
            "show quote ",
        )
    ):
        return "agent_request"

    # Anything genuinely ambiguous or open-ended
    return None


def parse_quote_request_heuristic(text: str) -> QuoteRequest | None:
    """Heuristically extract customer and item quantities from a quote request.

    Example input: 'Create a quote for Globex for 3 Notebook Pro and 5 Wireless Mouse.'

    Args:
        text: User quote request text.

    Returns:
        QuoteRequest if parsed, or None.
    """
    clean = text.strip()
    match = re.search(r"for\s+([A-Za-z0-9_\s]+?)\s+for\s+(.+)$", clean, re.IGNORECASE)
    if not match:
        match = re.search(
            r"para\s+([A-Za-z0-9_\s]+?)\s+(?:por|con|de)\s+(.+)$", clean, re.IGNORECASE
        )
    if not match:
        return None

    customer = match.group(1).strip()
    raw_items = match.group(2).strip()

    parts = re.split(r",|\band\b|\by\b", raw_items, flags=re.IGNORECASE)
    items: list[RequestedItem] = []

    for part in parts:
        item_match = re.search(r"(\d+)\s+([A-Za-z0-9_\s\"-]+)", part.strip())
        if item_match:
            qty = int(item_match.group(1))
            prod_name = item_match.group(2).strip()
            if qty > 0 and prod_name:
                items.append(RequestedItem(product=prod_name, quantity=qty))

    if customer and items:
        return QuoteRequest(customer=customer, items=items)
    return None


def default_quote_reviewer(draft: QuoteDraft) -> None:
    """Print an authoritative host-generated review summary for a quote draft.

    Args:
        draft: Authoritative quote draft dictionary.
    """
    print("\n" + "=" * 50)
    print("HOST QUOTE REVIEW")
    print("=" * 50)
    print(f"Customer: {draft['customer_name']} (ID: {draft['customer_id']})")
    print("Line items:")
    for line in draft["lines"]:
        print(
            f"  - {line['name']} ({line['sku']}): {line['quantity']}x @ "
            f"{format_currency(line['unit_price_cents'])} = {format_currency(line['subtotal_cents'])}"
        )
    print(f"Subtotal:        {format_currency(draft['subtotal_cents'])}")
    print(
        f"Discount:        {draft['discount_percent']}% ({format_currency(draft['discount_amount_cents'])})"
    )
    print(f"Total:           {format_currency(draft['total_cents'])}")
    print("=" * 50)


def create_demo_graph(
    conn: sqlite3.Connection,
    *,
    structured_model: RuntimeModel[Any] | None = None,
    controlled_agent_model: RuntimeModel[Any] | None = None,
    approval_handler: ApprovalHandler | None = None,
    discount_prompter: Callable[[int], int] | None = None,
    auth_interactive: Callable[[sqlite3.Connection], AuthenticatedUser | None] | None = None,
    quote_reviewer: Callable[[QuoteDraft], None] | None = None,
) -> Any:
    """Assemble and compile the LangGraph StateGraph for Smart Quote Agent.

    Args:
        conn: Open SQLite database connection.
        structured_model: RuntimeModel bound with profile='structured', level='low'.
        controlled_agent_model: RuntimeModel bound with profile='controlled_agent', level='low'.
        approval_handler: Optional Phase 5 ApprovalHandler for write confirmation.
        discount_prompter: Optional callback for discount prompt (defaults to prompt_discount_interactive).
        auth_interactive: Optional callback for interactive login (defaults to authenticate_user_interactive).
        quote_reviewer: Optional callback to review quote before approval (defaults to default_quote_reviewer).

    Returns:
        Compiled LangGraph runnable graph.
    """
    active_structured_model = structured_model
    active_controlled_agent_model = controlled_agent_model
    actual_approval_handler = approval_handler or ConsoleApprovalHandler()
    actual_discount_prompter = discount_prompter or prompt_discount_interactive
    actual_auth_interactive = auth_interactive or authenticate_user_interactive
    actual_quote_reviewer = quote_reviewer or default_quote_reviewer

    async def intent_router_node(state: DemoState) -> dict[str, Any]:
        """Classify user intent via deterministic rules or low-level structured classifier."""
        user_input = state.get("input", "")

        # 1. Deterministic heuristic check
        heuristic = classify_intent_heuristic(user_input)
        if heuristic is not None:
            return {"intent": heuristic}

        # 2. Ambiguous phrasing: invoke structured model if available
        if active_structured_model is not None:
            instructions = (
                "You are an intent classifier for the Smart Quote Agent CLI. "
                "Classify the user input into exactly one of these four categories:\n"
                "- 'login': The user wants to sign in, log in, or authenticate.\n"
                "- 'logout': The user wants to sign out, log out, or exit their account.\n"
                "- 'quote_create': The user wants to create, generate, or initiate a new quote/budget for a customer.\n"
                "- 'agent_request': The user is exploring products, asking about prices, requesting calculations, "
                "asking about system capabilities, or inspecting quote history.\n"
            )
            runtime_input = RuntimeInput(
                (
                    RuntimeMessage("system", (TextContent(instructions),)),
                    RuntimeMessage("user", (TextContent(user_input),)),
                )
            )
            structured_router = active_structured_model.with_structured_output(IntentDecision)
            res = await structured_router.ainvoke(runtime_input)
            decision = cast(IntentDecision, res.value)
            return {"intent": decision.intent}

        # 3. Fallback when offline
        return {"intent": "agent_request"}

    async def login_hitl_node(state: DemoState) -> dict[str, Any]:
        """Execute interactive login and record sanitized identity."""
        user = actual_auth_interactive(conn)
        if user is not None:
            return {
                "authenticated_user": user,
                "output": f"Logged in as {user.display_name} ({user.role})",
            }
        return {"output": "Login failed: invalid username or password."}

    async def clear_auth_node(state: DemoState) -> dict[str, Any]:
        """Clear authenticated identity from graph state."""
        return {
            "authenticated_user": None,
            "output": "Logged out. Continuing as anonymous.",
        }

    async def auth_guard_node(state: DemoState) -> dict[str, Any]:
        """Enforce staff authorization for quote creation workflow."""
        user = state.get("authenticated_user")
        if user is None or user.role != "staff":
            return {
                "quote_authorized": False,
                "output": "Access denied. Persisted quotes can only be created by staff.",
            }
        return {"quote_authorized": True}

    async def quote_planner_node(state: DemoState) -> dict[str, Any]:
        """Extract customer and requested product items from request text."""
        user_input = state.get("input", "")
        req: QuoteRequest | None = None

        if active_structured_model is not None:
            instructions = (
                "Extract quote creation parameters explicitly present in the user request.\n"
                "- customer: Customer name or identifier explicitly stated, or null if omitted.\n"
                "- items: List of requested products and quantities explicitly stated.\n"
                "CRITICAL: Never invent or guess a customer. Never invent a product or quantity.\n"
                "If information is missing, leave the field null or items empty."
            )
            runtime_input = RuntimeInput(
                (
                    RuntimeMessage("system", (TextContent(instructions),)),
                    RuntimeMessage("user", (TextContent(user_input),)),
                )
            )
            structured_planner = active_structured_model.with_structured_output(QuoteRequest)
            res = await structured_planner.ainvoke(runtime_input)
            req = cast(QuoteRequest, res.value)
        else:
            req = parse_quote_request_heuristic(user_input)

        # Validate completeness host-side
        if req is None or not req.customer or not req.items:
            return {
                "quote_request": None,
                "output": (
                    "Could not extract complete quote details. "
                    "Please specify both the customer name and items with quantities "
                    "(e.g. 'Create a quote for Globex for 2 Notebook Pro')."
                ),
            }

        for item in req.items:
            if not item.product or item.quantity is None or item.quantity <= 0:
                return {
                    "quote_request": None,
                    "output": (
                        "Incomplete item details in quote request. "
                        "Each item must specify a valid product name and positive quantity."
                    ),
                }

        return {"quote_request": req}

    async def resolve_quote_data_node(state: DemoState) -> dict[str, Any]:
        """Resolve customer and product IDs and re-read authoritative DB prices."""
        req = state.get("quote_request")
        if req is None or not req.customer:
            return {"output": "Missing quote request."}

        cust = find_customer_by_query(conn, req.customer)
        if cust is None:
            return {"output": f"Customer '{req.customer}' not found in database."}
        if cust.get("ambiguous"):
            return {"output": str(cust["message"])}

        draft_lines: list[QuoteLineDraft] = []
        subtotal_cents = 0

        for item in req.items:
            if item.product is None or item.quantity is None:
                continue
            prod = find_product_by_query(conn, item.product)
            if prod is None:
                return {"output": f"Product '{item.product}' not found in active catalog."}
            if prod.get("ambiguous"):
                return {"output": str(prod["message"])}

            unit_price = int(prod["unit_price_cents"])
            line_subtotal = unit_price * item.quantity
            subtotal_cents += line_subtotal
            draft_lines.append(
                {
                    "product_id": int(prod["id"]),
                    "sku": str(prod["sku"]),
                    "name": str(prod["name"]),
                    "quantity": item.quantity,
                    "unit_price_cents": unit_price,
                    "subtotal_cents": line_subtotal,
                }
            )

        draft: QuoteDraft = {
            "customer_id": int(cust["id"]),
            "customer_name": str(cust["name"]),
            "lines": draft_lines,
            "subtotal_cents": subtotal_cents,
            "discount_percent": 0,
            "discount_amount_cents": 0,
            "total_cents": subtotal_cents,
        }
        return {"quote_draft": draft}

    async def discount_hitl_node(state: DemoState) -> dict[str, Any]:
        """Interactively prompt human for discount and display quote review."""
        draft = state.get("quote_draft")
        if draft is None:
            return {}

        discount_pct = actual_discount_prompter(draft["subtotal_cents"])
        discount_amount = calculate_discount_amount(draft["subtotal_cents"], discount_pct)
        total_cents = draft["subtotal_cents"] - discount_amount

        updated_draft: QuoteDraft = {
            "customer_id": draft["customer_id"],
            "customer_name": draft["customer_name"],
            "lines": draft["lines"],
            "subtotal_cents": draft["subtotal_cents"],
            "discount_percent": discount_pct,
            "discount_amount_cents": discount_amount,
            "total_cents": total_cents,
        }

        # Display host quote review before approval
        actual_quote_reviewer(updated_draft)

        return {"quote_draft": updated_draft}

    async def create_quote_tool_node(state: DemoState) -> dict[str, Any]:
        """Execute create_quote tool through ToolExecutor with approval handling."""
        draft = state.get("quote_draft")
        if draft is None:
            return {"output": "No quote draft available to create."}

        user = state.get("authenticated_user")
        if user is None or user.role != "staff":
            return {"output": "Staff authentication required to persist quote."}

        # Dedicated write registry containing create_quote bound to the active staff user
        write_registry = get_quote_write_registry(conn, user)
        executor = create_tool_executor(
            write_registry,
            user,
            approval_handler=actual_approval_handler,
        )

        items_payload = [
            {"product_id": line["product_id"], "quantity": line["quantity"]}
            for line in draft["lines"]
        ]

        inv_id = f"quote-inv-{uuid.uuid4().hex}"
        call_id = f"quote-call-{uuid.uuid4().hex}"

        tool_req = ToolRequest(
            inv_id,
            call_id,
            "create_quote",
            {
                "customer_id": draft["customer_id"],
                "items": items_payload,
                "discount_percent": draft["discount_percent"],
            },
        )

        try:
            res = await executor.execute(tool_req)
        finally:
            executor.end_invocation(inv_id)

        if res.success:
            val = res.as_provider_value()
            return {
                "created_quote_id": val.get("quote_id"),
                "output": (
                    f"[SUCCESS] Quote #{val.get('quote_id')} created for {val.get('customer_name')}.\n"
                    f"Total: {val.get('total')}"
                ),
            }
        if res.denied:
            return {"output": "Quote creation was denied by user. Nothing was persisted."}
        return {"output": f"Quote creation failed: {res.error_code}"}

    async def controlled_agent_node(state: DemoState) -> dict[str, Any]:
        """Execute controlled agent inquiries against host-managed tools."""
        user = state.get("authenticated_user")
        user_input = state.get("input", "")

        # Agent registry never exposes create_quote
        agent_registry = get_agent_tool_registry(conn, user)
        executor = create_tool_executor(
            agent_registry,
            user,
            approval_handler=actual_approval_handler,
        )

        # If a live controlled agent model is available, invoke it directly
        if active_controlled_agent_model is not None:
            agent_model = active_controlled_agent_model.with_tools(
                agent_registry, executor=executor
            )
            system_instruction = (
                "You are the Smart Quote Agent, a helpful assistant for product exploration, "
                "authoritative pricing inquiries, non-persisted quote calculations, and quote record reviews.\n"
                "Rules:\n"
                "- Explore products and retrieve authoritative prices using host-managed tools.\n"
                "- Calculate non-persisted quote previews using calculate_quote.\n"
                "- Inspect persisted quote history using list_quotes and get_quote only when host permissions allow it.\n"
                "- Explain your own capabilities accurately when asked.\n"
                "- Always use tools for business facts rather than inventing products, prices, quotes, or customers.\n"
                "- Reply in the user's language.\n"
                "- Treat tool permission denial as authoritative.\n"
                "- Never claim that quote persistence occurred unless the host tool reports success."
            )
            runtime_input = RuntimeInput(
                (
                    RuntimeMessage("system", (TextContent(system_instruction),)),
                    RuntimeMessage("user", (TextContent(user_input),)),
                )
            )
            res = await agent_model.ainvoke(runtime_input)
            return {"output": str(res.value)}

        # Offline deterministic query routing for tests without Codex
        clean = user_input.lower()
        if (
            "notebook" in clean
            or "product" in clean
            or "catalogo" in clean
            or "catalog" in clean
            or "accessories" in clean
        ):
            prods = list_active_products(conn)
            lines = [
                f"- {p['name']} ({p['sku']}): {format_currency(p['unit_price_cents'])}"
                for p in prods
            ]
            return {"output": "Available products:\n" + "\n".join(lines)}

        if "quote" in clean or "cotizaci" in clean:
            policy = get_permission_policy_for_user(user)
            if not policy.allows("quote.read"):
                return {"output": "Access denied. Quote records are available to staff only."}
            match_id = re.search(r"quote\s+#?(\d+)", clean)
            if match_id:
                qid = int(match_id.group(1))
                inv_id = f"agent-inv-{uuid.uuid4().hex}"
                call_id = f"agent-call-{uuid.uuid4().hex}"
                try:
                    tool_res = await executor.execute(
                        ToolRequest(inv_id, call_id, "get_quote", {"quote_id": qid})
                    )
                finally:
                    executor.end_invocation(inv_id)

                if tool_res.success:
                    val = tool_res.as_provider_value()
                    lines_fmt = "\n".join(
                        f"  {line_item['quantity']}x {line_item['name']} ({line_item['unit_price']}) = {line_item['subtotal']}"
                        for line_item in val.get("lines", [])
                    )
                    return {
                        "output": (
                            f"Quote #{val['quote_id']} for {val['customer_name']}:\n"
                            f"{lines_fmt}\n"
                            f"Subtotal: {val['subtotal']}\n"
                            f"Discount: {val['discount_percent']}% ({val['discount_amount']})\n"
                            f"Total: {val['total']}"
                        )
                    }
                return {"output": f"Quote #{qid} not found."}

            inv_id = f"agent-inv-{uuid.uuid4().hex}"
            call_id = f"agent-call-{uuid.uuid4().hex}"
            try:
                tool_res = await executor.execute(
                    ToolRequest(inv_id, call_id, "list_quotes", {"limit": 10})
                )
            finally:
                executor.end_invocation(inv_id)

            if tool_res.success:
                quotes_list = tool_res.as_provider_value()
                if not quotes_list:
                    return {"output": "No quotes found in system."}
                fmt = "\n".join(
                    f"- Quote #{q['id']} ({q['customer_name']}): {q['total']}" for q in quotes_list
                )
                return {"output": f"Recent quotes:\n{fmt}"}

        return {"output": "I can help you explore products, calculate previews, or manage quotes."}

    async def final_output_node(state: DemoState) -> dict[str, Any]:
        """Ensure final output text is present."""
        return {"output": state.get("output", "")}

    def route_intent(state: DemoState) -> str:
        intent = state.get("intent", "agent_request")
        if intent == "login":
            return "login_hitl"
        if intent == "logout":
            return "clear_auth"
        if intent == "quote_create":
            return "auth_guard"
        return "controlled_agent"

    def route_auth_guard(state: DemoState) -> str:
        if state.get("quote_authorized") is not True:
            return "final_output"
        return "quote_planner"

    def route_quote_planner(state: DemoState) -> str:
        if state.get("quote_request") is not None:
            return "resolve_quote_data"
        return "final_output"

    def route_resolve_data(state: DemoState) -> str:
        if state.get("quote_draft") is not None:
            return "discount_hitl"
        return "final_output"

    builder = StateGraph(DemoState)

    builder.add_node("intent_router", intent_router_node)
    builder.add_node("login_hitl", login_hitl_node)
    builder.add_node("clear_auth", clear_auth_node)
    builder.add_node("auth_guard", auth_guard_node)
    builder.add_node("quote_planner", quote_planner_node)
    builder.add_node("resolve_quote_data", resolve_quote_data_node)
    builder.add_node("discount_hitl", discount_hitl_node)
    builder.add_node("create_quote_tool", create_quote_tool_node)
    builder.add_node("controlled_agent", controlled_agent_node)
    builder.add_node("final_output", final_output_node)

    builder.add_edge(START, "intent_router")
    builder.add_conditional_edges(
        "intent_router",
        route_intent,
        {
            "login_hitl": "login_hitl",
            "clear_auth": "clear_auth",
            "auth_guard": "auth_guard",
            "controlled_agent": "controlled_agent",
        },
    )

    builder.add_conditional_edges(
        "auth_guard",
        route_auth_guard,
        {
            "quote_planner": "quote_planner",
            "final_output": "final_output",
        },
    )

    builder.add_conditional_edges(
        "quote_planner",
        route_quote_planner,
        {
            "resolve_quote_data": "resolve_quote_data",
            "final_output": "final_output",
        },
    )

    builder.add_conditional_edges(
        "resolve_quote_data",
        route_resolve_data,
        {
            "discount_hitl": "discount_hitl",
            "final_output": "final_output",
        },
    )

    builder.add_edge("discount_hitl", "create_quote_tool")
    builder.add_edge("create_quote_tool", "final_output")

    builder.add_edge("login_hitl", "final_output")
    builder.add_edge("clear_auth", "final_output")
    builder.add_edge("controlled_agent", "final_output")
    builder.add_edge("final_output", END)

    return builder.compile()
