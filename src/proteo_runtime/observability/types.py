"""Shared observability vocabulary without optional SDK dependencies."""

from proteo_runtime.core.observability import ObservabilityStatus

__all__ = ["ObservabilityStatus", "PayloadMode"]


from enum import StrEnum


class PayloadMode(StrEnum):
    """Payload visibility requested for one observer binding."""

    METADATA_ONLY = "metadata_only"
    REDACTED = "redacted"
    FULL = "full"
    DISABLED = "disabled"
