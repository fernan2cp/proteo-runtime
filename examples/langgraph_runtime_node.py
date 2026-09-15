"""Demonstrate brain, structured, and resume-only session LangGraph nodes."""

from __future__ import annotations

from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from proteo_runtime.core.runtime import Runtime
from proteo_runtime.integrations.langgraph import RuntimeNode
from proteo_runtime.providers.codex import CodexRuntime


class Decision(BaseModel):
    """Structured planner result."""

    decision: str


class GraphState(TypedDict, total=False):
    """State owned by the LangGraph host."""

    input: str
    output: Any


def _compile(node: RuntimeNode[GraphState]) -> Any:
    """Compile a one-node graph around a RuntimeNode."""

    builder = StateGraph(GraphState)
    builder.add_node("proteo", node)
    builder.add_edge(START, "proteo")
    builder.add_edge("proteo", END)
    return builder.compile()


async def main() -> None:
    """Run all three Phase 3 node modes with explicit host-owned session state."""

    async with CodexRuntime() as runtime:
        brain = await runtime.brain(level="low")
        brain_result = await _compile(RuntimeNode[GraphState](brain)).ainvoke(
            {"input": "Say hello."}
        )
        print(brain_result["output"])

        structured = (await runtime.brain(level="low")).with_structured_output(Decision)
        structured_result = await _compile(RuntimeNode[GraphState](structured)).ainvoke(
            {"input": "Return decision yes."}
        )
        print(structured_result["output"])

        session = await runtime.session(level="low")
        session_descriptor = session.descriptor
        await session.close()
        session_graph = _compile(RuntimeNode[GraphState](cast(Runtime, runtime)))
        session_result = await session_graph.ainvoke(
            {"input": "Continue the investigation."},
            config={
                "configurable": {
                    "thread_id": "example-thread",
                    "proteo_session_id": session_descriptor,
                }
            },
        )
        print(session_result["output"])


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
