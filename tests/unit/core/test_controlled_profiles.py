"""Unit tests for profile resolution, capabilities, and factory boundary enforcement."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from proteo_runtime.config import load_runtime_config
from proteo_runtime.core.capabilities import RuntimeCapabilities
from proteo_runtime.core.context import ContextPolicy
from proteo_runtime.core.errors import CapabilityError
from proteo_runtime.core.profiles import (
    DEFAULT_PROFILE_SPECS,
    ExecutionProfile,
    HostToolsMode,
    LifecycleMode,
    LogicalLevel,
    profile_spec,
)
from proteo_runtime.core.security import SecurityPolicy
from proteo_runtime.providers.codex.runtime import CodexRuntime
from proteo_runtime.testing.fakes import FakeRuntime
from proteo_runtime.tools import ToolRegistry, runtime_tool

# Ensure tests/unit is available for imports
_unit_dir = str(Path(__file__).resolve().parent.parent)
if _unit_dir not in sys.path:
    sys.path.insert(0, _unit_dir)

from test_codex_provider import FakeSDK, install_sdk  # noqa: E402


@runtime_tool(name="sample_tool", description="Sample tool for tests.", permission="test.sample")
async def _sample_tool(arg: str) -> str:
    """Return the input argument.

    Args:
        arg: String input.

    Returns:
        The same string.
    """
    return arg


def test_default_profile_specs_declaration() -> None:
    """Verify controlled_turn and controlled_agent specifications in default table."""
    turn_spec = DEFAULT_PROFILE_SPECS["controlled_turn"]
    assert turn_spec.lifecycle is LifecycleMode.EPHEMERAL
    assert turn_spec.context is ContextPolicy.EXTERNAL
    assert turn_spec.host_tools is HostToolsMode.CONTROLLED
    assert turn_spec.security_policy is SecurityPolicy.CONTROLLED_TOOLS

    agent_spec = DEFAULT_PROFILE_SPECS["controlled_agent"]
    assert agent_spec.lifecycle is LifecycleMode.EPHEMERAL
    assert agent_spec.context is ContextPolicy.RUNTIME
    assert agent_spec.host_tools is HostToolsMode.CONTROLLED
    assert agent_spec.security_policy is SecurityPolicy.CONTROLLED_TOOLS

    assert profile_spec(ExecutionProfile.CONTROLLED_AGENT) == agent_spec
    assert profile_spec("controlled_turn") == turn_spec


def test_packaged_codex_defaults_for_controlled_turn_and_agent() -> None:
    """Verify packaged default configuration maps both profiles across all logical levels."""
    config = load_runtime_config()
    for profile in ("controlled_turn", "controlled_agent"):
        for level in LogicalLevel:
            mapping = config.lookup(profile, level)
            assert mapping.model
            assert mapping.reasoning_effort


@pytest.mark.asyncio
async def test_runtime_capabilities_ephemeral_tasks_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify default and provider advertisement of ephemeral_tasks capability."""
    default_caps = RuntimeCapabilities()
    assert default_caps.ephemeral_tasks is False

    fake_runtime = FakeRuntime()
    assert (await fake_runtime.capabilities()).ephemeral_tasks is True

    install_sdk(monkeypatch, FakeSDK())
    codex_runtime = CodexRuntime()
    await codex_runtime.start()
    assert (await codex_runtime.capabilities()).ephemeral_tasks is True
    await codex_runtime.close()


def test_model_factory_boundary_rejection_without_await() -> None:
    """Verify runtime.model(profile='controlled_agent') fails fast synchronously without await."""
    fake = FakeRuntime()
    with pytest.raises(CapabilityError) as fake_exc:
        fake.model(profile="controlled_agent")
    assert "requires an explicit task lifecycle via runtime.task()" in str(fake_exc.value)
    assert "use 'controlled_turn' for invocation-scoped model execution" in str(fake_exc.value)

    codex = CodexRuntime()
    with pytest.raises(CapabilityError) as codex_exc:
        codex.model(profile="controlled_agent")
    assert "requires an explicit task lifecycle via runtime.task()" in str(codex_exc.value)
    assert "use 'controlled_turn' for invocation-scoped model execution" in str(codex_exc.value)


@pytest.mark.asyncio
async def test_session_factory_boundary_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ephemeral profiles cannot be created as persistent sessions."""
    fake = FakeRuntime()
    with pytest.raises(
        CapabilityError, match="use runtime.task\\(\\) for ephemeral task execution"
    ):
        await fake.session("controlled_agent")
    with pytest.raises(
        CapabilityError, match="use runtime.model\\(\\) for invocation-scoped execution"
    ):
        await fake.session("controlled_turn")

    install_sdk(monkeypatch, FakeSDK())
    codex = CodexRuntime()
    await codex.start()
    with pytest.raises(
        CapabilityError, match="use runtime.task\\(\\) for ephemeral task execution"
    ):
        await codex.session("controlled_agent")
    with pytest.raises(
        CapabilityError, match="use runtime.model\\(\\) for invocation-scoped execution"
    ):
        await codex.session("controlled_turn")
    await codex.close()


@pytest.mark.asyncio
async def test_task_factory_profile_boundary_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify non-runtime or external profiles cannot be created via runtime.task()."""
    registry = ToolRegistry()
    registry.register(_sample_tool)

    fake = FakeRuntime()
    with pytest.raises(CapabilityError, match="has external context; use runtime.model"):
        await fake.task("brain", registry=registry)

    with pytest.raises(CapabilityError, match="has external context; use runtime.model"):
        await fake.task("controlled_turn", registry=registry)

    install_sdk(monkeypatch, FakeSDK())
    codex = CodexRuntime(experimental_dynamic_tools=True)
    await codex.start()
    with pytest.raises(CapabilityError, match="has external context; use runtime.model"):
        await codex.task("brain", registry=registry)

    with pytest.raises(CapabilityError, match="has external context; use runtime.model"):
        await codex.task("controlled_turn", registry=registry)
    await codex.close()


@pytest.mark.asyncio
async def test_task_factory_missing_ephemeral_tasks_capability() -> None:
    """Verify runtime fails fast if ephemeral_tasks capability is disabled."""
    registry = ToolRegistry()
    registry.register(_sample_tool)

    caps_without_tasks = RuntimeCapabilities(
        host_tools=True,
        ephemeral_sessions=True,
        ephemeral_tasks=False,
    )
    fake = FakeRuntime(capabilities=caps_without_tasks)
    with pytest.raises(CapabilityError, match="does not support ephemeral multi-turn tasks"):
        await fake.task("controlled_agent", registry=registry)
