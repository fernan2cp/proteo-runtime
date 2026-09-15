"""Contract tests for RuntimeNode inside real LangGraph StateGraphs."""

from __future__ import annotations

import json
from typing import Any, TypedDict, cast

import pytest
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from proteo_runtime.integrations.langgraph import RuntimeNode
from proteo_runtime.testing import FakeRuntime, FakeTurn


class State(TypedDict, total=False):
    """Minimal graph state shared by contract scenarios."""

    input: str
    output: Any


class Decision(BaseModel):
    """Structured graph value."""

    decision: str


def _graph(node: RuntimeNode[Any]) -> Any:
    """Compile one-node StateGraph using the public adapter callable."""

    builder = StateGraph(State)
    builder.add_node("proteo", node)
    builder.add_edge(START, "proteo")
    builder.add_edge("proteo", END)
    return builder.compile()


@pytest.mark.asyncio
async def test_stategraph_brain_and_structured_nodes_return_neutral_state() -> None:
    """StateGraph can execute both plain and structured provider-neutral models."""

    brain_runtime = FakeRuntime(turns=[FakeTurn(value="brain")])
    brain_result = await _graph(RuntimeNode[Any](brain_runtime.model(profile="brain"))).ainvoke(
        {"input": "hello"}
    )
    assert brain_result["output"] == "brain"

    structured_runtime = FakeRuntime(turns=[FakeTurn(value='{"decision":"yes"}')])
    structured = structured_runtime.model(profile="brain").with_structured_output(Decision)
    structured_result = await _graph(RuntimeNode[Any](structured)).ainvoke({"input": "choose"})
    assert structured_result["output"] == Decision(decision="yes")
    assert all("RuntimeResult" not in repr(value) for value in structured_result.values())


@pytest.mark.asyncio
async def test_stategraph_json_schema_output_passes_through_validated_value() -> None:
    """StateGraph can execute a model linked with a JSON Schema output contract."""

    schema = {
        "type": "object",
        "properties": {"decision": {"type": "string"}},
        "required": ["decision"],
        "additionalProperties": False,
    }
    runtime = FakeRuntime(turns=[FakeTurn(value='{"decision":"yes"}')])
    structured = runtime.model(profile="brain").with_structured_output(schema)

    result = await _graph(RuntimeNode[Any](structured)).ainvoke({"input": "choose"})

    assert result["output"] == {"decision": "yes"}


@pytest.mark.asyncio
async def test_stategraph_custom_stream_is_json_safe_and_ordered() -> None:
    """LangGraph custom mode receives ordered neutral envelopes without raw state objects."""

    runtime = FakeRuntime(turns=[FakeTurn(value="streamed")])
    graph = _graph(RuntimeNode[Any](runtime.model(profile="brain")))
    chunks = [
        chunk
        async for chunk in graph.astream({"input": "stream"}, stream_mode="custom", version="v2")
    ]
    events = [chunk["data"] for chunk in chunks if chunk["type"] == "custom"]

    assert events
    assert [event["event"]["sequence"] for event in events] == sorted(
        event["event"]["sequence"] for event in events
    )
    assert events[-1]["event"]["kind"] == "invocation_completed"
    serialized = json.dumps(events)
    assert "RuntimeResult" not in serialized
    assert "raw" not in serialized


@pytest.mark.asyncio
async def test_stategraph_session_uses_host_configured_descriptor() -> None:
    """A persistent node resumes only the descriptor supplied by configurable state."""

    runtime = FakeRuntime(turns=[FakeTurn(value="session")])
    created = await runtime.session()
    descriptor = created.descriptor
    await created.close()
    graph = _graph(RuntimeNode[Any](cast(Any, runtime)))

    result = await graph.ainvoke(
        {"input": "continue"},
        config={"configurable": {"thread_id": "graph-thread", "proteo_session_id": descriptor}},
    )

    assert result["output"] == "session"
    assert descriptor not in json.dumps(result)
