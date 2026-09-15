"""Provider-neutral observability enums shared by runtime contracts."""

from enum import StrEnum


class ObservabilityStatus(StrEnum):
    """Health state reported by the configured observability pipeline."""

    DISABLED = "disabled"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
