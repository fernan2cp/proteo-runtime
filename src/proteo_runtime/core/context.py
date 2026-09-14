"""Context handling vocabulary."""

from enum import StrEnum


class ContextPolicy(StrEnum):
    """Describe where runtime context is assembled."""

    EXTERNAL = "external"
    RUNTIME = "runtime"
    HYBRID = "hybrid"
    EXPLICIT = "explicit"
