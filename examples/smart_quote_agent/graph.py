"""LangGraph state graph compiling deterministic workflow and controlled agent nodes."""

from __future__ import annotations

import re
import sqlite3
import uuid
from collections.abc import Awaitable, Callable
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

from proteo_runtime.core.events import RuntimeEvent
from proteo_runtime.core.input import RuntimeInput, RuntimeMessage, TextContent
from proteo_runtime.core.model import RuntimeModel
from proteo_runtime.tools import (
    ApprovalHandler,
    ToolRequest,
)


def detect_language(text: str) -> str:
    """Detect whether user input is Spanish ('es') or English ('en').

    Args:
        text: User input string.

    Returns:
        'es' if Spanish characters or common terms are detected, otherwise 'en'.
    """
    clean = text.strip().lower()
    if any(char in clean for char in "áéíóúüñ¿¡"):
        return "es"
    spanish_words = {
        "hola",
        "buen",
        "dia",
        "dias",
        "tardes",
        "noches",
        "que",
        "como",
        "cuanto",
        "donde",
        "quien",
        "por",
        "para",
        "favor",
        "gracias",
        "de",
        "nada",
        "ayuda",
        "puedo",
        "hacer",
        "cosas",
        "podria",
        "iniciar",
        "sesion",
        "cerrar",
        "salir",
        "productos",
        "catalogo",
        "cotizacion",
        "cotizaciones",
        "presupuesto",
        "cotizar",
        "crear",
        "generar",
        "mostrar",
        "ver",
        "listar",
        "un",
        "una",
        "unos",
        "unas",
        "el",
        "la",
        "los",
        "las",
        "y",
        "o",
        "si",
        "no",
        "genial",
        "perfecto",
        "quisiera",
        "quiero",
        "necesito",
        "precio",
        "precios",
        "hay",
    }
    tokens = set(re.findall(r"\b\w+\b", clean))
    if tokens & spanish_words:
        return "es"
    return "en"


def allowed_actions(user: AuthenticatedUser | None) -> frozenset[str]:
    """Return the set of actions authorized for the current user role.

    Args:
        user: Currently authenticated user, or None if anonymous.

    Returns:
        Frozenset of authorized action strings.
    """
    if user is None:
        return frozenset({"login", "help", "acknowledgement", "catalog_query", "quote_preview"})
    if user.role == "staff":
        return frozenset(
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
    return frozenset({"logout", "help", "acknowledgement", "catalog_query", "quote_preview"})


def classify_intent_heuristic(text: str) -> str | None:
    """Classify user intent deterministically only when unequivocal.

    Args:
        text: Raw user input text.

    Returns:
        One of the canonical application actions, or None if ambiguous.
    """
    clean = text.strip().lower()
    if not clean:
        return "help"

    core = clean.strip("?¿!¡. ")

    # 1. Informational login questions (must classify as help, not trigger login action)
    if core in (
        "how can i login",
        "how can i log in",
        "how do i login",
        "how do i log in",
        "how to login",
        "how to log in",
        "how can i sign in",
        "how do i sign in",
        "como inicio sesion",
        "cómo inicio sesión",
        "como iniciar sesion",
        "cómo iniciar sesión",
        "como puedo iniciar sesion",
        "cómo puedo iniciar sesión",
        "como me logueo",
        "cómo me logueo",
        "como loguearme",
        "cómo loguearme",
        "como puedo loguearme",
        "cómo puedo loguearme",
    ):
        return "help"

    # 2. Unequivocal login action phrases
    if clean in ("login", "iniciar sesion", "iniciar sesión", "log in", "sign in", "quiero entrar"):
        return "login"

    # 3. Unequivocal logout phrases
    if clean in (
        "logout",
        "cerrar sesion",
        "cerrar sesión",
        "log out",
        "sign out",
        "salir de mi cuenta",
    ):
        return "logout"

    # 4. Acknowledgement phrases
    if core in (
        "gracias",
        "muchas gracias",
        "thanks",
        "thank you",
        "perfecto",
        "genial",
        "ok",
        "okay",
        "okey",
    ):
        return "acknowledgement"

    # 5. Unequivocal quote creation phrases
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

    # 6. Unequivocal help / capability / greeting phrases
    if core in (
        "help",
        "ayuda",
        "hola",
        "hello",
        "hi",
        "buen dia",
        "buen día",
        "buenos dias",
        "buenos días",
        "buenas tardes",
        "buenas",
        "que puedo hacer",
        "qué puedo hacer",
        "what can i do",
        "what things could i do",
        "what can you do",
        "que cosas podria hacer",
        "que cosas podría hacer",
        "qué cosas podria hacer",
        "qué cosas podría hacer",
        "para que sirve este agente",
        "para qué sirve este agente",
        "what is this agent for",
    ):
        return "help"

    # 7. Unequivocal catalog inquiries
    if clean in (
        "products",
        "productos",
        "catalogo",
        "catálogo",
        "catalog",
        "list products",
        "show products",
        "listar productos",
        "ver catalogo",
        "ver catálogo",
    ) or clean.startswith(
        (
            "list products",
            "show products",
            "listar productos",
            "ver catalogo",
            "ver catálogo",
        )
    ):
        return "catalog_query"

    # 8. Unequivocal quote history inquiries
    if clean in (
        "quotes",
        "cotizaciones",
        "show quotes",
        "list quotes",
        "show latest quotes",
        "show the latest quotes",
        "ver cotizaciones",
        "historial de cotizaciones",
    ) or clean.startswith(
        (
            "show quotes",
            "list quotes",
            "show the latest quotes",
            "show quote ",
            "ver cotizacion ",
            "ver cotización ",
        )
    ):
        return "quote_history"

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
    if match:
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

        return QuoteRequest(customer=customer or None, items=items)

    # Heuristic for partial: customer specified but no items
    match_cust = re.search(
        r"(?:create\s+quote|crear\s+cotizaci[oó]n|quote|cotizar)\s+(?:for|para)\s+([A-Za-z0-9_\s]+)$",
        clean,
        re.IGNORECASE,
    )
    if match_cust:
        cand = match_cust.group(1).strip()
        if not re.match(r"^\d+", cand):
            return QuoteRequest(customer=cand, items=[])

    # Heuristic for partial: items specified but no customer
    match_items = re.search(
        r"(?:create\s+quote|crear\s+cotizaci[oó]n|quote|cotizar)(?:\s+(?:for|para|de))?\s+(\d+\s+.+)$",
        clean,
        re.IGNORECASE,
    )
    if match_items:
        raw_items = match_items.group(1).strip()
        parts = re.split(r",|\band\b|\by\b", raw_items, flags=re.IGNORECASE)
        items = []
        for part in parts:
            item_match = re.search(r"(\d+)\s+([A-Za-z0-9_\s\"-]+)", part.strip())
            if item_match:
                qty = int(item_match.group(1))
                prod_name = item_match.group(2).strip()
                if qty > 0 and prod_name:
                    items.append(RequestedItem(product=prod_name, quantity=qty))
        if items:
            return QuoteRequest(customer=None, items=items)

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
    event_sink: Callable[[RuntimeEvent], Awaitable[Any]] | None = None,
) -> Any:
    """Assemble and compile the LangGraph StateGraph for Smart Quote Agent.

    Args:
        conn: Open SQLite database connection.
        structured_model: RuntimeModel bound with profile='structured', level='low'.
        controlled_agent_model: RuntimeModel bound with profile='controlled_turn', level='low'.
        approval_handler: Optional Phase 5 ApprovalHandler for write confirmation.
        discount_prompter: Optional callback for discount prompt (defaults to prompt_discount_interactive).
        auth_interactive: Optional callback for interactive login (defaults to authenticate_user_interactive).
        quote_reviewer: Optional callback to review quote before approval (defaults to default_quote_reviewer).
        event_sink: Optional async callable for exporting tool lifecycle events to telemetry.

    Returns:
        Compiled LangGraph runnable graph.
    """
    active_structured_model = structured_model
    active_controlled_agent_model = controlled_agent_model
    actual_approval_handler = approval_handler or ConsoleApprovalHandler()
    actual_discount_prompter = discount_prompter or prompt_discount_interactive
    actual_auth_interactive = auth_interactive or authenticate_user_interactive
    actual_quote_reviewer = quote_reviewer or default_quote_reviewer
    actual_event_sink = event_sink

    async def intent_router_node(state: DemoState) -> dict[str, Any]:
        """Classify user intent via deterministic rules or low-level structured classifier."""
        user_input = state.get("input", "")
        user = state.get("authenticated_user")

        # 1. Deterministic heuristic check
        heuristic = classify_intent_heuristic(user_input)
        if heuristic is not None:
            return {"intent": heuristic}

        # 2. Ambiguous phrasing: invoke structured model if available
        if active_structured_model is not None:
            role_label = user.role if user is not None else "anonymous"
            available = sorted(allowed_actions(user))
            instructions = (
                "You classify requests for the Smart Quote Agent.\n"
                f"Current access level: {role_label}\n"
                "Recognized application actions:\n"
                "- 'login': Explicit request to initiate login/sign in right now (e.g. 'login', 'sign in', 'iniciar sesión'). "
                "Informational questions about how to log in (e.g. 'How do I log in?', 'Cómo inicio sesión?') must be classified as 'help'.\n"
                "- 'logout': User wants to sign out.\n"
                "- 'help': User asks what the agent can do, asks for help, asks how to log in, greets the agent without "
                "another concrete request, or asks about the application itself.\n"
                "- 'acknowledgement': Polite acknowledgements or thanks (e.g. 'thanks', 'thank you', 'gracias', 'ok', 'perfecto').\n"
                "- 'catalog_query': Product, catalog, or price availability questions.\n"
                "- 'quote_preview': Non-persistent calculations or quote previews.\n"
                "- 'quote_history': List or inspect persisted quotes.\n"
                "- 'quote_create': Create or persist a new quote for a customer.\n"
                "- 'out_of_scope': Any request unrelated to Smart Quote Agent capabilities.\n"
                f"Actions currently available for this access level:\n"
                + "\n".join(f"- {act}" for act in available)
                + "\n\n"
                "Instructions:\n"
                "- Classify what the user is asking for.\n"
                "- Identify the requested action even if the current user is not allowed to perform it.\n"
                "- Use 'out_of_scope' when the request is unrelated to this application.\n"
                "- Do not map generic assistant tasks, programming, web research, arbitrary files, "
                "image generation, or unrelated knowledge questions into a supported action."
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

        # 3. Explicit offline deterministic fallback (provider-free)
        clean = user_input.strip().lower()
        core = clean.strip("?¿!¡. ")
        if core in (
            "gracias",
            "muchas gracias",
            "thanks",
            "thank you",
            "perfecto",
            "genial",
            "ok",
            "okay",
        ):
            return {"intent": "acknowledgement"}
        if any(
            term in clean
            for term in (
                "how can i login",
                "how do i login",
                "como inicio sesion",
                "cómo inicio sesión",
            )
        ):
            return {"intent": "help"}
        if any(
            term in clean
            for term in (
                "product",
                "producto",
                "notebook",
                "mouse",
                "keyboard",
                "precio",
                "price",
                "catalog",
                "catalogo",
            )
        ):
            return {"intent": "catalog_query"}
        if any(term in clean for term in ("calculate", "calcular", "preview", "preliminar")):
            return {"intent": "quote_preview"}
        if any(
            term in clean
            for term in (
                "quote #",
                "cotizacion #",
                "cotización #",
                "history",
                "historial",
                "show quotes",
                "list quotes",
            )
        ):
            return {"intent": "quote_history"}
        return {"intent": "out_of_scope"}

    async def scope_gate_node(state: DemoState) -> dict[str, Any]:
        """Apply host-owned action policy and handle help/out-of-scope requests deterministically."""
        intent = state.get("intent", "out_of_scope")
        user = state.get("authenticated_user")
        user_input = state.get("input", "")
        lang = detect_language(user_input)
        allowed = allowed_actions(user)

        # 1. Out-of-scope requests: short deterministic reply, never reach LLM
        if intent == "out_of_scope":
            msg = (
                "Esa solicitud está fuera del alcance de este agente. "
                "Puedo ayudarte a consultar productos, precios o calcular un presupuesto preliminar."
                if lang == "es"
                else (
                    "That request is outside the scope of this agent. "
                    "I can help you consult products, prices, or calculate a preliminary quote preview."
                )
            )
            return {
                "action_allowed": False,
                "output": msg,
            }

        # 2. Acknowledgement requests: short deterministic reply, never reach LLM
        if intent == "acknowledgement":
            msg = "De nada." if lang == "es" else "You're welcome."
            return {
                "action_allowed": True,
                "output": msg,
            }

        # 3. Help requests: role-specific deterministic capability summary, no LLM
        if intent == "help":
            clean = user_input.strip().lower()
            is_login_query = any(
                term in clean
                for term in (
                    "login",
                    "log in",
                    "iniciar sesion",
                    "iniciar sesión",
                    "inicio sesion",
                    "inicio sesión",
                    "loguear",
                    "logueo",
                    "sign in",
                )
            )
            if is_login_query:
                msg = (
                    "Escribí 'login' para iniciar sesión."
                    if lang == "es"
                    else "Type `login` to sign in."
                )
            elif user is None:
                msg = (
                    "Puedo ayudarte a consultar productos y precios o calcular presupuestos preliminares. "
                    "También podés iniciar sesión; las funciones adicionales dependen de tu rol."
                    if lang == "es"
                    else (
                        "I can help you consult products and prices or calculate preliminary quote previews. "
                        "You can also log in; additional capabilities depend on your role."
                    )
                )
            elif user.role == "client":
                msg = (
                    "Puedo ayudarte a consultar productos y precios o calcular presupuestos preliminares. "
                    "También podés cerrar sesión con 'logout'."
                    if lang == "es"
                    else (
                        "I can help you consult products and prices or calculate preliminary quote previews. "
                        "You can also log out using 'logout'."
                    )
                )
            else:
                msg = (
                    "Puedo consultar productos y precios, calcular presupuestos preliminares, "
                    "crear cotizaciones e inspeccionar el historial de cotizaciones. "
                    "También podés cerrar sesión con 'logout'."
                    if lang == "es"
                    else (
                        "I can consult products and prices, calculate preliminary quote previews, "
                        "create quotes, and inspect persisted quote history. You can also log out using 'logout'."
                    )
                )
            return {
                "action_allowed": True,
                "output": msg,
            }

        # 4. Action recognized but forbidden for the current role
        if intent not in allowed:
            if intent == "logout" and user is None:
                msg = (
                    "No hay una sesión activa para cerrar. Podés iniciar sesión con 'login'."
                    if lang == "es"
                    else "No active session to log out from. You can log in using 'login'."
                )
                return {
                    "action_allowed": False,
                    "output": msg,
                }
            if intent == "login" and user is not None:
                msg = (
                    f"Ya iniciaste sesión como {user.display_name} ({user.role}). "
                    "Para cambiar de cuenta, primero cerrá sesión con 'logout'."
                    if lang == "es"
                    else (
                        f"Already logged in as {user.display_name} ({user.role}). "
                        "To switch accounts, please log out first using 'logout'."
                    )
                )
                return {
                    "action_allowed": False,
                    "output": msg,
                }
            if intent == "quote_history":
                msg = (
                    "El historial de cotizaciones está disponible únicamente para el personal (staff). "
                    "Podés consultar productos, precios o calcular un presupuesto preliminar."
                    if lang == "es"
                    else (
                        "Quote history is available to staff only. "
                        "You can consult products, prices, or calculate a quote preview."
                    )
                )
                return {
                    "action_allowed": False,
                    "output": msg,
                }
            if intent == "quote_create":
                msg = (
                    "Acceso denegado. Las cotizaciones guardadas solo pueden ser creadas por el personal (staff)."
                    if lang == "es"
                    else "Access denied. Persisted quotes can only be created by staff."
                )
                return {
                    "action_allowed": False,
                    "quote_authorized": False,
                    "output": msg,
                }
            msg = (
                "Esta acción no está disponible para tu nivel de acceso actual."
                if lang == "es"
                else "This action is not available for your current access level."
            )
            return {
                "action_allowed": False,
                "output": msg,
            }

        # 5. Action is authorized
        return {"action_allowed": True}

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
        lang = detect_language(user_input)
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
        has_customer = bool(req is not None and req.customer and req.customer.strip())
        has_items = bool(req is not None and req.items and len(req.items) > 0)

        if not has_customer and not has_items:
            msg = (
                "No se pudieron extraer los detalles de la cotización. "
                "Por favor especifica tanto el nombre del cliente como los productos con sus cantidades "
                "(ej. 'Crear cotización para Globex de 2 Notebook Pro')."
                if lang == "es"
                else (
                    "Could not extract quote details. "
                    "Please specify both the customer name and items with quantities "
                    "(e.g. 'Create a quote for Globex for 2 Notebook Pro')."
                )
            )
            return {"quote_request": None, "output": msg}

        if not has_customer:
            msg = (
                "Se requiere el nombre o identificador del cliente para crear una cotización. "
                "Por favor especifica el cliente (ej. 'para Globex')."
                if lang == "es"
                else (
                    "A customer name or identifier is required to create a quote. "
                    "Please specify the customer (e.g. 'for Globex')."
                )
            )
            return {"quote_request": None, "output": msg}

        if not has_items:
            msg = (
                "Se requiere al menos un producto y su cantidad para crear una cotización. "
                "Por favor especifica los productos (ej. '2 Notebook Pro')."
                if lang == "es"
                else (
                    "At least one product and quantity are required to create a quote. "
                    "Please specify the items (e.g. '2 Notebook Pro')."
                )
            )
            return {"quote_request": None, "output": msg}

        assert req is not None
        for item in req.items:
            if not item.product or item.quantity is None or item.quantity <= 0:
                msg = (
                    "Detalles de producto incompletos en la solicitud de cotización. "
                    "Cada producto debe especificar un nombre válido y una cantidad positiva."
                    if lang == "es"
                    else (
                        "Incomplete item details in quote request. "
                        "Each item must specify a valid product name and positive quantity."
                    )
                )
                return {
                    "quote_request": None,
                    "output": msg,
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
            event_sink=actual_event_sink,
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
            event_sink=actual_event_sink,
        )

        role_label = user.role if user is not None else "anonymous"
        tool_names = [d.name for d in agent_registry.definitions()]

        # If a live controlled agent model is available, invoke it directly
        if active_controlled_agent_model is not None:
            agent_model = active_controlled_agent_model.with_tools(
                agent_registry, executor=executor
            )
            system_instruction = (
                "You are ONLY the Smart Quote Agent for this application.\n"
                f"Current role: {role_label}\n"
                f"Available conversational tools: {', '.join(tool_names)}\n\n"
                "Rules:\n"
                "- Your conversational scope is strictly limited to product exploration, "
                "authoritative pricing inquiries, non-persisted quote calculations, and quote reviews (staff only).\n"
                "- Do not answer general-purpose requests outside this scope.\n"
                "- Do not claim capabilities simply because the underlying model could normally perform them.\n"
                "- You do NOT have arbitrary internet browsing, filesystem access, code execution/editing, "
                "image generation, document analysis, external connected applications, shell access, or "
                "unrestricted network tools.\n"
                "- Always use host-managed tools for business facts. Never invent products, prices, "
                "customers, or persisted quotes.\n"
                "- Do NOT narrate tool execution, intermediate steps, or progress (e.g., never say "
                "'Voy a consultar...', 'Let me check...', or 'Voy a revisar el catálogo...'). "
                "NEVER send intermediate thinking or announcements before invoking tools. "
                "Query tools directly and return only the final synthesized answer to the user.\n"
                "- Each interaction is completely stateless across turns. Do NOT ask open-ended or "
                "conversational follow-up questions expecting context preservation across turns "
                "(such as '¿Cuál de ellos te interesa?' or 'Which one do you prefer?').\n"
                "- If a query is broad or ambiguous, present the relevant catalog options directly and "
                "instruct the user to submit a complete standalone request specifying the exact product name and quantity "
                "(e.g., 'Por favor indica el producto exacto y la cantidad que deseas cotizar o consultar.').\n"
                "- Reply in the user's language.\n"
                "- Treat tool permission denial as authoritative.\n"
                "- Never claim that quote persistence occurred unless a host tool reports success.\n"
                "- If an out-of-scope request reaches this node unexpectedly, do not answer the request. "
                "Return only: 'That request is outside the scope of this agent. I can help you consult "
                "products, prices, or calculate a preliminary quote preview.'"
            )
            runtime_input = RuntimeInput(
                (
                    RuntimeMessage("system", (TextContent(system_instruction),)),
                    RuntimeMessage("user", (TextContent(user_input),)),
                )
            )
            res = await agent_model.ainvoke(runtime_input)
            output_text = str(res.value).strip()
            output_text = re.sub(
                r"^(?:(?:Voy a (?:consultar|revisar|verificar)|Let me check|I will check)[^\n.!?]+[.!?]\s*)+",
                "",
                output_text,
                flags=re.IGNORECASE,
            ).strip()
            return {"output": output_text}

        # Offline deterministic query routing for tests without Codex
        clean = user_input.lower()
        if (
            "notebook" in clean
            or "product" in clean
            or "catalogo" in clean
            or "catalog" in clean
            or "accessories" in clean
            or "mouse" in clean
            or "keyboard" in clean
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

        return {
            "output": (
                "That request is outside the scope of this agent. "
                "I can help you consult products, prices, or calculate a preliminary quote preview."
            )
        }

    async def final_output_node(state: DemoState) -> dict[str, Any]:
        """Ensure final output text is present."""
        return {"output": state.get("output", "")}

    def route_scope_gate(state: DemoState) -> str:
        """Route user request from the host scope gate according to authorization and intent.

        Args:
            state: Current graph state.

        Returns:
            Target node name in the LangGraph StateGraph.
        """
        intent = state.get("intent", "out_of_scope")
        action_allowed = state.get("action_allowed")

        if not action_allowed or intent in ("help", "acknowledgement"):
            return "final_output"

        if intent == "login":
            return "login_hitl"
        if intent == "logout":
            return "clear_auth"
        if intent == "quote_create":
            return "auth_guard"
        if intent in ("catalog_query", "quote_preview", "quote_history"):
            return "controlled_agent"

        return "final_output"

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
    builder.add_node("scope_gate", scope_gate_node)
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
    builder.add_edge("intent_router", "scope_gate")
    builder.add_conditional_edges(
        "scope_gate",
        route_scope_gate,
        {
            "login_hitl": "login_hitl",
            "clear_auth": "clear_auth",
            "auth_guard": "auth_guard",
            "controlled_agent": "controlled_agent",
            "final_output": "final_output",
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
