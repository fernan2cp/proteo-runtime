"""Opt-in real Codex smoke tests through the LangGraph adapter."""

from __future__ import annotations

import os
from typing import Any, TypedDict, cast

import pytest
from langgraph.graph import END, START, StateGraph

from proteo_runtime.core.runtime import Runtime
from proteo_runtime.integrations.langgraph import RuntimeNode

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("PROTEO_CODEX_INTEGRATION") != "1", reason="Codex integration is opt-in"
    ),
]

LUNA_MODEL = "gpt-5.6-luna"
LUNA_LEVEL = "low"


class State(TypedDict, total=False):
    """Minimal graph state for the live adapter smoke."""

    input: str
    output: Any
    model: str
    reasoning_effort: str | None


def _graph(node: RuntimeNode[State]) -> Any:
    """Compile a StateGraph containing one live RuntimeNode."""

    builder = StateGraph(State)
    builder.add_node("proteo", node)
    builder.add_edge(START, "proteo")
    builder.add_edge("proteo", END)
    return builder.compile()


@pytest.mark.asyncio
async def test_langgraph_brain_smoke() -> None:
    """Invoke one real Luna turn through a StateGraph."""

    from proteo_runtime.providers.codex import CodexRuntime

    async with CodexRuntime() as runtime:
        model = await runtime.brain(level=LUNA_LEVEL)
        result = await _graph(
            RuntimeNode[State](
                model,
                output_mapper=lambda value: {
                    "output": value.value,
                    "model": value.model,
                    "reasoning_effort": value.reasoning_effort,
                },
            )
        ).ainvoke({"input": "Reply with one word."})
        assert result["output"]
        assert result["model"] == LUNA_MODEL
        assert result["reasoning_effort"] == LUNA_LEVEL


@pytest.mark.asyncio
async def test_langgraph_session_smoke() -> None:
    """Resume a host-created Luna session through a configured StateGraph."""

    from proteo_runtime.providers.codex import CodexRuntime

    async with CodexRuntime() as runtime:
        session = await runtime.session(level=LUNA_LEVEL)
        descriptor = session.descriptor
        await session.close()
        result = await _graph(
            RuntimeNode[State](
                cast(Runtime, runtime),
                output_mapper=lambda value: {
                    "output": value.value,
                    "model": value.model,
                    "reasoning_effort": value.reasoning_effort,
                },
            )
        ).ainvoke(
            {"input": "Reply with one word."},
            config={
                "configurable": {
                    "thread_id": "codex-langgraph-smoke",
                    "proteo_session_id": descriptor,
                }
            },
        )
        assert result["output"]
        assert result["model"] == LUNA_MODEL
        assert result["reasoning_effort"] == LUNA_LEVEL
