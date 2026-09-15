"""Strict immutable configuration schema version one."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from proteo_runtime.core.context import ContextPolicy
from proteo_runtime.core.errors import ConfigurationError
from proteo_runtime.core.profiles import (
    DEFAULT_PROFILE_SPECS,
    HostToolsMode,
    LifecycleMode,
    LogicalLevel,
    ProfileSpec,
)
from proteo_runtime.core.security import SecurityPolicy


class ModelMapping(BaseModel):
    """Map one logical level to a provider model and effort."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    reasoning_effort: str = Field(min_length=1)


class ProfileConfig(BaseModel):
    """Describe the execution semantics of a user-defined profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lifecycle: LifecycleMode
    context_policy: ContextPolicy
    security_policy: SecurityPolicy
    host_tools: HostToolsMode

    def to_spec(self) -> ProfileSpec:
        """Convert the immutable configuration model to a core profile specification."""

        return ProfileSpec(
            lifecycle=self.lifecycle,
            context=self.context_policy,
            host_tools=self.host_tools,
            security_policy=self.security_policy.value,
        )


class RuntimeConfigV1(BaseModel):
    """Version-one configuration with immutable nested profile mappings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    runtime: str = Field(min_length=1)
    profiles: Mapping[str, Mapping[LogicalLevel, ModelMapping]]
    profile_specs: Mapping[str, ProfileConfig] = Field(default_factory=dict)

    @field_validator("runtime")
    @classmethod
    def validate_runtime(cls, value: str) -> str:
        """Reject providers that are outside the version-one configuration contract."""

        if value not in {"codex", "fake"}:
            raise ValueError("unsupported runtime")
        return value

    @field_validator("profiles")
    @classmethod
    def validate_profiles(
        cls, value: Mapping[str, Mapping[LogicalLevel, ModelMapping]]
    ) -> Mapping[str, Mapping[LogicalLevel, ModelMapping]]:
        """Reject empty profile names and profile mappings."""

        if not value:
            raise ValueError("profiles must not be empty")
        for profile, mapping in value.items():
            if not profile or not mapping:
                raise ValueError("profile names and mappings must not be empty")
        return value

    def model_post_init(self, __context: Any) -> None:
        """Deeply freeze profile mappings after Pydantic validation."""

        frozen_profiles = {
            profile: MappingProxyType(dict(levels)) for profile, levels in self.profiles.items()
        }
        object.__setattr__(self, "profiles", MappingProxyType(frozen_profiles))
        object.__setattr__(self, "profile_specs", MappingProxyType(dict(self.profile_specs)))

        builtin_names = set(DEFAULT_PROFILE_SPECS)
        for profile, spec in self.profile_specs.items():
            if profile in builtin_names:
                raise ValueError(f"profile_specs cannot redefine built-in profile {profile!r}")
            if profile not in self.profiles:
                raise ValueError(f"profile_specs entry {profile!r} has no model mapping")
            if (
                spec.context_policy is ContextPolicy.EXTERNAL
                and spec.lifecycle is not LifecycleMode.EPHEMERAL
            ):
                raise ValueError("external context requires ephemeral lifecycle")
            if (
                spec.context_policy in {ContextPolicy.RUNTIME, ContextPolicy.HYBRID}
                and spec.lifecycle is not LifecycleMode.PERSISTENT
            ):
                raise ValueError("runtime or hybrid context requires persistent lifecycle")
            if spec.lifecycle is LifecycleMode.EXPLICIT:
                raise ValueError("explicit lifecycle is reserved for the native profile")

    def lookup(self, profile: str, level: LogicalLevel | str) -> ModelMapping:
        """Return a mapping or raise a path-aware configuration error."""

        level_name = str(level)
        try:
            profile_mapping = self.profiles[profile]
            return profile_mapping[LogicalLevel(level_name)]
        except (KeyError, ValueError) as exc:
            raise ConfigurationError(
                f"No model mapping for profile {profile!r} at level {level_name!r}",
                path=f"profiles.{profile}.{level_name}",
            ) from exc

    def profile_spec(self, profile: str) -> ProfileSpec:
        """Return a built-in or custom profile specification."""

        try:
            return DEFAULT_PROFILE_SPECS[profile]
        except KeyError:
            try:
                return self.profile_specs[profile].to_spec()
            except KeyError as exc:
                raise ConfigurationError(
                    f"Unknown execution profile {profile!r}", path=f"profiles.{profile}"
                ) from exc
