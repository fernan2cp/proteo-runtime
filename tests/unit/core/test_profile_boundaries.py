"""Unit tests for profile boundary enforcement and custom profile matrix."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from proteo_runtime.config import validate_config
from proteo_runtime.core.context import ContextPolicy
from proteo_runtime.core.errors import CapabilityError, ConfigurationError
from proteo_runtime.core.profiles import (
    HostToolsMode,
    LifecycleMode,
    ProfileSpec,
    validate_model_profile,
    validate_session_profile,
    validate_task_profile,
)
from proteo_runtime.core.security import SecurityPolicy
from proteo_runtime.providers.codex.runtime import CodexRuntime
from proteo_runtime.testing.fakes import FakeRuntime
from proteo_runtime.tools import ToolRegistry, runtime_tool

_unit_dir = str(Path(__file__).resolve().parent.parent)
if _unit_dir not in sys.path:
    sys.path.insert(0, _unit_dir)

from test_codex_provider import FakeSDK, install_sdk  # noqa: E402


@runtime_tool(name="boundary_tool", description="Boundary test tool.", permission="test.boundary")
async def _boundary_tool(arg: str) -> str:
    """Return the input argument.

    Args:
        arg: String input.

    Returns:
        The same string.
    """
    return arg


def _make_registry() -> ToolRegistry:
    """Create a non-empty tool registry for task tests.

    Returns:
        A ToolRegistry containing one tool.
    """
    registry = ToolRegistry()
    registry.register(_boundary_tool)
    return registry


def test_profile_spec_normalization_and_validation() -> None:
    """Verify ProfileSpec normalizes string arguments and rejects unknown policies."""
    spec = ProfileSpec(
        lifecycle="ephemeral",  # type: ignore[arg-type]
        context="runtime",  # type: ignore[arg-type]
        host_tools="controlled",  # type: ignore[arg-type]
        security_policy="controlled_tools",  # type: ignore[arg-type]
    )
    assert spec.lifecycle is LifecycleMode.EPHEMERAL
    assert spec.context is ContextPolicy.RUNTIME
    assert spec.host_tools is HostToolsMode.CONTROLLED
    assert spec.security_policy is SecurityPolicy.CONTROLLED_TOOLS

    with pytest.raises(ValueError, match="Unknown lifecycle mode"):
        ProfileSpec(
            lifecycle="invalid",  # type: ignore[arg-type]
            context=ContextPolicy.EXTERNAL,
            host_tools=HostToolsMode.DISABLED,
            security_policy=SecurityPolicy.ISOLATED,
        )

    with pytest.raises(ValueError, match="Unknown context policy"):
        ProfileSpec(
            lifecycle=LifecycleMode.EPHEMERAL,
            context="invalid",  # type: ignore[arg-type]
            host_tools=HostToolsMode.DISABLED,
            security_policy=SecurityPolicy.ISOLATED,
        )

    with pytest.raises(ValueError, match="Unknown host tools mode"):
        ProfileSpec(
            lifecycle=LifecycleMode.EPHEMERAL,
            context=ContextPolicy.EXTERNAL,
            host_tools="invalid",  # type: ignore[arg-type]
            security_policy=SecurityPolicy.ISOLATED,
        )

    with pytest.raises(ValueError, match="Unknown security policy"):
        ProfileSpec(
            lifecycle=LifecycleMode.EPHEMERAL,
            context=ContextPolicy.EXTERNAL,
            host_tools=HostToolsMode.DISABLED,
            security_policy="invalid",  # type: ignore[arg-type]
        )


def test_config_rejects_explicit_context_in_custom_profiles() -> None:
    """Verify RuntimeConfigV1 rejects custom profiles configured with explicit context."""
    raw_config: dict[str, Any] = {
        "schema_version": 1,
        "runtime": "codex",
        "profiles": {
            "custom_explicit": {
                "low": {"model": "gpt-5.6-luna", "reasoning_effort": "low"},
                "medium": {"model": "gpt-5.6-luna", "reasoning_effort": "high"},
                "high": {"model": "gpt-5.6-sol", "reasoning_effort": "low"},
                "ultra": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
            }
        },
        "profile_specs": {
            "custom_explicit": {
                "lifecycle": "ephemeral",
                "context_policy": "explicit",
                "security_policy": "isolated",
                "host_tools": "disabled",
            }
        },
    }
    with pytest.raises(
        ConfigurationError, match="explicit context is reserved for the native profile"
    ):
        validate_config(raw_config)


def test_direct_validators_exact_boundaries() -> None:
    """Verify validate_model_profile, validate_task_profile, and validate_session_profile directly."""
    # Model profile validator: only EPHEMERAL + EXTERNAL allowed
    m_valid = ProfileSpec(
        LifecycleMode.EPHEMERAL,
        ContextPolicy.EXTERNAL,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    )
    validate_model_profile(m_valid, "m_valid")

    m_persistent = ProfileSpec(
        LifecycleMode.PERSISTENT,
        ContextPolicy.RUNTIME,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    )
    with pytest.raises(CapabilityError, match="is persistent; use runtime.session\\(\\)"):
        validate_model_profile(m_persistent, "m_persistent")

    m_task = ProfileSpec(
        LifecycleMode.EPHEMERAL,
        ContextPolicy.RUNTIME,
        HostToolsMode.CONTROLLED,
        SecurityPolicy.CONTROLLED_TOOLS,
    )
    with pytest.raises(
        CapabilityError, match="requires an explicit task lifecycle via runtime.task\\(\\)"
    ):
        validate_model_profile(m_task, "m_task")

    m_native = ProfileSpec(
        LifecycleMode.EXPLICIT,
        ContextPolicy.EXPLICIT,
        HostToolsMode.PROVIDER_DEFINED,
        SecurityPolicy.NATIVE,
    )
    with pytest.raises(CapabilityError, match="requires explicit provider-native execution"):
        validate_model_profile(m_native, "native")

    m_explicit_ctx = ProfileSpec(
        LifecycleMode.EPHEMERAL,
        ContextPolicy.EXPLICIT,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    )
    with pytest.raises(
        CapabilityError, match="models require EPHEMERAL lifecycle and EXTERNAL context"
    ):
        validate_model_profile(m_explicit_ctx, "m_explicit_ctx")

    # Task profile validator: only EPHEMERAL + RUNTIME allowed
    t_valid = ProfileSpec(
        LifecycleMode.EPHEMERAL,
        ContextPolicy.RUNTIME,
        HostToolsMode.CONTROLLED,
        SecurityPolicy.CONTROLLED_TOOLS,
    )
    validate_task_profile(t_valid, "t_valid")

    t_persistent = ProfileSpec(
        LifecycleMode.PERSISTENT,
        ContextPolicy.RUNTIME,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    )
    with pytest.raises(CapabilityError, match="is persistent; use runtime.session\\(\\)"):
        validate_task_profile(t_persistent, "t_persistent")

    t_external = ProfileSpec(
        LifecycleMode.EPHEMERAL,
        ContextPolicy.EXTERNAL,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    )
    with pytest.raises(CapabilityError, match="has external context; use runtime.model\\(\\)"):
        validate_task_profile(t_external, "t_external")

    t_explicit = ProfileSpec(
        LifecycleMode.EPHEMERAL,
        ContextPolicy.EXPLICIT,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    )
    with pytest.raises(
        CapabilityError, match="tasks require EPHEMERAL lifecycle and RUNTIME context"
    ):
        validate_task_profile(t_explicit, "t_explicit")

    # Session profile validator: PERSISTENT and non-EXTERNAL context
    s_valid_rt = ProfileSpec(
        LifecycleMode.PERSISTENT,
        ContextPolicy.RUNTIME,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    )
    validate_session_profile(s_valid_rt, "s_valid_rt")

    s_valid_hy = ProfileSpec(
        LifecycleMode.PERSISTENT,
        ContextPolicy.HYBRID,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    )
    validate_session_profile(s_valid_hy, "s_valid_hy")

    s_ephemeral_rt = ProfileSpec(
        LifecycleMode.EPHEMERAL,
        ContextPolicy.RUNTIME,
        HostToolsMode.CONTROLLED,
        SecurityPolicy.CONTROLLED_TOOLS,
    )
    with pytest.raises(
        CapabilityError, match="use runtime.task\\(\\) for ephemeral task execution"
    ):
        validate_session_profile(s_ephemeral_rt, "s_ephemeral_rt")

    s_ephemeral_ext = ProfileSpec(
        LifecycleMode.EPHEMERAL,
        ContextPolicy.EXTERNAL,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    )
    with pytest.raises(
        CapabilityError, match="use runtime.model\\(\\) for invocation-scoped execution"
    ):
        validate_session_profile(s_ephemeral_ext, "s_ephemeral_ext")

    s_ephemeral_exp = ProfileSpec(
        LifecycleMode.EPHEMERAL,
        ContextPolicy.EXPLICIT,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    )
    with pytest.raises(CapabilityError, match="sessions require PERSISTENT lifecycle"):
        validate_session_profile(s_ephemeral_exp, "s_ephemeral_exp")

    s_persistent_ext = ProfileSpec(
        LifecycleMode.PERSISTENT,
        ContextPolicy.EXTERNAL,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    )
    with pytest.raises(
        CapabilityError, match="external context is incompatible with persistent sessions"
    ):
        validate_session_profile(s_persistent_ext, "s_persistent_ext")


# Mandatory custom profile combination matrix specifications
MATRIX_SPECS: Mapping[str, ProfileSpec] = {
    "ephemeral_external": ProfileSpec(
        LifecycleMode.EPHEMERAL,
        ContextPolicy.EXTERNAL,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    ),
    "ephemeral_runtime": ProfileSpec(
        LifecycleMode.EPHEMERAL,
        ContextPolicy.RUNTIME,
        HostToolsMode.CONTROLLED,
        SecurityPolicy.CONTROLLED_TOOLS,
    ),
    "ephemeral_explicit": ProfileSpec(
        LifecycleMode.EPHEMERAL,
        ContextPolicy.EXPLICIT,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    ),
    "persistent_runtime": ProfileSpec(
        LifecycleMode.PERSISTENT,
        ContextPolicy.RUNTIME,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    ),
    "persistent_hybrid": ProfileSpec(
        LifecycleMode.PERSISTENT,
        ContextPolicy.HYBRID,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    ),
    "persistent_external": ProfileSpec(
        LifecycleMode.PERSISTENT,
        ContextPolicy.EXTERNAL,
        HostToolsMode.DISABLED,
        SecurityPolicy.ISOLATED,
    ),
}


@pytest.mark.asyncio
async def test_fake_runtime_custom_profiles_matrix() -> None:
    """Verify FakeRuntime accepts and rejects the custom profile matrix across all factories."""
    registry = _make_registry()
    fake = FakeRuntime(custom_profiles=MATRIX_SPECS)
    await fake.start()

    # 1. ephemeral_external: model() ACCEPT, task() REJECT, session() REJECT
    model = fake.model(profile="ephemeral_external")
    assert model.profile == "ephemeral_external"

    with pytest.raises(CapabilityError, match="has external context; use runtime.model"):
        await fake.task("ephemeral_external", registry=registry)

    with pytest.raises(
        CapabilityError, match="use runtime.model\\(\\) for invocation-scoped execution"
    ):
        await fake.session("ephemeral_external")

    # 2. ephemeral_runtime: model() REJECT, task() ACCEPT, session() REJECT
    with pytest.raises(
        CapabilityError, match="requires an explicit task lifecycle via runtime.task"
    ):
        fake.model(profile="ephemeral_runtime")

    task = await fake.task("ephemeral_runtime", registry=registry)
    assert task.id.startswith("task_")
    assert task.state.value == "open"
    await task.close()

    with pytest.raises(
        CapabilityError, match="use runtime.task\\(\\) for ephemeral task execution"
    ):
        await fake.session("ephemeral_runtime")

    # 3. ephemeral_explicit: model() REJECT, task() REJECT, session() REJECT
    with pytest.raises(
        CapabilityError, match="models require EPHEMERAL lifecycle and EXTERNAL context"
    ):
        fake.model(profile="ephemeral_explicit")

    with pytest.raises(
        CapabilityError, match="tasks require EPHEMERAL lifecycle and RUNTIME context"
    ):
        await fake.task("ephemeral_explicit", registry=registry)

    with pytest.raises(CapabilityError, match="sessions require PERSISTENT lifecycle"):
        await fake.session("ephemeral_explicit")

    # 4. persistent_runtime: model() REJECT, task() REJECT, session() ACCEPT
    with pytest.raises(CapabilityError, match="is persistent; use runtime.session"):
        fake.model(profile="persistent_runtime")

    with pytest.raises(CapabilityError, match="is persistent; use runtime.session"):
        await fake.task("persistent_runtime", registry=registry)

    session = await fake.session("persistent_runtime")
    assert session.descriptor
    await session.close()

    # 5. persistent_hybrid: model() REJECT, task() REJECT, session() ACCEPT
    with pytest.raises(CapabilityError, match="is persistent; use runtime.session"):
        fake.model(profile="persistent_hybrid")

    with pytest.raises(CapabilityError, match="is persistent; use runtime.session"):
        await fake.task("persistent_hybrid", registry=registry)

    session_hy = await fake.session("persistent_hybrid")
    assert session_hy.descriptor
    await session_hy.close()

    # 6. persistent_external: model() REJECT, task() REJECT, session() REJECT
    with pytest.raises(CapabilityError, match="is persistent; use runtime.session"):
        fake.model(profile="persistent_external")

    with pytest.raises(CapabilityError, match="is persistent; use runtime.session"):
        await fake.task("persistent_external", registry=registry)

    with pytest.raises(
        CapabilityError, match="external context is incompatible with persistent sessions"
    ):
        await fake.session("persistent_external")

    await fake.close()


@pytest.mark.asyncio
async def test_codex_runtime_custom_profiles_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify CodexRuntime accepts and rejects the custom profile matrix across all factories."""
    install_sdk(monkeypatch, FakeSDK())
    registry = _make_registry()
    codex = CodexRuntime(experimental_dynamic_tools=True)
    await codex.start()

    monkeypatch.setattr(codex, "_profile_spec", lambda p: MATRIX_SPECS[p])
    monkeypatch.setattr(
        codex,
        "_resolve_binding",
        lambda profile, level, config: type("_B", (), {"model": "mock-model", "effort": "low"})(),
    )

    # 1. ephemeral_external: model() ACCEPT, task() REJECT, session() REJECT
    model = codex.model(profile="ephemeral_external")
    assert model is not None

    with pytest.raises(CapabilityError, match="has external context; use runtime.model"):
        await codex.task("ephemeral_external", registry=registry)

    with pytest.raises(
        CapabilityError, match="use runtime.model\\(\\) for invocation-scoped execution"
    ):
        await codex.session("ephemeral_external")

    # 2. ephemeral_runtime: model() REJECT, task() ACCEPT, session() REJECT
    with pytest.raises(
        CapabilityError, match="requires an explicit task lifecycle via runtime.task"
    ):
        codex.model(profile="ephemeral_runtime")

    task = await codex.task("ephemeral_runtime", registry=registry)
    assert task.id.startswith("task_")
    assert task.state.value == "open"
    await task.close()

    with pytest.raises(
        CapabilityError, match="use runtime.task\\(\\) for ephemeral task execution"
    ):
        await codex.session("ephemeral_runtime")

    # 3. ephemeral_explicit: model() REJECT, task() REJECT, session() REJECT
    with pytest.raises(
        CapabilityError, match="models require EPHEMERAL lifecycle and EXTERNAL context"
    ):
        codex.model(profile="ephemeral_explicit")

    with pytest.raises(
        CapabilityError, match="tasks require EPHEMERAL lifecycle and RUNTIME context"
    ):
        await codex.task("ephemeral_explicit", registry=registry)

    with pytest.raises(CapabilityError, match="sessions require PERSISTENT lifecycle"):
        await codex.session("ephemeral_explicit")

    # 4. persistent_runtime: model() REJECT, task() REJECT, session() ACCEPT
    with pytest.raises(CapabilityError, match="is persistent; use runtime.session"):
        codex.model(profile="persistent_runtime")

    with pytest.raises(CapabilityError, match="is persistent; use runtime.session"):
        await codex.task("persistent_runtime", registry=registry)

    session = await codex.session("persistent_runtime")
    assert session.descriptor
    await session.close()

    # 5. persistent_hybrid: model() REJECT, task() REJECT, session() ACCEPT
    with pytest.raises(CapabilityError, match="is persistent; use runtime.session"):
        codex.model(profile="persistent_hybrid")

    with pytest.raises(CapabilityError, match="is persistent; use runtime.session"):
        await codex.task("persistent_hybrid", registry=registry)

    session_hy = await codex.session("persistent_hybrid")
    assert session_hy.descriptor
    await session_hy.close()

    # 6. persistent_external: model() REJECT, task() REJECT, session() REJECT
    with pytest.raises(CapabilityError, match="is persistent; use runtime.session"):
        codex.model(profile="persistent_external")

    with pytest.raises(CapabilityError, match="is persistent; use runtime.session"):
        await codex.task("persistent_external", registry=registry)

    with pytest.raises(
        CapabilityError, match="external context is incompatible with persistent sessions"
    ):
        await codex.session("persistent_external")

    await codex.close()


def test_runtime_config_v1_profile_validation_edge_cases() -> None:
    """Verify edge cases in RuntimeConfigV1 profile and spec validation."""
    from proteo_runtime.config import RuntimeConfigV1
    from proteo_runtime.config.models import ModelMapping, ProfileConfig
    from proteo_runtime.core.profiles import LogicalLevel

    valid_mapping = {
        "brain": {
            LogicalLevel.MEDIUM: ModelMapping(model="gpt-4o", reasoning_effort="medium"),
        }
    }

    # 1. Empty profile name or empty mapping raises ValueError
    with pytest.raises(ValueError, match="profile names and mappings must not be empty"):
        RuntimeConfigV1(
            runtime="codex",
            profiles={
                "": {LogicalLevel.MEDIUM: ModelMapping(model="gpt-4o", reasoning_effort="medium")}
            },
        )

    with pytest.raises(ValueError, match="profile names and mappings must not be empty"):
        RuntimeConfigV1(runtime="codex", profiles={"custom": {}})

    # 2. Redefining built-in profile in profile_specs raises ValueError
    with pytest.raises(ValueError, match="profile_specs cannot redefine built-in profile 'brain'"):
        RuntimeConfigV1(
            runtime="codex",
            profiles=valid_mapping,
            profile_specs={
                "brain": ProfileConfig(
                    lifecycle=LifecycleMode.EPHEMERAL,
                    context_policy=ContextPolicy.EXTERNAL,
                    host_tools=HostToolsMode.DISABLED,
                    security_policy=SecurityPolicy.ISOLATED,
                )
            },
        )

    # 3. Spec without model mapping raises ConfigurationError
    with pytest.raises(ConfigurationError, match="Profile spec 'custom' has no model mapping"):
        RuntimeConfigV1(
            runtime="codex",
            profiles=valid_mapping,
            profile_specs={
                "custom": ProfileConfig(
                    lifecycle=LifecycleMode.EPHEMERAL,
                    context_policy=ContextPolicy.RUNTIME,
                    host_tools=HostToolsMode.DISABLED,
                    security_policy=SecurityPolicy.ISOLATED,
                )
            },
        )

    # 4. Explicit lifecycle in custom spec raises ConfigurationError
    with pytest.raises(
        ConfigurationError, match="explicit lifecycle is reserved for the native profile"
    ):
        RuntimeConfigV1(
            runtime="codex",
            profiles={
                "brain": {
                    LogicalLevel.MEDIUM: ModelMapping(model="gpt-4o", reasoning_effort="medium")
                },
                "custom": {
                    LogicalLevel.MEDIUM: ModelMapping(model="gpt-4o", reasoning_effort="medium")
                },
            },
            profile_specs={
                "custom": ProfileConfig(
                    lifecycle=LifecycleMode.EXPLICIT,
                    context_policy=ContextPolicy.RUNTIME,
                    host_tools=HostToolsMode.DISABLED,
                    security_policy=SecurityPolicy.ISOLATED,
                )
            },
        )

    # 5. profile_spec lookup on unknown profile raises ConfigurationError
    cfg = RuntimeConfigV1(runtime="codex", profiles=valid_mapping)
    with pytest.raises(ConfigurationError, match="Unknown execution profile 'nonexistent'"):
        cfg.profile_spec("nonexistent")
