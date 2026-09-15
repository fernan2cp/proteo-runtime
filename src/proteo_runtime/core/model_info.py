"""Model metadata contract."""

from dataclasses import dataclass

from .capabilities import RuntimeCapabilities


@dataclass(frozen=True, slots=True, init=False)
class ModelInfo:
    """Immutable public information about one model."""

    identifier: str
    display_name: str
    supported_reasoning_efforts: tuple[str, ...]
    capabilities: RuntimeCapabilities
    is_default: bool
    description: str | None

    def __init__(
        self,
        identifier: str | None = None,
        display_name: str | None = None,
        supported_reasoning_efforts: tuple[str, ...] = (),
        capabilities: RuntimeCapabilities | None = None,
        *,
        id: str | None = None,
        name: str | None = None,
        is_default: bool = False,
        description: str | None = None,
    ) -> None:
        """Initialize metadata from legacy or provider-facing keyword names."""

        selected = identifier or id
        selected_display = display_name or name
        if not selected or not selected_display:
            raise ValueError("Model identifier and display name are required")
        object.__setattr__(self, "identifier", selected)
        object.__setattr__(self, "display_name", selected_display)
        object.__setattr__(self, "supported_reasoning_efforts", tuple(supported_reasoning_efforts))
        object.__setattr__(self, "capabilities", capabilities or RuntimeCapabilities())
        object.__setattr__(self, "is_default", is_default)
        object.__setattr__(self, "description", description)

    @property
    def id(self) -> str:
        """Return the stable identifier under provider-facing terminology."""

        return self.identifier

    @property
    def name(self) -> str:
        """Return the stable identifier as a model name."""

        return self.identifier
