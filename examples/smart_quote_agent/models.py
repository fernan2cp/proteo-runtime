"""Domain and graph state models, Pydantic schemas, and typed dictionaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class IntentDecision(BaseModel):
    """Structured classifier output for top-level user intent."""

    model_config = ConfigDict(extra="forbid")

    intent: Literal[
        "login",
        "logout",
        "help",
        "catalog_query",
        "quote_preview",
        "quote_history",
        "quote_create",
        "out_of_scope",
    ] = Field(
        description="The classified intent of the user request.",
    )


class RequestedItem(BaseModel):
    """Product quantity item extracted from quote request text."""

    model_config = ConfigDict(extra="forbid")

    product: str | None = Field(
        default=None,
        description="Product name, SKU, or descriptor if explicitly stated; null if missing.",
    )
    quantity: int | None = Field(
        default=None,
        gt=0,
        description="Quantity requested if explicitly stated (must be > 0); null if missing.",
    )


class QuoteRequest(BaseModel):
    """Extracted quote creation request parameters from natural language."""

    model_config = ConfigDict(extra="forbid")

    customer: str | None = Field(
        default=None,
        description="Customer name or code identified from the request; null if missing.",
    )
    items: list[RequestedItem] = Field(
        default_factory=list,
        description="List of requested products and quantities explicitly stated in the request.",
    )


class QuoteItemInput(BaseModel):
    """Validated item input shape for calculation and quote creation tools."""

    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(
        gt=0,
        description="Catalog product ID (must be greater than zero).",
    )
    quantity: int = Field(
        gt=0,
        description="Requested quantity (must be greater than zero).",
    )


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Sanitized representation of an authenticated user identity in host state.

    Crucially excludes raw passwords, credential tokens, or database connection details.
    """

    user_id: int
    username: str
    display_name: str
    role: Literal["staff", "client"]
    customer_id: int | None = None


class QuoteLineDraft(TypedDict):
    """Authoritative quote line calculated host-side from database records."""

    product_id: int
    sku: str
    name: str
    quantity: int
    unit_price_cents: int
    subtotal_cents: int


class QuoteDraft(TypedDict):
    """Authoritative quote draft calculated host-side prior to persistence."""

    customer_id: int
    customer_name: str
    lines: list[QuoteLineDraft]
    subtotal_cents: int
    discount_percent: int
    discount_amount_cents: int
    total_cents: int


class DemoState(TypedDict, total=False):
    """Host-owned state for the LangGraph workflow."""

    input: str
    output: str
    authenticated_user: AuthenticatedUser | None
    intent: str
    action_allowed: bool | None
    quote_authorized: bool | None
    quote_request: QuoteRequest | None
    quote_draft: QuoteDraft | None
    created_quote_id: int | None
