"""Host-managed tool definitions, registry factories, and executor factory."""

from __future__ import annotations

import sqlite3
from typing import Any

from auth import get_permission_policy_for_user
from database import (
    find_customer_by_query,
    find_product_by_query,
    format_currency,
    get_quote_by_id,
    list_active_products,
    list_recent_quotes,
    persist_quote_transactional,
)
from models import AuthenticatedUser, QuoteItemInput

from proteo_runtime.tools import (
    ApprovalHandler,
    ApprovalRequirement,
    SideEffect,
    ToolExecutor,
    ToolRegistry,
    runtime_tool,
)


def make_list_products(conn: sqlite3.Connection) -> Any:
    """Create the list_products tool bound to the SQLite connection."""

    @runtime_tool(
        name="list_products",
        description="List all active products in the catalog, optionally filtered by a query.",
        permission="catalog.read",
        side_effect=SideEffect.READ,
        approval=ApprovalRequirement.NEVER,
    )
    async def list_products(query: str = "") -> list[dict[str, Any]]:
        """List active products matching query.

        Args:
            query: Optional search filter for product SKU or name.

        Returns:
            List of product records with formatted pricing.
        """
        all_prods = list_active_products(conn)
        clean = query.strip().lower()
        if not clean:
            return [
                {
                    "id": p["id"],
                    "sku": p["sku"],
                    "name": p["name"],
                    "description": p["description"],
                    "unit_price": format_currency(p["unit_price_cents"]),
                    "unit_price_cents": p["unit_price_cents"],
                    "currency": "USD",
                }
                for p in all_prods
            ]
        return [
            {
                "id": p["id"],
                "sku": p["sku"],
                "name": p["name"],
                "description": p["description"],
                "unit_price": format_currency(p["unit_price_cents"]),
                "unit_price_cents": p["unit_price_cents"],
                "currency": "USD",
            }
            for p in all_prods
            if clean in p["sku"].lower() or clean in p["name"].lower()
        ]

    return list_products


def make_find_product(conn: sqlite3.Connection) -> Any:
    """Create the find_product tool bound to the SQLite connection."""

    @runtime_tool(
        name="find_product",
        description="Find an active product by exact SKU, ID, name, or unique partial name match.",
        permission="catalog.read",
        side_effect=SideEffect.READ,
        approval=ApprovalRequirement.NEVER,
    )
    async def find_product(query: str) -> dict[str, Any]:
        """Find a product by SKU, ID, or name.

        Args:
            query: Product SKU, ID, or name search term.

        Returns:
            Product record with pricing, or error dictionary if not found or ambiguous.
        """
        prod = find_product_by_query(conn, query)
        if prod is None:
            return {"error": f"Product '{query}' not found"}
        if prod.get("ambiguous"):
            return {
                "error": prod["message"],
                "candidates": prod.get("candidates", []),
            }
        return {
            "id": prod["id"],
            "sku": prod["sku"],
            "name": prod["name"],
            "description": prod["description"],
            "unit_price": format_currency(prod["unit_price_cents"]),
            "unit_price_cents": prod["unit_price_cents"],
            "currency": "USD",
        }

    return find_product


def make_calculate_quote(conn: sqlite3.Connection) -> Any:
    """Create the calculate_quote tool bound to the SQLite connection."""

    @runtime_tool(
        name="calculate_quote",
        description="Calculate authoritative quote subtotal and line items without applying discounts or persisting.",
        permission="quote.calculate",
        side_effect=SideEffect.NONE,
        approval=ApprovalRequirement.NEVER,
    )
    async def calculate_quote(items: list[QuoteItemInput]) -> dict[str, Any]:
        """Calculate authoritative subtotal for items.

        Args:
            items: List of QuoteItemInput items.

        Returns:
            Dictionary containing lines and subtotal.
        """
        if not items:
            return {"error": "At least one item is required"}

        lines: list[dict[str, Any]] = []
        subtotal_cents = 0

        for item in items:
            if item.quantity <= 0 or item.product_id <= 0:
                return {
                    "error": f"Invalid item: product_id={item.product_id}, quantity={item.quantity}"
                }
            prod = find_product_by_query(conn, str(item.product_id))
            if prod is None:
                return {"error": f"Product {item.product_id} not found or inactive"}
            if prod.get("ambiguous"):
                return {"error": prod["message"]}

            unit_price = int(prod["unit_price_cents"])
            line_sub = unit_price * item.quantity
            subtotal_cents += line_sub
            lines.append(
                {
                    "product_id": item.product_id,
                    "sku": prod["sku"],
                    "name": prod["name"],
                    "quantity": item.quantity,
                    "unit_price": format_currency(unit_price),
                    "subtotal": format_currency(line_sub),
                    "subtotal_cents": line_sub,
                }
            )

        return {
            "lines": lines,
            "subtotal": format_currency(subtotal_cents),
            "subtotal_cents": subtotal_cents,
            "currency": "USD",
        }

    return calculate_quote


def make_find_customer(conn: sqlite3.Connection) -> Any:
    """Create the find_customer tool bound to the SQLite connection."""

    @runtime_tool(
        name="find_customer",
        description="Search for a customer by code, ID, name, or unique partial match (staff only).",
        permission="customer.read",
        side_effect=SideEffect.READ,
        approval=ApprovalRequirement.NEVER,
    )
    async def find_customer(query: str) -> dict[str, Any]:
        """Find a customer by identifier, code, or name.

        Args:
            query: Customer identifier, code, or name search term.

        Returns:
            Customer record, or error dictionary if not found or ambiguous.
        """
        cust = find_customer_by_query(conn, query)
        if cust is None:
            return {"error": f"Customer '{query}' not found"}
        if cust.get("ambiguous"):
            return {
                "error": cust["message"],
                "candidates": cust.get("candidates", []),
            }
        return cust

    return find_customer


def make_list_quotes(conn: sqlite3.Connection) -> Any:
    """Create the list_quotes tool bound to the SQLite connection."""

    @runtime_tool(
        name="list_quotes",
        description="List recent quotes created in the system (staff only).",
        permission="quote.read",
        side_effect=SideEffect.READ,
        approval=ApprovalRequirement.NEVER,
    )
    async def list_quotes(limit: int = 10) -> list[dict[str, Any]]:
        """List recent quotes.

        Args:
            limit: Maximum number of quotes to return (bounded between 1 and 50).

        Returns:
            List of quote summary records.
        """
        bounded = max(1, min(50, limit))
        raw_quotes = list_recent_quotes(conn, limit=bounded)
        return [
            {
                "id": q["id"],
                "customer_name": q["customer_name"],
                "creator_name": q["creator_name"],
                "created_at": q["created_at"],
                "total": format_currency(q["total_cents"]),
                "currency": q["currency"],
            }
            for q in raw_quotes
        ]

    return list_quotes


def make_get_quote(conn: sqlite3.Connection) -> Any:
    """Create the get_quote tool bound to the SQLite connection."""

    @runtime_tool(
        name="get_quote",
        description="Fetch detailed information for a specific quote including line items (staff only).",
        permission="quote.read",
        side_effect=SideEffect.READ,
        approval=ApprovalRequirement.NEVER,
    )
    async def get_quote(quote_id: int) -> dict[str, Any]:
        """Fetch full quote details.

        Args:
            quote_id: Primary key of the quote (must be greater than zero).

        Returns:
            Detailed quote dictionary, or error if not found.
        """
        if quote_id <= 0:
            return {"error": "Invalid quote_id: must be greater than zero"}
        quote = get_quote_by_id(conn, quote_id)
        if quote is None:
            return {"error": f"Quote #{quote_id} not found"}

        formatted_lines = [
            {
                "product_id": line["product_id"],
                "sku": line["sku"],
                "name": line["name"],
                "quantity": line["quantity"],
                "unit_price": format_currency(line["unit_price_cents"]),
                "subtotal": format_currency(line["subtotal_cents"]),
            }
            for line in quote["lines"]
        ]

        return {
            "quote_id": quote["id"],
            "customer_name": quote["customer_name"],
            "creator_name": quote["creator_name"],
            "created_at": quote["created_at"],
            "subtotal": format_currency(quote["subtotal_cents"]),
            "discount_percent": quote["discount_percent"],
            "discount_amount": format_currency(quote["discount_amount_cents"]),
            "total": format_currency(quote["total_cents"]),
            "currency": quote["currency"],
            "lines": formatted_lines,
        }

    return get_quote


def make_create_quote(conn: sqlite3.Connection, user: AuthenticatedUser) -> Any:
    """Create the create_quote tool bound to an authenticated staff user."""

    @runtime_tool(
        name="create_quote",
        description="Persist an approved quote for a customer in the database (staff only).",
        permission="quote.create",
        side_effect=SideEffect.WRITE,
        approval=ApprovalRequirement.FOR_SIDE_EFFECTS,
    )
    async def create_quote(
        customer_id: int,
        items: list[QuoteItemInput],
        discount_percent: int = 0,
    ) -> dict[str, Any]:
        """Persist quote transactionally after human approval.

        Args:
            customer_id: Target customer ID (must be greater than zero).
            items: List of QuoteItemInput items.
            discount_percent: Whole discount percentage (0..30).

        Returns:
            Dictionary summarizing created quote.

        Raises:
            PermissionError: If user is not staff.
            ValueError: If inputs fail domain validation.
        """
        if user.role != "staff":
            raise PermissionError("Staff authentication required to persist quote")
        if customer_id <= 0:
            raise ValueError("customer_id must be greater than zero")
        if not items:
            raise ValueError("At least one item is required")
        if not (0 <= discount_percent <= 30):
            raise ValueError("discount_percent must be between 0 and 30")

        lines_tuple = [(item.product_id, item.quantity) for item in items]
        quote_id = persist_quote_transactional(
            conn,
            customer_id=customer_id,
            created_by_user_id=user.user_id,
            lines=lines_tuple,
            discount_percent=discount_percent,
        )
        created = get_quote_by_id(conn, quote_id)
        if created is None:
            raise RuntimeError("Failed to read back created quote")
        return {
            "quote_id": quote_id,
            "customer_name": created["customer_name"],
            "created_at": created["created_at"],
            "creator_name": created["creator_name"],
            "subtotal": format_currency(created["subtotal_cents"]),
            "discount_percent": created["discount_percent"],
            "discount_amount": format_currency(created["discount_amount_cents"]),
            "total": format_currency(created["total_cents"]),
            "currency": created["currency"],
            "status": "created",
        }

    return create_quote


def get_agent_tool_registry(
    conn: sqlite3.Connection,
    user: AuthenticatedUser | None,
) -> ToolRegistry:
    """Return the tool registry available to the controlled conversational agent.

    Public and client sessions expose:
    - list_products
    - find_product
    - calculate_quote

    Staff sessions also expose:
    - find_customer
    - list_quotes
    - get_quote

    Under NO circumstances is `create_quote` exposed to the free conversational agent.

    Args:
        conn: Open SQLite database connection.
        user: Authenticated user identity, or None if anonymous.

    Returns:
        Populated ToolRegistry with conversational tools.
    """
    registry = ToolRegistry()
    registry.register(make_list_products(conn))
    registry.register(make_find_product(conn))
    registry.register(make_calculate_quote(conn))

    if user is not None and user.role == "staff":
        registry.register(make_find_customer(conn))
        registry.register(make_list_quotes(conn))
        registry.register(make_get_quote(conn))

    return registry


def get_quote_write_registry(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
) -> ToolRegistry:
    """Return the dedicated tool registry for the deterministic quote write workflow.

    Args:
        conn: Open SQLite database connection.
        user: Authenticated staff user identity.

    Returns:
        Populated ToolRegistry containing only create_quote.
    """
    registry = ToolRegistry()
    registry.register(make_create_quote(conn, user))
    return registry


def create_tool_registry(
    conn: sqlite3.Connection,
    user: AuthenticatedUser | None = None,
) -> ToolRegistry:
    """Compatibility registry factory returning the conversational tool registry.

    Args:
        conn: Open SQLite database connection.
        user: Optional user identity.

    Returns:
        ToolRegistry without create_quote.
    """
    return get_agent_tool_registry(conn, user)


def create_tool_executor(
    registry: ToolRegistry,
    user: AuthenticatedUser | None,
    approval_handler: ApprovalHandler | None = None,
) -> ToolExecutor:
    """Create a ToolExecutor bound with the user's role policy and approval handler.

    Args:
        registry: Configured ToolRegistry.
        user: Authenticated user identity, or None if anonymous.
        approval_handler: Optional Phase 5 ApprovalHandler for write confirmation.

    Returns:
        Configured ToolExecutor.
    """
    policy = get_permission_policy_for_user(user)
    return ToolExecutor(
        registry,
        permission_policy=policy,
        approval_handler=approval_handler,
    )
