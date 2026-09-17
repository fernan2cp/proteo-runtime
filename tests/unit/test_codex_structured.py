"""Unit tests for strict structured-output schema normalization and runtime invocation."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from proteo_runtime.core.model import RuntimeResult
from proteo_runtime.providers.codex import runtime as codex_runtime
from proteo_runtime.providers.codex._structured import (
    _normalize_sdk_schema,
    _SchemaAdapter,
)

# Ensure examples/smart_quote_agent is on sys.path for QuoteRequest import
_DEMO_DIR = Path(__file__).resolve().parent.parent.parent / "examples" / "smart_quote_agent"
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from models import QuoteRequest, RequestedItem  # noqa: E402
from test_codex_provider import (  # noqa: E402
    FakeNotification,
    FakeSDK,
    FakeTurn,
    install_sdk,
)


def _json_notifications(text: str) -> tuple[FakeNotification, ...]:
    """Build a notification sequence returning a specific JSON text payload.

    Args:
        text: JSON response text to emit in the agent message.

    Returns:
        Tuple of FakeNotification objects representing turn completion.
    """
    item = SimpleNamespace(type="agentMessage", text=text)
    turn = SimpleNamespace(
        id="turn-1",
        status="completed",
        items=[item],
        duration_ms=15,
    )
    usage = SimpleNamespace(
        last=SimpleNamespace(
            inputTokens=10,
            outputTokens=5,
            totalTokens=15,
            cachedInputTokens=2,
            reasoningOutputTokens=0,
            cacheWriteInputTokens=0,
        ),
        model_context_window=1000,
    )
    return (
        FakeNotification("item/completed", SimpleNamespace(item=item)),
        FakeNotification("thread/tokenUsage/updated", SimpleNamespace(token_usage=usage)),
        FakeNotification("turn/completed", SimpleNamespace(turn=turn)),
    )


def test_a1_required_nullable_scalar() -> None:
    """A1: Validate required nullable scalar schema normalization.

    Verifies that for a model with an optional nullable scalar:
    - the field appears in the 'required' list;
    - accepts both string and null via anyOf;
    - does not contain an incompatible 'default: null'.
    """

    class ExampleScalar(BaseModel):
        """Test model containing an optional nullable scalar field."""

        model_config = ConfigDict(extra="forbid")
        value: str | None = None

    raw_schema = ExampleScalar.model_json_schema()
    normalized = _normalize_sdk_schema(raw_schema)

    assert normalized.get("type") == "object"
    assert normalized.get("additionalProperties") is False
    assert "value" in normalized.get("required", [])
    assert "default" not in normalized["properties"]["value"]

    val_prop = normalized["properties"]["value"]
    types_allowed = {
        item.get("type")
        for item in val_prop.get("anyOf", ())
        if isinstance(item, dict) and "type" in item
    }
    assert "string" in types_allowed
    assert "null" in types_allowed


def test_a2_nested_nullable_fields_quote_request() -> None:
    """A2: Validate nested nullable schema normalization on QuoteRequest and RequestedItem.

    Recursively verifies:
    - root properties are listed in 'required';
    - nested item properties are listed in 'required';
    - customer, product, and quantity retain nullable semantics via anyOf;
    - items is an array schema referencing RequestedItem;
    - nested object schemas have additionalProperties set to False.
    """
    raw_schema = QuoteRequest.model_json_schema()
    normalized = _normalize_sdk_schema(raw_schema)

    # Root object assertions
    assert normalized.get("type") == "object"
    assert normalized.get("additionalProperties") is False
    assert set(normalized.get("required", [])) == {"customer", "items"}

    # Customer field assertions
    customer_prop = normalized["properties"]["customer"]
    assert "default" not in customer_prop
    cust_types = {item.get("type") for item in customer_prop.get("anyOf", ())}
    assert "string" in cust_types
    assert "null" in cust_types

    # Items field assertions
    items_prop = normalized["properties"]["items"]
    assert items_prop.get("type") == "array"
    assert "$ref" in items_prop.get("items", {})

    # Nested RequestedItem assertions in $defs
    defs = normalized.get("$defs", {})
    assert "RequestedItem" in defs
    item_schema = defs["RequestedItem"]
    assert item_schema.get("type") == "object"
    assert item_schema.get("additionalProperties") is False
    assert set(item_schema.get("required", [])) == {"product", "quantity"}

    # Product and quantity nullable assertions
    product_prop = item_schema["properties"]["product"]
    assert "default" not in product_prop
    prod_types = {item.get("type") for item in product_prop.get("anyOf", ())}
    assert "string" in prod_types
    assert "null" in prod_types

    qty_prop = item_schema["properties"]["quantity"]
    assert "default" not in qty_prop
    qty_types = {item.get("type") for item in qty_prop.get("anyOf", ())}
    assert "integer" in qty_types
    assert "null" in qty_types


def test_a3_empty_missing_semantic_values_validate_correctly() -> None:
    """A3: Validate host validation accepts null and empty collections for QuoteRequest."""
    adapter = _SchemaAdapter.create(QuoteRequest)

    # Valid payload with missing customer and empty items
    payload_empty = '{"customer": null, "items": []}'
    result_empty = adapter.validate(payload_empty)
    assert isinstance(result_empty, QuoteRequest)
    assert result_empty.customer is None
    assert result_empty.items == []

    # Valid payload with item having null product and null quantity
    payload_null_item = '{"customer": "Acme", "items": [{"product": null, "quantity": null}]}'
    result_item = adapter.validate(payload_null_item)
    assert isinstance(result_item, QuoteRequest)
    assert result_item.customer == "Acme"
    assert len(result_item.items) == 1
    assert isinstance(result_item.items[0], RequestedItem)
    assert result_item.items[0].product is None
    assert result_item.items[0].quantity is None


@pytest.mark.asyncio
async def test_a4_canonical_structured_runtime_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A4: Validate canonical structured runtime invocation with null values and strict schema."""
    json_response = '{"customer": null, "items": [{"product": "Wireless Mouse", "quantity": 2}]}'
    sdk = FakeSDK(turns=[FakeTurn(notifications=_json_notifications(json_response))])
    install_sdk(monkeypatch, sdk)

    runtime = codex_runtime.CodexRuntime()
    await runtime.start()

    try:
        model = runtime.model(profile="structured", level="low").with_structured_output(
            QuoteRequest
        )
        res: RuntimeResult[QuoteRequest] = await model.ainvoke(
            "Create a quote for 2 Wireless Mouse"
        )

        assert isinstance(res.value, QuoteRequest)
        assert res.value.customer is None
        assert len(res.value.items) == 1
        assert res.value.items[0].product == "Wireless Mouse"
        assert res.value.items[0].quantity == 2

        # Verify that the provider received the strict normalized schema
        assert len(sdk.turn_calls) == 1
        _args, kwargs = sdk.turn_calls[0]
        schema_passed = kwargs.get("output_schema")
        assert schema_passed is not None
        assert schema_passed.get("additionalProperties") is False
        assert set(schema_passed.get("required", [])) == {"customer", "items"}
        assert "default" not in schema_passed["properties"]["customer"]
        assert "$defs" in schema_passed
        assert schema_passed["$defs"]["RequestedItem"]["additionalProperties"] is False
        assert set(schema_passed["$defs"]["RequestedItem"]["required"]) == {
            "product",
            "quantity",
        }
    finally:
        await runtime.close()
