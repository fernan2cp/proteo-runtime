"""Runtime identity value objects."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .types import freeze_mapping


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    """Stable, non-secret identity for a runtime provider."""

    provider: str
    fingerprint: str
    label: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate identity text and freeze safe metadata."""

        if not self.provider or not self.fingerprint:
            raise ValueError("provider and fingerprint are required")
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))
