"""Execution profiles and their safe defaults."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal

from .context import ContextPolicy
from .security import SecurityPolicy


class ExecutionProfile(StrEnum):
    """Initial provider-neutral execution profiles."""

    BRAIN = "brain"
    STRUCTURED = "structured"
    SESSION = "session"
    CONTROLLED_TURN = "controlled_turn"
    CONTROLLED_AGENT = "controlled_agent"
    NATIVE = "native"


ExecutionProfileName = Literal[
    "brain",
    "structured",
    "session",
    "controlled_turn",
    "controlled_agent",
    "native",
]


class LogicalLevel(StrEnum):
    """Provider-neutral reasoning effort levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    ULTRA = "ultra"


class LifecycleMode(StrEnum):
    """Describe whether a profile is ephemeral or persistent."""

    EPHEMERAL = "ephemeral"
    PERSISTENT = "persistent"
    EXPLICIT = "explicit"


class HostToolsMode(StrEnum):
    """Describe host-tool permissions for a profile."""

    DISABLED = "disabled"
    CONTROLLED = "controlled"
    EXPLICIT = "explicit"
    PROVIDER_DEFINED = "provider_defined"


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    """Immutable safe defaults for one execution profile."""

    lifecycle: LifecycleMode
    context: ContextPolicy
    host_tools: HostToolsMode
    security_policy: SecurityPolicy

    def __post_init__(self) -> None:
        """Normalize compatible policy strings and reject unknown policies."""

        lifecycle: Any = self.lifecycle
        if not isinstance(lifecycle, LifecycleMode):
            try:
                lifecycle = LifecycleMode(lifecycle)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Unknown lifecycle mode: {lifecycle!r}") from exc
            object.__setattr__(self, "lifecycle", lifecycle)

        context: Any = self.context
        if not isinstance(context, ContextPolicy):
            try:
                context = ContextPolicy(context)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Unknown context policy: {context!r}") from exc
            object.__setattr__(self, "context", context)

        host_tools: Any = self.host_tools
        if not isinstance(host_tools, HostToolsMode):
            try:
                host_tools = HostToolsMode(host_tools)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Unknown host tools mode: {host_tools!r}") from exc
            object.__setattr__(self, "host_tools", host_tools)

        policy: Any = self.security_policy
        if not isinstance(policy, SecurityPolicy):
            try:
                policy = SecurityPolicy(policy)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Unknown security policy: {policy!r}") from exc
            object.__setattr__(self, "security_policy", policy)

    @property
    def persistent(self) -> bool:
        """Return whether this profile has persistent lifecycle semantics."""

        return self.lifecycle is LifecycleMode.PERSISTENT


DEFAULT_PROFILE_SPECS = MappingProxyType(
    {
        ExecutionProfile.BRAIN.value: ProfileSpec(
            LifecycleMode.EPHEMERAL,
            ContextPolicy.EXTERNAL,
            HostToolsMode.DISABLED,
            SecurityPolicy.ISOLATED,
        ),
        ExecutionProfile.STRUCTURED.value: ProfileSpec(
            LifecycleMode.EPHEMERAL,
            ContextPolicy.EXTERNAL,
            HostToolsMode.DISABLED,
            SecurityPolicy.ISOLATED,
        ),
        ExecutionProfile.SESSION.value: ProfileSpec(
            LifecycleMode.PERSISTENT,
            ContextPolicy.RUNTIME,
            HostToolsMode.DISABLED,
            SecurityPolicy.ISOLATED,
        ),
        ExecutionProfile.CONTROLLED_TURN.value: ProfileSpec(
            LifecycleMode.EPHEMERAL,
            ContextPolicy.EXTERNAL,
            HostToolsMode.CONTROLLED,
            SecurityPolicy.CONTROLLED_TOOLS,
        ),
        ExecutionProfile.CONTROLLED_AGENT.value: ProfileSpec(
            LifecycleMode.EPHEMERAL,
            ContextPolicy.RUNTIME,
            HostToolsMode.CONTROLLED,
            SecurityPolicy.CONTROLLED_TOOLS,
        ),
        ExecutionProfile.NATIVE.value: ProfileSpec(
            LifecycleMode.EXPLICIT,
            ContextPolicy.EXPLICIT,
            HostToolsMode.PROVIDER_DEFINED,
            SecurityPolicy.NATIVE,
        ),
    }
)


def profile_spec(profile: str | ExecutionProfile) -> ProfileSpec:
    """Look up a built-in execution profile or raise a capability error."""

    from .errors import CapabilityError

    name = str(profile)
    try:
        return DEFAULT_PROFILE_SPECS[name]
    except KeyError as exc:
        raise CapabilityError(f"Unknown execution profile: {name}") from exc


def validate_model_profile(spec: ProfileSpec, profile: str) -> None:
    """Validate that a profile specification satisfies model factory boundaries.

    RuntimeModel requires EPHEMERAL lifecycle and EXTERNAL context.

    Args:
        spec: The resolved profile specification.
        profile: Profile name for diagnostic messages.

    Raises:
        CapabilityError: If the profile is incompatible with runtime.model().
    """
    from .errors import CapabilityError

    if spec.lifecycle is LifecycleMode.EPHEMERAL and spec.context is ContextPolicy.EXTERNAL:
        return

    if profile == ExecutionProfile.NATIVE.value or spec.security_policy is SecurityPolicy.NATIVE:
        raise CapabilityError(
            f"Profile '{profile}' requires explicit provider-native execution; "
            f"native profiles are not supported via standard runtime.model() invocations."
        )

    if spec.persistent or spec.lifecycle is LifecycleMode.PERSISTENT:
        raise CapabilityError(
            f"Profile '{profile}' is persistent; use runtime.session() for durable sessions."
        )
    if spec.context is ContextPolicy.RUNTIME and spec.lifecycle is LifecycleMode.EPHEMERAL:
        raise CapabilityError(
            f"Profile '{profile}' has runtime context and requires an explicit task lifecycle "
            f"via runtime.task(); use 'controlled_turn' for invocation-scoped model execution."
        )
    raise CapabilityError(
        f"Profile '{profile}' (lifecycle={spec.lifecycle.value}, context={spec.context.value}) "
        f"is incompatible with runtime.model(); models require EPHEMERAL lifecycle and EXTERNAL context."
    )


def validate_task_profile(spec: ProfileSpec, profile: str) -> None:
    """Validate that a profile specification satisfies task factory boundaries.

    RuntimeTask requires EPHEMERAL lifecycle and RUNTIME context.

    Args:
        spec: The resolved profile specification.
        profile: Profile name for diagnostic messages.

    Raises:
        CapabilityError: If the profile is incompatible with runtime.task().
    """
    from .errors import CapabilityError

    if spec.lifecycle is LifecycleMode.EPHEMERAL and spec.context is ContextPolicy.RUNTIME:
        return

    if spec.persistent or spec.lifecycle is LifecycleMode.PERSISTENT:
        raise CapabilityError(
            f"Profile '{profile}' is persistent; use runtime.session() for durable sessions"
        )
    if spec.context is ContextPolicy.EXTERNAL:
        raise CapabilityError(
            f"Profile '{profile}' has external context; use runtime.model() for invocation-scoped execution"
        )
    raise CapabilityError(
        f"Profile '{profile}' (lifecycle={spec.lifecycle.value}, context={spec.context.value}) "
        f"is incompatible with runtime.task(); tasks require EPHEMERAL lifecycle and RUNTIME context."
    )


def validate_session_profile(spec: ProfileSpec, profile: str) -> None:
    """Validate that a profile specification satisfies session factory boundaries.

    RuntimeSession requires PERSISTENT lifecycle and non-EXTERNAL context.

    Args:
        spec: The resolved profile specification.
        profile: Profile name for diagnostic messages.

    Raises:
        CapabilityError: If the profile is incompatible with runtime.session().
    """
    from .errors import CapabilityError

    if spec.lifecycle is LifecycleMode.EPHEMERAL:
        if spec.context is ContextPolicy.RUNTIME:
            raise CapabilityError(
                f"Profile '{profile}' is ephemeral; use runtime.task() for ephemeral task execution"
            )
        if spec.context is ContextPolicy.EXTERNAL:
            raise CapabilityError(
                f"Profile '{profile}' is ephemeral and external; use runtime.model() for invocation-scoped execution"
            )
        raise CapabilityError(
            f"Profile '{profile}' (lifecycle={spec.lifecycle.value}, context={spec.context.value}) "
            f"is incompatible with runtime.session(); sessions require PERSISTENT lifecycle."
        )

    if not spec.persistent or spec.lifecycle is not LifecycleMode.PERSISTENT:
        raise CapabilityError(
            f"Profile '{profile}' (lifecycle={spec.lifecycle.value}) is incompatible with runtime.session(); "
            f"sessions require PERSISTENT lifecycle."
        )

    if spec.context is ContextPolicy.EXTERNAL:
        raise CapabilityError(
            f"Profile '{profile}' has external context; external context is incompatible with persistent sessions "
            f"in runtime.session(). Use runtime.model() for invocation-scoped execution."
        )
