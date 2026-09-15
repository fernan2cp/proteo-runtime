"""Opt-in smoke coverage for the experimental Codex dynamic-tools bridge."""

from __future__ import annotations

import os

import pytest

from proteo_runtime.config import ModelMapping, RuntimeConfigV1
from proteo_runtime.core.profiles import LogicalLevel
from proteo_runtime.providers.codex import CodexRuntime
from proteo_runtime.tools import ToolRegistry, runtime_tool

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("PROTEO_CODEX_DYNAMIC_TOOLS_INTEGRATION") != "1",
        reason="dynamic Codex tools smoke is opt-in",
    ),
]


@runtime_tool(
    name="add_value",
    description="Add one to an integer.",
    permission="smoke.math",
)
async def add_value(value: int) -> int:
    """Return the supplied integer incremented by one."""

    return value + 1


@runtime_tool(
    name="uppercase_value",
    description="Uppercase a short string.",
    permission="smoke.text",
)
async def uppercase_value(value: str) -> str:
    """Return an uppercase string."""

    return value.upper()


def _smoke_config() -> RuntimeConfigV1:
    """Build a disposable Luna/low controlled-agent mapping for the smoke."""

    mapping = {
        level: ModelMapping(model="gpt-5.6-luna", reasoning_effort="low") for level in LogicalLevel
    }
    return RuntimeConfigV1(
        runtime="codex",
        profiles={"controlled_agent": mapping},
    )


@pytest.mark.asyncio
async def test_codex_dynamic_tools_two_calls() -> None:
    """Exercise two host calls and a sanitized final response using Luna/low."""

    registry = ToolRegistry()
    registry.register(add_value)
    registry.register(uppercase_value)
    async with CodexRuntime(
        config=_smoke_config(),
        experimental_dynamic_tools=True,
    ) as runtime:
        model = runtime.model(profile="controlled_agent", level="low").with_tools(registry)
        result = await model.ainvoke(
            "Call add_value with 4 and uppercase_value with 'proteo'. "
            "Use both tools exactly once, then reply with the two results."
        )
        assert result.model == "gpt-5.6-luna"
        assert result.reasoning_effort == "low"
        assert result.output
