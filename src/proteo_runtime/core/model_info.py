"""Model metadata contract."""

from dataclasses import dataclass

from .capabilities import RuntimeCapabilities


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Immutable public information about one model."""

    identifier: str
    display_name: str
    supported_reasoning_efforts: tuple[str, ...]
    capabilities: RuntimeCapabilities

    def __post_init__(self) -> None:
        """Normalize supported effort names and validate identity text."""

        if not self.identifier or not self.display_name:
            raise ValueError("Model identifier and display name are required")
        object.__setattr__(
            self, "supported_reasoning_efforts", tuple(self.supported_reasoning_efforts)
        )
