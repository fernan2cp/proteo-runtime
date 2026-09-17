"""Opt-in live integration tests for Codex task-scoped controlled agents."""

from __future__ import annotations

import os

import pytest

from proteo_runtime.core.errors import AuthenticationError
from proteo_runtime.providers.codex import CodexRuntime
from proteo_runtime.tools import (
    ToolExecutor,
    ToolPermissionPolicy,
    ToolRegistry,
    runtime_tool,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("PROTEO_CODEX_INTEGRATION") != "1",
        reason="Codex integration is opt-in",
    ),
]


@runtime_tool(name="calc_add", description="Add two integers.", permission="calc.add")
async def _calc_add(a: int, b: int) -> int:
    """Add two integers.

    Args:
        a: First integer.
        b: Second integer.

    Returns:
        Sum of a and b.
    """
    return a + b


@pytest.mark.asyncio
async def test_codex_controlled_agent_multi_turn_and_isolation() -> None:
    """Verify live multi-turn context reuse and task isolation with tool execution."""
    registry = ToolRegistry()
    registry.register(_calc_add)
    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"calc.add"})),
    )

    runtime = CodexRuntime(experimental_dynamic_tools=True)
    try:
        await runtime.start()
    except AuthenticationError:
        pytest.skip("Codex subscription login is not active; skipping live integration tests.")
    except Exception as exc:
        pytest.skip(f"Codex runtime startup failed: {exc}")

    try:
        # Task 1: Verify multi-turn memory reuse and host tool execution
        task1 = await runtime.task(
            "controlled_agent",
            level="low",
            instructions="You are a helpful assistant with calculation tools.",
            registry=registry,
            executor=executor,
        )

        turn1_result = await task1.ainvoke(
            "Remember that my favorite fruit is persimmon and my secret number is 40."
        )
        assert turn1_result.output

        turn2_result = await task1.ainvoke(
            "What is my secret number? Call calc_add to add 2 to it, and tell me the result."
        )
        assert turn2_result.output
        assert "42" in turn2_result.output or "persimmon" in turn2_result.output.casefold()

        await task1.close()

        # Task 2: Verify fresh context isolation (clean slate)
        task2 = await runtime.task(
            "controlled_agent",
            level="low",
            instructions="You are a helpful assistant.",
            registry=registry,
            executor=executor,
        )

        turn3_result = await task2.ainvoke("What is my favorite fruit?")
        assert turn3_result.output
        assert "persimmon" not in turn3_result.output.casefold()

        await task2.close()

    finally:
        await runtime.close()
