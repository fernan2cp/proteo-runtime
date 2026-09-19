"""Domain and graph state models, Pydantic schemas, and typed dictionaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, TypeAlias, TypedDict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IntentDecision(BaseModel):
    """Structured classifier output for top-level user intent."""

    model_config = ConfigDict(extra="forbid")

    intent: Literal[
        "login",
        "logout",
        "help",
        "acknowledgement",
        "catalog_query",
        "quote_preview",
        "quote_history",
        "customer_query",
        "quote_create",
        "out_of_scope",
        "clarification",
    ] = Field(
        description="The classified intent of the user request.",
    )

    language: Literal["es", "en"] | None = Field(
        default=None,
        description="Confident language detected for the current turn, or null when ambiguous.",
    )


class _QuotePatchOperationBase(BaseModel):
    """Shared strict field definitions for quote patch operation variants."""

    model_config = ConfigDict(extra="forbid")

    target: str | None = None
    product: str | None = None
    quantity: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_nonblank_references(self) -> _QuotePatchOperationBase:
        """Reject blank target and product references in patch operations.

        Returns:
            This validated operation.

        Raises:
            ValueError: If an optional target or product is blank rather than absent.
        """
        if self.target is not None and not self.target.strip():
            raise ValueError("Quote patch target cannot be blank")
        if self.product is not None and not self.product.strip():
            raise ValueError("Quote patch product cannot be blank")
        return self


class SetCustomerOperation(_QuotePatchOperationBase):
    """Set the customer reference for a pending quote workflow."""

    operation: Literal["set_customer"]
    target: str = Field(min_length=1)
    product: None = None
    quantity: None = None


class AddItemOperation(_QuotePatchOperationBase):
    """Add a product line to a pending quote workflow."""

    operation: Literal["add_item"]
    target: None = None
    product: str = Field(min_length=1)
    quantity: int | None = Field(default=None, gt=0)


class ReplaceItemOperation(_QuotePatchOperationBase):
    """Replace the product on one identified quote line."""

    operation: Literal["replace_item"]
    target: str = Field(min_length=1)
    product: str = Field(min_length=1)
    quantity: None = None


class SetQuantityOperation(_QuotePatchOperationBase):
    """Set the quantity for one uniquely identified quote line."""

    operation: Literal["set_quantity"]
    target: str | None = None
    product: None = None
    quantity: int = Field(gt=0)


class RemoveItemOperation(_QuotePatchOperationBase):
    """Remove one identified quote line."""

    operation: Literal["remove_item"]
    target: str = Field(min_length=1)
    product: None = None
    quantity: None = None


QuotePatchOperation: TypeAlias = Annotated[
    SetCustomerOperation
    | AddItemOperation
    | ReplaceItemOperation
    | SetQuantityOperation
    | RemoveItemOperation,
    Field(discriminator="operation"),
]


class QuotePatch(BaseModel):
    """Collection of proposed quote changes validated and applied by the host."""

    model_config = ConfigDict(extra="forbid")

    operations: list[QuotePatchOperation] = Field(default_factory=list)


class TurnDecision(IntentDecision):
    """Context-aware turn classification with an optional quote edit proposal."""

    quote_patch: QuotePatch | None = None


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


class QuoteWorkflowItem(BaseModel):
    """Host-owned mutable line intent for an in-progress quote."""

    model_config = ConfigDict(extra="forbid")

    line_id: str = Field(default_factory=lambda: f"line_{uuid4().hex}")
    product_query: str | None = None
    quantity: int | None = Field(default=None, gt=0)
    product_id: int | None = Field(default=None, gt=0)
    sku: str | None = None
    canonical_name: str | None = None
    status: Literal["incomplete", "unresolved", "ambiguous", "resolved"] = "incomplete"
    candidates: list[str] = Field(default_factory=list)


class QuoteWorkflowState(BaseModel):
    """Authoritative host state for one in-progress quote conversation."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(default_factory=lambda: f"quote_{uuid4().hex}")
    revision: int = 1
    phase: Literal["collecting", "needs_resolution", "ready_for_review"] = "collecting"
    customer_query: str | None = None
    customer_id: int | None = Field(default=None, gt=0)
    customer_name: str | None = None
    items: list[QuoteWorkflowItem] = Field(default_factory=list)
    focused_line_id: str | None = None
    last_candidates: list[str] = Field(default_factory=list)


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

    workflow_id: str
    workflow_revision: int
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
    pending_action: str | None
    pending_quote_request: QuoteRequest | None
    quote_workflow: QuoteWorkflowState | None
    quote_patch: QuotePatch | None
    interaction_id: str
    quote_request: QuoteRequest | None
    quote_draft: QuoteDraft | None
    created_quote_id: int | None
    language: Literal["es", "en"]
