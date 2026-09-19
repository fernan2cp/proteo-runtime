"""LangGraph state graph compiling deterministic workflow and controlled agent nodes."""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from inspect import signature
from time import perf_counter
from typing import Any, Literal, cast

from auth import authenticate_user_interactive, get_permission_policy_for_user
from database import (
    calculate_discount_amount,
    find_customer_by_query,
    find_product_by_query,
    format_currency,
    list_active_products,
    list_customers,
)
from hitl import ConsoleApprovalHandler, prompt_discount_interactive
from langgraph.graph import END, START, StateGraph
from models import (
    AddItemOperation,
    AuthenticatedUser,
    DemoState,
    QuoteDraft,
    QuoteItemInput,
    QuoteLineDraft,
    QuotePatch,
    QuotePatchOperation,
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
from session import AgentSessionManager
from tools import (
    create_tool_executor,
    get_agent_tool_registry,
    get_quote_write_registry,
)

from proteo_runtime.core.events import RuntimeEvent
from proteo_runtime.core.input import RuntimeInput, RuntimeMessage, TextContent
from proteo_runtime.core.model import InvocationConfig, RuntimeModel
from proteo_runtime.core.task import RuntimeTask
from proteo_runtime.tools import (
    ApprovalHandler,
    ToolRequest,
)

_PREVIEW_PRODUCT_ALIASES = {
    "dock": "DOCK-USBC",
    "docks": "DOCK-USBC",
    "usb c dock": "DOCK-USBC",
    "mouse": "MS-WL",
    "mice": "MS-WL",
    "mouses": "MS-WL",
    "raton": "MS-WL",
    "wireless mouse": "MS-WL",
    "keyboard": "KB-MECH",
    "keyboards": "KB-MECH",
    "teclado": "KB-MECH",
    "mechanical keyboard": "KB-MECH",
    "monitor": "MON-27",
    "monitors": "MON-27",
    "notebook pro": "NB-PRO",
    "pro notebook": "NB-PRO",
    "notebook air": "NB-AIR",
    "air notebook": "NB-AIR",
    "notebook": "notebook",
    "notebooks": "notebook",
    "laptop": "notebook",
    "laptops": "notebook",
}

_PREVIEW_QUANTITIES = {
    "a": 1,
    "an": 1,
    "one": 1,
    "un": 1,
    "una": 1,
    "uno": 1,
    "two": 2,
    "dos": 2,
    "three": 3,
    "tres": 3,
    "four": 4,
    "cuatro": 4,
    "five": 5,
    "cinco": 5,
}

_TURN_DECISION_SYSTEM_PROMPT = """You classify turns for the Smart Quote Agent and extract quote data in the same response.
Return only the requested structured TurnDecision.

Supported intents: login, logout, help, acknowledgement, catalog_query, quote_preview,
quote_history, customer_query, quote_create, out_of_scope, clarification.

Classify the requested action, even when the current role is not allowed to perform it.
An explicit command to sign in is login; a question about how to sign in is help. Use
catalog_query for product, availability, or price questions; quote_preview for a
non-persistent calculation; quote_history to inspect saved quotes; customer_query to
list or search customers; and out_of_scope only for requests unrelated to this application.
Do not map programming, web research, files, image generation, or unrelated knowledge
questions to a supported action.

For quote_create, use quote_request for a new quote or an explicit complete restatement.
Use quote_patch only when a pending quote is supplied and the turn makes a targeted edit.
Never return both. A customer-only continuation uses set_customer. A partial new request
uses quote_request with only the explicitly stated customer and items. Leave omitted values
null or empty; never invent a customer, product, quantity, price, permission, or discount.
When a singular article such as "a", "an", "un", or "una" directly specifies one product,
extract quantity 1; an explicitly stated numeric quantity always takes precedence.

For pending quote edits, target lines only by their supplied stable line_id. Replace only the
named product line and preserve its quantity. A short quantity applies only to a unique line
missing quantity. Additions use add_item; corrections use replace_item; removals use
remove_item. Resolve pronouns only when supplied candidates identify one unambiguous target.
If a query is read-only or unrelated, return its appropriate intent with quote_request and
quote_patch null, preserving any pending quote unchanged.

Use the current turn's language when clear; otherwise return null so the host can retain it.
"""
_MAX_TURN_CONTEXT_BYTES = 16_384


class TurnDecisionContextTooLargeError(ValueError):
    """Raised when dynamic structured-decision context exceeds its byte limit."""


def build_turn_decision_input(state: DemoState, user_input: str) -> RuntimeInput:
    """Build stable-prefix model input with bounded, deterministic turn context.

    Args:
        state: Current host-owned conversation and quote state.
        user_input: Current raw user turn.

    Returns:
        RuntimeInput whose fixed system prompt is followed by ordered JSON context.
    """
    user = state.get("authenticated_user")
    role = user.role if user is not None else "anonymous"
    workflow = state.get("quote_workflow")
    pending_quote: dict[str, Any] | None = None
    if workflow is not None:
        pending_quote = {
            "workflow_id": workflow.workflow_id,
            "revision": workflow.revision,
            "phase": workflow.phase,
            "customer_query": workflow.customer_query,
            "customer_name": workflow.customer_name,
            "items": [
                {
                    "line_id": item.line_id,
                    "product_query": item.product_query,
                    "canonical_name": item.canonical_name,
                    "quantity": item.quantity,
                    "status": item.status,
                    "candidates": item.candidates,
                }
                for item in workflow.items
            ],
            "last_candidates": workflow.last_candidates,
        }
    payload = {
        "available_actions": sorted(allowed_actions(user)),
        "identity_role": role,
        "pending_quote": pending_quote,
        "previous_language": state.get("language"),
        "user_input": user_input,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > _MAX_TURN_CONTEXT_BYTES:
        raise TurnDecisionContextTooLargeError()
    return RuntimeInput(
        (
            RuntimeMessage("system", (TextContent(_TURN_DECISION_SYSTEM_PROMPT),)),
            RuntimeMessage("user", (TextContent(serialized),)),
        )
    )


_PREVIEW_IGNORED_TERMS = frozenset(
    {
        "a",
        "an",
        "and",
        "calculate",
        "calculates",
        "calcula",
        "calcular",
        "calcule",
        "calculame",
        "can",
        "could",
        "cost",
        "costs",
        "cotizacion",
        "cuanto",
        "cuesta",
        "de",
        "del",
        "dame",
        "do",
        "does",
        "dollars",
        "el",
        "la",
        "las",
        "los",
        "for",
        "favor",
        "get",
        "how",
        "i",
        "in",
        "is",
        "me",
        "much",
        "need",
        "necesito",
        "of",
        "please",
        "para",
        "por",
        "preliminar",
        "preliminary",
        "presupuesto",
        "price",
        "preview",
        "product",
        "products",
        "producto",
        "productos",
        "quote",
        "quiero",
        "quisiera",
        "the",
        "this",
        "to",
        "usd",
        "un",
        "una",
        "x",
        "what",
        "would",
        "you",
        "show",
        "y",
    }
)


def _normalize_preview_text(text: str) -> str:
    """Normalize preview input for accent- and punctuation-insensitive matching.

    Args:
        text: Raw user text.

    Returns:
        Lowercase text with accents and punctuation converted to spaces.
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", without_accents).strip()


def _parse_quote_preview_items(
    conn: sqlite3.Connection,
    text: str,
    language: str,
) -> tuple[list[QuoteItemInput], str | None]:
    """Resolve explicit catalog items and quantities for an offline preview.

    Args:
        conn: Open business database connection.
        text: User's preview request.
        language: Stable interaction language.

    Returns:
        Validated product and quantity inputs, or a localized clarification.
    """
    if re.search(r"[-−‐‑‒–—﹣－]\s*\d+(?!\w)", text):
        return [], (
            "La cantidad debe ser un entero positivo, no negativo."
            if language == "es"
            else "Quantity must be a positive whole number, not a negative value."
        )
    if re.search(r"(?<!\w)\d+[.,]\d+(?!\w)", text):
        return [], (
            "La cantidad debe ser un entero positivo, sin decimales."
            if language == "es"
            else "Quantity must be a positive whole number, not a decimal."
        )

    normalized = _normalize_preview_text(text)
    normalized = re.sub(r"\bx(?=\d)", "x ", normalized)
    product_aliases = dict(_PREVIEW_PRODUCT_ALIASES)
    for catalog_product in list_active_products(conn):
        for alias in (str(catalog_product["name"]), str(catalog_product["sku"])):
            product_aliases[_normalize_preview_text(alias)] = str(catalog_product["id"])
        catalog_id = str(catalog_product["id"])
        for alias in (f"id {catalog_id}", f"product id {catalog_id}", f"producto id {catalog_id}"):
            product_aliases[_normalize_preview_text(alias)] = catalog_id
    segments = [
        part.strip()
        for part in re.split(r"\s*(?:,|;|\band\b|\by\b|\bplus\b)\s*", normalized)
        if part.strip()
    ]
    resolved_items: list[QuoteItemInput] = []
    for segment in segments:
        matches: list[tuple[int, int, str, str]] = []
        for alias, query in product_aliases.items():
            alias_pattern = r"\s+".join(re.escape(token) for token in alias.split())
            for match in re.finditer(rf"(?<!\w){alias_pattern}(?!\w)", segment):
                matches.append((match.start(), match.end(), query, alias))
        if not matches:
            unknown = [
                token
                for token in segment.split()
                if token not in _PREVIEW_IGNORED_TERMS
                and token not in _PREVIEW_QUANTITIES
                and not token.isdigit()
                and token not in {"units", "unit", "unidades", "unidad"}
            ]
            if unknown:
                phrase = " ".join(unknown)
                return [], (
                    f"No reconozco '{phrase}' como producto activo; no calculé el subtotal."
                    if language == "es"
                    else f"I don't recognize '{phrase}' as an active product; I did not calculate a subtotal."
                )
            quantity_only = [
                token
                for token in segment.split()
                if token.isdigit() or token in _PREVIEW_QUANTITIES
            ]
            if quantity_only:
                quantity_text = " ".join(quantity_only)
                return [], (
                    f"La cantidad {quantity_text} no tiene un producto asociado; no calculé el subtotal."
                    if language == "es"
                    else f"Quantity {quantity_text} has no associated product; I did not calculate a subtotal."
                )
            continue

        unmatched_characters = list(segment)
        for start, end, _, _ in matches:
            unmatched_characters[start:end] = " " * (end - start)
        unmatched_text = "".join(unmatched_characters)
        unknown = [
            token
            for token in unmatched_text.split()
            if token not in _PREVIEW_IGNORED_TERMS
            and token not in _PREVIEW_QUANTITIES
            and not token.isdigit()
            and token not in {"units", "unit", "unidades", "unidad"}
        ]
        if unknown:
            phrase = " ".join(unknown)
            return [], (
                f"No reconozco '{phrase}' como producto activo; no calculé el subtotal."
                if language == "es"
                else f"I don't recognize '{phrase}' as an active product; I did not calculate a subtotal."
            )

        # Prefer the most specific phrase (e.g. "notebook pro" over "notebook").
        specific_matches = [
            candidate
            for candidate in matches
            if not any(
                other[0] <= candidate[0]
                and other[1] >= candidate[1]
                and (other[1] - other[0]) > (candidate[1] - candidate[0])
                for other in matches
            )
        ]
        resolved: dict[int, dict[str, Any]] = {}
        resolved_matches: list[tuple[tuple[int, int, str, str], dict[str, Any]]] = []
        for candidate in specific_matches:
            _, _, query, _ = candidate
            product = find_product_by_query(conn, query)
            if product is None:
                continue
            if product.get("ambiguous"):
                candidates = ", ".join(str(value) for value in product.get("candidates", []))
                return [], (
                    f"¿Qué producto quieres incluir? Coincidencias: {candidates}."
                    if language == "es"
                    else f"Which product should I include? Matches: {candidates}."
                )
            product_id = int(product["id"])
            resolved[product_id] = product
            resolved_matches.append((candidate, product))

        if not resolved:
            continue
        if len(resolved) > 1:
            return [], (
                "Separa cada producto con una coma o 'y' para indicar sus cantidades."
                if language == "es"
                else "Separate each product with a comma or 'and' so I can read its quantity."
            )

        product = next(iter(resolved.values()))
        product_match, _ = next(
            resolved_match
            for resolved_match in resolved_matches
            if int(resolved_match[1]["id"]) == int(product["id"])
        )
        prefix = segment[: product_match[0]].strip()
        suffix = segment[product_match[1] :].strip()
        quantity_pattern = (
            r"(?:\b(?:qty|quantity|cantidad|x)\s*)?"
            r"(\d+|one|an|a|un|una|uno|two|dos|three|tres|four|cuatro|five|cinco)"
            r"\s*(?:units?|unidades?)?\b"
        )
        prefix_quantity_match = re.search(
            quantity_pattern + r"\s*$",
            prefix,
            flags=re.IGNORECASE,
        )
        suffix_quantity_match = re.search(
            quantity_pattern + r"(?:\s+(?:please|por\s+favor|porfa|porfavor))*\s*$",
            suffix,
            flags=re.IGNORECASE,
        )
        if prefix_quantity_match is not None and suffix_quantity_match is not None:
            return [], (
                "Indica la cantidad una sola vez, antes o después del producto."
                if language == "es"
                else "Specify the quantity only once, before or after the product."
            )
        quantity = 1
        quantity_match = prefix_quantity_match or suffix_quantity_match
        if quantity_match is not None:
            raw_quantity = quantity_match.group(1).casefold()
            quantity = (
                int(raw_quantity)
                if raw_quantity.isdigit()
                else _PREVIEW_QUANTITIES.get(raw_quantity, 0)
            )
        if quantity <= 0:
            return [], (
                "La cantidad debe ser un entero positivo."
                if language == "es"
                else "Quantity must be a positive whole number."
            )
        resolved_items.append(QuoteItemInput(product_id=int(product["id"]), quantity=quantity))

    if not resolved_items:
        return [], (
            "Indica un producto activo y su cantidad para calcular la vista preliminar."
            if language == "es"
            else "Specify an active product and its quantity for a quote preview."
        )
    return resolved_items, None


def detect_language(text: str) -> Literal["es", "en"]:
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
        "cantidad",
        "cliente",
        "clientes",
        "agrega",
        "cambia",
        "reemplaza",
        "hay",
    }
    tokens = set(re.findall(r"\b\w+\b", clean))
    if tokens & spanish_words:
        return "es"
    return "en"


def resolve_language(text: str, previous: Literal["es", "en"] | None = None) -> Literal["es", "en"]:
    """Resolve turn language while preserving session language for terse inputs.

    Args:
        text: Current user input.
        previous: Previously established language, if any.

    Returns:
        Stable language code, either ``es`` or ``en``.
    """
    clean = text.strip().lower()
    if previous in ("es", "en") and len(clean.split()) <= 3:
        english_markers = {
            "a",
            "an",
            "add",
            "all",
            "can",
            "change",
            "customers",
            "delete",
            "for",
            "help",
            "how",
            "i",
            "list",
            "me",
            "my",
            "please",
            "products",
            "quantity",
            "replace",
            "show",
            "thanks",
            "the",
            "what",
            "which",
            "yes",
        }
        tokens = set(re.findall(r"\b\w+\b", clean))
        if detect_language(text) == "en" and not tokens.intersection(english_markers):
            return previous
    return detect_language(text)


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
                "customer_query",
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
    quote_create_prefixes = (
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
        "cotizar",
        "cotizacion para",
        "cotización para",
        "quiero cotizar",
        "quiero crear una cotizacion",
        "quiero crear una cotización",
        "quiero una cotizacion",
        "quiero una cotización",
        "necesito una cotizacion",
        "necesito una cotización",
        "quisiera cotizar",
        "quisiera una cotizacion",
        "quisiera una cotización",
        "i want to create a quote",
        "i want a quote",
        "i need a quote",
    )
    if (
        clean.startswith(quote_create_prefixes)
        or bool(
            re.search(
                r"^(?:(?:quiero|quisiera|necesito|i\s+want\s+to|i\s+need\s+to)\s+)?(?:create|crear|generar|build|hacer)\s+(?:a\s+|una?\s+)?(?:quote|cotizaci[oó]n|presupuesto)\b",
                clean,
            )
        )
        or bool(
            re.search(
                r"^(?:(?:quiero|quisiera|necesito)\s+)?cotizar\b",
                clean,
            )
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

    # Non-persistent quote calculations remain read-only, including during collection.
    if any(
        phrase in clean
        for phrase in (
            "quote preview",
            "preview quote",
            "preliminary quote",
            "calcular cotizacion",
            "calcular cotización",
            "presupuesto preliminar",
            "calcular presupuesto",
        )
    ):
        return "quote_preview"

    # 7. Unequivocal catalog inquiries
    if clean in (
        "products",
        "productos",
        "catalogo",
        "catálogo",
        "catalog",
        "list products",
        "show products",
        "what products are active",
        "what active products are there",
        "listar productos",
        "ver catalogo",
        "ver catálogo",
        "que productos activos hay",
        "qué productos activos hay",
        "muestrame los productos activos",
        "muéstrame los productos activos",
    ) or clean.startswith(
        (
            "list products",
            "show products",
            "what products are active",
            "what active products are there",
            "listar productos",
            "ver catalogo",
            "ver catálogo",
            "que productos activos hay",
            "qué productos activos hay",
            "muestrame los productos activos",
            "muéstrame los productos activos",
        )
    ):
        return "catalog_query"

    # 8. Unequivocal staff customer directory inquiries
    if clean in (
        "customers",
        "list customers",
        "show customers",
        "clientes",
        "listar clientes",
        "ver clientes",
        "muéstrame los clientes",
        "muestrame los clientes",
        "muéstrame la lista de clientes",
        "muestrame la lista de clientes",
        "muestrame la lista de clientes",
        "muéstrame la lista de clientes",
    ) or clean.startswith(("list customers", "show customers", "listar clientes")):
        return "customer_query"

    # 9. Unequivocal quote history inquiries
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
    if re.search(
        r"\b(?:list|show|see|ver|listar|muestra|mostrame|mu[eé]strame|historial|listado)\b.*\b(?:quotes?|cotizaciones?)\b",
        clean,
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
        r"(?:create\s+(?:a\s+)?quote|crear\s+(?:una?\s+)?cotizaci[oó]n|quote|cotizar)\s+(?:for|para)\s+([A-Za-z0-9_\s]+)$",
        clean,
        re.IGNORECASE,
    )
    if match_cust:
        cand = match_cust.group(1).strip()
        if not re.match(r"^\d+", cand):
            return QuoteRequest(customer=cand, items=[])

    # Heuristic for follow-up customer: e.g. "para Globex", "for Globex", "hazlo para Globex"
    match_cust_followup = re.search(
        r"^(?:(?:hazlo|hacelo)\s+)?(?:for|para)\s+([A-Za-z0-9_\s]+)$",
        clean,
        re.IGNORECASE,
    )
    if match_cust_followup:
        cand = match_cust_followup.group(1).strip()
        if not re.match(r"^\d+", cand):
            return QuoteRequest(customer=cand, items=[])

    # Heuristic for partial: items specified but no customer
    match_items = re.search(
        r"(?:create\s+(?:a\s+)?quote|crear\s+(?:una?\s+)?cotizaci[oó]n|quote|cotizar)(?:\s+(?:for|para|de))?\s+(\d+\s+.+)$",
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

    # Heuristic for follow-up items: e.g. "2 Notebook Pro", "1 Notebook Pro y 2 Mouse"
    if re.match(r"^\d+\s+[A-Za-z0-9_\s\"-]+", clean):
        parts = re.split(r",|\band\b|\by\b", clean, flags=re.IGNORECASE)
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


def _workflow_from_request(req: QuoteRequest | None) -> QuoteWorkflowState:
    """Create a lossy compatibility workflow from the legacy request projection.

    Args:
        req: Structured request extracted from the current user turn.

    Returns:
        New quote workflow with unresolved user-supplied references. Its identity,
        revision, stable line IDs, and candidates cannot be recovered from the projection.
    """
    return QuoteWorkflowState(
        customer_query=req.customer if req is not None else None,
        items=[
            QuoteWorkflowItem(product_query=item.product, quantity=item.quantity)
            for item in (req.items if req is not None else [])
        ],
    )


def _request_from_workflow(workflow: QuoteWorkflowState) -> QuoteRequest:
    """Project workflow content into a lossy legacy request view.

    Args:
        workflow: Current host-owned quote workflow.

    Returns:
        QuoteRequest containing customer and item references only. Consumers must
        round-trip ``quote_workflow`` itself to preserve identity, revision, and candidates.
    """
    return QuoteRequest(
        customer=workflow.customer_query,
        items=[
            RequestedItem(product=item.product_query, quantity=item.quantity)
            for item in workflow.items
        ],
    )


def _clean_product_reference(value: str) -> str:
    """Remove common articles and conversational wrappers from a product reference.

    Args:
        value: Raw product phrase extracted from a turn.

    Returns:
        Product name or reference without surrounding conversational words.
    """
    clean = value.strip().strip(" .,!?:;\"'")
    clean = re.sub(r"^(?:un|una|unos|unas|el|la|los|las|a|an|the)\s+", "", clean, flags=re.I)
    clean = re.sub(
        r"^(?:quiero|quisiera|necesito|agrega|agregá|añade|anade|add)\s+", "", clean, flags=re.I
    )
    return clean.strip()


def _quote_patch_from_text(
    workflow: QuoteWorkflowState,
    text: str,
    req: QuoteRequest | None,
) -> QuotePatch:
    """Propose safe quote operations from explicit current-turn language.

    Args:
        workflow: Current host-owned quote workflow.
        text: Current user turn.
        req: Optional structured or heuristic extraction for the turn.

    Returns:
        A validated patch proposal; its targets are checked again by the reducer.
    """
    clean = text.strip()
    lowered = clean.casefold()
    operations: list[QuotePatchOperation] = []

    if req is not None and req.customer and req.customer.strip():
        operations.append(
            SetCustomerOperation(operation="set_customer", target=req.customer.strip())
        )

    correction = re.search(
        r"(?:quiero|quisiera|necesito|use|replace(?:\s+with)?|cambia(?:r)?(?:\s+por)?|usa)\s+"
        r"(?P<replacement>.+?)\s+(?:en\s+vez\s+de|instead\s+of)\s+"
        r"(?P<target>.+?)[.!?]*$",
        clean,
        re.IGNORECASE,
    )
    if correction is None:
        correction = re.search(
            r"(?P<replacement>[\w][\w\s\-\"]*?)\s+(?:en\s+vez\s+de|instead\s+of)\s+"
            r"(?P<target>[\w][\w\s\-\"]*)[.!?]*$",
            clean,
            re.IGNORECASE,
        )
    if correction is not None:
        replacement = _clean_product_reference(correction.group("replacement"))
        target = _clean_product_reference(correction.group("target"))
        target_key = re.sub(r"\s+", " ", target).casefold()
        matches = [
            item
            for item in workflow.items
            if item.product_query
            and (
                target_key in re.sub(r"\s+", " ", item.product_query).casefold()
                or re.sub(r"\s+", " ", item.product_query).casefold() in target_key
            )
        ]
        if len(matches) == 1 and replacement:
            operations.append(
                ReplaceItemOperation(
                    operation="replace_item",
                    target=matches[0].line_id,
                    product=replacement,
                )
            )
            return QuotePatch(operations=operations)

    quantity_only = re.fullmatch(r"(?:cantidad|quantity)?\s*(\d+)", lowered)
    if quantity_only is not None:
        quantity = int(quantity_only.group(1))
        missing = [item for item in workflow.items if item.quantity is None]
        if quantity > 0 and len(missing) == 1:
            operations.append(
                SetQuantityOperation(
                    operation="set_quantity", target=missing[0].line_id, quantity=quantity
                )
            )
        return QuotePatch(operations=operations)

    add_match = re.search(
        r"(?:agrega|agregá|añade|anade|add|also\s+add)\s+"
        r"(?:(?P<quantity>\d+)\s+)?(?P<product>.+?)"
        r"(?:\s+(?:al|a\s+la|to\s+the)?\s*(?:presupuesto|cotizaci[oó]n|quote))?[.!?]*$",
        clean,
        re.IGNORECASE,
    )
    if add_match is not None:
        product = _clean_product_reference(add_match.group("product"))
        quantity = int(add_match.group("quantity") or 1)
        if product.casefold() in {"ese", "esa", "that", "it"}:
            candidates = {
                candidate for item in workflow.items for candidate in item.candidates
            } | set(workflow.last_candidates)
            if len(candidates) == 1:
                product = next(iter(candidates)).split(" (", maxsplit=1)[0]
            else:
                product = ""
        if product:
            operations.append(
                AddItemOperation(operation="add_item", product=product, quantity=quantity)
            )
        return QuotePatch(operations=operations)

    remove_match = re.search(
        r"(?:elimina|eliminar|quita|quitar|remove|delete)\s+(?:el|la|un|una|the|a)?\s*(.+?)[.!?]*$",
        clean,
        re.IGNORECASE,
    )
    if remove_match is not None:
        reference = _clean_product_reference(remove_match.group(1)).casefold()
        matches = [
            item
            for item in workflow.items
            if item.product_query
            and (
                reference in item.product_query.casefold()
                or item.product_query.casefold() in reference
            )
        ]
        if len(matches) == 1:
            operations.append(
                RemoveItemOperation(operation="remove_item", target=matches[0].line_id)
            )
        return QuotePatch(operations=operations)

    if req is not None and req.items:
        add_turn = any(
            token in lowered for token in ("agrega", "agregá", "añade", "anade", "add", "also")
        )
        complete_request = bool(
            req.customer
            or any(term in lowered for term in ("presupuesto", "cotizacion", "cotización", "quote"))
        )
        if add_turn or not complete_request:
            operations.extend(
                AddItemOperation(
                    operation="add_item",
                    product=item.product,
                    quantity=item.quantity,
                )
                for item in req.items
                if item.product
            )

    return QuotePatch(operations=operations)


def _apply_quote_patch(
    workflow: QuoteWorkflowState,
    patch: QuotePatch,
) -> QuoteWorkflowState:
    """Apply validated operations to a copied workflow without touching unrelated lines.

    Args:
        workflow: Workflow to update.
        patch: Proposed operations whose targets are validated host-side.

    Returns:
        Updated workflow.
    """
    current = workflow.model_copy(deep=True)
    for operation in patch.operations:
        if operation.operation == "set_customer":
            if operation.target:
                current.customer_query = operation.target.strip()
                current.customer_id = None
                current.customer_name = None
            continue
        if operation.operation == "add_item":
            if operation.product:
                line = QuoteWorkflowItem(
                    product_query=operation.product,
                    quantity=operation.quantity,
                )
                current.items.append(line)
                current.focused_line_id = line.line_id
            continue
        targets = [line for line in current.items if line.line_id == operation.target]
        if not targets and operation.operation == "set_quantity" and operation.target is None:
            targets = [line for line in current.items if line.quantity is None]
        if not targets and operation.target:
            target_query = operation.target.casefold()
            targets = [
                line
                for line in current.items
                if line.product_query
                and (
                    target_query in line.product_query.casefold()
                    or line.product_query.casefold() in target_query
                )
            ]
        if len(targets) != 1:
            continue
        target = targets[0]
        if operation.operation == "replace_item" and operation.product:
            target.product_query = operation.product
            target.product_id = None
            target.sku = None
            target.canonical_name = None
            target.candidates = []
            target.status = "incomplete"
            current.focused_line_id = target.line_id
        elif operation.operation == "set_quantity" and operation.quantity is not None:
            target.quantity = operation.quantity
            current.focused_line_id = target.line_id
        elif operation.operation == "remove_item":
            current.items = [line for line in current.items if line.line_id != target.line_id]
            current.focused_line_id = current.items[-1].line_id if current.items else None
    return current


def _apply_quote_turn(
    workflow: QuoteWorkflowState | None,
    req: QuoteRequest | None,
    text: str,
    patch: QuotePatch | None = None,
    *,
    replace_existing: bool = False,
) -> QuoteWorkflowState:
    """Apply one user turn to a quote workflow without dropping unrelated lines.

    Args:
        workflow: Existing workflow, or None when starting a quote.
        req: Values explicitly extracted from the current turn.
        text: Raw current user turn used for deterministic correction syntax.
        patch: Optional model-proposed patch, revalidated by the host reducer.
        replace_existing: Whether the validated request is an explicit full restatement.

    Returns:
        Updated workflow with a new revision when continuing an existing quote.
    """
    current = (
        workflow.model_copy(deep=True) if workflow is not None else _workflow_from_request(req)
    )
    if workflow is None:
        return current
    lowered = text.casefold()
    incoming = req.items if req is not None else []
    complete_request = bool(
        incoming
        and req is not None
        and req.customer
        and any(
            term in lowered
            for term in ("presupuesto", "cotizacion", "cotización", "quote", "cotizar")
        )
    )
    if (complete_request or replace_existing) and req is not None:
        return _workflow_from_request(req)

    if re.search(r"\b(ese|esa|eso|that|it)\b", lowered):
        proposed = _quote_patch_from_text(current, text, req)
    else:
        proposed = patch or _quote_patch_from_text(current, text, req)
    updated = _apply_quote_patch(current, proposed) if proposed.operations else current
    if not proposed.operations and req is not None and req.customer and req.customer.strip():
        updated.customer_query = req.customer.strip()
        updated.customer_id = None
        updated.customer_name = None
    if updated == workflow:
        return workflow
    updated.revision = workflow.revision + 1
    updated.phase = "collecting"
    updated.last_candidates = []
    return updated


def default_quote_reviewer(draft: QuoteDraft, *, language: str = "en") -> None:
    """Print an authoritative host-generated review summary for a quote draft.

    Args:
        draft: Authoritative quote draft dictionary.
        language: Stable interaction language (`es` or `en`).
    """
    is_spanish = language == "es"
    print("\n" + "=" * 50)
    print("REVISIÓN DE COTIZACIÓN" if is_spanish else "HOST QUOTE REVIEW")
    print("=" * 50)
    print(
        f"Cliente: {draft['customer_name']} (ID: {draft['customer_id']})"
        if is_spanish
        else f"Customer: {draft['customer_name']} (ID: {draft['customer_id']})"
    )
    print("Productos:" if is_spanish else "Line items:")
    for line in draft["lines"]:
        print(
            f"  - {line['name']} ({line['sku']}): {line['quantity']}x @ "
            f"{format_currency(line['unit_price_cents'])} = {format_currency(line['subtotal_cents'])}"
        )
    print(
        f"Subtotal:         {format_currency(draft['subtotal_cents'])}"
        if is_spanish
        else f"Subtotal:        {format_currency(draft['subtotal_cents'])}"
    )
    print(
        f"Descuento:        {draft['discount_percent']}% ({format_currency(draft['discount_amount_cents'])})"
        if is_spanish
        else f"Discount:        {draft['discount_percent']}% ({format_currency(draft['discount_amount_cents'])})"
    )
    print(
        f"Total:            {format_currency(draft['total_cents'])}"
        if is_spanish
        else f"Total:           {format_currency(draft['total_cents'])}"
    )
    print("=" * 50)


def _draft_matches_workflow(
    workflow: QuoteWorkflowState | None,
    draft: QuoteDraft | None,
) -> bool:
    """Check that a draft belongs to the current ready-to-review workflow revision.

    Args:
        workflow: Current host-owned workflow state.
        draft: Derived quote draft awaiting review or persistence.

    Returns:
        Whether identifiers, revision, and review phase all match.
    """
    return bool(
        workflow is not None
        and draft is not None
        and workflow.phase == "ready_for_review"
        and workflow.workflow_id == draft["workflow_id"]
        and workflow.revision == draft["workflow_revision"]
    )


def create_demo_graph(
    conn: sqlite3.Connection,
    *,
    structured_model: RuntimeModel[Any] | None = None,
    context_agent: RuntimeTask[Any] | Callable[[], RuntimeTask[Any] | None] | None = None,
    session_manager: AgentSessionManager | None = None,
    controlled_agent_model: Any = None,
    approval_handler: ApprovalHandler | None = None,
    discount_prompter: Callable[..., int] | None = None,
    auth_interactive: Callable[..., AuthenticatedUser | None] | None = None,
    quote_reviewer: Callable[..., None] | None = None,
    event_sink: Callable[[RuntimeEvent], Awaitable[Any]] | None = None,
    host_event_sink: Callable[[Mapping[str, Any]], None] | None = None,
    host_error_sink: Callable[..., None] | None = None,
) -> Any:
    """Assemble and compile the LangGraph StateGraph for Smart Quote Agent.

    Args:
        conn: Open SQLite database connection.
        structured_model: RuntimeModel bound with profile='structured', level='low'.
        context_agent: RuntimeTask or callable returning active RuntimeTask with profile='controlled_agent'.
        session_manager: Optional AgentSessionManager managing task lifecycle across identities.
        controlled_agent_model: Deprecated compatibility alias for context_agent.
        approval_handler: Optional Phase 5 ApprovalHandler for write confirmation.
        discount_prompter: Optional callback for discount prompt (defaults to prompt_discount_interactive).
        auth_interactive: Optional callback for interactive login (defaults to authenticate_user_interactive).
        quote_reviewer: Optional callback to review quote before approval (defaults to default_quote_reviewer).
        event_sink: Optional async callable for exporting tool lifecycle events to telemetry.
        host_event_sink: Optional sink for host-side metadata-only transition events.
        host_error_sink: Optional best-effort sink for sanitized host exceptions.

    Returns:
        Compiled LangGraph runnable graph.
    """
    active_structured_model = structured_model
    active_context_agent = context_agent if context_agent is not None else controlled_agent_model
    active_session_manager = session_manager
    actual_approval_handler = approval_handler or ConsoleApprovalHandler()
    actual_discount_prompter = discount_prompter or prompt_discount_interactive
    actual_auth_interactive = auth_interactive or authenticate_user_interactive
    actual_quote_reviewer = quote_reviewer or default_quote_reviewer
    actual_event_sink = event_sink
    actual_host_event_sink = host_event_sink
    actual_host_error_sink = host_error_sink

    def _mark_error_stage(error: Exception, stage: str) -> None:
        """Attach a controlled stage label for the outer REPL error boundary."""
        try:
            error.__dict__["_smart_quote_stage"] = stage
        except Exception:
            return

    def _invocation_config(
        state: DemoState,
        stage: str,
        task_id: str | None = None,
        call_id: str | None = None,
    ) -> InvocationConfig:
        """Build safe per-call correlation metadata for Proteo invocations."""
        active_task: Any = task_id
        if active_task is None and active_session_manager is not None:
            active_task = active_session_manager.active_task
        if active_task is None and callable(active_context_agent):
            active_task = active_context_agent()
        if (
            active_task is None
            and active_context_agent is not None
            and hasattr(active_context_agent, "id")
        ):
            active_task = active_context_agent

        metadata: dict[str, str] = {"stage": stage}
        if call_id is not None:
            metadata["call_id"] = call_id
        interaction_id = state.get("interaction_id")
        if isinstance(interaction_id, str):
            metadata["interaction_id"] = interaction_id
        resolved_task_id = (
            active_task if isinstance(active_task, str) else getattr(active_task, "id", None)
        )
        if isinstance(resolved_task_id, str):
            metadata["task_id"] = resolved_task_id
        workflow = state.get("quote_workflow")
        workflow_id = getattr(workflow, "workflow_id", None)
        if isinstance(workflow_id, str):
            metadata["workflow_id"] = workflow_id
        return InvocationConfig(metadata=metadata)

    def _emit_host_timing_event(
        state: DemoState,
        event_kind: str,
        stage: str,
        *,
        result_code: str | None = None,
        duration_ms: float | None = None,
        call_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        """Emit one content-free, correlated timing event on a best-effort basis.

        Args:
            state: Current host-owned graph state.
            event_kind: Fixed event name from the application timing vocabulary.
            stage: Stable workflow stage identifier.
            result_code: Optional non-sensitive completion outcome.
            duration_ms: Optional measured duration in milliseconds.
            call_id: Optional stable identifier for one runtime call.
            task_id: Optional task identifier known by the caller.
        """
        if actual_host_event_sink is None:
            return
        metadata = dict(_invocation_config(state, stage, task_id, call_id).metadata)
        metadata["event_kind"] = event_kind
        metadata["status"] = "running" if event_kind.endswith("_started") else "completed"
        if result_code is not None:
            metadata["result_code"] = result_code
            metadata["status"] = "failed" if result_code.endswith("failed") else "completed"
        if duration_ms is not None:
            metadata["duration_ms"] = max(0.0, duration_ms)
        try:
            actual_host_event_sink(metadata)
        except Exception:
            # Timing telemetry must never affect model or workflow execution.
            return

    async def _invoke_with_diagnostics(
        target: Any, input_value: Any, state: DemoState, stage: str, task_id: str | None = None
    ) -> Any:
        """Invoke one runtime model/task with correlation and measured host timing."""
        call_id = uuid.uuid4().hex
        started_at = perf_counter()
        _emit_host_timing_event(
            state,
            "host.model_call_started",
            stage,
            call_id=call_id,
            task_id=task_id,
        )
        try:
            result = await target.ainvoke(
                input_value,
                config=_invocation_config(state, stage, task_id, call_id),
            )
        except Exception as error:
            _emit_host_timing_event(
                state,
                "host.model_call_completed",
                stage,
                result_code="model_call_failed",
                duration_ms=(perf_counter() - started_at) * 1000,
                call_id=call_id,
                task_id=task_id,
            )
            _mark_error_stage(error, stage)
            raise
        _emit_host_timing_event(
            state,
            "host.model_call_completed",
            stage,
            result_code="model_call_completed",
            duration_ms=(perf_counter() - started_at) * 1000,
            call_id=call_id,
            task_id=task_id,
        )
        return result

    async def _structured_turn_decision(state: DemoState, user_input: str) -> TurnDecision:
        """Classify and extract one turn using the stable structured prompt/schema pair.

        Args:
            state: Current host-owned graph state.
            user_input: Raw user turn to classify and extract.

        Returns:
            Host-validated structured turn decision.
        """
        assert active_structured_model is not None
        structured_router = active_structured_model.with_structured_output(TurnDecision)
        result = await _invoke_with_diagnostics(
            structured_router,
            build_turn_decision_input(state, user_input),
            state,
            "intent_router",
        )
        return cast(TurnDecision, result.value)

    def _oversized_context_decision(user_input: str, state: DemoState) -> dict[str, Any]:
        """Return a localized clarification marker without invoking the model.

        Args:
            user_input: Current user turn used only for language detection.
            state: Current state whose quote workflow must remain unchanged.

        Returns:
            Router result that scope handling renders as a bounded-context clarification.
        """
        return {
            "intent": "clarification",
            "language": resolve_language(user_input, state.get("language")),
            "quote_request": None,
            "quote_patch": None,
            "router_result_code": "turn_context_too_large",
        }

    def _record_host_error(error: Exception, state: DemoState, stage: str) -> None:
        """Record a swallowed host exception without changing the business result."""
        if actual_host_error_sink is None:
            return
        config = _invocation_config(state, stage)
        metadata = config.metadata
        try:
            actual_host_error_sink(
                error,
                stage=stage,
                interaction_id=str(metadata.get("interaction_id") or "unknown"),
                task_id=(str(metadata["task_id"]) if metadata.get("task_id") else None),
                workflow_id=(str(metadata["workflow_id"]) if metadata.get("workflow_id") else None),
            )
        except Exception:
            # Diagnostic persistence must not affect business outcomes.
            return

    def emit_host_transition(
        state: DemoState,
        route: str,
        result_code: str,
        updates: Mapping[str, Any] | None = None,
    ) -> None:
        """Emit a content-free host transition correlated to task and workflow.

        Args:
            state: State before the host transition.
            route: Host node or routing stage name.
            result_code: Stable non-sensitive outcome code.
            updates: Node output values used to derive the post-transition phase.
        """
        if actual_host_event_sink is None:
            return
        active_task: Any = active_session_manager.active_task if active_session_manager else None
        if active_task is None and callable(active_context_agent):
            active_task = active_context_agent()
        if active_task is None and active_context_agent is not None:
            active_task = active_context_agent
        before = state.get("quote_workflow")
        effective_updates = updates or {}
        after = effective_updates.get("quote_workflow", before)
        metadata: dict[str, Any] = {
            "interaction_id": state.get("interaction_id"),
            "task_id": getattr(active_task, "id", None),
            "workflow_id": getattr(after, "workflow_id", None)
            or getattr(before, "workflow_id", None),
            "revision": getattr(after, "revision", None) or getattr(before, "revision", None),
            "intent": effective_updates.get("intent", state.get("intent")),
            "route": route,
            "phase_before": getattr(before, "phase", None),
            "phase_after": getattr(after, "phase", None),
            "result_code": result_code,
        }
        try:
            actual_host_event_sink(metadata)
        except Exception:
            # Diagnostics must not change business workflow outcomes.
            return

    def prompt_discount(subtotal_cents: int, language: str, state: DemoState) -> int:
        """Call a compatible discount prompter with the active language when supported.

        Args:
            subtotal_cents: Authoritative subtotal in integer cents.
            language: Stable interaction language.
            state: Current graph state used only for event correlation.

        Returns:
            Validated discount percentage.
        """
        hitl_started_at = perf_counter()
        _emit_host_timing_event(state, "host.hitl_started", "discount_hitl")
        try:
            accepts_language = "language" in signature(actual_discount_prompter).parameters
        except (TypeError, ValueError):
            accepts_language = False
        try:
            if accepts_language:
                result = int(actual_discount_prompter(subtotal_cents, language=language))
            else:
                result = int(actual_discount_prompter(subtotal_cents))
        except Exception:
            _emit_host_timing_event(
                state,
                "host.hitl_resolved",
                "discount_hitl",
                result_code="hitl_failed",
                duration_ms=(perf_counter() - hitl_started_at) * 1000,
            )
            raise
        _emit_host_timing_event(
            state,
            "host.hitl_resolved",
            "discount_hitl",
            result_code="hitl_resolved",
            duration_ms=(perf_counter() - hitl_started_at) * 1000,
        )
        return result

    def review_quote(draft: QuoteDraft, language: str) -> None:
        """Call the review renderer with language when its signature supports it.

        Args:
            draft: Authoritative host-calculated quote draft.
            language: Stable interaction language.
        """
        try:
            accepts_language = "language" in signature(actual_quote_reviewer).parameters
        except (TypeError, ValueError):
            accepts_language = False
        if accepts_language:
            actual_quote_reviewer(draft, language=language)
            return
        actual_quote_reviewer(draft)

    async def _intent_router_decision_node(state: DemoState) -> dict[str, Any]:
        """Classify user intent via deterministic rules or low-level structured classifier."""
        user_input = state.get("input", "")
        workflow = state.get("quote_workflow")
        pending_action = state.get("pending_action")

        # 0. If in an active quote creation workflow, honor continuation or cancel
        clean = user_input.strip().lower()
        if workflow is not None or pending_action == "quote_create":
            if clean in ("cancel", "cancelar", "abort", "abortar"):
                return {
                    "intent": "cancel_action",
                    "quote_workflow": None,
                    "quote_draft": None,
                    "quote_request": None,
                    "quote_patch": None,
                    "pending_action": None,
                    "pending_quote_request": None,
                }
            if clean in ("logout", "cerrar sesion", "cerrar sesión", "salir de mi cuenta"):
                return {
                    "intent": "logout",
                    "quote_workflow": None,
                    "quote_draft": None,
                    "quote_request": None,
                    "quote_patch": None,
                    "pending_action": None,
                    "pending_quote_request": None,
                }
            pending_heuristic = classify_intent_heuristic(user_input)
            if pending_heuristic in {
                "catalog_query",
                "customer_query",
                "quote_preview",
                "quote_history",
                "help",
                "acknowledgement",
            }:
                return {
                    "intent": pending_heuristic,
                    "language": resolve_language(user_input, state.get("language")),
                    "quote_request": None,
                    "quote_patch": None,
                }
            if pending_heuristic in {"login", "logout"}:
                return {
                    "intent": pending_heuristic,
                    "language": resolve_language(user_input, state.get("language")),
                    "quote_request": None,
                    "quote_patch": None,
                }
            if workflow is not None:
                quantity_only = re.fullmatch(r"(?:cantidad|quantity)?\s*\d+", clean) is not None
                anaphoric = re.search(r"\b(ese|esa|eso|that|it)\b", clean) is not None
                known_candidates = {
                    candidate for item in workflow.items for candidate in item.candidates
                } | set(workflow.last_candidates)
                if (
                    quantity_only and sum(item.quantity is None for item in workflow.items) != 1
                ) or (anaphoric and len(known_candidates) != 1):
                    return {
                        "intent": "quote_create",
                        "language": resolve_language(user_input, state.get("language")),
                        "quote_request": None,
                        "quote_patch": None,
                    }
                heuristic_request = parse_quote_request_heuristic(user_input)
                complete_request = bool(
                    heuristic_request is not None
                    and heuristic_request.customer
                    and heuristic_request.items
                    and any(
                        term in clean
                        for term in ("presupuesto", "cotizacion", "cotización", "quote", "cotizar")
                    )
                )
                if complete_request:
                    return {
                        "intent": "quote_create",
                        "language": resolve_language(user_input, state.get("language")),
                        "quote_request": heuristic_request,
                        "quote_patch": None,
                    }
                deterministic_patch = _quote_patch_from_text(
                    workflow,
                    user_input,
                    heuristic_request,
                )
                if deterministic_patch.operations:
                    return {
                        "intent": "quote_create",
                        "language": resolve_language(user_input, state.get("language")),
                        "quote_request": None,
                        "quote_patch": deterministic_patch,
                    }
            if active_structured_model is not None:
                try:
                    decision = await _structured_turn_decision(state, user_input)
                except TurnDecisionContextTooLargeError:
                    return _oversized_context_decision(user_input, state)
                return {
                    "intent": decision.intent,
                    "language": decision.language
                    or resolve_language(user_input, state.get("language")),
                    "quote_request": decision.quote_request,
                    "quote_patch": decision.quote_patch,
                }
            return {
                "intent": "clarification",
                "language": resolve_language(user_input, state.get("language")),
                "quote_request": None,
                "quote_patch": None,
            }

        # 1. Deterministic heuristic check
        heuristic = classify_intent_heuristic(user_input)
        if heuristic is not None and heuristic != "quote_create":
            return {"intent": heuristic}

        # 2. Ambiguous turns and quote requests use one combined structured decision.
        if active_structured_model is not None:
            try:
                decision = await _structured_turn_decision(state, user_input)
            except TurnDecisionContextTooLargeError:
                return _oversized_context_decision(user_input, state)
            return {
                "intent": decision.intent,
                "language": decision.language
                or resolve_language(user_input, state.get("language")),
                "quote_request": decision.quote_request,
                "quote_patch": decision.quote_patch,
            }

        if heuristic == "quote_create":
            return {"intent": heuristic, "quote_request": None, "quote_patch": None}

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
                "quote #",
                "cotizacion #",
                "cotización #",
                "history",
                "historial",
                "show quotes",
                "list quotes",
                "show latest quotes",
                "ver cotizaciones",
            )
        ):
            return {"intent": "quote_history"}

        if any(
            term in clean
            for term in ("preview", "preliminar", "calcular cotizacion", "calculate quote")
        ):
            return {"intent": "quote_preview"}

        if any(
            term in clean
            for term in (
                "cotizar",
                "cotizacion",
                "cotización",
                "quote",
                "presupuesto",
            )
        ):
            return {"intent": "quote_create"}

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
        return {"intent": "out_of_scope"}

    async def intent_router_node(state: DemoState) -> dict[str, Any]:
        """Correlate each router decision and record it without conversation content."""
        routed_state = cast(DemoState, dict(state))
        routed_state["interaction_id"] = routed_state.get("interaction_id") or uuid.uuid4().hex
        if (
            routed_state.get("quote_workflow") is None
            and routed_state.get("pending_action") == "quote_create"
            and routed_state.get("pending_quote_request") is not None
        ):
            routed_state["quote_workflow"] = _workflow_from_request(
                routed_state["pending_quote_request"]
            )
        updates = await _intent_router_decision_node(routed_state)
        updates.setdefault("quote_request", None)
        updates.setdefault("quote_patch", None)
        updates["router_result_code"] = updates.get("router_result_code")
        if routed_state.get("quote_workflow") is not None:
            updates.setdefault("quote_workflow", routed_state["quote_workflow"])
        updates["interaction_id"] = routed_state["interaction_id"]
        emit_host_transition(
            routed_state,
            "intent_router",
            str(updates.get("router_result_code") or "intent_routed"),
            updates,
        )
        return updates

    async def scope_gate_node(state: DemoState) -> dict[str, Any]:
        """Apply host-owned action policy and handle help/out-of-scope requests deterministically."""
        intent = state.get("intent", "out_of_scope")
        user = state.get("authenticated_user")
        user_input = state.get("input", "")
        lang = resolve_language(user_input, state.get("language"))
        allowed = allowed_actions(user)

        if intent == "clarification":
            if state.get("router_result_code") == "turn_context_too_large":
                if state.get("quote_workflow") is not None:
                    msg = (
                        "La solicitud es demasiado extensa para procesarla; la cotización pendiente se conserva. Acórtala e inténtalo de nuevo."
                        if lang == "es"
                        else "The request is too long to process; the pending quote is unchanged. Shorten it and try again."
                    )
                else:
                    msg = (
                        "La solicitud es demasiado extensa para procesarla. Acórtala e inténtalo de nuevo."
                        if lang == "es"
                        else "The request is too long to process. Shorten it and try again."
                    )
                return {"action_allowed": False, "output": msg, "language": lang}
            msg = (
                "No identifiqué una acción clara. Indica qué quieres consultar o qué dato de la cotización quieres cambiar."
                if lang == "es"
                else "I couldn't identify a clear action. Say what you want to look up or which quote detail to change."
            )
            return {"action_allowed": False, "output": msg, "language": lang}

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
                "language": lang,
            }

        # 2. Cancel action: reset pending state deterministically
        if intent == "cancel_action":
            msg = (
                "Operación de cotización cancelada."
                if lang == "es"
                else "Quote creation cancelled."
            )
            return {
                "action_allowed": True,
                "output": msg,
                "pending_action": None,
                "pending_quote_request": None,
                "quote_request": None,
                "quote_workflow": None,
                "quote_draft": None,
                "quote_patch": None,
                "language": lang,
            }

        # 3. Acknowledgement requests: short deterministic reply, never reach LLM
        if intent == "acknowledgement":
            msg = "De nada." if lang == "es" else "You're welcome."
            return {
                "action_allowed": True,
                "output": msg,
                "language": lang,
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
                "language": lang,
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
                    "language": lang,
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
                    "language": lang,
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
                    "language": lang,
                }
            if intent == "customer_query":
                msg = (
                    "La consulta de clientes está disponible únicamente para el personal (staff)."
                    if lang == "es"
                    else "Customer lookup is available to staff only."
                )
                return {"action_allowed": False, "output": msg, "language": lang}
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
                    "language": lang,
                }
            msg = (
                "Esta acción no está disponible para tu nivel de acceso actual."
                if lang == "es"
                else "This action is not available for your current access level."
            )
            return {
                "action_allowed": False,
                "output": msg,
                "language": lang,
            }

        # 5. Action is authorized
        return {"action_allowed": True, "language": lang}

    async def login_hitl_node(state: DemoState) -> dict[str, Any]:
        """Execute interactive login and record sanitized identity."""
        lang = state.get("language", "en")
        try:
            accepts_language = "language" in signature(actual_auth_interactive).parameters
        except (TypeError, ValueError):
            accepts_language = False
        user = (
            actual_auth_interactive(conn, language=lang)
            if accepts_language
            else actual_auth_interactive(conn)
        )
        if user is not None:
            if active_session_manager is not None:
                await active_session_manager.switch_identity(user)
            return {
                "authenticated_user": user,
                "pending_action": None,
                "pending_quote_request": None,
                "quote_request": None,
                "quote_workflow": None,
                "quote_draft": None,
                "quote_patch": None,
                "output": (
                    f"Sesión iniciada como {user.display_name} ({user.role})"
                    if lang == "es"
                    else f"Logged in as {user.display_name} ({user.role})"
                ),
            }
        return {
            "output": (
                "No se pudo iniciar sesión: usuario o contraseña inválidos."
                if lang == "es"
                else "Login failed: invalid username or password."
            )
        }

    async def clear_auth_node(state: DemoState) -> dict[str, Any]:
        """Clear authenticated identity from graph state."""
        if active_session_manager is not None:
            await active_session_manager.switch_identity(None)
        return {
            "authenticated_user": None,
            "pending_action": None,
            "pending_quote_request": None,
            "quote_request": None,
            "quote_workflow": None,
            "quote_draft": None,
            "quote_patch": None,
            "output": (
                "Sesión cerrada. Continuás como usuario anónimo."
                if state.get("language") == "es"
                else "Logged out. Continuing as anonymous."
            ),
        }

    async def auth_guard_node(state: DemoState) -> dict[str, Any]:
        """Enforce staff authorization for quote creation workflow."""
        user = state.get("authenticated_user")
        if user is None or user.role != "staff":
            is_spanish = state.get("language") == "es"
            return {
                "quote_authorized": False,
                "pending_action": None,
                "pending_quote_request": None,
                "quote_request": None,
                "quote_workflow": None,
                "quote_draft": None,
                "quote_patch": None,
                "output": (
                    "Acceso denegado. Solo el personal (staff) puede crear cotizaciones guardadas."
                    if is_spanish
                    else "Access denied. Persisted quotes can only be created by staff."
                ),
            }
        return {"quote_authorized": True}

    async def quote_planner_node(state: DemoState) -> dict[str, Any]:
        """Extract and reduce one quote turn into authoritative host workflow state."""
        user_input = state.get("input", "")
        lang = resolve_language(user_input, state.get("language"))
        workflow = state.get("quote_workflow")
        if workflow is None and state.get("pending_quote_request") is not None:
            workflow = _workflow_from_request(state["pending_quote_request"])
        req = state.get("quote_request")
        proposed_patch = state.get("quote_patch")
        clean = user_input.strip().casefold()
        quantity_only = re.fullmatch(r"(?:cantidad|quantity)?\s*\d+", clean) is not None
        anaphoric = re.search(r"\b(ese|esa|eso|that|it)\b", clean) is not None
        if workflow is not None and (
            (quantity_only and sum(item.quantity is None for item in workflow.items) != 1)
            or (
                anaphoric
                and len(
                    {candidate for item in workflow.items for candidate in item.candidates}
                    | set(workflow.last_candidates)
                )
                != 1
            )
        ):
            lang = resolve_language(user_input, state.get("language"))
            candidates = sorted(
                {candidate for item in workflow.items for candidate in item.candidates}
                | set(workflow.last_candidates)
            )
            if quantity_only:
                output = (
                    "¿A cuál producto corresponde esa cantidad?"
                    if lang == "es"
                    else "Which product should receive that quantity?"
                )
            elif candidates:
                output = (
                    "No puedo identificar a cuál producto te refieres. Elige uno: "
                    + ", ".join(candidates)
                    if lang == "es"
                    else "I cannot identify which product you mean. Choose one: "
                    + ", ".join(candidates)
                )
            else:
                output = (
                    "No hay una referencia única para 'ese'. Indica el producto."
                    if lang == "es"
                    else "There is no unique reference for 'that'. Please name the product."
                )
            updates: dict[str, Any] = {
                "quote_workflow": workflow,
                "quote_request": None,
                "quote_draft": None,
                "quote_patch": None,
                "pending_action": "quote_create",
                "output": output,
                "language": lang,
            }
            emit_host_transition(state, "quote_planner", "clarification_required", updates)
            return updates

        if req is None:
            req = parse_quote_request_heuristic(user_input)

        workflow = _apply_quote_turn(
            workflow,
            req,
            user_input,
            proposed_patch,
            replace_existing=state.get("quote_request") is not None
            and state.get("quote_workflow") is not None,
        )
        existing_workflow = state.get("quote_workflow")
        if (
            existing_workflow is not None
            and workflow.workflow_id == existing_workflow.workflow_id
            and workflow.revision == existing_workflow.revision
        ):
            output = (
                "No identifiqué un cambio para la cotización. Indica el producto, la cantidad o el cliente que quieres modificar."
                if lang == "es"
                else "I couldn't identify a quote change. Specify the product, quantity, or customer you want to change."
            )
            updates = {
                "quote_workflow": existing_workflow,
                "quote_request": None,
                "pending_quote_request": _request_from_workflow(existing_workflow),
                "pending_action": "quote_create",
                "quote_draft": None,
                "quote_patch": None,
                "output": output,
                "language": lang,
            }
            emit_host_transition(state, "quote_planner", "clarification_required", updates)
            return updates
        projected = _request_from_workflow(workflow)
        emit_host_transition(
            state,
            "quote_planner",
            "workflow_reduced",
            {"quote_workflow": workflow, "intent": "quote_create"},
        )
        return {
            "quote_workflow": workflow,
            "quote_request": projected,
            "pending_quote_request": projected,
            "pending_action": "quote_create",
            "quote_draft": None,
            "created_quote_id": None,
            "language": lang,
            "quote_patch": None,
        }

    async def resolve_quote_data_node(state: DemoState) -> dict[str, Any]:
        """Resolve every workflow entity while retaining unresolved state and candidates."""
        workflow = state.get("quote_workflow")
        lang = state.get("language", "en")
        if workflow is None:
            emit_host_transition(state, "resolve_quote_data", "workflow_missing")
            return {
                "quote_draft": None,
                "output": (
                    "No se encontró un flujo de cotización pendiente."
                    if lang == "es"
                    else "No pending quote workflow was found."
                ),
            }

        workflow = workflow.model_copy(deep=True)
        issues: list[str] = []
        workflow.last_candidates = []
        if not workflow.customer_query:
            issues.append(
                "Se requiere el nombre o identificador del cliente; indícalo, por ejemplo, 'para Globex'."
                if lang == "es"
                else "A customer name or identifier is required; specify it, for example, 'for Globex'."
            )
        else:
            cust = find_customer_by_query(conn, workflow.customer_query)
            if cust is None:
                issues.append(
                    f"No se encontró el cliente '{workflow.customer_query}'."
                    if lang == "es"
                    else f"Customer '{workflow.customer_query}' was not found."
                )
            elif cust.get("ambiguous"):
                candidates = [str(value) for value in cust.get("candidates", [])]
                workflow.last_candidates.extend(candidates)
                issues.append(
                    "Varios clientes coinciden: " + ", ".join(candidates)
                    if lang == "es"
                    else "Multiple customers matched: " + ", ".join(candidates)
                )
            else:
                workflow.customer_id = int(cust["id"])
                workflow.customer_name = str(cust["name"])

        draft_lines: list[QuoteLineDraft] = []
        subtotal_cents = 0
        draft_line_by_product: dict[int, int] = {}
        missing_quantity_items: list[QuoteWorkflowItem] = []

        if not workflow.items:
            issues.append(
                "Se requiere al menos un producto y su cantidad."
                if lang == "es"
                else "At least one product and quantity are required."
            )

        for item in workflow.items:
            item.product_id = None
            item.sku = None
            item.canonical_name = None
            item.candidates = []
            if not item.product_query or item.quantity is None:
                item.status = "incomplete"
                if not item.product_query:
                    issues.append(
                        "Falta indicar un producto para una línea de la cotización."
                        if lang == "es"
                        else "A product is missing from one quote line."
                    )
                elif item.quantity is None:
                    missing_quantity_items.append(item)
                workflow.focused_line_id = (
                    item.line_id if len(missing_quantity_items) <= 1 else None
                )
                continue
            prod = find_product_by_query(conn, item.product_query)
            if prod is None:
                item.status = "unresolved"
                workflow.focused_line_id = item.line_id
                issues.append(
                    f"No se encontró el producto '{item.product_query}' en el catálogo activo."
                    if lang == "es"
                    else f"Product '{item.product_query}' was not found in the active catalog."
                )
                continue
            if prod.get("ambiguous"):
                item.status = "ambiguous"
                item.candidates = [str(value) for value in prod.get("candidates", [])]
                workflow.last_candidates.extend(item.candidates)
                workflow.focused_line_id = item.line_id
                issues.append(
                    f"'{item.product_query}' coincide con: {', '.join(item.candidates)}."
                    if lang == "es"
                    else f"'{item.product_query}' matched: {', '.join(item.candidates)}."
                )
                continue

            unit_price = int(prod["unit_price_cents"])
            line_subtotal = unit_price * item.quantity
            subtotal_cents += line_subtotal
            item.product_id = int(prod["id"])
            item.sku = str(prod["sku"])
            item.canonical_name = str(prod["name"])
            item.status = "resolved"
            product_id = int(prod["id"])
            existing_line_index = draft_line_by_product.get(product_id)
            if existing_line_index is not None:
                existing_line = draft_lines[existing_line_index]
                existing_line["quantity"] += item.quantity
                existing_line["subtotal_cents"] += line_subtotal
            else:
                draft_line_by_product[product_id] = len(draft_lines)
                draft_lines.append(
                    {
                        "product_id": product_id,
                        "sku": str(prod["sku"]),
                        "name": str(prod["name"]),
                        "quantity": item.quantity,
                        "unit_price_cents": unit_price,
                        "subtotal_cents": line_subtotal,
                    }
                )

        if missing_quantity_items:
            names = [item.product_query or "" for item in missing_quantity_items]
            if len(names) == 1:
                issue = (
                    f"¿Qué cantidad necesitas de {names[0]}?"
                    if lang == "es"
                    else f"What quantity do you need for {names[0]}?"
                )
            else:
                joined = ", ".join(names)
                issue = (
                    f"Indica las cantidades para cada producto ({joined}); si respondes solo con una cantidad, señala el producto."
                    if lang == "es"
                    else f"Specify quantities for each product ({joined}); if giving one quantity, identify its product."
                )
                workflow.focused_line_id = None
            issues.append(issue)

        if issues or workflow.customer_id is None:
            workflow.phase = "needs_resolution"
            projected = _request_from_workflow(workflow)
            if not workflow.customer_query and not workflow.items:
                output = (
                    "No se pudieron extraer los detalles de la cotización. "
                    "Especifica el cliente y los productos con sus cantidades."
                    if lang == "es"
                    else "Could not extract quote details. Specify the customer and items with quantities."
                )
            else:
                output = "\n".join(f"- {issue}" for issue in issues)
            updates: dict[str, Any] = {
                "quote_workflow": workflow,
                "quote_request": None,
                "pending_quote_request": projected,
                "pending_action": "quote_create",
                "quote_draft": None,
                "output": output,
            }
            emit_host_transition(state, "resolve_quote_data", "resolution_required", updates)
            return updates

        workflow.phase = "ready_for_review"
        draft: QuoteDraft = {
            "workflow_id": workflow.workflow_id,
            "workflow_revision": workflow.revision,
            "customer_id": workflow.customer_id,
            "customer_name": workflow.customer_name or "",
            "lines": draft_lines,
            "subtotal_cents": subtotal_cents,
            "discount_percent": 0,
            "discount_amount_cents": 0,
            "total_cents": subtotal_cents,
        }
        updates = {
            "quote_workflow": workflow,
            "quote_draft": draft,
            "pending_action": None,
            "pending_quote_request": None,
        }
        emit_host_transition(state, "resolve_quote_data", "draft_ready", updates)
        return updates

    async def discount_hitl_node(state: DemoState) -> dict[str, Any]:
        """Interactively prompt human for discount and display quote review."""
        draft = state.get("quote_draft")
        if draft is None:
            return {}
        workflow = state.get("quote_workflow")
        if not _draft_matches_workflow(workflow, draft):
            updates = {
                "quote_draft": None,
                "output": (
                    "El borrador quedó desactualizado; vuelve a revisar la cotización vigente."
                    if state.get("language") == "es"
                    else "Quote draft is stale; review the current quote workflow again."
                ),
            }
            emit_host_transition(state, "discount_hitl", "draft_stale", updates)
            return updates

        discount_pct = prompt_discount(draft["subtotal_cents"], state.get("language", "en"), state)
        discount_amount = calculate_discount_amount(draft["subtotal_cents"], discount_pct)
        total_cents = draft["subtotal_cents"] - discount_amount

        updated_draft: QuoteDraft = {
            "workflow_id": draft["workflow_id"],
            "workflow_revision": draft["workflow_revision"],
            "customer_id": draft["customer_id"],
            "customer_name": draft["customer_name"],
            "lines": draft["lines"],
            "subtotal_cents": draft["subtotal_cents"],
            "discount_percent": discount_pct,
            "discount_amount_cents": discount_amount,
            "total_cents": total_cents,
        }

        # Display host quote review before approval
        review_quote(updated_draft, state.get("language", "en"))

        return {"quote_draft": updated_draft}

    async def create_quote_tool_node(state: DemoState) -> dict[str, Any]:
        """Execute create_quote tool through ToolExecutor with approval handling."""
        draft = state.get("quote_draft")
        if draft is None:
            return {
                "output": (
                    "No hay un borrador de cotización listo para crear."
                    if state.get("language") == "es"
                    else "No quote draft is ready to create."
                )
            }
        workflow = state.get("quote_workflow")
        if not _draft_matches_workflow(workflow, draft):
            updates = {
                "quote_draft": None,
                "output": (
                    "El borrador quedó desactualizado; vuelve a revisar la cotización vigente."
                    if state.get("language") == "es"
                    else "Quote draft is stale; review the current quote workflow again."
                ),
            }
            emit_host_transition(state, "create_quote_tool", "draft_stale", updates)
            return updates

        user = state.get("authenticated_user")
        if user is None or user.role != "staff":
            return {
                "output": (
                    "Se requiere una sesión de personal (staff) para guardar la cotización."
                    if state.get("language") == "es"
                    else "Staff authentication is required to persist a quote."
                )
            }

        if isinstance(actual_approval_handler, ConsoleApprovalHandler):
            actual_approval_handler.set_language(state.get("language", "en"))

        # Dedicated write registry containing create_quote bound to the active staff user
        write_registry = get_quote_write_registry(conn, user)
        quote_event_config = _invocation_config(state, "quote_persistence")
        quote_event_task_id = quote_event_config.metadata.get("task_id")
        quote_event_metadata = dict(quote_event_config.metadata)

        async def correlated_quote_event_sink(event: RuntimeEvent) -> None:
            """Attach safe interaction/workflow correlation to quote tool events."""
            if actual_event_sink is None:
                return
            correlated_event = replace(
                event,
                task_id=(
                    event.task_id
                    or (quote_event_task_id if isinstance(quote_event_task_id, str) else None)
                ),
                metadata={**event.metadata, **quote_event_metadata},
            )
            try:
                await actual_event_sink(correlated_event)
            except Exception:
                # Best-effort telemetry must not affect quote authorization or persistence.
                return

        executor = create_tool_executor(
            write_registry,
            user,
            approval_handler=actual_approval_handler,
            event_sink=(correlated_quote_event_sink if actual_event_sink is not None else None),
        )

        items_payload = [
            {"product_id": line["product_id"], "quantity": line["quantity"]}
            for line in draft["lines"]
        ]

        inv_id = f"quote-inv-{uuid.uuid4().hex}"
        call_id = f"quote-call-{uuid.uuid4().hex}"

        tool_req = ToolRequest(
            invocation_id=inv_id,
            call_id=call_id,
            name="create_quote",
            arguments={
                "customer_id": draft["customer_id"],
                "items": items_payload,
                "discount_percent": draft["discount_percent"],
            },
            task_id=(quote_event_task_id if isinstance(quote_event_task_id, str) else None),
        )

        try:
            res = await executor.execute(tool_req)
        except Exception as error:
            _record_host_error(error, state, "create_quote_tool")
            updates = {
                "pending_action": None,
                "pending_quote_request": None,
                "quote_request": None,
                "quote_patch": None,
                "quote_workflow": None,
                "quote_draft": None,
                "output": (
                    "No se pudo guardar la cotización (error de persistencia)."
                    if state.get("language") == "es"
                    else "Quote creation failed (persistence error)."
                ),
            }
            emit_host_transition(state, "create_quote_tool", "persistence_failed", updates)
            return updates
        finally:
            executor.end_invocation(inv_id)

        if res.success:
            val = res.as_provider_value()
            updates = {
                "created_quote_id": val.get("quote_id"),
                "pending_action": None,
                "pending_quote_request": None,
                "quote_request": None,
                "quote_patch": None,
                "quote_workflow": None,
                "quote_draft": None,
                "output": (
                    f"[ÉXITO] Cotización #{val.get('quote_id')} creada para {val.get('customer_name')}.\n"
                    f"Total: {val.get('total')}"
                    if state.get("language") == "es"
                    else (
                        f"[SUCCESS] Quote #{val.get('quote_id')} created for {val.get('customer_name')}.\n"
                        f"Total: {val.get('total')}"
                    )
                ),
            }
            emit_host_transition(state, "create_quote_tool", "quote_persisted", updates)
            return updates
        if res.denied:
            updates = {
                "pending_action": None,
                "pending_quote_request": None,
                "quote_request": None,
                "quote_patch": None,
                "quote_workflow": None,
                "quote_draft": None,
                "output": (
                    "El usuario rechazó la creación. No se guardó ninguna cotización."
                    if state.get("language") == "es"
                    else "Quote creation was denied by user. Nothing was persisted."
                ),
            }
            emit_host_transition(state, "create_quote_tool", "approval_denied", updates)
            return updates
        updates = {
            "pending_action": None,
            "pending_quote_request": None,
            "quote_request": None,
            "quote_patch": None,
            "quote_workflow": None,
            "quote_draft": None,
            "output": (
                f"No se pudo guardar la cotización (código: {res.error_code})."
                if state.get("language") == "es"
                else f"Quote creation failed (code: {res.error_code})."
            ),
        }
        emit_host_transition(state, "create_quote_tool", "persistence_failed", updates)
        return updates

    async def controlled_agent_node(state: DemoState) -> dict[str, Any]:
        """Execute controlled agent inquiries against host-managed tools."""
        user = state.get("authenticated_user")
        user_input = state.get("input", "")

        # Resolve active task
        task: RuntimeTask[Any] | None = None
        if callable(active_context_agent):
            task = active_context_agent()
        elif active_context_agent is not None and hasattr(active_context_agent, "ainvoke"):
            task = cast(Any, active_context_agent)

        if active_session_manager is not None:
            task = await active_session_manager.get_or_create_task(user)

        # If a live or fake controlled agent task is available, invoke it directly
        if task is not None:
            # Under ContextPolicy.RUNTIME, task instructions and tools are frozen at task creation.
            # We pass user_input directly to ainvoke. Never per-turn system messages.
            task_identifier = getattr(task, "id", None)
            res = await _invoke_with_diagnostics(
                task,
                user_input,
                state,
                "controlled_agent",
                task_id=task_identifier if isinstance(task_identifier, str) else None,
            )
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
        lang = state.get("language", "en")
        if state.get("intent") == "quote_preview":
            items, clarification = _parse_quote_preview_items(conn, user_input, lang)
            if clarification is not None:
                return {"output": clarification}

            registry = get_agent_tool_registry(conn, user)
            fallback_executor = create_tool_executor(registry, user)
            invocation_id = f"preview-inv-{uuid.uuid4().hex}"
            call_id = f"preview-call-{uuid.uuid4().hex}"
            try:
                tool_result = await fallback_executor.execute(
                    ToolRequest(
                        invocation_id,
                        call_id,
                        "calculate_quote",
                        {"items": [item.model_dump() for item in items]},
                    )
                )
            finally:
                fallback_executor.end_invocation(invocation_id)

            if not tool_result.success:
                return {
                    "output": (
                        "No se pudo calcular la vista preliminar con los datos disponibles."
                        if lang == "es"
                        else "The preview could not be calculated with the available details."
                    )
                }
            preview = tool_result.as_provider_value()
            preview_lines = "\n".join(
                f"- {line['quantity']}x {line['name']} @ {line['unit_price']} = {line['subtotal']}"
                for line in preview.get("lines", [])
            )
            heading = (
                "Vista preliminar (no se guarda):" if lang == "es" else "Quote preview (not saved):"
            )
            return {"output": f"{heading}\n{preview_lines}\nSubtotal: {preview['subtotal']}"}

        if (
            "notebook" in clean
            or "product" in clean
            or "producto" in clean
            or "catalogo" in clean
            or "catálogo" in clean
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
            heading = (
                "Productos activos:" if state.get("language") == "es" else "Available products:"
            )
            return {"output": heading + "\n" + "\n".join(lines)}

        if "customer" in clean or "cliente" in clean:
            if user is None or user.role != "staff":
                message = (
                    "Acceso denegado. La información de clientes es solo para staff."
                    if state.get("language") == "es"
                    else "Access denied. Customer records are available to staff only."
                )
                return {"output": message}
            rows = list_customers(conn, limit=50)
            heading = "Clientes:" if state.get("language") == "es" else "Customers:"
            return {
                "output": heading
                + "\n"
                + "\n".join(f"- {row['name']} ({row['code']}, ID: {row['id']})" for row in rows)
            }

        if "quote" in clean or "cotizaci" in clean:
            policy = get_permission_policy_for_user(user)
            if not policy.allows("quote.read"):
                return {
                    "output": (
                        "Acceso denegado. El historial de cotizaciones es solo para staff."
                        if lang == "es"
                        else "Access denied. Quote records are available to staff only."
                    )
                }
            reg = get_agent_tool_registry(conn, user)
            fallback_executor = create_tool_executor(reg, user)
            match_id = re.search(r"(?:quote|cotizaci[oó]n)\s*#?\s*(\d+)", clean)
            if match_id:
                qid = int(match_id.group(1))
                inv_id = f"agent-inv-{uuid.uuid4().hex}"
                call_id = f"agent-call-{uuid.uuid4().hex}"
                try:
                    tool_res = await fallback_executor.execute(
                        ToolRequest(inv_id, call_id, "get_quote", {"quote_id": qid})
                    )
                finally:
                    fallback_executor.end_invocation(inv_id)

                if tool_res.success:
                    val = tool_res.as_provider_value()
                    lines_fmt = "\n".join(
                        f"  {line_item['quantity']}x {line_item['name']} ({line_item['unit_price']}) = {line_item['subtotal']}"
                        for line_item in val.get("lines", [])
                    )
                    header = (
                        f"Cotización #{val['quote_id']} para {val['customer_name']}:"
                        if lang == "es"
                        else f"Quote #{val['quote_id']} for {val['customer_name']}:"
                    )
                    totals = (
                        f"Subtotal: {val['subtotal']}\n"
                        f"Descuento: {val['discount_percent']}% ({val['discount_amount']})\n"
                        f"Total: {val['total']}"
                        if lang == "es"
                        else (
                            f"Subtotal: {val['subtotal']}\n"
                            f"Discount: {val['discount_percent']}% ({val['discount_amount']})\n"
                            f"Total: {val['total']}"
                        )
                    )
                    return {"output": f"{header}\n{lines_fmt}\n{totals}"}
                return {
                    "output": (
                        f"No se encontró la cotización #{qid}."
                        if lang == "es"
                        else f"Quote #{qid} not found."
                    )
                }

            inv_id = f"agent-inv-{uuid.uuid4().hex}"
            call_id = f"agent-call-{uuid.uuid4().hex}"
            try:
                tool_res = await fallback_executor.execute(
                    ToolRequest(inv_id, call_id, "list_quotes", {"limit": 10})
                )
            finally:
                fallback_executor.end_invocation(inv_id)

            if tool_res.success:
                quotes_list = tool_res.as_provider_value()
                if not quotes_list:
                    return {
                        "output": (
                            "No hay cotizaciones en el sistema."
                            if lang == "es"
                            else "No quotes found in system."
                        )
                    }
                fmt = "\n".join(
                    f"- {'Cotización' if lang == 'es' else 'Quote'} #{q['id']} ({q['customer_name']}): {q['total']}"
                    for q in quotes_list
                )
                heading = "Cotizaciones recientes:" if lang == "es" else "Recent quotes:"
                return {"output": f"{heading}\n{fmt}"}

        return {
            "output": (
                "Esa solicitud está fuera del alcance de este agente. Puedo ayudarte a consultar productos, precios o calcular un presupuesto preliminar."
                if lang == "es"
                else "That request is outside the scope of this agent. I can help you consult products, prices, or calculate a preliminary quote preview."
            )
        }

    async def final_output_node(state: DemoState) -> dict[str, Any]:
        """Ensure final output text is present."""
        output = state.get("output", "")
        workflow = state.get("quote_workflow")
        if workflow is not None and state.get("intent") == "catalog_query":
            clean_input = re.sub(r"\s+", " ", state.get("input", "").casefold()).strip()
            clean_input = clean_input.replace("mouses", "mouse").replace("mice", "mouse")
            matching_products = [
                product
                for product in list_active_products(conn)
                if str(product["name"]).casefold() in clean_input
                or str(product["sku"]).casefold() in clean_input
            ]
            if not matching_products and any(
                phrase in clean_input
                for phrase in (
                    "active products",
                    "productos activos",
                    "catalog",
                    "catálogo",
                    "catalogo",
                )
            ):
                matching_products = list_active_products(conn)
            if not matching_products:
                generic_terms = {
                    "active",
                    "activos",
                    "activo",
                    "a",
                    "an",
                    "available",
                    "catalog",
                    "catalogo",
                    "catálogo",
                    "check",
                    "de",
                    "del",
                    "dame",
                    "do",
                    "el",
                    "en",
                    "find",
                    "for",
                    "hay",
                    "how",
                    "in",
                    "is",
                    "la",
                    "list",
                    "lista",
                    "listar",
                    "los",
                    "me",
                    "muestra",
                    "mostrar",
                    "muestrame",
                    "muéstrame",
                    "much",
                    "of",
                    "products",
                    "producto",
                    "productos",
                    "price",
                    "pricing",
                    "please",
                    "que",
                    "qué",
                    "cost",
                    "does",
                    "you",
                    "un",
                    "una",
                    "para",
                    "por",
                    "y",
                    "presupuesto",
                    "preliminar",
                    "calcular",
                    "see",
                    "show",
                    "the",
                    "there",
                    "ver",
                    "what",
                }
                candidates: set[str] = set()
                for token in re.findall(r"\b[\w-]+\b", clean_input):
                    if token in generic_terms or token.isdigit():
                        continue
                    match = find_product_by_query(conn, token)
                    if match is None:
                        continue
                    if match.get("ambiguous"):
                        candidates.update(str(value) for value in match.get("candidates", []))
                    else:
                        candidates.add(f"{match['name']} ({match['sku']})")
                workflow = workflow.model_copy(deep=True)
                workflow.last_candidates = sorted(candidates)
            else:
                workflow = workflow.model_copy(deep=True)
                workflow.last_candidates = [
                    f"{product['name']} ({product['sku']})" for product in matching_products
                ]
        if workflow is not None and state.get("intent") in {
            "catalog_query",
            "customer_query",
            "quote_preview",
            "quote_history",
            "help",
            "acknowledgement",
            "clarification",
            "out_of_scope",
        }:
            lang = state.get("language", "en")
            if not workflow.customer_query:
                next_step = (
                    "El próximo dato pendiente es el cliente."
                    if lang == "es"
                    else "The next missing detail is the customer."
                )
            else:
                incomplete = [item for item in workflow.items if item.status != "resolved"]
                if not workflow.items:
                    next_step = (
                        "El próximo dato pendiente son los productos y sus cantidades."
                        if lang == "es"
                        else "The next missing details are products and quantities."
                    )
                elif incomplete:
                    item = incomplete[0]
                    if not item.product_query:
                        need = "el producto" if lang == "es" else "the product"
                    elif item.quantity is None:
                        need = "la cantidad" if lang == "es" else "the quantity"
                    else:
                        need = (
                            "una referencia de producto válida"
                            if lang == "es"
                            else "a valid product reference"
                        )
                    next_step = (
                        f"Falta {need} para una línea de la cotización."
                        if lang == "es"
                        else f"The quote still needs {need} for one line."
                    )
                else:
                    next_step = (
                        "La cotización sigue pendiente de revisión."
                        if lang == "es"
                        else "The quote is still pending review."
                    )
            reminder = (
                f"La cotización sigue pendiente. {next_step}"
                if lang == "es"
                else f"The quote remains pending. {next_step}"
            )
            output = f"{output}\n\n{reminder}".strip()
        result: dict[str, Any] = {"output": output}
        if workflow is not None and workflow is not state.get("quote_workflow"):
            result["quote_workflow"] = workflow
        return result

    def route_scope_gate(state: DemoState) -> str:
        """Route user request from the host scope gate according to authorization and intent.

        Args:
            state: Current graph state.

        Returns:
            Target node name in the LangGraph StateGraph.
        """
        intent = state.get("intent", "out_of_scope")
        action_allowed = state.get("action_allowed")

        if not action_allowed or intent in ("help", "acknowledgement", "cancel_action"):
            return "final_output"

        if intent == "login":
            return "login_hitl"
        if intent == "logout":
            return "clear_auth"
        if intent == "quote_create":
            return "auth_guard"
        if intent in ("catalog_query", "quote_preview", "quote_history", "customer_query"):
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

    def route_discount_result(state: DemoState) -> str:
        """Continue to persistence only when discount review left a current draft."""
        return (
            "create_quote_tool"
            if _draft_matches_workflow(state.get("quote_workflow"), state.get("quote_draft"))
            else "final_output"
        )

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

    builder.add_conditional_edges(
        "discount_hitl",
        route_discount_result,
        {"create_quote_tool": "create_quote_tool", "final_output": "final_output"},
    )
    builder.add_edge("create_quote_tool", "final_output")

    builder.add_edge("login_hitl", "final_output")
    builder.add_edge("clear_auth", "final_output")
    builder.add_edge("controlled_agent", "final_output")
    builder.add_edge("final_output", END)

    return builder.compile()
