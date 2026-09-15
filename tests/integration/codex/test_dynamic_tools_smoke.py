"""Opt-in smoke coverage for the experimental Codex dynamic-tools bridge."""

from __future__ import annotations

import os
import secrets

import pytest

from proteo_runtime.config import ModelMapping, RuntimeConfigV1
from proteo_runtime.core.profiles import LogicalLevel
from proteo_runtime.providers.codex import CodexRuntime
from proteo_runtime.tools import ToolExecutor, ToolPermissionPolicy, ToolRegistry, runtime_tool

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("PROTEO_CODEX_DYNAMIC_TOOLS_INTEGRATION") != "1",
        reason="dynamic Codex tools smoke is opt-in",
    ),
]


@runtime_tool(
    name="issue_runtime_nonce",
    description="Issue an opaque runtime nonce for a supplied label. The value cannot be computed by the model.",
    permission="smoke.math",
)
async def issue_runtime_nonce(label: str) -> str:
    """Return an unpredictable host-generated nonce for the supplied label."""

    return f"{label}-{secrets.token_hex(8)}"


@runtime_tool(
    name="issue_runtime_marker",
    description="Issue an opaque runtime marker for a supplied label. The value cannot be computed by the model.",
    permission="smoke.text",
)
async def issue_runtime_marker(label: str) -> str:
    """Return an unpredictable host-generated marker for the supplied label."""

    return f"{label}-{secrets.token_hex(8)}"


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
    registry.register(issue_runtime_nonce)
    registry.register(issue_runtime_marker)
    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"smoke.math", "smoke.text"})),
    )
    async with CodexRuntime(
        config=_smoke_config(),
        experimental_dynamic_tools=True,
    ) as runtime:
        model = runtime.model(profile="controlled_agent", level="low").with_tools(
            registry, executor=executor
        )
        result = await model.ainvoke(
            "You MUST call issue_runtime_nonce with label 'alpha' and issue_runtime_marker "
            "with label 'beta', exactly once each. Their outputs are opaque values that only "
            "the host can generate; do not calculate, guess, or answer until both tool calls "
            "have completed. Then reply by quoting both exact returned values."
        )
        assert result.model == "gpt-5.6-luna"
        assert result.reasoning_effort == "low"
        assert result.output
    completed = [event for event in executor.events if event.kind.value == "tool_completed"]
    assert len(completed) >= 2
