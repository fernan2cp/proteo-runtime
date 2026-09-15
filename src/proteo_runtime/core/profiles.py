"""Execution profiles and their safe defaults."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from .context import ContextPolicy
from .security import SecurityPolicy


class ExecutionProfile(StrEnum):
    """Initial provider-neutral execution profiles."""

    BRAIN = "brain"
    STRUCTURED = "structured"
    SESSION = "session"
    CONTROLLED_AGENT = "controlled_agent"
    NATIVE = "native"


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

        policy = self.security_policy
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
        ExecutionProfile.CONTROLLED_AGENT.value: ProfileSpec(
            LifecycleMode.EPHEMERAL,
            ContextPolicy.EXTERNAL,
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
