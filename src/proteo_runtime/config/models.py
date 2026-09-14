"""Strict immutable configuration schema version one."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from proteo_runtime.core.errors import ConfigurationError
from proteo_runtime.core.profiles import LogicalLevel


class ModelMapping(BaseModel):
    """Map one logical level to a provider model and effort."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    reasoning_effort: str = Field(min_length=1)


class RuntimeConfigV1(BaseModel):
    """Version-one configuration with immutable nested profile mappings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    runtime: str = Field(min_length=1)
    profiles: Mapping[str, Mapping[LogicalLevel, ModelMapping]]

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
