"""Usage accounting value objects."""

from dataclasses import dataclass, field
from typing import Any

from .types import freeze_mapping


@dataclass(frozen=True, slots=True)
class RuntimeUsage:
    """Immutable token, timing, and operation usage counters."""

    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    duration_ms: float | None = None
    turn_count: int = 1
    tool_call_count: int = 0
    retry_count: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate non-negative counters and freeze the raw payload."""

        for name in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
            "duration_ms",
            "turn_count",
            "tool_call_count",
            "retry_count",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")
        object.__setattr__(self, "raw", freeze_mapping(self.raw))
